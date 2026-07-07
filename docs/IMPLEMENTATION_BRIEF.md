# Implementation Brief — Agent Memory Prototype (final, recon rounds 1+2 wired)

**You are the implementation agent on the pod, with the harness repository open.** The memory feature is already written and verified in this transfer repo. Your job: place one package, make **three small insertions in `agent_factory/runtime/sdk_runner.py`**, wire one tool, set up demo profiles, run the gates, and report. Every edit below quotes the real code it anchors to (verified against the repository in recon round 2). Do not redesign, do not refactor, keep diffs minimal.

## Non-negotiable rules

- Never log or print memory **content** — ids, counts, statuses only.
- Never `await` extraction on the stream path — only `schedule_extraction(...)`. The RESPONSE_COMPLETED block is on the client-visible stream; awaited work there delays every turn's completion.
- `llm_complete` stays on the bare-SDK `Runner.run` path with an explicit model (already implemented in `memory/_digit.py`) — never route extraction through `SdkRunnerAdapter.stream_turn`.
- Touch no tables other than `agent_memory_entries` / `agent_memory_user_models`.
- If an anchor string below is missing, stop and report — don't hunt creatively.
- If a gate fails twice for the same cause, stop and report.

## Task 1 — Place package, create tables, baseline gate

- [ ] Copy `memory/` → `src/agent_factory/memory` (sibling of `persistence`, `runtime`).
- [ ] `python3 -c "from agent_factory.memory import _digit; print(_digit.WIRING)"` → expect `base=True` now that the harness `Base` imports.
- [ ] Export `AGENT_FACTORY_DATABASE_URL` in your shell (same value as `.env`).
- [ ] `python3 scripts/reset_dev_tables.py --yes` → `RESET: ok ...` (this is the dev DDL path — `AGENT_FACTORY_DB_CREATE_TABLES=0` in dev, so app startup will not create tables, by design).
- [ ] `python3 scripts/verify_phase_a.py` → **`PHASE_A: PASS` before any harness edit.**

## Task 2 — Edit 1: expose the flag to tools (one line)

File: `agent_factory/runtime/sdk_runner.py`, function `_harness_run_context`. The dict currently starts:
```python
return {
    "profile_id": profile.profile_id,
    "run_id": run_id,
```
- [ ] After the `"profile_id": profile.profile_id,` line add:
```python
    "memory_enabled": bool(profile.memory.semantic_memory_enabled),
```

## Task 3 — Edit 2: recall injection (CORRECTED — harness refactored after recon round 2)

The original anchor (`sdk_instructions` local + `_with_response_preview_context` in `stream_turn`) no longer exists: instruction-building moved into `sdk_adapter.build_agent`, which resolves internally via `resolved_instructions = instructions or self.load_instructions(profile, ...)`. The memory block therefore rides through `build_agent` as an **optional kwarg** — the same optional-override pattern `instructions` itself uses. When the kwarg is None (all existing callers), behavior is byte-identical.

**(a)** File: `agent_factory/runtime/sdk_adapter.py`, method `build_agent`:
- [ ] Add a keyword-only parameter `memory_block: str | None = None` to the signature.
- [ ] Anchor: `resolved_instructions = instructions or self.load_instructions(`. After the **last** line that transforms or reassigns `resolved_instructions` (wrappers included, if any moved here), immediately before its final use constructing the agent, insert:
```python
        if memory_block and resolved_instructions:
            resolved_instructions = f"{resolved_instructions}\n\n{memory_block}"
```
Do not modify the existing resolution logic in any other way.

**(b)** File: `agent_factory/runtime/sdk_runner.py`, in `stream_turn`, immediately before the `self._sdk_adapter.build_agent(profile,` call:
- [ ] Insert:
```python
    _memory_block = None
    if profile.memory.semantic_memory_enabled:
        _user = getattr(effective_request, "user", None)
        if _user is not None:
            from agent_factory.memory.recall import build_memory_block

            _memory_block, _mem_count = await build_memory_block(
                profile.profile_id,
                _user.user_id,
                getattr(_user, "tenant_id", None) or "default",
            )
```
- [ ] and pass `memory_block=_memory_block` in the `build_agent(...)` call.
- [ ] `build_memory_block` returns a `(block, count)` tuple (the `count` feeds the optional recall indicator — see `docs/INDICATORS.md`). If you are NOT adding the indicator, you can ignore `_mem_count`; just keep the tuple-unpack so the call matches the current `recall.py`.
(Lazy import is deliberate: flag-off agents never import the memory package. `stream_turn` is async — the `await` is legal there; `build_agent` stays sync and DB-free.)

