# Recon Round 5 — Embedder, pgvector, and Compaction Ground Truth (for memory v2)

You are the on-pod recon agent with full read access to the harness repository **and shell access**. This round determines whether the memory system's v2 (semantic retrieval via embeddings + pgvector) is feasible in this environment, and what to build it on. Some questions require **running read-only commands** — exact commands are provided; run them as written.

**SECURITY:** Never print API keys, passwords, or full connection strings. When a command would output a secret, redact it (`***`). Read-only only — do NOT `CREATE EXTENSION`, do not INSERT/ALTER anything.

## RETURN CHANNEL

Write your full answer to `recon_round_5_answers.md` (lossless copy-out). Screenshots fallback: numbered `Q<n>:` answers, identifiers on their own lines.

## Context

Memory v1 (built, working) retrieves by recency. v2 adds: embedding-based semantic retrieval (pgvector column + an embedder), update-instead-of-duplicate writes, and compaction. We need to know: what embedder exists here, whether pgvector is available on the Azure Postgres, and how the harness's existing session compaction works (reuse candidate).

---

## Block A — The embedder

**Q1.** Grep the harness for existing embedding usage:
```
grep -rniE "embedd?ing|text-embedding" src/agent_factory --include='*.py' | grep -v test | head -40
grep -iE "embed" .env.example
grep -iE "embed" .env    # redact values, report variable NAMES only
```
Report: any existing embedding client/service/config in the harness (module + quote ≤10 lines), and any embedding-related env var names (values redacted).

**Q2.** List what deployments the Azure OpenAI resource actually serves (key/endpoint from `.env`, loaded into the shell — do not print them):
```
set -a; source .env; set +a
curl -sS "$AZURE_OPENAI_ENDPOINT/openai/deployments?api-version=2023-05-15" -H "api-key: $AZURE_OPENAI_API_KEY" | head -c 3000
curl -sS "$AZURE_OPENAI_ENDPOINT/openai/models?api-version=2024-10-21" -H "api-key: $AZURE_OPENAI_API_KEY" | head -c 3000
```
Report the deployment/model **names** returned (especially anything embedding-shaped). If both endpoints refuse (401/403/404), say so and move to Q3.

**Q3.** Probe candidate embedding deployments directly (one tiny embeddings call each — read-only inference). For each NAME in: `text-embedding-3-large`, `text-embedding-3-small`, `text-embedding-ada-002`, plus any embedding-ish names found in Q1/Q2:
```
curl -sS -o /tmp/emb.json -w "%{http_code}" \
  "$AZURE_OPENAI_ENDPOINT/openai/deployments/NAME/embeddings?api-version=2023-05-15" \
  -H "api-key: $AZURE_OPENAI_API_KEY" -H "content-type: application/json" \
  -d '{"input":"ping"}'
python3 -c "import json;d=json.load(open('/tmp/emb.json'));print('dim:',len(d['data'][0]['embedding']))" 2>/dev/null || true
```
Report per candidate: HTTP status, and for any 200 the **embedding dimension**.

---

## Block B — pgvector availability (run this verbatim)

**Q4.** Run this read-only DB probe (uses the app's own URL handling; prints no secrets):
```
cd /projects/DigitHarnessRepo/digit-agent-harness && set -a; source .env; set +a
PYTHONPATH=src python3 - <<'EOF'
import asyncio, os
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
url = os.environ["AGENT_FACTORY_DATABASE_URL"]
try:
    from agent_factory.persistence.urls import normalize_async_database_url
    url = normalize_async_database_url(url)
except Exception:
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
async def main():
    e = create_async_engine(url)
    async with e.connect() as c:
        for q in [
            "SELECT version()",
            "SELECT current_user",
            "SELECT has_database_privilege(current_user, current_database(), 'CREATE')",
            "SELECT name, default_version, installed_version FROM pg_available_extensions WHERE name = 'vector'",
            "SELECT extname, extversion FROM pg_extension",
            "SHOW azure.extensions",
            "SELECT count(*) FROM agent_memory_entries",
        ]:
            try:
                r = await c.execute(text(q))
                print(q, "=>", r.fetchall())
            except Exception as ex:
                print(q, "=> ERROR:", type(ex).__name__, str(ex)[:150])
    await e.dispose()
asyncio.run(main())
EOF
```
Report the full output. Key readings: does `pg_available_extensions` list `vector` (and installed_version)? What does `SHOW azure.extensions` say (the Azure allow-list)? Does the app user have CREATE privilege?

**Q5.** Python-side readiness:
```
pip show pgvector sqlalchemy openai 2>/dev/null | grep -E "^(Name|Version)"
```
Report versions (pgvector Python package present or not — it's the SQLAlchemy `Vector` type helper).

---

## Block C — Session compaction (reuse candidate for memory compaction)

**Q6.** The harness already compacts **chat history** (`profile.memory.compaction_enabled` / `compaction_mode: previous_response_id | input | auto`). Find and quote the load-bearing code (≤15 lines): where compaction actually happens (the session factory / SQLAlchemySession settings / any summarizer), and state plainly: does it **summarize** old messages with a model, **truncate/replay-limit** them, or delegate to an OpenAI SDK feature? Is there a reusable summarization utility a memory-compaction job could call?

---

## Block D — Small facts for the v2 design

**Q7.** Which chat models are configured for cheap side-calls (env: `AGENT_FACTORY_AGENT_SETUP_MODELS`, `AGENT_FACTORY_MEMORY_MODEL` if set) — names only.

**Q8.** Confirm from `pip show` output (Q5) or venv: SQLAlchemy major version, and whether `asyncpg` is installed.

---

## Final verdict lines (end with exactly these)

```
EMBEDDER: <deployment name + dim | NONE-FOUND>
PGVECTOR: INSTALLED | AVAILABLE-NOT-INSTALLED | ALLOWLISTED-NEEDS-ADMIN | NOT-AVAILABLE | UNKNOWN-<why>
PGVECTOR-PY: INSTALLED <ver> | NOT-INSTALLED
COMPACTION-REUSE: <one line: what exists and whether it's reusable>
```
