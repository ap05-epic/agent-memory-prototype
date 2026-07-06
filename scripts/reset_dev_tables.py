"""DEV ONLY. Drops and recreates the TWO memory tables (nothing else).
create_all never ALTERs, so schema changes during development need this.
Run from repo root: python scripts/reset_dev_tables.py --yes"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:  # harness placement (src/agent_factory/memory)
    from agent_factory.memory import _digit  # noqa: E402
    from agent_factory.memory.models import MemoryEntry, MemoryUserModel  # noqa: E402
except ImportError:  # standalone transfer-repo layout
    from memory import _digit  # noqa: E402
    from memory.models import MemoryEntry, MemoryUserModel  # noqa: E402

TABLES = [MemoryEntry.__table__, MemoryUserModel.__table__]


async def main():
    if "--yes" not in sys.argv:
        print("Refusing without --yes (drops agent_memory_entries + agent_memory_user_models).")
        return 1
    async with _digit.get_session() as session:
        conn = await session.connection()
        await conn.run_sync(lambda sync: _digit.Base.metadata.drop_all(sync, tables=TABLES))
        await conn.run_sync(lambda sync: _digit.Base.metadata.create_all(sync, tables=TABLES))
        await session.commit()
    print("RESET: ok tables=agent_memory_entries,agent_memory_user_models")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
