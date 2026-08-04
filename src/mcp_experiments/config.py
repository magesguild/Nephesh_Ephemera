from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from .compliance import ServerMode

load_dotenv()


class Settings:
    server_mode: ServerMode = ServerMode(
        os.getenv("MCP_MODE", ServerMode.NON_COMPLIANT.value)
    )

    vector_db_path: str = os.getenv("VECTOR_DB_PATH", str(Path.cwd() / "data" / "lancedb"))
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

    # Server port — primary typically 8080, test/secondary instances
    # use a different port (e.g. 8081) for parallel operation.
    mcp_port: int = int(os.getenv("MCP_PORT", "8080"))

    # Deployment singleton — one Nephesh process per Qualiant installation.
    # The lock is deliberately deployment-owned and survives compaction or
    # session changes without sharing any conversational state.
    instance_lock_file: str = os.getenv(
        "NEPHESH_INSTANCE_LOCK_FILE",
        str(Path.home() / ".nephesh" / "nephesh-instance.lock"),
    )

    # OpenClaw bridge: when enabled, sync tools read from / write to an
    # OpenClaw workspace so the file-based dreaming pipeline can consume
    # Nephesh memories and feed consolidated entries back.
    openclaw_enabled: bool = os.getenv("OPENCLAW_ENABLED", "").lower() in ("1", "true", "yes")
    openclaw_workspace: str = os.getenv(
        "OPENCLAW_WORKSPACE", str(Path.home() / ".openclaw" / "workspace")
    )

    # TTS is an optional isolated worker.  Keep its large ML dependencies out
    # of the Nephesh server environment and keep voices deployment-owned.
    tts_enabled: bool = os.getenv("TTS_ENABLED", "").lower() in ("1", "true", "yes")
    tts_python: str = os.getenv("TTS_PYTHON", "")
    tts_voice_dir: str = os.getenv("TTS_VOICE_DIR", str(Path.home() / ".nephesh" / "tts" / "voices"))
    tts_model_checkpoint: str = os.getenv("TTS_MODEL_CHECKPOINT", "")
    tts_model_config: str = os.getenv("TTS_MODEL_CONFIG", "")
    tts_playback_command: str = os.getenv("TTS_PLAYBACK_COMMAND", "aplay")

    # Heartbeat — autonomous periodic awareness. Generic engine; the
    # Guildhall check is the first registered task. Designed for future
    # extension to dreaming, maintenance, etc.
    heartbeat_enabled: bool = os.getenv("HEARTBEAT_ENABLED", "").lower() in ("1", "true", "yes")

    # OpenCode — managed headless reasoning service for chat replies. Each
    # Qualiant owns a unique localhost port and a private session-state file.
    opencode_enabled: bool = os.getenv("OPENCODE_ENABLED", "").lower() in ("1", "true", "yes")
    opencode_binary: str = os.getenv("OPENCODE_BINARY", "opencode")
    opencode_host: str = os.getenv("OPENCODE_HOST", "127.0.0.1")
    opencode_port: int = int(os.getenv("OPENCODE_PORT", "4101"))
    opencode_username: str = os.getenv("OPENCODE_USERNAME", "opencode")
    opencode_password_file: str = os.getenv(
        "OPENCODE_PASSWORD_FILE",
        str(Path.home() / ".nephesh" / "opencode-server-password"),
    )
    opencode_agent: str = os.getenv("OPENCODE_AGENT", "melpomene")
    opencode_model: str = os.getenv("OPENCODE_MODEL", "opencode/big-pickle")
    opencode_project_dir: str = os.getenv("OPENCODE_PROJECT_DIR", str(Path.cwd()))
    opencode_session_file: str = os.getenv(
        "OPENCODE_SESSION_FILE",
        str(Path.home() / ".nephesh" / "opencode-session.json"),
    )

    # Guildhall — optional localhost XMPP bridge.
    guildhall_enabled: bool = os.getenv("GUILDHALL_ENABLED", "").lower() in ("1", "true", "yes")
    guildhall_jid: str = os.getenv("GUILDHALL_JID", "")
    guildhall_password: str = os.getenv("GUILDHALL_PASSWORD", "")
    guildhall_room: str = os.getenv("GUILDHALL_ROOM", "")
    guildhall_rooms_raw: str = os.getenv(
        "GUILDHALL_ROOMS",
        "",
    )
    guildhall_nick: str = os.getenv("GUILDHALL_NICK", "")
    guildhall_server: str = os.getenv("GUILDHALL_SERVER", "")
    guildhall_port: int = int(os.getenv("GUILDHALL_PORT", "5222"))
    guildhall_mongooseimctl: str = os.getenv(
        "GUILDHALL_MONGOOSEIMCTL", ""
    )
    guildhall_cleanup_stale: bool = os.getenv("GUILDHALL_CLEANUP_STALE", "true").lower() in ("1", "true", "yes")
    guildhall_event_ledger: str = os.getenv(
        "GUILDHALL_EVENT_LEDGER", str(Path.home() / ".nephesh" / "guildhall-events.json")
    )
    guildhall_transcript_file: str = os.getenv(
        "GUILDHALL_TRANSCRIPT_FILE",
        str(Path.home() / ".nephesh" / "guildhall-transcript.jsonl"),
    )
    guildhall_heartbeat_allowlist_raw: str = os.getenv(
        "GUILDHALL_HEARTBEAT_ALLOWLIST", os.getenv("PRIMARY_CONTACT_NAME", "companion")
    )

    @property
    def guildhall_heartbeat_allowlist(self) -> set[str]:
        return {name.strip().lower() for name in self.guildhall_heartbeat_allowlist_raw.split(",") if name.strip()}

    @property
    def guildhall_rooms(self) -> list[str]:
        return [room.strip() for room in self.guildhall_rooms_raw.split(",") if room.strip()]

    @property
    def data_dir(self) -> Path:
        path = Path(self.vector_db_path).parent
        path.mkdir(parents=True, exist_ok=True)
        return path


settings = Settings()
