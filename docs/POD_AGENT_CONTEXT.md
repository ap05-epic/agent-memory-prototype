# Pod Agent Context — read this first, fully

You are the implementation agent on the dev pod, starting fresh. This document loads everything you need to know about the codebase state, what is deployed and working, and where things live. Your **task list** is `docs/IMPLEMENTATION_BRIEF_V2.md` — read it after this. Nothing in this doc asks you to do anything yet.

## The two repositories

| | Path on pod | What it is |
|---|---|---|
| **Transfer repo** (this one) | `/projects/agent-memory-prototype` | Authored off-pod, synced via `git pull`. Holds the memory **package source** (`memory/`), **scripts** (`scripts/`), and **docs** (`docs/`). |
| **Harness** | `/projects/DigitHarnessRepo/digit-agent-harness` | The real product (FastAPI + OpenAI Agents SDK + async SQLAlchemy). The memory package is **deployed** at `src/agent_factory/memory/` (synced by copying from the transfer repo). Run python with `PYTHONPATH=src` from its root. Its `.env` holds real credentials — source it in the shell; **never print secrets**. |

Work on the harness happens on branch `feature/agentmemory` (or its v2 successor).

## What this system is, and what is LIVE right now

**Agent memory for the harness**: per-(agent, user) persistent memory in the existing Azure Postgres, opt-in per agent via the `profile.memory.semantic_memory_enabled` flag. **v1 is deployed, live-verified end to end, and must not regress.** Working today:

- **Recall**: at turn start, the user's memories are fetched and appended to the agent's instructions, with a `run.status` "🧠 Recalled N memories" indicator the console renders.
- **Save**: a `save_memory` custom tool (visible tool chip); write hygiene (500-char cap, `<user_memory>` fence-strip, secrets denylist, dedup) lives in the package store.
- **Extract**: after RUN_COMPLETED is prepared, a fire-and-forget background task captures durable facts (never awaited on the stream path).
- Live acceptance passed: save → row → backend restart → new-thread recall → user isolation → flag-off agent inert → extraction row → chit-chat writes nothing.

## Deployed harness touch points (already wired — know them, don't re-do them)

All in the harness repo, all flag-gated, all no-ops when the flag is off:

