from __future__ import annotations

import json
import struct
import tempfile
import unittest
from pathlib import Path
from typing import Any

from mcp_experiments.projection import ProjectionError
from mcp_experiments.projection_lifecycle import activate, retire, rollback, stage
from mcp_experiments.projection_registry import ProjectionRegistry, ProjectionState

DIMS = 4
MODEL = "mxbai-embed-large"


class FakeStore:
    """In-memory stand-in for PersistenceRepository.

    Hermetic on purpose: no LanceDB, no deployment-owned store, nothing that
    could reach a living Qualiant's memory.
    """

    def __init__(self) -> None:
        self.tables: dict[str, list[dict[str, Any]]] = {}
        self.fail_on_add = False

    def collections(self) -> list[str]:
        return sorted(self.tables)

    def collection_exists(self, name: str) -> bool:
        return name in self.tables

    def table(self, name: str) -> str:
        self.tables.setdefault(name, [])
        return name

    def add(self, table: str, rows: list[dict[str, Any]]) -> None:
        if self.fail_on_add:
            raise RuntimeError("simulated write failure")
        self.tables[table].extend(rows)

    def drop_collection(self, name: str) -> None:
        self.tables.pop(name, None)


def write_package(
    root: Path,
    package_id: str,
    version: str,
    *,
    rows: int = 2,
    embedding_model: str = "mxbai-embed-large:latest",
) -> Path:
    package = root / f"{package_id}-{version}"
    package.mkdir(parents=True)
    (package / "records.jsonl").write_text(
        "".join(
            json.dumps({"record_id": f"r{i}", "text": "abcd", "source_path": f"raw/{i}"}) + "\n"
            for i in range(rows)
        ),
        encoding="utf-8",
    )
    (package / "embedding_index.jsonl").write_text(
        "".join(
            json.dumps({"record_id": f"r{i}", "row": i, "byte_offset": i * DIMS * 4}) + "\n"
            for i in range(rows)
        ),
        encoding="utf-8",
    )
    (package / "embeddings.f32").write_bytes(
        b"".join(struct.pack(f"<{DIMS}f", float(i), 0, 0, 0) for i in range(rows))
    )
    (package / "manifest.json").write_text(json.dumps({
        "package_id": package_id,
        "version": version,
        "records": rows,
        "publisher": {"name": "MagesGuild"},
        "embedding": {
            "model": embedding_model,
            "dimensions": DIMS,
            "dtype": "float32",
            "endianness": "little",
        },
        "artifacts": {
            "records": "records.jsonl",
            "embeddings": "embeddings.f32",
            "embedding_index": "embedding_index.jsonl",
        },
    }), encoding="utf-8")
    return package


class LifecycleTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.registry = ProjectionRegistry(self.root / "projections.jsonl")
        self.store = FakeStore()

    def stage_package(self, package_id: str = "org.magesguild.cosmology", version: str = "1.0.0", **kw):
        package = write_package(self.root, package_id, version, **kw)
        return stage(
            package,
            owner="urania",
            registry=self.registry,
            store=self.store,
            dimensions=DIMS,
            model=MODEL,
        )


