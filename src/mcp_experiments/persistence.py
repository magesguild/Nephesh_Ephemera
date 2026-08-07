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


def _fsync_directory(directory: Path) -> None:
    """Make a newly created file's directory entry durable.

    os.fsync on a file descriptor forces that file's DATA to disk and says
    nothing about the directory entry naming it. For a file that already
    existed this does not matter; for one just created, the write can be
    durable while the file itself is absent after power loss — the first
    record of a new ledger surviving fsync and then not being there.

    Not every platform permits opening a directory, so failure here is
    tolerated rather than fatal: the data write already succeeded.
    """
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def durable_append(path: Path, line: str) -> None:
    """Append one line, all-or-nothing, and make it survive power loss.

    A short write — out of space, over quota, over a file-size limit — leaves
    the bytes that did land committed to an append-only file with no trailing
    newline. Every reader here deliberately refuses an unreadable line rather
    than skipping it, so a single torn record would make the file permanently
    unreadable: not a lost write but a lost kernel, or a lost registry. On
    failure the file is rolled back to its last whole record.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    created = not path.exists()
    committed = 0 if created else path.stat().st_size
    try:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        try:
            with path.open("r+b") as handle:
                handle.truncate(committed)
                handle.flush()
                os.fsync(handle.fileno())
        except OSError:
            pass  # nothing further we can do; the caller still sees the error
        raise
    if created:
        _fsync_directory_chain(path.parent)


def durable_write_new(path: Path, text: str) -> None:
    """Create a file that did not exist, atomically and durably.

    Written to a temporary name and renamed, so a reader never sees a partial
    file under the real name. Refuses to overwrite: the callers here keep
    append-only histories where an existing name is always a bug.
    """
    if path.exists():
        raise FileExistsError(f"refusing to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".partial")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    _fsync_directory_chain(path.parent)


def _fsync_directory_chain(directory: Path) -> None:
    """Commit a new file's whole path, not just its immediate parent.

    fsync of a directory makes the names *inside* it durable, not the name of
    the directory itself. A just-created state/ can therefore be absent after
    power loss and take the carefully fsynced ledger inside it along. Runs only
    on the first write to a new file; fsync of an already-durable directory
    costs nothing.
    """
    current = directory
    while True:
        _fsync_directory(current)
        if current.parent == current:
            return
        current = current.parent


def read_jsonl_lines(text: str) -> list[str]:
    """Split JSONL on newlines only.

    str.splitlines() also breaks on \\x0b, \\x0c, \\x1c, \\x1d, \\x1e, \\x85,
    \\u2028 and \\u2029. json.dumps escapes all of those under its default
    ensure_ascii=True, but Lore writes records.jsonl with ensure_ascii=False,
    which leaves \\x85, \\u2028 and \\u2029 literal. Reading such a file with
    splitlines() would cut a record in half. read_text() has already
    normalised \\r\\n and \\r, so splitting on \\n alone is both correct and
    free of that coupling.
    """
    return text.split("\n")


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
        durable_append(self.path, json.dumps(record.as_dict(), sort_keys=True) + "\n")

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
