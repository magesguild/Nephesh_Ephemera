from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from unittest.mock import patch

from mcp_experiments.config import settings
from mcp_experiments.tools.info import _source_version, nephesh_info, nephesh_recovery_report, truthful_floor
from mcp_experiments.server import _health_status


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

    def test_truthful_floor_uses_source_when_distribution_metadata_is_missing(self) -> None:
        with patch("mcp_experiments.tools.info.version", side_effect=PackageNotFoundError), \
             patch("mcp_experiments.tools.info._source_version", return_value="5.3.6"), \
             patch("mcp_experiments.tools.info._endpoint_reachable", return_value=None):
            floor = truthful_floor()
        self.assertEqual(floor["version"], "5.3.6")


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

    def test_truthful_floor_keeps_reachability_and_usability_distinct(self) -> None:
        checks = self.info["floor"]["checks"]
        for key in (
            "process_reachable",
            "transport_reachable",
            "embedding_endpoint_reachable",
            "embedding_usable",
            "memory_readable",
            "kernel_readable",
            "operation_ledger_readable",
            "schedule_state",
            "heartbeat_state",
            "clock",
            "projection_drift",
        ):
            self.assertIn(key, checks)
            self.assertIn(checks[key]["status"], {"value", "unset", "failed", "uncertain", "unavailable"})
        self.assertEqual(checks["embedding_usable"]["status"], "unset")
        self.assertIn("endpoint reachability", checks["embedding_usable"]["reason"])


class RecoverySurfaceTests(unittest.TestCase):
    def test_recovery_report_keeps_heartbeat_and_schedule_ledgers_visible(self) -> None:
        async def run() -> dict:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                with patch.multiple(
                    settings,
                    memory_collection_name="missing-memory",
                    operation_ledger_file=str(root / "operations.jsonl"),
                    heartbeat_ledger_file=str(root / "heartbeats.jsonl"),
                    schedule_config_file=str(root / "schedule.jsonl"),
                    schedule_events_file=str(root / "schedule-events.jsonl"),
                ), patch(
                    "mcp_experiments.tools.info.repository.collection_exists",
                    return_value=False,
                ):
                    return await nephesh_recovery_report()

        report = asyncio.run(run())
        self.assertIn("heartbeat", report)
        self.assertIn("schedule", report)
        self.assertEqual(report["heartbeat"]["status"], "unset")
        self.assertEqual(report["schedule"]["status"], "unset")

    def test_malformed_floor_records_are_failed_not_process_errors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            schedule = root / "schedule-events.jsonl"
            schedule.write_text('[]\n"not an object"\n', encoding="utf-8")
            with patch.multiple(
                settings,
                schedule_config_file=str(root / "schedule.jsonl"),
                schedule_events_file=str(schedule),
            ):
                from mcp_experiments.tools.info import _read_schedule_floor
                result = _read_schedule_floor()
            self.assertEqual(result["status"], "failed")


class HealthStatusTests(unittest.TestCase):
    def test_failed_critical_floor_check_degrades_health(self) -> None:
        floor = {"checks": {
            "process_reachable": {"status": "value", "value": True},
            "transport_reachable": {"status": "value", "value": True},
            "memory_readable": {"status": "failed", "reason": "store unavailable"},
        }}
        self.assertEqual(_health_status(floor), "degraded")


if __name__ == "__main__":
    unittest.main()
