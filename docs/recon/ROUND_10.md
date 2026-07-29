# Recon Round 10 — Documentation Fact-Check, Part Two

**READ-ONLY.** No edits, no state changes, no servers, and do **not** fix anything you find — report only. Run inside `/projects/DigitHarnessRepo/digit-agent-harness-v3` on `feature/agentmemory-v3`. Write the answer to `recon_round_10_answers.md` as flat text with real code quoted.

**Why:** round 9 verified the documentation against the code as it stood *before* the test-hardening workstream, the dev merge, and the console work. Everything those three changed is currently asserted in the docs but unverified. This round checks only that delta.

**Answer format:** `CONFIRMED` with quoted evidence, or `WRONG: <what the code actually says>` with quoted evidence. For any claim about *absence*, show the command and its full output — a missing line in a listing looks exactly like a missing file, and we have been caught by that once already.

---

## Block A — the test surface

1. List every file matching `tests/test_agent_memory*.py` **and** `tests/test_migrations.py`. Use `ls -1` (not `find`) and paste the raw output. The docs claim twelve memory-related files.
2. For each, the number of test functions (`grep -c "^def test_"`). The docs claim: semantic 17, write_gate 10, recall 6, extraction 4, tool 2, roundtrip 3, regressions 3, sessions 3, input_channel 4, outbox 6, governance 7, migrations 4.
3. Run the full suite and paste the final line verbatim. The docs claim **466 passed, 2 skipped, 0 failed**, and state there is no known-failures allowance.
4. Quote the off-by-default guard test in full from wherever it lives.

## Block B — the recall-count fix

5. Quote `_entry_lines` from `memory/recall.py` in full.
6. Quote `render_block` — the docs claim its public signature is **unchanged** by the refactor.
7. Quote the return statement of `build_memory_block` — the docs claim the count now reflects the lines actually rendered, not the entries selected.

## Block C — what the dev merge left behind

8. `grep -n "EventName.RUN_COMPLETED" src/agent_factory/runtime/sdk_runner.py` — the docs imply one terminal per successful turn. Report every hit and state how many can fire on one normal turn.
9. `grep -n "_enqueue_memory_extraction_if_eligible" src/agent_factory/runtime/sdk_runner.py` — expect one definition and one call. Quote the helper in full, including its guards.
10. `grep -n "memory_identity_ok" src/agent_factory/runtime/sdk_runner.py` — confirm the recall guard and the enqueue helper both use it.
11. `grep -rn '"default"' src/agent_factory/runtime/sdk_runner.py` — the docs claim no default-tenant fallback survives in the runner's memory paths. Report hits with context, or NONE.

## Block D — the console layer

12. `ls -R agent-console/app/api/harness/memory/` — the docs claim six routes: the collection, `status`, `[entryId]`, `forget`, `disable`, `enable`.
13. Quote the tenant read from `agent-console/lib/harness.ts`. The docs claim the variable is **`DIGIT_CONSOLE_TENANT_ID`**, read **server-side only** — confirm it is not prefixed `NEXT_PUBLIC_` and is not referenced from any client component (`grep -rn "DIGIT_CONSOLE_TENANT_ID" agent-console/`).
14. Quote where `tenant_id` is added to the turn body in `app/api/harness/chat/route.ts`, and confirm it is omitted entirely when the value is unset.
15. Quote one memory proxy route in full and confirm which headers it forwards. The docs claim `x-user-id` and `x-tenant-id`.
16. Confirm the package manager: does `agent-console/package.json` declare one, and does a `pnpm-lock.yaml` exist? The docs tell developers to use `pnpm`, not `npm`.
17. **The "no harness changes" claim.** `git show --stat <the W8 commit>` — the docs say the harness needed no source changes for the console work because it already read `x-tenant-id`. Confirm the only `src/` change in that commit is tests, or report what else changed.

## Block E — configuration and schema, re-checked

18. `grep -rn "AGENT_FACTORY_MEMORY\|DIGIT_CONSOLE_TENANT" src/ agent-console/lib agent-console/app --include=*.py --include=*.ts` — list every variable actually read, with its default. Compare against the docs list: `PGVECTOR`, `EMBED_MODEL`, `EMBED_DIM`, `MODEL`, `OUTBOX_ENABLED`, `OUTBOX_INTERVAL_SECONDS`, `RETENTION_DAYS`, `RETENTION_INTERVAL_SECONDS`, `QUIET`, `DIGIT_CONSOLE_TENANT_ID`.
19. `ls migrations/versions/` and, for each, its `revision` and `down_revision`. The docs claim exactly three, chained baseline → outbox → audit.
20. `python3 -m alembic check` — expect no new operations. (Read-only; it does not write.)

## Final lines (end with exactly these)

```
TESTS: <file list + counts, or the corrections>
SUITE: <the verbatim final line>
RECALL-FIX: <correct | wrong: …>
MERGE-STATE: <run_completed sites, enqueue sites, identity guards, default-tenant hits>
CONSOLE: <routes, env var, header forwarding, package manager — correct or corrections>
CONFIG: <missing: … | invented: … | all correct>
SCHEMA: <revisions + alembic check result>
DOC-RISK: <up to 3 lines: the claims that would most mislead a reader if left wrong>
```
