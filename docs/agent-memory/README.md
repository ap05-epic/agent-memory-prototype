# Agent Memory

Persistent, per-user memory for DIGIT agents. An agent with memory enabled remembers durable facts about each specific user — preferences, corrections, working context — across threads and across restarts.

**Off by default.** Nothing changes for an agent until its profile enables it, and a test in the suite fails the build if any non-test profile does.

---

## The 60-second model

A memory is one short fact about one user, stored in the harness's existing Postgres and keyed by **(agent, user, tenant)**. Two things create memories, and one thing uses them:

- **The `save_memory` tool** — the agent calls it when the user states something durable.
- **Post-turn extraction** — a background worker reads the finished exchange and captures durable facts the user stated without asking.
- **Recall** — at the start of every turn, relevant memories are fetched, ranked, and passed to the model as a fenced block of *data* (never as instructions).

Every write passes one gate: exact duplicates are dropped for free, near-identical facts supersede the old one, and genuinely ambiguous cases are adjudicated by a small model. Contradictions never overwrite — the old row is retired with a pointer to its replacement, so the history stays auditable. Deletes are soft, and a retention job handles permanent removal on a configured schedule.

If memory can't do its job — the embedder is down, the database is unreachable, identity is incomplete — it degrades or switches itself off. **It never breaks a turn.**

## Where to look next

| If you want to… | Read |
|---|---|
| Understand how it works, with diagrams | [ARCHITECTURE.md](ARCHITECTURE.md) |
| Change or extend it without breaking things | [DEVELOPING.md](DEVELOPING.md) |
| Run it, configure it, or debug it | [OPERATIONS.md](OPERATIONS.md) |
| Know what a specific file or function does | [CODE_WALKTHROUGH.md](CODE_WALKTHROUGH.md) |

## What exists today

The feature is built and verified; it is not yet enabled for general use.

**Working and verified:** the tool and automatic extraction, semantic recall with relevance-and-recency ranking, supersede-on-contradiction, per-(agent, user, tenant) scoping, the fail-closed identity gate, schema managed by Alembic migrations, memory running on the harness's own database lifecycle, durable extraction that survives restarts, and recalled memory travelling in the model's data channel rather than its instructions.

**In progress:** the governed API layer (view, delete, forget, disable your own memories, with an audit trail and retention), and the console tenant plumbing that will re-enable memory in the UI.

**Deliberately not built:** consolidation of many small memories into a per-user summary. It is designed, the table is reserved, and it is the natural next step once the governance work lands.

## The five things worth knowing before you touch it

1. **Scope is three-part.** Every query filters on agent, user, *and* tenant. Dropping one silently mixes people's data — the most dangerous possible bug in this system.
2. **Memory is data, not instructions.** The recalled block is fenced and explicitly subordinate to what the user says now. Never move it into the instruction channel for convenience.
3. **Failure means "do nothing", not "guess".** Every degradation path falls back to writing an extra row or injecting nothing. That asymmetry is deliberate: a duplicate is noise, a wrong overwrite is damage.
4. **Nothing is destroyed at runtime.** Soft-delete and supersede chains *are* the audit trail.
5. **Thresholds are measured, not borrowed.** The similarity numbers in the write gate came from telemetry on real behaviour with the model we actually use. If you change the embedding model, recalibrate them — the current values will not transfer.
