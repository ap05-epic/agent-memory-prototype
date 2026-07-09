# Memory v2 — Semantic Retrieval, Smart Writes, Compaction

> Working architecture doc. v1 is live and proven; **v2 is strictly additive** — every capability degrades to v1 behavior, the flag semantics don't change, and no existing rows are touched.
>
> **Recon round 5 resolved the environment facts:** pgvector **0.8.0 is already installed** in the Azure PG (15.16) with app-user CREATE privilege — rung 1 available immediately, no platform ask. Working embedding deployments: `text-embedding-3-large` (3072) and `text-embedding-ada-002` (1536); `3-small` is **not deployed** — so the chosen config is **3-large with `dimensions=1536`** (top-tier model, server-side Matryoshka truncation to an index-ready size; ada-002@1536 is the zero-change fallback config, noting a model switch requires re-embedding via the backfill script). The pgvector *Python* package needs a `pip install` on the pod (rung 2 covers refusal). The harness's chat compaction is SDK-delegated (`OpenAIResponsesCompactionSession`, disabled for tool-capable profiles) with no reusable summarizer — consolidation uses our own `llm_complete`, as designed.

## 0. Design principles

1. **v1 is the floor.** Recall can never break a turn; if any v2 dependency (embedder, extension) is missing or down, behavior degrades to the proven v1 path — automatically, per call.
2. **Additive schema only.** New columns are nullable; applied with `ALTER TABLE ADD COLUMN IF NOT EXISTS` (a small idempotent script — no reset, no data loss, live rows keep working).
3. **Same seam discipline.** The embedder joins `_digit.py` as one function; everything else stays in the memory package.

## 1. Pillar 1 — Semantic retrieval

**Why:** v1 recalls the newest ~20 entries. Once a user has many memories, "newest" ≠ "relevant." Retrieval should rank by *meaning against the current message*, with recency still respected.

