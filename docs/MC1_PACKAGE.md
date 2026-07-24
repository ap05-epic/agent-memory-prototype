# Merge Candidate 1 — the package

Everything needed to open the merge request and talk it through with Subomi.

**Branch: `feature/agentmemory-mc1`**, a snapshot of the candidate-1 work cut from `feature/agentmemory-v3` at the identity commit `938de17`, which itself was cut from dev `7fa86f5`. Ten commits: the five original prototype commits carried over, four workstream commits (W0 marker sync `2fc2dbb`, W5 `d68db32`, W1 `5a2956e`, W6 `938de17`), and one commit removing the documentation bundle so the merge is code and tests only.

Candidate-2 work (the injection boundary, the outbox, and the in-progress governance layer) lives on `feature/agentmemory-v3` and is deliberately **not** in this branch. Nothing pushed there can affect this merge request.

Net diff against `dev`: 26 files, ~2,270 insertions, no documentation paths.

---

## 1. MR text (paste as the description)

**Title:** `Agent memory — merge candidate 1: re-base, migrations, harness lifecycle, identity (memory off by default)`
**Source:** `feature/agentmemory-mc1` → **Target:** `dev`

> ## What this is
>
> Merge candidate 1 of 2 for the agent memory feature, per the split we agreed. This one is the foundation: the feature re-based onto current dev plus the production plumbing from your review. The memory behaviour changes (moving recall out of the instruction channel, durable extraction, governed APIs and retention) are candidate 2 and are not in this branch.
>
> **Memory stays off by default.** No non-test profile enables it, and a test enforces that. The only profile with it on is the demo fixture under `tests/fixtures`. On this branch memory also requires a validated user and tenant — console traffic sends no tenant yet, so even the demo profile runs with memory disabled from the console until candidate 2 adds the tenant plumbing.
>
> ## What is in it
>
> 1. **Re-base.** All memory work re-applied onto current dev. One conflict (`sdk_runner.py`), resolved by keeping dev's structure and re-placing the memory insertions.
> 2. **Real migrations.** Alembic added to the harness (async setup). Revision `5258f2433fcb` is a reviewed baseline of the full current schema, memory tables included, with a `CREATE EXTENSION IF NOT EXISTS vector` guard. The dev database adopted it with a one-time stamp and `alembic check` reports no drift. `create_all` is now documented as local/test bootstrap only. Details: `docs/MIGRATIONS.md`.
> 3. **Harness-managed DB lifecycle.** Memory no longer runs its own engine. `create_app` installs the app's `Database.session_factory` into the memory package, so in-app memory shares the app's pool and shutdown. Standalone scripts keep a fallback engine, and a startup log line says which mode is active.
> 4. **Model-call conventions.** Memory side-calls follow the `SdkSubagentExecutor` pattern (explicit model, tracing disabled, workflow name, trace metadata) and log token usage when the SDK exposes it (it currently does not — logged as None).
> 5. **Identity hardening.** Memory (recall, the `save_memory` tool, and post-turn extraction) requires both `user_id` and `tenant_id`. Harness paths no longer default the tenant. Missing identity means memory is off for that turn, fail-closed, with one content-free log line.
> 6. **Tests.** Ten new tests across sessions, migrations and identity, including the off-by-default guard. Full suite: 333 passed; the 2 failures are pre-existing on dev (see below).
>
> ## Things you should know
>
> - **Found on the shared dev DB:** a hand-applied unique index `ix_agent_runs_one_active_per_thread` on `agent_runs` that no code creates (it enforces one in-flight run per thread). Left untouched and excluded from migration management; the full definition is in `docs/MIGRATIONS.md`. The team should decide whether to adopt it into the models or drop it.
> - **Pre-existing test failures (not from this branch):** `test_turn_stream_custom_mcp_reaches_sdk_agent` (test double missing the new `manifest_path` kwarg) and `test_turn_service_immediate_stream_does_not_block_on_event_journal` (event-journal wait timeout). Both reproduce at the pre-change baseline commit.
> - Because the dev database is shared, the Alembic setup only manages harness-owned tables. The `studio_*` tables belong to another app, and `agent_sessions`/`agent_messages` are created by the OpenAI Agents SDK — all deliberately unmanaged.
> - The shared dev database currently sits a couple of revisions ahead of this branch, because candidate-2 migrations are applied there too. That is expected while both branches share one dev database.
> - Documentation is being rewritten after the review and will be shared alongside candidate 2, so the old docs bundle is removed here — this MR is code and tests only. Happy to add documentation under a shared path (e.g. `docs/agent-memory/`) if you'd rather it live in the repo.
>
> ## How it was verified
>
> Each piece ran as a gated procedure on the dev pod with logged receipts: non-destructive verification scripts against the live database, live smoke turns on a separate port with a build marker proving which code the server loaded, and for identity a matched pair of turns — full identity under a real tenant (save and recall worked; older default-tenant rows correctly did not appear), and a tenant-less turn (normal reply, one identity-gate log line, zero memory operations). The exact commit in this branch was re-verified in a clean worktree before the MR was opened.

