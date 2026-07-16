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

    @property
    def data_dir(self) -> Path:
        path = Path(self.vector_db_path).parent
        path.mkdir(parents=True, exist_ok=True)
        return path


settings = Settings()
