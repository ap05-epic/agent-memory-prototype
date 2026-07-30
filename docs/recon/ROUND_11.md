# Recon Round 11 — the two blocks round 10 could not answer

**READ-ONLY except for one thing**, called out explicitly in Part 2: the latency probe inserts a handful of rows into `agent_memory_entries` under a dedicated probe scope (`user_id=latency-probe@ubs.com`, `tenant_id=t-latency`). Nothing else is written, no schema changes, no other scope touched. Everything in Part 1 is pure reads.

Run inside `/projects/DigitHarnessRepo/digit-agent-harness-v3` on `feature/agentmemory-v3`. Write the answer to `recon_round_11_answers.md` as flat text.

**Why this round exists.** Round 10 answered almost everything, but two blocks did not survive review:

- **Block F was never executed.** The report said the database questions "were not present in the retrieved top portion" — the file was read partially, so the block was skipped rather than answered. It is reproduced here in full, at the top, with nothing above it.
- **Block H measured the wrong thing.** It reported `embed median 0.115 ms`. A real HTTPS call to Azure OpenAI cannot complete in a tenth of a millisecond; that number is the *failure* path, where `_digit.embed` catches an exception and returns `None`. Every downstream number inherited the error: the "total" measured the recency fallback, not semantic recall. The live turn comparison was also unusable — both turns took 55–65 s (the model dominates), the delta came out negative, and both replies said the user had no saved preferences, meaning the scope was empty and no recall happened at all.

So Part 2 below **refuses to measure anything until it has proved the embedder works and the scope has memories**. If either precondition fails, it stops and says so. A stopped probe is a useful result; an invented number is not.

---

# Part 1 — Where the data actually lives

Answer every numbered item. `CONFIRMED` plus quoted evidence, or the real value.

**1. Connection facts.** From the harness `.env`, report from `AGENT_FACTORY_DATABASE_URL`: the **host**, **port**, **database name**, and **user**. **Mask the password completely** — write `***` where it appears, and do not paste the raw URL. Also state whether `AGENT_FACTORY_SESSION_DATABASE_URL` is set, and whether it points somewhere different.

**2. Server identity.** Source the `.env`, then run these read-only queries and paste the output verbatim:

    SELECT version();
    SELECT current_database(), current_user;
    SELECT name, setting FROM pg_settings
     WHERE name IN ('server_version','max_connections','shared_buffers','TimeZone');
    SELECT extname, extversion FROM pg_extension;

**3. What memory actually occupies.**

    SELECT relname,
           pg_size_pretty(pg_total_relation_size(relid)) AS total_size,
           n_live_tup AS approx_rows
      FROM pg_stat_user_tables
     WHERE relname LIKE 'agent_memory%'
     ORDER BY relname;

Then the same for the harness's own tables, so the relative footprint is visible:

    SELECT relname,
           pg_size_pretty(pg_total_relation_size(relid)) AS total_size,
           n_live_tup AS approx_rows
      FROM pg_stat_user_tables
     WHERE relname NOT LIKE 'agent_memory%'
     ORDER BY pg_total_relation_size(relid) DESC
     LIMIT 15;

Also the whole-database size: `SELECT pg_size_pretty(pg_database_size(current_database()));`

**4. Is this server shared?**

    SELECT datname FROM pg_database ORDER BY 1;
    SELECT schemaname, count(*) FROM pg_tables GROUP BY 1 ORDER BY 1;

Report what else lives on this server besides our database.

**5. Azure provisioning — only if genuinely reachable.** Run `az --version`. If the CLI is missing or not authenticated, write exactly `AZURE: az unavailable` and **move on** — do not guess, do not infer a subscription from the hostname. If it *is* available and authenticated, run `az postgres flexible-server list -o table`, and for the server matching the host from item 1, `az postgres flexible-server show -n <name> -g <group>`; report subscription id, resource group, region, tier/SKU, storage size, and backup retention.

---

# Part 2 — Latency, measured properly

## 2a. The preconditions (this is the part that failed last time)

Set up the environment exactly as a normal launch does — this matters, because the previous run almost certainly ran without credentials loaded:

    cd /projects/DigitHarnessRepo/digit-agent-harness-v3
    unset AZURE_OPENAI_BASE_URL OPENAI_API_KEY OPENAI_BASE_URL
    set -a && . ./.env && set +a
    export AGENT_FACTORY_MEMORY_PGVECTOR=1
    export AGENT_FACTORY_MEMORY_EMBED_MODEL=text-embedding-3-large
    export AGENT_FACTORY_MEMORY_EMBED_DIM=1536
    export AGENT_FACTORY_MEMORY_MODEL=gpt-5.4-mini

