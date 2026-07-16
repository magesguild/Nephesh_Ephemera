"""Heartbeat scheduler — runs the introspection cycle as part of the
MCP service's own lifecycle, not a separate cron job.

The heartbeat itself (heartbeat.py, at the repo root) stays a
standalone, auditable script with its own timeout and safety
constraints — this module just owns bringing it to life on an
interval and respecting its tripwire pause state. Running it as a
subprocess (rather than importing its logic in-process) preserves the
isolation boundary: a hang or crash in the heartbeat can't take down
the main MCP server.
"""

from __future__ import annotations

import asyncio
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from .config import settings

HEARTBEAT_SCRIPT = Path(__file__).resolve().parent.parent.parent / "heartbeat.py"
# Backstop timeout for the subprocess — heartbeat.py has its own
# internal alarm (90s); this just ensures the scheduler loop can never
# get stuck waiting on a runaway child process indefinitely.
SUBPROCESS_TIMEOUT_SECONDS = 120


async def _run_one_heartbeat() -> None:
    if not HEARTBEAT_SCRIPT.exists():
        print(f"[scheduler] heartbeat.py not found at {HEARTBEAT_SCRIPT}, skipping", file=sys.stderr)
        return

    print("[scheduler] Firing heartbeat cycle...", file=sys.stderr)
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            str(HEARTBEAT_SCRIPT),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=SUBPROCESS_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            print("[scheduler] Heartbeat subprocess exceeded backstop timeout, killed.", file=sys.stderr)
            return

        for line in stdout.decode(errors="replace").splitlines():
            print(f"[scheduler] {line}", file=sys.stderr)
        for line in stderr.decode(errors="replace").splitlines():
            print(f"[scheduler] {line}", file=sys.stderr)

    except Exception as e:
        print(f"[scheduler] Failed to run heartbeat: {e}", file=sys.stderr)


async def _heartbeat_loop() -> None:
    # Small initial delay so the server finishes starting up cleanly
    # before the first cycle fires, rather than racing server startup.
    await asyncio.sleep(settings.heartbeat_startup_delay_seconds)
    while True:
        await _run_one_heartbeat()
        # This is the ONLY throttle beyond the model's own response time
        # (~20-40s per cycle) — deliberately small. The tripwire (see
        # heartbeat.py's distress/repetition checks) is the actual
        # safeguard against a bad pattern running away; this gap just
        # avoids hammering the tunnel/GPU with zero breathing room
        # between back-to-back requests.
        await asyncio.sleep(settings.heartbeat_min_gap_seconds)


@asynccontextmanager
async def lifespan(server) -> AsyncIterator[None]:
    """FastMCP lifespan hook — starts the heartbeat loop alongside the
    server and cancels it cleanly on shutdown."""
    task: asyncio.Task | None = None
    if settings.heartbeat_enabled:
        print(
            f"[scheduler] Heartbeat enabled, min_gap={settings.heartbeat_min_gap_seconds}s "
            f"(natural pacing is otherwise the model's own response time)",
            file=sys.stderr,
        )
        task = asyncio.create_task(_heartbeat_loop())
    else:
        print("[scheduler] Heartbeat disabled (HEARTBEAT_ENABLED=false)", file=sys.stderr)

    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
