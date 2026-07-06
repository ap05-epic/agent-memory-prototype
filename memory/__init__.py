"""Agent-level persistent memory, scoped per (profile, user, tenant).

Self-contained package: every harness-specific symbol is imported/adapted in
one place, `memory._digit`. Nothing else in this package touches the host app.
"""

from .models import MemoryEntry, MemoryUserModel
from .store import add_entry, recent_entries, discard_entry, count_entries
from .recall import build_memory_block, render_block
from .tool import TOOL_NAME, TOOL_DESCRIPTION, save_memory_impl
from .extraction import extract_and_store, schedule_extraction

__all__ = [
    "MemoryEntry",
    "MemoryUserModel",
    "add_entry",
    "recent_entries",
    "discard_entry",
    "count_entries",
    "build_memory_block",
    "render_block",
    "TOOL_NAME",
    "TOOL_DESCRIPTION",
    "save_memory_impl",
    "extract_and_store",
    "schedule_extraction",
]
