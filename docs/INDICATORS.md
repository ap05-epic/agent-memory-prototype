# Memory Indicators — Design & Brief

Goal: make memory activity **visible in the console**, the way other assistants show a "Memory updated" chip — so the user can see when the agent saves, recalls, or learns something, instead of it happening invisibly.

## What we mean, and what already works

Three moments where memory is "touched":

| Moment | When | Already visible? |
|---|---|---|
| **Save** (explicit tool) | mid-turn, agent calls `save_memory` | **Yes** — renders as a `tool.started`/`tool.completed` chip when `observability.emit_tool_events: true` (the memory-demo profile sets this). |
| **Recall** (injection) | turn start, stored memories added to the prompt | **No** — invisible; the agent just "knows" things. |
| **Learn** (extraction) | after the turn, background capture | **No** — happens after the stream closes. |

Two things need no code at all:
- **Save is already a visible chip.** In the live run you saw `save_memory` fire in the transcript.
- **"What do you remember about me?"** — the agent recites its injected memory block on request. A zero-code way to prove recall in the demo.

The valuable add is a **recall indicator**: a small "🧠 Recalled N memories" line at the start of a turn when memory was injected. That makes the invisible magic visible — the single most demo-enhancing signal.

## The mechanism (grounded in the real profile schema)

DIGIT already ships a first-class custom-UI-event system. From `tests/fixtures/profiles/test-full/agent.profile.yaml`:

```yaml
ui:
  stream_version: 1
  fallback_renderer: artifact
  stream_events:
    - event: test.card
      description: Test card event for unit testing.
      renderer: test-card
      payload_schema: { type: object, required: [card_type, data], properties: {...} }
```

So a profile **declares** custom stream events (name + renderer + payload schema); the backend **emits** them on the SSE stream; the console **renders** them via the named renderer. This is the same machinery that renders tool calls — we are not inventing a surface, we are using one that exists.

`_harness_run_context` (the per-turn context dict) already carries a `ui_event_emitter_key` — the hook backend code uses to emit these events. The `memory-demo` profile already declares `memory.recalled` and `memory.learned` under `ui.stream_events`.

## Two facts to pin first (recon — GPT-5.4, ~10 min)

We can see the *declaration* side but not the *emit* side (the harness `src/` wasn't in the snapshot). Two questions:

**R1 — the emit API.** How does backend code emit a profile-declared `ui.stream_events` event? Find where `ui_event_emitter_key` is consumed and how a custom event (e.g. `test.card`) is emitted from harness code. Quote the emit function/signature (≤10 lines). Is it reachable from inside `stream_turn` (where we inject recall) — i.e., can we call `yield event("memory.recalled", ...)` or an emitter helper there?

**R2 — the renderer registry.** What renderers does the console ship (the values usable in `renderer:`)? Grep the console for how `stream_events[].renderer` is dispatched and list the built-in renderer names (is there a `status`/`chip`/`text` renderer, or only the `test-*` ones?). This decides whether our `renderer: status` works or needs a different value / the `fallback_renderer`.

## Implementation (once R1/R2 are pinned)

**Recall indicator (the star).** In `sdk_runner.py stream_turn`, where Task 3b computes `_memory_block` (we already have `profile`, `run_id`, `thread_id`, the emitter key, and — from the store — the entry count): if the flag is on and the block is non-empty, emit one event before/at the first yield:

```python
# after building _memory_block, when it is non-empty
<emit>("memory.recalled", run_id=run_id, thread_id=thread_id,
       count=<n entries injected>, summary="Recalled saved preferences")
```
`build_memory_block` would return (block, count) — a one-line change in `recall.py` — or the count comes from a cheap `count_entries`. The console shows "🧠 Recalled N memories" at turn start.

**Save indicator.** Already works. Optional polish: make `save_memory`'s return string read like a chip label ("✓ Saved to memory: <short content>") so the tool chip is self-explanatory — a one-line change in `memory/tool.py`, no new event.

**Learn indicator (honest limitation).** Extraction runs *after* `RUN_COMPLETED`, fire-and-forget, when the SSE stream is already closing — so it **cannot reliably emit to the current turn's stream**. Three options, cheapest first:
1. **Skip it live.** The save chip + recall chip already cover the two in-turn moments; extraction's proof is the DB row / `verify_phase_b`. (Recommended — lazy and honest.)
2. **Surface it on the *next* turn's recall** ("🧠 Recalled N memories (1 new since we last talked)") — piggybacks on the recall indicator, no new stream problem.
3. **Emit an optimistic "processing memories…" event before `RUN_COMPLETED`** — but it can't say *what* was learned yet, so it over-promises. Not recommended.

## Recommendation (right-sized)

Ship the **recall indicator** (R1+R2 then ~15 lines) and the **save return polish** (1 line). Both are in-turn, low-risk, and turn the invisible parts of the demo into visible chips. Treat the learn indicator as option 1 (skip live) or option 2 (fold into recall) — do **not** build option 3. The `memory-demo` profile already declares the events; activating them is the only remaining work.

This is a clean follow-on, not a blocker: the demo works today without any of it. Hand R1/R2 to GPT-5.4, then the ~16-line implementation to GPT-5.4 as well (it's mechanical once the emit API is known).
