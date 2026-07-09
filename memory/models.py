"""Two tables, both scoped (profile_id, user_id, tenant_id).

Classic Column style on purpose — compatible with SQLAlchemy 1.4 and 2.x,
whichever the host pins. tenant_id is NOT NULL with a sentinel because a
nullable column inside a unique key breaks ON CONFLICT semantics (pre-15
Postgres treats NULLs as distinct).

v2 columns (all nullable → additive, applied to live DBs by
scripts/upgrade_v2_columns.py):
- embedding: vector(dim) when AGENT_FACTORY_MEMORY_PGVECTOR=1 (extension
  enabled), else packed-float32 LargeBinary — Letta's dialect-conditional
  pattern; the pgvector import happens only in that branch.
- superseded_by: id of the replacing entry (supersede-not-overwrite).
- observed_at: event time (when the fact was true) vs created_at (ingest);
  used by the older-never-supersedes-newer guard.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)

from ._digit import Base

EMBED_DIM = int(os.getenv("AGENT_FACTORY_MEMORY_EMBED_DIM", "1536"))
USE_PGVECTOR = os.getenv("AGENT_FACTORY_MEMORY_PGVECTOR", "").strip() in ("1", "true", "yes")

if USE_PGVECTOR:
    from pgvector.sqlalchemy import Vector  # only imported when the extension is enabled

    _EmbeddingType = Vector(EMBED_DIM)
else:
    _EmbeddingType = LargeBinary  # packed float32; python-side similarity (rung 2)


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MemoryEntry(Base):
    """Append-only memory log. Soft delete via discarded_at — never UPDATE
    content, never hard-DELETE outside dev scripts; the log doubles as the
    audit trail."""

    __tablename__ = "agent_memory_entries"

    id = Column(String(36), primary_key=True, default=_uuid)
    profile_id = Column(String(255), nullable=False)
    user_id = Column(String(255), nullable=False)
    tenant_id = Column(String(255), nullable=False, default="default")
    content = Column(Text, nullable=False)
    category = Column(String(32), nullable=True)  # preference | fact | context | note
    source = Column(String(16), nullable=False, default="tool")  # tool | extraction
    thread_id = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now())
    discarded_at = Column(DateTime(timezone=True), nullable=True)
    # v2 (nullable/additive)
    embedding = Column(_EmbeddingType, nullable=True)
    superseded_by = Column(String(36), nullable=True)
    observed_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_agent_memory_entries_scope", "profile_id", "user_id", "created_at"),
    )


class MemoryUserModel(Base):
    """Curated per-(agent, user) doc. Ships empty in v1; home of the synthesis
    stretch. version = optimistic locking for when rewrites arrive."""

    __tablename__ = "agent_memory_user_models"

    id = Column(String(36), primary_key=True, default=_uuid)
    profile_id = Column(String(255), nullable=False)
    user_id = Column(String(255), nullable=False)
    tenant_id = Column(String(255), nullable=False, default="default")
    content = Column(Text, nullable=False, default="")
    version = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("profile_id", "user_id", "tenant_id", name="uq_agent_memory_user_models_scope"),
    )
