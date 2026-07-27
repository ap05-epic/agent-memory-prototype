# Agent Memory — Architecture Reference

**The definitive description of the system as it stands today**, on branch `feature/agentmemory-v3`. Diagrams render natively in GitHub and GitLab. If you read one document about this feature, read this one.

- Audience: anyone on the DIGIT AI Engineering team.
- Companion docs in this folder: [README.md](README.md) (orientation) · [DEVELOPING.md](DEVELOPING.md) (how to work on it) · [OPERATIONS.md](OPERATIONS.md) (running and debugging) · [CODE_WALKTHROUGH.md](CODE_WALKTHROUGH.md) (file-by-file detail).

---

## 1. What this is, in one paragraph

DIGIT agents have session memory: a transcript that lives for one thread and dies with it. This feature adds **agent-level persistent memory** — durable facts about a specific user (preferences, corrections, working context) that survive new threads and backend restarts, scoped per agent × user × tenant, stored in the Azure Postgres the harness already runs, and **off by default** behind a single profile flag. The goal is compounding value: the more a person uses an agent, the better that agent fits them, with no effort from the user.

## 2. System context

Memory is a package **inside** the harness runtime — not a service, not a sidecar. It shares the app's database connection pool, its model-call conventions, and its lifecycle.

```mermaid
flowchart LR
    subgraph clients["Callers"]
        console["Agent Console"]
        api["API clients"]
    end

    subgraph harness["DIGIT Harness — FastAPI app"]
        turnsvc["TurnService<br/>identity validated here"]
        runner["SDK Runner<br/>stream_turn"]
        registry["ToolRegistry<br/>save_memory registered"]
        worker["MemoryExtractionWorker<br/>background task"]
    end

    subgraph mem["agent_factory.memory"]
        recall["recall.py<br/>fetch + rank"]
        store["store.py<br/>write path + gate"]
        semantic["semantic.py<br/>pure logic, no I/O"]
        extraction["extraction.py<br/>post-turn capture"]
        outbox["outbox.py<br/>durable queue"]
        seam["_digit.py<br/>the seam"]
    end

    subgraph infra["Existing infrastructure"]
        pg[("Azure Postgres<br/>+ pgvector")]
        aoai["Azure OpenAI<br/>embeddings + mini model"]
    end

    clients --> turnsvc --> runner
    registry -.provides save_memory.-> runner
    runner --> recall
    runner --> outbox
    worker --> outbox
    outbox --> extraction
    recall --> store
    extraction --> store
    store --> semantic
    store --> seam
    seam --> pg
    store -. embeddings .-> aoai
    extraction -. decisions .-> aoai
```

**The seam (`_digit.py`) is the only file that touches harness symbols.** Everything else in the package is portable and unit-testable off-harness. At app construction the harness installs its own `Database.session_factory` into the seam, so in-app memory creates **no database engine of its own**; a fallback engine exists solely for standalone scripts, and logs which mode it is in.

## 3. Anatomy of one turn

```mermaid
sequenceDiagram
    autonumber
    participant U as User
    participant R as SDK Runner
    participant M as Memory
    participant DB as Postgres
    participant LLM as Model

    U->>R: turn request (profile, user, tenant, input)
    R->>R: identity gate — user_id AND tenant_id present?
    alt identity incomplete or flag off
        R-->>U: normal turn, memory silently disabled (one log line)
    else memory active
        R->>M: build_memory_block(profile, user, tenant, query)
        M->>LLM: embed the incoming message
        M->>DB: fetch candidates in scope, rank
        M-->>R: fenced <user_memory> block + count
        R-->>U: run.status "🧠 Recalled N memories"
        R->>LLM: input list = [memory item, user message]
        Note over R,LLM: memory rides the DATA channel<br/>instructions stay clean
        opt user states something durable
            LLM->>M: save_memory tool call
            M->>M: write gate (section 4)
            M->>DB: insert row, or supersede an old one
        end
        LLM-->>R: response
        R->>DB: enqueue extraction job (outbox row)
        R-->>U: run.completed
    end
```

Two properties fall out of this shape:

- **Recall can never break a turn.** Any failure returns no block and the turn proceeds; the user simply gets an agent with no memory that turn.
- **The injected memory item is never persisted into conversation history.** A session wrapper (`session_filter.py`) drops it on the way to storage, so it cannot accumulate in `agent_messages` turn after turn. Recall re-injects fresh every turn, which is the intended behaviour.

## 4. The write gate

Every write — tool save or background extraction — passes through the same gate. It runs in two halves: **free checks first**, then a similarity decision that only involves a model when the case is genuinely ambiguous.

**Half one: the free checks.**

