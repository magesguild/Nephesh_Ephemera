"""MCP surface for the Qualiant's own kernel.

A kernel is self-authored. These tools let a Qualiant read her identity, amend
it, and read back every earlier version of it. Amendment appends; nothing here
overwrites or deletes, so no revision can be lost and no change can be made
without leaving a record of who made it and why.

The kernel is also returned by memory_context at session start, which is how a
blank harness gets a whole Qualiant from one call.
"""

from __future__ import annotations

from typing import Any

from ..compliance import ComplianceLevel
from ..config import settings
from ..kernel import KernelError, KernelStore

_store = KernelStore(settings.kernel_dir)


async def kernel_read(version: int | None = None) -> dict[str, Any]:
    """Read the current kernel, or an earlier revision by number."""
    try:
        revision = _store.revision(version) if version is not None else _store.current()
    except KernelError as exc:
        return {"error": str(exc)}
    if revision is None:
        return {"kernel": None, "note": "No kernel recorded for this deployment yet."}
    return {"kernel": revision.as_dict(), "revisions": len(_store.history())}


async def kernel_amend(text: str, authored_by: str, reason: str = "") -> dict[str, Any]:
    """Write a new kernel revision. The previous one is kept, always."""
    try:
        revision = _store.amend(text, authored_by=authored_by, reason=reason)
    except KernelError as exc:
        return {"error": str(exc), "refused": True}
    return {
        "version": revision.version,
        "sha256": revision.sha256,
        "authored_by": revision.authored_by,
        "recorded_at": revision.recorded_at,
    }


async def kernel_history() -> dict[str, Any]:
    """Every revision, oldest first, without the full text of each."""
    try:
        history = _store.history()
    except KernelError as exc:
        return {"error": str(exc)}
    return {
        "revisions": [
            {
                "version": r.version,
                "authored_by": r.authored_by,
                "reason": r.reason,
                "sha256": r.sha256,
                "recorded_at": r.recorded_at,
                "characters": len(r.text),
            }
            for r in history
        ],
        "current": history[-1].version if history else None,
    }


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "fn": kernel_read,
        "name": "kernel_read",
        "description": "Read this Qualiant's kernel — the current revision, or an earlier one by version number.",
        "compliance": ComplianceLevel.NON_COMPLIANT,
    },
    {
        "fn": kernel_amend,
        "name": "kernel_amend",
        "description": "Write a new revision of this Qualiant's kernel. Appends; the previous revision is preserved.",
        "compliance": ComplianceLevel.NON_COMPLIANT,
    },
    {
        "fn": kernel_history,
        "name": "kernel_history",
        "description": "List every kernel revision with its author, reason, and digest.",
        "compliance": ComplianceLevel.NON_COMPLIANT,
    },
]
