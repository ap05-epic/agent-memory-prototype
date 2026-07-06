# Agent Memory Prototype — Working Repo

Working repository for an **agent-level persistent memory** prototype on a multi-agent harness (FastAPI + OpenAI Agents SDK + async SQLAlchemy/Postgres). Files here are authored off-pod and reach the dev pod via `git clone` / `git pull`.

## Layout

```
docs/
  DESIGN_DRAFT.md            # architecture direction for team review (finalized after recon)
  research/REFERENCE_NOTES.md# source-level notes on Hermes Agent, OpenClaw, Letta, mem0
  recon/ROUND_1.md           # ← question brief for the on-pod recon agent (run this next)
```

Coming after recon round 1: `memory/` (the drop-in package with a single `_digit.py` seam file), `scripts/` (verify / reset / seed), `docs/IMPLEMENTATION_BRIEF.md` (the complete build+test plan for the implementation agent), `docs/DEMO_RUNBOOK.md`.

## How to run the recon round (on the pod)

1. `git pull` this repo onto the pod.
2. Point the recon agent (Copilot CLI) at `docs/recon/ROUND_1.md`, e.g.:
   *"Read docs/recon/ROUND_1.md and answer all questions against this repository, following the ANSWER FORMAT rules exactly, including the final GO/NO-GO table."*
3. Screenshot its full answer (the format rules make it OCR-safe) and bring it back off-pod.

## Status

- [x] Reference research (4 systems, source-level)
- [x] Design draft
- [x] Recon round 1 brief
- [ ] Recon answers → finalize design
- [ ] Scaffolding + implementation brief
- [ ] Phase A build (models · store · tool · injection) → verify gate
- [ ] Phase B build (post-turn extraction) → verify gate
- [ ] Demo runbook + rehearsal
