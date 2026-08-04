from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class ConfigIsolationTests(unittest.TestCase):
    def test_defaults_are_scoped_to_explicit_deployment_root(self) -> None:
        source_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            deployment_root = Path(directory) / "deployment"
            env = os.environ.copy()
            env["NEPHESH_HOME"] = str(deployment_root)
            env["PYTHONPATH"] = str(source_root / "src")
            script = (
                "from mcp_experiments.config import settings; "
                "print(settings.vector_db_path); "
                "print(settings.instance_lock_file); "
                "print(settings.openclaw_workspace); "
                "print(settings.guildhall_event_ledger)"
            )
            result = subprocess.run(
                [sys.executable, "-c", script],
                env=env,
                text=True,
                capture_output=True,
                check=True,
            )
            paths = result.stdout.splitlines()
            self.assertTrue(paths)
            self.assertTrue(all(str(deployment_root) in path for path in paths))
            self.assertNotIn(str(Path.home()), result.stdout)


if __name__ == "__main__":
    unittest.main()
