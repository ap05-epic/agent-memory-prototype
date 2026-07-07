# Memory Indicators — Design & Implementation (recon round 4 confirmed)

Goal: make memory activity **visible in the console** — a small status line when the agent recalls or saves something — the way other assistants show a "Memory updated" chip.

## What recon round 4 settled

The console does **not** dispatch on the `renderer` field of `ui.stream_events`. `agent-console/components/agent-console.tsx::activityFromHarnessEvent` switches on the event **name** against a fixed list; an unrecognized event returns `null` and is dropped. So declaring `memory.recalled` with `renderer: status` in a profile renders **nothing** — a branded custom chip would require changing the console (a separate Next.js app, another team, out of scope).

But the console **does** render `run.status`:
```tsx
if (event === "run.status") {
  return { kind: "status", label: String(payload.message ?? payload.text ?? "Run status"), status: "info" };
}
```
And recon confirmed emitting is reachable from `stream_turn` (`EMIT_FROM_STREAM_TURN: YES`) — the harness already yields `run.status` there for other notices. So the memory indicator is: **emit a `run.status` event with a `message` from the recall path.** Zero console changes.

| Moment | Indicator |
|---|---|
| **Save** (agent stores something) | **Already visible** — `save_memory` renders as a `tool.started`/`tool.completed` chip (`emit_tool_events: true`). Optional one-line polish below. |
| **Recall** (agent uses stored memory) | **New:** emit `run.status` — "🧠 Recalled N memories" — at turn start. This is the build. |
| **Learn** (background extraction) | Runs after `RUN_COMPLETED`, the stream is closing — can't emit live. Fold into the *next* turn's recall status, or skip. |

## Implementation — the recall indicator

Prereq already done in this repo: `memory/recall.py::build_memory_block` now returns `(block, count)`. Re-copy the package so the pod has it: `git pull` then `cp -r <repo>/src/agent_factory/memory` (or just the updated `recall.py`) into `src/agent_factory/memory`.

Then one edit in `agent_factory/runtime/sdk_runner.py`, `stream_turn` — this **replaces** the Task 3b block from the original build (which called `build_memory_block` expecting a string):

```python
    _memory_block = None
    if agent is None and profile.memory.semantic_memory_enabled:   # keep the deployed guard as-is
        _user = getattr(effective_request, "user", None)
        if _user is not None:
            from agent_factory.memory.recall import build_memory_block

            _memory_block, _mem_count = await build_memory_block(
                profile.profile_id,
                _user.user_id,
                getattr(_user, "tenant_id", None) or "default",
            )
            if _memory_block:
                yield event(
                    EventName.RUN_STATUS,
                    run_id=run_id,
                    thread_id=thread_id,
                    sequence=sequence,
                    message=f"\U0001F9E0 Recalled {_mem_count} saved "
                            f"{'memory' if _mem_count == 1 else 'memories'}",
                )
                sequence += 1
```
Then pass `memory_block=_memory_block` into `build_agent(...)` as before. Only the *body* changes (tuple-unpack + the new `yield`); the surrounding `if agent is None and ...` guard and the `build_agent(..., memory_block=_memory_block)` call stay exactly as deployed.

Notes:
- `EventName.RUN_STATUS` and the `event(...)` helper are already imported in `sdk_runner.py` (the repaired-tool-call notice uses the same pattern). If `RUN_STATUS` isn't imported in scope, use the string form `event("run.status", ...)` — recon confirmed `event(name: EventName | str)` accepts a raw string.
- `sequence` must be incremented after the yield (the surrounding code relies on monotonic `sequence`); mirror the adjacent `sequence += 1` sites exactly.
- This yields **before** the model runs, so the status appears at the top of the turn, then the answer streams.

## Optional one-line polish — the save chip

In `memory/tool.py`, make the success return read like a chip label so the tool.completed chip is self-explanatory:
```python
"saved": "✓ Saved to memory.",
```
(Currently "Saved to persistent memory." — cosmetic only.)

## The learn indicator (documented, not built)

Extraction is fire-and-forget after `RUN_COMPLETED`; the stream is gone, so it cannot emit into the turn that triggered it. Two honest options, neither on the critical path:
1. **Skip live** — its proof is the DB row / `verify_phase_b`. (Recommended.)
2. **Fold into the next recall** — have the recall status say "Recalled N memories (1 new since we last talked)" by tracking a last-seen marker. Adds state; do it only if the team wants an autonomous-learning signal in the UI.

## Bottom line

Ship the recall `run.status` indicator (one `stream_turn` edit + the already-made `recall.py` change) and, if you like, the one-line save-chip polish. Both are console-change-free and low-risk. The demo works without any of it — this is polish that makes the invisible recall moment visible.
