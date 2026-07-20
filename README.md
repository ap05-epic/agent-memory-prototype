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
  SHOWCASE.md                 # ★ the team-lead walkthrough — simple, complete, v1+v2
  UNDERSTANDING_THE_SYSTEM.md # ★ YOUR ground-up map: concepts, message trace, the story, Q&A
  TECHNICAL_DEEP_DIVE.md      # ★ engineering reference: every file, edit, decision (v1 + v2 addendum)
  DEMO_WALKTHROUGH.md         # ★ the demo narrated step-by-step, with what you see
  DEMO_FLOWS.md               # ★ exact conversations to type (smoke test + showcase) + memory-clear commands
  TEAM_WALKTHROUGH.md         # ★ presenter's script for the team demo: beats, spoken tour, Q&A prep
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

- **Showing the team lead?** → `docs/SHOWCASE.md` (5-min read, diagrams, honest roadmap).
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
- [ ] W1 Alembic — **brief ready**: `docs/briefs/W1_ALEMBIC_DEPLOYMENT.md` (full-schema baseline revision incl. memory tables, stamp-adopt dev DB, alembic check receipt, MIGRATIONS.md, create_all demoted; run after W5)
- [ ] W6 identity hardening — **brief ready**: `docs/briefs/W6_IDENTITY_HARDENING.md` (memory_identity_ok predicate at the three runner sites; no default-tenant writes; off-by-default guard test = the MC1 condition receipt; run after W1) → completes merge-candidate 1
- [ ] W3 injection boundary · W4 durable extraction (outbox) · W2 governed memory APIs + retention → merge-candidate 2

Open (optional / follow-up):
- [ ] v2 pillar 3: consolidation into the user-model doc (designed, not yet built)
- [ ] Retention purge-job proposal (designed in DESIGN_V2 §3, folds into W2)
- [ ] Karan sync (scoping / tenant / prod-DDL / retention)
- [ ] Nice-to-haves: save-chip wording polish, learn indicator (both in `docs/INDICATORS.md`, neither needed)
