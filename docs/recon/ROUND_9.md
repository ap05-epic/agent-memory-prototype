# Recon Round 9 — Documentation Fact-Check

**READ-ONLY.** No edits, no state changes, no servers. Run inside `/projects/DigitHarnessRepo/digit-agent-harness-v3` on branch `feature/agentmemory-v3`. Write the full answer to `recon_round_9_answers.md` as flat text with real code quoted.

**Purpose:** the documentation set in `docs/agent-memory/` makes specific factual claims about how the code behaves. This round checks each claim against the code so nothing in the docs is wrong. Documentation that confidently states something false is worse than no documentation at all.

**How to answer each item:** `CONFIRMED` with the quoted code, or `WRONG: <what the code actually says>` with the quoted code. Do not fix anything — report only. Where a claim is about *absence* ("no X anywhere"), show the grep and its result.

---

## Block A — constants and thresholds

Quote each value from the source. Claim → check.

1. `T_SAME = 0.95`, `T_DECIDE_FLOOR = 0.30`, `MIN_RECALL_SIM = 0.35` in `semantic.py`.
2. Blend is `0.7 × similarity + 0.3 × exp(−age_days / 30)` — quote `W_SIM`, `W_RECENCY`, the half-life constant, and the body of `blend_score`.
3. `recency_floor` default in `select_for_recall` (docs say the newest few are always kept regardless of score — quote the parameter and the code that applies it).
4. `store.py`: `MAX_ENTRY_CHARS = 500`, `DEDUP_WINDOW = 20`, `CANDIDATE_LIMIT = 60`, `DECISION_TOP_K = 5`.
5. `recall.py`: `CHAR_BUDGET = 8000`, `INJECT_LIMIT = 20`.
6. `outbox.py`: the lease duration constant, the claim batch size, the backoff formula, and the attempts cap. Docs claim: lease 5 minutes, claim 5 rows, backoff `min(60·2ⁿ, 3600)` seconds, cap 5 attempts.
7. `_digit.py`: the embed timeout constant, and the current `BUILD` string.

## Block B — behaviour claims

For each, quote the code that proves or disproves it.

8. **"Every read and write funnels through `_digit.get_session()`."** Show `get_session` and grep the package for any other session or engine creation.
9. **"In-app memory creates no engine of its own."** Show `install_session_factory`, the preference order in `get_session`, and where `create_app` calls the installer.
10. **"Recall returns nothing rather than raising."** Quote the exception handling in `build_memory_block`.
11. **"Extraction swallows every failure."** Quote the exception handling in `extract_and_store`.
12. **"Any gate failure degrades to a plain add."** Quote the `except` block in `smart_add_entry` and what it sets.
13. **"The decision index is range-validated."** Quote `parse_decision`.
14. **"An older fact can never supersede a newer one, enforced in code."** Quote `may_supersede` and both call sites.
15. **"The injected memory item never reaches stored history."** Quote `session_filter.py` in full and the line in `sdk_runner.py` that wraps the session.
16. **"Memory rides the input list, not the instructions."** Quote the `run_input` construction and confirm by grep that no memory content is added to instructions anywhere (`grep -rn "memory_block" src/agent_factory/runtime/`).
17. **"The tool is gated by the same context flag — no tool-side identity check."** Quote the `memory_enabled` context entry and the guard inside `tool.py`.
18. **"Enqueue failure falls back to the old in-process path."** Quote `enqueue_extraction`.
19. **"Model calls never happen inside an open transaction."** Quote `run_once` and mark where each transaction opens and closes relative to the extraction call.
20. **"Retention purges nothing unless a window is configured."** Quote the retention worker's cycle and the env read.

## Block C — configuration surface

21. List **every** `AGENT_FACTORY_MEMORY_*` environment variable the code actually reads (`grep -rn "AGENT_FACTORY_MEMORY" src/`), with the file and the default. The docs list: `PGVECTOR`, `EMBED_MODEL`, `EMBED_DIM`, `MODEL`, `OUTBOX_ENABLED`, `OUTBOX_INTERVAL_SECONDS`, `RETENTION_DAYS`, `RETENTION_INTERVAL_SECONDS`, `QUIET`. Report any the docs missed and any the docs invented.
22. Quote the `MemoryPolicy` class in full. Docs claim it carries `semantic_memory_enabled`, `retention_days`, `max_entries_per_scope`.
23. Confirm whether `max_entries_per_scope` is enforced anywhere (`grep -rn "max_entries_per_scope" src/`). Docs claim it is declared but **not** enforced.

## Block D — the API surface

24. List every memory route: method, exact path, and whether the handler is `async def`. Docs claim: `GET /api/v1/memory`, `DELETE /api/v1/memory/{entry_id}`, `POST /api/v1/memory/forget`, `POST /api/v1/memory/disable`, `POST /api/v1/memory/enable`, `GET /api/v1/memory/status`.
25. Quote the identity resolution used by those routes, including the tenant helper and the header names it reads.
26. Confirm the 400 and 403 behaviours the docs describe: missing user → 400, missing tenant → 400, mismatched explicit user with auth required → 403.

## Block E — log lines

27. For each line the docs tell an operator to look for, confirm the exact wording in the code: `agent_memory seam loaded build=`, `memory sessions: harness session factory installed`, `fallback engine created (standalone mode)`, `memory gate:`, `memory add id=`, `memory identity gate: disabled for turn`, `memory outbox: processed=`, `memory retention: purged=`, plus whatever line the per-user opt-out emits (quote it — the docs may have the wording wrong).
28. Confirm no log line anywhere in the package interpolates memory content (`grep -rn "log\." src/agent_factory/memory/` and check each).

## Block F — schema and migrations

29. List the migration revisions in order with their `down_revision` and what each creates. Docs claim: `5258f2433fcb` baseline, `6f4f8e6f7f55` outbox, `4f743f1f0d2d` audit + opt-out.
30. Quote the four table definitions' column lists. Docs claim `agent_memory_entries`, `agent_memory_outbox`, `agent_memory_audit`, `agent_memory_user_models` — confirm names and that the audit table has no content column.
31. Quote the `include_name` scoping function in `migrations/env.py` and the unmanaged-index set.

## Block G — tests

32. List every `tests/test_agent_memory_*.py` file with its test count. Docs describe six areas: sessions, migrations, identity + off-by-default guard, input channel, outbox, governance.
33. Quote the off-by-default guard test in full — the docs lean on it heavily as the mechanism that keeps memory disabled.

## Final lines (end with exactly these)

```
CONSTANTS: <all correct | list of wrong ones>
BEHAVIOUR: <all correct | list of wrong ones>
CONFIG: <all correct | missing: … | invented: …>
API: <all correct | list of wrong ones>
LOGS: <all correct | list of wrong wordings>
SCHEMA: <all correct | list of wrong ones>
TESTS: <counts per file>
DOC-RISK: <up to 3 lines: the claims that would most mislead a reader if left wrong>
```
