# Roadmap and Handover

This feature was built during a ten-week summer internship. What shipped is complete and verified — but ten weeks is ten weeks, and a number of good ideas were deliberately left on the table rather than half-built. This document is the list, written so that whoever picks it up next does not have to reconstruct the reasoning first.

**Nothing here is a known defect.** Everything that shipped works and is tested; see [README.md](README.md) for the verified capability list and [KNOWN_ISSUES](KNOWN_ISSUES.md) for the small number of genuinely open items. What follows is scope that was consciously deferred, each with why it matters, roughly how to build it, and what to watch out for.

Each item carries a rough size: **small** is an afternoon, **medium** a few days, **large** a sprint or a design conversation.

---

## Tier 1 — Performance: make memory cost almost nothing

The one substantive critique from technical review was latency. It is fair, and it has cheap answers.

**Where the time actually goes today — now measured, not estimated.** Timed directly, recall is 761 ms: a 412 ms embedding call, a 301 ms database fetch and 0.6 ms of ranking. Timed inside a live turn it looks like **4.7 seconds** instead, and that discrepancy is not yet explained — see the measured-cost table in [ARCHITECTURE.md](ARCHITECTURE.md#3-anatomy-of-one-turn). Extraction is already fully asynchronous and costs the turn nothing measurable.

**Take the larger number seriously when you plan.** Everything below was originally sized against a few hundred milliseconds. If the in-turn figure is the real one, these items are worth several seconds a turn rather than a few hundred milliseconds, and item 1.1 moves from a nice tidy-up to the single highest-value change in this document.

### 1.1 Skip recall entirely when the user has no memories — **small**

**Why:** today we pay for the embedding call and *then* discover there is nothing to recall. At rollout most users have zero stored memories, so most turns pay the **full recall cost — measured between 761 ms and 4.7 s — to retrieve nothing at all.**

**How:** before embedding, run one indexed count over the scope (`profile_id, user_id, tenant_id`, `discarded_at IS NULL`). Zero rows means return `(None, 0)` immediately. That is roughly 2 ms instead of the full recall cost — between 761 ms and 4.7 s, depending on which measurement holds. Cache the answer per scope in-process with a short TTL if the count query itself ever shows up in profiling — but measure before adding a cache, because a wrong cache here means a user's first memory does not appear until it expires.

**Watch out for:** the count must use the same scope filter as recall, or you will skip recall for users who *do* have memories.

### 1.2 Skip the embedding for trivial inputs — **small**

**Why:** "ok", "thanks", "yes please" gain nothing from semantic ranking, and they are a meaningful share of real messages.

**How:** if the incoming message is below a threshold (say 15 characters, or matches a small stop-phrase set), skip the embedding and use the recency rung — which already exists and is already tested. The plumbing is there; this is a branch, not a feature.

**Watch out for:** do not tune this by eye. Log which branch was taken alongside the existing `memory gate:` telemetry and look at real traffic before hardening the threshold.

### 1.3 Overlap the embedding with turn setup — **medium**

**Why:** the embedding currently happens sequentially, before the agent and session are constructed. Those steps do real work and do not depend on the memory block.

**How:** start the embedding as a task, build the agent and session, then await it just before assembling the input list. Setup was measured at about 1.6 s on the dev pod, so overlapping hides that much of recall for free.

**Watch out for:** an un-awaited task that throws becomes an unhandled exception. Wrap it so a failed embedding still degrades to the recency rung rather than surfacing.

### 1.4 Recall once per thread rather than once per turn — **large**

**Why:** the biggest possible win, since most turns in a thread need the same memories.

**How:** compute the block on the first turn of a thread and reuse it, refreshing every N turns or when the message's embedding diverges from the one that produced the cached block. Store it on the session or in a small in-process cache keyed by thread.

**Watch out for:** staleness is user-visible. If someone corrects a preference mid-thread and the cached block still holds the old fact, the agent will contradict itself. Any implementation needs an invalidation path on write. This is why it was not done in ten weeks: the cheap version is subtly wrong, and the correct version is a design conversation.

---

## Tier 2 — Capability: things the design already anticipates

### 2.1 Consolidation into per-user profiles — **large**

**Why:** memories accumulate as many small facts. Recall injects at most 20, so the system does not degrade — but it also never gets *smarter* about a long relationship. Consolidation folds many small facts into a compact, curated profile, which is where ChatGPT, Claude and Gemini have all landed.

**How:** the table is already reserved (`agent_memory_user_models`, with a `content` column and a `version` for optimistic locking). Run it as a background job on the pattern the outbox worker already establishes: when a scope exceeds a threshold, summarise its entries into the user-model row, then soft-discard the folded entries with `superseded_by` pointing at the model row so provenance survives. Recall then injects the profile plus recent unfolded entries.

**Watch out for:** never consolidate on the write path — it belongs off the critical path entirely. And keep the originals: a summary is lossy, and the audit trail depends on the rows still existing.

### 2.2 A memory management screen — **medium**

**Why:** all six endpoints exist and are proxied through the console, but nothing renders them. Users cannot see what an agent remembers about them without curl.

**How:** the API is done — `GET /api/v1/memory`, `DELETE /api/v1/memory/{id}`, forget, disable, enable, status. The work is entirely front-end, in the console or the official DIGIT UI.

**Watch out for:** this is a product design question dressed as an engineering task. What to show, how to phrase deletion, whether to expose provenance and dates — those decisions deserve a designer, which is exactly why the plumbing was built and the screen was not.

### 2.3 Enforce the per-scope quota — **small**

**Why:** `MemoryPolicy.max_entries_per_scope` is declared and documented, and nothing reads it. Growth is currently bounded by the injection budget rather than by a hard cap.

**How:** check it in `smart_add_entry` before persisting. The interesting question is what to do when the cap is hit: reject the write, or discard the oldest? Rejecting is safer and matches ChatGPT's behaviour (which stops saving when full); silently evicting risks losing something the user cares about. Consolidation (2.1) is the better long-term answer.

### 2.4 Turn on retention — **small engineering, large decision**

**Why:** the two-stage deletion story is only half live. Soft-delete works; the purge worker exists and runs; but with no window configured it deletes nothing, so "deleted" data lives indefinitely.

**How:** set `AGENT_FACTORY_MEMORY_RETENTION_DAYS`. That is the whole engineering task.

**Watch out for:** the number is a governance decision, not an engineering one. Reference points from the survey: ChatGPT hard-deletes within about 30 days; Gemini's activity default is 18 months. Someone with authority needs to choose, and the choice should be written down next to the value.

---

## Tier 3 — Operations and scale

### 3.1 Cost and usage accounting — **medium**

**Why:** memory makes model calls (embeddings, the adjudication call, extraction) and nobody is counting. The harness has no usage accounting anywhere, so this is not a memory-specific gap — but memory is a good place to start, because its calls are easy to attribute.

**How:** the side-call helper already logs token counts when the SDK exposes them (it currently does not). When it does, or via the provider's own reporting, emit a metric per call tagged by purpose: recall-embedding, gate-decision, extraction. Then the question "what does memory cost per active user per month" becomes answerable instead of arguable.

### 3.2 Make the gate telemetry visible — **small**

**Why:** every write already logs `memory gate: top_sim=… tier=… action=…`, which is exactly the data needed to retune thresholds. It currently lives in log files nobody aggregates.

**How:** ship those lines to whatever metrics stack the team uses and chart the distribution of `top_sim` by outcome. The moment someone changes the embedding model, that chart is how you recalibrate — see the trap below.

### 3.3 An ANN index, when the scale demands it — **medium**

**Why:** there is deliberately no vector index. At current scale an exact scan within one already-filtered scope is both faster and perfectly accurate, and an approximate index applied after filtering can actually *reduce* recall. See decision 3 in [DECISIONS.md](DECISIONS.md).

**How:** revisit when a single scope routinely exceeds tens of thousands of rows. HNSW with pgvector's iterative scans is the documented upgrade, and the 1536-dimension choice was made partly to stay under the index limit so it remains a drop-in.

**Watch out for:** adding it early is a pure loss — slower to build, worse recall, no benefit.

### 3.4 A re-embedding path — **medium**

**Why:** if the embedding model ever changes, every stored vector becomes incomparable with new ones, and the calibrated thresholds stop meaning anything.

**How:** `scripts/backfill_embeddings.py` already re-embeds rows with a null vector; generalise it to re-embed *all* rows for a scope, run it as a migration step, and recalibrate the thresholds from fresh telemetry afterwards. Treat a model change as a data migration, not a config change.

---

## Tier 4 — Decisions that are not engineering

- **Real tenant claims in the console.** The console currently takes its tenant from server-side configuration because it has no authentication claims to read. When it does, replace the config read in `agent-console/lib/harness.ts` — one line, one site. This is blocked on auth work, not on memory work.
- **Cross-agent or organisation-wide memory.** Deliberately impossible under the current scoping. If it is ever wanted, it should be a new, explicitly governed capability rather than a loosening of this one — shared memory is a different privacy conversation.
- **Stronger erasure guarantees.** If a scheduled purge is ever judged insufficient, per-scope encryption keys ("crypto-shredding") are the accepted upgrade: destroy the key and the data is unrecoverable regardless of backups.

---

## Something genuinely missing: a way to measure recall *quality*

Everything is tested for correctness — that memory saves, recalls, isolates, degrades and never breaks a turn. Nothing measures whether the memories it chooses are the *right* ones.

**Why it matters:** the ranking blend (0.7 similarity, 0.3 recency), the 0.35 injection floor and the 20-entry budget were all reasoned about and spot-checked live, never evaluated systematically. If someone changes them, they have no way to know whether recall got better or worse.

**How to build it:** a small fixture set of realistic scopes — say twenty memories per user across several topics — plus a set of queries with hand-labelled "these are the memories that should surface". Then a script that runs recall and reports precision and recall at the injection limit. It is perhaps a day's work and it turns every future tuning change from an argument into a measurement.

I would build this **first** if I came back to the project, because everything in Tier 1 changes what gets recalled, and right now there is no way to prove those changes are safe.

---

## If you only do three things

1. **Skip recall when the scope is empty** (1.1) — removes the per-turn cost for most users, an afternoon's work.
2. **Build the recall-quality harness** (above) — makes every other tuning change measurable instead of debatable.
3. **Decide the retention window** (2.4) — the engineering is one environment variable; the decision is the actual work, and until it is made, "deleted" data is not deleted.

## Traps worth knowing before you change anything

- **Do not port the similarity thresholds to a different embedding model.** They were measured on `text-embedding-3-large` at 1536 dimensions, where a genuine contradiction scored 0.309 — far below the 0.70 the literature suggests. Recalibrate from telemetry.
- **Do not make recall asynchronous.** The model needs the memories before it answers. Extraction is the asynchronous half and already is.
- **Do not hold a database session across a model call.** The outbox worker was written that way once and had to be restructured. Claim, release, process, finalise.
- **Do not put memory back in the instruction channel** because it is convenient. Instructions are the authority channel; stored user data is not authority.
- **Do not weaken the three-part scope.** Every query filters on agent, user *and* tenant. Dropping one silently mixes people's data, which is the worst failure this system could have.
