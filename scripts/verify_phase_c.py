"""Phase C gate — the v2 semantic layer. Run from repo root:
python scripts/verify_phase_c.py
Deterministic: stubs the embedder with fixed vectors, so it needs NO model
access and NO pgvector — it proves the logic on any database. A final live
section runs only if a real embedder responds (SKIP otherwise).
Prints PHASE_C: PASS | FAIL (OCR-safe)."""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete  # noqa: E402

try:  # harness placement
    from agent_factory.memory import _digit, semantic  # noqa: E402
    from agent_factory.memory.models import MemoryEntry  # noqa: E402
    from agent_factory.memory.recall import build_memory_block  # noqa: E402
    from agent_factory.memory.store import forget_user, scope_metrics, smart_add_entry  # noqa: E402
except ImportError:  # standalone transfer-repo layout
    from memory import _digit, semantic  # noqa: E402
    from memory.models import MemoryEntry  # noqa: E402
    from memory.recall import build_memory_block  # noqa: E402
    from memory.store import forget_user, scope_metrics, smart_add_entry  # noqa: E402

P, U = "verify-profile-c", "verify-user-c"
# Pass the tenant explicitly everywhere. The identity hardening removed the
# default-tenant sentinel from the store signatures, so relying on a default
# breaks against the current package (and passing it works against both).
T = "default"
FAILURES: list[str] = []
NOW = datetime.now(timezone.utc)

# --- deterministic embedder stub: fixed direction per known phrase ----------
# CRITICAL: stub vectors must match the environment's real dimension — a live
# pgvector column is vector(EMBED_DIM) and rejects anything else (learned on
# the pod: 8-dim stubs pass on a BYTEA column and fail on vector(1536)).
try:
    from agent_factory.memory.models import EMBED_DIM as DIM  # type: ignore
except ImportError:
    from memory.models import EMBED_DIM as DIM  # type: ignore


def _unit(i: int) -> list[float]:
    # logic lives in the first 8 components; zero-padding to DIM doesn't
    # change any cosine relationships the checks rely on
    v = [0.0] * DIM
    v[i % 8] = 1.0
    return v


def _mix(a: list[float], b: list[float], w: float) -> list[float]:
    return [w * x + (1 - w) * y for x, y in zip(a, b)]


TOPIC_FMT = _unit(0)      # formatting preference topic
TOPIC_TEAM = _unit(1)     # team/context topic
TOPIC_FOOD = _unit(2)     # unrelated topic

# cos(mix(a,b,w), a) = w/sqrt(w^2+(1-w)^2): w=0.97 -> ~0.9995 (tier 2);
# w=0.60 -> ~0.83 (tier-3 ambiguity band); w=0.90 -> ~0.99 (recall relevance).
VOCAB = {
    "user wants three bullet points": TOPIC_FMT,
    "user wants five bullet points": _mix(TOPIC_FMT, TOPIC_TEAM, 0.97),  # tier-2 same-fact
    "user wants three bullets": _mix(TOPIC_FMT, TOPIC_TEAM, 0.99),  # >=0.95, NOT richer (the live-failure shape)
    "user works on payments team": TOPIC_TEAM,
    "user works on payments reconciliation team now": _mix(TOPIC_TEAM, TOPIC_FMT, 0.60),  # tier-3 band
    "user likes pasta": TOPIC_FOOD,
    "query about formatting": _mix(TOPIC_FMT, TOPIC_FOOD, 0.90),
}


async def fake_embed(texts):
    return [VOCAB.get(t.strip().casefold(), _unit(5)) for t in texts]


def check(n, name, ok, detail=""):
    print(f"  {n}. {name}: {'ok' if ok else 'FAIL ' + str(detail)}")
    if not ok:
        FAILURES.append(name)


async def cleanup():
    async with _digit.get_session() as s:
        await s.execute(delete(MemoryEntry).where(MemoryEntry.profile_id == P))
        await s.commit()


