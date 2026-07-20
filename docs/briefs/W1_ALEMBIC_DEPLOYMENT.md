# W1 — Alembic in the Harness: real migrations, create_all demoted to local/test bootstrap

**Team-lead decision (verbatim intent):** Option A — Alembic in the harness. "Memory schema is not really memory-only anymore; it is harness production infrastructure. Keep create_all only for local/test bootstrap, and make deployed envs run migrations explicitly."

**Where:** `/projects/DigitHarnessRepo/digit-agent-harness-v3`, branch `feature/agentmemory-v3`. Run AFTER W5 is committed. OLD folder read-only; never force-push; never run `reset_dev_tables.py`.
**Who:** GPT-5.4 Copilot CLI, gated as usual: stop at every GATE, print the flat-text report, wait.

## Shape of the change

1. Add `alembic` as a dependency and initialize it (async template) at repo root: `alembic.ini` + `migrations/`.
2. `migrations/env.py` targets the harness's real metadata: import `agent_factory.persistence.models` AND `agent_factory.memory.models` (memory tables are part of the harness schema now — that's the point), `target_metadata = Base.metadata`, URL from `AGENT_FACTORY_DATABASE_URL` via `normalize_async_database_url`, async-engine `run_sync` recipe.
3. **Revision 001 = baseline of the entire current schema** (all harness tables + the two memory tables + indexes/uniques). New environments bootstrap with `alembic upgrade head`; existing databases adopt via a one-time `alembic stamp head`.
4. `create_all` stays exactly as-is mechanically (behind `AGENT_FACTORY_DB_CREATE_TABLES`) but is documented as local/test bootstrap only.
5. Ops doc + a cheap test slice.

## GATE 0 — read-first (report, wait)

1. `git status --short` clean (restore `agent-console/next-env.d.ts` if it reappears — never commit it); HEAD is the W5 commit or a descendant on `feature/agentmemory-v3`.
2. Quote the `[project]` dependencies block of `pyproject.toml` (style for adding `alembic`), and report `python3 -c "import alembic"` (already available or needs install).
3. Confirm there is no existing `alembic.ini`/`migrations/` anywhere (`find . -name alembic.ini -not -path "./node_modules/*"`).
4. Quote where `AGENT_FACTORY_DB_CREATE_TABLES` is read and where `create_tables()` is called (lifespan?) — 5 lines around each; the ops doc must describe reality.
5. Report which model modules exist under `src/agent_factory/persistence/` (models.py only, or more) so env.py imports the complete set.

## Task 1 — dependency

