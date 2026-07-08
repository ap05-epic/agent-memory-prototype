# Known Issues — Local Tool-Calling Loop

## Symptom

Locally, agents get **stuck in a loop on tool calls** — the turn never reaches `run.completed`, the model appears to keep re-issuing the same tool call, and messages never finish. Reported across agents.

## Important context (this narrows it)

Tool calling **has worked** in this exact environment: on 2026-07-07, `memory-demo`'s `save_memory` executed cleanly (`tool.started` → `tool.completed` → `run.completed`). So tool calls are **not** fundamentally broken — this is a **configuration or tool-compatibility** problem, and there is a known-good recipe to fall back to (bottom of this doc).

A tool-call loop almost always means the **tool-call → tool-result round-trip is failing**: the model emits a tool call, but the result never gets appended back to the conversation in a form the model accepts, so it thinks the tool wasn't answered and calls it again — until `max_turns` (20–30) is hit. The job is to find *why* the round-trip breaks.

## Likely causes, ranked (with how to check + fix)

### 1. Wrong API mode (Responses vs Chat Completions) — check this first
The harness's built-in namespaced tools (`artifact.*`, `workspace.*`, `subagent.*`) require the **Responses** API. On **Chat Completions**, the SDK rejects those tools outright, and tool-calling round-trips behave differently on Azure.
- **Check:** `echo $OPENAI_AGENTS_API` and grep the startup log for the API mode. Default is `responses` unless something set `chat_completions`.
- **Fix:** ensure Responses mode: `unset OPENAI_AGENTS_API` (defaults to `responses`) or `export OPENAI_AGENTS_API=responses`, then restart.

### 2. Stale pod env → wrong endpoint (the same trap that caused the earlier 401)
If the launch fix isn't applied, the app uses the pod's ambient `AZURE_OPENAI_BASE_URL` (a *different* Azure resource) instead of `.env`, so every model+tool round-trip hits the wrong endpoint and fails → the model retries → loop.
- **Check:** grep the startup log for the resolved `OPENAI_BASE_URL` — it must be the `digit-dev-cog-ai` endpoint from `.env`, NOT `acaeus2...`.
- **Fix:** always launch with `unset AZURE_OPENAI_BASE_URL OPENAI_BASE_URL OPENAI_API_KEY OPENAI_AGENTS_API` then export the `.env` key/endpoint (see `DEMO_RUNBOOK.md` launch fix).

### 3. Model/deployment doesn't support tool-calling in the active mode
If a profile's `model.default` names a deployment that doesn't exist on the resource (e.g. `gpt-5.5` when the resource serves `gpt-5.4`) or doesn't support function calling in the active API mode, tool calls fail → loop.
- **Check:** the profile's `model.default` vs `AZURE_OPENAI_MODEL` in `.env`.
- **Fix:** align to the deployment that actually serves — `gpt-5.4` on this endpoint.

### 4. Azure's Responses-API tool-calling support (a genuine platform tension — raise this)
The harness's own `config.py` warns: *"Azure OpenAI endpoints may not support the Responses API; default to chat_completions unless explicitly overridden."* But the harness's tools **need** Responses. If Azure's Responses implementation mishandles the tool-call/tool-result round-trip for this deployment, **every** tool-using agent loops. This is a platform-level question, not something the memory work introduced.
- **Check:** does the minimal repro (below) loop even with a single simple tool on Responses?
- **Fix / action:** raise with the platform team (question drafted below); workaround = the known-good recipe.

### 5. A tool itself erroring (less likely if "all agents" loop)
A tool that throws (e.g. a workspace tool that isn't configured → `ToolRegistryError`) returns an error result that the model retries.
- **Check:** read the server log during a loop — is there a tool exception, or the same tool call repeating with no result?

## Isolation ladder (do this to pinpoint it — one variable at a time)

1. **No-tool agent, simple prompt.** Does it reach `run.completed`? If **no** → the problem is upstream of tools (endpoint/mode/deployment — causes 1–3). If **yes** → tools are involved, continue.
2. **`memory-demo` (one custom tool, `save_memory`).** Does it complete? This is the known-good recipe. If **yes** → your looping agents differ by their tools (likely the namespaced built-ins — cause 4). If **no** → the environment regressed since 2026-07-07 (re-check causes 1–3, especially the launch fix).
3. **An agent with one namespaced built-in tool (`artifact.read`).** Does it loop while `memory-demo` doesn't? → strongly points to cause 4 (Azure + namespaced-tool round-trip).
4. **Read the server log during a loop.** Same tool call repeating? A tool error? Hitting `max_turns`? Capture 20 lines — that log is the single most useful piece of evidence.

## Known-good recipe (works today — fall back to this)

Responses mode + the `digit-dev-cog-ai` endpoint + the launch fix + a profile whose tools are compatible (`memory-demo` uses only `save_memory`, a raw custom tool — no namespaced built-ins). This is the exact configuration that completed tool calls cleanly on 2026-07-07, and it's what the Friday memory walkthrough uses — so **the memory demo is not blocked by this issue.**

## Question to raise with the platform team

> On the local dev pod, agents with the built-in namespaced tools (`artifact.*` / `workspace.*` / `subagent.*`) loop on tool calls and never reach `run.completed` against our Azure endpoint. The harness needs the Responses API for those tools, but `config.py` notes Azure may not fully support Responses. **What's the supported local configuration for tool-using agents — which Azure deployment + API mode is known to round-trip tool calls correctly?** (Raw custom tools like our `save_memory` do complete on Responses, so this seems specific to the namespaced tools / Azure Responses support.)
