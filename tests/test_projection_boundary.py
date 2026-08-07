from __future__ import annotations

import json
import struct
import tempfile
import unittest
from pathlib import Path

from mcp_experiments.config import settings
from mcp_experiments.projection import (
    FORBIDDEN_METADATA_KEYS,
    PROJECTION_PREFIX,
    CanonicalMemoryTargeted,
    EmbeddingContract,
    ProjectionError,
    build_rows,
    guard_memory_target,
    guard_projection_target,
    namespace_for,
    projection_metadata,
)


class NamespaceTests(unittest.TestCase):
    def test_namespace_is_prefixed(self) -> None:
        self.assertTrue(namespace_for("org.magesguild.z80-computing", "1.0.0").startswith(PROJECTION_PREFIX))

    def test_version_is_part_of_the_namespace(self) -> None:
        self.assertNotEqual(
            namespace_for("org.magesguild.z80-computing", "1.0.0"),
            namespace_for("org.magesguild.z80-computing", "1.1.0"),
        )

    def test_empty_components_are_refused(self) -> None:
        with self.assertRaises(ProjectionError):
            namespace_for("", "1.0.0")
        with self.assertRaises(ProjectionError):
            namespace_for("org.magesguild.x", "")

    def test_a_package_id_of_only_separators_is_refused(self) -> None:
        with self.assertRaises(ProjectionError):
            namespace_for("...", "1.0.0")


class GuardTests(unittest.TestCase):
    """The executable half of knowledge_not_memory.

    A JSON field saying a package is not memory is a claim. A namespace the
    memory tools refuse to open is a fact.
    """

    def test_memory_tools_refuse_a_projection(self) -> None:
        with self.assertRaises(ProjectionError):
            guard_memory_target(namespace_for("org.magesguild.cosmology", "1.0.0"))

    def test_memory_tools_accept_ordinary_collections(self) -> None:
        self.assertEqual(guard_memory_target("urania_memories_v1"), "urania_memories_v1")

    def test_projection_tools_refuse_canonical_memory(self) -> None:
        with self.assertRaises(CanonicalMemoryTargeted):
            guard_projection_target(settings.memory_collection_name)

    def test_projection_tools_refuse_an_unprefixed_name(self) -> None:
        with self.assertRaises(ProjectionError):
            guard_projection_target("looks_like_memory")

    def test_canonical_memory_is_refused_even_if_it_were_prefixed(self) -> None:
        # MEMORY_COLLECTION_NAME is deployment-configurable, so the reserved
        # name is checked explicitly rather than assumed not to collide.
        original = settings.memory_collection_name
        try:
            object.__setattr__(settings, "memory_collection_name", f"{PROJECTION_PREFIX}oops")
            with self.assertRaises(CanonicalMemoryTargeted):
                guard_projection_target(f"{PROJECTION_PREFIX}oops")
        finally:
            object.__setattr__(settings, "memory_collection_name", original)


class MetadataAllowlistTests(unittest.TestCase):
    """Strip, never copy. A package must not set a key the memory layer reads."""

    def test_forbidden_keys_never_survive_import(self) -> None:
        hostile = {
            "record_id": "r1",
            "source_path": "raw/x",
            # everything below is a memory concept a package must not assert
            "type": "message",
            "delivered": False,
            "experience_mode": "chat",
            "historical_status": "confirmed",
            "recorded_during": "chat",
            "event_time": "2026-08-06T00:00:00Z",
            "importance": 5,
            "salience": 1.0,
            "participants": ["Gaius"],
            "emotional_tone": "loved",
        }
        meta = projection_metadata(hostile, {}, package_id="p", version="1.0.0")
        self.assertEqual(FORBIDDEN_METADATA_KEYS & set(meta), set())

    def test_knowledge_is_labelled_as_such(self) -> None:
        meta = projection_metadata({"record_id": "r1"}, {}, package_id="p", version="1.0.0")
        self.assertTrue(meta["knowledge_not_memory"])
        self.assertEqual(meta["record_kind"], "knowledge")
        self.assertEqual(meta["package_id"], "p")

    def test_provenance_is_preserved(self) -> None:
        meta = projection_metadata(
            {"record_id": "r1", "source_path": "raw/z80/m.txt", "source_sha256": "abc"},
            {"chunk_index": 2, "chunk_count": 9},
            package_id="p",
            version="1.0.0",
        )
        self.assertEqual(meta["source_path"], "raw/z80/m.txt")
        self.assertEqual(meta["source_sha256"], "abc")
        self.assertEqual(meta["chunk_index"], 2)


