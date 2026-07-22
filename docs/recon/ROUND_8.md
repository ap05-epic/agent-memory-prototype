# Recon Round 8 — MC2 ground truth (injection channel, background work, API surface)

You are the on-pod recon agent. **READ-ONLY** — no edits, no state changes. Run inside `/projects/DigitHarnessRepo/digit-agent-harness-v3` (branch `feature/agentmemory-v3`, HEAD `938de17` or descendant). Write the full answer to `recon_round_8_answers.md` — flat text, real code quoted verbatim, no nested fences, never print secrets.

Context: merge candidate 1 is in review. Candidate 2 moves recalled memory out of the instruction string and into the model-input channel, makes extraction durable, and adds governed memory APIs. This round pins the facts those briefs need.

## Block A — the SDK input channel (W3: injection boundary)

**A1.** `pip show openai-agents` — report the exact installed version and location.

**A2.** In the INSTALLED SDK (site-packages), find `Runner.run_streamed` (and `Runner.run`): quote the signature and the type of its `input` parameter. If it accepts a list, quote the definition of the item type (`TResponseInputItem` or equivalent) — what item shapes exist (role messages, function_call_output, etc.), ≤25 lines total.

**A3.** On our branch, quote where the turn's `input` is passed to the SDK in `stream_turn` (the actual `Runner.run_streamed(...)` call with surrounding 10 lines). Today `effective_request.input` is a string — confirm whether anything anywhere already passes a LIST as input.

**A4.** Sessions: which session class does the harness use when `memory.session_backend: sqlalchemy` (quote where it's constructed), and in the INSTALLED SDK's session implementation, quote the code that decides WHAT gets persisted to session history each run — specifically: are the run's INPUT items written to history? (This decides whether an injected memory item would duplicate into `agent_messages` every turn — the core W3 design risk.) ≤30 lines.

**A5.** Compaction interplay: quote where `compaction_enabled` / `compaction_mode` from MemoryPolicy affect the session or input assembly on our branch (≤15 lines). One line verdict: would a per-turn injected input item survive/duplicate/vanish under compaction mode "auto"?

## Block B — background work + shutdown (W4: durable extraction)

**B1.** `ProfileHealthMonitor` appears in the health payload as a running service. Quote how it is constructed, started, and STOPPED across app startup/shutdown (create_app + lifespan sections, ≤30 lines). This is the template for an in-app background loop with graceful shutdown.

**B2.** Quote the app `lifespan` shutdown sequence in full (what gets closed, in what order — database close, monitor stop, anything task-related, ≤25 lines).

**B3.** Are there any other `asyncio.create_task` / background-loop patterns in `src/agent_factory` besides the health monitor and our memory `schedule_extraction`? `grep -rn "create_task" src/agent_factory --include=*.py` — list hits with one line of context each.

## Block C — API + events surface (W2: governed memory APIs)

**C1.** Quote ONE representative user-facing GET endpoint from `app.py` end to end: the decorator, auth/validation dependencies, query params, and its return shape (≤25 lines). Prefer something thread- or run-scoped (closest analog to "list my memories").

**C2.** How is API authentication applied on current dev — quote `_api_auth_required` (or successor) and show how a route opts in (≤15 lines).

**C3.** In the console (`agent-console/`), quote ONE proxy route that fronts a harness API (the file under `app/api/harness/...` for the C1 endpoint or similar, ≤20 lines) — the pattern a memory inspect/delete proxy would follow.

**C4.** Events: where is `EventName` defined — quote the enum entries that exist today (just the names), and quote ONE place a governance/audit-grade event is constructed and yielded in the runner (the `_agt_audit_payload` → GOVERNANCE_AUDIT flow, ≤20 lines). Confirm whether `memory.recalled` / `memory.learned` appear anywhere as event names on this branch (grep).

**C5.** The `ui_event_tool` guard from our c4336de commit (`_HARNESS_OWNED_EVENTS`): quote it as it exists on the v3 branch (≤10 lines) — W2 will emit those events from the harness side.

## Final verdict lines (end with exactly these)
```
SDK-INPUT: <str-only | list accepted: item types, one line>
SESSION-PERSISTENCE: <are input items written to history: yes/no + one line>
WORKER-TEMPLATE: <one line: what pattern W4's outbox loop should copy>
API-TEMPLATE: <one line: endpoint + auth + proxy pattern to mirror>
SURPRISES: <up to 3 lines, or "none">
```
