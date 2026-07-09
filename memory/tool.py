"""The explicit save_memory tool.

save_memory_impl is transport-agnostic: the 5-line registration wrapper at
the harness's tool-registry call site (see IMPLEMENTATION_BRIEF, Task 4)
adapts it to however tools receive per-turn context there.
"""

from __future__ import annotations

from datetime import datetime, timezone

from . import _digit
from .store import smart_add_entry

TOOL_NAME = "save_memory"

# Wording adapted from Hermes' memory tool: proactive save on durable signals.
TOOL_DESCRIPTION = (
    "Save a durable fact about this user to persistent memory so it survives "
    "across sessions. Use proactively when the user states a preference, "
    "correction, or lasting personal/professional detail (role, team, workflow, "
    "format preferences). Do NOT save chit-chat, one-off task details, or "
    "anything sensitive (credentials, account numbers, health, beliefs). "
    "content: one short sentence. category: preference | fact | context | note."
)

_DECLINE = "Memory is not enabled for this agent, so nothing was saved."
_RESULTS = {
    "saved": "Saved to persistent memory.",
    "superseded_old": "Saved - this replaces an older memory on the same topic.",
    "duplicate": "Already in memory - nothing new saved.",
    "rejected": "That looks like sensitive data (credentials/account numbers), so it was not saved.",
    "empty": "Nothing usable to save.",
}


async def save_memory_impl(ctx, content: str, category: str = "note") -> str:
    """ctx = whatever per-turn context object the harness hands tools.
    Flag check lives HERE because the shared harness has no per-request tool
    allowlist — a flag-off agent must decline even if the tool is visible."""
    if not _digit.memory_enabled(ctx):
        return _DECLINE
    identity = _digit.get_identity(ctx)
    if identity is None:
        _digit.log.warning("save_memory: could not resolve identity from ctx")
        return _DECLINE
    # User-directed saves get the FULL gate including the tier-3 decision:
    # they are high-intent and low-frequency, and this is the main path where
    # corrections ("actually, five now") arrive. Extraction can't catch these
    # afterwards — it treats tool-saved facts as already-known (observed live:
    # the two safeguards starve each other and contradictions accumulate).
    # On any decision failure the gate degrades to a plain ADD.
    from .extraction import decide_supersede  # local import avoids cycles at module load

    status, _ = await smart_add_entry(
        identity.profile_id,
        identity.user_id,
        content,
        category=category,
        source="tool",
        tenant_id=identity.tenant_id,
        thread_id=identity.thread_id,
        observed_at=datetime.now(timezone.utc),  # user stated it now
        decide=decide_supersede,
    )
    return _RESULTS.get(status, _DECLINE)
