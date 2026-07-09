# Implementation Brief — Memory v2 (semantic retrieval + supersede writes)

> **RESUME NOTE 5 — CLEAN ROOM (the definitive run).** Session 5 solved the whole mystery chain with evidence: (a) the earlier failures were phantom — a **stale uvicorn (pid 73569)** owned :8080 and served old code; (b) the BUILD/`memory gate:` lines could never appear because uvicorn doesn't surface the `agent_memory` logger — **fixed: the package now attaches its own stderr handler**, so with `2>&1` into a file the lines ARE captured (new `BUILD=2026-07-08.5-visible-logs`); (c) your reconstructed payload omitted `"runtime": {"execution_engine": "sdk"}`, so the harness ran its **placeholder engine** (no agent, no tools, no memory) — the exact curls are inline below; never rebuild payloads from OpenAPI. Protocol:
>
> 1. `cd /projects/agent-memory-prototype && git pull` → re-run the Task 2 `cp -r` sync.
> 2. **Kill ALL harness backends** (the coordinator has paused other sessions; every `uvicorn agent_factory.api.app` process is ours): `pkill -f "uvicorn agent_factory.api.app"` → wait 2s → `ss -ltnp | grep ':808'` must show nothing on 8080/8081.
> 3. Launch ONE backend on 8080 with the full block, PYTHONPATH, and file-captured stderr:
>    the usual `unset`/exports (launch fix, PORT=8080, AGENT_FACTORY_PROFILE_PATHS, the 4 memory vars) **plus `export PYTHONPATH=/projects/DigitHarnessRepo/digit-agent-harness/src`**, then `scripts/run-local-with-profiles.sh > /tmp/mem-r5.log 2>&1 &`.
> 4. **Identity (now satisfiable):** `grep 'agent_memory seam loaded build=2026-07-08.5-visible-logs' /tmp/mem-r5.log` must match, and the `ss -ltnp '( sport = :8080 )'` PID must be your process. Do not proceed otherwise.
> 5. Cleanup: retire all bullet rows for the acceptance user (same UPDATE as before).
> 6. The two turns — **run these EXACTLY as written**:
> ```
> curl -sS -N -X POST http://127.0.0.1:8080/api/v1/turns/stream -H 'Content-Type: application/json' \
>   -d '{"profile_id":"memory-demo","input":"Remember: I always want answers as exactly three bullet points.","user":{"user_id":"console-user","email":"console-user"},"runtime":{"execution_engine":"sdk"}}'
> curl -sS -N -X POST http://127.0.0.1:8080/api/v1/turns/stream -H 'Content-Type: application/json' \
>   -d '{"profile_id":"memory-demo","input":"Remember: actually I want five bullet points now, not three.","user":{"user_id":"console-user","email":"console-user"},"runtime":{"execution_engine":"sdk"}}'
> ```
> If any response mentions `placeholder`, the payload is wrong — use the block above verbatim.
> 7. Evidence: `grep 'memory gate:' /tmp/mem-r5.log` (now guaranteed for every write — include all lines), the DB chain query (`retired` + `superseded_by`), a new-thread neutral turn (expect five bullets), `scope_metrics` (expect `superseded>=1`).
>
> ~~RESUME NOTE 4 (superseded by the above):~~ Your run proved the decisive fact: rows were written but ZERO `memory gate:` lines appeared — and the current code logs that line **unconditionally on every write**. Therefore **the process serving :8080 was not running the synced code.** Two known causes: (a) a stale/foreign backend still owns 8080 (the coordinator has been running a backend from another session — likely!), so your new start failed to bind and the OLD process kept serving (health checks pass against it, its logs go elsewhere); (b) a non-editable `pip install` copy of `agent_factory` in site-packages shadowing `src/` for the app (scripts see src via PYTHONPATH; the app wouldn't). Do this, in order:
>
> 1. `cd /projects/agent-memory-prototype && git pull` → re-run the Task 2 `cp -r` sync (the package now carries a BUILD marker).
> 2. **Who owns the port?** `ss -ltnp '( sport = :8080 )'` → note PID → `ps -fp <PID>` (command, start time, cwd via `ls -l /proc/<PID>/cwd`). If it's a uvicorn `agent_factory.api.app` process: `pkill -f "uvicorn agent_factory.api.app"`, wait 2s, confirm the port is free. If it's something else/unknown (possibly the coordinator's other session): **don't kill it — use `PORT=8081`** for everything below and point the acceptance curls at 8081.
> 3. **Shadowing check** (from the harness repo root, no PYTHONPATH): `python3 -c "import agent_factory.memory._digit as d; print(d.__file__); print(d.BUILD)"` and the same with `PYTHONPATH=src`. Both must print a path under `.../digit-agent-harness/src/` and `BUILD=2026-07-08.4-decide-floor`. If the no-PYTHONPATH one prints a site-packages path or an older BUILD → shadowing confirmed → **add `export PYTHONPATH=/projects/DigitHarnessRepo/digit-agent-harness/src` to the launch block** (this makes the app and the scripts run identical code by construction) and note it in the report.
> 4. Launch with the full block (+ the PYTHONPATH export from step 3 regardless — it's harmless and removes the ambiguity class), log to a file. **Prove code identity before testing:** the startup log must contain `agent_memory seam loaded build=2026-07-08.4-decide-floor`, and the listener PID from `ss` must equal the process you just started. Do not proceed until both hold.
> 5. `verify_phase_c.py` (12 checks, PASS) → cleanup the acceptance user's bullet rows → the two supersede turns → expect: tool result "Saved - this replaces an older memory…", DB chain (`retired=true` + `superseded_by`), new-thread five-bullet recall, `superseded>=1`.
> 6. Report must include: the port-owner findings from step 2, both step-3 outputs, the startup BUILD line, and every `memory gate:` line from the two turns. With the identity checks passed, gate lines are guaranteed on any write — if a row appears without one, stop: you're still on the wrong process.
>
> ~~RESUME NOTE 3 (superseded by the above):~~ Your isolation work found it: the store path superseded correctly, but the live tool path silently ADDed — root cause: the gate only consulted the decision model inside a hand-picked 0.70–0.95 similarity band, and the real phrasings' similarity fell below it. Fixed upstream: on decider paths anything above a 0.50 floor is adjudicated by the LLM, and the gate now logs one content-free line per write (`memory gate: top_sim=… tier=… action=…`) so we see exactly what it did. **To resume:** `git pull` in the transfer repo → re-run the Task 2 `cp -r` sync → `verify_phase_c.py` (now 12 checks; expect PASS) → restart the backend with the full launch block → re-run the cleanup (retire ALL bullet rows for the acceptance user, as you did) → redo the two supersede turns → check: the second turn's tool result should read "Saved - this replaces an older memory on the same topic.", DB shows the chain, new thread recalls five bullets, `superseded>=1` in metrics. **In your report, include the `memory gate:` log lines from the backend log for both turns** (grep the server log for `memory gate:`) — they carry the observed top_sim values we need for calibration, pass or fail. If it still fails, also grep for `semantic gate failed`.
>
> ~~RESUME NOTE 2 (superseded by the above):~~ Everything is DONE and live-verified **except the supersede beat**: gates all PASS on the pod, backfill=5, semantic recall proven live (topical beat recency), user-b isolation OK. The supersede failure was a design gap, fixed upstream: the tool path now runs the tier-3 decision too (user corrections arrive via the tool; extraction treats tool-saved facts as already-known, so it could never catch them), and ≥0.95-similar contradictions route to the decision instead of being dropped as duplicates. **To resume:** `cd /projects/agent-memory-prototype && git pull` → re-run the Task 2 `cp -r` sync → run `verify_phase_c.py` (now 11 checks; expect PASS) → restart the backend with the full launch block → **cleanup the conflicting rows from the failed beat** (both format memories must go so the beat starts clean):
> `UPDATE agent_memory_entries SET discarded_at = now() WHERE profile_id='memory-demo' AND user_id='console-user' AND discarded_at IS NULL AND content ILIKE '%bullet%';`
> → then redo ONLY the supersede acceptance: (1) turn: `Remember: I always want answers as exactly three bullet points.` (expect a save); (2) turn: `Remember: actually I want five bullet points now, not three.` — expect the save_memory result to say it **replaces an older memory**, and the DB to show the three-bullets row with `retired=true` + `superseded_by` set; (3) new thread, neutral ask → five bullets; (4) fresh `scope_metrics` (expect `superseded>=1`). Carry the already-passing lines (semantic recall, isolation) into the final report unchanged. Keep `AGENT_FACTORY_MEMORY_PGVECTOR=1`.

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
