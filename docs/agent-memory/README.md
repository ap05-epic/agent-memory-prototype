# Agent Memory

Persistent, per-user memory for DIGIT agents. An agent with memory enabled remembers durable facts about each specific user — preferences, corrections, working context — across threads and across restarts.

**Off by default.** Nothing changes for an agent until its profile enables it, and a test in the suite fails the build if any non-test profile does.

---

## Why this exists

People not having to repeat themselves is a real benefit, but it is not why this was built.

This is the **base layer** for something larger. An agent that can durably record what a specific person needs is the prerequisite for an agent that adapts to them — and, further out, for generic agents that get measurably better for everyone as more people use them.

Three layers. Only the first is built.

**1 — Durable facts about a user.** *Shipped.* Preferences, corrections, working context, scoped per agent × user × tenant, governed and auditable. This is what the rest of this document describes.

**2 — Learned workflows, as a skill layer over a generic agent.** *Next.* The same capture path that records *"prefers concise updates"* can record how someone actually works: the shape of output they need, the steps they always ask for, the checks they always want run. Those compose into a per-user layer applied on top of a **generic** agent file — so one shared agent fits many people's very different work without anyone forking it.

**3 — Feeding real usage back into the generic agents.** *The payoff.* On a review cycle — every three to six months — pull what has accumulated across everyone using a given agent, find the patterns that recur across many people, and fold the common ones back into the core agent file. Every entry is already stored with an embedding, so finding those patterns is a clustering query plus a model reading the clusters, not a new pipeline.

**Step 3 is the point.** It turns the periodic agent-file review from an exercise in opinion into one with evidence behind it, and it means a generic agent improves from how it is actually used rather than from guesses about how it might be.

**None of it is possible without this layer.** You cannot analyse what people need from an agent if nothing ever recorded it. That is why the storage is scoped, governed and auditable from the first commit rather than bolted on once someone asks for the analysis.

> **One boundary, stated up front.** Step 3 reads across users, and the runtime scoping deliberately makes that impossible — no user ever sees another's memories, and that guarantee does not change. The aggregate analysis is a separate, offline, separately authorised job whose output is *patterns*, never any individual's data. Keeping those two things apart is a governance requirement, not an implementation detail. How to build it that way is in [ROADMAP.md](ROADMAP.md).

## The 60-second model

A memory is one short fact about one user, stored in the harness's existing Postgres and keyed by **(agent, user, tenant)**. Two things create memories, and one thing uses them:

- **The `save_memory` tool** — the agent calls it when the user states something durable.
- **Post-turn extraction** — a background worker reads the finished exchange and captures durable facts the user stated without asking.
- **Recall** — at the start of every turn, relevant memories are fetched, ranked, and passed to the model as a fenced block of *data* (never as instructions).

Every write passes one gate: exact duplicates are dropped for free, near-identical facts supersede the old one, and genuinely ambiguous cases are adjudicated by a small model. Contradictions never overwrite — the old row is retired with a pointer to its replacement, so the history stays auditable. Deletes are soft, and a retention job handles permanent removal on a configured schedule.

If memory can't do its job — the embedder is down, the database is unreachable, identity is incomplete — it degrades or switches itself off. **It never breaks a turn.**

## Where to look next

| If you want to… | Read | Time |
|---|---|---|
| Understand how it works, with diagrams | [ARCHITECTURE.md](ARCHITECTURE.md) | 15 min |
| Know why it is built this way | [DECISIONS.md](DECISIONS.md) | 10 min |
| Change or extend it without breaking things | [DEVELOPING.md](DEVELOPING.md) | 10 min |
| Run it, configure it, call its API, or debug it | [OPERATIONS.md](OPERATIONS.md) | reference |
| Know what a specific file or function does | [CODE_WALKTHROUGH.md](CODE_WALKTHROUGH.md) | reference |
| Pick up where this left off | [ROADMAP.md](ROADMAP.md) | 10 min |

Picking up work on this? Read this page, then ARCHITECTURE and DEVELOPING — about half an hour, and enough to be productive. Reach for DECISIONS the moment something looks arbitrary; it probably is not.

## What exists today

Everything below is built, and everything marked *live-verified* was proven by driving the running system rather than by reading the code. The one exception is called out in the table. The feature is **not enabled for general use** — that is a deliberate switch, not an unfinished edge.

