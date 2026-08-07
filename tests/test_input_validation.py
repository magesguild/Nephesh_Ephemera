from __future__ import annotations

import asyncio
import inspect
import unittest
from typing import Any

from mcp_experiments.config import settings
from mcp_experiments.projection import namespace_for
from mcp_experiments.tools import _threaded_tool, memory, vector_db


class VectorInputValidationTests(unittest.TestCase):
    def test_ingest_rejects_mismatched_ids_before_opening_store(self) -> None:
        result = asyncio.run(
            vector_db.ingest("scratch", ["one", "two"], ids=["only-one"])
        )
        self.assertIn("length", result["error"])

    def test_ingest_rejects_duplicate_ids(self) -> None:
        result = asyncio.run(
            vector_db.ingest("scratch", ["one", "two"], ids=["same", "same"])
        )
        self.assertIn("unique", result["error"])

    def test_search_rejects_non_positive_limit(self) -> None:
        result = asyncio.run(vector_db.search("scratch", "query", n_results=0))
        self.assertIn("greater than zero", result["error"])

    def test_memory_recall_rejects_non_positive_limit(self) -> None:
        result = asyncio.run(memory.memory_recall("query", n_results=0))
        self.assertIn("greater than zero", result["error"])

    def test_memory_sample_rejects_non_positive_limit(self) -> None:
        result = asyncio.run(memory.memory_sample(n=0))
        self.assertIn("greater than zero", result["error"])

    def test_delete_rejects_empty_ids(self) -> None:
        result = asyncio.run(vector_db.delete_documents("scratch", []))
        self.assertIn("not be empty", result["error"])

    def test_delete_cannot_target_canonical_memory(self) -> None:
        with self.assertRaises(RuntimeError):
            asyncio.run(vector_db.delete_documents(settings.memory_collection_name, ["id"]))

    def test_delete_cannot_target_a_knowledge_projection(self) -> None:
        namespace = namespace_for("org.test.knowledge", "1.0.0")
        with self.assertRaises(RuntimeError):
            asyncio.run(vector_db.delete_documents(namespace, ["id"]))

    def test_stress_test_rejects_empty_query_set(self) -> None:
        result = asyncio.run(vector_db.stress_test("scratch", n_queries=0))
        self.assertIn("greater than zero", result["error"])

    def test_malformed_metadata_is_reported_without_breaking_reads(self) -> None:
        result = memory._metadata({"id": "broken", "metadata_json": "not-json"})
        self.assertEqual(result["_metadata_row_id"], "broken")
        self.assertIn("not valid JSON", result["_metadata_error"])

    def test_vector_metadata_corruption_is_reportable(self) -> None:
        result = vector_db._metadata({"metadata_json": "[1, 2, 3]"})
        self.assertIn("must contain a JSON object", result["_metadata_error"])

    def test_blocking_async_shaped_tool_can_be_thread_dispatched(self) -> None:
        async def implementation(value: int) -> dict[str, int]:
            return {"value": value}

        wrapped = _threaded_tool(implementation)
        self.assertFalse(inspect.iscoroutinefunction(wrapped))
        self.assertFalse(hasattr(wrapped, "__wrapped__"))
        self.assertEqual(inspect.signature(wrapped).return_annotation, dict[str, Any])
        self.assertEqual(wrapped(7), {"value": 7})


if __name__ == "__main__":
    unittest.main()
