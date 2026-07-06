# Recon Round 2 — Exact Code at the Edit Sites (pre-implementation)

You are the on-pod recon agent with full read access to the harness repository. Round 1 locked the architecture-level facts; this round collects the **exact code and environment details** needed to write precise diffs, plus an adversarial check of our draft plan. Quote real code — do not paraphrase logic.

## RETURN CHANNEL (read first)

Preferred: **write your full answer to a new file** `recon_round_2_answers.md` in the workspace so the coordinator can copy it out losslessly. If the answer must instead return via screenshots, follow the OCR rules from ROUND_1 (numbered `Q<n>:`, identifiers on own lines, quotes ≤10 lines — split long quotes across multiple screenshots rather than shrinking them).

## Block A — the five edit sites, verbatim

**Q1.** In `agent_factory/runtime/sdk_runner.py`, `SdkRunnerAdapter.stream_turn`: quote the contiguous segment from where instructions are obtained (the call into `_load_sdk_instructions` / `load_instructions`) through the `Runner.run_streamed(...)` call — including how `sdk_agent` and `sdk_context` are built and the exact local variable names in scope there (`profile`, `effective_request`, `thread_id`, etc.).

**Q2.** Same file: quote the **entire** `if output_event.event == EventName.RESPONSE_COMPLETED:` block verbatim, from the `if` through the `yield event(EventName.RUN_COMPLETED, ...)` line — including how `final_output` is produced and its type (str? object?), and what encloses the block (the `async for` loop header line).

**Q3.** Quote `_load_sdk_instructions` in full (signature + body).

**Q4.** In `agent_factory/runtime/sdk_adapter.py`: quote `OpenAIAgentsSdkAdapter.load_instructions` in full — we need the name of the variable it returns and where the skill index gets appended.

**Q5.** Quote `_harness_run_context` in full (the dict construction).

**Q6.** In `agent_factory/tools/registry.py`: (a) quote `_build_workspace_sdk_tools` (or the smallest complete builder) showing the exact `function_tool(...)` usage and how a needs-approval wrapper gets applied or skipped; (b) quote the place where all builders' outputs are aggregated into the final tool list (method name + the aggregation lines) and state whether `profile` is in scope there; (c) quote `register_custom_tool` in full — is it a viable alternative to a new builder?

**Q7.** Quote the code path that decides which tools get approval wrappers — specifically: could `profile.approvals.default_policy` cause a NEW tool (added via a builder or register_custom_tool) to require approval without us opting in? Answer YES/NO with the deciding lines.

## Block B — the side-LLM path, concretely

**Q8.** Quote how `SdkSubagentExecutor` (agent_factory/subagents/sdk_executor.py) constructs its `Agent` and calls `Runner.run` — every argument it passes (model, run_config, session, context). Does it pass a model explicitly or rely on a default?

**Q9.** Where is the OpenAI/SDK **client configured** at app startup (base URL, API key, Azure settings)? Name the module and quote the configuration lines (redact secret values). Would a bare `Agent(name=..., instructions=...)` + `Runner.run(agent, prompt)` from arbitrary harness code inherit that configuration, or does it need explicit client/model wiring?

**Q10.** Quote `agent_factory.config.get_model_name` in full. Can it be called with no arguments for a sensible default? What model names are configured in dev (env values, redacted as needed)?

## Block C — environment & behavior facts

**Q11.** In the dev `.env` (redact secrets): (a) is `AGENT_FACTORY_DB_CREATE_TABLES` present/truthy? (b) the exact scheme of `AGENT_FACTORY_DATABASE_URL` (`postgresql://` vs `postgresql+asyncpg://` vs other) and its query params (e.g. `ssl=require`). (c) is `AGENT_FACTORY_SESSION_DATABASE_URL` set, and what is it for?

**Q12.** Profile storage on THIS dev pod: is the profiles root a PVC mount or emptyDir here (check the deployment/manifest actually applied, or the mount at runtime, e.g. `df`/mount info for the profiles dir)? Concretely: would an edited `agent.profile.yaml` survive a **pod** restart (we know a backend-process restart is fine)?

**Q13.** Client-disconnect behavior: if the SSE client disconnects mid-stream, does `stream_turn`'s generator still execute the RESPONSE_COMPLETED block (governance audit + RUN_COMPLETED), or is the generator cancelled/GC'd? Look for how the FastAPI/SSE layer consumes the generator and any `finally`/cancellation handling. Answer with the consuming code (module + lines).

**Q14.** Console identity: in `agent-console` (e.g. `app/api/harness/chat/route.ts`), quote how the `user` object / `x-user-id` header on `/turns/stream` requests is populated. What `user_id` would a normal dev console session write?

**Q15.** Quote the full `AgentProfile.memory` schema class (all sibling fields of `semantic_memory_enabled`). Also list 2–3 existing dev profile names usable for a demo, and quote one profile's `memory:` yaml section if any profile sets one.

**Q16.** SDK sessions/history: what does `OpenAIAgentsSessionFactory.plan_session` do — where is conversation history stored (DB table? which URL?), and is history replayed to the model each turn? 5 lines of the load-bearing code. (Context: we must cleanly answer "isn't this just chat history?" in the demo.)

**Q17.** Tests: name one existing test file path; do any tests touch the DB, and how do they get a session/URL (fixture? env? skip-if-unset)?

## Block D — adversarial check (most important)

**Q18.** Open `docs/IMPLEMENTATION_BRIEF.md` and `memory/_digit.py` in this cloned transfer repo. Compare every assumption against the real code and list **every mismatch or risk**, one line each, referencing the brief's task number — wrong anchor strings, wrong variable names, a kwarg that can't thread through `_load_sdk_instructions`, a dict key that differs, an import that would be circular, an approval wrapper we missed, anything. If a task would fail as written, say exactly why. End with: `MISMATCHES: <n>`.
