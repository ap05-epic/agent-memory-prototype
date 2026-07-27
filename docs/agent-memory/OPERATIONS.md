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
| `AGENT_FACTORY_MEMORY_QUIET` | off | Silence the package's own log handler |

`AGENT_FACTORY_MEMORY_EMBED_DIM` and `AGENT_FACTORY_MEMORY_PGVECTOR` are read **at import time** and decide the column type the code expects. If two processes disagree about them while sharing one database, writes fail — the write path retries without the embedding so content still persists, and logs a warning naming both values.

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
