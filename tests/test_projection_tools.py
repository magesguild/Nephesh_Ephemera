from __future__ import annotations

import asyncio
import unittest

from mcp_experiments.config import settings
from mcp_experiments.tools import get_registered_names
from mcp_experiments.tools.projection import projection_search

EXPECTED = {
    "projection_list",
    "projection_stage",
    "projection_activate",
    "projection_rollback",
    "projection_retire",
    "projection_search",
}


class ToolSurfaceTests(unittest.TestCase):
    """The guard that works by accident is worse than no guard.

    These run the tool functions themselves rather than the helpers underneath,
    because the last boundary bug was an import that only failed when the guard
    actually fired. The refusal paths return before any store is touched, so
    nothing here opens a deployment-owned collection.
    """

    def test_the_projection_tools_are_registered(self) -> None:
        self.assertTrue(EXPECTED <= set(get_registered_names()))

    def test_search_refuses_canonical_memory(self) -> None:
        result = asyncio.run(projection_search(settings.memory_collection_name, "anything"))
        self.assertTrue(result.get("refused"))

    def test_search_refuses_an_unprefixed_collection(self) -> None:
        result = asyncio.run(projection_search("some_other_table", "anything"))
        self.assertTrue(result.get("refused"))


if __name__ == "__main__":
    unittest.main()
