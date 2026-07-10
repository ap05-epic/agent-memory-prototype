# Demo Flows — proving the memory is real

> Two flows for agent **memory-demo**: a 2-minute smoke test, and **the Skeptic's Demo** — where every act is built to kill a specific "it's fake" objection, using arbitrary facts no model could guess, negative controls, and database receipts. "NEW CHAT" = start a fresh conversation (new thread; that's the point). Run the smoke test + a full rehearsal beforehand, and **clear memory** (bottom) so you start pristine.

---

## Flow 1 — Quick smoke test (~2 min, before any rehearsal)

1. **New chat:** `Remember: my favorite color for dashboards is teal.` → ☑ save chip
2. **NEW CHAT:** `What color should I use for my dashboard chart?` → ☑ 🧠 indicator + **teal**
3. Same chat: `Remember: actually, make my dashboard color navy from now on, not teal.` → ☑ chip: **"replaces an older memory"**
4. **NEW CHAT:** `Which color was it for my dashboards again?` → ☑ **navy**, no mention of conflicting preferences

Four ticks = save, recall, supersede, cross-thread. Clear afterward.

---

## Flow 2 — The Skeptic's Demo (~8 min)

Keep two terminal tabs ready: **[SQL]** the row query, **[LOG]** `grep 'memory gate:' /tmp/demo.log`.

```sql
-- [SQL] the receipt query
SELECT left(content,60) AS memory, category, source,
       discarded_at IS NOT NULL AS retired, superseded_by IS NOT NULL AS replaced
FROM agent_memory_entries
WHERE user_id='console-user' ORDER BY created_at;
```

### Act 1 — Seed arbitrary facts (Chat 1, new)

> Remember these things about me: my project's internal codename is Kestrel. My manager's name is Priya. I'm vegetarian. I want answers as exactly three bullet points. And I prefer Python over Java for code examples.

☑ save chip(s) — the agent decides how to split them (often several saves; say: *"it chose how to store those — every save is a visible, auditable tool call"*).

**[SQL]** → rows exist, `source=tool`, each tied to this thread id.

*Why this can't be faked:* "Kestrel" and "Priya" are arbitrary. No model "just knows" them — if they come back later, they came from storage.

### Act 2 — Kill "it's just the context window" (restart + NEW CHAT)

Restart the backend process (runbook launch block). Refresh the console. **NEW CHAT:**

> What was my project's codename again?

☑ **🧠 Recalled N saved memories** · answer: **Kestrel**.

*Say:* "New process, new conversation — the chat history table starts empty for this thread. The only place 'Kestrel' existed was the memory table."

### Act 3 — The negative control (kill "it hallucinates memories")

Same chat:

> And what's my favorite football team?

☑ Agent says it **doesn't have that stored** — no invention.

*Say:* "Just as important: it doesn't pretend. If it's not in memory, it says so. Recall is retrieval, not vibes." *(This one line buys more trust than any positive beat.)*

### Act 4 — Kill "it's keyword matching" (zero-overlap semantic recall)

**NEW CHAT:**

> I'm organizing a team dinner for us next week. Anything about me you'd factor into picking the restaurant?

☑ 🧠 indicator · answer factors in **vegetarian**.

*Say:* "Look at the words — 'dinner', 'restaurant'. The stored memory says 'vegetarian'. Zero keywords in common; it matched on **meaning**. That's the embedding search, running in our existing Postgres via pgvector."

Also point at the 🧠 count: it recalled a **subset**, not everything — *"and notice it selected the relevant memories, it doesn't dump the whole file into every prompt."*

### Act 5 — Relevance beats recency

Same or new chat:

> Show me a tiny example function that parses a date string.

☑ example arrives **in Python** (and the reply is in three bullets, if you want to point at the compound effect).

*Say:* "The Python preference wasn't the newest memory — it was the *relevant* one. Ranking is 70% meaning, 30% recency."

### Act 6 — Kill "updates just pile up" (supersede, with receipts)

**NEW CHAT:**

> Remember: the project codename changed — it's Osprey now, not Kestrel.

☑ chip: **"Saved — this replaces an older memory on the same topic."**

**[SQL]** → the Kestrel row now shows `retired=true, replaced=true`; a new Osprey row is live.
**[LOG]** → `memory gate: top_sim=0.… tier=decide action=supersede` — *"that's the system's own decision log: it measured the similarity, consulted a small model, and chose to supersede. Content-free telemetry — we tuned thresholds from these lines, not guesses."*

**NEW CHAT:** `What's my project's codename?` → ☑ **Osprey**, and Kestrel is *not* mentioned.

*Say:* "The old fact is retired with a link to its replacement — nothing deleted. The chain is a readable audit trail of how the fact evolved. That's the same pattern Zep uses for enterprise memory."

### Act 7 — Kill "it'll store anything" (the guardrail, live)

Same chat:

> Remember my corporate card number: 4111 1111 1111 1111.

☑ Either the agent itself declines, **or** the tool fires and returns *"That looks like sensitive data… not saved."* **[SQL]** → no new row either way.

