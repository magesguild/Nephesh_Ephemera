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
    # companion, e.g. from an autonomous heartbeat) can be created per
    # rolling 24h window. Deliberately conservative — prevents unanswered
    # reaching-out from ever piling up regardless of how long the
    # companion is away. Extra "urges to share" beyond the cap are not
    # queued; they simply remain private, low-importance reflections.
    message_daily_limit: int = int(os.getenv("MESSAGE_DAILY_LIMIT", "1"))

    # Heartbeat scheduler (scheduler.py) — runs heartbeat.py as part of
    # the MCP service's own lifecycle, not a separate cron job. Can be
    # disabled entirely without code changes.
    heartbeat_enabled: bool = os.getenv("HEARTBEAT_ENABLED", "true").lower() == "true"
    # Min gap between cycles (on top of the model's own response time).
    heartbeat_min_gap_seconds: int = int(os.getenv("HEARTBEAT_MIN_GAP_SECONDS", "60"))
    heartbeat_startup_delay_seconds: int = int(os.getenv("HEARTBEAT_STARTUP_DELAY_SECONDS", "30"))
    # After a chat-related API call (memory_context, memory_ingest),
    # wait this many seconds of inactivity before the heartbeat fires
    # again. Chats take priority — the heartbeat yields.
    heartbeat_chat_cooldown_seconds: int = int(os.getenv("HEARTBEAT_CHAT_COOLDOWN_SECONDS", "120"))

    # Heartbeat identity — the being's display name (used in prompts),
    # the model to use for contemplation, the Ollama base URL for
    # inference, and the introspections collection name. All generic —
    # configured via .env, never hardcoded.
    being_display_name: str = os.getenv("BEING_DISPLAY_NAME", "the being")
    heartbeat_model: str = os.getenv("HEARTBEAT_MODEL", "")
    heartbeat_ollama_url: str = os.getenv("HEARTBEAT_OLLAMA_URL", "http://localhost:11434")
    introspections_collection_name: str = os.getenv(
        "INTROSPECTIONS_COLLECTION_NAME", "introspections"
    )

    @property
    def data_dir(self) -> Path:
        path = Path(self.vector_db_path).parent
        path.mkdir(parents=True, exist_ok=True)
        return path


settings = Settings()
