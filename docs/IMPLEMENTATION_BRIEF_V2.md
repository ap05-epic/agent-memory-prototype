# Implementation Brief — Memory v2 (semantic retrieval + supersede writes)

> **RESUME NOTE (after the first build session):** Tasks 1–4 are DONE on the pod (pgvector installed, package synced, columns added as `vector(1536)`, query_text edit applied, Phase A+B PASS). The first session correctly stopped on a Phase C failure — two bugs in the *transfer repo* (an 8-dim test stub incompatible with the live vector(1536) column, and missing Azure-env bridging in standalone scripts), both now fixed upstream. **To resume:** `cd /projects/agent-memory-prototype && git pull` → re-run the Task 2 `cp -r` sync → re-run `backfill_embeddings.py` (expect embedded=5 now) → run the three gates (Phase C should PASS with `live_embedder=ok dim=1536`) → proceed to Task 6 acceptance. Keep `AGENT_FACTORY_MEMORY_PGVECTOR=1` — do NOT flip it to 0 (see corrected fallback ladder).

**You are the implementation agent on the pod, harness repository open.** Memory v1 is live and demonstrated; **do not regress it**. The entire v2 is already written and gate-verified in the transfer repo (`/projects/agent-memory-prototype`) — your job: install one package, sync the memory package, run one additive schema upgrade, make **one one-line harness edit**, set env, run the gates, and report. Recon round 5 confirmed: pgvector **0.8.0 is already installed** in the database, and the working embedding deployments are `text-embedding-3-large` (use with `dimensions=1536`) and `text-embedding-ada-002` (fallback).

## Non-negotiable rules

- Never log/print memory content — ids, counts, statuses only. Never print API keys.
- v1 behavior is the floor: if any v2 step fails, the fallback keeps the system on the previous behavior — never leave it broken.
- The live table `agent_memory_entries` has real rows. `upgrade_v2_columns.py` is additive-only; do NOT run `reset_dev_tables.py` unless explicitly told (it drops data).
- If an anchor is missing or a gate fails twice for the same cause: stop and report.

## Task 1 — Python dependency

- [ ] `pip install pgvector` in the harness venv → then `python3 -c "import pgvector; print('ok')"`.
- [ ] **If the index/proxy refuses the install:** do not fight it. Set `AGENT_FACTORY_MEMORY_PGVECTOR=0` everywhere below instead of `1` (the package then uses a BYTEA column + Python-side similarity — rung 2 — and everything still works). Note it in the report.

## Task 2 — Sync the package & set env

- [ ] `cd /projects/agent-memory-prototype && git pull`
- [ ] `cp -r /projects/agent-memory-prototype/memory/. /projects/DigitHarnessRepo/digit-agent-harness/src/agent_factory/memory/`
- [ ] Add to the launch environment (the same block that clears the stale `AZURE_OPENAI_BASE_URL` — see DEMO_RUNBOOK):
```
export AGENT_FACTORY_MEMORY_PGVECTOR=1          # 0 if Task 1 fell back
export AGENT_FACTORY_MEMORY_EMBED_MODEL=text-embedding-3-large
export AGENT_FACTORY_MEMORY_EMBED_DIM=1536
export AGENT_FACTORY_MEMORY_MODEL=gpt-5.4-mini
```
These must be set in the shell **before running any script below and before launching the backend** (the embedding column type is chosen at import time from `AGENT_FACTORY_MEMORY_PGVECTOR`).
- [ ] `PYTHONPATH=src python3 -c "from agent_factory.memory import _digit; print(_digit.WIRING)"` → imports clean, `embed=True`.

## Task 3 — Additive schema upgrade (live table, no drops)