1. `src/agent_factory/runtime/sdk_runner.py` → `_harness_run_context`: dict includes `"memory_enabled": bool(profile.memory.semantic_memory_enabled)` (tools can't see the profile).
2. `src/agent_factory/runtime/sdk_adapter.py` → `build_agent`: keyword-only `memory_block: str | None = None`; appends it to `resolved_instructions` when set.
3. `src/agent_factory/runtime/sdk_runner.py` → `stream_turn` (pre-run): guarded by `if agent is None and profile.memory.semantic_memory_enabled:` — calls `build_memory_block(...)` (tuple-unpacked `_memory_block, _mem_count`), yields the `EventName.RUN_STATUS` 🧠 indicator with `sequence += 1`, passes `memory_block=_memory_block` into `build_agent`. **This is where your one v2 edit lands** (adding a `query_text=` kwarg — the brief quotes it).
4. `src/agent_factory/runtime/sdk_runner.py` → `stream_turn`, inside the `RESPONSE_COMPLETED` block (after the governance-audit yield, before the RUN_COMPLETED yield): `schedule_extraction(...)`, not awaited.
5. `src/agent_factory/api/app.py`: right after `tool_registry = ToolRegistry(...)` — `register_custom_tool("save_memory", function_tool(_save_memory, ...))`. Note: `ctx` is deliberately **unannotated** with `_save_memory.__annotations__["ctx"] = ToolContext` set separately (the file uses `from __future__ import annotations`, which breaks the SDK's `get_type_hints` on a direct annotation — this was learned the hard way; keep the pattern).
6. Demo profiles: `memory-demo` (flag on, `save_memory` in `tools.function_tools`, model gpt-5.4) and `test-minimal` (flag off) — staged under the dir `AGENT_FACTORY_PROFILE_PATHS` points at (was `tests/fixtures/profiles`).

## The memory package (deployed at `src/agent_factory/memory/`, source of truth in the transfer repo)

| File | Role |
|---|---|
| `_digit.py` | **The seam file** — the only file touching harness symbols. `Base`, `get_session()` (own engine on `AGENT_FACTORY_DATABASE_URL`), `get_identity(ctx)`, `memory_enabled(...)`, `llm_complete()` (bare SDK `Runner.run`, explicit model — proven non-recursive), and v2's `embed()` (AsyncOpenAI; env-driven model/dim; returns `None` on ANY failure — callers degrade). |
| `models.py` | `agent_memory_entries` (append-only log; v2 adds nullable `embedding`, `superseded_by`, `observed_at`) and `agent_memory_user_models` (reserved, empty). Embedding column type chosen **at import** from `AGENT_FACTORY_MEMORY_PGVECTOR` (1 → pgvector `Vector(dim)`, else packed-float32 binary). |
| `semantic.py` | v2 pure logic: pack/unpack, cosine, the 0.7·sim + 0.3·recency blend (floor 0.35), tiered-gate thresholds (0.95 same-fact / 0.70 band), integer-indexed supersede decision prompt + range-validated parse (degrades to ADD), `may_supersede` observed_at guard. |
| `store.py` | Write funnel + `smart_add_entry` (the tiered gate; `add_entry` delegates with the gate off = v1 semantics), `candidate_entries` (pgvector SQL rung or recent-N), `forget_user`, `scope_metrics`, `discard_entry`, `recent_entries`. |
| `recall.py` | `build_memory_block(profile, user, tenant, query_text=None) -> (block, count)`; with `query_text` it embeds the message and blends relevance+recency; without it (or embedder down) it's v1 recency. Never raises. |
| `tool.py` | `save_memory_impl` — flag check inside, cheap tiers only (no LLM inline). |
| `extraction.py` | Post-turn prompt (now emits optional `observed_at` dates) + `decide_supersede` (tier-3, `AGENT_FACTORY_MEMORY_MODEL`) + `schedule_extraction`. |

Scripts (transfer repo `scripts/`): `verify_phase_a.py` / `verify_phase_b.py` / `verify_phase_c.py` (machine-checkable gates printing `PHASE_X: PASS|FAIL` — the C gate stubs the embedder, so it proves logic without model access), `upgrade_v2_columns.py` (additive ALTER only), `backfill_embeddings.py`, `seed_demo.py`, `reset_dev_tables.py` (**destructive — do not run; live rows exist**).

## Database facts (recon-verified)

Azure PostgreSQL 15.16, external (survives restarts). **pgvector 0.8.0 is already installed** in this database (`pg_extension` confirms; no CREATE EXTENSION needed), app user has CREATE privilege. `agent_memory_entries` holds real rows from the live v1 acceptance — the v2 schema change is **additive columns only**. The pgvector *Python* package is NOT yet in the venv (`pip install pgvector` is a brief task; refusal → the BYTEA fallback flag).

## Environment gotchas (each of these burned time once — respect them)

1. **The launch fix (mandatory):** the pod injects a stale ambient `AZURE_OPENAI_BASE_URL` (a *different* Azure resource) that overrides `.env` → 401s. Every backend launch must first:
   `unset AZURE_OPENAI_BASE_URL OPENAI_BASE_URL OPENAI_API_KEY OPENAI_AGENTS_API` then export the `.env` key + endpoint. (Full block in `docs/DEMO_RUNBOOK.md`.)
2. **Port:** `.env` may set `PORT=50001`, which can be occupied → `export PORT=8080`.
3. **Profiles:** the run script's default `AGENT_FACTORY_PROFILE_PATHS` points at other profile dirs → export it to the dir holding `memory-demo` + `test-minimal`.
4. **Env before import:** `AGENT_FACTORY_MEMORY_PGVECTOR` (and the embed model/dim vars) must be exported **before** running any memory script and before launching the backend — the column type is chosen at import time.
5. **Embeddings:** this resource serves `text-embedding-3-large` (use with `dimensions=1536`) and `ada-002`; **`text-embedding-3-small` is NOT deployed** (404s). The deployments-list endpoint 404s — direct probes are how reality was established.
6. Default/Responses API mode is required by the harness's namespaced tools; don't switch `OPENAI_AGENTS_API`.

## What v2 is (your build), in one breath

Three pillars, strictly additive, every one degrading to v1 automatically: (1) **semantic retrieval** — embed at write, embed the incoming message at recall, blend relevance+recency (pgvector SQL rung → Python-similarity rung → recency rung); (2) **supersede writes** — a tiered gate so changed facts *replace* old ones via `superseded_by` chains (new row in, old row soft-retired — nothing hard-deleted), LLM consulted only in the ambiguity band, always degrading to plain ADD; (3) consolidation into the profile doc — **NOT in this build**, comes later. Your build = pillars 1+2: it's mostly package-sync + env + one additive migration + **one one-line harness edit**, then gates and acceptance. The brief has exact commands.

## How we work (the contract)

Everything you need is front-loaded — anchors are quoted from deployed code, commands are ready-to-run, gates are machine-checkable. Therefore: **no improvisation**. If an anchor is missing, a gate fails twice for the same cause, or reality contradicts this document — stop and report rather than adapting creatively. Reports are terse PASS/FAIL checklists (they travel by screenshot/OCR). Never log or print memory *content* or secrets.

## Deeper references (read on demand, not up front)

- `docs/IMPLEMENTATION_BRIEF_V2.md` — **your task list; go there next.**
- `docs/DESIGN_V2.md` — why every v2 decision is what it is.
- `docs/TECHNICAL_DEEP_DIVE.md` — the full v1 system explainer.
- `docs/DEMO_RUNBOOK.md` — the launch-fix block + demo beats.
- `docs/research/INDUSTRY_PRACTICES.md` — the sourced research behind the thresholds.
- Harness repo `build_report.md` — the v1 build + live-acceptance record.