**Schema (additive):** `agent_memory_entries.embedding` — `vector(1536)` when pgvector is available (it is — recon-confirmed installed), else a packed-float32 `BYTEA` fallback (Letta's exact dialect-conditional pattern: the `pgvector.sqlalchemy.Vector` import happens only in that branch) — nullable by design. Dimension 1536 via `text-embedding-3-large` + the `dimensions` param (server-side truncation), deliberately under pgvector's 2000-dim HNSW limit so an index stays a pure drop-in later.

**Write path:** on every `add_entry`, embed the content — one call, ~5s timeout (measured p50 ~100–300ms, p90 ~500ms for hosted embedders). Failure ⇒ store with `embedding = NULL` and continue — **a write never blocks on the embedder**; a backfill script embeds `WHERE embedding IS NULL` rows in batches later.

**Read path (recall):** embed the incoming user message, over-fetch the scope's top ~50 live entries by cosine similarity, then **blend in app**: `score = 0.7·similarity + 0.3·exp(−age_days/30)`, with a **minimum-similarity floor (~0.35)** so weak matches aren't injected just for being top-k (OpenClaw gates injection the same way; a recency floor of the newest few entries stays exempt) → take top ~20 → render the same `<user_memory>` block (chronological for readability). Same char budget, framing, and 🧠 indicator. (App-side blending is the industry-standard shape; SQL-side blended scoring is the documented optimization if over-fetch ever gets expensive.)

**Three-rung degradation (the key design move):**
| Rung | Mechanism | Needs |
|---|---|---|
| 1 | similarity in SQL: `ORDER BY embedding <=> :qvec LIMIT 50` (exact scan within the b-tree-filtered scope) | pgvector extension |
| 2 | **Python-side cosine** over the scope's live rows (same blend; small per-(agent,user) sets make this cheap) | embedder only |
| 3 | v1 recency (`ORDER BY created_at DESC LIMIT 20`) | nothing |

Rung 2 means **semantic retrieval ships even if the extension is blocked** — pgvector then becomes a scale optimization, not a dependency. **No ANN index at our scale, deliberately**: with heavy per-(agent, user) filtering, an HNSW index *hurts* recall (pgvector applies WHERE after the index scan) — the b-tree on scope + exact distance sort is both correct and fast at thousands of rows per scope. This mirrors Letta in production (no vector index at all — b-trees + exact `cosine_distance`). Growth trigger documented: only when a single query must scan >50–100k rows, add `hnsw (embedding vector_cosine_ops)` + iterative scans (pgvector 0.8+).

## 2. Pillar 2 — Smart writes (update, don't duplicate)

**Why (Subomi's example):** preferences change over time; the store should not accumulate contradictions.

**Mechanism — supersede, never overwrite (audit-preserving; defaults finalized from the industry research):**
- New nullable columns: `superseded_by` (uuid of the replacing entry) and `observed_at` (event time — when the fact was true, resolved to an absolute date by the extractor; distinct from `created_at`, when we stored it).
- **Tiered gate on write** — the LLM is the last resort, not the first:
  1. normalized-text match → drop (free; v1 behavior);
  2. cosine ≥ **0.95** → same fact → drop unless the new text is strictly richer (mem0's fast path);
  3. **0.70–0.95** → the ambiguity band where contradictions live → one small-model call (`gpt-5.4-mini`): candidates shown as **integers 0..n** (never ids; outputs range-validated — mem0 and Graphiti converged on this independently), verdict ∈ ADD / SUPERSEDE(n) / NONE;
  4. below 0.70 → plain ADD, no LLM.
  Thresholds start conservative per financial-services dedup guidance (auto-merge ≥0.95+, review band from ~0.90) and get calibrated on our embedder — never ported blindly.
- **Apply is one transaction:** `INSERT` the new row, then `UPDATE old SET discarded_at = now(), superseded_by = <new id>`. The chain *is* the audit trail (Zep's bitemporal invalidate-don't-delete, structurally — mem0 needs a bolt-on history table for the same property).
- **Deterministic guard in code, not LLM judgment:** a fact whose `observed_at` is older than the incumbent's never supersedes it (Graphiti's rule). New information wins only through this check.
- **Degrade to ADD on any failure** (timeout, bad output, embedder down) — the cautionary tale here is upstream mem0 *removing* per-write LLM resolution in 2026 over cost/latency/misfires; on an append-only table a wrong ADD is harmless and consolidation cleans it up later.
- Contradiction with no replacement ("I no longer …") → soft-discard the old row with a tombstone successor; **hard delete is reserved for user-requested forget** under the retention policy.
- **The decision runs on BOTH write paths** (revised after live acceptance): the first build kept tier-3 off the tool path, assuming background extraction would catch contradictions — but extraction treats tool-saved facts as already-known, so the two safeguards starved each other and contradictions accumulated (observed live: "three bullets" and "five bullets" both staying active). User-directed saves are high-intent and low-frequency — exactly where an inline decision is appropriate; mem0's hot-path caution applies to high-volume auto-writes, and the background extraction path keeps it too. Related hardening: **at ≥0.95 similarity with a decider available, the decision still runs** — near-identical phrasing can be a contradiction ("three"→"five" embeds ~identically), and the prompt's "same meaning → NONE" rule handles true duplicates; the no-decider path stays conservative (≥0.95 → drop as duplicate).

## 3. Pillar 3 — Compaction & retention

**Consolidation (answers the storage-growth concern):** never on the write path — a **threshold-triggered background step** (checked from the existing post-turn task: fires when a scope's live entries exceed ~1.5–2× the injection budget; a nightly job is the documented production shape, per OpenClaw's 03:00 sweep and Letta's every-5-turns sleep-time agent). It synthesizes the oldest entries into the **`agent_memory_user_models` doc** — the reserved table finally activates as the compact "who is this user" profile (Hermes' USER.md / Letta's core block / **ChatGPT's 2026 "dreaming" profile** — this is where the industry converged). Folded entries are soft-discarded with `superseded_by` → the summary doc's id, so originals stay queryable as the archive tier (only Hermes destroys originals, and that's the weakest audit story of the systems surveyed). The doc rewrite uses the existing `version` column (optimistic locking). Injection becomes: **user-model doc + relevant/recent entries** — bounded context regardless of history length.

Recon round 5 answered the "check OpenAI tooling built-ins first" question: the harness's chat compaction just wraps the SDK's `OpenAIResponsesCompactionSession` (and is disabled for tool-capable profiles) — no reusable summarizer exists, so consolidation uses the same `llm_complete` path as extraction. Notably, session compaction being off for tool-capable agents makes memory-side consolidation *more* valuable, not redundant.

**Retention (proposal for governance, not auto-baked):** industry practice is **two-stage deletion** — hide immediately (our `discarded_at`), then **hard-purge on a schedule** (ChatGPT purges deleted memories within ~30 days and even its deleted-memory debug log is bounded at 30 days; Zep soft-deletes then periodically purges, including right-to-be-forgotten executions). Soft-delete alone is *not* erasure — regulators are explicit that suppressed-but-readable personal data fails GDPR Article 17. So the proposal: (a) keep `discarded_at` as stage one; (b) a scheduled purge job hard-deletes discarded/superseded rows older than a policy window (Gemini's 18-month user-tunable auto-delete is the consumer precedent; the window is governance's call); (c) a **one-call scope cascade** (`forget_user(profile_id, user_id)` — discard-all now, purge per schedule) since one-call user deletion is table stakes across Zep/mem0/Claude; (d) for the strictest reading, **crypto-shredding** (per-scope encryption key, destroy the key on erasure — EDPB/ICO-accepted) is documented as the enterprise-grade upgrade path. Metrics query shipped (`count live / discarded / superseded per scope`) so the growth conversation is data-driven.

## 4. New seams & config

- `_digit.embed(texts: list[str]) -> list[list[float]] | None` — Azure OpenAI embeddings using the platform's own env config; `None` on any failure (including a dimension mismatch — the column is never poisoned with wrong-size vectors). Env: `AGENT_FACTORY_MEMORY_EMBED_MODEL` (default `text-embedding-3-large`), `AGENT_FACTORY_MEMORY_EMBED_DIM` (default 1536; passed as the `dimensions` param for 3-series models), `AGENT_FACTORY_MEMORY_PGVECTOR` (1 in this environment).
- Decision model for smart writes: `AGENT_FACTORY_MEMORY_MODEL` (already supported) — pin to the mini model.
- `scripts/upgrade_v2_columns.py` — idempotent `ALTER TABLE ADD COLUMN IF NOT EXISTS` for `embedding` + `superseded_by` + `observed_at`. Extension enablement is a separate, deliberate step: on Azure Flexible Server, `vector` must first be **allow-listed in the `azure.extensions` server parameter** (portal or `az postgres flexible-server parameter set` — no restart needed), then `CREATE EXTENSION vector;` once per database (pgvector 0.8.2 on current Azure PG). If the app user lacks the privilege (⏳R5), that's a one-line platform-team/Karan request — and rung 2 keeps semantic retrieval working meanwhile.
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
