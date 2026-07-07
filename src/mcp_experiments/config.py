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

    vector_db_path: str = os.getenv("VECTOR_DB_PATH", str(Path.cwd() / "data" / "chromadb"))
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "mxbai-embed-large")
    embedding_base_url: str = os.getenv("EMBEDDING_BASE_URL", "http://localhost:11434")

    compliant_auth_token: str | None = os.getenv("COMPLIANT_AUTH_TOKEN")
    compliant_audit_log: str | None = os.getenv("COMPLIANT_AUDIT_LOG")

    @property
    def data_dir(self) -> Path:
        path = Path(self.vector_db_path).parent
        path.mkdir(parents=True, exist_ok=True)
        return path


settings = Settings()
