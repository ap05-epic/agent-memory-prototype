# Memory v2 — Semantic Retrieval, Smart Writes, Compaction

> Working architecture doc. Items marked ⏳R5 are pinned by `docs/recon/ROUND_5.md`; threshold defaults get finalized from the industry-research pass (`docs/research/INDUSTRY_PRACTICES.md`). v1 is live and proven; **v2 is strictly additive** — every capability degrades to v1 behavior, the flag semantics don't change, and no existing rows are touched.

## 0. Design principles

1. **v1 is the floor.** Recall can never break a turn; if any v2 dependency (embedder, extension) is missing or down, behavior degrades to the proven v1 path — automatically, per call.
2. **Additive schema only.** New columns are nullable; applied with `ALTER TABLE ADD COLUMN IF NOT EXISTS` (a small idempotent script — no reset, no data loss, live rows keep working).
3. **Same seam discipline.** The embedder joins `_digit.py` as one function; everything else stays in the memory package.

## 1. Pillar 1 — Semantic retrieval

**Why:** v1 recalls the newest ~20 entries. Once a user has many memories, "newest" ≠ "relevant." Retrieval should rank by *meaning against the current message*, with recency still respected.

**Schema (additive):** `agent_memory_entries.embedding` — `VECTOR(dim)` when pgvector is available, else `BYTEA` (packed float32) — nullable. ⏳R5: dim + availability.

**Write path:** on every `add_entry`, embed the content (one embedder call). Failure ⇒ store with `embedding = NULL` and continue — **a write never blocks on the embedder**. (Optional backfill script embeds NULL rows later.)

**Read path (recall):** embed the incoming user message, then blend:
- **Relevant:** top-k (k≈12) live entries by cosine similarity within (profile, user, tenant);
- **Recent:** the newest n (n≈6) regardless of similarity — recency floor;
- union → dedup → cap ~20 → render the same `<user_memory>` block (chronological order for readability). Same char budget, same framing, same indicator (the 🧠 chip now reflects the blended count).

**Three-rung degradation (the key design move):**
| Rung | Mechanism | Needs |
|---|---|---|
| 1 | similarity in SQL: `ORDER BY embedding <=> :qvec LIMIT k` | pgvector extension |
| 2 | **Python-side cosine** over the scope's live rows (small per-(agent,user) sets make this cheap) | embedder only |
| 3 | v1 recency (`ORDER BY created_at DESC LIMIT 20`) | nothing |

Rung 2 means **semantic retrieval ships even if the extension is blocked** — pgvector then becomes a scale optimization, not a dependency. Index: at our filtered, small-per-scope volumes, likely none needed initially; HNSW + `vector_cosine_ops` documented as the growth step (final call from research ⏳).

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

**Retention (proposal for governance, not auto-baked):** discarded/superseded rows older than a policy window get archived (cold table) or purged per compliance direction — presented as options with industry precedent from the research pass; decision belongs to governance/Karan. Metrics query shipped (`count live / discarded / superseded per scope`) so the growth conversation is data-driven.

## 4. New seams & config

- `_digit.embed(texts: list[str]) -> list[list[float]] | None` — Azure OpenAI embeddings using the platform's own env config; `None` on any failure. ⏳R5: deployment name + dim → `AGENT_FACTORY_MEMORY_EMBED_MODEL` / `..._EMBED_DIM` env (defaulted from recon findings).
- Decision model for smart writes: `AGENT_FACTORY_MEMORY_MODEL` (already supported) — pin to the mini model.
- `scripts/upgrade_v2_columns.py` — idempotent `ALTER TABLE ADD COLUMN IF NOT EXISTS` for `embedding` + `superseded_by` (+ optional `CREATE EXTENSION vector` only if recon says allow-listed and we're told to).
- `scripts/verify_phase_c.py` — the v2 gate: embed roundtrip (SKIP cleanly if no embedder) · deterministic similarity retrieval (seeded fake embeddings → nearest-neighbor correctness) · supersede flow (add A, add A′ → old row discarded + linked) · consolidation trigger (threshold → doc written, entries folded, injection uses doc) · degradation (no embedder ⇒ rung-3 recency still passes).

## 5. Governance notes (delta over v1)

- **Embedding calls send memory content to the same Azure OpenAI boundary the chat itself already uses** — no new data boundary; worth stating explicitly.
- Supersede chains *improve* auditability (fact evolution is inspectable); permanent-deletion requests now have a precise shape: purge a scope's rows including superseded chains — the policy question is *when*, which the retention proposal covers.
- Prompt-injection posture unchanged (same write funnel, caps, framing); the decision model only ever sees memory content + candidate fact, and its output is constrained to an enum + id.

## 6. What this does NOT change

The flag, the tool, the injection block format, the indicator, the never-break-a-turn property, the no-content-logging rule, v1's tables and rows, and the working demo — all untouched. v2 lands on a separate branch as additive columns + package changes + one seam function.

## 7. Build order (each step independently shippable)

1. `embed()` seam + embedding column + write-path embedding (silent, additive).
2. Blended recall (rungs, with automatic degradation) — the visible payoff.
3. Supersede pipeline on the extraction path (then the tool path).
4. Consolidation into the user-model doc + metrics query.
5. Retention proposal doc (with industry evidence) → governance.
