# Agent Memory Prototype — Working Repo

Working repository for an **agent-level persistent memory** prototype on a multi-agent harness (FastAPI + OpenAI Agents SDK + async SQLAlchemy/Postgres). Files here are authored off-pod and reach the dev pod via `git clone` / `git pull`.

## Layout

```
memory/                       # the memory package (complete, self-contained)
  __init__.py                 #   public exports
  _digit.py                   #   THE seam file — the only file that touches harness symbols
  models.py                   #   the 2 SQLAlchemy tables
  store.py                    #   async CRUD + write hygiene (cap, fence-strip, denylist, dedup)
  recall.py                   #   build_memory_block() -> (block, count)
  tool.py                     #   the save_memory tool
  extraction.py               #   post-turn extraction
scripts/
  reset_dev_tables.py         # dev-only: drop+recreate ONLY the two memory tables
  verify_phase_a.py           # gate: prints PHASE_A: PASS|FAIL
  verify_phase_b.py           # gate: prints PHASE_B: PASS|PARTIAL|FAIL
  seed_demo.py                # demo fallback row
profiles/
  memory-demo/                # purpose-built demo agent (flag on, save_memory, gpt-5.4)
docs/
  # ── Read these ────────────────────────────────────────────────
  SHOWCASE.md                 # ★ clean, digestible overview for the team lead (Subomi)
  TECHNICAL_DEEP_DIVE.md      # ★ know-everything explainer: every file, edit, decision
  DEMO_WALKTHROUGH.md         # ★ the demo narrated step-by-step, with what you see
  DESIGN_REVIEW_AND_ROADMAP.md# ★ one-page design + roadmap for a design-review meeting
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

Open (all optional / follow-up):
- [ ] Rehearse `DEMO_RUNBOOK.md` (+ add v2 beats: semantic recall, live supersede), then demo to Subomi
- [ ] Send Subomi the requested package: `SHOWCASE.md` + `DESIGN_V2.md` + `research/INDUSTRY_PRACTICES.md`
- [ ] v2 pillar 3: consolidation into the user-model doc (designed, not yet built)
- [ ] Retention purge-job proposal (designed in DESIGN_V2 §3, needs governance input)
- [ ] Karan sync (scoping / tenant / prod-DDL / retention)
- [ ] Nice-to-haves: save-chip wording polish, learn indicator (both in `docs/INDICATORS.md`, neither needed)
