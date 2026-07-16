# W0 — Branch Migration: `feature/agentmemory` → `feature/agentmemory-v3` on current dev

**Who runs this:** the on-pod GPT-5.4 Copilot CLI agent, with full repo access.
**Who watches:** the human, screenshotting every GATE report and saying "continue" between gates.
**Background if you need it:** `docs/POD_AGENT_CONTEXT.md` in the transfer repo. This brief is self-contained for the task itself.

## Mission

Create `feature/agentmemory-v3` from **current** `origin/dev` and carry over all five memory commits from `feature/agentmemory` by cherry-pick. Prove the result: package parity against the transfer repo, non-destructive verify scripts, a live smoke turn with the build-marker identity check. Then push the new branch. The old branch is the rollback and the still-working demo — it is never modified.

## Hard rules

1. NEVER commit to, reset, rebase, or force-push `feature/agentmemory` or `dev`. They are read-only.
2. NEVER `git push --force` anywhere, for any reason.
3. NEVER run `scripts/reset_dev_tables.py` — the shared DB holds live demo data. Only the non-destructive verify scripts are allowed.
4. At each GATE: stop, print the gate report block (format at the bottom), and wait for the human before proceeding.
5. Anything unexpected — a conflict outside the files named in the conflict guide, a dirty working tree, a failing check — STOP, print the state, do not improvise recovery.
6. If you must deviate from a command in this brief, say so in the gate report *before* running it.

## Facts

- Harness repo: `/projects/DigitHarnessRepo/digit-agent-harness`, remote `origin` (GitLab).
- Our branch: `feature/agentmemory`, exactly **5 commits** ahead of `origin/dev` (oldest → newest): `2bd6612`, `3c9a94e`, `349b9f9`, `123a92c`, `c4336de`. Roughly 117 behind.
- The transfer repo (github.com/ap05-epic/agent-memory-prototype) is cloned on this pod. Pull it first; it must be at or past commit `2866ca0` ("Reconcile transfer repo to deployed pod state").
- After the cherry-picks, `src/agent_factory/memory/` must differ from the transfer repo's `memory/` by **exactly one line**: `BUILD = "2026-07-08.5-visible-logs"` (harness) vs `BUILD = "2026-07-16.7-reconciled"` (transfer). Anything else differing is a finding, not something to fix silently.
- Expected conflicts (recon round 6): `src/agent_factory/runtime/sdk_runner.py` SMALL, `src/agent_factory/api/app.py` SMALL, possibly `pyproject.toml` and agent-console files (dependency/UI churn). `runtime/sdk_adapter.py`, `tools/registry.py`, `core/schemas.py` should apply clean.
- Dev now has structured-output agents whose streams skip RESPONSE_COMPLETED. Do not "fix" or touch anything about that while resolving conflicts — keep dev's code as-is and only re-place our insertions.

## Procedure

### GATE 0 — preflight (read-only + SSH perms)

```
chmod 700 /home/devpod/.ssh && chmod 600 /home/devpod/.ssh/config
cd /projects/DigitHarnessRepo/digit-agent-harness
git status --short
git stash list
git fetch origin
git rev-list --left-right --count origin/dev...feature/agentmemory
git log --oneline origin/dev..feature/agentmemory
```
Then in the transfer repo clone: `git pull` and `git log --oneline -1`.

Require: working tree clean (if not: STOP and report exactly what is dirty — do not stash or discard anything); fetch succeeds; exactly the 5 commits listed; transfer repo at/past `2866ca0`. Report GATE 0.

### GATE 1 — safety snapshot

```
git branch backup/agentmemory-pre-v3 feature/agentmemory
git rev-parse feature/agentmemory backup/agentmemory-pre-v3 origin/dev
```
Require: first two SHAs identical. This backup branch stays local — do not push it. Record all three SHAs in the report.

### GATE 2 — create v3 off current dev

```
git switch -c feature/agentmemory-v3 origin/dev
git log --oneline -1
```
Require: HEAD equals the `origin/dev` SHA recorded at GATE 1.

### GATE 3 — cherry-pick the five, one at a time, in order

For each SHA in `2bd6612 3c9a94e 349b9f9 123a92c c4336de`:

```
git cherry-pick <SHA>
```

- On conflict: resolve per the CONFLICT GUIDE below, `git add` the resolved files, `git cherry-pick --continue`.
- After each pick: `git status --short` must be clean, and run `python -m py_compile` on every `.py` file the pick touched (`git show --name-only --pretty= HEAD`).
- If a pick goes beyond what the guide covers: `git cherry-pick --abort`, STOP, report.

