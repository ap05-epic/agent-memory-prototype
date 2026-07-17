"""Async CRUD for memory entries. All write hygiene lives here:
length cap, fence-strip, denylist, dedup, soft delete — and in v2 the
embedding write path plus the tiered supersede gate.
Logging: ids / counts / outcomes only — NEVER content."""

from __future__ import annotations

from datetime import datetime, timezone

import re

from sqlalchemy import func, select, update
from sqlalchemy.exc import SQLAlchemyError

from . import _digit, semantic
from .models import EMBED_DIM, USE_PGVECTOR, MemoryEntry

MAX_ENTRY_CHARS = 500
DEDUP_WINDOW = 20
CANDIDATE_LIMIT = 60   # rows considered for similarity (per scope, live only)
DECISION_TOP_K = 5     # candidates shown to the decision model

# Best-effort backstop; the extraction prompt carries the real rules.
_DENYLIST = (
    re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b"),          # IBAN-shaped
    re.compile(r"\b(?:\d[ -]?){13,19}\b"),                     # card-shaped digit run
    re.compile(r"(?i)\b(password|passwd|secret|api[_-]?key|token|bearer)\b\s*[:=]"),
)

# Strip our own fence so stored content can never escape the injected block.
_FENCE = re.compile(r"(?i)</?user_memory>")


def _clean(content: str) -> str:
    content = _FENCE.sub("", content)
    content = " ".join(content.split())
    return content[:MAX_ENTRY_CHARS]


def _norm(content: str) -> str:
    return " ".join(content.split()).casefold()


def _denied(content: str) -> bool:
    return any(p.search(content) for p in _DENYLIST)


def _scope(stmt, profile_id: str, user_id: str, tenant_id: str):
    return stmt.where(
        MemoryEntry.profile_id == profile_id,
        MemoryEntry.user_id == user_id,
        MemoryEntry.tenant_id == tenant_id,
    )


def _store_embedding(vec):
    """list[float] -> column value for the active embedding column type."""
    if vec is None:
        return None
    return vec if USE_PGVECTOR else semantic.pack_vector(vec)


async def _embed_one(content: str):
    vecs = await _digit.embed([content])
    return vecs[0] if vecs else None


async def recent_entries(
    profile_id: str,
    user_id: str,
    tenant_id: str = "default",
    limit: int = DEDUP_WINDOW,
) -> list[MemoryEntry]:
    """Live entries, newest first."""
    stmt = _scope(select(MemoryEntry), profile_id, user_id, tenant_id)
    stmt = stmt.where(MemoryEntry.discarded_at.is_(None))
    stmt = stmt.order_by(MemoryEntry.created_at.desc()).limit(limit)
    async with _digit.get_session() as session:
        return list((await session.execute(stmt)).scalars())


async def candidate_entries(
    profile_id: str,
    user_id: str,
    tenant_id: str = "default",
    query_vec: "list[float] | None" = None,
    limit: int = CANDIDATE_LIMIT,
) -> list[MemoryEntry]:
    """Live rows for similarity work. Rung 1: pgvector orders in SQL; rung 2:
    recent-N fetch, ranking happens in Python (semantic.select_for_recall)."""
    stmt = _scope(select(MemoryEntry), profile_id, user_id, tenant_id)
    stmt = stmt.where(MemoryEntry.discarded_at.is_(None))
    if USE_PGVECTOR and query_vec is not None:
        stmt = stmt.where(MemoryEntry.embedding.isnot(None))
        stmt = stmt.order_by(MemoryEntry.embedding.cosine_distance(query_vec)).limit(limit)
    else:
        stmt = stmt.order_by(MemoryEntry.created_at.desc()).limit(limit)
    async with _digit.get_session() as session:
        return list((await session.execute(stmt)).scalars())


async def add_entry(
    profile_id: str,
    user_id: str,
    content: str,
    *,
    category: str = "note",
    source: str = "tool",
    tenant_id: str = "default",
    thread_id: str | None = None,
    observed_at: datetime | None = None,
) -> str:
    """v1-compatible primitive add (text-dedup only).
    Returns 'saved' | 'duplicate' | 'rejected' | 'empty'."""
    status, _ = await smart_add_entry(
        profile_id,
        user_id,
        content,
        category=category,
        source=source,
        tenant_id=tenant_id,
        thread_id=thread_id,
        observed_at=observed_at,
        decide=None,          # no LLM on this path
        semantic_gate=False,  # v1 semantics: text dedup only
    )
    return status


