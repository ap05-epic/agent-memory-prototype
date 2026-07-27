# W8 — Console Tenant Plumbing: memory works in the browser

**The gap.** Memory requires a validated user **and** tenant (the identity hardening). The console sends a user but no tenant, so every console turn hits the identity gate and memory silently does nothing. Everything works through curl; nothing works in the UI. This is the last functional gap in the feature.

**What "done" means:** a turn driven from the console recalls and saves memory exactly as a curl turn does, and the memory endpoints can be called from the console's own proxy layer with the caller's tenant attached.

**Where:** `/projects/DigitHarnessRepo/digit-agent-harness-v3`, branch `feature/agentmemory-v3` (HEAD `db438c46` or descendant). Standard rules: old folder read-only; port 8081; PID-scoped kills; never force-push; DB-writing or pushing commands run strictly alone; restore `agent-console/next-env.d.ts` if it appears; stop at every GATE.

**New wrinkle for this workstream:** it touches the console, which needs its dependencies installed (`npm install` under `agent-console/`) — deferred since W0, so budget time for it. Node work is verified by driving the UI, not just by compiling.

## GATE 0 — read-first (report, then wait)

1. `git status --short` clean; HEAD correct; `npm --version` and `node --version` reported.
2. **How a turn is built today.** In `agent-console/`, find where a chat turn is POSTed to the harness. Quote the request construction verbatim (≤30 lines): the URL, headers, and the JSON body — specifically how the `user` object is populated and where `user_id` / `x-user-email` comes from.
3. **Where config comes from.** Quote how the console reads environment/config today (a `.env.local`, `next.config`, a server-side config module) and give one example of an existing value flowing from config into a request.
4. **The proxy layer.** Quote one existing route under `agent-console/app/api/harness/...` in full — how it forwards headers and body to the harness.
5. **Does any tenant concept exist already?** `grep -rni "tenant" agent-console/ --include=*.ts --include=*.tsx | head -30`. Report hits or state NONE.
6. Confirm the harness side: quote the `UserContext` fields accepted on a turn request, and the `_caller_tenant_id` helper in `api/app.py` (header names it reads).

## Design (state it in the report before implementing)

**Where the tenant comes from.** For a dev console there is no per-user tenant claim to read, so it is **configuration**: a single tenant value for the deployment, read server-side, defaulting to nothing rather than to a guessed string. If it is unset, the console behaves exactly as it does today — memory stays off — which keeps the fail-closed posture intact.

- Server-side env var: `DIGIT_CONSOLE_TENANT_ID` (not `NEXT_PUBLIC_*` — it must not be settable from the browser).
- Turn requests include it as `user.tenant_id` in the JSON body, alongside the existing `user_id`.
- Proxy routes to the memory endpoints forward it as the `x-tenant-id` header.
- If the variable is unset: send nothing, log nothing, change nothing.

**Why not derive it from the signed-in user:** that is the right answer once the console has real auth claims, and this design does not block it — swapping a config read for a claim read is a one-line change at a single site. Note that in the report as the upgrade path.

## Task 1 — config surface

Add `DIGIT_CONSOLE_TENANT_ID` to the console's server-side config in the same style as existing values (per GATE 0 item 3), plus an entry in whatever `.env.example` the console has. Do **not** expose it to the browser bundle.

## Task 2 — turn requests carry the tenant

At the turn-construction site from GATE 0 item 2, include `tenant_id` in the `user` object when the config value is present. Keep everything else identical. If the console constructs turns in more than one place (chat, resume, retry), cover all of them and list each in the report.

## Task 3 — memory API proxy routes

Add proxy routes under `agent-console/app/api/harness/memory/...` mirroring the existing proxy pattern exactly, forwarding `x-user-id` (as the existing routes derive it) and `x-tenant-id`:

| Console route | Harness endpoint |
|---|---|
| `GET /api/harness/memory` | `GET /api/v1/memory` |
| `GET /api/harness/memory/status` | `GET /api/v1/memory/status` |
| `DELETE /api/harness/memory/[entryId]` | `DELETE /api/v1/memory/{entry_id}` |
| `POST /api/harness/memory/forget` | `POST /api/v1/memory/forget` |
| `POST /api/harness/memory/disable` | `POST /api/v1/memory/disable` |
| `POST /api/harness/memory/enable` | `POST /api/v1/memory/enable` |

**No UI in this brief.** Routes only — a memory management screen is a separate piece of work with its own design questions.

## Task 4 — tests

Follow whatever test convention the console already uses (report it at GATE 0; if it has none, say so and skip rather than inventing a framework). On the harness side, add one test asserting a turn request carrying `user.tenant_id` produces a run context with that tenant — mirroring the existing identity tests.

## GATE A — static + tests

`npm run build` (or the console's equivalent) succeeds; the harness suite still shows **465 passed, 0 failed**; any new tests pass.

## GATE B — live proof, the one that matters

Launch the harness on 8081 with `DIGIT_CONSOLE_TENANT_ID` set for the console, start the console, and drive it **through the browser**:

1. Say "Remember: I take the stairs, not the lift." Confirm the `save_memory` tool call renders and a `memory add` line appears in the harness log.
2. Open a **new thread** and ask what the agent remembers. Require the 🧠 indicator and a reply reciting the fact — **from the UI, not curl**. This is the moment the feature becomes real for a user.
3. Check the harness log for that turn: there must be **no** `memory identity gate: disabled for turn` line.
4. Unset `DIGIT_CONSOLE_TENANT_ID`, restart the console, run one more turn: memory goes quiet again and the gate line returns. This proves the fail-closed posture survived.
5. Call one proxy route (`GET /api/harness/memory`) and quote the response.
6. Stop both servers by their exact PIDs.

## GATE C — commit + push (plain wording)

```
console: send the caller's tenant so memory works in the UI

Memory requires a validated user and tenant, and the console only sent a
user, so every console turn hit the identity gate and memory did nothing.
The console now reads a server-side tenant value from configuration and
includes it as user.tenant_id on turn requests, and adds proxy routes for
the memory endpoints that forward the caller's user and tenant headers.

The value is configuration rather than a user claim because the console
has no tenant claim to read yet; swapping the config read for a claim is
a one-line change at a single site when it does. If the value is unset
the console behaves exactly as before and memory stays off, so the
fail-closed posture is unchanged.

Verified in the browser: a turn saved a memory, a new thread recalled it
with the indicator, and unsetting the value returned the identity gate to
silence.
```

## Rollback

Uncommitted: `git checkout -- <files>`. The console changes are additive and gated on a config value that defaults to unset, so the worst case with them present but unconfigured is today's behaviour.

## Report format

```
GATE <x>: PASS or FAIL
<KEY>: <value>
NEXT: waiting for human
```
