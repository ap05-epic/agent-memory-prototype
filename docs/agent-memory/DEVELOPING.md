# Developing on Agent Memory

How to work on this feature without breaking it. Read [ARCHITECTURE.md](ARCHITECTURE.md) first if you haven't — this assumes you know the shape.

---

## The layout

```
src/agent_factory/memory/     the feature; self-contained
  _digit.py                   the seam - the ONLY file that touches harness code
  models.py  semantic.py  store.py  recall.py  tool.py
  extraction.py  outbox.py  retention.py  session_filter.py
tests/test_agent_memory_*.py  the test suite
migrations/versions/          schema changes
```

**The seam rule:** every harness import lives in `_digit.py`. Sessions, logging, model calls, embeddings, identity extraction — all of it. Everything else in the package is plain Python that can be unit-tested without a harness, a database, or a network. If you find yourself importing `agent_factory.something` into any other memory file, stop: that dependency belongs in the seam.

## Getting it running

```bash
cd <harness>
unset AZURE_OPENAI_BASE_URL OPENAI_API_KEY OPENAI_BASE_URL     # stale shell vars win over .env
set -a && . ./.env && set +a
export AGENT_FACTORY_PROFILE_PATHS=<harness>/tests/fixtures/profiles
export AGENT_FACTORY_MEMORY_PGVECTOR=1
export AGENT_FACTORY_MEMORY_EMBED_MODEL=text-embedding-3-large
export AGENT_FACTORY_MEMORY_EMBED_DIM=1536
export AGENT_FACTORY_MEMORY_MODEL=gpt-5.4-mini
PYTHONPATH=src PORT=8081 <launch uvicorn> > /tmp/memory.log 2>&1
```

**Before trusting anything you see, confirm two lines in that log:**

```
agent_memory seam loaded build=<the marker in _digit.py>
memory sessions: harness session factory installed
```

The first proves which copy of the code the process actually loaded. The second proves it is using the app's database pool rather than its own. We lost three debugging sessions once to a stale server serving old code while we "fixed" things that were never running — hence the marker. Bump it whenever you change the package.

Then drive a turn with a full identity (a user id **and** a tenant id). Without both, memory switches itself off and you will conclude it is broken when it is behaving exactly as designed.

## Testing

```bash
pytest tests/test_agent_memory_*.py        # the feature's own suite
pytest                                     # everything
python scripts/verify_phase_a.py           # live: plumbing and scoping
python scripts/verify_phase_c.py           # live: the semantic layer, 12 checks
```

The `verify_phase_*` scripts talk to a real database (and optionally a real embedder) and print `PHASE_x: PASS|FAIL`. They exist because unit tests with fakes cannot catch a vector-column dimension mismatch or a credential problem — both of which have bitten us.

Two failures in the full suite are **pre-existing on dev** and not yours: `test_turn_stream_custom_mcp_reaches_sdk_agent` and `test_turn_service_immediate_stream_does_not_block_on_event_journal`. Confirm any new failure isn't one of those before investigating.

**Writing tests:** plain pytest with `asyncio.run(...)`; no async plugin is configured. For anything touching the database, install an aiosqlite factory via `_digit.install_session_factory(...)` and create tables from `Base.metadata`. Stub the embedder by monkeypatching `_digit.embed`, and pass a fake `decide` callable rather than reaching a real model.

## Making common changes

**Adding a column or table.** Edit `models.py`, then generate a migration:

```bash
AGENT_FACTORY_MEMORY_PGVECTOR=1 alembic revision --autogenerate -m "what it does"
```

Then *read the generated file* — autogenerate gets vector columns and server defaults wrong often enough that reviewing is not optional. Apply with `alembic upgrade head`. Never use `create_all` outside local scratch work; the deployed path is migrations only.

**Changing recall ranking.** The maths lives in `semantic.py` (`blend_score`, `select_for_recall`) and is pure — unit-test it directly. Anything that changes what gets injected should be checked against a live turn too, because ranking that looks right in a test can still surface the wrong memory in practice.

**Changing the write gate.** `store.smart_add_entry` is the ladder. Keep two invariants: every failure path must end in a plain ADD, and no path may hold a database session open across a model call. Both have been violated before and both caused real problems.

**Adding an API endpoint.** Follow the existing memory routes: `async def` handlers (never sync — see the pitfalls below), scope resolved with `_effective_user_id(...)` plus the tenant header, and one audit row per mutation.

**Changing extraction behaviour.** The prompt lives in `extraction.py`. Remember that already-stored facts are passed in so they aren't re-extracted, and that the tool path and extraction path can starve each other: a fact saved by the tool looks "already known" to extraction. That interaction has caused a real bug before.

## Pitfalls, all learned the hard way

- **Sync route handlers.** FastAPI runs `def` handlers in a worker thread. Bridging from there into async database calls creates a second event loop and produces `got Future attached to a different loop`, breaking connections borrowed from the shared pool — it cost us a debugging session on the governance endpoints. Always `async def`, always `await` directly, no `asyncio.run` anywhere in a request path.
- **Long transactions around model calls.** The outbox worker originally held a `FOR UPDATE` claim open across the whole extraction. Claim in a short transaction that leases the rows, process holding nothing, finalise in another short transaction.
- **Stale servers.** If behaviour doesn't match your code, check the build marker before debugging the logic.
- **Ambient environment variables.** A stale `AZURE_OPENAI_BASE_URL` in the shell silently overrides `.env` and produces 401s that look like bad credentials. Unset before sourcing.
- **Assuming SDK behaviour.** We assumed input items weren't persisted to session history; they are. A ten-minute throwaway probe caught it before it became a slow leak of duplicated rows. Probe first when an assumption is load-bearing.
- **Borrowed thresholds.** Similarity numbers from papers did not survive contact with our embedder — a real contradiction measured 0.309 where the literature implied 0.70+. Every write logs `memory gate: top_sim=… tier=… action=…` so calibration stays evidence-based.
- **The two-part identity.** Memory needs a user *and* a tenant. Most "memory is broken" reports turn out to be a missing tenant.

## Keeping the branch current

The feature branch drifts from `dev` at whatever rate the team ships. Merge `dev` in **weekly, and always before starting a new piece of work** — never let it pass roughly fifty commits, because small merges are boring and large ones are the ones people tell stories about.

```bash
git status --short                     # must be clean first
git fetch origin
git rev-list --left-right --count origin/dev...HEAD    # behind / ahead
git merge origin/dev
```

Use merge rather than rebase: the branch is pushed and shared. On conflicts, the rule of thumb is that files under `memory/` are ours and take our version, while harness files take dev's structure with our insertions re-placed into it. After any non-trivial merge, run the suite *and* drive one live turn — a merge that compiles can still have moved an integration point out from under us.

## Definition of done for a change here

- Unit tests for any pure logic you touched, and a database-level test if you touched the write or read path.
- The full suite green apart from the two known failures.
- A live turn driven end to end, with the build marker confirmed in the log first.
- If you changed the schema: a reviewed migration, applied, with `alembic check` reporting no drift.
- If you changed behaviour a user could notice: [ARCHITECTURE.md](ARCHITECTURE.md) and [OPERATIONS.md](OPERATIONS.md) updated in the same change.