Then write `/tmp/latency_probe.py` with exactly the content below and run it with `PYTHONPATH=src python3 /tmp/latency_probe.py`. Paste its **entire** output.

The script gates itself: it will not time anything until a real embedding has come back with the right dimension, and it will not report recall numbers against an empty scope. If it prints `PRECONDITION FAIL`, that is the finding — report it and stop; do not work around it.

```
import asyncio, statistics, sys, time
sys.path.insert(0, "src")

from agent_factory.memory import _digit, recall, semantic, store

PROFILE = "memory-demo"
USER    = "latency-probe@ubs.com"
TENANT  = "t-latency"
QUERY   = "What do you know about how I like my updates written?"

SEED = [
    "Prefers concise written updates with the conclusion stated first",
    "Works on the DIGIT agent engineering team",
    "Uses Postgres with pgvector for embedding storage",
    "Prefers dark mode in every tool that offers it",
    "Reviews merge requests in the morning before standup",
    "Based in the Raleigh office",
    "Prefers Python over Java for prototypes",
    "Runs the harness locally on port 8081",
]

def stats(label, samples_ms):
    lo  = min(samples_ms)
    mid = statistics.median(samples_ms)
    hi  = max(samples_ms)
    print("%-28s min=%8.1f  median=%8.1f  max=%8.1f  (n=%d)"
          % (label, lo, mid, hi, len(samples_ms)))
    return mid

async def timed(fn, n=5):
    out = []
    for _ in range(n):
        t0 = time.perf_counter()
        await fn()
        out.append((time.perf_counter() - t0) * 1000.0)
    return out

async def main():
    print("=== PRECONDITIONS ===")

    # 1. The embedder must actually work. This is the check that was missing.
    vecs = await _digit.embed(["a representative user message"])
    if not vecs or not vecs[0]:
        print("PRECONDITION FAIL: _digit.embed returned", repr(vecs))
        print("The embedder is not reachable - credentials or endpoint.")
        print("STOPPING. Any timing from here would measure the failure path.")
        return
    dim = len(vecs[0])
    print("embed returned 1 vector, dim=%d, first 3 = %r" % (dim, vecs[0][:3]))
    if dim != 1536:
        print("PRECONDITION FAIL: expected dim 1536, got %d" % dim)
        return

    # 2. The scope must have memories, or recall measures the empty path.
    existing = await store.candidate_entries(PROFILE, USER, tenant_id=TENANT, limit=100)
    print("scope %s / %s / %s has %d live entries" % (PROFILE, USER, TENANT, len(existing)))
    if len(existing) < len(SEED):
        print("seeding probe scope ...")
        for i, text in enumerate(SEED):
            r = await store.add_entry(PROFILE, USER, text,
                                      category="preference", source="probe",
                                      tenant_id=TENANT)
            print("  seed %d: %s" % (i, r))
        existing = await store.candidate_entries(PROFILE, USER, tenant_id=TENANT, limit=100)
        print("scope now has %d live entries" % len(existing))
    if not existing:
        print("PRECONDITION FAIL: scope still empty after seeding.")
        return

    print("PRECONDITIONS OK")
    print()
    print("=== RECALL PATH (5 runs each) ===")

    qvec = (await _digit.embed([QUERY]))[0]

    m_embed = stats("embed(query)",
                    await timed(lambda: _digit.embed([QUERY])))
    m_fetch = stats("store.candidate_entries",
                    await timed(lambda: store.candidate_entries(
                        PROFILE, USER, tenant_id=TENANT, query_vec=qvec)))

    cands = await store.candidate_entries(PROFILE, USER, tenant_id=TENANT, query_vec=qvec)

    rank_ms = []
    for _ in range(5):
        t0 = time.perf_counter()
        semantic.select_for_recall(cands, qvec, recall.INJECT_LIMIT)
        rank_ms.append((time.perf_counter() - t0) * 1000.0)
    m_rank = stats("semantic.select_for_recall", rank_ms)

    m_total = stats("recall.build_memory_block",
                    await timed(lambda: recall.build_memory_block(
                        PROFILE, USER, tenant_id=TENANT, query_text=QUERY)))

    block, count = await recall.build_memory_block(
        PROFILE, USER, tenant_id=TENANT, query_text=QUERY)
    print()
    print("block is None?   %s" % (block is None))
    print("memories in block: %d" % count)
    print("block chars:       %d" % (len(block) if block else 0))
    if block:
        print("--- block begins ---")
        print(block)
        print("--- block ends ---")

    print()
    print("=== WRITE PATH ===")
    write_ms = []
    for i in range(5):
        t0 = time.perf_counter()
        action, _sup = await store.smart_add_entry(
            PROFILE, USER, "Probe fact number %d about scheduling" % i,
            category="note", source="probe", tenant_id=TENANT, decide=None)
        write_ms.append((time.perf_counter() - t0) * 1000.0)
        print("  run %d -> %s" % (i, action))
    m_write = stats("smart_add_entry(decide=None)", write_ms)

    prompt = semantic.render_decision_prompt(
        "Prefers concise written updates",
        [e.content for e in existing[:5]])
    m_llm = stats("llm_complete(decision prompt)",
                  await timed(lambda: _digit.llm_complete(prompt), n=3))

    print()
    print("=== SUMMARY (medians, ms) ===")
    print("embed              %8.1f" % m_embed)
    print("db fetch           %8.1f" % m_fetch)
    print("rank in python     %8.1f" % m_rank)
    print("recall end to end  %8.1f" % m_total)
    print("write, no decider  %8.1f" % m_write)
    print("adjudication call  %8.1f" % m_llm)

asyncio.run(main())
```

