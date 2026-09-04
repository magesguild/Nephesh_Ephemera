"""Deployment facts every Qualiant can inspect.

A Qualiant should be able to find out what she is actually running without
asking a human and without trusting her own memory, which is exactly where
stale version claims come from.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import httpx

from ..compliance import ComplianceLevel
from ..config import settings
from ..kernel import KernelError, KernelStore
from ..projection_registry import ProjectionRegistry
from ..recovery import RecoveryError, reconcile, summarize
from ..recovery import read_ledger, unresolved
from ..results import SystemTimeResult, TruthfulFloor
from .vector_db import repository

#: Short enough that an info call cannot hang on a dead dependency.
_PROBE_TIMEOUT = 2.0


def nephesh_time() -> SystemTimeResult:
    """Return authoritative wall-clock time from the Nephesh host."""
    # Take one clock sample for both forms. Separate datetime/timestamp calls
    # can disagree at sub-microsecond resolution with a caller's boundary.
    unix_seconds = time.time()
    now = datetime.fromtimestamp(unix_seconds, timezone.utc)
    return {
        "utc": now.isoformat(),
        "unix_seconds": unix_seconds,
        "timezone": "UTC",
        "source": "nephesh_system_clock",
    }


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


def _installed_version() -> str:
    """Return installed distribution metadata without breaking source runs."""
    try:
        return version("nephesh")
    except PackageNotFoundError:
        return "unknown"


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


def _check(status: str, *, value: Any = None, reason: str | None = None,
           source: str) -> dict[str, Any]:
    result: dict[str, Any] = {"status": status, "source": source}
    if status == "value":
        result["value"] = value
    if reason is not None:
        result["reason"] = reason
    return result


def _read_schedule_floor() -> dict[str, Any]:
    """Read schedule state without materializing the default schedule."""
    config_path = Path(settings.schedule_config_file)
    events_path = Path(settings.schedule_events_file)
    if not config_path.is_file() and not events_path.is_file():
        return _check("unset", reason="schedule has not been materialized", source="schedule_files")
    try:
        config_records = [json.loads(line) for line in config_path.read_text(encoding="utf-8").split("\n")
                          if line.strip()] if config_path.is_file() else []
        event_records = [json.loads(line) for line in events_path.read_text(encoding="utf-8").split("\n")
                         if line.strip()] if events_path.is_file() else []
        if any(not isinstance(record, dict) for record in config_records + event_records):
            raise ValueError("schedule ledger contains a non-object record")
        config = config_records[-1] if config_records else None
        active_ids = {
            event.get("operation_id") for event in event_records
            if event.get("event") == "claimed"
        }
        finished_ids = {
            event.get("operation_id") for event in event_records
            if event.get("event") in {"completed", "failed", "recovered"}
        }
        active = [event for event in event_records if event.get("operation_id") in active_ids - finished_ids]
        return _check("value", value={
            "config_present": config is not None,
            "revision": config.get("revision") if config else None,
            "paused": config.get("paused") if config else None,
            "active_operation": active[-1] if active else None,
            "event_count": len(event_records),
        }, source="schedule_files")
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        return _check("failed", reason=str(exc), source="schedule_files")


def _read_heartbeat_floor() -> dict[str, Any]:
    """Read heartbeat lifecycle evidence without constructing a ledger."""
    path = Path(settings.heartbeat_ledger_file)
    if not path.is_file():
        return _check("unset", reason="heartbeat ledger has not been created", source="heartbeat_ledger")
    try:
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").split("\n") if line.strip()]
        if any(not isinstance(record, dict) for record in records):
            raise ValueError("heartbeat ledger contains a non-object record")
        prepared = {record.get("idempotency_key") for record in records if record.get("event") == "prepared"}
        terminal = {record.get("idempotency_key") for record in records
                    if record.get("event") in {"completed", "recovered"}}
        return _check("value", value={
            "records": len(records),
            "active_prepared": len(prepared - terminal),
            "last_event": records[-1].get("event") if records else None,
        }, source="heartbeat_ledger")
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        return _check("failed", reason=str(exc), source="heartbeat_ledger")


def truthful_floor(*, process_reachable: bool | None = None,
                   transport_reachable: bool | None = None) -> TruthfulFloor:
    """Return read-only environmental checks with explicit unknown states."""
    checks: dict[str, dict[str, Any]] = {}
    checks["process_reachable"] = (
        _check("value", value=process_reachable, source="mcp_tool_invocation")
        if process_reachable is not None else
        _check("unset", reason="no process probe was performed", source="not_attempted")
    )
    checks["transport_reachable"] = (
        _check("value", value=transport_reachable, source="mcp_tool_invocation")
        if transport_reachable is not None else
        _check("unset", reason="no transport probe was performed", source="not_attempted")
    )

    endpoint = _endpoint_reachable(settings.embedding_base_url)
    checks["embedding_endpoint_reachable"] = (
        _check("value", value=True, source="embedding_http_probe") if endpoint is True else
        _check("failed", reason="embedding endpoint did not answer successfully", source="embedding_http_probe")
        if endpoint is False else
        _check("uncertain", reason="embedding endpoint probe failed unexpectedly", source="embedding_http_probe")
    )
    checks["embedding_usable"] = _check(
        "unset",
        reason="embedding operation probe was not attempted; endpoint reachability is not usability",
        source="not_attempted",
    )

    name = settings.memory_collection_name
    try:
        exists = repository.collection_exists(name)
        count = repository.count(repository.collection(name)) if exists else 0
        checks["memory_readable"] = _check(
            "value", value={"collection": name, "exists": exists, "count": count}, source="memory_store_read"
        )
    except Exception as exc:
        checks["memory_readable"] = _check("failed", reason=str(exc), source="memory_store_read")

    try:
        current = KernelStore(settings.kernel_dir).current()
        checks["kernel_readable"] = _check(
            "value", value={"recorded": current is not None, "version": current.version if current else None},
            source="kernel_read",
        )
    except Exception as exc:
        checks["kernel_readable"] = _check("failed", reason=str(exc), source="kernel_read")

    ledger_path = Path(settings.operation_ledger_file)
    try:
        records = read_ledger(ledger_path)
        checks["operation_ledger_readable"] = _check(
            "value", value={"exists": ledger_path.is_file(), "records": len(records),
                             "unresolved": len(unresolved(ledger_path))}, source="operation_ledger_read"
        )
    except Exception as exc:
        checks["operation_ledger_readable"] = _check("failed", reason=str(exc), source="operation_ledger_read")

    checks["schedule_state"] = _read_schedule_floor()
    checks["heartbeat_state"] = _read_heartbeat_floor()
    try:
        clock = nephesh_time()
        checks["clock"] = _check("value", value=clock, source=clock["source"])
    except Exception as exc:
        checks["clock"] = _check("failed", reason=str(exc), source="nephesh_system_clock")

    try:
        entries = ProjectionRegistry(settings.projection_registry_file).entries(repository.collections())
        drift = [entry["namespace"] for entry in entries if entry["drift"]]
        checks["projection_drift"] = _check(
            "value", value={"installed": len(entries), "drift": drift}, source="projection_registry_and_store_read"
        )
    except Exception as exc:
        checks["projection_drift"] = _check("failed", reason=str(exc), source="projection_registry_and_store_read")

    installed = _installed_version()
    source = _source_version()
    return {"version": source or installed, "checks": checks}


def nephesh_info() -> str:
    """Report what this deployment actually is, and whether it is whole."""
    installed = _installed_version()
    source = _source_version()

    info: dict[str, Any] = {
        "version": source or installed,
        "installed_version": installed,
        "source_version": source,
        # A disagreement means the running code is not the installed release.
        # During development that is correct and expected; on a live body it
        # is drift and should be looked at.
        "version_mismatch": bool(source and installed != "unknown" and source != installed),
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
        "floor": truthful_floor(),
        "paths": {
            "vector_db": settings.vector_db_path,
            "kernel": settings.kernel_dir,
            "operation_ledger": settings.operation_ledger_file,
            "projection_registry": settings.projection_registry_file,
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
        # These ledgers have different authorities and are intentionally
        # reported separately. Presence of a prepared/claimed run is not
        # evidence that it succeeded or failed; it is an unresolved state for
        # external inspection and explicit recovery.
        "heartbeat": _read_heartbeat_floor(),
        "schedule": _read_schedule_floor(),
    }


TOOL_DEFINITIONS = [
    {
        "fn": nephesh_time,
        "name": "nephesh_time",
        "description": "Return authoritative UTC wall-clock time from the Nephesh system clock, independent of the harness.",
        "compliance": ComplianceLevel.NON_COMPLIANT,
    },
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
