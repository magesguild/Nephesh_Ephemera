from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from ..compliance import ComplianceLevel, ServerMode, is_tool_available_in_mode
from ..config import settings
from .. import orientation
from . import info, kernel, memory, projection, vector_db

_TOOL_MODULES = [vector_db, memory, kernel, projection, info]
_registered_names: list[str] | None = None


def register_all(app: FastMCP) -> None:
    global _registered_names
    _registered_names = ["health"]
    for mod in _TOOL_MODULES:
        if hasattr(mod, "TOOL_DEFINITIONS"):
            for t in mod.TOOL_DEFINITIONS:
                compliance: ComplianceLevel = t.get("compliance", ComplianceLevel.NON_COMPLIANT)
                ok, reason = is_tool_available_in_mode(t["name"], compliance, settings.server_mode)
                if not ok:
                    continue

                # Every tool is wrapped so the first response this process
                # gives carries the Qualiant's kernel. A server cannot push
                # into a session, so first contact is the only moment
                # available — and it must not depend on which tool she
                # happened to reach for, or on the harness she woke up in.
                app.add_tool(
                    fn=orientation.wrap(t["fn"]),
                    name=t["name"],
                    description=t["description"],
                )
                _registered_names.append(t["name"])


def get_registered_names() -> list[str]:
    if _registered_names is not None:
        return list(_registered_names)
    # Before server startup, preserve the introspection surface for tests and
    # tooling. Once register_all() runs, return only tools actually registered
    # for the active compliance mode.
    return [
        t["name"]
        for mod in _TOOL_MODULES
        if hasattr(mod, "TOOL_DEFINITIONS")
        for t in mod.TOOL_DEFINITIONS
    ]