- [ ] From the harness repo root (env from Task 2 exported, `.env` sourced for the DB URL):
  `python3 scripts/upgrade_v2_columns.py --yes` (script lives in the transfer repo's `scripts/`; run it from wherever you placed them, as with the v1 scripts)
  → expect `UPGRADE_V2: ok dialect=postgresql added=embedding,superseded_by,observed_at`.
- [ ] `python3 scripts/backfill_embeddings.py` → embeds the existing rows (expect `BACKFILL: ok embedded=5 ...`, count may differ).

## Task 4 — The one harness edit (recall becomes query-aware)

File: `agent_factory/runtime/sdk_runner.py`, in `stream_turn` — the deployed recall block from the indicator work reads:
```python
            _memory_block, _mem_count = await build_memory_block(
                profile.profile_id,
                _user.user_id,
                getattr(_user, "tenant_id", None) or "default",
            )
```
- [ ] Add one keyword argument so retrieval can rank by relevance to the incoming message:
```python
            _memory_block, _mem_count = await build_memory_block(
                profile.profile_id,
                _user.user_id,
                getattr(_user, "tenant_id", None) or "default",
                query_text=str(effective_request.input),
            )
```
(`str(effective_request.input)` is the exact expression the deployed extraction hook already uses — proven live.) Nothing else in the harness changes.

## Task 5 — Gates (in this order)

- [ ] `python3 scripts/verify_phase_a.py` → **PHASE_A: PASS** (v1 unregressed).
- [ ] `python3 scripts/verify_phase_b.py` → **PHASE_B: PASS**.
- [ ] `python3 scripts/verify_phase_c.py` → **PHASE_C: PASS**, and with the env set the last line should read `live_embedder=ok dim=1536` (a real embedding call). If live_embedder says skipped, the env vars aren't reaching the process — fix before continuing.

## Task 6 — Live acceptance (restart backend with the full launch block first)

- [ ] **Semantic recall beat:** on `memory-demo` as one user, save three memories on *different topics* across turns (e.g. "answers as three bullets", "works on payments reconciliation", "prefers Python over Java examples"). New thread, ask a **topical** question ("What language should this example use?") → the 🧠 indicator fires and the reply reflects the *relevant* memory (Python), demonstrating relevance-ranked recall rather than just recency.
- [ ] **Supersede beat:** say `Remember: actually I want answers as five bullet points now, not three.` → then check the DB:
  `SELECT content, discarded_at IS NOT NULL AS retired, superseded_by FROM agent_memory_entries WHERE user_id='console-user' ORDER BY created_at;`
  → the old three-bullets row shows `retired=true` with `superseded_by` pointing at the new row. New thread, neutral ask → reply uses **five** bullets.
- [ ] **Isolation unchanged:** one user-b curl → still no personalization.
- [ ] Report `scope_metrics` via:
  `PYTHONPATH=src python3 -c "import asyncio; from agent_factory.memory.store import scope_metrics; print(asyncio.run(scope_metrics('memory-demo','console-user')))"`

## Fallback ladder (highest rung that works; report which)

1. Full v2: pgvector rung 1 + supersede + query-aware recall.
2. `AGENT_FACTORY_MEMORY_PGVECTOR=0`: BYTEA + Python similarity (rung 2) — **only valid BEFORE the vector column exists** (i.e., if Task 1's pip install had failed and the upgrade had created BYTEA). Once the live column is `vector(1536)` — which it now is — flipping the flag mismatches the column type; converting to BYTEA would be a deliberate ALTER, not an env flip. On this pod: stay on 1.
3. Skip Task 4 (no query_text): v2 writes/supersede still land; recall stays recency-based (v1).
4. Anything else failing → revert env vars; v1 keeps running untouched.

## Report format (one screen, no code dumps)

```
MEMORY V2 BUILD REPORT
pgvector-py: INSTALLED|FALLBACK-BYTEA   env: PGVECTOR=1|0, model=..., dim=...
UPGRADE_V2: ok|FAIL (added=...)         BACKFILL: embedded=<n>
PHASE_A: PASS|FAIL  PHASE_B: PASS|FAIL  PHASE_C: PASS|FAIL (live_embedder=...)
harness edit (query_text kwarg): OK|FAIL
acceptance:
  semantic recall (topical beats recent): OK|FAIL
  supersede chain (retired=true + superseded_by set): OK|FAIL
  five-bullets recall after supersede: OK|FAIL
  user-b isolation: OK|FAIL
scope_metrics: {live=.., discarded=.., superseded=.., embedded=..}
fallback rung: 1|2|3|4
blockers/notes: <≤3 lines>
```
