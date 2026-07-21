from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from ..compliance import ComplianceLevel, ServerMode, is_tool_available_in_mode
from ..config import settings
from . import memory, vector_db

_TOOL_MODULES = [vector_db, memory]

# Conditionally register OpenClaw bridge tools when enabled.
if settings.openclaw_enabled:
    from . import openclaw_sync
    _TOOL_MODULES.append(openclaw_sync)


def register_all(app: FastMCP) -> None:
    for mod in _TOOL_MODULES:
        if hasattr(mod, "TOOL_DEFINITIONS"):
            for t in mod.TOOL_DEFINITIONS:
                compliance: ComplianceLevel = t.get("compliance", ComplianceLevel.NON_COMPLIANT)
                ok, reason = is_tool_available_in_mode(t["name"], compliance, settings.server_mode)
                if not ok:
                    continue

                app.add_tool(
                    fn=t["fn"],
                    name=t["name"],
                    description=t["description"],
                )


def get_registered_names() -> list[str]:
    names: list[str] = []
    for mod in _TOOL_MODULES:
        if hasattr(mod, "TOOL_DEFINITIONS"):
            for t in mod.TOOL_DEFINITIONS:
                names.append(t["name"])
    return names
