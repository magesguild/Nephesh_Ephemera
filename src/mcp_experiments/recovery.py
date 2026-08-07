"""Read the operation ledger back and reconcile it against the store.

The ledger has recorded prepared/completed/uncertain/failed since the first
rebuild pass, and nothing has ever read it. An uncertain write is only useful
if something can later ask what became of it; without a reader, honest
uncertainty is recorded and then lost, which is the same outcome as not
recording it.

Two questions this answers:

- *What was left unresolved?* Operations whose last recorded state is prepared
  (a process died mid-write) or uncertain (a durable write may or may not have
  landed).
- *What actually happened?* Each unresolved operation is checked against the
  store. A ledger entry is evidence about an intention, never about an outcome.

The presence check is injected rather than imported so a drill can run without
opening a deployment-owned store.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from .persistence import OperationState, read_jsonl_lines

#: Last states that need no follow-up.
_RESOLVED = frozenset({OperationState.COMPLETED, OperationState.FAILED})

#: What reconciliation concluded, as distinct from what the ledger claimed.
LANDED = "landed"
ABSENT = "absent"
UNVERIFIABLE = "unverifiable"


class RecoveryError(RuntimeError):
    """The ledger could not be read."""


def read_ledger(path: str | Path) -> list[dict[str, Any]]:
    """Every ledger line, in file order."""
    ledger = Path(path)
    if not ledger.is_file():
        return []
    records: list[dict[str, Any]] = []
    for line in read_jsonl_lines(ledger.read_text(encoding="utf-8")):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except ValueError as exc:
            raise RecoveryError(f"operation ledger contains an unreadable record: {exc}") from exc
    return records


def latest_by_operation(path: str | Path) -> dict[str, dict[str, Any]]:
    """Fold the append-only ledger to the last state of each operation."""
    latest: dict[str, dict[str, Any]] = {}
    for record in read_ledger(path):
        operation_id = record.get("operation_id")
        if operation_id:
            latest[operation_id] = record
    return latest


def unresolved(path: str | Path) -> list[dict[str, Any]]:
    """Operations that never reached a settled state.

    ``prepared`` means the process stopped between intent and outcome.
    ``uncertain`` means the write was attempted and its result is unknown.
    Both need a human or a drill to look, which is what this list is for.
    """
    return [
        record
        for record in latest_by_operation(path).values()
        if record.get("state") not in {s.value for s in _RESOLVED}
    ]


def reconcile(
    path: str | Path,
    row_exists: Callable[[str], bool],
) -> list[dict[str, Any]]:
    """Check each unresolved operation against the store and say what is true.

    ``row_exists`` is called with the operation's target and answers whether
    that row is present. Operations whose target is not a row — anything this
    module cannot check — are reported UNVERIFIABLE rather than guessed at. A
    recovery report that quietly assumes the uncheckable cases went fine is
    worse than no report, because it will be believed.
    """
    report: list[dict[str, Any]] = []
    for record in sorted(unresolved(path), key=lambda r: r.get("created_at", "")):
        target = record.get("target", "")
        try:
            present = row_exists(target)
            conclusion = LANDED if present else ABSENT
        except Exception as exc:  # a store that cannot answer must not be guessed at
            present = None
            conclusion = UNVERIFIABLE
            record = {**record, "check_error": str(exc)}
        report.append({
            "operation_id": record.get("operation_id"),
            "operation": record.get("operation"),
            "target": target,
            "recorded_state": record.get("state"),
            "created_at": record.get("created_at"),
            "updated_at": record.get("updated_at"),
            "details": record.get("details", {}),
            "target_present": present,
            "conclusion": conclusion,
        })
    return report


def summarize(report: list[dict[str, Any]]) -> dict[str, Any]:
    """A one-line answer to 'is this store consistent with its ledger?'"""
    counts: dict[str, int] = {}
    for entry in report:
        counts[entry["conclusion"]] = counts.get(entry["conclusion"], 0) + 1
    return {
        "unresolved": len(report),
        "by_conclusion": counts,
        # Clean means nothing needs a decision, not merely that nothing failed.
        "clean": len(report) == 0,
    }