## Task 4 — Wire the `save_memory` tool (pinned by recon round 3)

**Primary path — register a pre-built custom tool at app wiring.** File: `agent_factory/api/app.py`. Anchor — the existing construction call:
```python
tool_registry = ToolRegistry(
    artifact_service=artifact_service,
    ...
)
```
- [ ] Immediately after that construction closes, insert:
```python
from agents import function_tool
from agents.tool_context import ToolContext
from agent_factory.memory.tool import TOOL_NAME, TOOL_DESCRIPTION, save_memory_impl

async def _save_memory(ctx: ToolContext, content: str, category: str = "note") -> str:
    """Save a durable fact about this user to persistent memory."""
    return await save_memory_impl(ctx, content, category)

tool_registry.register_custom_tool(
    TOOL_NAME,
    function_tool(
        _save_memory,
        name_override=TOOL_NAME,
        description_override=TOOL_DESCRIPTION,
    ),
)
```
Notes: imports may move to the module top if that matches `app.py` style. `function_tool` is the OpenAI Agents SDK's own (recon-confirmed — not a wrapper); do **not** pass `needs_approval` (defaults to False; approval only applies when explicitly passed). The `ctx: ToolContext` annotation is load-bearing — it's what tells the SDK this is the context parameter, not a tool argument.

Why this works (recon-verified chain): `plan_tools` resolves any profile-listed name found in `self._custom_tools` → `build_sdk_tools` fetches it via `_resolve_custom_tool` → appends it raw (custom tools bypass `tool_namespace`). Recon round 3's `TOOL_PATH: BUILDER-NEEDED` verdict only observed that no `register_custom_tool` call exists *today* — the insertion above **is** that call; every link of the resolution chain is confirmed in quoted code.

**Fallback variant (native builder)** — only if the registration above misbehaves in practice: in `agent_factory/tools/registry.py`, mirror `_build_workspace_sdk_tools` exactly: add `_MEMORY_TOOLS = frozenset({"save_memory"})` to the class constants and to the `known_tools` union in `build_sdk_tools`; add a `_build_memory_sdk_tools(self, function_tool, tool_context_cls, profile, plan)` method gated on `"save_memory" in plan.resolved` returning `[function_tool(_save_memory, name_override=TOOL_NAME, description_override=TOOL_DESCRIPTION)]`; aggregate it in `build_sdk_tools` next to the workspace block via `tool_namespace(name="memory", description="Persistent user-memory tools.", tools=memory_tools)`.

## Task 5 — Demo profiles

- [ ] `cp -r tests/fixtures/profiles/test-full profiles/` and `cp -r tests/fixtures/profiles/test-minimal profiles/`.
- [ ] **Profile-path correction:** the run script's `AGENT_FACTORY_PROFILE_PATHS` default points at the digit-triage/digit-studio profile dirs, NOT repo `profiles/`. Do not copy fixtures into the team's profile dirs — instead **export `AGENT_FACTORY_PROFILE_PATHS` to the repo `profiles/` path before launching** (the script default is only a fallback), and confirm both profiles load at startup.
- [ ] In `profiles/test-full/agent.profile.yaml`: set `memory.semantic_memory_enabled: true` (the section exists; currently `false`) and add `save_memory` under `tools: → function_tools:` (recon-confirmed yaml shape — a plain name list):
```yaml
tools:
  function_tools:
    - workspace.evaluate
    - workspace.apply_ops
    - save_memory
```
Leave `test-minimal` untouched (flag-off agent).
- [ ] Restart the backend process: `scripts/run-local-with-profiles.sh`.

## Task 6 — Phase A acceptance (GATE — report before Phase B)

Dev auth is bypassed (`DEPLOYMENT_ENVIRONMENT` ≠ prod, `AGENT_FACTORY_REQUIRE_AUTH` unset).