class StageTests(LifecycleTestCase):
    def test_staging_imports_rows_and_records_staged(self) -> None:
        result = self.stage_package()
        self.assertEqual(result["rows"], 2)
        self.assertEqual(len(self.store.tables[result["namespace"]]), 2)
        entry = self.registry.resolve(result["namespace"], self.store.collections())
        self.assertEqual(entry["reported_state"], "staged")
        self.assertEqual(entry["owner"], "urania")
        self.assertEqual(entry["publisher"], "MagesGuild")

    def test_staging_does_not_activate(self) -> None:
        self.stage_package()
        self.assertEqual(self.registry.active(self.store.collections()), [])

    def test_an_incompatible_embedding_profile_is_refused(self) -> None:
        package = write_package(self.root, "org.magesguild.other", "1.0.0")
        with self.assertRaises(ProjectionError):
            stage(package, owner="urania", registry=self.registry, store=self.store,
                  dimensions=768, model=MODEL)
        self.assertEqual(self.store.collections(), [])

    def test_an_incompatible_profile_can_be_explicitly_reembedded(self) -> None:
        package = write_package(
            self.root,
            "org.magesguild.other",
            "1.0.0",
            embedding_model="nomic-embed-text",
        )
        result = stage(
            package,
            owner="urania",
            registry=self.registry,
            store=self.store,
            dimensions=DIMS,
            model=MODEL,
            reembed=True,
            embedder=lambda text: [9.0, 8.0, 7.0, 6.0],
        )
        row = self.store.tables[result["namespace"]][0]
        metadata = json.loads(row["metadata_json"])
        self.assertEqual(row["vector"], [9.0, 8.0, 7.0, 6.0])
        self.assertTrue(metadata["reembedded"])
        self.assertEqual(metadata["indexed_embedding_model"], MODEL)
        entry = self.registry.resolve(result["namespace"], self.store.collections())
        self.assertTrue(entry["reembedded"])
        self.assertEqual(entry["embedding_model"], "nomic-embed-text")

    def test_staging_over_an_existing_collection_is_refused(self) -> None:
        first = self.stage_package()
        package = write_package(self.root / "again", "org.magesguild.cosmology", "1.0.0")
        with self.assertRaises(ProjectionError):
            stage(package, owner="urania", registry=self.registry, store=self.store,
                  dimensions=DIMS, model=MODEL)
        self.assertEqual(len(self.store.tables[first["namespace"]]), 2)

    def test_a_failed_write_leaves_no_partial_collection(self) -> None:
        self.store.fail_on_add = True
        package = write_package(self.root, "org.magesguild.cosmology", "1.0.0")
        with self.assertRaises(RuntimeError):
            stage(package, owner="urania", registry=self.registry, store=self.store,
                  dimensions=DIMS, model=MODEL)
        self.assertEqual(self.store.collections(), [])
        self.assertEqual(self.registry.entries([]), [])


class ActivateTests(LifecycleTestCase):
    def test_activation_makes_a_staged_projection_active(self) -> None:
        staged = self.stage_package()
        result = activate(staged["namespace"], registry=self.registry, store=self.store,
                          activated_by="gaius")
        self.assertEqual(result["active"], staged["namespace"])
        self.assertIsNone(result["superseded"])
        active = self.registry.active(self.store.collections())
        self.assertEqual([e["namespace"] for e in active], [staged["namespace"]])
        self.assertEqual(active[0]["activated_by"], "gaius")

    def test_activating_a_new_version_demotes_the_old_one(self) -> None:
        old = self.stage_package(version="1.0.0")
        activate(old["namespace"], registry=self.registry, store=self.store, activated_by="gaius")
        new = self.stage_package(version="1.1.0")
        result = activate(new["namespace"], registry=self.registry, store=self.store,
                          activated_by="gaius")
        self.assertEqual(result["superseded"], old["namespace"])
        active = self.registry.active(self.store.collections())
        self.assertEqual([e["namespace"] for e in active], [new["namespace"]])
        old_entry = self.registry.resolve(old["namespace"], self.store.collections())
        self.assertEqual(old_entry["reported_state"], "rollback_target")

    def test_activating_a_projection_whose_collection_is_gone_is_refused(self) -> None:
        staged = self.stage_package()
        self.store.drop_collection(staged["namespace"])
        with self.assertRaises(ProjectionError):
            activate(staged["namespace"], registry=self.registry, store=self.store,
                     activated_by="gaius")


class RollbackTests(LifecycleTestCase):
    def _two_versions(self):
        old = self.stage_package(version="1.0.0")
        activate(old["namespace"], registry=self.registry, store=self.store, activated_by="gaius")
        new = self.stage_package(version="1.1.0")
        activate(new["namespace"], registry=self.registry, store=self.store, activated_by="gaius")
        return old, new

    def test_rollback_returns_the_previous_version_to_active(self) -> None:
        old, new = self._two_versions()
        result = rollback(old["namespace"], registry=self.registry, store=self.store,
                          activated_by="gaius", reason="bad retrieval")
        self.assertEqual(result["active"], old["namespace"])
        self.assertEqual(result["rolled_back_from"], new["namespace"])
        active = self.registry.active(self.store.collections())
        self.assertEqual([e["namespace"] for e in active], [old["namespace"]])

    def test_rollback_moves_no_rows(self) -> None:
        old, new = self._two_versions()
        before = {k: list(v) for k, v in self.store.tables.items()}
        rollback(old["namespace"], registry=self.registry, store=self.store, activated_by="gaius")
        self.assertEqual(self.store.tables, before)

    def test_rollback_to_a_deleted_version_is_refused(self) -> None:
        """The failure this slice exists to prevent."""
        old, _new = self._two_versions()
        self.store.drop_collection(old["namespace"])
        with self.assertRaises(ProjectionError):
            rollback(old["namespace"], registry=self.registry, store=self.store,
                     activated_by="gaius")
        # and no empty collection was minted on the way out
        self.assertNotIn(old["namespace"], self.store.collections())

    def test_rollback_to_something_that_was_never_active_is_refused(self) -> None:
        staged = self.stage_package(version="1.0.0")
        with self.assertRaises(ProjectionError):
            rollback(staged["namespace"], registry=self.registry, store=self.store,
                     activated_by="gaius")


