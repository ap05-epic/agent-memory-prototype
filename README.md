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
  recon/ROUND_3.md            # ① run this with the recon agent next (rounds 1+2 done)
  IMPLEMENTATION_BRIEF.md     # ② then hand this to the implementation agent (after round-3 slot fill)
  DEMO_RUNBOOK.md             # ③ then rehearse this
  HOW_IT_WORKS.md             # the full system explainer (present from this)
  DESIGN_DRAFT.md             # design doc for team review
  research/REFERENCE_NOTES.md # source-level notes: Hermes Agent, OpenClaw, Letta, mem0
```

## The loop

1. **Recon (unlimited agent):** *"Read docs/recon/ROUND_1.md and answer all questions against this repository, following the ANSWER FORMAT rules exactly, including the final GO/NO-GO table."* Screenshot the answer.
2. **Wire & build (implementation agent):** give it the recon answer sheet + *"Read docs/IMPLEMENTATION_BRIEF.md and execute it task by task. The memory package in this repo is already written — your job is the ~6 wiring seams, the gates, and the final report in the specified format."*
3. **Demo:** follow `docs/DEMO_RUNBOOK.md`.

## Status

- [x] Reference research (4 systems, source-level) · design draft
- [x] Recon rounds 1 + 2 answered — `_digit.py` wired, 22 adversarial findings folded in
- [x] Implementation plan approved (joint session): 3 sdk_runner insertions + custom-tool wiring + profile yaml
- [x] HOW_IT_WORKS.md explainer
- [x] Recon round 3 answered → tool wiring pinned (custom tool at app.py registration + profile `function_tools` entry); brief finalized
- [x] **Build code-complete on pod (Phase A + B):** all harness edits applied and verified, `PHASE_A: PASS` 7/7, `PHASE_B: PASS`, seam proven byte-identical when off, tool-plan scoping verified
- [x] **LIVE ACCEPTANCE PASSED end-to-end (2026-07-07):** save→row→restart→new-thread recall (3-bullet format honored), user-b isolation, test-minimal flag-off (no writes), live extraction row (`verify_phase_b` check 6 wrote=1), chit-chat writes nothing. Root cause of the earlier 401 was a **stale pod `AZURE_OPENAI_BASE_URL` overriding `.env`** — cleared at launch, no code change (see DEMO_RUNBOOK launch fix)
- [ ] Rehearse DEMO_RUNBOOK → demo to Subomi. Optional: Karan sync (scoping/tenant/prod-DDL/retention)
- [ ] Rehearsal (DEMO_RUNBOOK) + demo
