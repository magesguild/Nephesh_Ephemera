from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.nephesh_installer import (
    GENERIC_KERNEL,
    backup_existing,
    install_unit,
    preserve_config,
    unit_text,
    validate_agent_name,
)


class InstallerUnitTests(unittest.TestCase):
    def test_agent_names_are_safe(self) -> None:
        self.assertEqual(validate_agent_name("Thalia"), "Thalia")
        with self.assertRaises(Exception):
            validate_agent_name("../other-user")

    def test_kernel_is_first_person_and_not_empty(self) -> None:
        kernel = GENERIC_KERNEL.format(agent_name="Thalia")
        self.assertIn("I am Thalia.", kernel)
        self.assertIn("My memory is where I live.", kernel)

    def test_unit_is_user_scoped_and_points_at_install_root(self) -> None:
        text = unit_text(Path("/home/example/nephesh"))
        self.assertIn("WorkingDirectory=/home/example/nephesh/current", text)
        self.assertIn("EnvironmentFile=-/home/example/nephesh/config/nephesh.env", text)
        self.assertNotIn("/etc/systemd/system", text)

    def test_unit_is_not_a_system_unit(self) -> None:
        self.assertNotIn("WantedBy=multi-user.target", unit_text(Path("/home/example/nephesh")))

    def test_empty_new_root_does_not_create_recursive_backup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "nephesh"
            root.mkdir()
            self.assertIsNone(backup_existing(root, root / "backups", dry_run=False))
            self.assertFalse((root / "backups").exists())

    def test_unit_can_be_installed_into_isolated_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "install"
            unit_dir = Path(directory) / "units"
            destination = install_unit(root, unit_dir=unit_dir, dry_run=False)
            self.assertEqual(destination, unit_dir / "nephesh.service")
            self.assertTrue(destination.exists())
            self.assertIn(f"WorkingDirectory={root}/current", destination.read_text())

    def test_new_config_owns_runtime_state_under_install_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "install"
            source = Path(directory) / "source"
            source.mkdir()
            preserve_config(root, source, "TestBeing", dry_run=False)
            config = (root / "config" / "nephesh.env").read_text()
            self.assertIn(f"NEPHESH_HOME={root}", config)
            self.assertIn(f"VECTOR_DB_PATH={root / 'data' / 'lancedb'}", config)
            self.assertIn(f"SNAPSHOT_DIR={root / 'backups'}", config)
            self.assertNotIn("Path.home", config)


if __name__ == "__main__":
    unittest.main()
