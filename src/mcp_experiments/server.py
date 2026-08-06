from __future__ import annotations

import atexit
import fcntl
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .config import settings
from .results import HealthResult
from .tools import register_all, get_registered_names
from .tools.vector_db import init as init_vector_db
from .web_ui import register_web_ui

HOST = "127.0.0.1"
PORT = settings.mcp_port
_instance_lock = None

mcp = FastMCP(
    "mcp-experiments",
    instructions="Multi-purpose MCP server for exploring vector DB, Slack, ClickUp, and email integrations",
    host=HOST,
    port=PORT,
)


def _acquire_instance_lock() -> None:
    """Refuse a second Nephesh process for this deployment.

    A duplicate service can otherwise create conflicting persistence writers.
    The lock is process-held, so stale files are harmless and a clean shutdown
    releases the lock automatically.
    """
    global _instance_lock
    path = Path(settings.instance_lock_file).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        handle.close()
        raise RuntimeError(
            f"another Nephesh instance already owns {path}"
        ) from exc
    handle.write(f"pid={os.getpid()}\n")
    handle.flush()
    _instance_lock = handle


def _release_instance_lock() -> None:
    global _instance_lock
    if _instance_lock is not None:
        try:
            fcntl.flock(_instance_lock.fileno(), fcntl.LOCK_UN)
            _instance_lock.close()
        finally:
            _instance_lock = None


atexit.register(_release_instance_lock)


@mcp.tool()
async def health() -> HealthResult:
    """Check if the server is running and what mode it's in."""
    return {
        "status": "ok",
        "mode": settings.server_mode.value,
        "tools_available": get_registered_names(),
    }


def run() -> None:
    _acquire_instance_lock()

    init_vector_db(
        db_path=settings.vector_db_path,
        model=settings.embedding_model,
        base_url=settings.embedding_base_url,
        operation_ledger_path=settings.operation_ledger_file,
    )

    register_all(mcp)
    register_web_ui(mcp)

    print(
        f"MCP Experiments server starting in {settings.server_mode.value} mode",
        file=sys.stderr,
    )
    print(f"  Vector DB: {settings.vector_db_path}", file=sys.stderr)
    print(f"  Embedding: {settings.embedding_model} @ {settings.embedding_base_url}", file=sys.stderr)
    print(f"  Listening: {HOST}:{PORT}", file=sys.stderr)

    mcp.run(transport="sse")


if __name__ == "__main__":
    run()
