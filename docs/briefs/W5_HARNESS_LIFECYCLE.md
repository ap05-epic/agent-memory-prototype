# W5 — Harness-Managed Lifecycle: memory adopts the app's session factory and model conventions

**Where:** `/projects/DigitHarnessRepo/digit-agent-harness-v3`, branch `feature/agentmemory-v3`. The OLD folder stays read-only; port 8081 for any server; kill only PIDs you started; never force-push; never run `reset_dev_tables.py`.
**Who:** GPT-5.4 Copilot CLI. Stop at every GATE, print the report (flat text, OCR-safe), wait for the human.

## Why (review context)

Subomi's finding: the memory package runs its **own** SQLAlchemy engine (built in `memory/_digit.py` from `AGENT_FACTORY_DATABASE_URL`) and its own bare model calls, instead of the harness-managed lifecycle. Round 7 pinned the target patterns: `create_app()` builds `Database` objects and injects `database.session_factory` into repositories (`AsyncWorkspaceFileRepository(database.session_factory)` is the simple exemplar); non-turn model calls follow `SdkSubagentExecutor` (Agent + `Runner.run` + `RunConfig(model=..., tracing_disabled=True, workflow_name=..., trace_metadata={...})`). There is **no** token/usage accounting anywhere in the harness today (verified), so model-path work means *parity with the sanctioned pattern plus content-free usage logging*, not building a gateway.

Design chosen off-pod: **seam injection, not a rewrite.** Every memory function already gets sessions through one funnel — `_digit.get_session()`. We add an installer the app calls once at construction; the funnel prefers the installed factory and falls back to the package's own engine only for standalone scripts (reset/verify/backfill run outside the app by design). Smallest diff, zero changes to store/recall/tool/extraction call sites, and in-app the package creates no engine at all — lifecycle (pooling, disposal at shutdown) becomes the harness's.

## GATE 0 — read-first verification (report, then wait)

1. Quote `_database_from_env()` and `_runtime_database_from_env()` from `app.py` (or wherever they live): which env var does each read? Confirm which one corresponds to `AGENT_FACTORY_DATABASE_URL` — that is the factory memory must receive. Report if they can differ.
2. In `create_app`, locate: (a) the line `database = _database_from_env()`, (b) the existing `if database is not None:` guard (workspace repo wiring), (c) the existing `save_memory` tool registration from our v1 wiring (search `register_custom_tool`). Quote 3 lines around each — these are the anchors.
3. Where does the `session_factory` passed to `TurnService(...)` come from? Quote its assignment.
4. Test conventions: how is the suite invoked in this repo (pytest? a make target?), and is an async test plugin available (`grep -rn "pytest-asyncio\|anyio" pyproject.toml` + look at one existing async-touching test)? Report what exists — the new test must follow repo conventions, using `asyncio.run(...)` inside sync tests if no plugin is present.
5. `git status --short` must be clean and HEAD must be `2fc2dbb` (or a descendant on `feature/agentmemory-v3`).

## Task 1 — the seam installer (`src/agent_factory/memory/_digit.py`)

Add near the session section:

```python
_installed_session_factory = None


def install_session_factory(factory) -> None:
    """Called once by create_app with the harness Database.session_factory so
    memory shares the app's engine/pool/lifecycle. Standalone scripts never
    call this and keep the package's own fallback engine."""
    global _installed_session_factory
    _installed_session_factory = factory
    WIRING["session"] = "harness"
    log.info("memory sessions: harness session factory installed")
```

Change `get_session()` to prefer it:

```python
@asynccontextmanager
async def get_session():
    factory = _installed_session_factory or _default_session_factory()
    async with factory() as session:
        yield session
```

Inside `_default_session_factory()`, at the point the fallback engine is actually created, add one line:
`log.info("memory sessions: fallback engine created (standalone mode)")`
— its **absence** from the server log is the Gate B receipt that in-app memory owns no engine.

Update the `WIRING["session"]` comment (was "deliberate: own engine…") to reflect the new truth, and bump `BUILD` to `"2026-07-20.8-w5-shared-sessions"`.

## Task 2 — one-line wiring in `create_app` (`src/agent_factory/api/app.py`)

Inside the existing `if database is not None:` guard (same region as the workspace repository wiring), add:

