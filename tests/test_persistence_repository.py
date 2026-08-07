from __future__ import annotations

import unittest
import json
import tempfile
from pathlib import Path

import pyarrow as pa

from mcp_experiments.persistence import (
    DurableWriteError,
    OperationLedger,
    OperationState,
    PersistenceNotInitialized,
    PersistenceRepository,
    matches_filter,
)


class _Query:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def limit(self, amount: int) -> "_Query":
        return _Query(self._rows[:amount])

    def to_list(self) -> list[dict]:
        return list(self._rows)


class _Table:
    def __init__(self) -> None:
        self.rows: list[dict] = []
        self.fail_writes = False

    def count_rows(self) -> int:
        return len(self.rows)

    def search(self, _vector=None) -> _Query:
        return _Query(self.rows)

    def add(self, rows: list[dict]) -> None:
        if self.fail_writes:
            raise OSError("storage unavailable")
        self.rows.extend(rows)

    def update(self, *, where: str, values: dict) -> None:
        if self.fail_writes:
            raise OSError("storage unavailable")
        row_id = where.split("'", 2)[1]
        for row in self.rows:
            if row.get("id") == row_id:
                row.update(values)

    def delete(self, predicate: str) -> None:
        if self.fail_writes:
            raise OSError("storage unavailable")
        ids = predicate.split("(", 1)[1].rstrip(")").replace("'", "").split(", ")
        self.rows = [row for row in self.rows if row.get("id") not in ids]


class _Tables:
    def __init__(self, names: list[str]) -> None:
        self.tables = names


class _DB:
    def __init__(self) -> None:
        self.tables: dict[str, _Table] = {}

    def list_tables(self) -> _Tables:
        return _Tables(sorted(self.tables))

    def open_table(self, name: str) -> _Table:
        return self.tables[name]

    def create_table(self, name: str, schema) -> _Table:
        table = _Table()
        self.tables[name] = table
        return table

    def drop_table(self, name: str) -> None:
        self.tables.pop(name, None)


class PersistenceRepositoryTests(unittest.TestCase):
    def test_repository_requires_explicit_initialization(self) -> None:
        repository = PersistenceRepository(pa.schema([pa.field("id", pa.string())]))
        with self.assertRaises(PersistenceNotInitialized):
            repository.db()

    def test_legacy_metadata_filter_shape_is_preserved(self) -> None:
        metadata = {"kind": "decision", "importance": 5, "scope": "private"}
        self.assertTrue(matches_filter(metadata, {
            "$and": [
                {"kind": "decision"},
                {"importance": {"$gte": 4}},
            ],
        }))
        self.assertFalse(matches_filter(metadata, {"scope": "public"}))

    def test_repository_preserves_collection_and_write_operations(self) -> None:
        repository = PersistenceRepository(pa.schema([pa.field("id", pa.string())]))
        db = _DB()
        repository.configure(db, object())
        table = repository.table("memories")
        repository.add(table, [{"id": "one", "text": "old-format"}])
        repository.update(table, where="id = 'one'", values={"metadata_json": "{}"})
        self.assertEqual(repository.rows(table, 1)[0]["id"], "one")
        self.assertTrue(repository.collection_exists("memories"))
        repository.delete(table, "id IN ('one')")
        self.assertEqual(repository.count(table), 0)

    def test_failed_durable_write_is_typed(self) -> None:
        repository = PersistenceRepository(pa.schema([pa.field("id", pa.string())]))
        db = _DB()
        repository.configure(db, object())
        table = repository.table("memories")
        table.fail_writes = True
        with self.assertRaises(DurableWriteError):
            repository.add(table, [{"id": "one"}])

    def test_operation_ledger_preserves_recovery_transitions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger = OperationLedger(Path(directory) / "operations.jsonl")
            record = ledger.begin("memory_amend", "memory-1", successor_id="memory-2")
            ledger.transition(
                record,
                OperationState.UNCERTAIN,
                reason="successor stored but original update failed",
            )
            rows = [json.loads(line) for line in ledger.path.read_text().splitlines()]
            self.assertEqual([row["state"] for row in rows], ["prepared", "uncertain"])
            self.assertEqual(rows[-1]["operation_id"], record.operation_id)
            self.assertEqual(rows[-1]["details"]["successor_id"], "memory-2")


if __name__ == "__main__":
    unittest.main()
