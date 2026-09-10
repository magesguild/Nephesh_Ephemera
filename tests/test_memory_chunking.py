from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import patch

from mcp_experiments.config import settings
from mcp_experiments.tools import memory


class FakeEmbedder:
    def embed(self, text: str) -> list[float]:
        return [float(len(text)), 0.0, 0.0, 0.0]


class FakeMemoryStore:
    def __init__(self) -> None:
        self.rows_by_table: dict[str, list[dict]] = {"memories": []}
        self.embedder_instance = FakeEmbedder()

    def table(self, name: str) -> str:
        self.rows_by_table.setdefault(name, [])
        return name

    def collection(self, name: str) -> str:
        return self.table(name)

    def collection_exists(self, name: str) -> bool:
        return name in self.rows_by_table

    def count(self, table: str) -> int:
        return len(self.rows_by_table[table])

    def embedder(self) -> FakeEmbedder:
        return self.embedder_instance

    def nearest(self, table: str, _vector: list[float], limit: int) -> list[dict]:
        return [{**row, "_distance": 0.5} for row in self.rows_by_table[table][:limit]]

    def add(self, table: str, rows: list[dict]) -> None:
        self.rows_by_table[table].extend(rows)

    def rows(self, table: str, _limit: int | None = None) -> list[dict]:
        return list(self.rows_by_table[table])

    def begin_operation(self, *_args, **_kwargs) -> str:
        return "operation-1"

    def transition_operation(self, *_args, **_kwargs) -> None:
        return None

    def update(self, table: str, *, where: str, values: dict) -> None:
        row_id = where.split("'", 2)[1]
        for row in self.rows_by_table[table]:
            if row["id"] == row_id:
                row.update(values)


