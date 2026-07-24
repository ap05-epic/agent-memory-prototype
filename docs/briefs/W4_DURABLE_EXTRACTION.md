# W4 — Durable Extraction: the outbox

**Review item:** post-turn extraction is fire-and-forget — if the process dies between the turn ending and the extraction finishing, that memory is silently lost, and some completion paths (dev's structured-output agents skip RESPONSE_COMPLETED) may never fire it at all. **Target:** every eligible turn durably enqueues an extraction job in an `agent_memory_outbox` table; an in-app background worker processes jobs with retries and backoff; pending work survives restarts. At-least-once delivery — the existing dedup gate makes replays harmless.

**Where:** `/projects/DigitHarnessRepo/digit-agent-harness-v3`, branch `feature/agentmemory-v3`, HEAD = `8c75ac2` or descendant. Standard rules: old folder read-only; port 8081; PID-scoped kills; never force-push; never `reset_dev_tables.py`; DB-writing/pushing commands run strictly alone; restore `next-env.d.ts` if it appears; stop at every GATE.

**Patterns to copy (round-8 receipts):** the worker is modeled on `ProfileHealthMonitor` — service object, named `asyncio.create_task` in lifespan startup, `await stop()` FIRST in the lifespan `finally`, before the databases close. The migration is Alembic revision 002 on the baseline we installed in W1 — the framework's first real schema change.

## GATE 0 — read-first (report, wait)

1. `git status --short` clean; HEAD `8c75ac2` or descendant; branch correct.
2. **Completion sites:** quote where `EventName.RUN_COMPLETED` is yielded in `runtime/sdk_runner.py` (all occurrences, 5 lines context each), and where the current `schedule_extraction(...)` call sits. Answer explicitly: is RUN_COMPLETED emitted on ALL successful completion paths, including the structured-output path that skips RESPONSE_COMPLETED? (grep `uses_structured_output` and quote how that path ends.) The outbox write wants ONE site common to every successful turn; identify it.
3. Confirm `final_output` (or its equivalent) and `_user` are in scope at that site.
4. Quote the lifespan startup line where `profile_health_monitor.start()` runs and the `finally` shutdown ordering (round 8 showed it; re-confirm on current HEAD).
5. Confirm no table named `agent_memory_outbox` exists in the DB (read-only inspector query) and `alembic current` shows `5258f2433fcb (head)`.
6. Report whether the console/worker-router path can execute turns in a separate process on this branch (one line — if yes, note that outbox WRITES from such a process ride the W5 fallback engine and the shared table; the processor stays in the main app).

## Task 1 — model + migration (revision 002, hand-written)

1. In `src/agent_factory/memory/models.py`, add:

```python
class MemoryOutbox(Base):
    """Durable queue of pending extraction jobs (at-least-once; the write
    gate's dedup makes replays harmless). Rows are deleted on success;
    failed rows are kept with last_error for inspection."""

    __tablename__ = "agent_memory_outbox"

    id = Column(String(36), primary_key=True, default=_uuid)
    profile_id = Column(String(255), nullable=False)
    user_id = Column(String(255), nullable=False)
    tenant_id = Column(String(255), nullable=False)
    thread_id = Column(String(255), nullable=True)
    user_text = Column(Text, nullable=False)
    assistant_text = Column(Text, nullable=False)
    status = Column(String(16), nullable=False, default="pending")  # pending | failed
    attempts = Column(Integer, nullable=False, default=0)
    next_attempt_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now())
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now())
    last_error = Column(Text, nullable=True)

    __table_args__ = (
        Index("ix_agent_memory_outbox_claim", "status", "next_attempt_at"),
    )
```

2. New file `migrations/versions/<generated-id>_add_agent_memory_outbox.py`, hand-written (one table — no autogenerate needed): `down_revision = "5258f2433fcb"`, `upgrade()` = `op.create_table(...)` matching the model exactly + the claim index; `downgrade()` = drop. `python3 -m py_compile` it.

## Task 2 — the writer (one site, all paths)

At the common completion site identified in GATE 0 item 2, REPLACE the current `schedule_extraction(...)` call with a durable enqueue, same guard conditions as today (memory flag AND `memory_identity_ok(_user)`):

```python
from agent_factory.memory.outbox import enqueue_extraction
await enqueue_extraction(
    profile_id=profile.profile_id,
    user_id=_user.user_id,
    tenant_id=_user.tenant_id,
    thread_id=thread_id,
    user_text=str(effective_request.input),
    assistant_text=final_output,
)
```

`enqueue_extraction` lives in the new `src/agent_factory/memory/outbox.py`: one INSERT through `_digit.get_session()`, wrapped in try/except — on any failure it logs one content-free line and falls back to `schedule_extraction(...)` (today's behavior is the floor, never lost ground). `schedule_extraction` itself stays exported for standalone use.

If GATE 0 shows the structured-output path ends somewhere RUN_COMPLETED does not cover, add the same guarded enqueue there and say so in the report.

## Task 3 — the worker

In `src/agent_factory/memory/outbox.py`, add `MemoryExtractionWorker` copying the `ProfileHealthMonitor` shape exactly (constructor takes enabled + interval; `start()` creates a named task `agent-memory-outbox-worker`; `async stop()` sets the event and awaits the task). Each cycle:

1. Claim up to 5 due rows: `status='pending' AND next_attempt_at <= now()`, ordered by `created_at` — with `FOR UPDATE SKIP LOCKED` when the dialect is postgresql (plain select on sqlite so tests run).
2. Per row: call the existing `extraction.extract_and_store(Identity(...), user_text, assistant_text)`. Success → DELETE the row. Exception → `attempts += 1`, `last_error = str(exc)[:500]`, `next_attempt_at = now() + min(60 * 2**attempts, 3600) seconds`; when `attempts >= 5` → `status='failed'` (kept for inspection).
3. One content-free log line per non-empty cycle: `"memory outbox: processed=%d failed=%d"`.

Wiring in `create_app`: construct next to the health monitor when `database is not None` — `MemoryExtractionWorker(enabled=_enabled_env("AGENT_FACTORY_MEMORY_OUTBOX_ENABLED", default=True), interval_seconds=_float_env("AGENT_FACTORY_MEMORY_OUTBOX_INTERVAL_SECONDS", 3.0))` (reuse the existing env helpers) — `start()` right after `profile_health_monitor.start()`, `await stop()` right before the health monitor's stop in the `finally` (workers stop before databases close). Bump `BUILD` to `"2026-07-24.11-w4-outbox"`.

## Task 4 — tests (`tests/test_agent_memory_outbox.py`)

House style (plain pytest + asyncio.run, sqlite factory installed via `_digit.install_session_factory`, create tables from `Base.metadata` incl. the new one):

1. Enqueue writes a pending row with the right scope fields.
2. One worker cycle with a monkeypatched `extract_and_store` returning success → row deleted.
3. Monkeypatched failure → attempts incremented, `next_attempt_at` in the future, row still pending; failure repeated to the cap → `status='failed'`.
4. Backoff math: attempts 1..5 produce nondecreasing delays capped at 3600s.
5. Writer fallback: monkeypatch the session factory to raise → `enqueue_extraction` falls back to `schedule_extraction` without raising.

## GATE A — static + tests

`py_compile` all touched files; new tests pass; full suite still exactly the two documented pre-existing failures.

## GATE B — apply the migration (human-gated, the framework's first real upgrade)

1. Print the exact command and WAIT for explicit human continue:
   `python3 -m alembic upgrade head` (env sourced from the v3 root). This creates ONE new empty table + index on the shared dev DB. Additive only; no existing table is touched.
2. Then, each alone: `alembic current` (shows 002), `alembic check` (expected: no new operations), and a read-only inspector query proving `agent_memory_outbox` exists and is empty.

## GATE C — live proof: the restart-survival beat

1. Launch on 8081 (usual overrides; marker `build=2026-07-24.11-w4-outbox`). One full-identity turn (console-user + t-demo): "Remember: I take my coffee black." Require: `memory outbox:` processed line within ~10s, the memory add log from the worker's extraction OR tool save, and the outbox table back to empty (rows deleted on success).
2. **The durability receipt.** Stop the server (exact PID). With the server DOWN, INSERT one synthetic row via a scratch python (through the fallback engine): scope memory-demo/console-user/t-demo, user_text "Remember: I love pistachio ice cream.", assistant_text "Got it.", status pending. Confirm rowcount 1. Start the server again. Require: within ~15s the worker logs a processed line, the outbox is empty, and a `memory add ... source=extraction` (or gate) line appears for that scope. Then one recall turn (full identity): the reply mentions pistachio. That sequence — enqueued while dead, processed on boot, recalled live — IS the review answer.
3. Stop the server by its exact PID.

## GATE D — commit + push (plain wording)

```
memory: durable extraction with an outbox and background worker

Post-turn extraction is no longer fire-and-forget. Eligible turns write a
row to the new agent_memory_outbox table (Alembic revision 002), and a
background worker in the app processes rows with retries and backoff,
deleting them on success and keeping failed rows with the error for
inspection. Pending work survives restarts: a row enqueued while the
server is down is processed on the next boot. The worker starts and stops
with the app lifespan, before the database closes, following the
ProfileHealthMonitor pattern. If the outbox write itself fails, the old
fire-and-forget path still runs so behavior never gets worse. Replays are
harmless because the write gate deduplicates. Adds tests for enqueue,
success, retry/backoff, the failure cap, and the fallback.
```

Plain `git push` (SSH fix first if fresh session). Final report: SHAs, gate outcomes, the restart-survival receipts quoted.

## Rollback

Before GATE B: all local. After the migration: `alembic downgrade -1` drops only the empty outbox table — report before running it; human decision. Old folder untouched throughout.

## Report format

```
GATE <x>: PASS or FAIL
<KEY>: <value>
NEXT: waiting for human
```
