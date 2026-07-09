"""Pure v2 logic: vector packing, similarity, the relevance+recency blend,
and the supersede decision (tiered gate + prompt + lenient parse).

No DB, no network — everything here is deterministic and unit-testable.
Thresholds follow the industry survey (docs/research/INDUSTRY_PRACTICES.md):
conservative per financial-services dedup guidance; calibrate on the real
embedder before loosening.
"""

from __future__ import annotations

import json
import math
import re
import struct
from datetime import datetime, timezone

# --- tiered-gate thresholds (cosine similarity) ----------------------------
# Live calibration note: absolute cosine values vary by embedder — the live
# run showed real-phrasing contradictions can land below a hand-picked band.
# Rule: when a decider is available, anything >= T_DECIDE_FLOOR goes to the
# LLM to adjudicate (its prompt handles "unrelated -> ADD"); hard thresholds
# only gate the NO-decider paths, where they stay conservative.
T_SAME = 0.95          # >= : same fact (no-decider path drops as duplicate)
T_BAND_LOW = 0.70      # legacy band low (still the no-decider ADD boundary)
T_DECIDE_FLOOR = 0.50  # decider path: below this, skip the LLM, plain ADD
MIN_RECALL_SIM = 0.35  # injection floor: below this, relevance rung ignores it

# --- blend weights ----------------------------------------------------------
W_SIM = 0.7
W_RECENCY = 0.3
RECENCY_HALF_LIFE_DAYS = 30.0


# --- packing (LargeBinary rung: packed float32) ------------------------------
def pack_vector(vec: "list[float]") -> bytes:
    return struct.pack(f"<{len(vec)}f", *vec)


def unpack_vector(blob: bytes) -> "list[float]":
    n = len(blob) // 4
    return list(struct.unpack(f"<{n}f", blob))


def to_vector(value) -> "list[float] | None":
    """Normalize a stored embedding (pgvector value, packed bytes, or None)."""
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray)):
        return unpack_vector(bytes(value))
    return list(value)


# --- similarity ---------------------------------------------------------------
def cosine(a: "list[float]", b: "list[float]") -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = na = nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / math.sqrt(na * nb)


def blend_score(similarity: float, created_at: "datetime | None", now: "datetime | None" = None) -> float:
    now = now or datetime.now(timezone.utc)
    if created_at is None:
        age_days = 365.0
    else:
        ca = created_at if created_at.tzinfo else created_at.replace(tzinfo=timezone.utc)
        age_days = max(0.0, (now - ca).total_seconds() / 86400.0)
    return W_SIM * similarity + W_RECENCY * math.exp(-age_days / RECENCY_HALF_LIFE_DAYS)


def select_for_recall(entries, query_vec, limit: int, recency_floor: int = 4):
    """entries: MemoryEntry-likes with .embedding/.created_at, any order.
    Returns up to `limit` entries: newest `recency_floor` always in (recency
    floor, similarity-exempt), the rest ranked by blended score with the
    MIN_RECALL_SIM floor applied to the relevance rung. Falls back to pure
    recency when query_vec is None or nothing is embedded."""
    by_recency = sorted(entries, key=lambda e: e.created_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    if query_vec is None:
        return by_recency[:limit]
    floor_set = by_recency[:recency_floor]
    floor_ids = {e.id for e in floor_set}
    scored = []
    for e in entries:
        if e.id in floor_ids:
            continue
        vec = to_vector(getattr(e, "embedding", None))
        if vec is None:
            continue
        sim = cosine(query_vec, vec)
        if sim < MIN_RECALL_SIM:
            continue
        scored.append((blend_score(sim, e.created_at), e))
    scored.sort(key=lambda t: t[0], reverse=True)
    picked = floor_set + [e for _, e in scored]
    seen, out = set(), []
    for e in picked:
        if e.id not in seen:
            seen.add(e.id)
            out.append(e)
        if len(out) >= limit:
            break
    return out


# --- supersede decision (the 0.70–0.95 band) ---------------------------------
DECISION_PROMPT = """You maintain a user-memory store. A new fact arrived; below are existing
memories similar to it, numbered 0..{n_max}. Decide ONE action:

- ADD: the new fact is genuinely new information (none of the existing memories cover it).
- SUPERSEDE <number>: the new fact updates/replaces that existing memory
  (same subject, information changed or strictly richer).
- NONE: the new fact conveys nothing beyond an existing memory.

Rules: same meaning, different words = NONE. Changed preference/state = SUPERSEDE
the old one. Only pick a number from the list.

EXISTING:
{existing}

NEW FACT:
{fact}

Reply with ONLY one line: ADD | SUPERSEDE <number> | NONE"""


def render_decision_prompt(fact: str, candidates: "list[str]") -> str:
    existing = "\n".join(f"{i}: {c}" for i, c in enumerate(candidates))
    return DECISION_PROMPT.format(n_max=len(candidates) - 1, existing=existing, fact=fact)


def parse_decision(raw: str, n_candidates: int) -> "tuple[str, int | None]":
    """Returns ('add'|'supersede'|'none', index|None). Anything malformed or
    out of range degrades to 'add' — the mem0-pivot lesson: a wrong ADD is
    harmless on an append-only table; a wrong supersede is not."""
    if not raw:
        return ("add", None)
    line = raw.strip().splitlines()[0].strip().upper()
    if line.startswith("NONE"):
        return ("none", None)
    m = re.match(r"SUPERSEDE\s+(\d+)", line)
    if m:
        idx = int(m.group(1))
        if 0 <= idx < n_candidates:
            return ("supersede", idx)
        return ("add", None)  # out-of-range: refuse to guess
    return ("add", None)


def may_supersede(new_observed_at, old_observed_at) -> bool:
    """Deterministic guard (code, not LLM): an older fact never supersedes a
    newer one. Missing timestamps don't block (treated as 'now-ish')."""
    if new_observed_at is None or old_observed_at is None:
        return True
    a = new_observed_at if new_observed_at.tzinfo else new_observed_at.replace(tzinfo=timezone.utc)
    b = old_observed_at if old_observed_at.tzinfo else old_observed_at.replace(tzinfo=timezone.utc)
    return a >= b


def parse_observed_at(value: "str | None"):
    """Lenient YYYY-MM-DD parse for extractor-supplied event dates."""
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value.strip()[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def parse_json_maybe_fenced(raw: str):
    """Shared lenient JSON extraction (fences stripped, first object)."""
    if not raw:
        return None
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.MULTILINE)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except (json.JSONDecodeError, ValueError):
        return None
