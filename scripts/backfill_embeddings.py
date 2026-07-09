"""Embed rows written while the embedder was unavailable (embedding IS NULL).
Batched, resumable, read-then-update only. Run from repo root:
python scripts/backfill_embeddings.py [--limit 500]"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select, update  # noqa: E402

try:  # harness placement
    from agent_factory.memory import _digit, semantic  # noqa: E402
    from agent_factory.memory.models import USE_PGVECTOR, MemoryEntry  # noqa: E402
except ImportError:  # standalone transfer-repo layout
    from memory import _digit, semantic  # noqa: E402
    from memory.models import USE_PGVECTOR, MemoryEntry  # noqa: E402

BATCH = 64


async def main() -> int:
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 500
    done = failed = 0
    while done + failed < limit:
        async with _digit.get_session() as session:
            rows = list(
                (
                    await session.execute(
                        select(MemoryEntry)
                        .where(MemoryEntry.embedding.is_(None), MemoryEntry.discarded_at.is_(None))
                        .order_by(MemoryEntry.created_at.asc())
                        .limit(BATCH)
                    )
                ).scalars()
            )
        if not rows:
            break
        vecs = await _digit.embed([r.content for r in rows])
        if vecs is None:
            print(f"BACKFILL: embedder unavailable after done={done}; stopping")
            failed += len(rows)
            break
        async with _digit.get_session() as session:
            for row, vec in zip(rows, vecs):
                value = vec if USE_PGVECTOR else semantic.pack_vector(vec)
                await session.execute(
                    update(MemoryEntry).where(MemoryEntry.id == row.id).values(embedding=value)
                )
            await session.commit()
        done += len(rows)
    print(f"BACKFILL: ok embedded={done} remaining_failures={failed}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