async def smart_add_entry(
    profile_id: str,
    user_id: str,
    content: str,
    *,
    category: str = "note",
    source: str = "tool",
    tenant_id: str = "default",
    thread_id: str | None = None,
    observed_at: datetime | None = None,
    decide=None,          # async (fact, candidates: list[str]) -> raw decision text, or None
    semantic_gate: bool = True,
) -> "tuple[str, str | None]":
    """The v2 write pipeline (tiered gate; see DESIGN_V2 §2).
    Returns (status, new_entry_id|None); status ∈
    saved | superseded_old | duplicate | rejected | empty.
    Any failure in the semantic tiers degrades to a plain ADD."""
    content = _clean(content)
    if not content:
        return ("empty", None)
    if _denied(content):
        _digit.log.info("memory add rejected by denylist scope=%s/%s", profile_id, user_id)
        return ("rejected", None)

    # Tier 1 — normalized text match (free).
    recent = await recent_entries(profile_id, user_id, tenant_id, DEDUP_WINDOW)
    if any(_norm(e.content) == _norm(content) for e in recent):
        return ("duplicate", None)

    new_vec = await _embed_one(content)  # None => no semantic tiers this call
    supersede_target: MemoryEntry | None = None
    gate_note = "no-embed" if new_vec is None else "no-candidates"

    if semantic_gate and new_vec is not None:
        try:
            candidates = await candidate_entries(profile_id, user_id, tenant_id, new_vec)
            sims = []
            for e in candidates:
                vec = semantic.to_vector(e.embedding)
                if vec is not None:
                    sims.append((semantic.cosine(new_vec, vec), e))
            sims.sort(key=lambda t: t[0], reverse=True)

            if sims:
                top_sim, top_e = sims[0]
                gate_note = f"top_sim={top_sim:.3f} tier=add"
                # Tier 2 — same-fact fast path (richer text wins without an LLM).
                if top_sim >= semantic.T_SAME and len(content) > len(top_e.content) * 1.2:
                    if semantic.may_supersede(observed_at, top_e.observed_at):
                        supersede_target = top_e  # strictly richer -> replace
                        gate_note = f"top_sim={top_sim:.3f} tier=richer-fast-path"
                elif decide is not None and top_sim >= semantic.T_DECIDE_FLOOR:
                    # Decider path: adjudicate anything above the low floor —
                    # hand-picked bands proved uncalibrated for real phrasings
                    # (live: a three->five contradiction fell below 0.70 and
                    # silently ADDed). The prompt handles "unrelated -> ADD"
                    # and "same meaning -> NONE"; failures degrade to ADD.
                    band = [(s, e) for s, e in sims[:DECISION_TOP_K] if s >= semantic.T_DECIDE_FLOOR]
                    raw = await decide(content, [e.content for _, e in band])
                    action, idx = semantic.parse_decision(raw, len(band))
                    gate_note = f"top_sim={top_sim:.3f} tier=decide action={action}"
                    if action == "none":
                        _digit.log.info("memory gate: %s scope=%s/%s", gate_note, profile_id, user_id)
                        return ("duplicate", None)
                    if action == "supersede":
                        target = band[idx][1]
                        if semantic.may_supersede(observed_at, target.observed_at):
                            supersede_target = target
                        else:
                            gate_note += " guard=refused"
                elif decide is None and top_sim >= semantic.T_SAME:
                    # No decider: conservative — same-fact drops as duplicate.
                    _digit.log.info(
                        "memory gate: top_sim=%.3f tier=dup-no-decider scope=%s/%s",
                        top_sim, profile_id, user_id,
                    )
                    return ("duplicate", None)
        except Exception:
            _digit.log.warning("semantic gate failed (degrading to ADD)", exc_info=True)
            supersede_target = None
            gate_note = "gate-exception"
    _digit.log.info("memory gate: %s scope=%s/%s", gate_note, profile_id, user_id)

    entry_fields = dict(
        profile_id=profile_id,
        user_id=user_id,
        tenant_id=tenant_id,
        content=content,
        category=category,
        source=source,
        thread_id=thread_id,
        observed_at=observed_at,
    )
    embed_value = _store_embedding(new_vec)
    try:
        entry = await _persist(entry_fields, embed_value, supersede_target)
    except SQLAlchemyError:
        # The embedding write failed — almost always a vector/bytea column-type
        # mismatch from an env-drift process (USE_PGVECTOR=%s, dim=%s) sharing a
        # DB whose `embedding` column was created by a differently-configured
        # process. Never fail the whole save on this: persist the content
        # without the embedding so the tool succeeds and the demo stays clean.
        if embed_value is None:
            raise  # not an embedding problem — surface it
        _digit.log.warning(
            "memory insert failed with embedding (USE_PGVECTOR=%s dim=%s); retrying "
            "without embedding — check AGENT_FACTORY_MEMORY_PGVECTOR matches the "
            "embedding column type across all processes on this DB",
            USE_PGVECTOR, EMBED_DIM, exc_info=True,
        )
        entry = await _persist(entry_fields, None, supersede_target)
    _digit.log.info(
        "memory add id=%s source=%s superseded=%s scope=%s/%s",
        entry.id, source, bool(supersede_target), profile_id, user_id,
    )
    return (("superseded_old" if supersede_target else "saved"), entry.id)


