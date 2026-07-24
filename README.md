# Agent Memory Prototype — Working Repo

Working repository for an **agent-level persistent memory** prototype on a multi-agent harness (FastAPI + OpenAI Agents SDK + async SQLAlchemy/Postgres). Files here are authored off-pod and reach the dev pod via `git clone` / `git pull`.

## Layout

```
memory/                       # the memory package (complete, self-contained, v1+v2)
  __init__.py                 #   public exports
  _digit.py                   #   THE seam file — harness symbols, embed(), llm_complete(), BUILD marker
  models.py                   #   the 2 SQLAlchemy tables (+ v2 columns: embedding, superseded_by, observed_at)
  semantic.py                 #   v2 pure logic: cosine, relevance+recency blend, supersede decision, thresholds
  store.py                    #   async CRUD + write hygiene + the tiered smart-write gate + forget_user/metrics
  recall.py                   #   build_memory_block(query_text) -> (block, count), 3-rung degradation
  tool.py                     #   the save_memory tool (full gate incl. decider)
  extraction.py               #   post-turn extraction + the tier-3 decision call
scripts/
  reset_dev_tables.py         # dev-only: drop+recreate ONLY the two memory tables (destructive)
  upgrade_v2_columns.py       # additive v2 schema upgrade (live-table-safe)
  backfill_embeddings.py      # embed rows written while the embedder was down
  verify_phase_a.py           # gate: prints PHASE_A: PASS|FAIL
  verify_phase_b.py           # gate: prints PHASE_B: PASS|PARTIAL|FAIL
  verify_phase_c.py           # gate (v2): 12 deterministic checks, prints PHASE_C: PASS|FAIL
  seed_demo.py                # demo fallback row
profiles/
  memory-demo/                # purpose-built demo agent (flag on, save_memory, gpt-5.4)
docs/
  # ── Read these ────────────────────────────────────────────────
  ARCHITECTURE.md             # ★★ THE reference: diagrams (turn flow, write gate, data model,
                              #    outbox, identity gate, migrations) + config & failure tables
  SHOWCASE.md                 # ★ the team-lead walkthrough — simple, complete, v1+v2
  UNDERSTANDING_THE_SYSTEM.md # ★ YOUR ground-up map: concepts, message trace, the story, Q&A
  TECHNICAL_DEEP_DIVE.md      # ★ engineering reference: every file, edit, decision (v1 + v2 addendum)
  DEMO_WALKTHROUGH.md         # ★ the demo narrated step-by-step, with what you see
  DEMO_FLOWS.md               # ★ exact conversations to type (smoke test + showcase) + memory-clear commands
  TEAM_WALKTHROUGH.md         # ★ presenter's script for the team demo: beats, spoken tour, Q&A prep
  ARCHITECTURE_BREAKDOWN.md   # ★ full structured breakdown (what/architecture/data flow/safety/status) — slide-ready source material
  TEAM_DEMO_SLIDES.pptx       # ★ UBS-themed slide deck (6 slides, architecture diagrams, speaker notes)
  DESIGN_REVIEW_AND_ROADMAP.md# ★ one-page design + roadmap for a design-review meeting
  # ── Productionization (post-review program) ──────────────────
  briefs/W0_BRANCH_MIGRATION.md # gated runbook: fresh clone of current dev (two-folder), work ported as feature/agentmemory-v3
  recon/RECONCILIATION_NOTES.md # transfer repo == deployed pod state (single authoring base)
  # ── Operational / build history ───────────────────────────────
  DEMO_RUNBOOK.md             # operational demo checklist (launch commands, fallbacks)
  KNOWN_ISSUES.md             # local tool-calling loop — diagnosis, isolation steps, workaround
  INDICATORS.md               # the recall-indicator design + implementation
  IMPLEMENTATION_BRIEF.md     # the build brief handed to the implementation agent (historical)
  DESIGN_DRAFT.md             # the original pre-build design (historical)
  recon/ROUND_1..4.md         # the recon question rounds (historical)
  research/REFERENCE_NOTES.md # source-level notes: Hermes Agent, OpenClaw, Letta, mem0
```

