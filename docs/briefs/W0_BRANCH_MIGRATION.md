# W0 — Two-Folder Migration: fresh clone of current dev, work ported as `feature/agentmemory-v3`

**Who runs this:** the on-pod GPT-5.4 Copilot CLI agent, with full repo access.
**Who watches:** the human, screenshotting every GATE report and saying "continue" between gates.
**Background if you need it:** `docs/POD_AGENT_CONTEXT.md` in the transfer repo. This brief is self-contained for the task itself.

## Mission

Stand up a **second, clean checkout** of the harness next to the existing one, on a new branch `feature/agentmemory-v3` cut from **current** `origin/dev`, and carry the five memory commits over by cherry-pick. Prove the result (package parity vs the transfer repo, non-destructive verify scripts, live smoke with the build-marker identity check on its own port), then push the branch.

**The two-folder rule, which this whole design exists for:**
- **OLD folder** `/projects/DigitHarnessRepo/digit-agent-harness` — the frozen, working demo system on `feature/agentmemory`. It is never modified, never has its branch switched, never has its processes killed. Demos keep running from here (port 8080, per its `DEMO_RUNBOOK`).
- **NEW folder** (sibling: `/projects/DigitHarnessRepo/digit-agent-harness-v3`) — where all productionization work happens from now on. Its server uses **port 8081**.

## Hard rules

1. The OLD folder is read-only for this entire procedure. Exactly two read-only commands may run against it (both in GATE 0); nothing else, ever.
2. NEVER `git push --force` anywhere. NEVER touch `origin/feature/agentmemory` or `dev`.
3. NEVER run `scripts/reset_dev_tables.py` — both folders share ONE dev database and it holds live demo data. Non-destructive verify scripts only.
4. NEVER kill processes globally (`pkill -f uvicorn` is banned — it would take down a demo server). Kill only by the specific PID you started, or by port 8081.
5. At each GATE: stop, print the gate report block (format at the bottom), wait for the human.
6. Anything unexpected — a conflict outside the files named in the conflict guide, a failing check, a surprising diff — STOP, print the state, do not improvise recovery.
7. If you must deviate from a command in this brief, say so in the gate report *before* running it.

## Facts

- All five of our commits are already pushed to GitLab, so a fresh clone sees them on `origin/feature/agentmemory` (oldest → newest): `2bd6612`, `3c9a94e`, `349b9f9`, `123a92c`, `c4336de`. The remote branch tip **is** the backup — no local backup branch is needed because the old checkout is never touched.
- `origin/dev` is roughly 117 ahead of our branch point.
- The transfer repo (github.com/ap05-epic/agent-memory-prototype) is cloned on this pod. Pull it first; it must be at or past commit `7130602`.
- After the cherry-picks, `src/agent_factory/memory/` in the NEW folder must differ from the transfer repo's `memory/` by **exactly one line**: `BUILD = "2026-07-08.5-visible-logs"` (harness) vs `BUILD = "2026-07-16.7-reconciled"` (transfer). Anything else differing is a finding, not something to fix silently.
- Expected conflicts (recon round 6): `src/agent_factory/runtime/sdk_runner.py` SMALL, `src/agent_factory/api/app.py` SMALL, possibly `pyproject.toml` and agent-console files (dependency/UI churn). `runtime/sdk_adapter.py`, `tools/registry.py`, `core/schemas.py` should apply clean.
- Dev now has structured-output agents whose streams skip RESPONSE_COMPLETED. Do not "fix" or touch anything about that while resolving conflicts — keep dev's code as-is and only re-place our insertions.
- `.env` is gitignored — the fresh clone will NOT have it; it gets copied from the old folder in GATE 4.

## Procedure

### GATE 0 — preflight, clone, verify remotes

```
chmod 700 /home/devpod/.ssh && chmod 600 /home/devpod/.ssh/config
git -C /projects/DigitHarnessRepo/digit-agent-harness remote get-url origin
git -C /projects/DigitHarnessRepo/digit-agent-harness rev-parse feature/agentmemory
```
(Those are the only two commands ever aimed at the old folder: the remote URL and the local branch tip, both read-only.)