class MemoryChunkingTests(unittest.TestCase):
    def test_ingest_separates_receipt_from_authored_times(self) -> None:
        async def run() -> tuple[dict, dict]:
            store = FakeMemoryStore()
            with patch.object(memory, "repository", store), patch.object(
                settings, "memory_collection_name", "memories"
            ):
                result = await memory.memory_ingest(
                    "I formed this understanding earlier.",
                    "reflection",
                    time_formed="2026-08-16T12:00:00+00:00",
                    event_timestamp="2026-08-15T12:00:00+00:00",
                    allow_duplicate=True,
                )
                metadata = json.loads(store.rows_by_table["memories"][0]["metadata_json"])
                return result, metadata

        result, metadata = asyncio.run(run())
        self.assertEqual(result["status"], "stored")
        self.assertIn("time_ingested", metadata)
        self.assertEqual(metadata["memory_schema_version"], 1)
        self.assertNotEqual(metadata["time_ingested"], metadata["time_formed"])
        self.assertEqual(metadata["time_formed"], "2026-08-16T12:00:00+00:00")
        self.assertEqual(metadata["event_time"], "2026-08-15T12:00:00+00:00")

    def test_ingest_does_not_invent_authored_time(self) -> None:
        async def run() -> dict:
            store = FakeMemoryStore()
            with patch.object(memory, "repository", store), patch.object(
                settings, "memory_collection_name", "memories"
            ):
                await memory.memory_ingest("A memory with unknown timing.", "reflection", allow_duplicate=True)
                return json.loads(store.rows_by_table["memories"][0]["metadata_json"])

        metadata = asyncio.run(run())
        self.assertIsInstance(metadata["time_ingested"], str)
        self.assertEqual(metadata["memory_schema_version"], 1)
        self.assertIsNone(metadata["time_formed"])
        self.assertIsNone(metadata["event_time"])

    def test_display_time_prefers_event_then_formation_without_ingest_fallback(self) -> None:
        event = memory._display_dt({
            "event_time": "2026-08-15T12:00:00+00:00",
            "time_formed": "2026-08-16T12:00:00+00:00",
            "time_ingested": "2026-08-17T12:00:00+00:00",
        })
        formed = memory._display_dt({
            "event_time": None,
            "time_formed": "2026-08-16T12:00:00+00:00",
            "time_ingested": "2026-08-17T12:00:00+00:00",
        })
        unknown = memory._display_dt({
            "event_time": None,
            "time_formed": None,
            "time_ingested": "2026-08-17T12:00:00+00:00",
        })
        self.assertEqual(event.isoformat(), "2026-08-15T12:00:00+00:00")
        self.assertEqual(formed.isoformat(), "2026-08-16T12:00:00+00:00")
        self.assertIsNone(unknown)

    def test_authored_timestamps_require_timezone_aware_iso_strings(self) -> None:
        async def run(**kwargs: object) -> dict:
            store = FakeMemoryStore()
            with patch.object(memory, "repository", store), patch.object(
                settings, "memory_collection_name", "memories"
            ):
                return await memory.memory_ingest(
                    "A timestamp validation test.", "reflection", allow_duplicate=True, **kwargs
                )

        for kwargs, field in (
            ({"time_formed": "2026-08-16T12:00:00"}, "time_formed"),
            ({"event_timestamp": "2026-08-16T12:00:00"}, "event_timestamp"),
            ({"time_formed": 123}, "time_formed"),
        ):
            result = asyncio.run(run(**kwargs))
            self.assertEqual(result["error"], f"invalid {field}: expected an ISO 8601 timezone-aware string")

    def test_authored_time_selection_uses_event_then_formation(self) -> None:
        event = {"event_time": "2026-08-15T12:00:00+00:00", "time_formed": "2026-08-16T12:00:00+00:00"}
        formed = {"event_time": None, "time_formed": "2026-08-16T12:00:00+00:00"}
        self.assertEqual(memory._authored_time_dt(event), memory._display_dt(event))
        self.assertEqual(memory._authored_time_dt(formed), memory._display_dt(formed))

    def test_amendment_preserves_time_and_provenance_on_every_chunk(self) -> None:
        async def run() -> tuple[dict, list[dict]]:
            store = FakeMemoryStore()
            with patch.object(memory, "repository", store), patch.object(
                settings, "memory_collection_name", "memories"
            ):
                original = await memory.memory_ingest(
                    " ".join(f"amend-word-{i}" for i in range(500)),
                    "technical", allow_duplicate=True,
                    event_timestamp="2026-08-15T12:00:00+00:00",
                    time_formed="2026-08-16T12:00:00+00:00",
                    experience_mode="chat", historical_status="confirmed",
                    recorded_during="chat", provenance_note="formed together",
                )
                amended = await memory.memory_amend(original["id"], text="A corrected " + "version " * 500)
                successor = amended["successor_id"]
                rows = [row for row in store.rows_by_table["memories"] if json.loads(row["metadata_json"]).get("memory_id") == successor]
                return amended, rows

        amended, rows = asyncio.run(run())
        self.assertEqual(amended["status"], "amended")
        self.assertGreater(len(rows), 1)
        for row in rows:
            metadata = json.loads(row["metadata_json"])
            self.assertEqual(metadata["event_time"], "2026-08-15T12:00:00+00:00")
            self.assertEqual(metadata["time_formed"], "2026-08-16T12:00:00+00:00")
            self.assertEqual(metadata["experience_mode"], "chat")
            self.assertEqual(metadata["provenance_note"], "formed together")

    def test_wrong_json_metadata_types_do_not_break_memory_reads_or_amendment(self) -> None:
        async def run() -> tuple[dict, dict, dict, dict]:
            store = FakeMemoryStore()
            with patch.object(memory, "repository", store), patch.object(
                settings, "memory_collection_name", "memories"
            ):
                store.add("memories", [{
                    "id": "bad", "text": "corrupt but readable", "vector": [1.0],
                    "metadata_json": json.dumps({
                        "type": ["technical"], "importance": {"bad": True},
                        "chunked": True, "chunk_index": {"bad": True},
                        "participants": {"not": "a list"}, "event_time": ["bad"],
                    }),
                }])
                # An unversioned row remains a valid historical format; the
                # reader must not invent a schema generation for it.
                self.assertNotIn("memory_schema_version", json.loads(store.rows_by_table["memories"][0]["metadata_json"]))
                raw_before_recall = store.rows_by_table["memories"][0]["metadata_json"]
                recall = await memory.memory_recall("readable", n_results=1, include_retired=True)
                self.assertEqual(store.rows_by_table["memories"][0]["metadata_json"], raw_before_recall)
                context = await memory.memory_context(limit=1, include_retired=True)
                sample = await memory.memory_sample(n=1, include_retired=True)
                amend = await memory.memory_amend("bad", text="corrected")
                amended_metadata = json.loads(store.rows_by_table["memories"][0]["metadata_json"])
                retired = await memory.memory_retire("bad", "preserve malformed record")
                return recall, context, sample, amend, retired, amended_metadata, store.rows_by_table["memories"]

        recall, context, sample, amend, retired, amended_metadata, rows = asyncio.run(run())
        self.assertEqual(recall["results_count"], 1)
        self.assertIn("corrupt but readable", context["context"])
        self.assertIn("ssshh", context["context"])
        self.assertIn("quiet care note", context["context"])
        self.assertIn("last_contact_with_companion", context["context"])
        self.assertIn("legacy provenance", context["context"])
        self.assertIn("memories remain untouched", context["context"])
        self.assertNotIn("last_contact_with_companion", context)
        self.assertNotIn("last real conversation", context["context"])
        self.assertNotIn("No recorded conversation", context["context"])
        self.assertEqual(sample["sampled"], 1)
        self.assertEqual(amend["status"], "amended")
        self.assertEqual(retired["status"], "retired")
        self.assertEqual(amended_metadata["_raw_metadata_json"], json.dumps({
            "type": ["technical"], "importance": {"bad": True},
            "chunked": True, "chunk_index": {"bad": True},
            "participants": {"not": "a list"}, "event_time": ["bad"],
        }))
    def test_chunker_preserves_order_and_overlap(self) -> None:
        text = "".join(f"word{i} " for i in range(700))
        chunks = memory._chunk_memory_text(text)
        self.assertGreater(len(chunks), 1)
        self.assertLessEqual(max(len(chunk) for chunk in chunks), memory.MEMORY_CHUNK_SIZE)
        self.assertTrue(chunks[0][-20:].strip() in chunks[1])
        self.assertEqual(" ".join(chunks).count("word0"), 1)

    def test_joiner_removes_overlap(self) -> None:
        text = " ".join(f"word{i}" for i in range(500))
        chunks = memory._chunk_memory_text(text)
        rows = [{"text": chunk} for chunk in chunks]
        self.assertEqual(memory._join_memory_chunks(rows), text)

    def test_long_memory_is_stored_as_linked_chunks(self) -> None:
        async def run() -> dict:
            store = FakeMemoryStore()
            with patch.object(memory, "repository", store), patch.object(
                settings, "memory_collection_name", "memories"
            ):
                result = await memory.memory_ingest(
                    " ".join(f"memory-word-{i}" for i in range(500)),
                    "technical",
                    allow_duplicate=True,
                )
                rows = store.rows_by_table["memories"]
                return {"result": result, "rows": rows}

        output = asyncio.run(run())
        result = output["result"]
        rows = output["rows"]
        self.assertTrue(result["chunked"])
        self.assertEqual(result["total_memories"], 1)
        self.assertEqual(result["chunks_created"], len(rows))
        self.assertEqual(len(result["chunk_ids"]), len(rows))
        metadata = [json.loads(row["metadata_json"]) for row in rows]
        self.assertEqual([item["chunk_index"] for item in metadata], list(range(len(rows))))
        self.assertEqual(metadata[0]["previous_chunk_id"], None)
        self.assertEqual(metadata[-1]["next_chunk_id"], None)
        for left, right in zip(metadata, metadata[1:]):
            self.assertEqual(left["next_chunk_id"], right["chunk_id"])
            self.assertEqual(left["memory_id"], right["memory_id"])

    def test_linked_retrieval_is_opt_in(self) -> None:
        async def run() -> tuple[dict, dict]:
            store = FakeMemoryStore()
            with patch.object(memory, "repository", store), patch.object(
                settings, "memory_collection_name", "memories"
            ):
                await memory.memory_ingest(
                    " ".join(f"memory-word-{i}" for i in range(500)),
                    "technical",
                    allow_duplicate=True,
                )
                plain = await memory.memory_recall("memory-word-20", n_results=1)
                linked = await memory.memory_recall(
                    "memory-word-20", n_results=1, include_linked=True
                )
                return plain, linked

        plain, linked = asyncio.run(run())
        self.assertNotIn("linked_chunks", plain["results"][0])
        self.assertIn("linked_chunks", linked["results"][0])
        self.assertGreater(len(linked["results"][0]["linked_chunks"]), 0)

    def test_retiring_one_chunk_retires_the_logical_memory(self) -> None:
        async def run() -> tuple[dict, list[dict]]:
            store = FakeMemoryStore()
            with patch.object(memory, "repository", store), patch.object(
                settings, "memory_collection_name", "memories"
            ):
                ingested = await memory.memory_ingest(
                    " ".join(f"memory-word-{i}" for i in range(500)),
                    "technical",
                    allow_duplicate=True,
                )
                retired = await memory.memory_retire(ingested["chunk_ids"][1], "superseded")
                return retired, store.rows_by_table["memories"]

        retired, rows = asyncio.run(run())
        self.assertEqual(retired["status"], "retired")
        self.assertEqual(retired["id"], rows[0]["id"].split("#chunk-", 1)[0])
        self.assertTrue(all(json.loads(row["metadata_json"])["retired"] for row in rows))

    def test_context_uses_one_representative_per_linked_memory(self) -> None:
        rows = [
            {"id": "memory#chunk-0000", "metadata_json": json.dumps({"memory_id": "memory", "chunked": True, "chunk_index": 0})},
            {"id": "memory#chunk-0001", "metadata_json": json.dumps({"memory_id": "memory", "chunked": True, "chunk_index": 1})},
            {"id": "other", "metadata_json": json.dumps({"type": "technical"})},
        ]
        representatives = memory._context_representatives(rows)
        self.assertEqual([row["id"] for row in representatives], ["other", "memory#chunk-0000"])


if __name__ == "__main__":
    unittest.main()
