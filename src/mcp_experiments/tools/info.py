"""Small deployment facts that every Qualiant can inspect."""

from __future__ import annotations

import json
from importlib.metadata import PackageNotFoundError, version

from ..compliance import ComplianceLevel


def nephesh_info() -> str:
    """Return the installed Nephesh package version."""
    try:
        current = version("nephesh")
    except PackageNotFoundError:
        current = "unknown"
    return json.dumps({"version": current}, indent=2)


TOOL_DEFINITIONS = [
    {
        "fn": nephesh_info,
        "name": "nephesh_info",
        "description": "Return the installed Nephesh version.",
        "compliance": ComplianceLevel.NON_COMPLIANT,
    },
]
