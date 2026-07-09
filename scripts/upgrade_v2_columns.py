"""Additive v2 schema upgrade — safe on a live database, idempotent.
Adds nullable columns (embedding, superseded_by, observed_at) to
agent_memory_entries if missing. NEVER drops or rewrites anything.
Run from repo root: python scripts/upgrade_v2_columns.py --yes

Column type for `embedding` follows AGENT_FACTORY_MEMORY_PGVECTOR:
  unset/0 -> BYTEA (packed float32; python-side similarity — works everywhere)
  1       -> vector(EMBED_DIM)  (requires the pgvector extension to already be
             CREATE EXTENSION'd in this database — this script does NOT do that)
Converting BYTEA -> vector later is a documented one-off ALTER, not this script."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import inspect, text  # noqa: E402

try:  # harness placement
    from agent_factory.memory import _digit  # noqa: E402
    from agent_factory.memory.models import EMBED_DIM, USE_PGVECTOR  # noqa: E402
except ImportError:  # standalone transfer-repo layout
    from memory import _digit  # noqa: E402
    from memory.models import EMBED_DIM, USE_PGVECTOR  # noqa: E402

TABLE = "agent_memory_entries"


def _embedding_ddl(dialect: str) -> str:
    if USE_PGVECTOR:
        return f"vector({EMBED_DIM})"
    return "BYTEA" if dialect.startswith("postgres") else "BLOB"


async def main() -> int:
    if "--yes" not in sys.argv:
        print(f"Refusing without --yes (adds nullable columns to {TABLE}; no drops).")
        return 1
    async with _digit.get_session() as session:
        conn = await session.connection()
        dialect = conn.dialect.name

        def existing_columns(sync_conn):
            return {c["name"] for c in inspect(sync_conn).get_columns(TABLE)}

        have = await conn.run_sync(existing_columns)
        wanted = {
            "embedding": _embedding_ddl(dialect),
            "superseded_by": "VARCHAR(36)",
            "observed_at": "TIMESTAMP WITH TIME ZONE" if dialect.startswith("postgres") else "TIMESTAMP",
        }
        added = []
        for name, ddl in wanted.items():
            if name in have:
                continue
            await conn.execute(text(f"ALTER TABLE {TABLE} ADD COLUMN {name} {ddl}"))
            added.append(name)
        await session.commit()
    print(f"UPGRADE_V2: ok dialect={dialect} added={','.join(added) if added else 'none (already present)'}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
