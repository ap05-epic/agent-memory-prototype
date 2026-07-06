# Demo Runbook — Agent Memory Prototype

Audience: team lead review. ~5 minutes. Everything on the product surface (console + one DB query + one curl) — no dashboards.

## Pre-demo checklist (day before, and 30 min before)

- [ ] `python3 scripts/verify_phase_a.py` prints `PHASE_A: PASS` on the pod.
- [ ] Agent A (e.g. `test-full`): `memory.semantic_memory_enabled: true` in its `agent.profile.yaml`. Agent B: flag absent/false. **Restart the backend process** after editing (`scripts/run-local-with-profiles.sh`).
- [ ] Know your console user_id: run beat 1 once in rehearsal and read `user_id` from the DB row (console identity falls back to `console-user` unless a header sets it). Use that value everywhere below as `<u1>`.
- [ ] DB query ready in a terminal tab:
  `SELECT content, category, source, thread_id, user_id, created_at FROM agent_memory_entries WHERE user_id='<u1>' ORDER BY created_at DESC LIMIT 5;`
- [ ] Second-user curl ready (dev auth is bypassed):
  ```
  curl -N -X POST http://localhost:8080/api/v1/turns/stream -H "Content-Type: application/json" \
    -d '{"profile_id":"<agentA>","input":"Give me a quick status-update template.","user":{"user_id":"user-b","email":"user-b@example.com"},"runtime":{"execution_engine":"sdk"}}'
  ```
- [ ] Backend restart = kill uvicorn, rerun `scripts/run-local-with-profiles.sh`. Console keeps its conversation in localStorage — refresh the page after restart.
- [ ] Fallback seed ready (don't run unless needed): `python3 scripts/seed_demo.py --profile <agentA> --user <u1>`
- [ ] **Rehearse the full script once.** Reset between rehearsals: `python3 scripts/reset_dev_tables.py --yes`

## The script

**Beat 1 — capture.** Agent A, **new thread** in the console:
> "Remember: I always want answers as exactly three bullet points, addressed to me by name. Save that."

The console renders the `save_memory` tool call (tool.started/completed). Say: *"The agent decided to persist that — explicitly, auditably."*

**Beat 2 — the row.** Run the DB query. Say: *"A governed row in the platform's existing Azure Postgres — content, source, thread, user, timestamp. Not a file: the profile directory is ephemeral storage, which is exactly why this is DB-backed."*

**Beat 3 — durability.** Restart the backend process, live. Refresh the console.

**Beat 4 — recall (the headline).** Same agent, **new thread** — say out loud: *"New conversation, new thread id — chat history hasn't followed us; this is the memory table."* Ask something neutral:
> "Give me a quick status-update template."

Answer arrives as three bullets, addressed by name.

**Beat 5 — scoping (fast).**
- Run the `user-b` curl in the terminal → plain answer, no bullets-by-name. *"Different user, same agent: her memory, not mine — scoped per user within the agent."*
- Agent B in the console: ask the same neutral question → plain answer. Then:
> "Remember that I like tables."
→ decline (memory not enabled). *"Opt-in per agent — a disabled agent can't even write."*

**Beat 6 — close (compliance line).**
> *"Forget is one UPDATE to `discarded_at` today; an agent-facing forget-tool, per-write audit events, and the phase-two skills loop hang off the same seams. Retrieval scales from load-recent to Postgres full-text search long before we need to discuss vector infrastructure."*

**Optional beat (only if Phase B passed):** on Agent A, naturally:
> "By the way, I work on the payments reconciliation team."

Finish the turn, wait ~15s, re-run the DB query → a `source='extraction'` row appeared with no tool call. *"Same pipeline, autonomous path — and the seam the phase-two skills reviewer will share."*

## Fallbacks (rehearsed, not improvised)

| Symptom | Move |
|---|---|
| Beat 1: no tool call | Rephrase: "Use your save_memory tool to store this: …". Still nothing → `seed_demo.py`, show the row, continue from Beat 2 honestly ("seeded for time"). |
| Beat 4: preference not applied | Show the DB row, then `GET /api/v1/runs/<run_id>/events` for the recall turn — the run-events trace is the inspection surface (there is no assembled-instructions endpoint). The row + events are the proof; style compliance is model mood. |
| Restart takes long | Fill with the Beat-2 row walk-through. |
| Extraction beat flaky | Skip it — the headline never depends on extraction. |