```
cd /projects/DigitHarnessRepo
git clone <origin-url> digit-agent-harness-v3
cd digit-agent-harness-v3
git fetch origin
git rev-parse origin/feature/agentmemory
git rev-list --left-right --count origin/dev...origin/feature/agentmemory
git log --oneline origin/dev..origin/feature/agentmemory
```
Also pull the transfer repo clone and report its `git log --oneline -1`.

Require: clone succeeds; `origin/feature/agentmemory` tip == the old folder's local tip == `c4336de` (this proves everything we built is safely on the remote — the backup); exactly the 5 commits listed; disk has room (`df -h .` — report it); transfer repo at/past `7130602`. Report GATE 0.

### GATE 1 — create v3 off current dev (in the NEW folder; every later gate is in the NEW folder too)

```
git switch -c feature/agentmemory-v3 origin/dev
git log --oneline -1
```
Require: HEAD equals `origin/dev`'s SHA (record both in the report).

### GATE 2 — cherry-pick the five, one at a time, in order

For each SHA in `2bd6612 3c9a94e 349b9f9 123a92c c4336de`:

```
git cherry-pick <SHA>
```

- On conflict: resolve per the CONFLICT GUIDE below, `git add` the resolved files, `git cherry-pick --continue`.
- After each pick: `git status --short` must be clean, and run `python -m py_compile` on every `.py` file the pick touched (`git show --name-only --pretty= HEAD`).
- If a pick goes beyond what the guide covers: `git cherry-pick --abort`, STOP, report.

Report per pick: SHA, conflicted files (one line each on how resolved), compile result. GATE 2 report after all five.

### GATE 3 — package parity vs transfer repo (the reconciliation proof)

```
diff -ru --strip-trailing-cr <transfer>/memory src/agent_factory/memory
diff -u --strip-trailing-cr <transfer>/profiles/memory-demo/agent.profile.yaml tests/fixtures/profiles/memory-demo/agent.profile.yaml
```

Require for the package: the ONLY difference is the `BUILD =` line (ignore `__pycache__`). If anything else differs, STOP and paste the full diff into the report — that is a reconciliation miss the off-pod side must see before anything proceeds.

For the yaml: comment-only differences are fine (the harness fixture is truth; leave it). Known-acceptable: the transfer copy may declare an extra optional `summary` property under the `memory.learned` event. Any other non-comment difference: paste and STOP.

Then sync the build marker:

```
cp <transfer>/memory/_digit.py src/agent_factory/memory/_digit.py
git diff --stat
git add src/agent_factory/memory/_digit.py
git commit -m "memory: sync reconciled build marker 2026-07-16.7"
```
Require: `git diff --stat` before the add shows only `_digit.py`, one line changed each way.

### GATE 4 — environment bootstrap + verify scripts (non-destructive only)

1. Copy the runtime env: `cp /projects/DigitHarnessRepo/digit-agent-harness/.env .`
   (File copy FROM the old folder is fine — it does not modify it. This is not one of the two GATE-0 commands because it touches nothing.)
2. Inspect how the OLD folder's Python environment was set up (venv dir? uv? system pip? `pip show agent-factory` / look for `.venv/`) — WITHOUT running anything in the old folder that modifies it — and replicate the same setup in the NEW folder, including installing the project (`pip install -e .` or the uv equivalent) so the cherry-picked `pyproject.toml` (with the pgvector dependency) takes effect. Report exactly what you found and did.
3. Console `npm install` is NOT needed for this brief — skip it; it happens when a workstream first needs the console.
4. Run the verify scripts the way they ran in the v2 build (from the transfer-repo checkout root; they import the local `memory/` package and talk to the DB via `AGENT_FACTORY_DATABASE_URL`):

```
cd /projects/DigitHarnessRepo/digit-agent-harness-v3 && set -a && source .env && set +a
export AGENT_FACTORY_MEMORY_PGVECTOR=1
export AGENT_FACTORY_MEMORY_EMBED_MODEL=text-embedding-3-large
export AGENT_FACTORY_MEMORY_EMBED_DIM=1536
export AGENT_FACTORY_MEMORY_MODEL=gpt-5.4-mini
cd <transfer> && python scripts/verify_phase_a.py && python scripts/verify_phase_c.py
```

Do NOT run `reset_dev_tables.py`. Require: PASS lines from both scripts. If an embed/LLM check no-ops for env reasons, report that truthfully rather than forcing it.

### GATE 5 — live smoke in the NEW folder, port 8081

