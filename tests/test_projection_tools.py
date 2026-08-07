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


class SearchRespectsLifecycleTests(unittest.TestCase):
    """Activation and retirement have to change what search returns.

    projection_search is the only surface that reads projection rows. When it
    ignored recorded state, activate() and retire() changed nothing anyone
    could observe — retirement is defined as removing a projection from
    ordinary retrieval, and it did not.
    """

    def setUp(self) -> None:
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        from mcp_experiments.projection_registry import (
            ProjectionRecord,
            ProjectionRegistry,
            ProjectionState,
        )

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.ns = "kp__org_magesguild_cosmology__1_0_0"
        self.registry = ProjectionRegistry(Path(tmp.name) / "projections.jsonl")
        self.registry.record(ProjectionRecord(
            package_id="org.magesguild.cosmology", version="1.0.0",
            namespace=self.ns, state=ProjectionState.STAGED, owner="urania",
        ))
        self.State = ProjectionState

        for target, new in (
            ("mcp_experiments.tools.projection._registry", self.registry),
        ):
            p = patch(target, new)
            p.start()
            self.addCleanup(p.stop)
        p = patch("mcp_experiments.tools.projection.repository.collections",
                  return_value=[self.ns])
        p.start()
        self.addCleanup(p.stop)

    def _search(self):
        return asyncio.run(projection_search(self.ns, "anything"))

    def test_a_retired_projection_is_refused(self) -> None:
        self.registry.transition(self.ns, self.State.ACTIVE)
        self.registry.transition(self.ns, self.State.RETIRED)
        result = self._search()
        self.assertTrue(result.get("refused"))
        self.assertEqual(result.get("state"), "retired")

    def test_an_orphaned_projection_is_refused(self) -> None:
        """Recorded active, collection gone — must not be searched."""
        from unittest.mock import patch

        self.registry.transition(self.ns, self.State.ACTIVE)
        with patch("mcp_experiments.tools.projection.repository.collections", return_value=[]):
            result = self._search()
        self.assertTrue(result.get("refused"))
        self.assertEqual(result.get("state"), "orphaned")

    def test_an_unregistered_projection_is_refused(self) -> None:
        result = asyncio.run(projection_search("kp__never_registered__1_0_0", "anything"))
        self.assertTrue(result.get("refused"))


if __name__ == "__main__":
    unittest.main()
