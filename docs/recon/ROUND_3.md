# Recon Round 3 — Tool Wiring Pin (6 questions, final round before build)

You are the on-pod recon agent with full read access to the harness repository. These six questions pin the exact mechanics of registering one custom tool. Quote real code — do not paraphrase.

## RETURN CHANNEL

Preferred: write your full answer to `recon_round_3_answers.md` in the workspace for lossless copy-out. If returning via screenshots instead: numbered `Q<n>:` answers, identifiers on their own lines, quotes ≤10 lines each.

## Questions

**Q1.** In `agent_factory/tools/registry.py`: quote the code that produces `plan.resolved` (the `plan_tools` method or equivalent, full body if ≤40 lines, else the resolution logic). Specifically: a profile lists tool names somewhere — where in the profile schema (`tools:`? another key?) — and what happens to a listed name that is NOT in any built-in known set: does it survive into `plan.resolved` (so `_resolve_custom_tool` can pick it up), get dropped, or raise?

**Q2.** Where is `ToolRegistry` constructed at app wiring? Name the module (e.g. in `create_app` or a runtime setup module) and quote the construction call with its arguments. Is `register_custom_tool` called anywhere today (grep the repo, including tests) — if yes, quote one usage; if no, state NOT FOUND.

**Q3.** Quote `tests/fixtures/profiles/test-full/agent.profile.yaml` — the `tools:` section verbatim (or however tool names are listed), plus 3 lines of surrounding structure so the exact yaml shape is unambiguous.

**Q4.** Quote `_resolve_custom_tool` in full.

**Q5.** Quote the exact import line(s) through which `build_sdk_tools` obtains `function_tool` and `ToolContext`. Is `function_tool` the OpenAI Agents SDK's own, or a local wrapper (its use of a `needs_approval=` kwarg suggests a wrapper)? If local, name the module and quote the wrapper's signature only.

**Q6.** In `build_sdk_tools`' aggregation: are custom tools (from `_resolve_custom_tool`) appended raw or wrapped in `tool_namespace(...)`? Quote the appending lines. Also quote `tool_namespace`'s signature — any reason a group with a single tool would behave differently?

End with one line: `TOOL_PATH: CUSTOM-OK` if (a) an unknown profile-listed name survives into `plan.resolved` AND (b) there is a reachable place to call `register_custom_tool` at wiring — otherwise `TOOL_PATH: BUILDER-NEEDED` plus one line why.