---

## 2. Findings → receipts (crib sheet for the review conversation)

| Review point | What we did | The receipt |
|---|---|---|
| Branch far behind dev; needs re-base | Fresh branch off dev `7fa86f5`; five commits cherry-picked; one guided conflict | All W0 gates passed; live smoke recalled memories on the new branch; the original working copy was never touched |
| No real deployment path / migrations | Alembic, full-schema baseline `5258f2433fcb`, one-time stamp, scoped to harness tables | `alembic check`: "No new upgrade operations detected." Only real-DB write in that workstream: the single bookkeeping row |
| Memory runs its own DB engine | `install_session_factory` seam; app injects `Database.session_factory` at `create_app` | Server log: "memory sessions: harness session factory installed" and **zero** "fallback engine created" lines |
| Side model calls outside harness conventions | RunConfig parity with `SdkSubagentExecutor` + usage logging | Side-call log line fires (tokens None — the SDK does not expose usage; stated honestly) |
| Loose identity; default tenant | `memory_identity_ok` (user AND tenant) at every memory site; no default-tenant writes | Full-identity turn saved and recalled under a real tenant with correct isolation; tenant-less turn produced one gate line and zero memory operations |
| No test coverage | 10 new tests: sessions (3), migrations (4), identity + off-by-default guard (3) | Suite 333 passed; the 2 failures proven pre-existing at the baseline commit via a throwaway worktree |
| Memory must stay off by default (the MC1 condition) | Flag defaults false; only the `tests/fixtures` demo profile enables it | Guard test fails the build if any non-test profile turns it on |

**Candidate 2 status** (on `feature/agentmemory-v3`, not in this MR): recall moved out of the instruction channel into the model input list ✅ · durable extraction via outbox + worker ✅ · governed APIs, audit trail and retention 🔄 in progress · console tenant plumbing ⏳ next.

## 3. Message to send with the MR link

> Hi Subomi — merge candidate 1 is up for review, and it's my deliverable for this week: [MR link]
>
> It's on branch `feature/agentmemory-mc1`, cut from current dev — the foundation half we agreed:
>
> - **Re-based onto current dev.** The memory work re-applied commit by commit. One conflict, in `sdk_runner.py`, resolved by keeping dev's structure and re-placing my insertions.
> - **Real migrations.** Alembic is now in the harness with an async setup. Revision `5258f2433fcb` is a reviewed baseline of the full current schema, including the memory tables and a pgvector extension guard. The dev database adopted it with a one-time stamp and `alembic check` reports no drift. `create_all` is documented as local/test bootstrap only; deployed environments run `alembic upgrade head`.
> - **Harness-managed database lifecycle.** Memory no longer runs its own engine — `create_app` installs the app's `Database.session_factory` into the memory package, so it shares the app's pool and shutdown. A startup log line states which mode is active.
> - **Identity hardening.** Memory requires a validated user *and* tenant everywhere it operates, and the harness paths no longer default the tenant. Missing identity means memory is disabled for that turn, fail-closed, with one content-free log line.
> - **Tests.** Ten new tests, including a guard that fails the build if any non-test profile enables memory — so the off-by-default condition is enforced mechanically rather than by convention.
>
> Two things worth your eyes:
>
> 1. Verifying the migration baseline against the shared dev database surfaced a hand-applied unique index on `agent_runs` (`ix_agent_runs_one_active_per_thread`) that no code creates. I left it untouched and excluded it from migration management, with the definition documented — I think the team should decide whether to adopt it into the models or drop it.
> 2. Two tests fail on this branch (`test_turn_stream_custom_mcp_reaches_sdk_agent` and `test_turn_service_immediate_stream_does_not_block_on_event_journal`). Both reproduce at the pre-change commit, so they're pre-existing on dev rather than caused by this work.
>
> On documentation: the versions currently in the repo predate your review and describe the prototype rather than what's in this MR, so rather than share something stale I'm rewriting them and will send the updated set alongside candidate 2. I've kept the old docs bundle out of this MR for the same reason — it's code and tests only.
>
> Candidate 2 is well underway on a separate branch: recalled memory has moved out of the instruction channel into the model input list, and post-turn extraction is now durable through an outbox table with a background worker, both verified live. The governed memory APIs, audit trail and retention are in progress.
>
> Happy to walk through any of it whenever suits you.

## 4. Opening the MR (GitLab)

1. Left sidebar → **Code → Merge requests** → **New merge request** (top right). Do *not* use the branch dropdown on the Repository page — that only changes what you are browsing.
2. **Source branch:** `feature/agentmemory-mc1` · **Target branch:** `dev` → *Compare branches and continue*. If a form opens already targeting `main` (the project default), use the **Change branches** link at the top right to switch the target to `dev`. `dev` being protected does not prevent an MR from targeting it.
3. Paste the title and description from section 1.
4. Reviewer: Subomi. **Tick "Delete source branch when merge request is accepted"** — this branch is a disposable snapshot. Leave "Squash commits" unticked; the ten-commit history is worth showing.
5. Create, copy the link, send the section-3 message.
