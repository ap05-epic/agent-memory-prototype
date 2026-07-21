# Merge Candidate 1 — the package

Everything needed to open the MR and talk it through with Subomi. Branch: `feature/agentmemory-v3` at `938de17`, cut from dev `7fa86f5`, five original commits carried over plus four workstream commits (W0 marker sync `2fc2dbb`, W5 `d68db32`, W1 `5a2956e`, W6 `938de17`).

---

## 1. MR text (copy-paste as the description; title suggestion below)

**Title:** `Agent memory — merge candidate 1: re-base, migrations, harness lifecycle, identity (memory off by default)`
**Source:** `feature/agentmemory-v3` → **Target:** `dev`

> ## What this is
>
> Merge candidate 1 of 2 for the agent memory feature, per the split we agreed. This one is the foundation: the feature re-based onto current dev plus the production plumbing from your review. The memory behavior changes (moving recall out of the instruction channel, durable extraction, governed APIs and retention) are candidate 2.
>
> **Memory stays off by default.** No non-test profile enables it, and a test enforces that. The only profile with it on is the demo fixture under tests/fixtures. On this branch memory also requires a validated user and tenant — console traffic sends no tenant yet, so even the demo profile runs with memory disabled from the console until candidate 2 adds the tenant plumbing.
>
> ## What is in it
>
> 1. **Re-base.** All memory work re-applied onto current dev as this branch. One conflict (sdk_runner.py), resolved by keeping dev's structure and re-placing the memory insertions.
> 2. **Real migrations.** Alembic added to the harness (async setup). Revision 5258f2433fcb is a reviewed baseline of the full current schema, memory tables included. The dev database adopted it with a one-time stamp and alembic check reports no drift. create_all is now documented as local/test bootstrap only. Details: docs/MIGRATIONS.md.
> 3. **Harness-managed DB lifecycle.** Memory no longer runs its own engine. create_app installs the app's Database.session_factory into the memory seam, so in-app memory shares the app's pool and shutdown. Standalone scripts keep a fallback engine, and a log line tells you which mode is active.
> 4. **Model-call conventions.** Memory side-calls follow the SdkSubagentExecutor pattern (explicit model, tracing disabled, workflow name, trace metadata) and log token usage when the SDK exposes it (it currently does not — logged as None).
> 5. **Identity hardening.** Memory (recall, the save_memory tool, and post-turn extraction) requires both user_id and tenant_id. Harness paths no longer default the tenant. Missing identity means memory is off for that turn, fail-closed, with one content-free log line.
> 6. **Tests.** Ten new tests across sessions, migrations, and identity, including the off-by-default guard. Full suite: 333 passed; the 2 failures are pre-existing on dev (verified at the pre-change commit; see below).
>
> ## Things you should know
>
> - **Found on the shared dev DB:** a hand-applied unique index `ix_agent_runs_one_active_per_thread` on agent_runs that no code creates (it enforces one in-flight run per thread). Left untouched and excluded from migration management; full definition in docs/MIGRATIONS.md. The team should decide whether to adopt it into the models or drop it.
> - **Pre-existing test failures (not from this branch):** `test_turn_stream_custom_mcp_reaches_sdk_agent` (test double missing the new manifest_path kwarg) and `test_turn_service_immediate_stream_does_not_block_on_event_journal` (event-journal wait timeout). Both reproduce at the pre-change baseline commit.
> - Because the dev database is shared, the Alembic setup only manages harness-owned tables. The studio_* tables belong to another app, and agent_sessions/agent_messages are created by the OpenAI Agents SDK — all deliberately unmanaged.
>
> ## How it was verified
>
> Each piece ran as a gated procedure on the dev pod with logged receipts: non-destructive verify scripts against the live DB, live smoke turns on a separate port with a build marker proving which code the server loaded, and for identity a matched pair of turns — full identity (fresh tenant saved and recalled; older default-tenant memories correctly did not appear) and missing tenant (normal reply, exactly one identity-gate log line, zero memory operations).

---

## 2. Findings → receipts (your crib sheet for the review conversation)

| Review point | What we did | The receipt |
|---|---|---|
| Branch far behind dev; needs re-base | Fresh branch off dev `7fa86f5`; five commits cherry-picked; one guided conflict | W0 report: all 7 gates PASS; live smoke recalled 4 memories on the new branch; old working copy untouched |
| No real deployment path / migrations | Alembic, full-schema baseline `5258f2433fcb`, one-time stamp, scoped to harness tables | `alembic check`: "No new upgrade operations detected." Only real-DB write: the single bookkeeping row |
| Memory runs its own DB engine | `install_session_factory` seam; app injects `Database.session_factory` at create_app | Server log: "memory sessions: harness session factory installed" and **zero** "fallback engine created" lines |
| Side model calls outside harness conventions | RunConfig parity with SdkSubagentExecutor + usage logging | Side-call log line fires (tokens None/None — SDK does not expose usage; stated honestly) |
| Loose identity; default tenant | `memory_identity_ok` (user AND tenant) at all memory points; no default-tenant writes | Turn A: save+recall under tenant `t-demo` with correct isolation from old rows. Turn B: no tenant → one gate line, zero memory lines |
| No test coverage | 10 new tests: sessions (3), migrations (4), identity + off-by-default guard (3) | Suite 333 passed; the 2 failures proven pre-existing at baseline commit via throwaway worktree |
| Memory must stay off by default (your MC1 condition) | Flag defaults false; only the tests/fixtures demo profile enables it | Guard test fails the build if any non-test profile turns it on |

**MC2 (next candidate, already designed):** recall out of the instruction channel (input-list injection), durable extraction (outbox + retries, covering the structured-output completion path), governed APIs (list/delete/forget/disable + audit events on the governance rails), retention/purge, console tenant plumbing.

## 3. Short message to send Subomi with the MR link

> Merge candidate 1 is up: [link]. It's the foundation half we agreed — re-base onto current dev, Alembic with a verified baseline, memory moved onto the harness's own DB lifecycle, and identity hardening (validated user + tenant required, no more default tenant). Memory is off by default and a test enforces that; the demo fixture is the only profile with it on. Two things flagged in the MR you may want eyes on: a hand-applied unique index on agent_runs that exists in the dev DB but not in code (we left it alone and documented it — team call on adopting vs dropping), and two pre-existing test failures on dev that reproduce without my changes. Candidate 2 (injection channel, durable extraction, governed APIs/retention) is designed and next.

## 4. Opening the MR (GitLab clicks)

1. GitLab → the harness repo → Merge requests → **New merge request**.
2. Source branch: `feature/agentmemory-v3` · Target branch: `dev` → Compare branches and continue.
3. Paste the title and description from section 1.
4. Reviewer: Subomi. Leave "delete source branch" unchecked. If unsure whether she wants it reviewable-now, create it as **Draft** — she can mark it ready.
5. Create, copy the link, send her the section-3 message.
