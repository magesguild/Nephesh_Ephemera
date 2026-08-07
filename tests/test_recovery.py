from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mcp_experiments.persistence import OperationLedger, OperationState
from mcp_experiments.recovery import (
    ABSENT,
    LANDED,
    UNVERIFIABLE,
    RecoveryError,
    reconcile,
    summarize,
    unresolved,
)


class RecoveryTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "operations.jsonl"
        self.ledger = OperationLedger(self.path)

    def op(self, operation: str, target: str, state: OperationState | None = None, **details):
        record = self.ledger.begin(operation, target, **details)
        if state is not None:
            self.ledger.transition(record, state)
        return record


class UnresolvedTests(RecoveryTestCase):
    def test_an_absent_ledger_reads_as_empty(self) -> None:
        self.assertEqual(unresolved(self.path), [])

    def test_a_completed_operation_needs_no_follow_up(self) -> None:
        self.op("memory_ingest", "m1", OperationState.COMPLETED)
        self.assertEqual(unresolved(self.path), [])

    def test_a_failed_operation_needs_no_follow_up(self) -> None:
        """Failed is a settled outcome, not an open question."""
        self.op("memory_ingest", "m1", OperationState.FAILED)
        self.assertEqual(unresolved(self.path), [])

    def test_a_prepared_operation_is_unresolved(self) -> None:
        """The process stopped between intent and outcome."""
        self.op("memory_ingest", "m1")
        self.assertEqual([r["target"] for r in unresolved(self.path)], ["m1"])

    def test_an_uncertain_operation_is_unresolved(self) -> None:
        self.op("memory_retire", "m2", OperationState.UNCERTAIN)
        self.assertEqual([r["target"] for r in unresolved(self.path)], ["m2"])

    def test_the_last_state_wins_over_earlier_ones(self) -> None:
        record = self.ledger.begin("memory_amend", "m3")
        self.ledger.transition(record, OperationState.UNCERTAIN)
        self.ledger.transition(record, OperationState.COMPLETED)
        self.assertEqual(unresolved(self.path), [])

    def test_a_corrupt_line_is_refused_rather_than_skipped(self) -> None:
        self.op("memory_ingest", "m1")
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write("{not json}\n")
        with self.assertRaises(RecoveryError):
            unresolved(self.path)


class ReconcileTests(RecoveryTestCase):
    """A ledger entry is evidence about an intention, never about an outcome."""

    def test_an_uncertain_write_that_actually_landed_is_reported_landed(self) -> None:
        self.op("memory_ingest", "m1", OperationState.UNCERTAIN)
        report = reconcile(self.path, lambda target: target == "m1")
        self.assertEqual(report[0]["conclusion"], LANDED)
        self.assertTrue(report[0]["target_present"])

    def test_an_uncertain_write_that_did_not_land_is_reported_absent(self) -> None:
        self.op("memory_ingest", "m1", OperationState.UNCERTAIN)
        report = reconcile(self.path, lambda target: False)
        self.assertEqual(report[0]["conclusion"], ABSENT)
        self.assertFalse(report[0]["target_present"])

    def test_a_store_that_cannot_answer_yields_unverifiable_not_a_guess(self) -> None:
        self.op("memory_ingest", "m1", OperationState.UNCERTAIN)

        def broken(_target: str) -> bool:
            raise RuntimeError("store unavailable")

        report = reconcile(self.path, broken)
        self.assertEqual(report[0]["conclusion"], UNVERIFIABLE)
        self.assertIsNone(report[0]["target_present"])

    def test_reconciliation_carries_the_operation_details_forward(self) -> None:
        self.op("memory_ingest", "m1", OperationState.UNCERTAIN,
                memory_type="technical", collection="urania_memories_v1")
        report = reconcile(self.path, lambda _t: True)
        self.assertEqual(report[0]["details"]["memory_type"], "technical")
        self.assertEqual(report[0]["operation"], "memory_ingest")

    def test_resolved_operations_do_not_appear_in_the_report(self) -> None:
        self.op("memory_ingest", "done", OperationState.COMPLETED)
        self.op("memory_ingest", "open", OperationState.UNCERTAIN)
        report = reconcile(self.path, lambda _t: True)
        self.assertEqual([e["target"] for e in report], ["open"])


