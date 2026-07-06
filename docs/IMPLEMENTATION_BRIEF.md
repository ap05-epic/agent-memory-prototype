# Implementation Brief — Agent Memory Prototype (recon-wired, final)

**You are the implementation agent on the pod, with the harness repository open.** The memory feature is **already written and pre-wired against recon round 1** in this transfer repo. Your job: place one package, make **five small anchored edits** to harness files, run the gates, report. Do not redesign, do not refactor, keep diffs minimal.

## Non-negotiable rules

- Never log or print memory **content** — ids, counts, statuses only.
- Never `await` extraction on the stream path — only `schedule_extraction(...)` (the RESPONSE_COMPLETED block is client-visible; recon Q14 confirmed awaited work there delays completion).
- `llm_complete` stays on the bare-SDK `Runner.run` path (recon Q15: does not re-enter `SdkRunnerAdapter.stream_turn`, writes no harness rows). Never route extraction through the harness runner.
- Touch no tables other than `agent_memory_entries` / `agent_memory_user_models`.
- Anchor edits by the strings given below; if an anchor is missing, stop and report.
- If a gate fails twice for the same cause, stop and report.

## What already exists (do not rewrite)

`memory/` — models, store (cap/fence-strip/denylist/dedup), recall, tool impl, extraction, and `_digit.py` **already wired**: Base import with fallback, own async engine on `AGENT_FACTORY_DATABASE_URL`, identity from ToolContext's `ctx.context` dict, flag reads, `llm_complete` via bare SDK agent. `scripts/` — `reset_dev_tables.py --yes`, `verify_phase_a.py`, `verify_phase_b.py`, `seed_demo.py` (all try `agent_factory.memory` first, fall back to standalone layout).

## Task 1 — Place package, create tables, baseline gate

