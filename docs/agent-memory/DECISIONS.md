# Decision Record

Why this system is built the way it is. Each entry states the decision, what else was on the table, and the reasoning — including the ones we got wrong first and corrected. If you are about to change something here, read the relevant entry: several of these look arbitrary until you know what they cost to learn.

---

### 1. Memory lives inside the harness, not beside it

**Alternatives:** a separate memory service; an external memory product; the organisation's central memory system.

Memory needs the turn's identity, the profile's policy, and the harness's database — all of which are already in-process. A service would have meant network hops on the turn path, a second deployment to run, and duplicated auth. Instead the feature is a package with one seam file (`_digit.py`) holding every harness import, which keeps the rest portable and testable without a harness at all. The central system was not an option here: it is a separate service the team does not use for this, and this is agent-level memory governed by the harness's own profile system.

### 2. Postgres and pgvector, no new infrastructure

**Alternatives:** a dedicated vector database; a managed memory API.

The harness already runs Azure Postgres and the `vector` extension was already available. Two tables and a column beat a new system to operate, secure and pay for. At our scale the vector database buys nothing: queries are always scoped to one agent and one user first, which leaves tens of rows.

### 3. No ANN index — deliberately

**Alternative:** an HNSW index, which is what most vector tutorials do first.

Approximate indexes trade recall for speed, and they apply `WHERE` filters *after* the index scan. Because every query filters to a single scope, an exact scan over that handful of rows is both faster and perfectly accurate, while an index could actually *reduce* recall. Letta takes the same position in production. The growth trigger is documented: revisit when one scope exceeds tens of thousands of rows.

### 4. Append-only with supersede, never overwrite

**Alternatives:** update the row in place; delete and re-insert.

When a user changes their mind, the old fact is retired and given a pointer to its replacement. This preserves the history — auditors can reconstruct what the agent knew and when — and it makes every failure mode recoverable, because nothing is destroyed. It also makes the safe failure direction obvious: adding a duplicate row is noise, silently overwriting a fact is damage.

### 5. Everything degrades toward "add" or "do nothing"

No embedding, a malformed model verdict, a timeout, a database hiccup — every path ends in either a plain add or in memory quietly doing nothing for that turn. This is the single most important property of the write gate, and it is why mem0's 2026 removal of per-write model decisions did not force us to do the same: our decision can fail without consequence.

### 6. Recall travels in the data channel, not the instruction channel

**Alternative:** append recalled memories to the agent's instructions, which is what we originally built and what LangChain's `deepagents` still does by default.

Instructions are the authority channel — they are where "never do X" lives. Putting stored user data there gives anything that was ever saved instruction-level authority, which is a poor trust boundary in a multi-user system. Recall is now a separate fenced item in the model's input list, explicitly framed as data that loses to whatever the user says now.

**What it cost to get right:** we assumed the SDK did not persist input items into conversation history. A throwaway probe run *before* touching the harness proved the opposite. Without that check, the memory block would have accumulated in the stored transcript on every turn. The wrapper in `session_filter.py` exists because of that probe.

### 7. Similarity thresholds are measured, not borrowed

**Alternative:** the 0.70–0.95 "same entity" band that dedup literature suggests.

We used the literature values and they silently failed. A genuine changed-preference contradiction — "exactly three bullet points" becoming "five bullets now, not three" — measured **cosine 0.309** on `text-embedding-3-large` at 1536 dimensions. Short paraphrased sentences simply do not score the way entity-matching papers imply. The floor is now 0.30, taken from that measurement, and every write logs `memory gate: top_sim=… tier=… action=…` so the next person tunes from evidence instead of belief. **If you change the embedding model, these numbers do not transfer.**

### 8. The decision model returns an index, not text

Candidates are presented as a numbered list and the model replies with a number, which is range-validated. It cannot name a memory that does not exist, and anything malformed falls through to "add". mem0 and Graphiti arrived at the same guard independently, which is usually a sign it is the right one.

### 9. Identity is fail-closed, with no default tenant

**Alternative:** fall back to a `"default"` tenant when the caller does not send one — which is what the prototype did.

Filing a real person's data under a shared placeholder is the worst failure this system could have, because it is invisible and it mixes users. Memory now requires a validated user *and* tenant, and switches itself off for the turn otherwise. The visible cost is that console traffic has no memory until the console sends a tenant. That cost is worth paying, and it is temporary.

### 10. Post-turn extraction is durable, via an outbox

**Alternatives:** keep fire-and-forget; use a job queue system.

Fire-and-forget lost a memory whenever the process died between the turn ending and extraction finishing, and at the time one newer completion path in the harness skipped extraction entirely. (The harness has since unified its completion paths, so a single enqueue at the post-loop terminal now covers every success path by construction.) The outbox is a table plus a small worker — no new infrastructure, and the row survives anything. Delivery is at-least-once, which is safe precisely because of decision 4: a replay produces a duplicate the gate then drops.

The worker claims rows under a **lease** (a future retry timestamp) rather than a status flag, so a worker that dies mid-job releases its work automatically with no stuck-record cleanup to write.

### 11. Model calls never happen inside an open transaction

Our first worker held its claim transaction open across the extraction. It worked, and it was still wrong: a slow model call parks a pooled connection and a row lock for up to a minute. The cycle is now claim → extract → finalize as three separate short transactions, with nothing held during the model call. This is a general rule for the codebase, not just the worker.

### 12. Schema changes go through Alembic

**Alternative:** keep using `create_all` plus hand-written one-off scripts, which is what the harness did.

`create_all` cannot alter an existing table, so schema changes were becoming ad-hoc ALTER scripts nobody could audit. Migrations make every change reviewable before it runs, repeatable across environments, ordered, and reversible — the properties a regulated environment actually requires. The memory tables became the first revision; `create_all` survives only for throwaway local databases.

Because the dev database is shared with another application, migrations are scoped to harness-owned tables. Deciding *not* to manage another team's tables was as important as adopting the tool.

### 13. Deletion is two-stage

Deleting sets a timestamp, which stops the memory being used or shown immediately; permanent removal happens later via the retention worker. Regulators are explicit that hidden-but-readable data is not erasure, so the purge exists — but it only runs when a retention window is configured, because choosing that window is a governance decision rather than an engineering default.

### 14. Logs carry ids, counts and outcomes — never memory content

The system stores personal information, so its own telemetry must not become a second copy of that information in a place with weaker controls. The gate line proves this is not a limitation in practice: it carries a similarity score and a decision, which is enough to debug and tune without ever printing what someone said.

### 15. Off by default, enforced by a test

A flag that defaults false is a promise; a test that fails the build when any non-test profile turns it on is a guarantee. The distinction mattered to the review, and it costs about fifteen lines.

---

## Things we deliberately have not done

| Not built | Why not, and what would change our mind |
|---|---|
| Consolidation into per-user summaries | The injection budget already bounds per-turn cost. Build it when a user's scope routinely exceeds what 20 entries can represent. |
| An ANN vector index | See decision 3. Revisit past tens of thousands of rows in a single scope. |
| Cross-agent or organisation-wide memory | A much larger governance question than per-user memory, and not needed to prove the idea. |
| Sharing memory between users | Deliberately impossible under the current scoping. Any such feature should be a new, explicitly governed capability rather than a loosening of this one. |
| Per-entry encryption or crypto-shredding | Documented as the upgrade path if erasure guarantees ever need to be stronger than a scheduled purge. |
