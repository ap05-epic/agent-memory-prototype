# Recon Round 1 — Memory Prototype Ground Truth

You are the on-pod recon agent with full read access to the harness repository. Answer the numbered questions below against the **real code** — quote, don't infer. Your output will be transcribed from screenshots by OCR, so the ANSWER FORMAT rules are mandatory.

## Context (so your answers aim right)

We are adding **per-agent, per-user persistent memory** to the harness: two new SQLAlchemy tables scoped by (profile_id, user_id, tenant_id); a memory block fetched pre-turn and appended to instructions; a `save_memory` tool; a post-turn extraction step fired as a background task at the run-completed seam; everything gated by the existing inert `semantic_memory_enabled` profile flag. These questions lock down the exact seams before any code is written.

## Read these first

Three recon markdown files already exist in your workspace from earlier sessions (the harness-explained doc and the two memory-identity docs). Where they already answer a question, **quote them** and cite the file instead of rederiving from source.

## ANSWER FORMAT (mandatory — output survives OCR only if you follow this)

1. Answer every question as `Q<n>:` followed by at most 8 short lines.
2. Every code identifier (module path, class name, function name, attribute chain) goes on its **own line**.
3. Identifiers answering questions marked ★ must be printed **twice on two consecutive lines** (OCR redundancy).
4. Code quotes: max 6 lines each, only the load-bearing lines.
5. Anchor every location by **function/class name plus one short unique grep-able string** from that file. **Never use line numbers.**
6. If something is unknown or absent: write `NOT FOUND` plus one line saying where you looked. Never guess.
7. End with the GO/NO-GO table exactly as specified at the bottom.

---

## Block 1 — Persistence premise (answer these first; everything else is moot if they fail)

**Q1.** Does Postgres data survive a backend restart and a full pod restart? State whether the database is external/managed or runs inside the pod, and where its storage lives (PVC? external service? in-memory?).

**Q2.** Where does the value of `semantic_memory_enabled` actually live — a DB row, or a profile file on disk? (The profile directory is known to be emptyDir/ephemeral.) Give: (a) exact steps to flip the flag for one agent in dev, (b) whether the flipped value survives a backend restart, (c) whether it survives a pod restart.

**Q3.** Is `profile_id` stable across backend restarts and redeploys? What generates it (config file? DB row? derived at boot?)? If an agent's profile_id changes on restart, memory rows would orphan — confirm or deny this risk.

## Block 2 — Identity & scoping keys

**Q4.** ★ Confirm the per-agent scoping key: is `profile_id` the stable runtime identifier for "an agent"? Give the exact attribute chain to reach it at each of these three places: (a) inside `TurnService` while handling a turn, (b) inside a tool callable during a turn, (c) at the post-turn seam (after RESPONSE_COMPLETED in the runner).

**Q5.** Same three places as Q4: exact attribute chains for `user_id` and `tenant_id`. Also: is `thread_id` reachable at (b) the tool callable and (c) the post-turn seam?

**Q6.** (a) Postgres server major version. (b) Is `user_id` globally unique across tenants, or only unique within a tenant? (c) Do existing tables carry a `tenant_id` column — and if so, is it ever NULL in practice?

## Block 3 — Database plumbing

**Q7.** ★ (a) Exact module path where the SQLAlchemy `Base` is declared. (b) Where existing models live. (c) **Which module imports the models so `Base.metadata.create_all()` sees them** — the exact import site a new `memory/models.py` must be added to. (d) When does create_all run (app startup hook? separate script?)?

**Q8.** ★ Exact module path and name of the **async session factory** usable *outside* a request handler (e.g. `async_sessionmaker` instance). Name the ONE existing store class whose session-handling pattern a new MemoryStore should copy, and quote its session-acquisition idiom (≤6 lines).

**Q9.** We plan `asyncio.create_task(extract(...))` fired at the post-turn seam. Is there an existing background-task idiom in the codebase (fire-and-forget tasks, task supervisors)? Does anything cancel pending asyncio tasks at request teardown or shutdown that would kill such a task?