**If the script prints `PRECONDITION FAIL`:** report the exact message and stop Part 2b. Do not substitute estimates.

## 2b. The same thing during a real turn

Round 10 tried to measure this by timing two whole turns with `curl` and subtracting. That cannot work — the model takes 55–65 s and varies by seconds between runs, so a 200 ms difference is far below the noise. Use the harness's own instrumentation instead.

**6.** Round 10 found that timing instrumentation is enabled by `request.metadata["debug_timing"]`. Quote the code that reads it and the code that emits the timing lines (file and line numbers).

**7.** Launch on 8081 as in `docs/agent-memory/DEVELOPING.md`, confirm both startup lines (`agent_memory seam loaded build=…` and `memory sessions: harness session factory installed`), then drive **one** turn against the probe scope with debug timing on — headers `x-user-id: latency-probe@ubs.com` and `x-tenant-id: t-latency`, and `"metadata": {"debug_timing": true}` in the body. Ask something the seeded memories answer, e.g. *"How do I like my updates written?"*

Paste (a) the reply, (b) every timing line the log emits for that turn, and (c) every line matching `memory` from the same turn — the recall line, the gate line, and the enqueue line.

**8.** From that same log, state plainly: **what fraction of the turn was memory?** Give the memory time and the total turn time as measured, not estimated.

**9.** Confirm the asynchronous half with quoted code: the enqueue call site in `sdk_runner.py`, and the worker loop that consumes it. State in one sentence whether the extraction model call happens **during** the turn or **after** it, and give the line numbers that prove it.

---

## Report format — end with exactly these lines, flat, no code fences

    DB-HOST: <host, port, database, user - password masked>
    DB-SESSION-URL: <set and same | set and different | not set>
    DB-VERSION: <the version() string>
    DB-EXTENSIONS: <extname/extversion list>
    DB-MEMORY-SIZE: <each agent_memory table: size and approx rows>
    DB-HARNESS-SIZE: <top harness tables by size, and total database size>
    DB-SHARED: <other databases and schemas on this server>
    AZURE: <subscription/group/region/tier/storage/backup, or "az unavailable">
    PRECONDITION: <embed dim and entry count, or the FAIL message>
    LATENCY-EMBED: <median ms>
    LATENCY-FETCH: <median ms>
    LATENCY-RANK: <median ms>
    LATENCY-RECALL-TOTAL: <median ms>
    LATENCY-WRITE: <median ms without decider>
    LATENCY-ADJUDICATION: <median ms for the decision model call>
    RECALL-PROOF: <memories in block, block chars - proving the scope was not empty>
    TURN-TIMING: <memory ms out of total turn ms, from the debug timing lines>
    ASYNC: <one line: extraction runs during the turn, or after it, with line numbers>
    ANOMALY: <anything that looked wrong, or NONE>

**A number you could not measure is reported as `not measured: <why>`.** Round 10's timings looked plausible and were wrong, which is worse than a blank — a blank gets re-run, a wrong number gets written into documentation.
