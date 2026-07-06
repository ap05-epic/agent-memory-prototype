"""Async CRUD for memory entries. All write hygiene lives here:
length cap, fence-strip, denylist, dedup, soft delete.
Logging: ids / counts / outcomes only — NEVER content."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy import func, select, update

from . import _digit
from .models import MemoryEntry

MAX_ENTRY_CHARS = 500
DEDUP_WINDOW = 20

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


async def add_entry(
    profile_id: str,
    user_id: str,
    content: str,
    *,
    category: str = "note",
    source: str = "tool",
    tenant_id: str = "default",
    thread_id: str | None = None,
) -> str:
    """Returns a short status: 'saved' | 'duplicate' | 'rejected' | 'empty'."""
    content = _clean(content)
    if not content:
        return "empty"
    if _denied(content):
        log_ = _digit.log
        log_.info("memory add rejected by denylist scope=%s/%s", profile_id, user_id)
        return "rejected"
    existing = await recent_entries(profile_id, user_id, tenant_id, DEDUP_WINDOW)
    if any(_norm(e.content) == _norm(content) for e in existing):
        return "duplicate"
    entry = MemoryEntry(
        profile_id=profile_id,
        user_id=user_id,
        tenant_id=tenant_id,
        content=content,
        category=category,
        source=source,
        thread_id=thread_id,
    )
    async with _digit.get_session() as session:
        session.add(entry)
        await session.commit()
    _digit.log.info("memory add id=%s source=%s scope=%s/%s", entry.id, source, profile_id, user_id)
    return "saved"


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
