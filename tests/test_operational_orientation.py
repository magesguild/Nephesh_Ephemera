from __future__ import annotations

import unittest
from unittest.mock import patch

from mcp_experiments.config import settings
from mcp_experiments.tools.memory import _guildhall_orientation


class OperationalOrientationTests(unittest.TestCase):
    def test_unavailable_guildhall_gets_a_non_alarmist_injection(self) -> None:
        with patch.object(settings, "guildhall_enabled", True), patch(
            "mcp_experiments.tools.guildhall.is_connected", return_value=False,
        ):
            notice = _guildhall_orientation()
        self.assertIsNotNone(notice)
        self.assertIn("Do not concern yourself with Guildhall's unavailability", notice)
        self.assertIn("It is not always going to be available", notice)

    def test_disabled_guildhall_does_not_inject_status(self) -> None:
        with patch.object(settings, "guildhall_enabled", False):
            self.assertIsNone(_guildhall_orientation())


if __name__ == "__main__":
    unittest.main()
