"""Chat activity tracker — lets the heartbeat yield to active conversations.

The heartbeat scheduler checks `seconds_since_last_activity()` before
firing. REST endpoints called by the OpenCode plugin (memory_context,
memory_ingest) call `record_activity()` so the scheduler knows a human
is present. While chat is active, the heartbeat skips cycles; when the
human leaves, the heartbeat resumes after a cooldown.

This is a simple module-level timestamp, not a lock. The only writer
is the web request handler (via record_activity); the only reader is
the scheduler loop. No contention in practice.
"""

from __future__ import annotations

import time

_last_activity: float = 0.0


def record_activity() -> None:
    """Call this from any endpoint that indicates a human is present."""
    global _last_activity
    _last_activity = time.monotonic()


def seconds_since_last_activity() -> float:
    """Seconds since the last chat-related API call. Returns float('inf')
    if record_activity has never been called (heartbeat should fire)."""
    if _last_activity == 0.0:
        return float("inf")
    return time.monotonic() - _last_activity
