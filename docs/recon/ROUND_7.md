# Recon Round 7 — W5/W6 ground truth from the v3 folder

You are the on-pod recon agent. **READ-ONLY** — no edits, no state changes.
Run everything inside `/projects/DigitHarnessRepo/digit-agent-harness-v3` (current dev + the five memory commits). Write the full answer to `recon_round_7_answers.md` — flat text, real code quoted verbatim, no nested fences, never print secrets.

Context: W0 is done. Next workstreams: **W5** (memory stops running its own DB engine and side-channel model calls; it adopts the harness's `Database.session_factory` and model machinery) and **W6** (memory requires a validated user + tenant). This round pins the exact current code those briefs will anchor to.

## Block A — harness DB lifecycle (W5)

**A1.** In `src/agent_factory/api/app.py`: quote the app-construction region where the `Database` object is created and repositories/stores receive it or its `session_factory` — from `Database(...)` construction through the last repository wired (≤40 lines, verbatim, with function name).

**A2.** From `src/agent_factory/persistence/database.py`: quote the `Database` class — `__init__`, the `session_factory` attribute/property, `create_tables`, and any startup/shutdown hooks (≤40 lines).

**A3.** ONE representative existing repository class: file+class name, `__init__` signature (what it stores), and ONE method showing the session-usage pattern (`async with ...`) (≤20 lines).

**A4.** How does request-handling code reach a repository at runtime — constructor injection all the way, an `app.state` registry, a dependencies module? Show ONE existing component reaching a repository from turn/request code (≤15 lines).

**A5.** `grep -rn "create_async_engine" src/` — list every hit. (Expect: persistence/database + our memory/_digit; anything else is a surprise.)

## Block B — model side-call machinery (W5)

**B1.** Quote how the turn path builds model settings / `RunConfig` on current dev — the function(s) in `runtime/sdk_adapter.py` (and/or `sdk_runner.py`) where model name, reasoning effort, timeouts, and tracing flags are assembled (≤30 lines). This is the machinery a governed side-call helper must reuse.

**B2.** Where does model-name resolution live now (`agent_factory/config.py`? `get_model_name`?) — quote the resolution function (≤15 lines).

**B3.** Is ANY per-call usage accounting captured on dev (tokens, cost, durations)? `grep -rni "usage\|prompt_tokens\|completion_tokens" src/agent_factory --include=*.py -l` then quote the closest real thing (≤10 lines) or say NONE.

**B4.** The subagent executor's non-turn model call (the pattern our extraction side-call mirrors): quote its current form — Agent + Runner.run + RunConfig (≤20 lines) with file name. Confirm it still exists on current dev.

## Block C — identity & tenant validation (W6)

**C1.** Quote `enforce_profile_access` from `src/agent_factory/api/security.py` in FULL (≤40 lines).

**C2.** Every call site of `enforce_profile_access` in the turn/API path — file, function, and 5 surrounding lines each.

**C3.** Quote the `UserContext` model from `core/schemas.py` verbatim (fields, defaults, validators, ≤20 lines) and show where `request.user` is parsed/validated on the way into a turn.

**C4.** Is `tenant_id` required or validated anywhere today? `grep -rn "tenant" src/agent_factory/api src/agent_factory/core --include=*.py` — quote representative hits (≤15 lines total).

## Block D — config conventions (small)

**D1.** Quote `MemoryPolicy` from `core/schemas.py` as it stands on the v3 branch (verbatim).

**D2.** How does dev read env config — a settings module (pydantic BaseSettings?) or raw `os.getenv`? Quote one representative config read (≤10 lines) and name the file.

## Final verdict lines (end with exactly these)
```
DB-WIRING: <one line: where MemoryStore plugs into app construction>
MODEL-PATH: <one line: what machinery a side-call helper reuses>
AUTH-HOOK: <one line: where memory's validated-user+tenant gate hooks>
SURPRISES: <up to 3 lines contradicting our assumptions, or "none">
```