> **Package location:** in this transfer repo the package lives at `memory/`; on the harness it is placed at `src/agent_factory/memory/` (the deep dive describes it there).

## Which doc do I want?

- **Want the whole system with diagrams?** → `docs/ARCHITECTURE.md` (start here).
- **Showing the team lead?** → `docs/SHOWCASE.md` (5-min read, honest roadmap).
- **Presenting to the team?** → `docs/TEAM_WALKTHROUGH.md` (script) + `docs/TEAM_DEMO_SLIDES.pptx`.
- **Need to understand it fully / answer any question?** → `docs/TECHNICAL_DEEP_DIVE.md`.
- **Running or watching the demo?** → `docs/DEMO_WALKTHROUGH.md` (what you see) + `docs/DEMO_RUNBOOK.md` (how to launch).

## How it was built (historical)

The prototype was built off-pod (this repo) and integrated on a remote dev pod via `git pull`, using two on-pod agents: an unlimited recon agent (GPT-5.4) that answered repo questions across four rounds (`docs/recon/`), and an implementation agent that applied the wiring from `docs/IMPLEMENTATION_BRIEF.md`. That work is **done** — see the status below.

## Status

Done:
- [x] Reference research (4 systems, source-level) · design
- [x] Recon rounds 1–4 answered; wiring pinned (custom tool at `app.py` + profile `function_tools`)
- [x] Implementation plan approved (joint session)
- [x] **Build complete on pod (Phase A + B):** all harness edits applied, `PHASE_A: PASS` 7/7, `PHASE_B: PASS`, seam byte-identical when off, tool-plan scoping verified
- [x] **Live acceptance passed end-to-end (2026-07-07):** save → row → restart → new-thread recall (3-bullet format honored) → user-b isolation → flag-off agent writes nothing → live extraction row → chit-chat writes nothing. (The earlier 401 was a stale pod `AZURE_OPENAI_BASE_URL` overriding `.env`, cleared at launch — no code change; see the DEMO_RUNBOOK launch fix.)
- [x] Purpose-built demo agent `profiles/memory-demo/` (flag on, save_memory, gpt-5.4, tool events on — no hand-edits)
- [x] **Recall indicator live (2026-07-07):** turn start emits a `run.status` "🧠 Recalled N memories" line (console renders it natively — no console changes). Verified on `memory-demo`.
- [x] Documentation: SHOWCASE, TECHNICAL_DEEP_DIVE, DEMO_WALKTHROUGH

- [x] **Memory v2 LIVE-ACCEPTED end to end (pgvector semantic recall + supersede chains):** all gates PASS on pod, live beats green — topical recall beats recency, supersede chain in DB (`superseded_by` + retired old row), post-supersede recall follows the newest preference, isolation intact. Decision floor **live-calibrated to 0.30** via the gate's telemetry (real contradiction measured top_sim=0.309 on 3-large@1536). Design: `docs/DESIGN_V2.md` · brief: `docs/IMPLEMENTATION_BRIEF_V2.md`

