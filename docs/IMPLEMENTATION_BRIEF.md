# Implementation Brief — Agent Memory Prototype

**You are the implementation agent on the pod, with the harness repository open.** The memory feature is **already written** in this transfer repo — your job is to **wire ~6 seams, run the gates, and report**. Do not redesign, do not refactor harness code, keep every diff minimal.

## Kickoff inputs you need

1. This repo (cloned on the pod) — package `memory/`, scripts in `scripts/`.
2. The **recon answer sheet** (answers to `docs/recon/ROUND_1.md`, Q1–Q22). Every wiring decision below is keyed to a Q-number. **If you lack the answer sheet, stop and ask the coordinator — do not guess harness symbols.**

## Non-negotiable rules

- Never log or print memory **content** — ids, counts, statuses only.
- Never `await` extraction inline on the turn path — only `schedule_extraction(...)`.
- `llm_complete` must be a raw model-client call, **never** an agent-runner/SDK-agent run (re-enters the post-turn hook → infinite loop, pollutes run/event stores).
- Touch no tables other than `agent_memory_entries` / `agent_memory_user_models`.
- Anchor every harness edit by function name + a unique existing string; if an anchor is missing, stop and report — don't hunt creatively.
- After each gate, if the gate fails twice for the same cause, stop and report rather than iterating further.

## What already exists (do not rewrite)

| File | Role |
|---|---|
| `memory/_digit.py` | **The only file you edit in this package.** Seam slots marked `RECON:Qn`, each with a working default. Flip `WIRING[...]` flags as you wire. |
| `memory/models.py` | 2 SQLAlchemy models (Column-style, 1.4/2.x compatible). |
| `memory/store.py` | add/read/discard/count + all write hygiene (cap, fence-strip, denylist, dedup). |
| `memory/recall.py` | `build_memory_block(profile_id, user_id, tenant_id)` → `str \| None`. |
| `memory/tool.py` | `TOOL_NAME`, `TOOL_DESCRIPTION`, `save_memory_impl(ctx, content, category)` — flag check inside. |
| `memory/extraction.py` | prompt, lenient parser, `extract_and_store`, `schedule_extraction`. |
| `scripts/` | `reset_dev_tables.py --yes`, `verify_phase_a.py`, `verify_phase_b.py`, `seed_demo.py`. |

## Recon answer → slot map

