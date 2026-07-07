# Demo Runbook — Agent Memory Prototype

Audience: team lead review. ~5 minutes. Everything on the product surface (console + one DB query + one curl) — no dashboards.

## Pre-demo checklist (day before, and 30 min before)

- [ ] **LAUNCH FIX — the ambient env override (this is what caused the 401; the demo will not run without it).** The pod injects a stale `AZURE_OPENAI_BASE_URL` pointing at a *different* Azure resource (`...acaeus2deveis1aiml...`), and the harness's `load_environment()` keeps already-set shell vars over `.env` — so the app sent the good `.env` key to the wrong endpoint → 401. Clear the stale vars and export the `.env` values before launching, in default/Responses mode:
  ```
  unset AZURE_OPENAI_BASE_URL OPENAI_BASE_URL OPENAI_API_KEY OPENAI_AGENTS_API
  export AZURE_OPENAI_API_KEY=<from .env>  AZURE_OPENAI_ENDPOINT=<from .env>
  export AGENT_FACTORY_PROFILE_PATHS=<repo>/profiles
  scripts/run-local-with-profiles.sh
  ```
  Verify a plain turn works before demoing. (Worth flagging to the platform team: remove the stale pod `AZURE_OPENAI_BASE_URL` so `.env` just works.)
- [ ] `python3 scripts/verify_phase_a.py` prints `PHASE_A: PASS` on the pod.
- [ ] Demo profiles staged into the harness `profiles/` dir (the run script reads it):
  - **Agent A = `memory-demo`** — the purpose-built demo agent from this transfer repo (`profiles/memory-demo/`); copy it in. It already has `semantic_memory_enabled: true`, `save_memory` in `function_tools`, `emit_tool_events: true`, and `model.default: gpt-5.4`. Nothing to edit.
  - **Agent B (flag-off) = `test-minimal`** — `cp -r tests/fixtures/profiles/test-minimal profiles/`, untouched.
  - (`test-full` also works as Agent A if you prefer, but needs its flag flipped, `save_memory` added, and model set to gpt-5.4 by hand — `memory-demo` is the no-edit option.)
- [ ] Restart after any yaml edit is the same launch block above (the `unset`/`export` must precede every launch — a bare `scripts/run-local-with-profiles.sh` will 401).
- [ ] Console identity is `console-user` (from the x-user-email header fallback) — that's `<u1>` below. Confirm once in rehearsal by reading `user_id` off the beat-2 DB row.
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

Answer arrives as exactly three bullets — the saved preference honored in a fresh thread after a restart. **This is the moment.**

> Note on "by name": in the live run the reply opened with "Hey —" because the console user's id is literally `console-user`, not a real name. The **format** recall (three bullets) is the reliable, unmistakable proof — lead with that. If you want a real name in the greeting, send the turn with an `x-uname: <YourName>` header (or just explain the placeholder). Don't let the name be the headline; the format is.

**Beat 5 — scoping (fast).**
- Run the `user-b` curl in the terminal → plain answer, no bullets-by-name. *"Different user, same agent: her memory, not mine — scoped per user within the agent."*
- Agent B in the console: ask the same neutral question → plain answer. Then:
> "Remember that I like tables."
→ decline (memory not enabled). *"Opt-in per agent — a disabled agent can't even write."*

**Beat 6 — close (compliance line).**
> *"Forget is one UPDATE to `discarded_at` today; an agent-facing forget-tool, per-write audit events, and the phase-two skills loop hang off the same seams. Retrieval scales from load-recent to Postgres full-text search long before we need to discuss vector infrastructure."*

**Optional beat (automatic capture).** Heads-up from the live run: **test-full is an eager agent** — its recall footer tells it to save durable details, so when you say "By the way, I work on the payments reconciliation team," it often calls `save_memory` *itself* (a `source=tool` row), and the background extractor then correctly finds nothing new to add (dedupe). That's the system working — but it means a clean, isolated `source=extraction` row is hard to force live in the console.

The reliable way to show the autonomous path is the gate, run in a terminal:
> `python3 scripts/verify_phase_b.py` → its live check makes a real model call and writes a `source=extraction` row in a throwaway scope → `PHASE_B: PASS`.

Say: *"The explicit tool path and the autonomous post-turn extraction path are both proven — and extraction is the exact seam the phase-two skills reviewer will share."* If you'd rather keep the whole demo in the console, skip this beat — the headline never depends on it.

## Fallbacks (rehearsed, not improvised)

| Symptom | Move |
|---|---|
| Beat 1: no tool call | Rephrase: "Use your save_memory tool to store this: …". Still nothing → `seed_demo.py`, show the row, continue from Beat 2 honestly ("seeded for time"). |
| Beat 4: preference not applied | Show the DB row, then `GET /api/v1/runs/<run_id>/events` for the recall turn — the run-events trace is the inspection surface (there is no assembled-instructions endpoint). The row + events are the proof; style compliance is model mood. |
| Restart takes long | Fill with the Beat-2 row walk-through. |
| Extraction beat flaky | Skip it — the headline never depends on extraction. |
