# Demo Runbook — Agent Memory Prototype

Audience: team lead review. Total time ~5 minutes. Everything happens on the product surface (console + one DB query) — no dashboards.

## Pre-demo checklist (do this the day before, and again 30 min before)

- [ ] `verify_phase_a.py` prints `PHASE_A: PASS` on the pod.
- [ ] Agent A: `semantic_memory_enabled` **ON**. Agent B (any other agent): **OFF**.
- [ ] Two identities ready (per recon Q19): user 1 = you, user 2 = second test identity.
- [ ] A DB query ready in a terminal tab:
      `SELECT content, category, source, thread_id, created_at FROM agent_memory_entries WHERE user_id='<user1>' ORDER BY created_at DESC LIMIT 5;`
- [ ] Backend restart command ready (recon Q20).
- [ ] Fallback seed command ready (don't run unless needed):
      `python scripts/seed_demo.py --profile <agentA_profile_id> --user <user1>`
- [ ] **Rehearse the full script once.** If the agent doesn't call the tool on beat 1, switch to the stronger phrasing below; if it still doesn't, seed and pivot (see fallbacks).

## The script

**Beat 1 — capture.** Agent A, user 1, **new thread**:
> "Remember: I always want answers as exactly three bullet points, addressed to me by name. Save that."

Point at the visible `save_memory` tool call in the transcript. Say: *"The agent decided to persist that — explicitly, auditably."*

**Beat 2 — the row.** Run the DB query. Say: *"A governed row in the platform's existing Postgres — source, thread, user, timestamp. Not a hidden file; the profile directory is ephemeral, which is exactly why this is DB-backed."*

**Beat 3 — durability.** Restart the backend, live. Say nothing while it comes back; confidence is the message.

**Beat 4 — recall (the headline).** Same agent, same user, **new thread** — point at the new thread id out loud: *"New conversation. No history carried over — chat history is a different table and a different thread."* Ask something neutral:
> "Give me a quick status-update template."

The answer arrives as three bullets, addressed by name.

**Beat 5 — scoping trio (fast).**
- Same question, user 2, agent A → plain answer. *"Her memory, not mine — scoped per user within the agent."*
- Same question, user 1, agent B (flag off) → plain answer, and:
> "Remember that I like tables."
→ the agent declines: memory not enabled. *"Opt-in per agent; a disabled agent can't even write."*

**Beat 6 — close (compliance line).**
> *"Forget is one UPDATE to `discarded_at` today; an agent-facing forget-tool, per-write audit events, and the skills loop all hang off the same seams in phase two. Retrieval scales from load-recent to Postgres full-text search before we ever need to talk about vector infrastructure."*

**Optional beat (only if Phase B passed):** on agent A, say naturally:
> "By the way, I work on the payments reconciliation team."

Finish the turn, re-run the DB query → a `source='extraction'` row appeared with no tool call. *"Same pipeline, autonomous path — and it's the seam the phase-two skills reviewer shares."*

## Fallbacks (rehearsed, not improvised)

| Symptom | Move |
|---|---|
| Beat 1: no tool call | Rephrase: "Use your save_memory tool to store this: …". Still nothing → run `seed_demo.py`, show the row, continue from Beat 2 honestly ("seeded for time"). |
| Beat 4: preference not applied | Show the DB row + say the injection is in instructions; if recon Q21 gave an instructions/events inspector, show the `<user_memory>` block there. The row + block IS the proof; style compliance is model mood. |
| Restart takes long | Fill with Beat 2's row walk-through; the query tab is the parking spot. |
| Extraction beat flaky | Skip it — the headline never depends on extraction. |

## Reset between rehearsals

```
python scripts/reset_dev_tables.py --yes    # wipes ONLY the two memory tables
```