Report per pick: SHA, conflicted files (one line each on how resolved), compile result. GATE 3 report after all five.

### GATE 4 — package parity vs transfer repo (the reconciliation proof)

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

### GATE 5 — verify scripts (non-destructive only)

Source the harness `.env`, set the memory env, run the verify scripts exactly the way they ran in the v2 build (from the transfer-repo checkout root; they import the local `memory/` package and talk to the DB via `AGENT_FACTORY_DATABASE_URL`):

```
cd /projects/DigitHarnessRepo/digit-agent-harness && set -a && source .env && set +a
export AGENT_FACTORY_MEMORY_PGVECTOR=1
export AGENT_FACTORY_MEMORY_EMBED_MODEL=text-embedding-3-large
export AGENT_FACTORY_MEMORY_EMBED_DIM=1536
export AGENT_FACTORY_MEMORY_MODEL=gpt-5.4-mini
cd <transfer> && python scripts/verify_phase_a.py && python scripts/verify_phase_c.py
```

Do NOT run `reset_dev_tables.py`. Require: PASS lines from both scripts. If an embed/LLM check no-ops for env reasons, report that truthfully rather than forcing it.

### GATE 6 — live smoke on v3

Launch the backend exactly per the "launch fix" in `docs/DEMO_RUNBOOK.md` (transfer repo): kill stale uvicorns, unset stale ambient `AZURE_OPENAI_BASE_URL`/`OPENAI_*`, source `.env`, `PORT=8080`, `AGENT_FACTORY_PROFILE_PATHS` pointing at the fixtures profiles dir, `PYTHONPATH=src`, log redirected to a file, plus the four memory env vars from GATE 5.

Require, from the log file:
- `agent_memory seam loaded build=2026-07-16.7-reconciled` (this exact marker — it proves the v3 checkout is what the process loaded);
- listener PID matches the process you launched.

Then one turn against the `memory-demo` profile as a user who already has stored memories (e.g. `console-user`): the reply must reflect recall, and a `memory gate:` or recall telemetry line must appear. Quote the log lines in the report.

### GATE 7 — push

```
git push -u origin feature/agentmemory-v3
```
New branch, plain push, no force. Final report: SHAs for old branch, backup, v3 HEAD, origin/dev; one-line outcome per gate 0–6.

## Conflict guide (round-6 informed)

- **`runtime/sdk_runner.py`** — dev refactored around `stream_turn` but the shape holds. Our three insertions: (1) the `"memory_enabled": ...` entry in `_harness_run_context`; (2) the recall-injection block immediately after the `sdk_instructions = _with_response_preview_context(...)` assignment; (3) the extraction-scheduling block inside RESPONSE_COMPLETED handling, after the audit yield and before RUN_COMPLETED. Take dev's version of everything else and re-place our blocks at those anchors. If an anchor no longer exists verbatim, locate its successor by reading the function — and name what moved in the gate report.
- **`api/app.py`** — our change is the `save_memory` tool build + `register_custom_tool(...)` at the ToolRegistry wiring site. Take dev's registry construction, append our wiring after it.
- **`pyproject.toml`** — take dev's file, re-add our single `pgvector` dependency line.
- **agent-console files** — our changes are additive guards (SSE close on run end; `_HARNESS_OWNED_EVENTS` protection for `memory.recalled`/`memory.learned` in the ui_event_tool path). Place them into dev's current versions. If dev refactored those files beyond recognition, STOP and report rather than improvise.
- **memory package / fixtures / docs bundle** — purely additive; if git reports a conflict here, something is off: STOP and report.

## Rollback (any point before GATE 7)

```
git cherry-pick --abort        # only if mid-pick
git switch feature/agentmemory
git branch -D feature/agentmemory-v3
```
The old branch and the backup are untouched by design; nothing in this procedure can damage them. Starting over is always safe.

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

- **GATE 0:** status clean, exactly 5 commits listed, transfer repo at `2866ca0` or later.
- **GATE 1:** first two SHAs identical.
- **GATE 2:** HEAD SHA equals the origin/dev SHA from GATE 1.
- **GATE 3:** five picks; conflicts only in the files the guide names; every compile PASS.
- **GATE 4:** "only diff is the BUILD line." If it pastes any other package diff — stop, that goes off-pod before continuing.
- **GATE 5:** both verify scripts PASS.
- **GATE 6:** the log line says `build=2026-07-16.7-reconciled` and the smoke turn recalled memories.
- **GATE 7:** push output shows the new branch created (no force, no errors).
