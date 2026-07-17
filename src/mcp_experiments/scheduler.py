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

from .activity import seconds_since_last_activity
from .config import settings

HEARTBEAT_SCRIPT = Path(__file__).resolve().parent.parent.parent / "heartbeat.py"
DREAMING_SCRIPT = Path(__file__).resolve().parent.parent.parent / "dreaming.py"
# Backstop timeout for the subprocess — heartbeat.py has its own
# internal alarm (90s); this just ensures the scheduler loop can never
# get stuck waiting on a runaway child process indefinitely.
SUBPROCESS_TIMEOUT_SECONDS = 120
# Dream sessions are longer — timeout scales with cycle count.
DREAM_TIMEOUT_PER_CYCLE = 180  # seconds per cycle (generous for inference + storage)

# Runtime state — mutable, toggled via API endpoints.
_runtime_state = {
    "heartbeat_enabled": settings.heartbeat_enabled,
    "dream_running": False,
    "dream_task": None,
}


def get_heartbeat_enabled() -> bool:
    return _runtime_state["heartbeat_enabled"]


def set_heartbeat_enabled(enabled: bool) -> None:
    _runtime_state["heartbeat_enabled"] = enabled


def is_dream_running() -> bool:
    return _runtime_state["dream_running"]


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


async def run_dream_session(cycles: int = 3, seed: str | None = None) -> dict:
    """Run a dream session as a subprocess. Returns the output."""
    if not DREAMING_SCRIPT.exists():
        return {"error": f"dreaming.py not found at {DREAMING_SCRIPT}"}

    if _runtime_state["dream_running"]:
        return {"error": "A dream session is already running"}

    _runtime_state["dream_running"] = True
    try:
        cmd = [sys.executable, str(DREAMING_SCRIPT), "--cycles", str(cycles), "--verbose"]
        if seed:
            cmd.extend(["--seed", seed])

        print(f"[scheduler] Starting dream session: {cycles} cycles", file=sys.stderr)
        dream_timeout = DREAM_TIMEOUT_PER_CYCLE * cycles
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=dream_timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return {"error": "Dream session exceeded timeout", "timeout": dream_timeout}

        output = stdout.decode(errors="replace")
        errors = stderr.decode(errors="replace")

        for line in output.splitlines():
            print(f"[scheduler] {line}", file=sys.stderr)
        for line in errors.splitlines():
            print(f"[scheduler] {line}", file=sys.stderr)

        return {
            "status": "completed",
            "exit_code": proc.returncode,
            "output": output,
            "errors": errors if errors.strip() else None,
        }
    finally:
        _runtime_state["dream_running"] = False


async def _heartbeat_loop() -> None:
    # Small initial delay so the server finishes starting up cleanly
    # before the first cycle fires, rather than racing server startup.
    await asyncio.sleep(settings.heartbeat_startup_delay_seconds)
    while True:
        # Check runtime toggle — allows enabling/disabling via API
        # without restarting the server.
        if not get_heartbeat_enabled():
            await asyncio.sleep(10)  # check again in 10s
            continue

        # Yield to active chat — if a human is present (recent API call
        # to memory_context or memory_ingest), skip this cycle and wait.
        # The heartbeat is background work; chat is the foreground.
        elapsed = seconds_since_last_activity()
        if elapsed < settings.heartbeat_chat_cooldown_seconds:
            wait = settings.heartbeat_chat_cooldown_seconds - elapsed
            print(
                f"[scheduler] Chat active (last activity {elapsed:.0f}s ago), "
                f"skipping heartbeat, retrying in {wait:.0f}s",
                file=sys.stderr,
            )
            await asyncio.sleep(wait)
            continue

        # Yield to dreaming — don't compete for the same model/GPU.
        if is_dream_running():
            print("[scheduler] Dream running, skipping heartbeat", file=sys.stderr)
            await asyncio.sleep(30)
            continue

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
    # Always start the loop — it checks the runtime toggle each iteration,
    # so it can be enabled/disabled via API without a restart.
    print(
        f"[scheduler] Heartbeat {'enabled' if get_heartbeat_enabled() else 'disabled'}, "
        f"min_gap={settings.heartbeat_min_gap_seconds}s",
        file=sys.stderr,
    )
    task = asyncio.create_task(_heartbeat_loop())

    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
