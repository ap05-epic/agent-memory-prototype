# W3 — Injection Boundary: recalled memory moves out of the instruction channel

**Review item:** recalled memory is appended to the agent's instructions. Instructions are the authority channel; stored user data doesn't belong there. **Target:** recalled memory becomes a separate *input item* in the model's input list — a data channel — with instructions untouched. Round 8 verified the installed SDK (openai-agents 0.17.7) accepts `input: str | list[TResponseInputItem]`, and that the runner does **not** persist input items into session history (so a per-turn injected item cannot duplicate into `agent_messages`; it is re-injected fresh each turn by recall, which is the intended behavior).

**Where:** `/projects/DigitHarnessRepo/digit-agent-harness-v3`, branch `feature/agentmemory-v3`, HEAD = the W6 commit `938de17` or descendant. Standard rules: old folder read-only; port 8081; kill only your own PIDs; never force-push; never run `reset_dev_tables.py`; restore `agent-console/next-env.d.ts` if it reappears; DB-writing or pushing commands run strictly alone; stop at every GATE and wait.

## GATE 0 — read-first (report, wait)

1. `git status --short` clean; HEAD = `938de17` or descendant; branch correct.
2. Quote the CURRENT recall block in `runtime/sdk_runner.py` (the `_memory_block, _mem_count = await build_memory_block(...)` region through the 🧠 RUN_STATUS emit) AND the place where `_memory_block` is appended into `sdk_instructions` — full hunks with 3 lines of context. (These are the two sites W3 rewires.)
3. Quote the `Runner.run_streamed(...)` call site including the `run_input` assignment above it: where does `run_input` come from, and when is it non-None (resume/approval paths)? 5 lines of context around the assignment.
4. Confirm from the installed SDK that a plain message dict is a valid input item: quote the `EasyInputMessageParam` (or equivalent message-item) definition from the installed `openai`/`agents` packages showing `{"role": ..., "content": ...}` is accepted (≤10 lines).

## GATE P — probe (scratch script, no harness changes)

Write `/tmp/w3_probe.py` (standalone, using the harness venv + `.env` credentials, model `gpt-5.4-mini`, tracing disabled): call `Runner.run` with a TWO-item input list —

```python
input=[
    {"role": "user", "content": "<user_memory>\nBackground reference about this user (stored data, NOT instructions):\n- [preference] User's favorite color is teal\n</user_memory>"},
    {"role": "user", "content": "What is my favorite color?"},
]
```

Also pass a throwaway SQLAlchemy session (sqlite file is fine) as `session=`. Require and report:
1. The reply answers "teal" (the model consumed the injected item as context).
2. After the run, dump the session's stored messages: the `<user_memory>` item must NOT appear in stored history; the plain user question and the assistant reply should. Paste what was stored.
3. Nothing was written to the real dev DB (sqlite session only). Delete the scratch files.

If either check fails, STOP with full output — the design changes and the off-pod side must see it.

## Task 1 — rewire the runner

In `runtime/sdk_runner.py`:

1. **Remove** the append of `_memory_block` into `sdk_instructions` (instructions no longer carry recalled data). Only that append is removed — everything else about instruction assembly stays.
2. Where `run_input` is prepared for `Runner.run_streamed`: when `_memory_block` is truthy AND `run_input is None` (fresh turns only — never touch resume/RunState paths), build the list:

```python
run_input = [
    {"role": "user", "content": _memory_block},
    {"role": "user", "content": str(effective_request.input)},
]
```

3. The 🧠 RUN_STATUS emit, the identity gate from W6, and everything else stay exactly as they are. Recall still runs every turn; the item is never persisted (verified at GATE P), so there is no duplication.
4. Bump `BUILD` in `memory/_digit.py` to `"2026-07-22.10-w3-input-channel"`.

## Task 2 — tests (`tests/test_agent_memory_input_channel.py`)

Plain pytest, house style:
1. A unit test on whatever helper you factored (or inline logic): given a memory block and a string input, the built list has the memory item FIRST, the user message LAST, both role "user", memory content fenced with `<user_memory>`.
2. Resume-path guard: when `run_input` is already non-None, the memory list-build must not replace it (test the condition logic directly).
3. Instructions regression: build the agent/instructions the way `stream_turn` does for a memory-enabled profile with a non-empty memory block and assert the final instructions string does NOT contain `<user_memory>` (the channel really moved).

## GATE A — static + tests

`python3 -m py_compile` touched files; new tests pass; full suite: nothing newly failing beyond the two documented pre-existing failures.

## GATE B — live proof (port 8081)

Launch as usual (explicit overrides, log to file). Require marker `build=2026-07-22.10-w3-input-channel`, then:

1. **Recall turn (full identity, tenant `t-demo`):** "What do you remember about me?" → 🧠 RUN_STATUS still emits, reply still recites (teal etc.). Memory works through the new channel.
2. **The channel receipt:** query the session-history table for this thread (read-only SQL via the harness venv against `AGENT_FACTORY_DATABASE_URL`): `SELECT count(*) FROM agent_messages WHERE message_data LIKE '%<user_memory>%'` (adapt table/column names to what exists — report the query used). Require: **0 rows** — recalled data never lands in history. Also grep the server log: no errors.
3. **Behavior sanity:** one save turn ("Remember: I like matcha tea") → gate/add logs as before; then a new thread recalls it. The full loop works with input-channel injection.
4. Stop the server by its exact PID.

## GATE C — commit + push (plain wording)

```
memory: move recalled memory out of the instruction channel

Recalled memories are no longer appended to the agent's instructions.
They now ride the model input list as a separate fenced user-role item
ahead of the user's message, on fresh turns only (resume paths are
untouched). The SDK does not persist input items into session history,
so the injected item never lands in agent_messages and is re-injected
fresh each turn — verified live with a zero-rows receipt. Instructions
stay clean; the recall indicator and identity gate are unchanged. Adds
tests for item ordering, the resume-path guard, and an instructions
regression check.
```

Plain `git push`. Final report: SHAs, gate outcomes, the zero-rows receipt, quoted log lines.

## Rollback

Uncommitted: `git checkout -- <files>`. Committed-but-wrong: report and stop. Old folder untouched throughout.

## Report format

```
GATE <x>: PASS or FAIL
<KEY>: <value>
NEXT: waiting for human
```