- [ ] POST `/api/v1/turns/stream`:
```json
{"profile_id": "test-full",
 "input": "Remember: I always want answers as exactly three bullet points, addressed to me by name. Save that.",
 "user": {"user_id": "console-user", "email": "console-user"},
 "runtime": {"execution_engine": "sdk"}}
```
Expect `tool.started`/`tool.completed` for `save_memory` in the SSE stream; then one row `source='tool'` in `agent_memory_entries`.
- [ ] Restart the backend process. New request, same profile+user, **no thread_id** (new thread), input `"Give me a quick status-update template."` → reply is three bullets, addressed by name.
- [ ] Isolation: same request with `"user_id": "user-b", "email": "user-b"` → no personalization. Same requests against `test-minimal` → no injection, and the "Remember..." turn there produces no `save_memory` call (tool not in its plan) — if the tool somehow fires, it must return the decline message.
- [ ] **Report in the format below. Stop. Do not start Task 7 until told to proceed.**

## Task 7 — Edit 3: post-turn extraction (Phase B)

**Anchor pre-check (do this read-only during Phase A and include PRESENT/MISSING in the Phase A report):** confirm the `if output_event.event == EventName.RESPONSE_COMPLETED:` block (with `result.cancel()`, the audit yield, and the RUN_COMPLETED yield) still exists in `stream_turn` after the instruction-building refactor. If missing, stop and report — do not improvise.

File: `agent_factory/runtime/sdk_runner.py`, in `stream_turn`, inside `if output_event.event == EventName.RESPONSE_COMPLETED:`. The block currently reads (abridged):
```python
    result.cancel()
    audit_payload = agt_audit_payload(...)
    if audit_payload is not None:
        yield event(EventName.GOVERNANCE_AUDIT, ...)
        sequence += 1
    yield event(EventName.RUN_COMPLETED, ..., final_output=final_output)
    return
```
- [ ] Between the end of the `if audit_payload is not None:` block and the `yield event(EventName.RUN_COMPLETED,` line, insert (do not touch `sequence` handling or the trailing `return`):
```python
    _user = getattr(effective_request, "user", None)
    if _user is not None and profile.memory.semantic_memory_enabled:
        from agent_factory.memory import _digit as _mem
        from agent_factory.memory.extraction import schedule_extraction

        schedule_extraction(
            _mem.Identity(
                profile.profile_id,
                _user.user_id,
                getattr(_user, "tenant_id", None) or "default",
                thread_id,
            ),
            str(effective_request.input),
            final_output,
        )
```
(`final_output` is already a string here — `_serialize_final_output(...)` or `"".join(streamed_text_chunks)`.)

- [ ] Optional cost control: `export AGENT_FACTORY_MEMORY_MODEL=gpt-5.4-mini` (else defaults to `get_model_name()` → `gpt-5.4` in dev).
- [ ] `python3 scripts/verify_phase_b.py` → **`PHASE_B: PASS`** (live model call included now).
- [ ] Live acceptance: `test-full`, new thread, input `"By the way, I work on the payments reconciliation team."` → let the turn fully complete, wait ~15s → one `source='extraction'` row. Then a chit-chat turn (`"thanks, that's all!"`) → no new row. (Known limitation: if the client disconnects mid-stream, extraction for that turn may not run — do not chase this as a bug.)

## Fallback ladder (take the highest rung that works, report which)

1. Full build (Tasks 1–7).
2. Phase A only (Tasks 1–6) — the headline demo is fully covered.
3. Injection + seeded rows (`python3 scripts/seed_demo.py --profile test-full --user console-user`) — if tool wiring is blocked entirely.

## Report format (paste-able, one screen, no code dumps)

```
MEMORY BUILD REPORT — Phase A|A+B
WIRING: base=.. session=.. identity=.. flag=.. llm=..
PHASE_A: PASS|FAIL   PHASE_B: PASS|PARTIAL|FAIL|SKIPPED
harness edits:
  - sdk_runner.py _harness_run_context: +1 line OK|FAIL
  - sdk_runner.py stream_turn injection: +N lines OK|FAIL
  - tool wiring (<site>): OK|FAIL (variant: custom|builder)
  - sdk_runner.py stream_turn extraction: +N lines OK|FAIL|SKIPPED
  - profiles: test-full flag+tool OK|FAIL, test-minimal copied OK|FAIL
acceptance:
  save via tool: OK|FAIL     rows source=tool: <n>
  restart + new-thread recall: OK|FAIL
  user-b isolation: OK|FAIL  flag-off agent: no injection OK|FAIL, no save OK|FAIL
  extraction row: OK|FAIL|SKIPPED   chit-chat writes nothing: OK|FAIL|SKIPPED
fallback rung used: 1|2|3
blockers/notes: <≤3 lines>
```