| Q | Slot (grep for the marker) | Action |
|---|---|---|
| Q7 | `RECON:Q7` in `_digit.py` | Import the harness `Base`; delete the fallback block; add `import memory.models` (or relocated path) at the model-registration site named in Q7c. Flip `WIRING["base"]`. *If Q7 shows no clean import site: keep the fallback Base — tables are created by `reset_dev_tables.py` instead; note it in the report.* |
| Q8 | `RECON:Q8` in `_digit.py` | Swap `get_session` to the harness async session factory **only if it's a one-liner**; the env-URL default is acceptable for the prototype. Flip `WIRING["session"]` either way once verified. |
| Q4/Q5 | `RECON:Q4/Q5` in `_digit.py` | Replace the probe chains in `get_identity` with the confirmed attribute paths for each seam's ctx object. Flip `WIRING["identity"]`. |
| Q16 | `RECON:Q16` in `_digit.py` | Replace `memory_enabled` probing with the confirmed flag path. Flip `WIRING["flag"]`. |
| Q15 | `RECON:Q15` in `_digit.py` | Implement `llm_complete` with the harness's internal model client (Phase B only). Flip `WIRING["llm"]`. |
| Q22 | package placement | Put `memory/` where Q22a says (or add repo root to the app's import path). Keep the top-level import name `memory` if collision-free; otherwise rename the folder and sed the `from memory` / `import memory` lines in `scripts/` only. |

## Tasks

### Task 1 — Place the package & create tables
- [ ] Place `memory/` per Q22a. Confirm `python -c "import memory"` works in the app's environment.
- [ ] Run: `python scripts/reset_dev_tables.py --yes` → expect `RESET: ok tables=...`
- [ ] Run: `python scripts/verify_phase_a.py` → with default (unwired) `_digit`, checks 1–7 must already pass against the dev DB. Expected: `PHASE_A: PASS` with `WIRING: base=False ...`. This proves DB plumbing before any harness edit.

### Task 2 — Wire `_digit.py` (Q7, Q8, Q4/Q5, Q16)
- [ ] Fill the four Phase-A slots per the map above; flip their `WIRING` flags.
- [ ] Re-run `verify_phase_a.py` → `PHASE_A: PASS` with the four flags `=True`.

### Task 3 — Register the `save_memory` tool (Q12/Q13)
At the tool-registry site named in Q13a, register a thin wrapper over `save_memory_impl`. Two variants — pick the one matching Q12's context mechanism:

**Variant A — SDK context parameter (e.g. RunContextWrapper):**
```python
from memory.tool import TOOL_NAME, TOOL_DESCRIPTION, save_memory_impl

async def save_memory(ctx, content: str, category: str = "note") -> str:
    return await save_memory_impl(ctx.context, content, category)
# register with function_tool(...), name=TOOL_NAME, description=TOOL_DESCRIPTION,
# needs_approval=False, following the adjacent existing tool's registration shape
```

**Variant B — closure over build-time context:**
```python
from memory.tool import TOOL_NAME, TOOL_DESCRIPTION, save_memory_impl

def build_save_memory(runtime_ctx):
    async def save_memory(content: str, category: str = "note") -> str:
        return await save_memory_impl(runtime_ctx, content, category)
    return save_memory
```
- [ ] Add the tool name to the tool-group class constant per Q13a, mirroring siblings.
- [ ] `needs_approval` explicitly false (Q13b).

### Task 4 — Inject memory pre-turn (Q10/Q11)
At the point named in Q11 (where the turn service has user + profile and instructions are assembled):

```python
from memory import _digit
from memory.recall import build_memory_block

memory_block = None
if _digit.memory_enabled(profile):                 # profile object per Q16
    ident = _digit.get_identity(turn_ctx)          # ctx object per Q4/Q5
    if ident:
        memory_block = await build_memory_block(ident.profile_id, ident.user_id, ident.tenant_id)
```
Then hand it to instruction assembly — per Q10, either:
- add kwarg `memory_block: str | None = None` to `load_instructions` and append `"\n\n" + memory_block` to its return when set (all existing callers unaffected), **or**
- if `load_instructions` is awkward (unexpected callers per Q10b), append to the assembled instructions string at the Q11 hand-off instead.
- [ ] Wire it; keep the diff to ≤10 added lines at the call site.

### Task 5 — Phase A acceptance (gate)
- [ ] Flip `semantic_memory_enabled` ON for one dev agent (Q2a), OFF for another.
- [ ] Via the API (payload per Q18) or console: user 1, flag-on agent, new thread → send `Remember: I always want answers as exactly three bullet points, addressed to me by name. Save that.` → confirm a `save_memory` tool call and a `saved` result; confirm 1 row (`source='tool'`) in `agent_memory_entries`.
- [ ] Restart backend (Q20). New thread, same agent+user → neutral question → reply is three bullets, addressed by name.
- [ ] Scoping: same question as user 2 → no personalization. Same user on flag-off agent → no injection, and a save attempt returns the decline message.
- [ ] Report Phase A (format below) **before starting Phase B**.

### Task 6 — Phase B: extraction (Q14/Q15)
- [ ] Wire `llm_complete` (Q15 slot; raw client only). Flip `WIRING["llm"]`.
- [ ] At the post-turn seam (function per Q14), after the governance audit, insert:
```python
from memory import _digit
from memory.extraction import schedule_extraction

if _digit.memory_enabled(profile):
    ident = _digit.get_identity(post_turn_ctx)
    schedule_extraction(ident, user_input_text, final_output_text)  # NOT awaited
```
(`user_input_text` / `final_output_text` from the objects Q14 says are in scope. If this turn's `save_memory` results are reachable there, pass them as `already_captured=[...]`; otherwise omit — dedup still catches repeats.)
- [ ] Run `python scripts/verify_phase_b.py` → `PHASE_B: PASS`.
- [ ] Live check: flag-on agent, new thread, say `I work on the payments reconciliation team, by the way` (no "remember") → within ~30s a `source='extraction'` row appears; a turn with pure chit-chat (`thanks, that's all!`) writes nothing.

## Fallback ladder (take the highest rung that works, report which)

1. Full build (Tasks 1–6).
2. Injection at the Q11 hand-off instead of a `load_instructions` kwarg.
3. **Phase A only** (skip Task 6) — the headline demo is fully covered; `verify_phase_b` reports PARTIAL.
4. Injection + seeded rows only (`scripts/seed_demo.py`) — if tool registration is blocked; still proves DB-backed cross-session recall.

## Report format (paste-able, one screen, no code dumps)

```
MEMORY BUILD REPORT — Phase A|A+B
WIRING: base=.. session=.. identity=.. flag=.. llm=..
PHASE_A: PASS|FAIL   PHASE_B: PASS|PARTIAL|FAIL|SKIPPED
files touched (harness): <path> (<anchor function>) x N lines
  - ...
acceptance:
  save via tool: OK|FAIL     rows source=tool: <n>
  restart + new-thread recall: OK|FAIL
  user-2 isolation: OK|FAIL  other-agent isolation: OK|FAIL
  flag-off: no injection OK|FAIL, tool declines OK|FAIL
  extraction row: OK|FAIL|SKIPPED   chit-chat writes nothing: OK|FAIL|SKIPPED
fallback rung used: 1|2|3|4
blockers/notes: <≤3 lines>
```
