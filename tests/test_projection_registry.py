from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mcp_experiments.projection import ProjectionError, namespace_for
from mcp_experiments.projection_registry import (
    ORPHANED,
    UNREGISTERED,
    ProjectionRecord,
    ProjectionRegistry,
    ProjectionState,
    RegistryError,
)


def _record(package_id: str = "org.magesguild.cosmology", version: str = "1.1.0", **kw) -> ProjectionRecord:
    base = {
        "package_id": package_id,
        "version": version,
        "namespace": namespace_for(package_id, version),
        "state": ProjectionState.STAGED,
        "owner": "urania",
    }
    base.update(kw)
    return ProjectionRecord(**base)


class RegistryTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.registry = ProjectionRegistry(Path(self._tmp.name) / "projections.jsonl")


class RecordingTests(RegistryTestCase):
    def test_a_projection_can_be_recorded_and_read_back(self) -> None:
        rec = self.registry.record(_record())
        entry = self.registry.resolve(rec.namespace, [rec.namespace])
        self.assertEqual(entry["package_id"], "org.magesguild.cosmology")
        self.assertEqual(entry["recorded_state"], "staged")
        self.assertFalse(entry["drift"])

    def test_a_non_projection_namespace_is_refused(self) -> None:
        with self.assertRaises(ProjectionError):
            self.registry.record(_record(namespace="urania_memories_v1"))

    def test_an_owner_is_required(self) -> None:
        with self.assertRaises(RegistryError):
            self.registry.record(_record(owner=""))

    def test_a_namespace_cannot_be_declared_twice(self) -> None:
        self.registry.record(_record())
        with self.assertRaises(RegistryError):
            self.registry.record(_record(note="second first-statement"))

    def test_the_same_package_version_cannot_be_registered_under_two_namespaces(self) -> None:
        self.registry.record(_record())
        with self.assertRaises(RegistryError):
            self.registry.record(_record(namespace="kp__hand_written__1_1_0"))

    def test_the_log_is_append_only(self) -> None:
        rec = self.registry.record(_record())
        self.registry.transition(rec.namespace, ProjectionState.ACTIVE)
        lines = self.registry.path.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 2)


class TransitionTests(RegistryTestCase):
    def test_staged_can_become_active(self) -> None:
        rec = self.registry.record(_record())
        self.registry.transition(rec.namespace, ProjectionState.ACTIVE, activated_by="gaius")
        entry = self.registry.resolve(rec.namespace, [rec.namespace])
        self.assertEqual(entry["reported_state"], "active")
        self.assertEqual(entry["activated_by"], "gaius")

    def test_an_illegal_transition_is_refused(self) -> None:
        rec = self.registry.record(_record())
        # staged -> rollback_target skips activation entirely
        with self.assertRaises(RegistryError):
            self.registry.transition(rec.namespace, ProjectionState.ROLLBACK_TARGET)

    def test_an_unregistered_namespace_cannot_transition(self) -> None:
        with self.assertRaises(RegistryError):
            self.registry.transition("kp__ghost__1_0_0", ProjectionState.ACTIVE)

    def test_two_versions_of_one_package_cannot_both_be_active(self) -> None:
        old = self.registry.record(_record(version="1.0.0"))
        self.registry.transition(old.namespace, ProjectionState.ACTIVE)
        new = self.registry.record(_record(version="1.1.0"))
        with self.assertRaises(RegistryError):
            self.registry.transition(new.namespace, ProjectionState.ACTIVE)

    def test_demoting_the_old_version_frees_the_active_slot(self) -> None:
        old = self.registry.record(_record(version="1.0.0"))
        self.registry.transition(old.namespace, ProjectionState.ACTIVE)
        self.registry.transition(old.namespace, ProjectionState.ROLLBACK_TARGET)
        new = self.registry.record(_record(version="1.1.0"))
        self.registry.transition(new.namespace, ProjectionState.ACTIVE)
        active = self.registry.active([old.namespace, new.namespace])
        self.assertEqual([e["namespace"] for e in active], [new.namespace])


class ReconciliationTests(RegistryTestCase):
    """The reason this module exists.

    A registry that reports its own claims would answer "active" for a
    collection that has been deleted, and a rollback pointed there would open an
    empty table through the ordinary create-or-open path and call it live.
    """

    def test_an_active_record_with_no_collection_reports_orphaned(self) -> None:
        rec = self.registry.record(_record())
        self.registry.transition(rec.namespace, ProjectionState.ACTIVE)
        entry = self.registry.resolve(rec.namespace, [])  # the store is empty
        self.assertEqual(entry["recorded_state"], "active")
        self.assertEqual(entry["reported_state"], ORPHANED)
        self.assertTrue(entry["drift"])

    def test_an_orphaned_projection_is_not_reported_as_active(self) -> None:
        rec = self.registry.record(_record())
        self.registry.transition(rec.namespace, ProjectionState.ACTIVE)
        self.assertEqual(self.registry.active([]), [])

    def test_a_retired_projection_with_no_collection_is_not_drift(self) -> None:
        rec = self.registry.record(_record())
        self.registry.transition(rec.namespace, ProjectionState.ACTIVE)
        self.registry.transition(rec.namespace, ProjectionState.RETIRED)
        entry = self.registry.resolve(rec.namespace, [])
        self.assertEqual(entry["reported_state"], "retired")
        self.assertFalse(entry["drift"])

    def test_an_unregistered_projection_collection_is_reported(self) -> None:
        entries = self.registry.entries(["kp__mystery__1_0_0"])
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["reported_state"], UNREGISTERED)
        self.assertTrue(entries[0]["drift"])

    def test_ordinary_collections_are_not_reported_as_unregistered(self) -> None:
        self.assertEqual(self.registry.entries(["urania_memories_v1"]), [])

    def test_reality_is_a_required_argument(self) -> None:
        # There must be no call shape that reports state without the store.
        with self.assertRaises(TypeError):
            self.registry.entries()  # type: ignore[call-arg]
        with self.assertRaises(TypeError):
            self.registry.active()  # type: ignore[call-arg]

    def test_a_drift_state_cannot_be_written_into_the_log(self) -> None:
        with self.assertRaises(ValueError):
            ProjectionState(ORPHANED)
        with self.assertRaises(ValueError):
            ProjectionState(UNREGISTERED)


class DurabilityTests(RegistryTestCase):
    def test_a_corrupt_line_is_refused_rather_than_skipped(self) -> None:
        rec = self.registry.record(_record())
        with self.registry.path.open("a", encoding="utf-8") as handle:
            handle.write("{not json}\n")
        with self.assertRaises(RegistryError):
            self.registry.entries([rec.namespace])

    def test_an_absent_registry_reads_as_empty(self) -> None:
        self.assertEqual(self.registry.entries([]), [])

    def test_state_survives_a_new_reader_over_the_same_file(self) -> None:
        rec = self.registry.record(_record())
        self.registry.transition(rec.namespace, ProjectionState.ACTIVE)
        reopened = ProjectionRegistry(self.registry.path)
        self.assertEqual(reopened.active([rec.namespace])[0]["namespace"], rec.namespace)


if __name__ == "__main__":
    unittest.main()
