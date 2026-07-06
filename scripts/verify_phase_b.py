"""Phase B gate. Run from repo root: python scripts/verify_phase_b.py
Checks extraction parsing + resilience WITHOUT a model (stubbed), then runs a
live extraction only if _digit.WIRING['llm'] is True.
Final line: PHASE_B: PASS | PARTIAL (llm not wired) | FAIL."""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete  # noqa: E402

from memory import _digit  # noqa: E402
from memory.extraction import extract_and_store, parse_extraction  # noqa: E402
from memory.models import MemoryEntry  # noqa: E402
from memory.store import count_entries  # noqa: E402

P, U = "verify-profile-b", "verify-user-b"
FAILURES: list[str] = []


def check(n: int, name: str, ok: bool):
    print(f"  {n}. {name}: {'ok' if ok else 'FAIL'}")
    if not ok:
        FAILURES.append(name)


async def cleanup():
    async with _digit.get_session() as s:
        await s.execute(delete(MemoryEntry).where(MemoryEntry.profile_id == P))
        await s.commit()


async def main():
    ident = _digit.Identity(profile_id=P, user_id=U)

    # 1-3. parser leniency (no DB, no model)
    good = '```json\n{"new_entries": [{"content": "User prefers bullets", "category": "preference"}]}\n```'
    check(1, "parse fenced json", parse_extraction(good) == [{"content": "User prefers bullets", "category": "preference"}])
    check(2, "parse garbage -> []", parse_extraction("no json here") == [])
    check(3, "parse bad category -> note", parse_extraction('{"new_entries": [{"content": "x", "category": "weird"}]}')[0]["category"] == "note")

    await cleanup()
    real_llm = _digit.llm_complete

    # 4. malformed model output costs nothing
    async def _garbage(prompt: str) -> str:
        return "TOTALLY NOT JSON {{{"

    _digit.llm_complete = _garbage
    written = await extract_and_store(ident, "hello", "hi")
    check(4, "garbage output -> 0 writes, no raise", written == 0 and await count_entries(P, U) == 0)

    # 5. valid output writes an entry
    marker = f"User works on the payments team {uuid.uuid4().hex[:8]}"

    async def _valid(prompt: str) -> str:
        return '{"new_entries": [{"content": "%s", "category": "context"}]}' % marker

    _digit.llm_complete = _valid
    written = await extract_and_store(ident, "I work on payments", "noted")
    check(5, "valid output -> 1 write", written == 1 and await count_entries(P, U) == 1)

    _digit.llm_complete = real_llm
    await cleanup()

    # 6. live model call (only when wired)
    live = "skipped"
    if _digit.WIRING.get("llm"):
        try:
            written = await extract_and_store(
                ident, "Remember: I always want answers as three bullet points.", "Understood."
            )
            live = f"ok wrote={written}"
            check(6, "live extraction", True)
        except Exception:
            live = "FAIL"
            check(6, "live extraction", False)
        await cleanup()
    print(f"live_llm={live}")

    if FAILURES:
        print(f"PHASE_B: FAIL ({', '.join(FAILURES)})")
        return 1
    if not _digit.WIRING.get("llm"):
        print("PHASE_B: PARTIAL (llm not wired - plumbing verified, wire RECON:Q15 for live)")
        return 0
    print("PHASE_B: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
