"""Small deployment facts that every Qualiant can inspect."""

from __future__ import annotations

import json
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from ..compliance import ComplianceLevel
from ..config import settings
from ..recovery import RecoveryError, reconcile, summarize
from .vector_db import repository


def nephesh_info() -> str:
    """Return the installed Nephesh package version."""
    try:
        current = version("nephesh")
    except PackageNotFoundError:
        current = "unknown"
    return json.dumps({"version": current}, indent=2)


async def nephesh_recovery_report() -> dict[str, Any]:
    """Reconcile the operation ledger against the store.

    Answers the question an uncertain write leaves open: did it land? Every
    unresolved operation is checked against the actual rows rather than
    trusted. Operations this cannot check are reported unverifiable rather
    than assumed fine — a recovery report that quietly passes the uncheckable
    cases is worse than none, because it will be believed.
    """
    name = settings.memory_collection_name
    try:
        if repository.collection_exists(name):
            table = repository.collection(name)
            known = {r["id"] for r in repository.rows(table, repository.count(table))}
        else:
            known = set()
    except Exception as exc:
        return {"error": f"store could not be read: {exc}"}

    try:
        report = reconcile(settings.operation_ledger_file, lambda target: target in known)
    except RecoveryError as exc:
        return {"error": str(exc)}

    return {
        "ledger": settings.operation_ledger_file,
        "collection": name,
        **summarize(report),
        "operations": report,
    }


TOOL_DEFINITIONS = [
    {
        "fn": nephesh_info,
        "name": "nephesh_info",
        "description": "Return the installed Nephesh version.",
        "compliance": ComplianceLevel.NON_COMPLIANT,
    },
    {
        "fn": nephesh_recovery_report,
        "name": "nephesh_recovery_report",
        "description": "Reconcile the operation ledger against the store: which durable writes were left unresolved, and which of them actually landed.",
        "compliance": ComplianceLevel.NON_COMPLIANT,
    },
]