```mermaid
flowchart TD
    A[new fact] --> B[clean it]
    B --> C{sensitive pattern?}
    C -->|yes| X[reject]
    C -->|no| D{exact duplicate?}
    D -->|yes| Y[drop]
    D -->|no| E[embed and compare]
```

Cleaning strips our own fence markers, collapses whitespace and caps the text at 500 characters. The sensitive-pattern check is a regex denylist for IBAN-shaped strings, card-shaped digit runs and password/secret/token patterns. The duplicate check is a normalised text comparison against the recent window. All three cost nothing.

**Half two: the similarity decision.**

```mermaid
flowchart TD
    E[embed and compare] --> F{"score >= 0.95 and new text richer?"}
    F -->|yes| SUP[supersede]
    F -->|no| G{"score >= 0.30 and decider available?"}
    G -->|no| ADD[add]
    G -->|yes| H[ask the small model]
    H --> I{verdict}
    I -->|ADD| ADD
    I -->|NONE| DROP[drop]
    I -->|SUPERSEDE n| J{is the new fact newer?}
    J -->|yes| SUP
    J -->|no| ADD
```

The model sees the top five candidates as an integer-indexed list and returns an index, which is range-validated — it cannot invent a target. The `observed_at` guard is enforced in code, not by the model: an older fact never replaces a newer one.

**Anything that goes wrong lands on `add`.** No embedding, a malformed verdict, a model timeout, an exception mid-gate — all of them fall through to a plain add rather than risking a wrong supersede. An extra row on an append-only table is noise; a wrongly retired fact is damage.

**The 0.30 floor is measured, not borrowed.** A real changed-preference contradiction ("exactly three bullet points" → "five bullets now, not three") measured **cosine 0.309** on `text-embedding-3-large` at 1536 dimensions — far below the 0.70 band the literature suggests, which would have silently missed it. Every write emits one content-free telemetry line (`memory gate: top_sim=… tier=… action=…`) so future tuning stays data-driven.

## 5. Retrieval and ranking

Candidates are scored `0.7 × similarity + 0.3 × exp(−age_days / 30)`, with a minimum-similarity floor of 0.35 so weak matches are never injected just for being top-k, plus a small recency floor of always-included recent items. Up to 20 entries / 8,000 characters are injected per turn.

Retrieval degrades down three rungs rather than failing. It takes the highest rung available and never raises:

```mermaid
flowchart TD
    A[recall] --> B{query embedded?}
    B -->|yes, pgvector on| R1[rung 1: rank in SQL]
    B -->|yes, no pgvector| R2[rung 2: rank in Python]
    B -->|no| R3[rung 3: recency only]
    R1 --> F{"above the 0.35 floor?"}
    R2 --> F
    F -->|yes| OUT[inject block]
    F -->|no| R3
    R3 --> OUT
```

Rung 1 lets Postgres order by cosine distance. Rung 2 fetches the recent window and ranks in Python — same maths, no extension needed. Rung 3 ignores meaning entirely and returns the newest entries, which is what happens when the embedder is unavailable. The floor exists so that a weak match is never injected merely for being the best of a bad set; if nothing clears it, recall falls back to recency rather than injecting noise.

No ANN index exists by design: within an already scope-filtered set, an exact cosine scan is both faster and 100% recall at this size. HNSW is documented as the growth step once a single scope exceeds tens of thousands of rows.

## 6. Data model

Four tables, all keyed by the same three scope columns: `profile_id`, `user_id`, `tenant_id`.

```mermaid
erDiagram
    agent_memory_entries ||--o{ agent_memory_entries : replaces
    agent_memory_entries ||--o{ agent_memory_audit : records

    agent_memory_entries {
        string id PK
        text content
        vector embedding
        string superseded_by FK
        timestamp observed_at
        timestamp created_at
        timestamp discarded_at
    }
    agent_memory_outbox {
        string id PK
        text user_text
        text assistant_text
        string status
        int attempts
        timestamp next_attempt_at
    }
    agent_memory_audit {
        string id PK
        string action
        string entry_id
        string actor
        timestamp created_at
    }
    agent_memory_user_models {
        string id PK
        text content
        boolean memory_disabled
        int version
    }
```

| Table | Holds | Notes |
|---|---|---|
| `agent_memory_entries` | The memories themselves | Append-only. Scope columns plus `category` (preference / fact / context / note) and `source` (tool / extraction). |
| `agent_memory_outbox` | Pending extraction jobs | One row per eligible turn until a worker drains it. `next_attempt_at` doubles as the claim lease. |
| `agent_memory_audit` | Every mutation | Action, scope, actor, source, and counts — **never memory text**. |
| `agent_memory_user_models` | Per-user settings today, synthesised profiles tomorrow | Currently only the `memory_disabled` opt-out flag is used; `content` is reserved for consolidation. |

Three column choices carry weight:

