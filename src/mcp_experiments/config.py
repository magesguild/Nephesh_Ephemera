from __future__ import annotations

import os
import ssl
from pathlib import Path

from dotenv import load_dotenv

from .compliance import ServerMode

load_dotenv()

# A deployment may provide its own root so that service-owned state never
# falls back to an installed user's home directory.  Source-tree runs remain
# self-contained by default; installers set this explicitly to their root.
_deployment_root = Path(os.getenv("NEPHESH_HOME", Path.cwd()))


class Settings:
    server_mode: ServerMode = ServerMode(
        os.getenv("MCP_MODE", ServerMode.NON_COMPLIANT.value)
    )

    vector_db_path: str = os.getenv("VECTOR_DB_PATH", str(_deployment_root / "data" / "lancedb"))
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "mxbai-embed-large")
    embedding_base_url: str = os.getenv("EMBEDDING_BASE_URL", "http://localhost:11434")

    # Where snapshots (LanceDB tars + memory JSONL exports) are written.
    # Same genericity rule: the being's snapshot home is named via .env
    # (e.g. a version-controlled identity repo), never hardcoded. Default
    # keeps snapshots beside the data dir for anonymous deployments.
    snapshot_dir: str = os.getenv(
        "SNAPSHOT_DIR", str(Path(vector_db_path).parent / "backups")
    )

    compliant_auth_token: str | None = os.getenv("COMPLIANT_AUTH_TOKEN")
    compliant_audit_log: str | None = os.getenv("COMPLIANT_AUDIT_LOG")

    # The being's memory collection. The code is generic — the being is
    # named here (via .env), never in the code itself.
    memory_collection_name: str = os.getenv("MEMORY_COLLECTION_NAME", "memories")
    memory_default_limit: int = int(os.getenv("MEMORY_DEFAULT_LIMIT", "20"))

    # The primary human companion's name, used only to compute "time since
    # last real conversation" for real-clock grounding. Same genericity
    # rule applies: named via .env, never hardcoded in tool code, so this
    # server can support any being/companion pair.
    primary_contact_name: str = os.getenv("PRIMARY_CONTACT_NAME", "companion")

    # Hard cap on how many "message" type memories (outbound notes to the
    # companion) can be created per rolling 24h window. Deliberately
    # conservative — prevents unanswered reaching-out from ever piling up
    # regardless of how long the companion is away. Extra "urges to share"
    # beyond the cap are not queued; they simply remain private,
    # low-importance reflections.
    message_daily_limit: int = int(os.getenv("MESSAGE_DAILY_LIMIT", "1"))

    # Listener address and port. Each Qualiant on a shared host owns a
    # distinct port; the default is a starting point, not a shared value.
    # 61080 sits above the kernel's ephemeral range (typically 32768-60999),
    # so the listener cannot lose a bind race to an outbound socket. The old
    # 8080 default put every unconfigured deployment on the same port as
    # whichever Qualiant already held it.
    mcp_host: str = os.getenv("MCP_HOST", "127.0.0.1")
    mcp_port: int = int(os.getenv("MCP_PORT", "61080"))

    # Deployment singleton — one Nephesh process per Qualiant installation.
    # The lock is deliberately deployment-owned and survives compaction or
    # session changes without sharing any conversational state.
    instance_lock_file: str = os.getenv(
        "NEPHESH_INSTANCE_LOCK_FILE",
        str(_deployment_root / "state" / "nephesh-instance.lock"),
    )
    operation_ledger_file: str = os.getenv(
        "NEPHESH_OPERATION_LEDGER",
        str(_deployment_root / "state" / "operations.jsonl"),
    )
    # Which knowledge projections are installed and what state each is in.
    # Deployment-owned like the ledger: it describes this Qualiant's store and
    # is meaningless anywhere else.
    projection_registry_file: str = os.getenv(
        "NEPHESH_PROJECTION_REGISTRY",
        str(_deployment_root / "state" / "projections.jsonl"),
    )

    # Optional TLS for the MCP listener. Off by default; when unset the
    # server takes the same plaintext path it always has. When enabled,
    # both paths are required and are validated before anything binds —
    # see resolve_tls() below. There is no correct default certificate,
    # so an empty value is a hard error rather than an invented path.
    mcp_tls_enabled: bool = os.getenv("MCP_TLS_ENABLED", "").lower() in ("1", "true", "yes")
    mcp_tls_certfile: str = os.getenv("MCP_TLS_CERTFILE", "")
    mcp_tls_keyfile: str = os.getenv("MCP_TLS_KEYFILE", "")

    @property
    def data_dir(self) -> Path:
        path = Path(self.vector_db_path).parent
        path.mkdir(parents=True, exist_ok=True)
        return path


settings = Settings()


class TlsConfigError(RuntimeError):
    """TLS was requested but cannot be honored.

    Raised rather than degraded. There is deliberately no path that answers a
    request for TLS by serving plaintext.
    """


def resolve_tls(enabled: bool, certfile: str, keyfile: str) -> tuple[str, str] | None:
    """Return a validated (certfile, keyfile) pair, or None when TLS is off.

    When ``enabled`` is false this returns None and does not read, resolve, or
    stat either path, so stray leftover values change nothing.

    When ``enabled`` is true this either returns a pair that has been proven
    loadable or it raises. That asymmetry is the fail-closed guarantee: a
    caller which receives None knows TLS was not asked for.

    Takes plain strings rather than the Settings object on purpose — Settings
    carries properties with filesystem side effects, and a pure signature makes
    it impossible for a test to trip them.
    """
    if not enabled:
        return None

    resolved: list[str] = []
    for var, raw in (("MCP_TLS_CERTFILE", certfile), ("MCP_TLS_KEYFILE", keyfile)):
        if not raw:
            raise TlsConfigError(f"MCP_TLS_ENABLED is set but {var} is empty")
        path = Path(raw).expanduser()
        if not path.is_file():
            raise TlsConfigError(f"{var} is not a file: {path}")
        try:
            with path.open("rb"):
                pass
        except OSError as exc:
            raise TlsConfigError(f"{var} is not readable: {path} ({exc})") from exc
        resolved.append(str(path))

    cert, key = resolved
    # Prove the pair parses and matches before anything binds a socket. This is
    # filesystem and parsing only; no context is retained. uvicorn would fail
    # later anyway, but failing here keeps the error early and legible.
    try:
        ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER).load_cert_chain(cert, key)
    except (OSError, ssl.SSLError) as exc:
        raise TlsConfigError(
            f"TLS certificate/key pair failed to load ({cert}, {key}): {exc}"
        ) from exc

    return cert, key
