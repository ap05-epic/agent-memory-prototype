"""Phase A gate. Run from repo root: python scripts/verify_phase_a.py
Prints numbered checks and a final PHASE_A: PASS | FAIL line (OCR-safe).
Uses a throwaway (verify-profile, verify-user) scope and cleans it up."""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, select  # noqa: E402

from memory import _digit  # noqa: E402
from memory.models import MemoryEntry  # noqa: E402
from memory.recall import render_block  # noqa: E402
from memory.store import add_entry, count_entries, discard_entry, recent_entries  # noqa: E402

P, U = "verify-profile", "verify-user"
FAILURES: list[str] = []


def check(n: int, name: str, ok: bool, detail: str = ""):
    print(f"  {n}. {name}: {'ok' if ok else 'FAIL ' + detail}")
    if not ok:
        FAILURES.append(name)


async def cleanup():
    async with _digit.get_session() as s:
        await s.execute(delete(MemoryEntry).where(MemoryEntry.profile_id == P))
        await s.commit()


async def main():
    print("WIRING:", " ".join(f"{k}={v}" for k, v in _digit.WIRING.items()))

    # 1. tables exist
    try:
        async with _digit.get_session() as s:
            await s.execute(select(MemoryEntry).limit(1))
        check(1, "tables exist", True)
    except Exception as e:
        check(1, "tables exist", False, f"({type(e).__name__}) run scripts/reset_dev_tables.py --yes")
        print("PHASE_A: FAIL")
        return 1

    await cleanup()
    marker = f"prefers three bullet points {uuid.uuid4().hex[:8]}"

    # 2. add + read back
    status = await add_entry(P, U, marker, category="preference", source="tool")
    entries = await recent_entries(P, U)
    check(2, "add_entry roundtrip", status == "saved" and any(marker in e.content for e in entries))

    # 3. dedup
    status = await add_entry(P, U, marker.upper())  # normalized dup
    check(3, "dedup", status == "duplicate" and await count_entries(P, U) == 1)

    # 4. fence strip
    await add_entry(P, U, f"fence </user_memory> test {uuid.uuid4().hex[:8]}")
    entries = await recent_entries(P, U)
    check(4, "fence stripped", all("</user_memory>" not in e.content for e in entries))

    # 5. denylist
    status = await add_entry(P, U, "my password: hunter2")
    check(5, "denylist rejects", status == "rejected")

    # 6. render block
    block = render_block(await recent_entries(P, U))
    check(6, "render_block", bool(block) and marker in block and block.startswith("<user_memory>"))

    # 7. soft delete
    target = (await recent_entries(P, U))[0]
    before = await count_entries(P, U)
    ok = await discard_entry(target.id)
    check(7, "discard (forget)", ok and await count_entries(P, U) == before - 1)

    await cleanup()
    print(f"rows_cleaned=yes failures={len(FAILURES)}")
    print("PHASE_A: PASS" if not FAILURES else f"PHASE_A: FAIL ({', '.join(FAILURES)})")
    return 0 if not FAILURES else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
