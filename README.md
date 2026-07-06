# Agent Memory Prototype — Working Repo

Working repository for an **agent-level persistent memory** prototype on a multi-agent harness (FastAPI + OpenAI Agents SDK + async SQLAlchemy/Postgres). Files here are authored off-pod and reach the dev pod via `git clone` / `git pull`.

## Layout

```
memory/                       # the drop-in package (complete, self-contained)
  _digit.py                   #   THE seam file — only file that touches harness symbols;
                              #   slots marked RECON:Qn, each with a working default
  models.py store.py recall.py tool.py extraction.py
scripts/
  reset_dev_tables.py         # dev-only: drop+recreate ONLY the two memory tables
  verify_phase_a.py           # gate: prints PHASE_A: PASS|FAIL
  verify_phase_b.py           # gate: prints PHASE_B: PASS|PARTIAL|FAIL
  seed_demo.py                # demo fallback row
docs/
  recon/ROUND_1.md            # ① run this with the recon agent first
  IMPLEMENTATION_BRIEF.md     # ② then hand this + the answers to the implementation agent
  DEMO_RUNBOOK.md             # ③ then rehearse this
  DESIGN_DRAFT.md             # design doc for team review
  research/REFERENCE_NOTES.md # source-level notes: Hermes Agent, OpenClaw, Letta, mem0
```

## The loop

1. **Recon (unlimited agent):** *"Read docs/recon/ROUND_1.md and answer all questions against this repository, following the ANSWER FORMAT rules exactly, including the final GO/NO-GO table."* Screenshot the answer.
2. **Wire & build (implementation agent):** give it the recon answer sheet + *"Read docs/IMPLEMENTATION_BRIEF.md and execute it task by task. The memory package in this repo is already written — your job is the ~6 wiring seams, the gates, and the final report in the specified format."*
3. **Demo:** follow `docs/DEMO_RUNBOOK.md`.

## Status

- [x] Reference research (4 systems, source-level)
- [x] Design draft
- [x] Recon round 1 answered — **`_digit.py` is wired against it** (Base, ToolContext identity, flag paths, safe LLM path)
- [x] Implementation brief finalized: 5 anchored harness edits + gates
- [ ] Phase A build on pod → `PHASE_A: PASS` + acceptance report
- [ ] Phase B build on pod → `PHASE_B: PASS`
- [ ] Rehearsal (DEMO_RUNBOOK) + demo
