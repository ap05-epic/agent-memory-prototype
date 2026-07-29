# Operating Agent Memory

Enabling it, configuring it, watching it, and diagnosing it. For how it works internally see [ARCHITECTURE.md](ARCHITECTURE.md).

---

## Turning it on for an agent

Two lines in the agent's profile:

```yaml
memory:
  semantic_memory_enabled: true    # the master switch
tools:
  function_tools:
    - save_memory                  # lets the agent save explicitly
```

The flag alone gives the agent recall and automatic extraction; the tool adds explicit "remember this" saves. Without the flag, no memory code runs for that agent at all.

**It also needs identity.** Memory only operates when the turn carries both a validated `user_id` and a `tenant_id`. Miss either and memory silently disables itself for that turn and logs one line. This is deliberate: it is better to forget than to file someone's data under the wrong owner.

## Configuration

| Variable | Default | What it does |
|---|---|---|
| `AGENT_FACTORY_MEMORY_PGVECTOR` | off | Store embeddings in a `vector` column instead of packed bytes. Must match the column type already in the database. |
| `AGENT_FACTORY_MEMORY_EMBED_MODEL` | `text-embedding-3-large` | Embedding deployment name |
| `AGENT_FACTORY_MEMORY_EMBED_DIM` | `1536` | Dimensions requested; must match the column |
| `AGENT_FACTORY_MEMORY_MODEL` | harness default | Model used for gate decisions and extraction |
| `AGENT_FACTORY_MEMORY_OUTBOX_ENABLED` | `true` | Run the extraction worker |
| `AGENT_FACTORY_MEMORY_OUTBOX_INTERVAL_SECONDS` | `3.0` | How often it drains the queue |
| `AGENT_FACTORY_MEMORY_RETENTION_DAYS` | unset | How long soft-deleted rows survive before permanent removal. **Unset means nothing is ever purged.** |
| `AGENT_FACTORY_MEMORY_RETENTION_INTERVAL_SECONDS` | `3600.0` | How often the retention worker checks |
| `AGENT_FACTORY_MEMORY_QUIET` | off | Silence the package's own log handler |
| `DIGIT_CONSOLE_TENANT_ID` | unset | **Console-side.** The tenant the console sends with each turn. Unset means the console sends no tenant and memory stays off in the UI. |

`AGENT_FACTORY_MEMORY_EMBED_DIM` and `AGENT_FACTORY_MEMORY_PGVECTOR` are read **at import time** and decide the column type the code expects. If two processes disagree about them while sharing one database, writes fail — the write path retries without the embedding so content still persists, and logs a warning naming both values.

## Turning it on in the console

Memory needs a tenant, and the console has no tenant claim to read, so it takes one from server-side configuration:

```bash
DIGIT_CONSOLE_TENANT_ID=t-demo    # in the console's environment
```

With it set, the console includes `tenant_id` in the `user` object on every turn and memory behaves in the browser exactly as it does over curl. With it unset, the console sends no tenant, memory stays off, and nothing else changes — the fail-closed posture is preserved either way.

The console also proxies the memory endpoints under `/api/harness/memory/...`, forwarding the caller's `x-user-id` and `x-tenant-id`. There is no memory UI yet; the routes exist so one can be built.

**When real authentication arrives**, replace the config read with the signed-in user's tenant claim — it is a one-line change at a single site in `agent-console/lib/harness.ts`.

## The memory API

Six endpoints let a person see and control what is stored about them. All of them act on **one scope** — one agent, one user, one tenant — and that scope comes from the caller's identity, not from what they ask for.

**Identity.** The caller is resolved from headers: `x-user-id` (or `x-user-email` / `x-username`) and `x-tenant-id`. A `user_id` query parameter cannot override the header — if a header is present it wins, and when authentication is required a mismatched parameter is rejected with 403. Missing user or missing tenant is a 400. This is the same precedence the rest of the harness uses for caller-scoped endpoints.

| Method | Path | Does |
|---|---|---|
| `GET` | `/api/v1/memory` | List this scope's live memories |
| `GET` | `/api/v1/memory/status` | Summary: whether memory is on, how many entries, oldest and newest, whether the user has opted out |
| `DELETE` | `/api/v1/memory/{entry_id}` | Soft-delete one memory. 404 if it is not in the caller's scope |
| `POST` | `/api/v1/memory/forget` | Soft-delete every memory in the scope; returns the count |
| `POST` | `/api/v1/memory/disable` | Turn memory off for this user on this agent |
| `POST` | `/api/v1/memory/enable` | Turn it back on |

