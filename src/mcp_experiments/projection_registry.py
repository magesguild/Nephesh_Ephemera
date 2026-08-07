"""Durable record of which knowledge projections exist and what state they are in.

The operation ledger records that things happened. Nothing in Nephesh could
answer the question a lifecycle depends on: *what is active now.* Rollback in
docs/NEPHESH_KNOWLEDGE_PROJECTION_ADAPTER_5.0.0.md section 6 is a pointer move,
and a pointer needs something that knows where it currently points. Without
this, a rollback naming a deleted version would open a fresh empty collection
through the ordinary create-or-open path and report it as active.

The governing property of this module: **a read cannot be performed without
being handed the set of collections that actually exist.** Reality is a required
argument, not an option with a default, so there is no call shape that reports a
registry's own claim as if it were the state of the store. A registry that can
only be asked "what do you believe" will eventually be believed.

Two limitations are recorded in the schema rather than implied:

- ``activated_by`` is written and is NOT enforced. Nephesh 5.0.0 has no
  mechanism that can verify who authorized an activation. The field exists so
  the gap is visible to an auditor instead of being assumed closed.
- Staging and activation are separate states with separate transitions, because
  an automatic pull may stage and must never activate.

This module records. It does not stage, import, activate, or delete anything.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, Iterable

from .projection import ProjectionError, guard_projection_target


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RegistryError(ProjectionError):
    """A registry operation was refused."""


class ProjectionState(StrEnum):
    """States a projection may be recorded in.

    ORPHANED and UNREGISTERED are deliberately absent: they are conclusions
    drawn by comparing this record against the store, never values written into
    it. A drift state that could be persisted could also be forged.
    """

    STAGED = "staged"
    ACTIVE = "active"
    RETIRED = "retired"
    FAILED = "failed"
    ROLLBACK_TARGET = "rollback_target"


#: Reported-only states. Produced by reconciliation, never stored.
ORPHANED = "orphaned"
UNREGISTERED = "unregistered"

#: Legal transitions. A registry that silently accepts any transition cannot be
#: used to reason about history, and rollback is exactly a history question.
_TRANSITIONS: dict[ProjectionState, frozenset[ProjectionState]] = {
    ProjectionState.STAGED: frozenset({ProjectionState.ACTIVE, ProjectionState.FAILED, ProjectionState.RETIRED}),
    ProjectionState.ACTIVE: frozenset({ProjectionState.ROLLBACK_TARGET, ProjectionState.RETIRED}),
    ProjectionState.ROLLBACK_TARGET: frozenset({ProjectionState.ACTIVE, ProjectionState.RETIRED}),
    ProjectionState.RETIRED: frozenset({ProjectionState.STAGED}),
    ProjectionState.FAILED: frozenset({ProjectionState.STAGED}),
}


@dataclass
class ProjectionRecord:
    """One durable statement about one projection namespace."""

    package_id: str
    version: str
    namespace: str
    state: ProjectionState
    owner: str
    manifest_sha256: str = ""
    publisher: str = ""
    records: int = 0
    chunks: int = 0
    embedding_model: str = ""
    embedding_dimensions: int = 0
    embedding_dtype: str = ""
    embedding_endianness: str = ""
    source_path: str = ""
    # Recorded, NOT enforced in 5.0.0. See the module docstring.
    activated_by: str = ""
    supersedes: str = ""
    note: str = ""
    recorded_at: str = field(default_factory=_now)

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["state"] = self.state.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProjectionRecord:
        payload = dict(data)
        payload["state"] = ProjectionState(payload["state"])
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in payload.items() if k in known})


class ProjectionRegistry:
    """Append-only JSONL registry of knowledge projections, with a reader.

    Append-only for the same reason the operation ledger is: a truncated or
    partially rewritten file loses history that rollback depends on. The current
    state of a namespace is the last record written for it.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    # ------------------------------------------------------------------ write

    def _append(self, record: ProjectionRecord) -> ProjectionRecord:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record.as_dict(), sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return record

    def record(self, record: ProjectionRecord) -> ProjectionRecord:
        """Write the first statement about a namespace.

        Refuses a namespace that is not a projection, and refuses to re-declare
        one that is already known — a second first-statement would silently
        rewrite provenance that a later rollback reads.
        """
        guard_projection_target(record.namespace)
        if not record.package_id or not record.version:
            raise RegistryError("package_id and version are required")
        if not record.owner:
            raise RegistryError(f"projection {record.namespace!r} must record an owner")
        history = self._history()
        if record.namespace in history:
            raise RegistryError(
                f"{record.namespace!r} is already registered to "
                f"{history[record.namespace].package_id!r}; use transition() to change its state"
            )
        for known in history.values():
            if known.package_id == record.package_id and known.version == record.version:
                raise RegistryError(
                    f"{record.package_id} {record.version} is already registered as {known.namespace!r}"
                )
        return self._append(record)

    def transition(
        self,
        namespace: str,
        state: ProjectionState,
        *,
        activated_by: str = "",
        note: str = "",
    ) -> ProjectionRecord:
        """Move a known namespace to a new state, refusing illegal moves."""
        guard_projection_target(namespace)
        current = self._history().get(namespace)
        if current is None:
            raise RegistryError(f"{namespace!r} is not registered")
        if state not in _TRANSITIONS[current.state]:
            raise RegistryError(
                f"cannot move {namespace!r} from {current.state.value} to {state.value}"
            )
        if state is ProjectionState.ACTIVE:
            self._require_no_other_active(current.package_id, namespace)
        successor = ProjectionRecord(**{
            **{k: v for k, v in current.as_dict().items() if k not in ("state", "recorded_at")},
            "state": state,
        })
        successor.activated_by = activated_by or (current.activated_by if state is ProjectionState.ACTIVE else "")
        successor.note = note
        return self._append(successor)

    def _require_no_other_active(self, package_id: str, namespace: str) -> None:
        """One active version per package. Two would make "what is active" ambiguous."""
        for known in self._history().values():
            if (
                known.package_id == package_id
                and known.namespace != namespace
                and known.state is ProjectionState.ACTIVE
            ):
                raise RegistryError(
                    f"{package_id} is already active as {known.namespace!r}; "
                    "retire or demote it before activating another version"
                )

    # ------------------------------------------------------------------- read

    def _history(self) -> dict[str, ProjectionRecord]:
        """Fold the append-only log to the latest record per namespace."""
        if not self.path.is_file():
            return {}
        latest: dict[str, ProjectionRecord] = {}
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = ProjectionRecord.from_dict(json.loads(line))
            except (ValueError, KeyError, TypeError) as exc:
                raise RegistryError(f"projection registry contains an unreadable record: {exc}") from exc
            latest[record.namespace] = record
        return latest

    def entries(self, existing_collections: Iterable[str]) -> list[dict[str, Any]]:
        """Report every projection, reconciled against the store.

        ``existing_collections`` is required. There is deliberately no way to
        ask this registry what it believes without also telling it what is
        actually there, because the two can differ and the difference is the
        only thing worth reporting.

        Each entry carries ``recorded_state`` (what the log says),
        ``reported_state`` (what is true given the store), and ``drift``.
        """
        present = set(existing_collections)
        history = self._history()
        entries: list[dict[str, Any]] = []

        for namespace, record in sorted(history.items()):
            data = record.as_dict()
            recorded = record.state.value
            exists = namespace in present
            # A retired or failed projection is not expected to have a live
            # collection, so its absence is not drift. Any other state claims
            # the rows are there.
            expects_collection = record.state in (
                ProjectionState.STAGED,
                ProjectionState.ACTIVE,
                ProjectionState.ROLLBACK_TARGET,
            )
            reported = recorded
            if expects_collection and not exists:
                reported = ORPHANED
            data["recorded_state"] = recorded
            data["reported_state"] = reported
            data["collection_present"] = exists
            data["drift"] = reported != recorded
            data.pop("state", None)
            entries.append(data)

        # The inverse drift: projection collections nobody registered. An
        # unregistered projection is not a registry error, but reporting only
        # what the log knows would hide it, and hiding it is how a manual
        # import becomes invisible state.
        for namespace in sorted(present):
            if namespace in history or not namespace.startswith("kp__"):
                continue
            entries.append({
                "namespace": namespace,
                "recorded_state": None,
                "reported_state": UNREGISTERED,
                "collection_present": True,
                "drift": True,
            })
        return entries

    def active(self, existing_collections: Iterable[str]) -> list[dict[str, Any]]:
        """The projections that are genuinely active — recorded AND present."""
        return [e for e in self.entries(existing_collections) if e["reported_state"] == ProjectionState.ACTIVE.value]

    def resolve(self, namespace: str, existing_collections: Iterable[str]) -> dict[str, Any]:
        """Report one namespace, reconciled. Raises if it was never registered."""
        for entry in self.entries(existing_collections):
            if entry["namespace"] == namespace:
                return entry
        raise RegistryError(f"{namespace!r} is not registered")
