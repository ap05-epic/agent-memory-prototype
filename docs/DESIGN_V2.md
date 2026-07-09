# Memory v2 — Semantic Retrieval, Smart Writes, Compaction

> Working architecture doc. Items marked ⏳R5 are pinned by `docs/recon/ROUND_5.md`; threshold defaults get finalized from the industry-research pass (`docs/research/INDUSTRY_PRACTICES.md`). v1 is live and proven; **v2 is strictly additive** — every capability degrades to v1 behavior, the flag semantics don't change, and no existing rows are touched.

## 0. Design principles

1. **v1 is the floor.** Recall can never break a turn; if any v2 dependency (embedder, extension) is missing or down, behavior degrades to the proven v1 path — automatically, per call.
2. **Additive schema only.** New columns are nullable; applied with `ALTER TABLE ADD COLUMN IF NOT EXISTS` (a small idempotent script — no reset, no data loss, live rows keep working).
3. **Same seam discipline.** The embedder joins `_digit.py` as one function; everything else stays in the memory package.

## 1. Pillar 1 — Semantic retrieval

**Why:** v1 recalls the newest ~20 entries. Once a user has many memories, "newest" ≠ "relevant." Retrieval should rank by *meaning against the current message*, with recency still respected.

**Schema (additive):** `agent_memory_entries.embedding` — `vector(1536)` when pgvector is available, else a packed-float32 `BYTEA` fallback (Letta's exact dialect-conditional pattern: the `pgvector.sqlalchemy.Vector` import happens only in the Postgres-with-extension branch) — nullable by design. Dimension 1536 = `text-embedding-3-small` native, deliberately under pgvector's 2000-dim HNSW limit so an index stays a pure drop-in later. ⏳R5 confirms which embedding deployment the resource actually serves.

**Write path:** on every `add_entry`, embed the content — one call, ~5s timeout (measured p50 ~100–300ms, p90 ~500ms for hosted embedders). Failure ⇒ store with `embedding = NULL` and continue — **a write never blocks on the embedder**; a backfill script embeds `WHERE embedding IS NULL` rows in batches later.

**Read path (recall):** embed the incoming user message, over-fetch the scope's top ~50 live entries by cosine similarity, then **blend in app**: `score = 0.7·similarity + 0.3·exp(−age_days/30)` → take top ~20 → render the same `<user_memory>` block (chronological for readability). Same char budget, framing, and 🧠 indicator. (App-side blending is the industry-standard shape; SQL-side blended scoring is the documented optimization if over-fetch ever gets expensive.)

**Three-rung degradation (the key design move):**
| Rung | Mechanism | Needs |
|---|---|---|
| 1 | similarity in SQL: `ORDER BY embedding <=> :qvec LIMIT 50` (exact scan within the b-tree-filtered scope) | pgvector extension |
| 2 | **Python-side cosine** over the scope's live rows (same blend; small per-(agent,user) sets make this cheap) | embedder only |
| 3 | v1 recency (`ORDER BY created_at DESC LIMIT 20`) | nothing |

Rung 2 means **semantic retrieval ships even if the extension is blocked** — pgvector then becomes a scale optimization, not a dependency. **No ANN index at our scale, deliberately**: with heavy per-(agent, user) filtering, an HNSW index *hurts* recall (pgvector applies WHERE after the index scan) — the b-tree on scope + exact distance sort is both correct and fast at thousands of rows per scope. This mirrors Letta in production (no vector index at all — b-trees + exact `cosine_distance`). Growth trigger documented: only when a single query must scan >50–100k rows, add `hnsw (embedding vector_cosine_ops)` + iterative scans (pgvector 0.8+).

## 2. Pillar 2 — Smart writes (update, don't duplicate)

**Why (Subomi's example):** preferences change over time; the store should not accumulate contradictions.

**Mechanism — supersede, never overwrite (audit-preserving):**
- New nullable column: `superseded_by` (uuid of the replacing entry).
- On write, fetch the most similar live entries (rung 1/2 similarity; exact-match dedup remains the rung-3 fallback):
  - similarity ≥ **T_dup** (≈0.95 ⏳research) → same fact → drop as duplicate (v1 behavior, now semantic);
  - **T_band** (≈0.75–0.95 ⏳research) → ambiguous → one small-model call (mem0's ADD/UPDATE/NONE decision, `gpt-5.4-mini`): on UPDATE → insert the new row, then `discarded_at = now(), superseded_by = <new id>` on the old one;
  - below the band → plain ADD.
- A "I no longer …" contradiction resolves as UPDATE-to-the-new-state or discard-with-nothing-added — **nothing is ever hard-deleted**, and the `superseded_by` chain is a readable audit trail of how a fact evolved (the Zep-style temporal-invalidation pattern, on our append-only table).
- Applies to both write paths; the extraction path gets it first (it's background, latency-free), the tool path uses the cheap threshold checks inline.

## 3. Pillar 3 — Compaction & retention

**Consolidation (answers the storage-growth concern):** when a scope's live-entry count exceeds **N_max** (≈60 ⏳research), a background step (piggybacked on the existing post-turn task) synthesizes the oldest entries into the **`agent_memory_user_models` doc** — the reserved table finally activates as the compact "who is this user" profile (Hermes' USER.md / Letta's core block, realized). Folded entries get `discarded_at` set; the doc rewrite uses the existing `version` column (optimistic locking). Injection becomes: **user-model doc + relevant/recent entries** — bounded context regardless of history length.

⏳R5: whether the harness's session-compaction machinery has a reusable summarizer (Subomi's "check OpenAI tooling built-ins first") — reuse it if so, else the same `llm_complete` path.

**Retention (proposal for governance, not auto-baked):** industry practice is **two-stage deletion** — hide immediately (our `discarded_at`), then **hard-purge on a schedule** (ChatGPT purges deleted memories within ~30 days and even its deleted-memory debug log is bounded at 30 days; Zep soft-deletes then periodically purges, including right-to-be-forgotten executions). Soft-delete alone is *not* erasure — regulators are explicit that suppressed-but-readable personal data fails GDPR Article 17. So the proposal: (a) keep `discarded_at` as stage one; (b) a scheduled purge job hard-deletes discarded/superseded rows older than a policy window (Gemini's 18-month user-tunable auto-delete is the consumer precedent; the window is governance's call); (c) a **one-call scope cascade** (`forget_user(profile_id, user_id)` — discard-all now, purge per schedule) since one-call user deletion is table stakes across Zep/mem0/Claude; (d) for the strictest reading, **crypto-shredding** (per-scope encryption key, destroy the key on erasure — EDPB/ICO-accepted) is documented as the enterprise-grade upgrade path. Metrics query shipped (`count live / discarded / superseded per scope`) so the growth conversation is data-driven.

## 4. New seams & config

- `_digit.embed(texts: list[str]) -> list[list[float]] | None` — Azure OpenAI embeddings using the platform's own env config; `None` on any failure. ⏳R5: deployment name + dim → `AGENT_FACTORY_MEMORY_EMBED_MODEL` / `..._EMBED_DIM` env (defaulted from recon findings).
- Decision model for smart writes: `AGENT_FACTORY_MEMORY_MODEL` (already supported) — pin to the mini model.
- `scripts/upgrade_v2_columns.py` — idempotent `ALTER TABLE ADD COLUMN IF NOT EXISTS` for `embedding` + `superseded_by`. Extension enablement is a separate, deliberate step: on Azure Flexible Server, `vector` must first be **allow-listed in the `azure.extensions` server parameter** (portal or `az postgres flexible-server parameter set` — no restart needed), then `CREATE EXTENSION vector;` once per database (pgvector 0.8.2 on current Azure PG). If the app user lacks the privilege (⏳R5), that's a one-line platform-team/Karan request — and rung 2 keeps semantic retrieval working meanwhile.
- `scripts/verify_phase_c.py` — the v2 gate: embed roundtrip (SKIP cleanly if no embedder) · deterministic similarity retrieval (seeded fake embeddings → nearest-neighbor correctness) · supersede flow (add A, add A′ → old row discarded + linked) · consolidation trigger (threshold → doc written, entries folded, injection uses doc) · degradation (no embedder ⇒ rung-3 recency still passes).

## 5. Governance notes (delta over v1)

- **Embedding calls send memory content to the same Azure OpenAI boundary the chat itself already uses** — no new data boundary; worth stating explicitly.
- Supersede chains *improve* auditability (fact evolution is inspectable) — and this is the same bitemporal pattern Zep uses in its enterprise temporal knowledge graph (facts get `invalid_at`, never overwritten), so it's defensible as industry-strongest practice, not an invention.
- Permanent deletion now has a precise, two-stage shape (see §3): discard immediately, purge on schedule, one-call scope cascade. Important nuance from the research: **deletion must reach the embeddings** — in our design embeddings live in the same row (a column, not a separate index/store), so a row purge removes the vector with it; if an ANN index is added later, index hygiene joins the purge job's duties.
- Prompt-injection posture unchanged (same write funnel, caps, framing); the decision model only ever sees memory content + candidate fact, and its output is constrained to an enum + id.

## 6. What this does NOT change

The flag, the tool, the injection block format, the indicator, the never-break-a-turn property, the no-content-logging rule, v1's tables and rows, and the working demo — all untouched. v2 lands on a separate branch as additive columns + package changes + one seam function.

## 7. Build order (each step independently shippable)

1. `embed()` seam + embedding column + write-path embedding (silent, additive).
2. Blended recall (rungs, with automatic degradation) — the visible payoff.
3. Supersede pipeline on the extraction path (then the tool path).
4. Consolidation into the user-model doc + metrics query.
5. Retention proposal doc (with industry evidence) → governance.
