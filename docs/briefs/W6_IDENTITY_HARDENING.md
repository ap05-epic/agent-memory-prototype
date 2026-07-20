# W6 — Identity Hardening: memory requires a validated user + tenant

**Review finding:** memory operates on loosely-validated identity — the harness paths default `tenant_id` to `"default"` and only require a `user_id`-shaped string. **Target:** memory (recall, tool saves, extraction) operates ONLY when the turn carries a validated user **and** tenant; otherwise memory is disabled for that turn, fail-closed, with one content-free telemetry line. No more `"default"` tenant writes from harness paths.

**Where:** `/projects/DigitHarnessRepo/digit-agent-harness-v3`, branch `feature/agentmemory-v3`, AFTER W1 is committed. Same rules: old folder read-only, port 8081, PID-scoped kills only, no force-push, no `reset_dev_tables.py`, stop at every GATE.

**Design (locked off-pod, round-7-anchored):** one tiny predicate in `security.py`, applied at the three memory insertion points in `sdk_runner.py`. The tool path needs no logic of its own — gating the `memory_enabled` context entry gates the tool automatically. The `_digit` seam keeps its permissive defaults for standalone scripts; the harness paths simply stop using them.

**A consequence to understand (and report, not "fix"):** the console does not send a tenant today, so on this branch console-driven turns will run with memory silently disabled until tenant plumbing lands in MC2. That is aligned with the team lead's MC1 condition (memory off by default / demo-only; the old folder keeps demoing unaffected). Existing dev-DB rows with tenant `"default"` stay readable only to `"default"`-tenant callers — that's scoping working, not data loss.

## GATE 0 — read-first (report, wait)

1. `git status --short` clean (restore `next-env.d.ts` if it reappears); HEAD = the W1 commit or descendant; branch `feature/agentmemory-v3`.
2. Quote the three memory insertion sites in `runtime/sdk_runner.py` AS THEY ARE NOW (recall block ~line 156, extraction block ~line 383, `"memory_enabled"` entry ~line 1334) with 3 lines of context each.
3. Quote the `_harness_run_context` dict construction in full (which keys exist — round 1 said profile_id/user_id/thread_id/run_id, NO tenant).
4. Quote `default_profile_paths()` (or equivalent) — where non-test profiles live, for the guard test in Task 4.
5. Confirm `enforce_profile_access` still sits in `src/agent_factory/security.py` with the single call site in `turn_service._build_prepared_turn`.

## Task 1 — the predicate (`src/agent_factory/security.py`)

Add below `enforce_profile_access`:

```python
def memory_identity_ok(user) -> bool:
    """Agent memory operates only for a validated user AND tenant scope
    (memory review: identity hardening). Fail-closed: missing identity means
    memory is disabled for the turn, never mis-keyed rows."""
    return bool(user is not None and getattr(user, "user_id", None) and getattr(user, "tenant_id", None))
```

## Task 2 — apply at the three sites (`runtime/sdk_runner.py`)

Import `memory_identity_ok` alongside the existing `security` imports.

1. **Recall block:** condition becomes flag AND `memory_identity_ok(_user)`. When the flag is on but identity fails, log once:
   `_digit-style log or the module's logger: "memory identity gate: disabled for turn (missing user or tenant) profile=%s"` — use the `agent_memory` logger via the lazy import that already exists in that block so the line lands in the same log stream. Pass `_user.tenant_id` directly to `build_memory_block` — delete the `or "default"` fallback.
2. **Extraction block:** same condition change; `Identity(profile.profile_id, _user.user_id, _user.tenant_id, thread_id)` — no `"default"` fallback. If the identity gate already logged for this turn in the recall block, do not log a second line (a simple local flag is fine).
3. **Context entry:** `"memory_enabled": bool(profile.memory.semantic_memory_enabled) and memory_identity_ok(_user_for_ctx)` — and ADD `"tenant_id": getattr(_user_for_ctx, "tenant_id", None)` to the context dict (use however the user object is reachable where `_harness_run_context` is built; GATE 0 item 3 tells you). `_digit.get_identity` already reads a `tenant_id` key — no seam change needed. Known-acceptable wording quirk: when identity-blocked, `save_memory` returns the existing "Memory is not enabled for this agent" decline; do not add new strings.

`_digit.py`: bump `BUILD = "2026-07-20.9-w6-identity-gate"`. No other seam changes — the dataclass defaults stay for standalone scripts.

## Task 3 — tests (`tests/test_agent_memory_identity.py`)

Plain pytest, `asyncio.run` where needed, following the W5 file's style:

1. `memory_identity_ok` truth table: None user; user_id only; tenant_id only; both → True.
2. Context gating: build the context the way `_harness_run_context` does (call it directly if importable with a stub profile/user, else construct equivalently) and assert `memory_enabled` is False when tenant is missing even with the profile flag on, and `tenant_id` is present in the dict when supplied.
3. **The off-by-default guard (MC1 condition, team-lead requirement):** iterate every `agent.profile.yaml` under the non-test profile paths from GATE 0 item 4; assert none sets `semantic_memory_enabled: true`. (The demo fixture under `tests/fixtures/` is exempt by construction.) This test is the merge-request receipt for "memory stays off by default."

## GATE A — static + tests

`python3 -m py_compile` on touched files; run the new test file; run the repo suite — expectation unchanged: the two documented pre-existing failures (`test_turn_stream_custom_mcp_reaches_sdk_agent`, `test_turn_service_immediate_stream_does_not_block_on_event_journal`) and nothing else newly failing.

## GATE B — live proof (port 8081, two curls)

Launch as in W5 GATE B. Require marker `build=2026-07-20.9-w6-identity-gate`, then:

1. **Turn A (full identity):** curl a turn to `memory-demo` with `user: {user_id: "console-user", tenant_id: "t-demo"}`, input "Remember: my favorite color is teal." Then a NEW thread, same identity, "What do you remember about me?" — require: a `memory gate:`/`memory add` log for the save, and the recall turn recites teal (fresh tenant scope starts empty — recalling the new fact IS the proof the full cycle works under a real tenant; the old `default`-tenant memories correctly do NOT appear).
2. **Turn B (no tenant):** same curl shape but user has only `user_id`, input "Remember: my favorite color is crimson." Require: response completes normally, the log shows `memory identity gate: disabled for turn`, and NO `memory add`/`memory gate:`/extraction lines for this turn.
3. Quote all log lines for both turns. Stop the server by its exact PID.

## GATE C — commit + push

```
memory: require validated user + tenant for all memory operation

Adds security.memory_identity_ok and applies it at the three memory
integration points in the runner: recall, post-turn extraction, and the
tool-enabling context entry (which gates save_memory with no tool-side
change). Harness paths no longer default the tenant — the run context now
carries the caller's real tenant_id and memory is disabled fail-closed,
with one content-free log line, when user or tenant is missing. Adds an
identity test slice plus the off-by-default guard test asserting no
non-test profile enables semantic memory (merge-candidate condition).
Console turns carry no tenant yet, so on this branch console-driven memory
stays disabled until the MC2 tenant plumbing — consistent with keeping
memory demo-only until MC2.
```

Plain `git push`. Final report: SHAs, gate outcomes, quoted receipts.

## Rollback

Uncommitted: `git checkout -- <files>`. Committed-but-wrong: report and stop. Old folder untouched throughout.

## Report format

```
GATE <x>: PASS or FAIL
<KEY>: <value>
NEXT: waiting for human
```
