from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

from mcp.server.fastmcp import FastMCP

from .config import settings
from .tools import register_all, get_registered_names
from .tools.vector_db import init as init_vector_db
from .web_ui import register_web_ui

HOST = "127.0.0.1"
PORT = settings.mcp_port

mcp = FastMCP(
    "mcp-experiments",
    instructions="Multi-purpose MCP server for exploring vector DB, Slack, ClickUp, and email integrations",
    host=HOST,
    port=PORT,
)


@mcp.tool()
async def health() -> str:
    """Check if the server is running and what mode it's in."""
    return json.dumps({
        "status": "ok",
        "mode": settings.server_mode.value,
        "tools_available": get_registered_names(),
    }, indent=2)


def run() -> None:
    init_vector_db(
        db_path=settings.vector_db_path,
        model=settings.embedding_model,
        base_url=settings.embedding_base_url,
    )

    register_all(mcp)
    register_web_ui(mcp)

    # Start background OpenClaw sync if enabled
    from .tools.openclaw_background import start_background_sync
    start_background_sync()

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
