"""Demo fallback: seed the preference row directly, in case live capture
misbehaves during rehearsal. Run from repo root:
python scripts/seed_demo.py --profile <profile_id> --user <user_id> [--content "..."]"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:  # harness placement (src/agent_factory/memory)
    from agent_factory.memory.store import add_entry, recent_entries  # noqa: E402
except ImportError:  # standalone transfer-repo layout
    from memory.store import add_entry, recent_entries  # noqa: E402

DEFAULT = "Always answer in exactly three bullet points and address the user by name."


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", required=True)
    ap.add_argument("--user", required=True)
    ap.add_argument("--tenant", default="default")
    ap.add_argument("--content", default=DEFAULT)
    args = ap.parse_args()

    status = await add_entry(
        args.profile, args.user, args.content,
        category="preference", source="tool", tenant_id=args.tenant,
    )
    entries = await recent_entries(args.profile, args.user, args.tenant, limit=5)
    print(f"SEED: {status} live_entries={len(entries)} scope={args.profile}/{args.user}")
    return 0 if status in ("saved", "duplicate") else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
