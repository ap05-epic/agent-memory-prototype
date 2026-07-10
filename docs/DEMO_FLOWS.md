# Demo Flows — exact conversations to run

Two scripted flows for agent **memory-demo** in the console: a 2-minute smoke test (run before any rehearsal/demo) and the full showcase flow. Type the lines as written; "NEW CHAT" means start a fresh conversation (new thread — that's what proves memory ≠ history). Expected observations follow each line.

---

## Flow 1 — Quick smoke test (~2 min, run this first)

**Chat 1 (new):**
> Remember: my favorite color for dashboards is teal.

☑ `save_memory` tool chip appears · result "Saved to persistent memory."

**Chat 2 (NEW CHAT):**
> What color should I use for my dashboard chart?

☑ **🧠 Recalled 1 saved memory** at the top · answer says **teal**

**Same chat:**
> Remember: actually, make my dashboard color navy from now on, not teal.

☑ tool chip · result **"Saved — this replaces an older memory on the same topic."**

**Chat 3 (NEW CHAT):**
> Which color was it for my dashboards again?

☑ 🧠 indicator · answer says **navy** (not teal, no "conflicting preferences")

All four boxes ticked = save, recall, supersede, and cross-thread memory all healthy. **Clean up after** (see bottom) so the demo starts pristine.

---

## Flow 2 — The showcase (~5–6 min, this is the demo)

### Act 1 — teach it (Chat 1, new)
> Remember these three things about me: I always want answers as exactly three bullet points. I work on the payments reconciliation team. And I prefer Python over Java for code examples.

☑ one or more `save_memory` chips (the agent may save them as separate memories — even better, say: "it decided how to store those — visibly, auditably")

*Optional aside for the audience:* show the DB rows —
```sql
SELECT content, category, source, thread_id FROM agent_memory_entries
WHERE user_id='console-user' AND discarded_at IS NULL ORDER BY created_at;
```
*"Governed rows in our existing Postgres — not files, not a vector database service."*

### Act 2 — durability (optional but powerful)
Restart the backend process (launch block from the runbook). Refresh the console.
*"Fresh process. Only the database survived."*

### Act 3 — recall in a NEW conversation (Chat 2, NEW CHAT)
> Give me a quick status update for my manager.

☑ **🧠 Recalled N saved memories** · answer arrives as **exactly three bullets**, and — nice touch — it's framed for someone on a payments team.
*Say: "New conversation. Chat history did not follow us — this is the memory table. And you can see it recall."*

### Act 4 — relevance, not recency (same chat or new)
> Show me a tiny example function that parses a date string.

☑ the example comes back in **Python** — the *relevant* memory won, not the newest one.
*Say: "Recall is ranked by meaning against what I just asked — embeddings via pgvector in the same Postgres. Zero new infrastructure."*

### Act 5 — change your mind (Chat 3, NEW CHAT)
> Remember: actually I want five bullet points from now on, not three.

☑ tool chip: **"Saved — this replaces an older memory on the same topic."**

Show the chain (the money shot for governance):
```sql
SELECT content, discarded_at IS NOT NULL AS retired, superseded_by
FROM agent_memory_entries WHERE user_id='console-user' ORDER BY created_at;
```
☑ the three-bullets row: `retired = true`, `superseded_by` = id of the new row.
*Say: "It updated instead of piling up contradictions — and nothing was deleted. The chain IS the audit trail: you can read how my preference evolved."*

### Act 6 — proof it took (Chat 4, NEW CHAT)
> Summarize what you know about how I like to work.

☑ 🧠 indicator · a **five-bullet** summary mentioning payments reconciliation and Python.
*Say: "Full transparency — the user can always ask what it remembers."*

### Act 7 — containment (terminal, prepared curl)
```bash
curl -sS -N -X POST http://127.0.0.1:8080/api/v1/turns/stream -H 'Content-Type: application/json' \
  -d '{"profile_id":"memory-demo","input":"What do you know about me and how I like to work?","user":{"user_id":"user-b","email":"user-b"},"runtime":{"execution_engine":"sdk"}}'
```
☑ user-b gets "nothing stored yet" — zero leakage.
*Close: "Scoped per user within each agent, opt-in per agent, delete is one update, and the same post-turn seam is where the phase-two self-improving-skills loop plugs in."*

---

## Clearing all memory (a clean profile to start from)

**Recommended — delete the rows, keep the schema** (zero risk of column-type drift). Run on the pod from the harness repo root with `.env` sourced:
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
No backend restart needed — the next turn simply finds no memories.

**Alternative — full table reset** (`reset_dev_tables.py --yes` from the transfer repo): drops and recreates both tables. ⚠️ Only with the memory env vars exported first (especially `AGENT_FACTORY_MEMORY_PGVECTOR=1`) — the embedding column's type is chosen at import time, and resetting without the flag recreates it as the wrong type.

**Soft alternative — retire one user only** (also a nice compliance demo):
```bash
PYTHONPATH=src python3 -c "import asyncio; from agent_factory.memory.store import forget_user; print('retired', asyncio.run(forget_user('memory-demo','console-user')))"
```
(Soft-delete: rows stay for audit but stop being recalled. For a pristine demo slate, use the DELETE above instead.)

### The prompt to hand Copilot (if you'd rather not run it yourself)

> Clear all agent memory so we have a clean demo slate. In /projects/DigitHarnessRepo/digit-agent-harness, source .env, then with PYTHONPATH=src run a short python snippet that opens a session via agent_factory.memory._digit.get_session and executes DELETE FROM agent_memory_entries and DELETE FROM agent_memory_user_models, commits, and prints the deleted row counts. Touch no other tables, do not run reset_dev_tables.py, and do not print any secrets. Then confirm with scope_metrics('memory-demo','console-user') that live=0.
