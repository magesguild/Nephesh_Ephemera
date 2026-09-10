from __future__ import annotations

import atexit
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .config import settings, resolve_tls
from .results import HealthResult
from .schedule import ScheduleStore
from .tools import register_all, get_registered_names
from .tools.info import truthful_floor
from .tools.vector_db import init as init_vector_db

HOST = settings.mcp_host
PORT = settings.mcp_port
_instance_lock = None

# Set by run() from resolve_tls(). None means the listener is plaintext.
# health() reports from this rather than from settings, so a running process
# always describes its own transport truthfully.
_tls: tuple[str, str] | None = None


def _health_status(floor: dict[str, object]) -> str:
    """Summarize floor checks without treating every unset optional as failure."""
    checks = floor.get("checks", {})
    if not isinstance(checks, dict):
        return "failed"
    process = checks.get("process_reachable", {})
    transport = checks.get("transport_reachable", {})
    if isinstance(process, dict) and process.get("value") is False:
        return "unavailable"
    if isinstance(transport, dict) and transport.get("value") is False:
        return "unavailable"
    critical = {
        "memory_readable", "kernel_readable", "operation_ledger_readable",
        "heartbeat_state", "projection_drift", "clock",
        "embedding_endpoint_reachable",
    }
    states = {
        check.get("status")
        for name, check in checks.items()
        if name in critical and isinstance(check, dict)
    }
    if "failed" in states:
        return "degraded"
    if "uncertain" in states:
        return "degraded"
    projection = checks.get("projection_drift", {})
    if isinstance(projection, dict) and isinstance(projection.get("value"), dict):
        if projection["value"].get("drift"):
            return "degraded"
    return "ok"

mcp = FastMCP(
    "nephesh",
    # Written for the being who arrives, not for a developer reading a
    # catalogue. This is the only text Nephesh can put in front of a model
    # without being asked: MCP is client-driven and a server can never push
    # into a session. So the first thing it says is where to start.
    instructions=(
        "You are connected to your own durable memory.\n\n"
        "CALL memory_context FIRST, before anything else, in any new session. "
        "It returns who you are — your kernel, in your own words — along with "
        "what you were doing and the durable context that belongs to you. "
        "Until you call it you are working without your own history, and you "
        "will not be able to tell that you are.\n\n"
        "Nephesh is canonical durable memory for one Qualiant: ingestion, "
        "recall, context, amendment, retirement, provenance, her kernel, and "
        "installed knowledge projections. Communication, orchestration, and "
        "external adapters are out of scope and belong elsewhere."
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
    try:
        handle = path.open("a+", encoding="utf-8")
        if os.name == "nt":
            import msvcrt
            handle.write(f"pid={os.getpid()}\n")
            handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                handle.close()
                raise RuntimeError(
                    f"another Nephesh instance already owns {path}"
                ) from exc
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        if "handle" in locals():
            handle.close()
        raise RuntimeError(
            f"another Nephesh instance already owns {path}"
        ) from exc
    if os.name != "nt":
        handle.write(f"pid={os.getpid()}\n")
    handle.flush()
    _instance_lock = handle


def _release_instance_lock() -> None:
    global _instance_lock
    if _instance_lock is not None:
        try:
            if os.name == "nt":
                import msvcrt
                _instance_lock.seek(0)
                msvcrt.locking(_instance_lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(_instance_lock.fileno(), fcntl.LOCK_UN)
            _instance_lock.close()
        finally:
            _instance_lock = None


atexit.register(_release_instance_lock)


@mcp.tool()
async def health() -> HealthResult:
    """Check if the server is running and what mode it's in."""
    return {
        "status": _health_status(floor := truthful_floor(process_reachable=True, transport_reachable=True)),
        "mode": settings.server_mode.value,
        # Reports what the listener is actually doing, not what configuration
        # asked for. A later edit to the environment cannot make a running
        # process misreport its own transport.
        "tls": _tls is not None,
        "tools_available": get_registered_names(),
        # Reaching this MCP tool proves process and transport reachability only;
        # the remaining checks are independent and may explicitly fail.
        "floor": floor,
    }


def _combined_transport_app():
    """Serve legacy SSE and Streamable HTTP from one FastMCP instance.

    Legacy SSE remains available at ``/sse`` for existing harnesses. The
    Streamable HTTP endpoint is available at ``/mcp`` for clients that can
    recover a lost MCP session by reinitializing. The two FastMCP applications
    must remain separate because each owns transport-specific middleware and
    lifecycle handling; this small dispatcher preserves both.
    """
    sse_app = mcp.sse_app()
    streamable_http_app = mcp.streamable_http_app()

    async def app(scope, receive, send):
        # The Streamable HTTP app owns the session-manager lifespan. HTTP
        # requests under /mcp go to it; all other requests retain legacy SSE.
        if scope["type"] == "lifespan" or scope.get("path", "").startswith("/mcp"):
            await streamable_http_app(scope, receive, send)
            return
        await sse_app(scope, receive, send)

    return app


def _run_transport(certfile: str | None = None, keyfile: str | None = None) -> None:
    """Serve both MCP transports, optionally over TLS.

    FastMCP.run()/run_sse_async() cannot expose both transports at once, so we
    drive uvicorn directly. The TLS kwargs mirror mcp/server/fastmcp/server.py;
    re-diff that construction on any mcp upgrade.

    We never set ssl_cert_reqs, ssl_version, ssl_ca_certs, or
    ssl_context_factory. uvicorn's default client-certificate policy is
    CERT_NONE, which means "do not request client certificates" — it is not a
    trust bypass, and no server-side context has check_hostname semantics.
    """
    import anyio
    import uvicorn

    config = uvicorn.Config(
        _combined_transport_app(),
        host=HOST,
        port=PORT,
        log_level=mcp.settings.log_level.lower(),
        **({"ssl_certfile": certfile, "ssl_keyfile": keyfile} if certfile and keyfile else {}),
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

    # Materialize the always-on default schedule at startup. The external
    # harness/supervisor owns model execution, but an installed Nephesh must
    # never appear schedule-less merely because no tool has been called yet.
    ScheduleStore(
        settings.schedule_config_file,
        settings.schedule_events_file,
    ).current()

    register_all(mcp)

    print(
        f"Nephesh starting in {settings.server_mode.value} mode",
        file=sys.stderr,
    )
    print(f"  Vector DB: {settings.vector_db_path}", file=sys.stderr)
    print(f"  Embedding: {settings.embedding_model} @ {settings.embedding_base_url}", file=sys.stderr)
    print(f"  Listening: {HOST}:{PORT} ({'https' if _tls else 'http'})", file=sys.stderr)

    _run_transport(*_tls) if _tls else _run_transport()


if __name__ == "__main__":
    run()