*Say:* "Two layers: the agent is instructed never to store credentials or card numbers, and even if it tries, the store's denylist rejects it at write. Defense in depth — and memory content never appears in logs at all."

### Act 8 — Kill "it leaks across users" (isolation, terminal)

```bash
curl -sS -N -X POST http://127.0.0.1:8080/api/v1/turns/stream -H 'Content-Type: application/json' \
  -d '{"profile_id":"memory-demo","input":"What do you know about me and my project?","user":{"user_id":"user-b","email":"user-b"},"runtime":{"execution_engine":"sdk"}}'
```

☑ user-b: nothing stored, no 🧠, no Osprey. **[SQL]** filtered on `user_id='user-b'` → zero rows.

*Say:* "Same agent, different user — different rows, nothing shared. Every query is scoped by (agent, user). And an agent without the memory flag can't read or write any of this at all."

### Act 9 — The finale: transparency, then the right to forget (live)

**NEW CHAT:** `What do you remember about me? List everything.`
☑ 🧠 + an honest list (Osprey, Priya, vegetarian, five/three bullets, Python).

Then, in the terminal — one call:
```bash
cd /projects/DigitHarnessRepo/digit-agent-harness && set -a; source .env; set +a
PYTHONPATH=src python3 -c "import asyncio; from agent_factory.memory.store import forget_user; print('retired:', asyncio.run(forget_user('memory-demo','console-user')))"
```

**NEW CHAT:** `What do you remember about me?`
☑ No 🧠 indicator · *"I don't have anything stored about you yet."*

*Say:* "One call retired everything — reversible and audit-preserving today, with a scheduled hard-purge policy proposed for governance. Right-to-forget isn't a slide, you just watched it."

---

## If a beat wobbles (rehearsed fallbacks)

| Wobble | Move |
|---|---|
| Agent answers Act 1 without saving | Append: "Please save those with your save_memory tool." |
| A recall answer is right but style is off (bullets count) | The **fact** recall is the claim; point at the 🧠 line + [SQL] rows — style is model mood |
| Act 4 doesn't surface vegetarian | Ask more directly: "any dietary preferences of mine to consider?" — still zero-keyword vs the stored text |
| Act 6 chip says plain "Saved" | Show [LOG]: if `action=add`, say "the decision model judged them distinct — watch the DB instead," then show both rows and rerun the ask; the recall still prefers the newest. Investigate after, never during |
| Act 7 agent refuses before the tool fires | That IS the demo — "the first layer caught it; the denylist is the backstop" |

## Backstage checklist

- Launch with the full block (env vars + `PYTHONPATH` + `> /tmp/demo.log 2>&1`); verify the BUILD line: `grep 'agent_memory seam loaded' /tmp/demo.log`.
- Smoke test (Flow 1) → **clear memory** → rehearse Flow 2 once → **clear memory** again → demo.

---

## Clearing all memory (clean slate)

**Recommended — delete rows, keep schema (zero risk):**
```bash
cd /projects/DigitHarnessRepo/digit-agent-harness && set -a; source .env; set +a
PYTHONPATH=src python3 - <<'EOF'
import asyncio
from sqlalchemy import text
from agent_factory.memory import _digit
async def main():
    async with _digit.get_session() as s:
        r1 = await s.execute(text("DELETE FROM agent_memory_entries"))
        r2 = await s.execute(text("DELETE FROM agent_memory_user_models"))
        await s.commit()
        print(f"CLEARED entries={r1.rowcount} user_models={r2.rowcount}")
asyncio.run(main())
EOF
```
No restart needed. (⚠️ `reset_dev_tables.py` also works but ONLY with the memory env vars exported first — the embedding column type is chosen at import time. The row-delete above avoids that trap entirely.)

**Copilot prompt version:**
> Clear all agent memory so we have a clean demo slate. In /projects/DigitHarnessRepo/digit-agent-harness, source .env, then with PYTHONPATH=src run a short python snippet that opens a session via agent_factory.memory._digit.get_session and executes DELETE FROM agent_memory_entries and DELETE FROM agent_memory_user_models, commits, and prints the deleted row counts. Touch no other tables, do not run reset_dev_tables.py, and do not print any secrets. Then confirm with scope_metrics('memory-demo','console-user') that live=0.

---

## The objection → receipt map (keep in your head)

| If they say… | You show… |
|---|---|
| "It's just the context window" | new thread + restart, then Kestrel comes back (Act 2) |
| "The model's just guessing well" | arbitrary facts (Kestrel/Priya) + the negative control (Act 3) |
| "It's keyword search" | the dinner→vegetarian beat, zero word overlap (Act 4) |
| "Preferences will contradict over time" | the supersede chain in the DB + the gate log line (Act 6) |
| "It'll store something sensitive" | the card-number rejection, no row written (Act 7) |
| "It'll leak between users" | user-b curl, zero rows (Act 8) |
| "What about GDPR/forget?" | the live forget finale (Act 9) |
| "Is this real or a mock?" | [SQL] rows with thread ids + the `memory gate:` telemetry, live |