| Capability | State |
|---|---|
| Explicit saves via the `save_memory` tool | Live-verified |
| Automatic capture from finished turns | Live-verified |
| Semantic recall ranked by relevance and recency | Live-verified |
| Supersede on contradiction, with the history kept | Live-verified |
| Scoping per agent, user and tenant | Live-verified, including cross-user and cross-tenant checks |
| Fail-closed identity gate | Live-verified both ways — works with identity, silent without |
| Schema through Alembic migrations | Applied and drift-free against the live database |
| Running on the harness's own database lifecycle | Verified by log receipt: no private engine in-app |
| Durable extraction surviving restarts | Live-verified: killed mid-flight, drained on boot |
| Recall in the data channel, out of the instruction channel | Live-verified, with zero rows leaking into stored history |
| View, delete, forget and disable your own memories | Live-verified, with an audit row per mutation |
| Audit trail and retention worker | Built; retention purges only when a window is configured |
| Memory in the console UI | Code complete, verified by inspection — browser check still outstanding |
| Consolidation into per-user summaries | **Designed, not built** — see [ROADMAP.md](ROADMAP.md) |

**What it costs a turn** is measured rather than argued: recall is the only synchronous part, extraction happens entirely after the user has their answer, and both figures — including one discrepancy that is still unexplained — are in [ARCHITECTURE.md](ARCHITECTURE.md#3-anatomy-of-one-turn). Short version: on the dev pod memory is roughly a tenth of turn latency, and the other nine tenths is a harness stall that has nothing to do with this feature.

This was built during a ten-week internship. What shipped is complete and verified; what was deliberately left is written up in [ROADMAP.md](ROADMAP.md) with the reasoning, an implementation sketch and the traps for each item — so the next person starts from where this finished rather than from scratch.

## Explaining this to someone

Three depths. Pick by who is asking and how long you have.

**Thirty seconds — anyone.**
> DIGIT agents forget everything between conversations, so people repeat themselves constantly. This gives an agent durable memory of each specific user — their preferences, corrections, working context — that survives new threads and restarts. It lives in the database the harness already uses, it is off by default, and it is scoped so one user can never see another's memories.

**Five minutes — an engineer or a manager.** Walk one turn, because the whole design falls out of it: a turn arrives → the agent checks a flag and the caller's identity → relevant memories are ranked and passed to the model *as data, never as instructions* → the model answers → anything durable the user said gets saved, either explicitly through a tool or automatically afterwards → every write passes a gate that deduplicates and retires contradicted facts rather than overwriting them. Then the two properties that matter: **it can never break a turn** (every failure degrades or does nothing), and **nothing is destroyed** (soft deletes and supersede chains are the audit trail). Show the two pipeline diagrams at the top of [ARCHITECTURE.md](ARCHITECTURE.md)'s section 3 while you say it — the same turn drawn twice, once plain and once with memory, so the whole footprint is visibly two boxes and a background worker.

**Fifteen minutes — someone who will work on it or review it.** The five-minute version, then the three things that are non-obvious: the similarity thresholds are *measured from our own telemetry*, not taken from papers, and they do not transfer if you change the embedding model; recall lives in the data channel specifically because instructions are the authority channel and stored user data does not belong there; and identity is fail-closed, so no validated user and tenant means no memory rather than a guess. Finish with [DECISIONS.md](DECISIONS.md) — it answers "why not the obvious thing?" for every choice that looks strange.

**If they want to go deeper**, the reading order is this page → ARCHITECTURE → DECISIONS → DEVELOPING → CODE_WALKTHROUGH, and they can stop at any point and still have a complete picture at that depth. Do not hand someone the walkthrough first; it is a reference, not an introduction.

## The five things worth knowing before you touch it

1. **Scope is three-part.** Every query filters on agent, user, *and* tenant. Dropping one silently mixes people's data — the most dangerous possible bug in this system.
2. **Memory is data, not instructions.** The recalled block is fenced and explicitly subordinate to what the user says now. Never move it into the instruction channel for convenience.
3. **Failure means "do nothing", not "guess".** Every degradation path falls back to writing an extra row or injecting nothing. That asymmetry is deliberate: a duplicate is noise, a wrong overwrite is damage.
4. **Nothing is destroyed at runtime.** Soft-delete and supersede chains *are* the audit trail.
5. **Thresholds are measured, not borrowed.** The similarity numbers in the write gate came from telemetry on real behaviour with the model we actually use. If you change the embedding model, recalibrate them — the current values will not transfer.

Every one of those five has a decision entry explaining what it cost to learn.