Add `alembic` to `pyproject.toml` dependencies (match the file's style), then install it the same way the project was installed in W0 GATE 4 (editable install / pip). Report the installed version.

## Task 2 — init + env.py

`alembic init -t async migrations` at the repo root. Then edit:

- `alembic.ini`: leave `sqlalchemy.url` empty/commented — env.py owns the URL.
- `migrations/env.py`:
  - `import os`, then make `src/` importable the way the repo's tooling does (if running from repo root with the editable install, plain imports work — verify).
  - `from agent_factory.persistence.models import Base` and `import agent_factory.persistence.models  # noqa` plus `import agent_factory.memory.models  # noqa` (register every table on the metadata), plus any additional model modules found at GATE 0 item 5.
  - `from agent_factory.persistence.urls import normalize_async_database_url`; set the URL from `AGENT_FACTORY_DATABASE_URL` (fail with a clear message if unset).
  - `target_metadata = Base.metadata`.
  - Since memory models pick their embedding column type from env: set `AGENT_FACTORY_MEMORY_PGVECTOR=1` context — document at the top of env.py that migrations are authored against the pgvector column type (`vector(1536)`), and that this env var must be set when running alembic (add `os.environ.setdefault("AGENT_FACTORY_MEMORY_PGVECTOR", "1")` in env.py so it's deterministic).
  - `compare_type=True` in the `context.configure(...)` calls.

## Task 3 — the baseline revision

Generate revision 001 by diffing the metadata against an EMPTY database, then hand-review:

1. `AGENT_FACTORY_DATABASE_URL=sqlite+aiosqlite:////tmp/alembic_baseline_scratch.db alembic revision --autogenerate -m "baseline: full harness schema incl. agent memory tables"` — the empty scratch DB makes autogenerate render `create_table` for everything. (This is a rendering trick only; nothing runs against sqlite afterwards. If aiosqlite is unavailable, install it as a dev step or report.)
2. Hand-review the generated revision and fix Postgres realities: the memory `embedding` column must be `pgvector.sqlalchemy.Vector(1536)` with the proper import at the top of the revision file; `server_default=func.now()` preserved; JSON/JSONB columns rendered correctly; all indexes and unique constraints present (`ix_agent_memory_entries_scope`, `uq_agent_memory_user_models_scope`, and every existing harness index). List in the report every table the revision creates — the count must match `Base.metadata.tables`.
3. Add one guard line at the top of `upgrade()` for the vector extension: `op.execute("CREATE EXTENSION IF NOT EXISTS vector")` (matches how the live DB was provisioned; harmless if present — note: requires the extension to be allow-listed on Azure, which it already is on this server).
4. Delete the scratch sqlite file.

## GATE A — offline verification (no DB writes)

1. `alembic upgrade head --sql > /tmp/alembic_baseline.sql` (offline mode renders the full DDL). Report: table count in the SQL, presence of `CREATE TABLE agent_memory_entries` with `embedding vector(1536)`, and the extension guard. Paste the memory-table DDL sections into the report.
2. `alembic history` shows exactly one revision; `python3 -c` import of the revision file compiles.
3. Confirm zero writes so far to the real dev DB.

## GATE B — adopt on the shared dev DB (ONE row written — human confirms first)

The dev database already has every table, so it adopts the baseline by stamping (writes only the `alembic_version` bookkeeping row — no DDL):

1. Print the exact command and WAIT for explicit human continue:
   `alembic stamp head` (with `AGENT_FACTORY_DATABASE_URL` sourced from the v3 `.env`).
2. After stamping: `alembic check` — expected result: no new operations detected (proves the baseline matches the live schema; if it reports drift, STOP and paste the drift — that's a baseline bug we must see).
3. `alembic current` shows the baseline revision id.

## Task 4 — ops doc + create_all demotion note

1. New `docs/MIGRATIONS.md` in the harness repo (this becomes part of MC1): how a NEW environment bootstraps (`alembic upgrade head`), how an EXISTING database adopts (`alembic stamp head` once), how future schema changes work (edit models → `alembic revision --autogenerate` → review → `upgrade head` per env), the `AGENT_FACTORY_MEMORY_PGVECTOR=1` requirement when authoring, and — per the team lead — that `AGENT_FACTORY_DB_CREATE_TABLES`/`create_all` is local/test bootstrap ONLY and deployed environments apply schema exclusively via migrations.
2. In the code, add one comment line at the `create_tables` call site found in GATE 0 item 4: `# Local/test bootstrap only — deployed environments run "alembic upgrade head" (see docs/MIGRATIONS.md).` No behavior change.

## Task 5 — test slice

`tests/test_migrations.py`, plain pytest (no DB): (1) alembic `Config` loads and the script directory resolves; (2) the revision graph has exactly one head; (3) the baseline revision's `upgrade()` source contains `agent_memory_entries` and `agent_memory_user_models` (regression guard that memory tables stay in the baseline). Run it plus the repo's existing suite; nothing previously green may break.

## GATE C — commit + push

```
harness: adopt Alembic migrations with a full-schema baseline

Per team-lead decision, migrations are now the deployment path for schema:
alembic init (async template), env.py targeting the harness Base.metadata
with persistence AND agent-memory models registered, and revision 001 as a
reviewed baseline of the entire current schema (including the memory
tables and the pgvector extension guard). The shared dev database adopted
the baseline via a one-time stamp, verified drift-free with alembic check.
create_all remains local/test bootstrap only and is documented as such in
docs/MIGRATIONS.md. Adds a no-DB test slice covering config load, single
head, and memory-table presence in the baseline.
```

Plain `git push`. Final report: gate outcomes, revision id, `alembic check` output, files touched.

## Rollback

Before GATE B: everything is local — `git checkout -- .` / delete `migrations/`. After stamping: the only DB artifact is the `alembic_version` row; report before touching it — removal is a human decision, not yours.

## Report format

```
GATE <x>: PASS or FAIL
<KEY>: <value>
NEXT: waiting for human
```
