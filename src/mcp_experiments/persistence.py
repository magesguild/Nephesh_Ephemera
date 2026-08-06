"""Small persistence boundary for the Nephesh 5 rebuild.

This module deliberately preserves the current LanceDB representation. It is
an ownership seam, not a schema migration: existing memory stores may contain
multiple generations of rows and readers must remain tolerant of that shape.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any

import lancedb
import pyarrow as pa


def matches_filter(metadata: dict, where: dict) -> bool:
    """Evaluate the legacy metadata filter shape without changing its meaning."""
    for key, value in where.items():
        if key == "$and":
            if not all(matches_filter(metadata, sub) for sub in value):
                return False
        elif key == "$or":
            if not any(matches_filter(metadata, sub) for sub in value):
                return False
        elif isinstance(value, dict):
            for op, val in value.items():
                if op == "$gte" and metadata.get(key, float("-inf")) < val:
                    return False
                elif op == "$lte" and metadata.get(key, float("inf")) > val:
                    return False
                elif op == "$ne" and metadata.get(key) == val:
                    return False
                elif op == "$eq" and metadata.get(key) != val:
                    return False
                elif op == "$in" and metadata.get(key) not in val:
                    return False
                elif op == "$nin" and metadata.get(key) in val:
                    return False
        elif metadata.get(key) != value:
            return False
    return True


class PersistenceError(RuntimeError):
    """Base class for storage and persistence-boundary failures."""


class PersistenceNotInitialized(PersistenceError):
    """Raised when a repository is used before deployment initialization."""


class DurableWriteError(PersistenceError):
    """Raised when a durable append or update cannot be completed."""


class OperationState(StrEnum):
    PREPARED = "prepared"
    COMPLETED = "completed"
    UNCERTAIN = "uncertain"
    FAILED = "failed"


@dataclass
class OperationRecord:
    """A durable, inspectable record of a persistence-side operation."""

    operation: str
    target: str
    state: OperationState = OperationState.PREPARED
    operation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    details: dict[str, Any] = field(default_factory=dict)

    def transition(self, state: OperationState, **details: Any) -> None:
        self.state = state
        self.updated_at = datetime.now(timezone.utc).isoformat()
        self.details.update(details)

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["state"] = self.state.value
        return data


class OperationLedger:
    """Append-only JSONL ledger for recovery and integrity inspection."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def append(self, record: OperationRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record.as_dict(), sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def begin(self, operation: str, target: str, **details: Any) -> OperationRecord:
        record = OperationRecord(operation=operation, target=target, details=details)
        self.append(record)
        return record

    def transition(self, record: OperationRecord, state: OperationState, **details: Any) -> None:
        record.transition(state, **details)
        self.append(record)


class PersistenceRepository:
    """Own the database/table boundary while preserving the existing schema."""

    def __init__(self, schema: pa.Schema) -> None:
        self._schema = schema
        self._db: lancedb.db.LanceDBConnection | None = None
        self._embedder: Any | None = None
        self._ledger: OperationLedger | None = None

    def configure(
        self,
        db: lancedb.db.LanceDBConnection,
        embedder: Any,
        operation_ledger_path: str | Path | None = None,
    ) -> None:
        self._db = db
        self._embedder = embedder
        self._ledger = OperationLedger(operation_ledger_path) if operation_ledger_path else None

    def begin_operation(self, operation: str, target: str, **details: Any) -> OperationRecord | None:
        if self._ledger is None:
            return None
        return self._ledger.begin(operation, target, **details)

    def transition_operation(
        self,
        record: OperationRecord | None,
        state: OperationState,
        **details: Any,
    ) -> None:
        if record is not None and self._ledger is not None:
            self._ledger.transition(record, state, **details)

    def db(self) -> lancedb.db.LanceDBConnection:
        if self._db is None:
            raise PersistenceNotInitialized("persistence repository is not initialized")
        return self._db

    def embedder(self) -> Any:
        if self._embedder is None:
            raise PersistenceNotInitialized("persistence repository is not initialized")
        return self._embedder

    def table(self, name: str):
        db = self.db()
        if name in db.list_tables().tables:
            return db.open_table(name)
        return db.create_table(name, schema=self._schema)

    def has_table(self, name: str) -> bool:
        return name in self.db().list_tables().tables

    def open_table(self, name: str):
        db = self.db()
        if not self.has_table(name):
            raise KeyError(f"collection '{name}' not found")
        return db.open_table(name)

    def collection_exists(self, name: str) -> bool:
        return self.has_table(name)

    def collection(self, name: str):
        return self.open_table(name)

    def collections(self) -> list[str]:
        return sorted(self.db().list_tables().tables)

    def drop_collection(self, name: str) -> None:
        try:
            self.db().drop_table(name)
        except Exception as exc:
            raise PersistenceError(f"collection drop failed: {name}") from exc

    @staticmethod
    def delete(table, predicate: str) -> None:
        try:
            table.delete(predicate)
        except Exception as exc:
            raise DurableWriteError("durable delete failed") from exc

    @staticmethod
    def count(table) -> int:
        return table.count_rows()

    @staticmethod
    def rows(table, limit: int | None = None) -> list[dict[str, Any]]:
        query = table.search()
        if limit is not None:
            query = query.limit(limit)
        return query.to_list()

    @staticmethod
    def nearest(table, vector: list[float], limit: int) -> list[dict[str, Any]]:
        return table.search(vector).limit(limit).to_list()

    @staticmethod
    def add(table, records: list[dict[str, Any]]) -> None:
        try:
            table.add(records)
        except Exception as exc:
            raise DurableWriteError("durable append failed") from exc

    @staticmethod
    def update(table, *, where: str, values: dict[str, Any]) -> None:
        try:
            table.update(where=where, values=values)
        except Exception as exc:
            raise DurableWriteError("durable update failed") from exc