- [ ] Copy `memory/` → `src/agent_factory/memory` (sibling of `persistence`, `runtime`).
- [ ] Confirm: `python3 -c "from agent_factory.memory import _digit; print(_digit.WIRING)"` → `base=True` expected now.
- [ ] Ensure `AGENT_FACTORY_DATABASE_URL` is exported in your shell (same value as `.env`).
- [ ] `python3 scripts/reset_dev_tables.py --yes` → `RESET: ok ...`
- [ ] `python3 scripts/verify_phase_a.py` → **`PHASE_A: PASS`** before any harness edit. (If engine creation rejects the URL's `ssl=require` param, mirror how `agent_factory.persistence.database` builds its engine and adjust `_default_session_factory` accordingly — that is the one permitted `_digit.py` edit.)

## Task 2 — Register models with app create_all (parity)

- [ ] At the **bottom** of `agent_factory/persistence/models.py` add:
```python
from agent_factory.memory import models as _memory_models  # noqa: E402,F401  (registers memory tables on Base.metadata)
```
Bottom placement avoids the circular import (`memory.models` imports `Base` from this module — already bound by then). If lint/CI complains, the alternative site is `agent_factory/persistence/database.py` next to `Database.create_tables`.
Note: app-startup create_all only runs when `AGENT_FACTORY_DB_CREATE_TABLES` is truthy; the reset script already created the tables either way.

## Task 3 — Expose the flag to tools (one line)

- [ ] In `agent_factory/runtime/sdk_runner.py`, function `_harness_run_context`, in the dict containing `"profile_id": profile.profile_id`, add:
```python
"memory_enabled": bool(profile.memory.semantic_memory_enabled),
```
(`memory/tool.py` fails closed without it — the tool would decline even for flag-on agents.)

## Task 4 — Register the `save_memory` tool

- [ ] In `agent_factory/tools/registry.py`, mirror the workspace pattern (`_WORKSPACE_TOOLS` + `_build_workspace_sdk_tools`): add a `_MEMORY_TOOLS` class constant and a builder:
```python
def _build_memory_sdk_tools(self):
    from agent_factory.memory.tool import TOOL_NAME, TOOL_DESCRIPTION, save_memory_impl

    async def save_memory(ctx, content: str, category: str = "note") -> str:
        return await save_memory_impl(ctx, content, category)

    # wrap exactly like the workspace builder wraps its callables with
    # function_tool(...), using TOOL_NAME / TOOL_DESCRIPTION; NO approval wrapper.
    return [...]
```
- [ ] Include the builder's output wherever `_build_workspace_sdk_tools`' output is aggregated. If the profile is in scope there, gate exposure: only include when `profile.memory.semantic_memory_enabled` (the in-body guard remains as defense-in-depth). If not in scope, include unconditionally — the guard declines for flag-off agents.

## Task 5 — Inject memory pre-turn

- [ ] In `agent_factory/runtime/sdk_runner.py`, `SdkRunnerAdapter.stream_turn`, before instructions are assembled (anchor: the call into `_load_sdk_instructions` / `load_instructions`, upstream of `Runner.run_streamed`):
```python
memory_block = None
_user = getattr(effective_request, "user", None)
if _user is not None and profile.memory.semantic_memory_enabled:
    from agent_factory.memory.recall import build_memory_block
    memory_block = await build_memory_block(
        profile.profile_id, _user.user_id, getattr(_user, "tenant_id", None) or "default"
    )
```
- [ ] Thread `memory_block` into `OpenAIAgentsSdkAdapter.load_instructions` (file `agent_factory/runtime/sdk_adapter.py`): add keyword param `memory_block: str | None = None` to the signature (after `include_skill_index`), and immediately before the final return of the assembled string:
```python
if memory_block:
    instructions = instructions + "\n\n" + memory_block
```
(Adjust the local variable name to whatever the function returns. If `_load_sdk_instructions` sits between, thread the kwarg through it. Existing callers pass nothing → byte-identical behavior.)

## Task 6 — Phase A acceptance (GATE — report before Phase B)

- [ ] Pick a dev agent (e.g. `test-full`): set `memory.semantic_memory_enabled: true` in its `agent.profile.yaml`; keep a second agent flag-off. Restart the backend **process** (`scripts/run-local-with-profiles.sh`).
- [ ] POST `/api/v1/turns/stream` (dev auth is bypassed unless `DEPLOYMENT_ENVIRONMENT=prod` / `AGENT_FACTORY_REQUIRE_AUTH`):
```json
{"profile_id": "test-full", "input": "Remember: I always want answers as exactly three bullet points, addressed to me by name. Save that.", "user": {"user_id": "user-a", "email": "user-a@example.com"}, "runtime": {"execution_engine": "sdk"}}
```
Expect a `save_memory` tool.started/completed in the stream and one `source='tool'` row in `agent_memory_entries`.
- [ ] Restart the backend process. Send a **new thread** (omit `thread_id`), same profile + user, input `"Give me a quick status-update template."` → reply is three bullets, addressed by name.
- [ ] Isolation: same input with `"user_id": "user-b"` → no personalization. Same input, flag-off profile, user-a → no personalization, and a "Remember..." turn there gets a decline from the tool (or no tool at all if exposure-gated).
- [ ] Report Phase A in the format below. **Stop here and report before Task 7.**

## Task 7 — Phase B: post-turn extraction

- [ ] In `SdkRunnerAdapter.stream_turn`, inside the `if output_event.event == EventName.RESPONSE_COMPLETED:` block, after the governance-audit yield and before `yield event(EventName.RUN_COMPLETED, ...)`:
```python
_user = getattr(effective_request, "user", None)
if _user is not None and profile.memory.semantic_memory_enabled:
    from agent_factory.memory import _digit as _mem
    from agent_factory.memory.extraction import schedule_extraction
    schedule_extraction(
        _mem.Identity(profile.profile_id, _user.user_id,
                      getattr(_user, "tenant_id", None) or "default", thread_id),
        str(effective_request.input), str(final_output),
    )  # fire-and-forget — MUST NOT be awaited
```
- [ ] Optional: `export AGENT_FACTORY_MEMORY_MODEL=<cheap model name>` (else SDK default; names come from `agent_factory.config.get_model_name` / `profile.model.default`).
- [ ] `python3 scripts/verify_phase_b.py` → **`PHASE_B: PASS`** (live check included now that `llm_complete` is wired).
- [ ] Live: flag-on agent, new thread, input `"By the way, I work on the payments reconciliation team."` → within ~30s one `source='extraction'` row. Then a pure chit-chat turn (`"thanks, that's all!"`) → no new row.

## Fallback ladder (take the highest rung that works, report which)

1. Full build (Tasks 1–7).
2. Phase A only (Tasks 1–6) — headline demo fully covered.
3. Injection + seeded rows (`scripts/seed_demo.py --profile test-full --user user-a`) — if tool registration is blocked.

## Report format (paste-able, one screen, no code dumps)

```
MEMORY BUILD REPORT — Phase A|A+B
WIRING: base=.. session=.. identity=.. flag=.. llm=..
PHASE_A: PASS|FAIL   PHASE_B: PASS|PARTIAL|FAIL|SKIPPED
files touched (harness):
  - persistence/models.py (bottom import) +1
  - runtime/sdk_runner.py (_harness_run_context) +1
  - runtime/sdk_runner.py (stream_turn: inject) +N
  - runtime/sdk_adapter.py (load_instructions kwarg) +N
  - tools/registry.py (_MEMORY_TOOLS + builder) +N
  - runtime/sdk_runner.py (stream_turn: schedule_extraction) +N   [Phase B]
acceptance:
  save via tool: OK|FAIL     rows source=tool: <n>
  restart + new-thread recall: OK|FAIL
  user-b isolation: OK|FAIL  flag-off: no injection OK|FAIL, tool declines OK|FAIL
  extraction row: OK|FAIL|SKIPPED   chit-chat writes nothing: OK|FAIL|SKIPPED
fallback rung used: 1|2|3
blockers/notes: <≤3 lines>
```