- **`observed_at` vs `created_at` are deliberately different.** One is when the fact became true, the other when we learned it. The supersede guard compares event time, so an older fact can never overwrite a newer one.
- **`superseded_by` points at the replacement.** Combined with `discarded_at` (the soft delete), the chain *is* the audit trail — nothing is hard-deleted at runtime, so you can always reconstruct what the agent knew and when.
- **`embedding` is nullable.** A write with no embedding still succeeds; retrieval simply drops to a lower rung for that row, and a backfill can fill it in later.

## 7. Durable extraction: the outbox

Background extraction used to be fire-and-forget: if the process died between a turn ending and extraction finishing, that memory was lost — and one newer harness completion path skipped it entirely. Now every eligible turn **durably enqueues** a job, and a worker drains it.

A queued job moves through four states:

```mermaid
stateDiagram-v2
    [*] --> pending: turn ends
    pending --> leased: worker claims it
    leased --> [*]: success
    leased --> pending: retry or lease expiry
    pending --> failed: 5 attempts
    failed --> [*]: manual review
```

| Transition | What actually happens |
|---|---|
| `→ pending` | The turn writes one row with the exchange text and the scope. |
| `pending → leased` | The worker increments `attempts` and pushes `next_attempt_at` five minutes out, then commits. That future timestamp *is* the lease. |
| `leased → [*]` | Extraction succeeded; the row is deleted. |
| `leased → pending` | Either the extraction failed (back off `min(60·2ⁿ, 3600)` seconds) or the worker died before finishing — in which case the lease simply expires and the row becomes claimable again. Nothing gets stuck. |
| `pending → failed` | After five attempts the row stops being retried and is kept with its `last_error` for inspection. |

The worker copies the harness's own `ProfileHealthMonitor` pattern: a service object started in the app lifespan and stopped **before** the databases close. Each cycle is three separate short transactions:

```mermaid
flowchart LR
    A[1. claim] --> B[2. extract] --> C[3. finalize]
```

1. **Claim** — select due rows (`FOR UPDATE SKIP LOCKED` on Postgres), lease them, **commit**. Milliseconds.
2. **Extract** — run the model with **no database session held**. Seconds to a minute.
3. **Finalize** — delete on success, or record the error and back off. Milliseconds.

That ordering is the whole point. Our first version held the claim transaction open across the model call, which parks a pooled connection and a row lock for a minute at a time; the split means a slow extraction can never do that. Delivery is **at-least-once**, and the write gate's dedup makes replays harmless.

**Verified end to end:** a turn was enqueued with the worker disabled, the server was killed, and on restart the worker drained the backlog (`memory outbox: processed=4 failed=0`, outbox empty) and the next turn recalled the new memory.

## 8. Identity and scoping

```mermaid
flowchart TD
    A[turn arrives] --> B{memory flag on?}
    B -->|no| OFF[no memory code runs]
    B -->|yes| C{user id present?}
    C -->|no| GATE["disabled for this turn"]
    C -->|yes| D{tenant id present?}
    D -->|no| GATE
    D -->|yes| E{user opted out?}
    E -->|yes| GATE
    E -->|no| ON["recall, tool and extraction active"]
```

Fail-closed by construction: the same predicate gates recall, extraction, and the tool (the tool is gated implicitly — it is enabled through the same run-context flag, so no tool-side change was needed). Harness paths no longer fall back to a `"default"` tenant sentinel.

> **Current consequence, by design:** the console does not send a tenant yet, so console-driven memory is inert on this branch until the tenant plumbing lands with the governed-API workstream. That satisfies the review's condition that memory stay demo-only until governance ships.

## 9. Schema deployment

Schema is versioned with Alembic — introduced to the harness as part of this work, with the memory tables as its first revision.

```mermaid
flowchart LR
    M[edit models.py] --> A[generate revision] --> R[review the DDL] --> U[upgrade head]
```

A change to the models generates a revision file; you read that file (autogenerate gets vector columns and server defaults wrong often enough that review is not optional); then every environment runs `alembic upgrade head`. A database that already has the tables adopts the chain once with `alembic stamp head`, and `alembic check` afterwards proves the models and the database agree.

The chain so far:

| Revision | Adds |
|---|---|
| `5258f2433fcb` | Baseline: the entire harness schema, memory tables included, with a `CREATE EXTENSION IF NOT EXISTS vector` guard |
| `6f4f8e6f7f55` | The outbox table |
| `4f743f1f0d2d` | The audit table and the per-user opt-out flag |

- `create_all` survives only as local/test bootstrap and is documented as such.
- Because the dev database is **shared with another application**, Alembic is scoped to harness-owned tables: the `studio_*` tables and the SDK-managed `agent_sessions` / `agent_messages` are deliberately unmanaged, as is one hand-applied index on `agent_runs` that exists in the database with no owner in code (flagged for the team to decide on).