Launch the backend from the NEW folder exactly per the "launch fix" in `docs/DEMO_RUNBOOK.md` (transfer repo), with two changes: **PORT=8081**, and no global process kills (if 8081 is somehow occupied, find and kill only that PID). Unset stale ambient `AZURE_OPENAI_BASE_URL`/`OPENAI_*`, source `.env`, `AGENT_FACTORY_PROFILE_PATHS` pointing at the NEW folder's fixtures profiles dir, `PYTHONPATH=src`, the four memory env vars from GATE 4, log redirected to a file.

Require, from the log file:
- `agent_memory seam loaded build=2026-07-16.7-reconciled` (this exact marker — it proves the v3 checkout is what the process loaded);
- the PID listening on 8081 matches the process you launched.

Then one turn against the `memory-demo` profile on **port 8081** as a user who already has stored memories (e.g. `console-user`): the reply must reflect recall, and a `memory gate:` or recall telemetry line must appear. Quote the log lines in the report. Stop the 8081 server afterwards (by its PID).

### GATE 6 — push

```
git push -u origin feature/agentmemory-v3
```
New branch, plain push, no force. Final report: SHAs for origin/feature/agentmemory, v3 HEAD, origin/dev; one-line outcome per gate 0–5; confirmation that the OLD folder received zero writes.

## Conflict guide (round-6 informed)

- **`runtime/sdk_runner.py`** — dev refactored around `stream_turn` but the shape holds. Our three insertions: (1) the `"memory_enabled": ...` entry in `_harness_run_context`; (2) the recall-injection block immediately after the `sdk_instructions = _with_response_preview_context(...)` assignment; (3) the extraction-scheduling block inside RESPONSE_COMPLETED handling, after the audit yield and before RUN_COMPLETED. Take dev's version of everything else and re-place our blocks at those anchors. If an anchor no longer exists verbatim, locate its successor by reading the function — and name what moved in the gate report.
- **`api/app.py`** — our change is the `save_memory` tool build + `register_custom_tool(...)` at the ToolRegistry wiring site. Take dev's registry construction, append our wiring after it.
- **`pyproject.toml`** — take dev's file, re-add our single `pgvector` dependency line.
- **agent-console files** — our changes are additive guards (SSE close on run end; `_HARNESS_OWNED_EVENTS` protection for `memory.recalled`/`memory.learned` in the ui_event_tool path). Place them into dev's current versions. If dev refactored those files beyond recognition, STOP and report rather than improvise.
- **memory package / fixtures / docs bundle** — purely additive; if git reports a conflict here, something is off: STOP and report.

## Rollback (any point before GATE 6)

```
git cherry-pick --abort        # only if mid-pick
cd /projects/DigitHarnessRepo && rm -rf digit-agent-harness-v3
```
The NEW folder is disposable until its branch is pushed; deleting it and re-running this brief is always safe. The OLD folder and the remote branch are untouched by design.

## Gate report format (flat text — no nested fences, OCR-safe)

```
GATE <n>: PASS or FAIL
<KEY>: <value>
<KEY>: <value>
NEXT: waiting for human
```

---

## For the human (gate checklist — agent: no action needed here)

Screenshot each gate report. Say "continue" only when the line below holds; anything surprising → stop and bring the screenshots back off-pod.

- **GATE 0:** clone succeeded; remote branch tip == old folder tip == `c4336de`; exactly 5 commits; transfer repo at `7130602` or later.
- **GATE 1:** HEAD SHA equals the origin/dev SHA.
- **GATE 2:** five picks; conflicts only in the files the guide names; every compile PASS.
- **GATE 3:** "only diff is the BUILD line." If it pastes any other package diff — stop, that goes off-pod before continuing.
- **GATE 4:** env replicated (it says how), both verify scripts PASS.
- **GATE 5:** the log line says `build=2026-07-16.7-reconciled`, the smoke turn recalled memories, all on port 8081.
- **GATE 6:** push output shows the new branch created (no force, no errors) + "OLD folder: zero writes."

**Afterwards, your world looks like this:** demos keep running from the old folder on port 8080 exactly as before — nothing there changed. All productionization work (W1–W6 briefs) happens in `digit-agent-harness-v3`. When Subomi accepts a merge candidate, it merges from the v3 branch; the old folder retires only when you no longer need the demo fallback.