async def _persist(entry_fields: dict, embed_value, supersede_target) -> "MemoryEntry":
    """Insert one entry (+ optional supersede) in a fresh session. Isolated so
    the caller can retry with embed_value=None if the embedding write itself
    fails — the memory content must persist even when the vector column and the
    process's USE_PGVECTOR flag disagree (env drift across processes sharing one
    DB). This is the write-path counterpart to embed()'s degrade-to-None rule."""
    entry = MemoryEntry(**entry_fields, embedding=embed_value)
    async with _digit.get_session() as session:
        session.add(entry)
        await session.flush()
        if supersede_target is not None:
            await session.execute(
                update(MemoryEntry)
                .where(MemoryEntry.id == supersede_target.id, MemoryEntry.discarded_at.is_(None))
                .values(discarded_at=datetime.now(timezone.utc), superseded_by=entry.id)
            )
        await session.commit()
    return entry


async def discard_entry(entry_id: str) -> bool:
    """Soft delete — 'forget' is one UPDATE."""
    stmt = (
        update(MemoryEntry)
        .where(MemoryEntry.id == entry_id, MemoryEntry.discarded_at.is_(None))
        .values(discarded_at=datetime.now(timezone.utc))
    )
    async with _digit.get_session() as session:
        result = await session.execute(stmt)
        await session.commit()
    return bool(result.rowcount)


async def forget_user(profile_id: str, user_id: str, tenant_id: str = "default") -> int:
    """One-call scope cascade (stage one of two-stage deletion): discard every
    live entry for this (agent, user). Hard purge is the scheduled policy job."""
    stmt = (
        update(MemoryEntry)
        .where(
            MemoryEntry.profile_id == profile_id,
            MemoryEntry.user_id == user_id,
            MemoryEntry.tenant_id == tenant_id,
            MemoryEntry.discarded_at.is_(None),
        )
        .values(discarded_at=datetime.now(timezone.utc))
    )
    async with _digit.get_session() as session:
        result = await session.execute(stmt)
        await session.commit()
    _digit.log.info("forget_user scope=%s/%s discarded=%s", profile_id, user_id, result.rowcount)
    return int(result.rowcount or 0)


async def scope_metrics(profile_id: str, user_id: str, tenant_id: str = "default") -> dict:
    """live / discarded / superseded / embedded counts — the growth conversation."""
    base = _scope(select(func.count(MemoryEntry.id)), profile_id, user_id, tenant_id)
    async with _digit.get_session() as session:
        live = (await session.execute(base.where(MemoryEntry.discarded_at.is_(None)))).scalar_one()
        discarded = (await session.execute(base.where(MemoryEntry.discarded_at.isnot(None)))).scalar_one()
        superseded = (await session.execute(base.where(MemoryEntry.superseded_by.isnot(None)))).scalar_one()
        embedded = (
            await session.execute(
                base.where(MemoryEntry.discarded_at.is_(None), MemoryEntry.embedding.isnot(None))
            )
        ).scalar_one()
    return {"live": live, "discarded": discarded, "superseded": superseded, "embedded": embedded}


async def count_entries(
    profile_id: str,
    user_id: str,
    tenant_id: str = "default",
    include_discarded: bool = False,
) -> int:
    stmt = _scope(select(func.count(MemoryEntry.id)), profile_id, user_id, tenant_id)
    if not include_discarded:
        stmt = stmt.where(MemoryEntry.discarded_at.is_(None))
    async with _digit.get_session() as session:
        return (await session.execute(stmt)).scalar_one()
