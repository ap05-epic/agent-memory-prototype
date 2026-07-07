# Recon Round 4 — Memory Indicators: emit API + renderer registry (2 questions)

You are doing **READ-ONLY** recon on this harness repo. Do NOT edit or create anything except the one answers file below, and do NOT run code — just read and report.

## RETURN CHANNEL

Write your full answer to `recon_round_4_answers.md` in the workspace, quoting real code verbatim (do not paraphrase). If returning via screenshots instead: numbered `Q<n>:` answers, identifiers on their own line, code quotes ≤10 lines.

## Context

We're adding console **indicators** for the memory feature — small "chip" events the console shows when memory is recalled or saved (like a "Memory updated" chip). The harness already has a custom-UI-event system: profiles declare events under `ui.stream_events` (each with a `renderer` and a `payload_schema` — see `tests/fixtures/profiles/test-full/agent.profile.yaml`), the backend emits them, the console renders them. We need to know exactly how to emit one from backend code, and which renderers the console ships.

## Q1 — THE EMIT API

Find how backend code emits a profile-declared `ui.stream_events` custom event.
- Start from `ui_event_emitter_key` (a key in the `_harness_run_context` dict in `sdk_runner.py`) and grep for where it is **consumed**.
- Also grep for `stream_events`, and for how the `event(...)` helper / `EventName` enum handle a **custom (non-enum)** event name.
- Quote the emit function/helper and its signature (≤10 lines).
- **CRITICAL:** is emitting reachable from inside `SdkRunnerAdapter.stream_turn` (where `profile`, `run_id`, `thread_id`, and the emitter key are in scope)? Show the exact call shape to emit a custom event named e.g. `"memory.recalled"` with a small payload from there.

## Q2 — THE RENDERER REGISTRY

Find what renderer names the console supports for `ui.stream_events[].renderer`.
- Grep the console (`agent-console/`) for where `stream_events` / `renderer` is dispatched to a component, and list the built-in renderer names.
- Is there a generic `status` / `chip` / `text` / `badge` renderer usable for a one-line memory indicator, or only the `test-card` / `test-status` ones from the test fixtures?
- What happens to an event whose `renderer` isn't recognized — does it fall back to `fallback_renderer`, or is it dropped?

## Final lines (end with exactly these two)

```
EMIT_FROM_STREAM_TURN: YES | NO
RENDERER: <best existing renderer name for a one-line memory chip, or NONE-FOUND>
```
