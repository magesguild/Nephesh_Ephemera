"""Deployment facts every Qualiant can inspect.

A Qualiant should be able to find out what she is actually running without
asking a human and without trusting her own memory, which is exactly where
stale version claims come from.
"""

from __future__ import annotations

import json
import re
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import httpx

from ..compliance import ComplianceLevel
from ..config import settings
from ..kernel import KernelError, KernelStore
from ..projection_registry import ProjectionRegistry
from ..recovery import RecoveryError, reconcile, summarize
from .vector_db import repository

#: Short enough that an info call cannot hang on a dead dependency.
_PROBE_TIMEOUT = 2.0


def _source_version() -> str | None:
    """The version of the source tree actually being imported, if findable.

    Distribution metadata describes what was installed, not what is running. A
    source-tree deployment can be several versions ahead of its own dist-info
    and report the stale number forever — which this tool was built to prevent
    and was itself doing.
    """
    for parent in Path(__file__).resolve().parents:
        pyproject = parent / "pyproject.toml"
        if pyproject.is_file():
            match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject.read_text(encoding="utf-8"), re.M)
            return match.group(1) if match else None
    return None


def _comparable_version(value: str) -> str:
    """Compare the project's display spelling with normalized package metadata."""
    return re.sub(r"[-.]rc$", "rc0", value.lower())


def _endpoint_reachable(url: str) -> bool | None:
    """Whether the embedding host answers at all. None if the probe itself failed.

    Deliberately named for what it measures. A reachable endpoint is not proof
    that embedding works — a healthy-looking Nephesh with dead embeddings is a
    failure we have actually lived through, and this must not be read as
    ruling it out.
    """
    try:
        with httpx.Client(timeout=_PROBE_TIMEOUT) as client:
            return client.get(url).status_code < 500
    except httpx.HTTPError:
        return False
    except Exception:
        return None


def nephesh_info() -> str:
    """Report what this deployment actually is, and whether it is whole."""
    try:
        installed = version("nephesh")
    except PackageNotFoundError:
        installed = "unknown"
    source = _source_version()

    info: dict[str, Any] = {
        "version": source or installed,
        "installed_version": installed,
        "source_version": source,
        # A disagreement means the running code is not the installed release.
        # During development that is correct and expected; on a live body it
        # is drift and should be looked at.
        "version_mismatch": bool(
            source
            and installed != "unknown"
            and _comparable_version(source) != _comparable_version(installed)
        ),
        "mode": str(settings.server_mode.value),
        "listener": {
            "host": settings.mcp_host,
            "port": settings.mcp_port,
            "tls_configured": settings.mcp_tls_enabled,
        },
        "embedding": {
            "model": settings.embedding_model,
            "base_url": settings.embedding_base_url,
            "endpoint_reachable": _endpoint_reachable(settings.embedding_base_url),
        },
        "paths": {
            "vector_db": settings.vector_db_path,
            "kernel": settings.kernel_dir,
            "operation_ledger": settings.operation_ledger_file,
            "projection_registry": settings.projection_registry_file,
            "memory_hygiene_guidance": settings.memory_hygiene_state_file,
        },
    }

    name = settings.memory_collection_name
    try:
        exists = repository.collection_exists(name)
        count = repository.count(repository.collection(name)) if exists else 0
        info["memory"] = {"collection": name, "exists": exists, "count": count}
    except Exception as exc:
        info["memory"] = {"collection": name, "error": str(exc)}

    try:
        current = KernelStore(settings.kernel_dir).current()
        info["kernel"] = (
            {"recorded": True, "version": current.version, "sha256": current.sha256,
             "authored_by": current.authored_by}
            if current else {"recorded": False}
        )
    except KernelError as exc:
        info["kernel"] = {"error": str(exc)}

    try:
        entries = ProjectionRegistry(settings.projection_registry_file).entries(
            repository.collections()
        )
        info["projections"] = {
            "installed": len(entries),
            "active": [e["namespace"] for e in entries if e["reported_state"] == "active"],
            "drift": [e["namespace"] for e in entries if e["drift"]],
        }
    except Exception as exc:
        info["projections"] = {"error": str(exc)}

    return json.dumps(info, indent=2)


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
        "description": "Report what this Nephesh deployment actually is: version, mode, listener, embedding endpoint, memory, kernel, and installed knowledge projections.",
        "compliance": ComplianceLevel.NON_COMPLIANT,
    },
    {
        "fn": nephesh_recovery_report,
        "name": "nephesh_recovery_report",
        "description": "Reconcile the operation ledger against the store: which durable writes were left unresolved, and which of them actually landed.",
        "compliance": ComplianceLevel.NON_COMPLIANT,
    },
]