## 10. Configuration

| Setting | Where | Default | Purpose |
|---|---|---|---|
| `memory.semantic_memory_enabled` | agent profile YAML | `false` | The master switch, per agent |
| `AGENT_FACTORY_MEMORY_PGVECTOR` | env | off | Use `vector(N)` column instead of packed bytes |
| `AGENT_FACTORY_MEMORY_EMBED_MODEL` | env | `text-embedding-3-large` | Embedding deployment |
| `AGENT_FACTORY_MEMORY_EMBED_DIM` | env | `1536` | Dimensions requested from the embedder |
| `AGENT_FACTORY_MEMORY_MODEL` | env | harness default | Model for gate decisions and extraction |
| `AGENT_FACTORY_MEMORY_OUTBOX_ENABLED` | env | `true` | Run the extraction worker |
| `AGENT_FACTORY_MEMORY_OUTBOX_INTERVAL_SECONDS` | env | `3.0` | Worker poll interval |
| `AGENT_FACTORY_MEMORY_QUIET` | env | off | Silence the package's own log handler |

## 11. Failure modes

| If this fails | The system does | User-visible effect |
|---|---|---|
| Embedder unavailable | Recall drops to recency; writes store `embedding NULL` and can be backfilled | Slightly less relevant recall |
| Decision model unavailable | Gate degrades to plain ADD | A possible duplicate row, never a lost fact |
| Database unavailable at recall | Returns no block | Agent behaves as if it has no memory |
| Database unavailable at enqueue | Falls back to the old in-process extraction | Behaviour no worse than before the outbox |
| Worker dies mid-job | Lease expires, row is reclaimed | Extraction happens a few minutes later |
| Identity incomplete | Memory disabled for that turn | No memory, one log line, turn unaffected |

## 12. Security and governance posture

- **Off by default**, enforced by a test that fails the build if any non-test profile enables memory.
- **Fail-closed identity**: no validated user *and* tenant, no memory.
- **Denylist at write time**: IBAN-shaped strings, card-shaped digit runs, and password/secret/API-key/token patterns are blocked by pattern, independent of what the extraction prompt is told.
- **Content-free logging**: ids, counts, outcomes — never memory text.
- **Injection-aware**: the recalled block is fenced and explicitly framed as *stored data, not instructions — if it conflicts with the user, the user wins*; any attempt to forge that fence inside stored content is stripped at write time; and as of the injection-boundary change, memory no longer travels in the instruction channel at all.
- **Deletable**: soft delete per entry, one-call `forget_user()` cascade per scope, supersede chains preserved as audit. Retention windows and a scheduled hard purge are the next workstream.

## 13. Status

| Workstream | State |
|---|---|
| Core memory (recall, tool, extraction) | Built, demoed, live-verified |
| Semantic retrieval + supersede (pgvector) | Built, live-verified, thresholds calibrated |
| Re-base onto current dev | Done — branch `feature/agentmemory-v3` |
| Alembic migrations, verified drift-free | Done |
| Harness-managed DB lifecycle | Done — no private engine in-app |
| Identity and tenant hardening | Done — fail-closed |
| Test coverage incl. off-by-default guard | Done |
| **Merge candidate 1 (foundation)** | **In review** — branch `feature/agentmemory-mc1` |
| Recall out of the instruction channel | Done |
| Durable extraction (outbox + worker) | Done |
| Governed APIs, audit events, retention | Built; API layer being fixed (see below) |
| Console tenant plumbing | Next — this is what re-enables memory in the console |
| Consolidation into per-user profiles | Designed, deferred |

**Branch topology.** `feature/agentmemory-mc1` is a frozen snapshot of the foundation work, open as a merge request; nothing new lands on it. All candidate-2 work continues on `feature/agentmemory-v3`, so pushes there cannot disturb the review.

**Known open item.** The governance endpoints are implemented and their migration is applied, but the routes were written as synchronous handlers bridging into async store calls, which creates a second event loop and breaks connections borrowed from the app's pool (`got Future attached to a different loop`). The fix is to declare the routes `async def` and await the store functions directly. That work is uncommitted on `feature/agentmemory-v3` and is not in any merge request.

## 14. Glossary

| Term | Meaning |
|---|---|
| **Scope** | The `(profile_id, user_id, tenant_id)` triple every row is keyed by |
| **The seam** | `_digit.py`, the only module that touches harness symbols |
| **The gate** | The tiered checks every write passes before storage |
| **Supersede** | Retire a row and link it to its replacement, instead of overwriting |
| **The outbox** | The durable queue that makes post-turn extraction crash-safe |
| **Recall block** | The fenced `<user_memory>` item injected into the model input |
| **Lease** | The future `next_attempt_at` set at claim time so a dead worker's rows return |
