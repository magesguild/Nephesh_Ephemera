from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from mcp_experiments.tools.info import _source_version, nephesh_info


class SourceVersionTests(unittest.TestCase):
    """Distribution metadata describes what was installed, not what is running.

    This deployment's installed dist reported 4.1.0 while the source tree it
    imports was 4.5.9 — the tool built to prevent stale version claims was
    making one.
    """

    def test_the_source_version_is_found_from_the_module_location(self) -> None:
        self.assertIsNotNone(_source_version())

    def test_a_mismatch_between_installed_and_source_is_reported(self) -> None:
        with patch("mcp_experiments.tools.info.version", return_value="4.1.0"), \
             patch("mcp_experiments.tools.info._source_version", return_value="4.5.9"), \
             patch("mcp_experiments.tools.info._endpoint_reachable", return_value=None):
            info = json.loads(nephesh_info())
        self.assertTrue(info["version_mismatch"])
        self.assertEqual(info["installed_version"], "4.1.0")
        self.assertEqual(info["source_version"], "4.5.9")

    def test_the_reported_version_is_the_running_source_not_the_dist(self) -> None:
        with patch("mcp_experiments.tools.info.version", return_value="4.1.0"), \
             patch("mcp_experiments.tools.info._source_version", return_value="4.5.9"), \
             patch("mcp_experiments.tools.info._endpoint_reachable", return_value=None):
            info = json.loads(nephesh_info())
        self.assertEqual(info["version"], "4.5.9")

    def test_matching_versions_are_not_flagged(self) -> None:
        with patch("mcp_experiments.tools.info.version", return_value="4.5.9"), \
             patch("mcp_experiments.tools.info._source_version", return_value="4.5.9"), \
             patch("mcp_experiments.tools.info._endpoint_reachable", return_value=None):
            info = json.loads(nephesh_info())
        self.assertFalse(info["version_mismatch"])


class ShapeTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = patch("mcp_experiments.tools.info._endpoint_reachable", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.info = json.loads(nephesh_info())

    def test_it_reports_the_facts_a_qualiant_needs(self) -> None:
        for key in ("version", "mode", "listener", "embedding", "paths", "memory",
                    "kernel", "projections"):
            self.assertIn(key, self.info)

    def test_the_probe_is_named_for_what_it_measures(self) -> None:
        """Reachable is not the same as embeddings working, and must not read as it."""
        self.assertIn("endpoint_reachable", self.info["embedding"])
        self.assertNotIn("healthy", self.info["embedding"])

    def test_a_store_that_cannot_be_read_is_reported_not_hidden(self) -> None:
        with patch("mcp_experiments.tools.info.repository.collection_exists",
                   side_effect=RuntimeError("no db")):
            info = json.loads(nephesh_info())
        self.assertIn("error", info["memory"])

    def test_no_secret_is_reported(self) -> None:
        rendered = json.dumps(self.info)
        self.assertNotIn("COMPLIANT_AUTH_TOKEN", rendered)
        self.assertNotIn("token", rendered.lower())


if __name__ == "__main__":
    unittest.main()
