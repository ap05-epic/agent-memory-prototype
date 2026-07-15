# Recon Round 6 — Post-Review Ground Truth (drift audit + current-dev reconnaissance)

You are the on-pod recon agent with full read access to the harness repository. **READ-ONLY** — no edits, no checkouts that change the working tree, no commands that modify state (`git fetch` is allowed and needed). Context: the memory feature on `feature/agentmemory` received a formal review; the branch is ~113 commits behind `origin/dev`, and productionization work will be built against **current dev**. This round establishes (A) the exact current state of our branch and pod, and (B) what today's dev looks like in every area the review touches.

## RETURN CHANNEL
Write your full answer to `recon_round_6_answers.md` (lossless copy-out preferred). Quote real code; never print secrets.

---

## Block A — Our branch & pod state (the drift audit)

**A1.** `git fetch origin` then report: `git log --oneline origin/dev..origin/feature/agentmemory` (our commits) and `git log --oneline -15 feature/agentmemory` — list every commit on the branch with one-line subjects. Also `git status --short` — any uncommitted changes left on the pod?

**A2.** Recent bug-fix/optimization sessions changed things we haven't tracked. For the last N commits made after the docs bundle commit: `git show --stat <sha>` each, and for any file OUTSIDE `Anshuman-Memory-Docs/` and `src/agent_factory/memory/`, quote the load-bearing hunks (≤15 lines each). Specifically identify: what made response times drop from ~130s to 5–15s (model switch? where — profile yaml `model.default`? env? `get_model_name`? reasoning_effort?), and any changes to tool-calling/UI paths.

**A3.** Current `src/agent_factory/memory/store.py` on the branch: does it contain the `_persist` retry-without-embedding hardening (grep `_persist` / `retry with embed_value=None`)? Quote its current `smart_add_entry` persistence section (≤25 lines) — the off-pod copy must be reconciled to match.

**A4.** Timing ground truth: from any recent server log, report per-turn timing evidence if present (the `[timing:` debug lines or timestamps between run.started and run.completed for a memory-demo turn), and which model the demo profile currently runs (`tests/fixtures/profiles/memory-demo/agent.profile.yaml` → model block, verbatim).

## Block B — What moved underneath us (targeted diff vs current dev)

**B1.** Magnitude first: `git diff --stat origin/feature/agentmemory...origin/dev | tail -5` (just the summary line + biggest entries).

**B2.** For EACH of our five touched files, summarize what changed on dev since our merge-base, with the key hunks quoted (≤15 lines each) — `git log --oneline origin/feature/agentmemory..origin/dev -- <file>` then `git diff origin/feature/agentmemory...origin/dev -- <file>` (summarize; don't dump):
- `src/agent_factory/runtime/sdk_runner.py` — does `stream_turn` still exist in the same shape? Is the RESPONSE_COMPLETED → audit → RUN_COMPLETED block intact? Where would our recall/extraction insertions land now?
- `src/agent_factory/runtime/sdk_adapter.py` — `build_agent` signature now? Does `resolved_instructions = instructions or self.load_instructions(...)` still exist?
- `src/agent_factory/api/app.py` — is `ToolRegistry(...)` construction still there? Auth (`_api_auth_required`) changes? New router structure?
- `src/agent_factory/tools/registry.py` — `plan_tools`/`_custom_tools`/`register_custom_tool` still the same mechanism? Any new tool-governance layer?
- `src/agent_factory/core/schemas.py` — `MemoryPolicy` / `ToolPolicy` / `UserContext` changes? Anything new about tenant/user validation?

**B3.** Verdict per file: `CLEAN-APPLY | SMALL-CONFLICTS | HEAVILY-MOVED` — your judgment of whether our edits re-apply mechanically or need redesign.

## Block C — Current dev's infrastructure (one question per review workstream)

**C1. Migrations (review finding 2):** does current dev have a migration framework now (alembic dir, `migrations/`, any `alembic.ini`, or a documented DDL path)? If yes: quote how an existing table's migration looks (≤10 lines) and how migrations run (startup? CI? command). If no: how does dev create tables today — is `AGENT_FACTORY_DB_CREATE_TABLES` still the mechanism, and where exactly does `create_tables` run relative to model imports?

**C2. Harness DB lifecycle (finding 6):** on current dev, how would a feature properly obtain an async session from the harness's own `Database` (dependency injection? an accessor? app.state?)? Quote how an existing store/repository gets its session factory wired at app construction (≤10 lines).

**C3. Model-call path (finding 6):** does current dev have an internal LLM client/service for side calls (non-turn model calls) — anything like a model gateway, client wrapper, or accounting layer beyond bare SDK `Runner.run`? Quote how any existing non-turn model call is made. If none exists, say NONE — and note what observability/accounting hooks a side call would be expected to integrate with (tracing config, token accounting, timeout policy — quote where those live).

**C4. Governed capabilities (findings 3/7):** what does "a first-class governed capability" look like on current dev — is there a capability registry, approval policies beyond `needs_approval`, tool governance config, or an entitlements mechanism? Quote the closest existing pattern (how a sensitive tool/capability is declared, gated, and audited today, ≤15 lines).

**C5. Audit events (finding 3):** how does the harness emit audit-grade events today (the governance audit machinery in the runner — `agt_audit_payload` / governance bundle)? Quote how an audit event is constructed and where it's persisted/shipped, so a `memory.write` audit event can ride the same rails.

**C6. API surface (finding 3):** where would user-facing memory endpoints live (inspect/delete/disable)? Quote how an existing user-scoped CRUD-ish endpoint is declared on current dev (router, auth dependency, request validation — ≤15 lines) and how the console calls such endpoints.

**C7. Context channels (finding 4):** on current dev, what channels exist for supplying per-turn context to the model BESIDES the instruction string — e.g., prepended input messages, session items, tool-result injection, an SDK context parameter that reaches the model, or any "retrieval results" convention? Quote how `input` is assembled for `Runner.run_streamed` now, and whether anything else injects contextual items into the input list. (This decides the new home for recalled memory.)

**C8. Background/durable work (finding 5):** what background-work infrastructure exists on current dev — the `agent_factory.worker` module's current role, any job queue/outbox pattern, scheduled tasks, graceful-shutdown handling for pending asyncio tasks? Quote how the worker processes work items if it does (≤15 lines). Could a small "pending memory extraction" outbox table be processed by existing machinery, or would we add a minimal loop?

**C9. Auth/tenant validation (finding 8):** on current dev, how is `request.user` validated (is a turn possible with no/invalid user)? Is `tenant_id` mandatory anywhere? Quote `_api_auth_required` (or successor) and the UserContext validation path, and state plainly: what would "require a validated user + tenant for memory-enabled profiles" hook into?

**C10. Test conventions (finding 9):** current dev's test setup — async test support now (pytest-asyncio? anyio?), DB test fixtures (sqlite? testcontainers? monkeypatched URL?), and quote one representative test that touches the DB and one that tests an API endpoint (≤10 lines each).

## Final verdict lines (end with exactly these)
```
BRANCH-STATE: <n commits ahead / m behind; uncommitted: yes|no>
REAPPLY: sdk_runner=<CLEAN|SMALL|HEAVY> sdk_adapter=<...> app=<...> registry=<...> schemas=<...>
MIGRATIONS: <framework|create_all-only>  WORKER-INFRA: <exists: what|none>
MODEL-CLIENT: <exists: what|none>  GOVERNANCE-PATTERN: <one line>
CONTEXT-CHANNEL: <best non-instruction channel for recalled memory, one line>
SURPRISES: <up to 3 lines of anything that contradicts our assumptions>
```