async def main():
    real_embed = _digit.embed
    _digit.embed = fake_embed
    try:
        await cleanup()

        # 1-2. pure functions
        check(1, "pack/unpack roundtrip", semantic.unpack_vector(semantic.pack_vector([0.5, -1.0, 2.0])) == [0.5, -1.0, 2.0])
        check(2, "cosine sanity", abs(semantic.cosine(TOPIC_FMT, TOPIC_FMT) - 1.0) < 1e-9 and semantic.cosine(TOPIC_FMT, TOPIC_TEAM) == 0.0)

        # 3. decision parse: valid / out-of-range / garbage
        check(3, "decision parse + range-validate",
              semantic.parse_decision("SUPERSEDE 1", 3) == ("supersede", 1)
              and semantic.parse_decision("SUPERSEDE 9", 3) == ("add", None)
              and semantic.parse_decision("hmm unsure", 3) == ("add", None)
              and semantic.parse_decision("NONE", 3) == ("none", None))

        # 4. plain adds (distinct topics) -> saved, embedded
        s1, id1 = await smart_add_entry(P, U, tenant_id=T, content="user wants three bullet points", category="preference")
        s2, _ = await smart_add_entry(P, U, tenant_id=T, content="user works on payments team", category="context")
        m = await scope_metrics(P, U, T)
        check(4, "adds embedded", s1 == s2 == "saved" and m["live"] == 2 and m["embedded"] == 2, m)

        # 5. tier-2 same-fact fast path (cos ~0.97, not richer) -> duplicate
        s3, _ = await smart_add_entry(P, U, tenant_id=T, content="user wants five bullet points")
        # NOTE: 'five' vs 'three' IS a changed fact, but without a decide callback the
        # fast path only auto-supersedes when strictly richer -> expect duplicate here.
        check(5, "tier-2 fast path (no LLM) conservative", s3 == "duplicate" and (await scope_metrics(P, U, T))["live"] == 2)

        # 6. tier-3 band with stub decide -> supersede, chain recorded
        async def decide_supersede_0(fact, candidates):
            return "SUPERSEDE 0"

        s4, new_id = await smart_add_entry(
            P, U, tenant_id=T, content="user works on payments reconciliation team now",
            observed_at=NOW, decide=decide_supersede_0,
        )
        m = await scope_metrics(P, U, T)
        check(6, "tier-3 supersede + chain", s4 == "superseded_old" and m["superseded"] == 1 and m["live"] == 2, (s4, m))

        # 7. observed_at guard: an OLDER fact may not supersede the incumbent
        old_date = NOW - timedelta(days=400)

        async def decide_always_0(fact, candidates):
            return "SUPERSEDE 0"

        s6, _ = await smart_add_entry(
            P, U, tenant_id=T, content="user works on payments team", observed_at=old_date, decide=decide_always_0
        )
        check(7, "observed_at guard -> ADD not supersede", s6 == "saved", s6)

        # 8. blended recall: query near formatting topic ranks the fmt memory in
        block, count = await build_memory_block(P, U, T, query_text="query about formatting")
        check(8, "relevance recall", block is not None and "three bullet points" in block and count >= 1, count)

        # 9. degradation: embedder down -> recency recall still works
        async def dead_embed(texts):
            return None

        _digit.embed = dead_embed
        block, count = await build_memory_block(P, U, T, query_text="query about formatting")
        check(9, "embedder-down degradation", block is not None and count >= 1)
        _digit.embed = fake_embed

        # 10. >=0.95-similar CONTRADICTION with a decider routes to the decision
        # (the live-observed failure: "three bullets" -> "five bullets" embeds
        # near-identically; without this routing it was dropped as a duplicate)
        async def decide_contradiction(fact, candidates):
            return "SUPERSEDE 0"

        s10, _ = await smart_add_entry(
            P, U, tenant_id=T, content="user wants three bullets", observed_at=NOW, decide=decide_contradiction
        )
        m = await scope_metrics(P, U, T)
        check(10, "high-sim contradiction via decide -> supersede", s10 == "superseded_old" and m["superseded"] >= 2, (s10, m))

        # 11. below the decide floor, the LLM is never consulted (cost control)
        async def decide_must_not_be_called(fact, candidates):
            raise AssertionError("decide called below T_DECIDE_FLOOR")

        s11, _ = await smart_add_entry(P, U, tenant_id=T, content="user likes pasta", decide=decide_must_not_be_called)
        check(11, "decide floor skips LLM for unrelated fact", s11 == "saved", s11)

        # 12. forget_user cascade
        n = await forget_user(P, U, T)
        m = await scope_metrics(P, U, T)
        check(12, "forget_user cascade", n >= 3 and m["live"] == 0 and m["discarded"] >= n, (n, m))

        await cleanup()
    finally:
        _digit.embed = real_embed

    # 11. live embedder (optional)
    live = "skipped"
    try:
        vecs = await _digit.embed(["ping"])
        if vecs and vecs[0]:
            live = f"ok dim={len(vecs[0])}"
    except Exception:
        live = "skipped"
    print(f"live_embedder={live}")

    print("PHASE_C: PASS" if not FAILURES else f"PHASE_C: FAIL ({', '.join(FAILURES)})")
    return 0 if not FAILURES else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
