# Memory Prototype — Demo in Action

> A narrated walkthrough of the demo: each step, the exact input, and **what you see happen**. This is the "watch it work" companion to `DEMO_RUNBOOK.md` (which is the operational checklist with the launch commands). Reproduces the live run verified on 2026-07-07.

**Setup in one line:** backend running with the launch fix, agent `memory-demo` (memory ON), a second agent with the flag OFF, and a terminal tab with this query ready:
```sql
SELECT content, category, source, thread_id, user_id, created_at
FROM agent_memory_entries WHERE user_id = '<you>' ORDER BY created_at DESC LIMIT 5;
```

---

## Act 1 — Teach it something

**You, in a new conversation with `memory-demo`:**
> "Remember: I always want answers as exactly three bullet points, addressed to me by name. Save that."

**What you see:** the transcript renders a **`save_memory` tool call** — `tool.started` then `tool.completed`. The agent decided, visibly and auditably, to persist your preference.

> *Say:* "It chose to store that — explicitly, as a tool call anyone can see."

---

## Act 2 — Show the row

**Run the SQL query.** One row comes back:

```
content                                             | category   | source | thread_id | user_id
----------------------------------------------------+------------+--------+-----------+----------
answers as three bullet points, addressed by name   | preference | tool   | <thread-1>| <you>
```

> *Say:* "A governed row in our existing Azure Postgres — content, source, which thread, which user, timestamp. Not a file in the ephemeral profile directory — a durable database row. That's the whole point."

---

## Act 3 — Restart (prove durability)

**Restart the backend process, live.** Wait for it to come back healthy; refresh the console.

> *Say nothing — confidence is the message.* Then: "Fresh process. Nothing in memory-of-the-running-app survived. Only the database did."

---

## Act 4 — The headline: recall in a brand-new thread

**Open a NEW conversation** with the same agent (new thread id — point it out). Ask something neutral, with no hint of the preference:
> "Give me a quick status-update template."

**What you see — two things:**
1. A status line at the top of the turn: **🧠 Recalled 1 saved memory** — the recall indicator firing.
2. The answer arrives as **exactly three bullet points**:
```
- Today: [what you completed]
- In progress: [current item] — [ETA]
- Blocked / next: [blocker] — [what you need]
```

> *Say:* "New conversation, new thread — the chat history did not follow us; that's a different table. But the agent still formats the way I taught it, and you can see it recall. This is memory, not history."

*(On the note of "by name": in the live run the greeting rendered as a placeholder because the demo user's id is literally `console-user`, not a real name. The three-bullet **format** is the unmistakable proof — lead with that.)*

---

## Act 5 — Scoping (prove it's not global)

**A different user, same agent** (run the prepared curl as `user-b`, or a second identity): ask the same neutral question.

**What you see:** a normal, long, default-format answer — **no** three bullets, **no** recall indicator. And if you check the DB, `user-b` has **no rows**.

> *Say:* "Her memory, not mine. Scoped per user within the agent."

**The flag-off agent:** ask it the same question → plain answer, no indicator. Then:
> "Remember that I like tables."

→ it declines — memory isn't enabled for that agent.

> *Say:* "Opt-in per agent. A disabled agent can't even write. Nothing changes for agents that don't want this."

---

## Act 6 — Automatic capture (optional, if showing Phase B)

**Back on `memory-demo`, say something durable in passing** — no "remember", just conversation:
> "By the way, I work on the payments reconciliation team."

Let the turn finish. Behind the scenes, a background step reads the exchange and stores the fact — no tool call needed.

> **Honest demo note:** `memory-demo` is an *eager* agent — it often calls `save_memory` itself for durable facts, and the background extractor then correctly finds nothing new to add (it dedupes). So a clean, isolated `source='extraction'` row is hard to force live in the console. The reliable way to show the autonomous path is in a terminal:
> ```
> python3 scripts/verify_phase_b.py    →    PHASE_B: PASS (a real source='extraction' row is written)
> ```

> *Say:* "There are two ways memory gets written — the agent choosing to save, and an automatic post-turn capture. Both are proven. The automatic one is the seam a future self-improving-skills reviewer will share."

---

## Act 7 — Close (answer the governance question before it's asked)

> *Say:* "Deleting a memory is one soft-delete update today — nothing is ever hard-erased, so the log is also an audit trail. An agent-facing forget tool, per-write audit events, and the phase-two skills loop all hang off the same seams. And retrieval scales from load-recent to Postgres full-text search long before we'd need to talk about vector infrastructure."

---

## If something misbehaves (rehearsed, not improvised)

| Symptom | Move |
|---|---|
| Act 1: no tool call | Rephrase: "Use your save_memory tool to store this: …". Still nothing → seed the row with `scripts/seed_demo.py`, show it, continue from Act 2 honestly. |
| Act 4: format not applied | Show the DB row + the 🧠 indicator + the run-events trace (`GET /api/v1/runs/<run_id>/events`). The row + indicator are the proof; exact style is model mood. |
| Backend won't start | Check the launch fix ran (`unset` stale `AZURE_OPENAI_BASE_URL`) and `PORT=8080` (not the occupied 50001). |
| Extraction beat flaky | Skip it — the headline never depends on it; use `verify_phase_b.py` instead. |

---

## The 30-second version (if you have no time)

1. Teach `memory-demo` a preference → visible save.
2. Restart the backend.
3. New thread → **🧠 Recalled 1 saved memory** → answer honors the preference.
4. Different user / flag-off agent → nothing.

That sequence *is* the prototype: durable, per-(agent, user), opt-in, visible, surviving a restart.
