# W2 — Governed Memory: user-facing APIs, audit trail, retention

**Review item (the big one):** memory is a capability that stores data about people, so it needs the controls any such capability needs — a user must be able to see what is stored about them, delete one item or all of it, and turn it off; every mutation must be auditable; and stored data must not live forever by default.

**Scope of this brief (harness side).** Endpoints, an audit trail, per-user opt-out, and retention/purge. **Not** in this brief: console UI and tenant plumbing — those are W8, deliberately separate because they need `npm install`, browser verification, and a different kind of session.

**Where:** `/projects/DigitHarnessRepo/digit-agent-harness-v3`, branch `feature/agentmemory-v3`, HEAD = the W4 commit `b238f207` or descendant. Standard rules: old folder read-only; port 8081; PID-scoped kills; never force-push; never `reset_dev_tables.py`; DB-writing or pushing commands run strictly alone; restore `agent-console/next-env.d.ts` if it reappears; stop at every GATE and wait.

## GATE 0 — read-first (report, then wait)

1. `git status --short` clean; HEAD correct; `alembic current` shows `6f4f8e6f7f55`.
2. **One endpoint, verbatim and complete:** pick an existing `@app.get` route in `api/app.py` that returns a list of models, and quote it *with* its `response_model`, its Pydantic response class definition, and any `Depends(...)` it uses (≤30 lines). This is the shape our routes must match.
3. **Auth:** quote `_api_auth_required()` and every dependency function used to protect a route today (e.g. `require_worker_registration_token`), plus one route that opts in (≤20 lines). Then answer plainly: **is there any existing way a non-turn endpoint learns the caller's identity** (a header, a dependency, a session)? If not, say NONE — the design below depends on the answer.
4. Quote how `MemoryPolicy` is declared in `core/schemas.py` (verbatim) and how a profile's policy is reached from app code (one example line).
5. Quote the `create_app` region where `MemoryExtractionWorker` is constructed and started (from W4) — the retention worker sits beside it.

## Design

**Identity rule (state it in the report before implementing).** These endpoints act on one person's data, so the scope must be *asserted by the caller and validated*, never trusted blindly:

- Requests carry `profile_id`, `user_id`, `tenant_id` as query parameters (list/forget/disable) or path + query (delete).
- When `_api_auth_required()` is true, the route requires the same authenticated-caller check the turn path uses, and rejects any request whose `user_id` is not the authenticated caller's (403). When auth is off (dev), the parameters are taken at face value — same posture as the rest of the harness in dev.
- If GATE 0 item 3 reports NONE (no identity mechanism exists for non-turn endpoints), implement the parameter-based version, mark the auth check with a clear `TODO(W8/security)` comment, and **say so explicitly in the report and the commit message** — it becomes an open item in the merge request rather than a silent hole.

## Task 1 — schema (Alembic revision 003)

Two additions in `memory/models.py`, then one hand-written revision (`down_revision = "6f4f8e6f7f55"`):

```python
class MemoryAudit(Base):
    """Append-only audit of memory mutations. Content-free by design: ids,
    actions, scope and actor only — never memory text."""

    __tablename__ = "agent_memory_audit"

    id = Column(String(36), primary_key=True, default=_uuid)
    profile_id = Column(String(255), nullable=False)
    user_id = Column(String(255), nullable=False)
    tenant_id = Column(String(255), nullable=False)
    action = Column(String(32), nullable=False)   # write | supersede | delete | forget | disable | enable | purge
    entry_id = Column(String(36), nullable=True)
    actor = Column(String(255), nullable=True)    # who performed it
    source = Column(String(16), nullable=False)   # tool | extraction | api | worker
    detail = Column(String(255), nullable=True)   # counts / reason, never content
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now())

    __table_args__ = (
        Index("ix_agent_memory_audit_scope", "profile_id", "user_id", "created_at"),
    )
```

Plus one nullable column on the existing reserved table so opt-out has a home without a new table: `memory_disabled = Column(Boolean, nullable=True)` on `MemoryUserModel`. (That table is already uniquely keyed by scope — the opt-out row is an upsert.)

## Task 2 — store functions (`memory/store.py`)

Add, each in its own short transaction and each writing one audit row:

- `list_entries(profile_id, user_id, tenant_id, *, include_discarded=False, limit=200)` → live entries newest-first (no audit row; reads are not mutations).
- `record_audit(...)` — the single helper every other function calls.
- `set_memory_disabled(profile_id, user_id, tenant_id, disabled: bool)` → upsert on `agent_memory_user_models`, audit `disable`/`enable`.
- `is_memory_disabled(profile_id, user_id, tenant_id) -> bool` — used by the runtime gate.
- `purge_discarded(older_than_days: int) -> int` — hard-DELETE rows whose `discarded_at` is older than the window; audit one `purge` row with the count in `detail`.

Also add audit calls to the existing paths: `smart_add_entry` records `write` (or `supersede`), `discard_entry` records `delete`, `forget_user` records `forget` with the count. All content-free.

## Task 3 — the runtime opt-out check

In the recall and extraction guards in `sdk_runner.py` (the ones already gated by `memory_identity_ok`), add the user's opt-out: if `is_memory_disabled(...)` returns true, memory does nothing for that turn and logs one content-free line (`memory disabled by user preference`). Cache nothing; one cheap indexed read per turn is fine, and correctness beats micro-optimisation here.

## Task 4 — endpoints (`api/app.py`, following the GATE 0 shapes)