```python
from agent_factory.memory import _digit as _memory_digit

_memory_digit.install_session_factory(database.session_factory)
```

Use the factory confirmed at GATE 0 item 1 (the `AGENT_FACTORY_DATABASE_URL` one). If the local import style there differs (round 7 shows lazy imports inside the guard), match it.

## Task 3 — model side-call parity (`_digit.llm_complete`)

Align to the `SdkSubagentExecutor` pattern (round 7 B4) without changing behavior:

1. Keep: explicit model on Agent **and** RunConfig, `tracing_disabled=True`, `workflow_name="memory-extraction"`.
2. Add `trace_metadata={"component": "agent-memory", "purpose": "extraction-or-decision"}` to the RunConfig.
3. After the run, capture usage if the SDK result exposes it and log ONE content-free line:
   `log.info("memory side-call model=%s tokens_in=%s tokens_out=%s", model, in_t, out_t)` — guard with `getattr`/try so missing usage never breaks the call (report what the result object actually exposes: `result.usage`, `context_wrapper.usage`, or nothing).

## Task 4 — local env cleanup (not committed)

`.env` line 3 in the v3 folder still points `AGENT_FACTORY_PROFILE_PATHS` at the OLD folder's `profiles/`. Change it to the v3 folder's `tests/fixtures/profiles`. Local file only — confirm `.env` is gitignored and never staged.

## Task 5 — the W7 test slice (`tests/test_agent_memory_sessions.py`)

Follow the conventions found at GATE 0 item 4. Cover, with an in-memory/aiosqlite `async_sessionmaker` (pattern exists in the transfer repo's verify scripts):

1. **Installed factory is used:** `install_session_factory(fake_factory)` → `get_session()` yields a session from `fake_factory` (assert by identity/side effect), and no fallback engine is created.
2. **Fallback still works:** with the installed factory reset to `None` and `AGENT_FACTORY_DATABASE_URL` monkeypatched to sqlite, `get_session()` still functions (this is the standalone-scripts path).
3. **Write path through installed factory:** create the two memory tables on the sqlite engine (`Base.metadata.create_all` equivalent for the test), then `await add_entry(...)` and assert the row exists — proves the whole store funnel rides the injected factory.
Reset the module-global in test teardown so ordering never leaks between tests.

## GATE A — static + tests

`python3 -m py_compile` on every touched file; run the new test file; then run the repo's existing suite the conventional way (GATE 0 item 4). Requirement: new tests pass, and no previously-passing test breaks (report the before/after counts if the suite has pre-existing failures — do not fix unrelated failures).

## GATE B — live proof (port 8081)

Launch from the v3 folder exactly as W0 GATE 5 did (explicit `PYTHONPATH=src`, v3 profile paths — now also correct in `.env` per Task 4 — PORT=8081, the four memory env vars, log to file). Require, in the log:

1. `agent_memory seam loaded build=2026-07-20.8-w5-shared-sessions`
2. `memory sessions: harness session factory installed`
3. **NO** `fallback engine created` line anywhere in the server log.
4. One recall turn (memory-demo, console-user, "What do you remember about me?") → recall indicator or recital, exactly as in W0 GATE 5 — proving reads/writes work through the shared factory.
5. Optional receipt if cheap: the side-call usage log line after a turn that triggers extraction or a save.

Stop the server by its exact PID.

## GATE C — commit + push

One commit on `feature/agentmemory-v3`:

```
memory: adopt harness-managed DB sessions and model-call conventions

create_app now installs Database.session_factory into the memory seam, so
in-app memory shares the app's engine, pool, and shutdown lifecycle and
creates no engine of its own (fallback engine remains for standalone
scripts, with a log receipt either way). Memory side-calls now carry the
same RunConfig conventions as SdkSubagentExecutor (workflow name, trace
metadata, tracing disabled) and log content-free token usage when the SDK
exposes it. Adds tests covering installed-factory use, standalone
fallback, and the write path through an injected factory.
```

Plain `git push`. Final report: SHAs, gate outcomes, and the quoted log receipts.

## Rollback

Uncommitted: `git checkout -- <files>` in the v3 folder. Committed-but-wrong: report and stop — the off-pod side decides (never rewrite pushed history). Old folder untouched throughout.

## Gate report format

```
GATE <x>: PASS or FAIL
<KEY>: <value>
NEXT: waiting for human
```
