"""THE SEAM FILE — the only module that touches host-harness symbols.

WIRED against recon round 1 (2026-07-06). Every function still degrades
gracefully off-harness so the package imports and the scripts run standalone
against any dev database. WIRING flags are computed where possible;
verify_phase_a.py prints the truth for the environment it runs in.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass

log = logging.getLogger("agent_memory")

WIRING = {
    "base": False,      # set below: True when the harness Base imported
    "session": True,    # deliberate: own engine from AGENT_FACTORY_DATABASE_URL (see Q8 note)
    "identity": True,   # Q4/Q5: ToolContext.context dict keys profile_id/user_id/thread_id
    "flag": True,       # Q16: profile.memory.semantic_memory_enabled; tools via ctx key
    "llm": True,        # Q15: mini SDK Runner.run — confirmed non-recursive path
    "embed": True,      # v2: Azure OpenAI embeddings via the same env the SDK uses (R5 pins deployment)
}


# --------------------------------------------------------------------------
# Q7 — declarative Base.
# On the harness: agent_factory.persistence.models.Base. The fallback keeps
# the package testable off-harness; reset_dev_tables.py creates the tables
# directly either way, independent of app-startup create_all
# (Database.create_tables, gated by AGENT_FACTORY_DB_CREATE_TABLES).
# --------------------------------------------------------------------------
try:
    from agent_factory.persistence.models import Base  # type: ignore

    WIRING["base"] = True
except ImportError:
    from sqlalchemy.orm import declarative_base

    Base = declarative_base()


# --------------------------------------------------------------------------
# Q8 — sessions.
# The harness factory (agent_factory.persistence.database.Database.
# session_factory) lives on an instance we can't cleanly reach from here, so
# this module keeps its own engine on the SAME database via
# AGENT_FACTORY_DATABASE_URL — the exact URL the app uses. Small separate
# pool; acceptable for the prototype, swap to shared DI later.
# URL normalization: prefer the harness's own normalizer (round 2 found
# agent_factory.persistence.urls.normalize_async_database_url); fall back to
# the simple scheme rewrite when running standalone.
# --------------------------------------------------------------------------
_engine = None
_session_factory = None


def _default_session_factory():
    global _engine, _session_factory
    if _session_factory is None:
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        url = os.environ.get("AGENT_FACTORY_DATABASE_URL")
        if not url:
            raise RuntimeError(
                "AGENT_FACTORY_DATABASE_URL is not set — agent memory needs the harness database URL"
            )
        try:
            from agent_factory.persistence.urls import normalize_async_database_url  # type: ignore

            url = normalize_async_database_url(url)
        except ImportError:
            if url.startswith("postgresql://"):
                url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        _engine = create_async_engine(url, pool_pre_ping=True)
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _session_factory


@asynccontextmanager
async def get_session():
    """Yield an AsyncSession. Callers commit explicitly (same shape as
    AsyncThreadRepository: `async with factory() as session: ...`)."""
    factory = _default_session_factory()
    async with factory() as session:
        yield session


# --------------------------------------------------------------------------
# Q4/Q5 — identity.
# Two shapes exist:
#   * SDK tools: ctx is agents.tool_context.ToolContext; ctx.context is the
#     dict built by agent_factory.runtime.sdk_runner._harness_run_context
#     with keys profile_id / user_id / thread_id / run_id (NO tenant_id).
#   * Harness call sites (stream_turn): profile + effective_request are in
#     scope — construct Identity directly there, don't probe.
# --------------------------------------------------------------------------
@dataclass
class Identity:
    profile_id: str
    user_id: str
    tenant_id: str = "default"
    thread_id: str | None = None


def _lookup(source, key: str):
    if source is None:
        return None
    if isinstance(source, dict):
        val = source.get(key)
    else:
        val = getattr(source, key, None)
    return val if isinstance(val, str) and val else None


def get_identity(ctx) -> Identity | None:
    """For tool callables: pass the SDK ToolContext (or its .context dict).
    Returns None unless BOTH profile_id and user_id resolve — memory then
    silently no-ops rather than mis-keying rows."""
    if ctx is None:
        return None
    sources = [getattr(ctx, "context", None), ctx]
    profile_id = user_id = thread_id = None
    for s in sources:
        profile_id = profile_id or _lookup(s, "profile_id")
        user_id = user_id or _lookup(s, "user_id")
        thread_id = thread_id or _lookup(s, "thread_id")
    if not profile_id or not user_id:
        return None
    tenant_id = next(filter(None, (_lookup(s, "tenant_id") for s in sources)), None)
    return Identity(profile_id, user_id, tenant_id or "default", thread_id)


# --------------------------------------------------------------------------
# Q16 — the opt-in flag: profile.memory.semantic_memory_enabled (bool,
# default False, lives in agent.profile.yaml; flip + restart backend).
# Tools can't see the profile, so the harness adds a "memory_enabled" key to
# the _harness_run_context dict (see IMPLEMENTATION_BRIEF Task 3). Accepts a
# profile object, a ToolContext, or the context dict. Fails CLOSED.
# --------------------------------------------------------------------------
def memory_enabled(profile_or_ctx) -> bool:
    if profile_or_ctx is None:
        return False
    for source in (getattr(profile_or_ctx, "context", None), profile_or_ctx):
        if source is None:
            continue
        if isinstance(source, dict):
            if "memory_enabled" in source:
                return bool(source["memory_enabled"])
            continue
        mem = getattr(source, "memory", None)
        if mem is not None and hasattr(mem, "semantic_memory_enabled"):
            return bool(mem.semantic_memory_enabled)
        prof = getattr(source, "profile", None)
        mem = getattr(prof, "memory", None) if prof is not None else None
        if mem is not None and hasattr(mem, "semantic_memory_enabled"):
            return bool(mem.semantic_memory_enabled)
    return False


# --------------------------------------------------------------------------
# Q15 — side LLM call for extraction (Phase B).
# No raw internal client exists in the harness. The confirmed-safe path is a
# bare SDK agent via Runner.run: recon verified it does NOT re-enter
# SdkRunnerAdapter.stream_turn (no post-turn recursion) and writes no
# harness thread/run/event rows. Tool-less, so no side effects.
# Round 2 correction: mirror SdkSubagentExecutor exactly — pass the model
# EXPLICITLY on both Agent and RunConfig, tracing disabled. Model resolution:
# AGENT_FACTORY_MEMORY_MODEL env override, else the harness default from
# agent_factory.config.get_model_name() (AZURE_OPENAI_MODEL in dev).
# --------------------------------------------------------------------------
async def llm_complete(prompt: str) -> str:
    from agents import Agent, Runner, RunConfig  # lazy: Phase A never needs this

    try:
        from agent_factory.config import get_model_name  # type: ignore

        default_model = get_model_name()
    except ImportError:
        default_model = os.getenv("AZURE_OPENAI_MODEL") or os.getenv("OPENAI_MODEL") or "gpt-4.1"
    model = os.getenv("AGENT_FACTORY_MEMORY_MODEL") or default_model
    agent = Agent(
        name="memory-extractor",
        instructions="You extract durable memories. Reply with valid JSON only.",
        model=model,
    )
    result = await Runner.run(
        agent,
        prompt,
        run_config=RunConfig(
            model=model,
            tracing_disabled=True,
            workflow_name="memory-extraction",
        ),
    )
    return str(result.final_output or "")


# --------------------------------------------------------------------------
# v2 — embeddings seam.
# Uses the same process env the SDK inherits at app startup
# (configure_openai_env sets OPENAI_API_KEY / OPENAI_BASE_URL from the Azure
# values). Deployment name comes from AGENT_FACTORY_MEMORY_EMBED_MODEL
# (recon round 5 pins the default for this environment).
# Contract: returns one vector per input text, or None on ANY failure —
# callers must treat None as "no semantic tier this call" and degrade.
# --------------------------------------------------------------------------
EMBED_TIMEOUT_SECONDS = 5.0


async def embed(texts: list[str]) -> "list[list[float]] | None":
    if not texts:
        return []
    try:
        import asyncio

        from openai import AsyncOpenAI

        # Recon round 5: this resource serves text-embedding-3-large (3072) and
        # ada-002 (1536); 3-small is NOT deployed. Default: 3-large truncated
        # server-side to EMBED_DIM via the `dimensions` param (3-series only —
        # ada rejects it; its native 1536 matches the default dim anyway).
        model = os.getenv("AGENT_FACTORY_MEMORY_EMBED_MODEL", "text-embedding-3-large")
        dim = int(os.getenv("AGENT_FACTORY_MEMORY_EMBED_DIM", "1536"))
        kwargs = {"model": model, "input": [t[:4000] for t in texts]}
        if "text-embedding-3" in model:
            kwargs["dimensions"] = dim
        client = AsyncOpenAI()  # key/base_url from process env, same as the SDK
        resp = await asyncio.wait_for(
            client.embeddings.create(**kwargs), timeout=EMBED_TIMEOUT_SECONDS
        )
        vectors = [item.embedding for item in sorted(resp.data, key=lambda d: d.index)]
        if len(vectors) != len(texts) or any(len(v) != dim for v in vectors):
            log.info("embed dim/count mismatch (degrading to non-semantic path)")
            return None  # never poison the column with wrong-dimension vectors
        return vectors
    except Exception:
        log.info("embed failed (degrading to non-semantic path)")
        return None