**Now: productionization** (Subomi's merge review → 7 workstreams, two merge milestones; branch re-based as `feature/agentmemory-v3` off current dev):
- [x] **W0 branch migration COMPLETE** — all 7 gates passed. `origin/feature/agentmemory-v3` pushed (tip `2fc2dbb`, cut from dev `7fa86f5`); one guided conflict (sdk_runner.py) resolved; package parity proven; verify scripts PASS from the new clone; live smoke on port 8081 showed `build=2026-07-16.7-reconciled` + "🧠 Recalled 4 saved memories" + reply reciting stored facts + `extraction wrote=0` negative control; old folder received zero writes. Punch list: v3 `.env` line 3 still carries the old folder's `AGENT_FACTORY_PROFILE_PATHS` (launches override it; fix during W5); console `npm install` deferred until a workstream needs the console.
**Subomi's decisions (locked):** Alembic in the harness ("memory schema is harness production infrastructure"; create_all = local/test bootstrap only, deployed envs migrate explicitly) · two merge candidates as proposed · **condition: MC1 ships memory off-by-default/demo-only; enabled persistent memory waits for MC2** (already structurally true — flag defaults false, only the test fixture enables it; make explicit in MC1 packaging + guard test).
- [x] **W5 harness-managed lifecycle COMPLETE** — commit `d68db32` on v3. Receipts: "harness session factory installed" at startup, `fallback engine created` absent from server log (in-app memory owns no engine), recall through the shared pool, side-call RunConfig parity + usage logging (SDK exposes no token counts — logged None/None by design), 3-case test slice green, the 2 repo-suite failures proven pre-existing at baseline `2fc2dbb` via throwaway worktree (dev's failures: MCP test-double `manifest_path` lag + event-journal timeout — documented, not ours).
- [x] **W1 Alembic COMPLETE** — commit `5a2956e` on v3. Receipts: baseline `5258f2433fcb` (all 11 tables incl. memory, `vector(1536)`, extension guard) verified offline then adopted on the shared dev DB via one-time stamp (single bookkeeping row = only real-DB write); `alembic check`: no new upgrade operations after scoping env.py to harness-owned tables (studio_* = another app, agent_sessions/agent_messages = SDK-owned, both deliberately unmanaged). **Finding for the team:** hand-applied unique index `ix_agent_runs_one_active_per_thread` on agent_runs exists in the DB with no owner in code — documented in MIGRATIONS.md, decision pending. create_all demoted to local/test bootstrap; 4-test no-DB slice green.
- [x] **W6 identity hardening COMPLETE** — commit `938de17` on v3. Receipts: full-identity turn under tenant `t-demo` saved + recalled with correct isolation from old default-tenant rows; tenant-less turn ran normally with exactly one "memory identity gate: disabled for turn" line and zero memory operations; off-by-default guard test enforces the MC1 condition; suite 333 passed / same 2 pre-existing failures.
- **★ MERGE-CANDIDATE 1 READY** — `docs/MC1_PACKAGE.md`: MR title+description (plain wording), findings→receipts crib sheet, Subomi message, GitLab steps. Branch `feature/agentmemory-v3` @ `938de17`.

**MC2 (production memory behavior — Subomi's list 2):**
- Round 8 recon DONE: SDK 0.17.7 accepts list input; input items NOT persisted to session history (duplication risk dead); ProfileHealthMonitor = the W4 worker template; W2 route/auth/proxy/event templates quoted; memory.recalled/learned already reserved as harness-owned UI event names.
- [x] **W4 durable extraction COMPLETE (pending push)** — outbox table as Alembic revision `6f4f8e6f7f55`, enqueue at BOTH terminal sites (incl. the structured-output path the review flagged), `MemoryExtractionWorker` on the health-monitor pattern with leased claim / session-free processing / short finalise. Receipts: worker-off enqueue → server killed → drain on boot (`processed=4 failed=0`, outbox empty) → recall recited the new memory. One transient (`agent_sessions connection is closed`) observed once and not reproducible — recorded as SDK-side (its session engine lacks `pool_pre_ping`).
- [x] **W3 injection boundary COMPLETE** — commit `8c75ac2` on v3. Recalled memory now rides the model input list as a fenced user-role item (fresh turns only; resume paths untouched); the v1 `memory_block` insertion in `build_agent` is deleted; `MemoryItemFilterSession` keeps the injected item out of stored history. Receipts: probe disproved the input-items-not-persisted assumption BEFORE any harness edit (design adapted); live 🧠 recital through the new channel; tenant-less turn produced exactly one identity-gate line; `agent_messages` zero rows containing `<user_memory>`. Bonus discovery: turns route through `control_plane/worker_router` on current dev (noted for W4).
- [ ] W2 governed APIs + audit events + retention (+ console tenant plumbing) — the last MC2 workstream
- [ ] W3 injection boundary · W4 durable extraction (outbox) · W2 governed memory APIs + retention → merge-candidate 2

Open (optional / follow-up):
- [ ] v2 pillar 3: consolidation into the user-model doc (designed, not yet built)
- [ ] Retention purge-job proposal (designed in DESIGN_V2 §3, folds into W2)
- [ ] Karan sync (scoping / tenant / prod-DDL / retention)
- [ ] Nice-to-haves: save-chip wording polish, learn indicator (both in `docs/INDICATORS.md`, neither needed)