## Block 4 — Instruction assembly

**Q10.** ★ `load_instructions` in the SDK adapter: (a) exact current signature, (b) **all call sites** — in particular, do subagent runs also call it? (c) sync or async function?

**Q11.** Where exactly does `TurnService` (or whatever sits between it and the runner) hand the assembled instructions to `Runner.run_streamed`? What user/profile objects are in scope at that point? (This is our injection point: fetch memory there, pass a pre-rendered string into `load_instructions` as a new optional kwarg.)

## Block 5 — Tools

**Q12.** ★ How does a tool callable receive per-turn context — closure at build time, an SDK context parameter (e.g. `RunContextWrapper`), or something else? Show ONE existing tool that reads per-turn context (name + ≤6 quoted lines). Are tool callables `def` or `async def`? Is there any existing tool that touches the database (name it — we'll copy its pattern)?

**Q13.** ToolRegistry: (a) the registration pattern for adding a new tool group (class constant + build method — name them), (b) the default `needs_approval` posture for a newly registered tool, and whether governance/config can force approval ON for specific tools.

## Block 6 — Post-turn seam

**Q14.** ★ The exact function/method in the runner containing the RESPONSE_COMPLETED → governance audit → RUN_COMPLETED sequence. What is in scope there: final output text? the original user input? thread_id / profile / user objects? Is this code path on the client-visible stream (i.e., would an awaited slow call there delay what the user sees)?

**Q15.** For a side LLM call from harness code (our extraction step): (a) is there an existing raw model client used for internal calls — module, minimal usage, and which model names/aliases are configured? (b) If the idiomatic way is instead to run a mini SDK agent: does that path re-enter the same post-turn seam (recursion risk) and does it write thread/run/event rows? State which option you recommend and why in 2 lines.

## Block 7 — Flag & config

**Q16.** ★ Exact field path of `semantic_memory_enabled` on the profile object (e.g. `profile.features.semantic_memory_enabled`), its type and default, one example of where profile flags are read at runtime, and whether the console UI can edit it.

**Q17.** The settings/env pattern (the `AGENT_FACTORY_*` prefix): which module defines settings, and is adding one new env-backed setting a one-line change?

## Block 8 — Demo mechanics

**Q18.** A minimal **working** dev payload for `POST /api/v1/turns/stream`, including the user object and whatever auth dev mode needs (bypass token? header?). Show the JSON (≤10 lines, redact any real secret values).

**Q19.** For the demo: (a) how can we appear as **two distinct users** in dev (second test identity? forged user object in the payload?), (b) how a console session selects which agent/profile it talks to, (c) what creates a NEW thread vs continuing an existing one.

**Q20.** The exact command(s) to restart the backend on the pod, expected downtime, and whether console auth/session survives the restart.

**Q21.** Does the console transcript UI render tool calls (would an audience SEE a `save_memory` call happen)? Is there any existing surface (console or API) where the final assembled instructions or turn events can be inspected, to show the injected memory block as proof during the demo?

**Q22.** (a) Directory conventions: where should a new `memory/` package live to match the codebase layout (name the sibling package you'd put it next to)? (b) Test infra: pytest? how are tests invoked? any async-test fixtures to copy? (c) Grep for `memory`, `personalization`, `semantic_memory` outside the flag definition — does ANY memory-like execution path already exist?

---

## GO/NO-GO table (final output — exactly this shape)

| # | Seam | GO / NO-GO | One-line reason |
|---|------|------------|-----------------|
| 1 | Persistence premise (DB + flag + profile_id survive restart) | | |
| 2 | Injection via TurnService fetch + load_instructions kwarg | | |
| 3 | save_memory tool with per-turn (profile, user) context | | |
| 4 | Post-turn create_task extraction at RUN_COMPLETED seam | | |
| 5 | New tables via create_all registration | | |
| 6 | Flag gating via semantic_memory_enabled | | |
| 7 | Demo mechanics (2 users, new thread, restart, tool call visible) | | |

GO = the seam works as described in Context. NO-GO = it differs — say how in the reason column.
