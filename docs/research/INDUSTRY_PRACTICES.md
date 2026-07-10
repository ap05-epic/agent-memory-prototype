# Industry Practices — AI Memory Systems Survey

> The research pass requested at design review: how production AI systems handle memory **retention & deletion**, **vector storage & retrieval**, and **updates & consolidation** — and what we adopt from each. Sources: vendor documentation, engineering references, and source-level reads of four open-source systems (Letta, mem0, OpenClaw, Hermes Agent). Facts marked UNVERIFIED where only secondary sources exist.

---

## 1. Retention, deletion, and growth

**ChatGPT (OpenAI).** Two layers: explicit "Saved memories" (user-visible, editable) + implicit "reference chat history." Deletion is two-stage: immediately stops being used, hard-deleted from systems **within ~30 days** (even the safety/debug log of deleted memories is bounded at 30 days). Memory has a fixed capacity; when full, **new memories silently stop saving** — no auto-eviction (a documented user complaint). Deleting a chat does *not* delete memories derived from it. ([memory FAQ](https://help.openai.com/en/articles/8590148-memory-faq), [retention policies](https://help.openai.com/en/articles/8983778))

**Claude (Anthropic).** Memory is a synthesized summary refreshed within ~24h, user-editable; "Reset memory" is a one-call irreversible wipe; enterprise org-level retention policies apply to all memory data. ([docs](https://support.claude.com/en/articles/11817273))

**Gemini (Google).** Explicit "Saved info" + a periodically refreshed synthesized profile. Notable gotcha: a deleted memory *"might still be retained as long as the original conversation is saved."* Age-based auto-delete of activity: **default 18 months** (user-tunable 3/36/off) — the consumer precedent for a retention window. ([docs](https://support.google.com/gemini/answer/16598469))

**Letta.** No TTL anywhere — "persisted indefinitely." Bounded in-context blocks (20k–100k chars) force *curation* instead of eviction; passage deletion endpoints are **hard** deletes. (code: `letta/prompts/system_prompts/sleeptime_v2.py`, `services/passage_manager.py`)

**mem0.** Hard-deletes vectors but keeps an append-only history log **that retains deleted memory text** — the audit-vs-erasure anti-pattern to avoid. Expiration (`expiration_date`) is a *retrieval filter*, not deletion. One-call scoped `delete_all(user_id=…)` / `reset()`. (code: `mem0/memory/main.py`, `storage.py`)

**Zep.** The enterprise reference: user-scoped one-call cascade delete positioned explicitly as the right-to-be-forgotten mechanism; **soft-delete then periodic hard purge** (including RTBF executions); policy-driven retention schedules + legal hold in Zep Archive. ([deletion docs](https://help.getzep.com/deleting-data-from-the-graph), [Archive](https://blog.getzep.com/announcing-zep-archive-regulatory-compliance-and/))

**GDPR tension.** Regulators are explicit: suppressed-but-readable data fails Article 17 — soft-delete alone is not erasure. Accepted reconciliations: **two-stage delete** (hide now, purge on schedule), **crypto-shredding** (destroy a per-scope key; EDPB/ICO-accepted), or splitting personal data from an anonymized audit trail; legal hold is the sanctioned override. Vector wrinkle: soft-deleted embeddings can remain reconstructible in ANN indexes ("ghost vectors") — deletion must reach the index.

**Cross-cutting patterns → what we adopt:**
- Two tiers everywhere (small curated in-context layer + searchable archive) → our user-model doc + entries log.
- Caps are size budgets; when full, **curate, never silently evict** → consolidation, no auto-prune.
- Deletion is two-stage (immediate hide → scheduled purge) → `discarded_at` + a purge job proposal; one-call `forget_user` cascade (table stakes).
- Supersede-don't-overwrite (Zep bitemporal) → our `superseded_by` chain.
- TTL, if ever, = retrieval filter, not auto-delete.

---

## 2. Vector storage & retrieval (pgvector on Azure)

**Azure enablement.** Extension name is `vector`; must be allow-listed in the `azure.extensions` server parameter (portal or one CLI line, **no restart**), then `CREATE EXTENSION vector;` once per database. Current Azure ships pgvector **0.8.2** (PG 13–18). ([Azure how-to](https://learn.microsoft.com/en-us/azure/postgresql/extensions/how-to-use-pgvector))

**Index choice — the counterintuitive one.** pgvector's default is an **exact scan (100% recall)**; ANN indexes trade recall for speed and apply `WHERE` *after* the index scan — with heavy per-(agent,user) filtering, an HNSW index would *reduce* recall while buying nothing at thousands-of-rows-per-scope. **Letta ships no vector index at all** — b-trees on scope + exact `cosine_distance`. Growth trigger: only when a single query scans >50–100k rows, add HNSW (+ pgvector 0.8 iterative scans for filtered queries). ([pgvector README](https://github.com/pgvector/pgvector), Letta ORM)

**Model & dimensions.** `text-embedding-3-small` @ native **1536** dims: strong for short snippets, half the storage of 3072, and under the 2000-dim HNSW limit so an index stays a drop-in. OpenAI embeddings are normalized → cosine (`<=>`) is the standard operator (rankings identical to inner product on unit vectors).

**Write path.** Embed synchronously at write with a short timeout (hosted embedders: p50 ~100–300ms, p90 ~500ms); on failure **insert with `embedding NULL`** (text is the source of truth) and backfill later — Letta declares its embedding column nullable for exactly this.

**Retrieval.** Standard shape at our scale: filter by scope in SQL, over-fetch top ~50 by similarity, **blend in app**: `0.7·similarity + 0.3·exp(−age_days/30)`, plus a **minimum-similarity floor** so irrelevant memories aren't injected just because they're top-k (OpenClaw gates injection at min score 0.35). RRF/full-text hybrid is the documented later step if exact-keyword search is ever needed.

---

## 3. Updates (don't duplicate) & consolidation

**mem0 classic** (the paper pipeline): per new fact, retrieve top-10 similar memories, one LLM call decides **ADD / UPDATE / DELETE / NONE** ("same thing → keep the most informative"; "totally different → update, keep the same ID"; "contradicts → delete"). UPDATE mutates the row in place; audit lives in a side history table. Anti-hallucination: candidates are shown to the LLM as **integers 0..n**, mapped back and range-validated.

**mem0's 2026 pivot (the cautionary tale).** Upstream OSS **removed the per-write LLM decision**: the add path is now extract → hash-dedup → **ADD-only** with `linked_memory_ids` to related olds. Conflict resolution moved off the hot write path — cost, latency, and misfires. Lesson: gate the LLM decision hard, and **degrade to plain ADD on any failure**; an append-only table makes that safe because consolidation can clean up later.

**Zep/Graphiti — the enterprise supersede pattern.** Bitemporal edges (`valid_at`/`invalid_at`): a contradicting fact **closes the old fact's validity window and opens a new one** — never deletes, full history queryable. Two deterministic guards done in *code*, not by the LLM: exact-normalized-text fast path, and "an older fact never invalidates a newer one" (compare event times before superseding). ([paper](https://arxiv.org/html/2501.13956v1))

**Letta.** Exact-substring block edits (auditable diffs) + `rethink_memory` whole-block rewrites, driven by a background **sleep-time agent every ~5 turns**, bounded by block char limits and "not every observation warrants an edit."

**ChatGPT "dreaming" (2026).** Background consolidation replacing static saved memories: rewrites a running user profile from past conversations, including temporal revision ("planned trip" → "went in August"). Press-verified; internals opaque. Strong validation that **profile synthesis is where the industry is heading**.

**Thresholds in practice.** mem0: 0.95 cosine = same-entity fast path; hash equality = exact duplicate; decision context top-k 10. Neo4j's agent-memory guidance is tiered and domain-tuned — **finserv: auto-merge 0.98, review-band from 0.90** ("start conservative"). All thresholds are embedding-model-specific — calibrate, never port blindly.

**Consolidation triggers.** OpenClaw: nightly cron (03:00) three-phase promote-to-curated with multi-signal gates, originals kept as archive; Hermes: consolidate-on-overflow (the write fails with "merge/remove then retry" — agent-driven, zero background cost); Letta: every-5-turns sleep-time; Generative Agents: accumulated-importance threshold. Common ground: **consolidation is never on the write path**, originals are kept (only Hermes destroys them — the weakest audit story), and folded items get provenance links.

---

## 4. Practice → our design (summary table)

| Industry practice | Our adoption |
|---|---|
| Two-stage deletion (hide → scheduled purge) | `discarded_at` today + purge-job proposal (window = governance's call; ChatGPT ≤30d / Gemini 18mo as reference points) |
| One-call user cascade delete | `forget_user(profile_id, user_id)` script/function |
| Crypto-shredding for strict erasure | documented upgrade path |
| Supersede with temporal validity (Zep) | `superseded_by` chain + `observed_at` guard (older facts never supersede newer — enforced in code) |
| Tiered dedup gate before any LLM call | hash-equal → drop · ≥0.95 → same-fact fast path · 0.70–0.95 → LLM decision · below → ADD (conservative per finserv guidance; calibrate on our embedder) |
| Integer-indexed candidates to the decision LLM | adopted verbatim (mem0 + Graphiti convergent) |
| Degrade to ADD on decision failure (mem0's pivot lesson) | adopted — decision only on the background path, never blocks a write |
| Exact scan, no ANN index at filtered small scale (Letta) | b-tree scope filter + exact cosine; HNSW documented as growth step |
| Nullable embedding + backfill | adopted |
| Blend relevance + recency, with a min-similarity floor | 0.7/0.3 blend, floor ≈0.35, cap ~20 |
| Consolidation off the write path, originals kept with provenance | threshold-triggered background fold into the user-model doc; folded rows soft-discarded with `superseded_by` → the summary |
| Profile synthesis as the destination (ChatGPT dreaming, Claude, Gemini) | the reserved `agent_memory_user_models` table is exactly this |

---

## 5. Post-implementation note — what the build confirmed

The survey's predictions held up under live verification, one of them the hard way:

- **"Thresholds are embedding-model-specific — never port a number without calibration"** was proven *twice*: both a literature-style similarity band (0.70–0.95) and a conservatively lowered floor (0.50) failed to catch a genuine changed-preference contradiction, which **measured cosine 0.309** on `text-embedding-3-large` @ 1536 dims. The shipped design therefore adjudicates anything above a **measured 0.30 floor** with the decision model on decider-enabled paths, and emits one content-free telemetry line per write (`memory gate: top_sim=… tier=… action=…`) so all future tuning is data-driven. Short paraphrased facts score far lower than entity-dedup literature suggests.
- **The no-ANN-index recommendation** (exact scan within a heavily filtered scope; Letta's production posture) shipped as designed and performs in single-digit milliseconds at prototype scale.
- **The supersede pattern** (Zep-style invalidate-don't-delete) is live: contradictions produce a `superseded_by` chain, verified end to end on the real backend.
- **mem0's hot-path caution** shaped the failure semantics: every decision failure degrades to a plain ADD, which live operation exercised and confirmed harmless.
- **Two-stage deletion** is implemented at stage one (soft-delete + one-call per-user cascade); the scheduled hard-purge window remains, as this survey framed it, a governance decision.
