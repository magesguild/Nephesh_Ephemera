"""Chat activity tracker — lets the heartbeat yield to active conversations.

Two layers:

1. In-process timestamp (for the scheduler loop in the same process):
   `record_activity()` / `seconds_since_last_activity()`. Used by the
   scheduler's pre-cycle check.

2. Shared state file (for the heartbeat subprocess): the scheduler writes
   a monotonic timestamp to `data/chat_activity.json` via
   `record_chat_activity()`; the heartbeat reads it via
   `seconds_since_chat_activity()` before the expensive Ollama call.
   This gives the subprocess a way to check "is a human chatting right
   now?" without IPC.

The heartbeat calls memory functions directly (not via REST), so its
own memory_context/ingest calls do NOT record activity — avoiding the
self-poisoning problem where the heartbeat's own API calls triggered
the120s cooldown.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

# --- In-process timestamp (scheduler only) ---
_last_activity: float = 0.0


def record_activity() -> None:
    """Record that a human-initiated API call happened. Called by REST
    endpoints (web_ui.py) when the OpenCode plugin or a human hits them.
    Do NOT call this from the heartbeat — it would poison the cooldown."""
    global _last_activity
    _last_activity = time.monotonic()
    # Also write to the shared file so the heartbeat subprocess sees it
    record_chat_activity()


def seconds_since_last_activity() -> float:
    """Seconds since the last chat-related API call. Returns float('inf')
    if record_activity has never been called (heartbeat should fire)."""
    if _last_activity == 0.0:
        return float("inf")
    return time.monotonic() - _last_activity


# --- Shared state file (cross-process, for heartbeat subprocess) ---
_ACTIVITY_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "chat_activity.json"


def record_chat_activity() -> None:
    """Write current wall-clock time to the shared activity file.
    Called by record_activity() (which is called by REST endpoints).
    The heartbeat subprocess reads this via seconds_since_chat_activity().
    Uses time.time() (wall clock) instead of time.monotonic() because
    monotonic clocks are not contractually comparable across processes."""
    _ACTIVITY_FILE.parent.mkdir(parents=True, exist_ok=True)
    _ACTIVITY_FILE.write_text(json.dumps({"timestamp": time.time()}))


def seconds_since_chat_activity() -> float:
    """Read the shared activity file and return seconds since last chat.
    Returns float('inf') if no file exists (heartbeat should fire).
    Called by heartbeat.py before the Ollama call — the mid-flight
    abort check."""
    if not _ACTIVITY_FILE.exists():
        return float("inf")
    try:
        data = json.loads(_ACTIVITY_FILE.read_text())
        saved = data.get("timestamp", 0.0)
        return time.time() - saved
    except (json.JSONDecodeError, OSError):
        return float("inf")
