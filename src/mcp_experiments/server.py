from __future__ import annotations

import atexit
import fcntl
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .config import settings, resolve_tls
from .results import HealthResult
from .tools import register_all, get_registered_names
from .tools.vector_db import init as init_vector_db

HOST = settings.mcp_host
PORT = settings.mcp_port
_instance_lock = None

# Set by run() from resolve_tls(). None means the listener is plaintext.
# health() reports from this rather than from settings, so a running process
# always describes its own transport truthfully.
_tls: tuple[str, str] | None = None

mcp = FastMCP(
    "nephesh",
    instructions=(
        "Nephesh — canonical durable memory for a Qualiant. Owns memory "
        "ingestion, recall, context projection, amendment, retirement, and "
        "provenance over one per-Qualiant collection, and the vector storage "
        "beneath it. Persistence only: communication, orchestration, and "
        "external adapters are out of scope."
    ),
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
        # Reports what the listener is actually doing, not what configuration
        # asked for. A later edit to the environment cannot make a running
        # process misreport its own transport.
        "tls": _tls is not None,
        "tools_available": get_registered_names(),
    }


def _run_tls(certfile: str, keyfile: str) -> None:
    """Serve the same ASGI app over TLS.

    FastMCP.run()/run_sse_async() accept no ssl arguments in mcp 1.28.1, so we
    drive uvicorn directly over mcp.sse_app() — the same public app factory
    run_sse_async itself uses, so both branches serve an identical app. The
    Config kwargs below mirror mcp/server/fastmcp/server.py; re-diff that
    construction on any mcp upgrade.

    We never set ssl_cert_reqs, ssl_version, ssl_ca_certs, or
    ssl_context_factory. uvicorn's default client-certificate policy is
    CERT_NONE, which means "do not request client certificates" — it is not a
    trust bypass, and no server-side context has check_hostname semantics.
    """
    import anyio
    import uvicorn

    config = uvicorn.Config(
        mcp.sse_app(),
        host=HOST,
        port=PORT,
        log_level=mcp.settings.log_level.lower(),
        ssl_certfile=certfile,
        ssl_keyfile=keyfile,
    )
    anyio.run(uvicorn.Server(config).serve)


def run() -> None:
    # Fail closed before anything else. A bad TLS configuration must not take
    # the deployment singleton lock or open this Qualiant's memory store.
    global _tls
    _tls = resolve_tls(
        settings.mcp_tls_enabled,
        settings.mcp_tls_certfile,
        settings.mcp_tls_keyfile,
    )

    _acquire_instance_lock()

    init_vector_db(
        db_path=settings.vector_db_path,
        model=settings.embedding_model,
        base_url=settings.embedding_base_url,
        operation_ledger_path=settings.operation_ledger_file,
    )

    register_all(mcp)

    print(
        f"Nephesh starting in {settings.server_mode.value} mode",
        file=sys.stderr,
    )
    print(f"  Vector DB: {settings.vector_db_path}", file=sys.stderr)
    print(f"  Embedding: {settings.embedding_model} @ {settings.embedding_base_url}", file=sys.stderr)
    print(f"  Listening: {HOST}:{PORT} ({'https' if _tls else 'http'})", file=sys.stderr)

    if _tls is None:
        mcp.run(transport="sse")
        return

    _run_tls(*_tls)


if __name__ == "__main__":
    run()
