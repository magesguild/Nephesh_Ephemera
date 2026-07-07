from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

from mcp.server.fastmcp import FastMCP

from .compliance import ComplianceLevel, ServerMode
from .config import settings
from .tools import get_available_tools, handle_tool_call

mcp = FastMCP(
    "mcp-experiments",
    description="Multi-purpose MCP server for exploring vector DB, Slack, ClickUp, and email integrations",
)


@mcp.list_tools()
async def list_tools():
    available = get_available_tools()
    return [
        {
            "name": t["name"],
            "description": _build_description(t),
            "inputSchema": t["input_schema"],
        }
        for t in available
    ]


def _build_description(tool: dict) -> str:
    desc = tool["description"]
    compliance = tool.get("compliance", ComplianceLevel.NON_COMPLIANT)
    if settings.server_mode == ServerMode.COMPLIANT:
        desc += f" [Compliance: {compliance.value}]"
    return desc


@mcp.call_tool()
async def call_tool(name: str, arguments: dict):
    start = datetime.now(timezone.utc)

    result = await handle_tool_call(name, arguments)

    if settings.server_mode == ServerMode.COMPLIANT:
        _audit_log(name, arguments, result, start)

    return result


def _audit_log(tool_name: str, arguments: dict, result: str, start: datetime) -> None:
    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    log_entry = json.dumps({
        "timestamp": start.isoformat(),
        "tool": tool_name,
        "arguments": _redact_arguments(arguments),
        "elapsed_seconds": round(elapsed, 4),
        "result_size_bytes": len(result),
    })

    if settings.compliant_audit_log:
        with open(settings.compliant_audit_log, "a") as f:
            f.write(log_entry + "\n")

    print(f"[AUDIT] {log_entry}", file=sys.stderr)


def _redact_arguments(args: dict) -> dict:
    SENSITIVE_KEYS = {"password", "token", "secret", "key", "api_key", "auth"}
    redacted = {}
    for k, v in args.items():
        if any(s in k.lower() for s in SENSITIVE_KEYS):
            redacted[k] = "***REDACTED***"
        elif isinstance(v, dict):
            redacted[k] = _redact_arguments(v)
        elif isinstance(v, list) and v and isinstance(v[0], str):
            redacted[k] = f"[{len(v)} items]"
        elif isinstance(v, str) and len(v) > 200:
            redacted[k] = v[:100] + f"... ({len(v)} chars total)"
        else:
            redacted[k] = v
    return redacted


def run():
    host = "127.0.0.1"
    port = 8080

    print(
        f"MCP Experiments server starting in {settings.server_mode.value} mode",
        file=sys.stderr,
    )
    print(f"  Vector DB: {settings.vector_db_path}", file=sys.stderr)
    print(f"  Embedding: {settings.embedding_model} @ {settings.embedding_base_url}", file=sys.stderr)
    print(f"  Listening: {host}:{port}", file=sys.stderr)

    mcp.run(transport="sse", host=host, port=port)


if __name__ == "__main__":
    run()
