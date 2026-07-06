"""THE SEAM FILE — the only module that touches host-harness symbols.

Every function here has a working default so the package imports and the
scripts run standalone against a dev database. The implementation agent
replaces the bodies marked RECON:<Qn> using the recon answer sheet, then
flips the matching WIRING flag to True. Nothing outside this file needs
editing to integrate with the harness.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass

log = logging.getLogger("agent_memory")

# Flipped to True per-slot by the implementation agent as each seam is wired.
# verify_phase_a.py prints this dict; base/session/identity/flag gate Phase A,
# llm gates Phase B.
WIRING = {
    "base": False,      # RECON:Q7
    "session": False,   # RECON:Q8
    "identity": False,  # RECON:Q4/Q5
    "flag": False,      # RECON:Q16
    "llm": False,       # RECON:Q15
}


# --------------------------------------------------------------------------
# RECON:Q7 — declarative Base.
# Replace the fallback with:   from <harness.db.module> import Base
# and delete the fallback block. If the harness model-import site cannot be
# found, the local Base still works: reset_dev_tables.py creates the tables
# directly, independent of the app's create_all.
# --------------------------------------------------------------------------
try:
    raise ImportError  # RECON:Q7 — remove this line when wiring the real Base
    # from harness.db import Base  # RECON:Q7 — real import goes here
except ImportError:
    from sqlalchemy.orm import declarative_base

    Base = declarative_base()


# --------------------------------------------------------------------------
# RECON:Q8 — async session factory.
# Default builds its own engine from AGENT_FACTORY_DATABASE_URL (confirmed
# env var). This works as-is on the pod (separate pool); swap to the
# harness's own async_sessionmaker if Q8 shows that is a one-liner.
# --------------------------------------------------------------------------
_engine = None
_session_factory = None


def _default_session_factory():
    global _engine, _session_factory
    if _session_factory is None:
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        url = os.environ["AGENT_FACTORY_DATABASE_URL"]
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        _engine = create_async_engine(url, pool_pre_ping=True)
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _session_factory


@asynccontextmanager
async def get_session():
    """Yield an AsyncSession. Callers commit explicitly."""
    factory = _default_session_factory()  # RECON:Q8 — or the harness factory
    async with factory() as session:
        yield session


# --------------------------------------------------------------------------
# RECON:Q4/Q5 — identity extraction, ctx-in.
# One accessor for all three seams (turn service, tool callable, post-turn
# hook); pass whatever context object that seam holds. The default probes
# common attribute chains and refuses to half-resolve: BOTH profile_id and
# user_id must be found, else None (callers then no-op — memory silently
# stays off rather than mis-keying rows).
# --------------------------------------------------------------------------
@dataclass
class Identity:
    profile_id: str
    user_id: str
    tenant_id: str = "default"
    thread_id: str | None = None


def _probe(obj, *chains):
    for chain in chains:
        cur = obj
        for attr in chain.split("."):
            cur = getattr(cur, attr, None)
            if cur is None:
                break
        if isinstance(cur, str) and cur:
            return cur
    return None


def get_identity(ctx) -> Identity | None:
    if ctx is None:
        return None
    # RECON:Q4/Q5 — replace probe chains with the confirmed attribute paths.
    profile_id = _probe(ctx, "profile.id", "profile_id", "profile.profile_id")
    user_id = _probe(ctx, "user.user_id", "user_id", "user_context.user_id")
    if not profile_id or not user_id:
        return None
    tenant_id = _probe(ctx, "user.tenant_id", "tenant_id") or "default"
    thread_id = _probe(ctx, "thread_id", "thread.id")
    return Identity(profile_id, user_id, tenant_id, thread_id)


# --------------------------------------------------------------------------
# RECON:Q16 — the per-agent opt-in flag.
# Pass the profile (or a ctx holding it). Default probes plausible paths and
# fails CLOSED: unknown shape means memory stays off for that agent.
# --------------------------------------------------------------------------
def memory_enabled(profile_or_ctx) -> bool:
    if profile_or_ctx is None:
        return False
    # RECON:Q16 — replace with the confirmed flag path.
    for chain in (
        "semantic_memory_enabled",
        "profile.semantic_memory_enabled",
        "features.semantic_memory_enabled",
        "profile.features.semantic_memory_enabled",
    ):
        cur = profile_or_ctx
        for attr in chain.split("."):
            cur = getattr(cur, attr, None)
            if cur is None:
                break
        if cur is not None:
            return bool(cur)
    return False


# --------------------------------------------------------------------------
# RECON:Q15 — side LLM call for post-turn extraction (Phase B only).
# CONTRACT: must be a raw model-client call. It must NOT run through the
# agent runner / SDK agent path — that would re-enter the post-turn hook
# (recursion) and write thread/run/event rows.
# Raises at call time, not import time, so Phase A never depends on it.
# --------------------------------------------------------------------------
async def llm_complete(prompt: str) -> str:
    raise NotImplementedError("RECON:Q15 — wire the harness's internal model client")
