# Reconciliation — transfer repo mirrored to pod state (post round 6)

The pod dumped the full deployed `src/agent_factory/memory/` package + the
memory-demo profile (`reconciliation_dump`, OCR'd). Diffed against this repo;
from here on **this repo is the single authoring base** — the pod state and
this repo are semantically identical as of branch commit `c4336de`
(fresh divergence count at dump time: dev 117 ahead / branch 5 ahead).

## Deltas applied here (pod → transfer)

1. **`memory/store.py`** — the `_persist` hardening (commit `123a92c`):
   entry fields split from the embedding value; insert wrapped in
   `try/except SQLAlchemyError` that retries **without** the embedding when a
   vector/bytea column-type mismatch (env drift across processes) breaks the
   write. New `_persist(entry_fields, embed_value, supersede_target)` helper
   owns the session/flush/supersede/commit block.
2. **`profiles/memory-demo/agent.profile.yaml`** — demo perf fix (`123a92c`):
   `model.default: gpt-5.4-mini`, `reasoning_effort: none`
   (130s → 5–15s turns), and the `ui.stream_events` declarations for
   `memory.recalled` / `memory.learned` restored (the pod ships them; the
   `ui_event_tool` guard in `c4336de` reserves both names as harness-owned).
3. **`memory/_digit.py`** — `BUILD = "2026-07-16.7-reconciled"`. Lineage: the
   pod still logs `2026-07-08.5-visible-logs` because the calibrated-floor
   edits were made surgically on-pod without a bump, and the off-pod
   `07-09.6` bump was never pulled. The next pod sync picks up this marker.

## OCR ambiguities — RESOLVED by the W0 GATE 3 parity diff (real git diff, no OCR)

- `EMBED_TIMEOUT_SECONDS = 5.0` confirmed correct (parity flagged nothing in
  `_digit.py` beyond the BUILD line).
- `memory.learned` payload has **no** `summary` property on the pod — the
  mirrored guess was removed here.
- Comment reconstructions replaced with the pod's verbatim text from the
  GATE 3 hunks (`semantic.py` threshold block + `T_DECIDE_FLOOR` line,
  `store.py` SQLAlchemyError block — which really does contain
  `(USE_PGVECTOR=%s, dim=%s)` in the comment — and the yaml model/ui blocks).
- Package parity at GATE 3: `_digit.py` differed only at the BUILD line
  (synced on-pod as commit `2fc2dbb`); all other diffs were comment-only and
  are now back-ported, so the next parity check should be exact.