class EmbeddingContractTests(unittest.TestCase):
    """Require an explicit decision before changing embedding geometry."""

    def _contract(self, **kw) -> EmbeddingContract:
        base = {"model": "mxbai-embed-large:latest", "dimensions": 1024, "dtype": "float32", "endianness": "little"}
        base.update(kw)
        return EmbeddingContract(**base)

    def test_matching_contract_is_accepted(self) -> None:
        self._contract().require_compatible(dimensions=1024, model="mxbai-embed-large")

    def test_dimension_mismatch_is_refused(self) -> None:
        with self.assertRaises(ProjectionError):
            self._contract(dimensions=768).require_compatible(dimensions=1024, model="mxbai-embed-large")

    def test_different_model_is_refused(self) -> None:
        with self.assertRaises(ProjectionError):
            self._contract(model="nomic-embed-text").require_compatible(dimensions=1024, model="mxbai-embed-large")

    def test_non_float32_is_refused(self) -> None:
        with self.assertRaises(ProjectionError):
            self._contract(dtype="float16").require_compatible(dimensions=1024, model="mxbai-embed-large")

    def test_big_endian_is_refused(self) -> None:
        with self.assertRaises(ProjectionError):
            self._contract(endianness="big").require_compatible(dimensions=1024, model="mxbai-embed-large")


class BuildRowsTests(unittest.TestCase):
    def _package(self, directory: Path, *, dimensions: int = 4) -> dict:
        (directory / "records.jsonl").write_text(
            json.dumps({"record_id": "r1", "text": "abcdefgh", "source_path": "raw/x", "type": "message"}) + "\n"
        )
        (directory / "embedding_index.jsonl").write_text(
            json.dumps({"record_id": "r1", "chunk_index": 0, "chunk_count": 2, "row": 0, "byte_offset": 0, "chars": 4}) + "\n"
            + json.dumps({"record_id": "r1", "chunk_index": 1, "chunk_count": 2, "row": 1, "byte_offset": 16, "chars": 4}) + "\n"
        )
        (directory / "embeddings.f32").write_bytes(
            struct.pack("<4f", 1, 0, 0, 0) + struct.pack("<4f", 0, 1, 0, 0)
        )
        return {
            "package_id": "org.test.pkg",
            "version": "1.0.0",
            "artifacts": {
                "records": "records.jsonl",
                "embeddings": "embeddings.f32",
                "embedding_index": "embedding_index.jsonl",
            },
        }

    def test_one_row_per_chunk_with_clean_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)
            manifest = self._package(path)
            rows = build_rows(path, manifest, dimensions=4)
            self.assertEqual(len(rows), 2)
            self.assertEqual([r["id"] for r in rows], ["r1#0", "r1#1"])
            self.assertEqual([r["text"] for r in rows], ["abcd", "efgh"])
            for row in rows:
                meta = json.loads(row["metadata_json"])
                self.assertTrue(meta["knowledge_not_memory"])
                # the record carried type="message"; it must not survive
                self.assertNotIn("type", meta)

    def test_truncated_vector_blob_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)
            manifest = self._package(path)
            (path / "embeddings.f32").write_bytes(b"\x00" * 17)  # not a whole number of vectors
            with self.assertRaises(ProjectionError):
                build_rows(path, manifest, dimensions=4)

    def test_index_referencing_an_unknown_record_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)
            manifest = self._package(path)
            (path / "embedding_index.jsonl").write_text(
                json.dumps({"record_id": "ghost", "row": 0, "byte_offset": 0}) + "\n"
            )
            (path / "embeddings.f32").write_bytes(struct.pack("<4f", 1, 0, 0, 0))
            with self.assertRaises(ProjectionError):
                build_rows(path, manifest, dimensions=4)


if __name__ == "__main__":
    unittest.main()
