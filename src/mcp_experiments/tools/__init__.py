from __future__ import annotations

from typing import Any

from ..compliance import ComplianceLevel, ServerMode, is_tool_available_in_mode
from ..config import settings
from . import vector_db

_TOOL_MODULES = [vector_db]


def get_all_tools() -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = []
    for mod in _TOOL_MODULES:
        if hasattr(mod, "get_tool_registrations"):
            tools.extend(mod.get_tool_registrations())
    return tools


def get_available_tools() -> list[dict[str, Any]]:
    all_tools = get_all_tools()
    available = []
    for t in all_tools:
        compliance = t.get("compliance", ComplianceLevel.NON_COMPLIANT)
        ok, reason = is_tool_available_in_mode(
            t["name"], compliance, settings.server_mode
        )
        if ok:
            available.append(t)
    return available


async def handle_tool_call(name: str, arguments: dict[str, Any]) -> str:
    for mod in _TOOL_MODULES:
        if hasattr(mod, "handle_tool_call"):
            try:
                return await mod.handle_tool_call(name, arguments)
            except ValueError:
                continue
    raise ValueError(f"Unknown tool: {name}")
