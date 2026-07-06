"""Post-turn extraction (Phase B). Fired as a background task at the
run-completed seam; can NEVER break or delay a turn.

Prompt rules adapted from mem0's additive-extraction prompt, fused with
bank-grade data guardrails. Empty result is the expected common case.
"""

from __future__ import annotations

import asyncio
import json
import re

from . import _digit
from .store import add_entry, recent_entries

TIMEOUT_SECONDS = 20
_CATEGORIES = {"preference", "fact", "context", "note"}

EXTRACTION_PROMPT = """You maintain long-term memory for an AI assistant's relationship with one user.
From the exchange below, extract durable facts worth remembering across sessions.

Extract ONLY:
- stable preferences (format, tone, tools, workflow)
- durable personal/professional context (role, team, projects, expertise)
- standing corrections or decisions
Attribute correctly ("User prefers X", "User was recommended Y").

Do NOT extract: greetings or chit-chat, one-off task details, vague
characterizations, anything already listed in KNOWN MEMORIES, and NEVER
credentials, secrets, account or card numbers, or sensitive personal data
(health, beliefs, finances beyond professional context).

If nothing qualifies, return an empty list - that is the common case.

KNOWN MEMORIES (do not re-extract these):
{known}

EXCHANGE:
User: {user_text}
Assistant: {assistant_text}

Return ONLY JSON, no prose:
{{"new_entries": [{{"content": "...", "category": "preference|fact|context|note"}}]}}"""


def parse_extraction(raw: str) -> list[dict]:
    """Lenient: strip code fences, take the first JSON object, drop garbage
    silently. Malformed model output must cost nothing."""
    if not raw:
        return []
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.MULTILINE)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        return []
    try:
        data = json.loads(text[start : end + 1])
    except (json.JSONDecodeError, ValueError):
        return []
    entries = data.get("new_entries") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        return []
    out = []
    for item in entries:
        if isinstance(item, dict) and isinstance(item.get("content"), str) and item["content"].strip():
            cat = item.get("category")
            out.append(
                {
                    "content": item["content"].strip(),
                    "category": cat if cat in _CATEGORIES else "note",
                }
            )
    return out


async def extract_and_store(
    identity,
    user_text: str,
    assistant_text: str,
    already_captured: list[str] | None = None,
) -> int:
    """Returns number of entries written. Swallows every failure."""
    if identity is None:
        return 0
    try:
        existing = await recent_entries(identity.profile_id, identity.user_id, identity.tenant_id)
        known = [e.content for e in existing] + list(already_captured or [])
        known_text = "\n".join(f"- {k}" for k in known) if known else "(none)"
        prompt = EXTRACTION_PROMPT.format(
            known=known_text,
            user_text=(user_text or "")[:4000],
            assistant_text=(assistant_text or "")[:4000],
        )
        raw = await asyncio.wait_for(_digit.llm_complete(prompt), timeout=TIMEOUT_SECONDS)
        written = 0
        for item in parse_extraction(raw):
            status = await add_entry(
                identity.profile_id,
                identity.user_id,
                item["content"],
                category=item["category"],
                source="extraction",
                tenant_id=identity.tenant_id,
                thread_id=identity.thread_id,
            )
            written += status == "saved"
        _digit.log.info(
            "extraction wrote=%d scope=%s/%s", written, identity.profile_id, identity.user_id
        )
        return written
    except NotImplementedError:
        _digit.log.info("extraction skipped: llm_complete not wired (Phase B pending)")
        return 0
    except Exception:
        _digit.log.warning("extraction failed (swallowed)", exc_info=True)
        return 0


def schedule_extraction(
    identity,
    user_text: str,
    assistant_text: str,
    already_captured: list[str] | None = None,
) -> "asyncio.Task | None":
    """Fire-and-forget from the post-turn seam. Never await this inline on the
    turn path. llm_complete's contract (see _digit) forbids routing through
    the agent runner, which is what prevents hook re-entry."""
    if identity is None:
        return None
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return None
    task = loop.create_task(extract_and_store(identity, user_text, assistant_text, already_captured))
    task.add_done_callback(lambda t: t.cancelled() or t.exception())  # retrieve, never raise
    return task