| Method + path | Does |
|---|---|
| `GET /api/v1/memory` | list this scope's live entries (id, content, category, source, created_at, observed_at) |
| `DELETE /api/v1/memory/{entry_id}` | soft-delete one entry — 404 if it is not in the caller's scope |
| `POST /api/v1/memory/forget` | discard every live entry in scope, returns the count |
| `POST /api/v1/memory/disable` / `POST /api/v1/memory/enable` | set the per-user opt-out |
| `GET /api/v1/memory/status` | `{enabled, entry_count, oldest, newest, disabled_by_user}` — what the console will show |

Match the file's existing route style exactly: `response_model` Pydantic classes declared alongside the other response models, query parameters typed, and the auth dependency per the identity rule above. Every mutating route returns the audit row's id so an action can be traced.

## Task 5 — retention worker

In a new `memory/retention.py`, `MemoryRetentionWorker` copying the `MemoryExtractionWorker` lifecycle exactly (env-gated, named task, `stop()` awaited before the databases close). Each cycle, if `AGENT_FACTORY_MEMORY_RETENTION_DAYS` is set and > 0, call `purge_discarded(days)` and log `memory retention: purged=N`. **Default is unset = no purging** — turning on hard deletion is a governance decision, not a default. Interval `AGENT_FACTORY_MEMORY_RETENTION_INTERVAL_SECONDS`, default 3600. Wire it beside the extraction worker in `create_app`.

Also extend `MemoryPolicy` in `core/schemas.py` with two optional, non-breaking fields — `retention_days: int | None = None` and `max_entries_per_scope: int | None = None` — and read `retention_days` as a per-profile override of the env default where a profile is in scope. `max_entries_per_scope` is declared but not enforced in this brief; note that in the commit.

Bump `BUILD` in `_digit.py` to `"2026-07-25.12-w2-governed"`.

## Task 6 — tests (`tests/test_agent_memory_governance.py`)

House style (plain pytest, `asyncio.run`, sqlite factory installed via `_digit.install_session_factory`, tables from `Base.metadata`):

1. `list_entries` returns only the caller's scope — seed two scopes, assert no leakage.
2. `discard_entry` on an entry outside the scope does not delete it (the API's 404 path).
3. `forget_user` discards all live entries in scope and writes exactly one `forget` audit row with the count.
4. Opt-out round trip: `set_memory_disabled(True)` → `is_memory_disabled` true → audit row `disable`; then `False` → `enable`.
5. `purge_discarded(days)` deletes only rows discarded older than the window, leaves live rows untouched, and audits the count.
6. Audit rows never contain memory content: assert the content string does not appear in any audit column.
7. API tests via `TestClient` for the list and forget routes, following the repo's existing TestClient pattern (in-memory or sqlite-backed, monkeypatched env).

## GATE A — static + tests

`python3 -m py_compile` all touched files; the new test file passes; full suite shows nothing newly failing beyond the two documented pre-existing failures.

## GATE B — migration (human-gated)

Print `python3 -m alembic upgrade head` and WAIT for explicit confirmation. Then, each alone: `alembic current` (shows revision 003), `alembic check` (no new operations), and a read-only query proving `agent_memory_audit` exists and `agent_memory_user_models` has the new column.

## GATE C — live proof (port 8081)

Launch as usual; marker must read `build=2026-07-25.12-w2-governed`. Then, with full identity (`console-user` + `t-demo`), using curl against the new routes and quoting every response:

1. `GET /api/v1/memory` lists the existing entries for that scope.
2. `GET /api/v1/memory` for a *different* `user_id` returns none of them.
3. `POST /api/v1/memory/disable` → then run a memory turn: the reply is normal, the log shows `memory disabled by user preference`, and no memory write occurs. Then `POST /api/v1/memory/enable` and confirm a turn recalls again.
4. `DELETE /api/v1/memory/{id}` on one entry → it disappears from the list; the audit table has a matching `delete` row.
5. `SELECT action, count(*) FROM agent_memory_audit GROUP BY action` — quote it. Confirm no audit column contains memory text.
6. Stop the server by its exact PID.

## GATE D — commit + push (plain wording)

```
memory: user-facing controls, audit trail and retention

Adds endpoints so a user can see what is stored about them, delete a
single memory, forget everything in their scope, and turn memory off for
themselves. Every mutation writes a row to a new append-only audit table
(Alembic revision 003) recording the action, scope, actor and source -
ids and counts only, never memory text.

Per-user opt-out is stored on the reserved user-model table and checked
at the start of every turn, alongside the existing identity gate.

Adds a retention worker beside the extraction worker: when a retention
window is configured it hard-deletes rows that were soft-deleted longer
ago than the window, completing the two-stage deletion story. It is off
unless configured, because turning on hard deletion is a governance
decision rather than a default.

Adds tests for scope isolation, cross-scope delete protection, forget,
opt-out, purge windows, and that audit rows never contain memory text.
```

If the identity rule ended up as parameter-based (GATE 0 item 3 = NONE), add one sentence to the commit saying so, and list it in the final report as an open item for the merge request.

Plain `git push`. Final report: SHAs, gate outcomes, quoted receipts, and the identity-rule outcome.

## Rollback

Before GATE B: all local. After: `alembic downgrade -1` drops the audit table and the added column — report before running it; human decision. Old folder untouched throughout.

## Report format

```
GATE <x>: PASS or FAIL
<KEY>: <value>
NEXT: waiting for human
```