```bash
# list your memories
curl -sS -H 'x-user-id: alice' -H 'x-tenant-id: acme' \
  'http://127.0.0.1:8081/api/v1/memory?profile_id=memory-demo'

# delete one
curl -sS -X DELETE -H 'x-user-id: alice' -H 'x-tenant-id: acme' \
  'http://127.0.0.1:8081/api/v1/memory/<entry_id>?profile_id=memory-demo'
# -> {"deleted": true, "audit_id": "..."}

# opt out entirely, then back in
curl -sS -X POST -H 'x-user-id: alice' -H 'x-tenant-id: acme' \
  'http://127.0.0.1:8081/api/v1/memory/disable?profile_id=memory-demo'
```

Every mutating call writes one row to `agent_memory_audit` recording the action, the scope, the actor and the source — and returns that row's id, so an action can be traced afterwards. Reads are not audited.

**The opt-out is checked at the start of every turn.** A user who disables memory gets normal replies with no recall and no writes, and one content-free log line explains why. Re-enabling takes effect on the next turn.

> **Not yet enforced:** `MemoryPolicy` declares `max_entries_per_scope`, but nothing acts on it. Growth is currently bounded by the recall budget rather than by a hard cap. If you need a quota, that is where to add it.

## Schema changes

The schema is managed by Alembic, not by `create_all`.

```bash
alembic upgrade head     # bring an environment to the current schema
alembic current          # what revision is this database at
alembic check            # does the database match the models
```

A new environment runs `upgrade head` and gets everything. A database that already has the tables adopts the baseline once with `alembic stamp head`, then uses `upgrade head` from then on. `create_all` remains only for local scratch databases and is documented as such.

Because the dev database is shared with another application, Alembic is deliberately scoped to harness-owned tables. The `studio_*` tables, the SDK's `agent_sessions`/`agent_messages`, and one hand-applied index on `agent_runs` are all excluded on purpose — see `docs/MIGRATIONS.md` in the harness repo.

## What to watch in the logs

All memory lines carry ids, counts and outcomes — **never memory content**.

| Line | Means |
|---|---|
| `agent_memory seam loaded build=…` | Which code this process loaded. Check it before believing anything else. |
| `memory sessions: harness session factory installed` | Sharing the app's database pool (correct in-app). |
| `fallback engine created (standalone mode)` | Running with its own engine — expected in scripts, **wrong in the server**. |
| `memory gate: top_sim=… tier=… action=…` | One per write: how similar the closest existing memory was, which tier decided, what happened. |
| `memory add id=… source=… superseded=…` | A memory was written; `superseded=True` means it replaced an older one. |
| `memory identity gate: disabled for turn` | The turn lacked a user or tenant, so memory did nothing. |
| `memory disabled by user preference` | The user has opted out on this agent; memory did nothing for the turn. |
| `memory outbox: processed=N failed=M` | The extraction worker drained a batch. |
| `memory retention: purged=N` | Old soft-deleted rows were permanently removed. |

The gate line is the one to keep. It is how the similarity thresholds were calibrated in the first place, and it is how you would retune them after changing embedding models.

## Data lifecycle and deletion

Deletion is two-stage, which is the standard pattern for this kind of data. A delete sets `discarded_at`: the memory stops being used immediately and stops appearing anywhere. It is permanently removed later by the retention worker, once a window is configured — until then nothing is hard-deleted.

Forgetting an entire user is one scoped operation across their memories. Contradictions are handled by superseding: the old row is retired and points at its replacement, so the history remains reconstructible for audit.

Growth is bounded in practice by the recall budget rather than the table: recall injects at most 20 entries or 8,000 characters per turn regardless of how many exist. The table itself grows slowly — one row per durable fact per user — and the designed answer to long-term growth is consolidation, which is not built yet.

## Troubleshooting

| Symptom | Likely cause | Check |
|---|---|---|
| Agent remembers nothing | Turn had no tenant | Look for `memory identity gate: disabled for turn` |
| Agent remembers nothing, no gate line either | Flag off for that profile | `semantic_memory_enabled` in the profile |
| Recall is odd or irrelevant | Embedder unavailable, so ranking fell back to recency | `embed failed (degrading to non-semantic path)` |
| Duplicates piling up | The gate is degrading, which is its safe direction | The `tier=` field on the gate lines |
| A correction didn't take effect | Similarity fell below the decision floor | The `top_sim=` value on that write |
| Writes fail with a column-type error | Two processes disagree on the pgvector env vars | The warning naming `USE_PGVECTOR` and `dim` |
| `got Future attached to a different loop` | A sync route handler bridging into async code | Handlers must be `async def` |
| Behaviour doesn't match the code | Stale process serving old code | The build marker in the log |

Nothing above should ever cause a failed turn. If memory *does* break a turn, that is a bug worth reporting with the run id — degrading quietly is the contract.