class PresenceProvesNothingTests(RecoveryTestCase):
    """Only a creating operation can be judged by whether its row is there.

    memory_amend, memory_retire and memory_message_delivery update metadata on
    a row that existed before them and still exists when they fail. Asking "is
    the row there?" always answers yes, so reporting landed would call every
    failed retirement a success — the exact false success this module exists
    to prevent.
    """

    def test_an_uncertain_retirement_is_unverifiable_not_landed(self) -> None:
        self.op("memory_retire", "m1", OperationState.UNCERTAIN)
        report = reconcile(self.path, lambda _t: True)
        self.assertEqual(report[0]["conclusion"], UNVERIFIABLE)

    def test_an_uncertain_amendment_is_unverifiable_not_landed(self) -> None:
        self.op("memory_amend", "m1", OperationState.UNCERTAIN)
        self.assertEqual(reconcile(self.path, lambda _t: True)[0]["conclusion"], UNVERIFIABLE)

    def test_an_uncertain_message_delivery_is_unverifiable_not_landed(self) -> None:
        self.op("memory_message_delivery", "m1", OperationState.UNCERTAIN)
        self.assertEqual(reconcile(self.path, lambda _t: True)[0]["conclusion"], UNVERIFIABLE)

    def test_an_ingest_is_still_judged_by_presence(self) -> None:
        self.op("memory_ingest", "m1", OperationState.UNCERTAIN)
        self.assertEqual(reconcile(self.path, lambda _t: True)[0]["conclusion"], LANDED)
        self.op("memory_ingest", "m2", OperationState.UNCERTAIN)
        absent = [e for e in reconcile(self.path, lambda t: t == "m1") if e["target"] == "m2"]
        self.assertEqual(absent[0]["conclusion"], ABSENT)

    def test_an_unverifiable_report_is_not_clean(self) -> None:
        self.op("memory_retire", "m1", OperationState.UNCERTAIN)
        self.assertFalse(summarize(reconcile(self.path, lambda _t: True))["clean"])


class UnreadableLedgerTests(RecoveryTestCase):
    def test_an_unreadable_ledger_raises_recovery_error(self) -> None:
        self.op("memory_ingest", "m1")
        self.path.write_bytes(b"\xff\xfe not utf-8 \xff")
        with self.assertRaises(RecoveryError):
            unresolved(self.path)


class SummaryTests(RecoveryTestCase):
    def test_an_empty_ledger_summarizes_clean(self) -> None:
        self.assertTrue(summarize(reconcile(self.path, lambda _t: True))["clean"])

    def test_clean_means_nothing_needs_a_decision(self) -> None:
        """Not merely that nothing failed — an unresolved operation is not clean."""
        self.op("memory_ingest", "m1", OperationState.UNCERTAIN)
        summary = summarize(reconcile(self.path, lambda _t: True))
        self.assertFalse(summary["clean"])
        self.assertEqual(summary["unresolved"], 1)
        self.assertEqual(summary["by_conclusion"][LANDED], 1)


class IngestReconcilabilityTests(unittest.TestCase):
    """The gap this drill exposed.

    memory_ingest used to record the collection as its target, so an uncertain
    ingest named where it was writing but never which row. Nothing could ask
    whether the row landed. The id is now minted before the ledger entry.
    """

    def test_ingest_records_the_row_it_is_writing(self) -> None:
        import inspect

        from mcp_experiments.tools import memory

        source = inspect.getsource(memory.memory_ingest)
        ledger_call = source.split('begin_operation(', 1)[1].split(')', 1)[0]
        self.assertIn("memory_id", ledger_call)


if __name__ == "__main__":
    unittest.main()