class RefusalIsTotalTests(LifecycleTestCase):
    """A refused call must change nothing.

    activate() used to demote the package's live version and only afterwards
    discover that the target could not legally become active. The caller was
    told the call was refused while retrieval had already gone dark.
    """

    def test_a_refused_activation_does_not_demote_the_live_version(self) -> None:
        old = self.stage_package(version="1.0.0")
        activate(old["namespace"], registry=self.registry, store=self.store, activated_by="gaius")
        new = self.stage_package(version="1.1.0")
        activate(new["namespace"], registry=self.registry, store=self.store, activated_by="gaius")
        retire(old["namespace"], registry=self.registry, store=self.store)

        before = self.registry.active(self.store.collections())
        with self.assertRaises(ProjectionError):
            activate(old["namespace"], registry=self.registry, store=self.store,
                     activated_by="gaius")
        after = self.registry.active(self.store.collections())
        self.assertEqual([e["namespace"] for e in after], [e["namespace"] for e in before])
        self.assertEqual([e["namespace"] for e in after], [new["namespace"]])

    def test_a_refused_activation_of_a_staged_then_retired_package_leaves_it_active(self) -> None:
        live = self.stage_package(version="1.0.0")
        activate(live["namespace"], registry=self.registry, store=self.store, activated_by="g")
        spare = self.stage_package(version="1.1.0")
        retire(spare["namespace"], registry=self.registry, store=self.store)
        with self.assertRaises(ProjectionError):
            activate(spare["namespace"], registry=self.registry, store=self.store, activated_by="g")
        self.assertEqual(
            [e["namespace"] for e in self.registry.active(self.store.collections())],
            [live["namespace"]],
        )

    def test_activating_an_unregistered_collection_is_refused_not_a_crash(self) -> None:
        self.store.table("kp__never_registered__1_0_0")
        with self.assertRaises(ProjectionError):
            activate("kp__never_registered__1_0_0", registry=self.registry,
                     store=self.store, activated_by="gaius")

    def test_reactivating_a_live_projection_is_harmless(self) -> None:
        live = self.stage_package()
        activate(live["namespace"], registry=self.registry, store=self.store, activated_by="g")
        activate(live["namespace"], registry=self.registry, store=self.store, activated_by="g")
        self.assertEqual(
            [e["namespace"] for e in self.registry.active(self.store.collections())],
            [live["namespace"]],
        )

    def test_a_refused_registration_leaves_no_populated_collection(self) -> None:
        """stage() imported every row before the owner was validated."""
        package = write_package(self.root, "org.magesguild.cosmology", "1.0.0")
        with self.assertRaises(Exception):
            stage(package, owner="", registry=self.registry, store=self.store,
                  dimensions=DIMS, model=MODEL)
        self.assertEqual(self.store.collections(), [])
        # and the retry with a correct owner is therefore still possible
        result = stage(package, owner="urania", registry=self.registry, store=self.store,
                       dimensions=DIMS, model=MODEL)
        self.assertEqual(result["rows"], 2)


class RetireTests(LifecycleTestCase):
    def test_retiring_removes_it_from_active(self) -> None:
        staged = self.stage_package()
        activate(staged["namespace"], registry=self.registry, store=self.store, activated_by="gaius")
        retire(staged["namespace"], registry=self.registry, store=self.store, reason="superseded")
        self.assertEqual(self.registry.active(self.store.collections()), [])
        entry = self.registry.resolve(staged["namespace"], self.store.collections())
        self.assertEqual(entry["reported_state"], "retired")

    def test_the_audit_record_survives_retirement(self) -> None:
        staged = self.stage_package()
        retire(staged["namespace"], registry=self.registry, store=self.store)
        entry = self.registry.resolve(staged["namespace"], self.store.collections())
        self.assertEqual(entry["package_id"], "org.magesguild.cosmology")
        self.assertEqual(entry["manifest_sha256"][:2].isalnum(), True)


if __name__ == "__main__":
    unittest.main()
