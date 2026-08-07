from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from ..compliance import ComplianceLevel, ServerMode, is_tool_available_in_mode
from ..config import settings
from .. import orientation
from . import info, kernel, memory, projection, vector_db

_TOOL_MODULES = [vector_db, memory, kernel, projection, info]


def register_all(app: FastMCP) -> None:
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


def get_registered_names() -> list[str]:
    names: list[str] = []
    for mod in _TOOL_MODULES:
        if hasattr(mod, "TOOL_DEFINITIONS"):
            for t in mod.TOOL_DEFINITIONS:
                names.append(t["name"])
    return names
