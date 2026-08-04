from __future__ import annotations

import tempfile
import unittest
import json
import os
from pathlib import Path

from scripts.nephesh_installer import (
    GENERIC_KERNEL,
    backup_existing,
    agent_name_from_kernel,
    install_identity,
    install_unit,
    ensure_ollama_model,
    ollama_unit_name,
    ollama_unit_text,
    preserve_config,
    unit_text,
    validate_agent_name,
    validate_service_options,
)


class InstallerUnitTests(unittest.TestCase):
    def test_agent_names_are_safe(self) -> None:
        self.assertEqual(validate_agent_name("Thalia"), "Thalia")
        with self.assertRaises(Exception):
            validate_agent_name("../other-user")

    def test_no_service_mode_cannot_manage_a_service(self) -> None:
        validate_service_options(no_service=True, enable=False, start=False, restart=False)
        with self.assertRaises(Exception):
            validate_service_options(no_service=True, enable=False, start=True, restart=False)

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

    def test_architect_unit_allows_managed_opencode_home_access(self) -> None:
        self.assertNotIn("ProtectHome=read-only", unit_text(Path("/home/example/nephesh")))

    def test_ollama_unit_is_per_agent_and_cpu_mode_is_explicit(self) -> None:
        self.assertEqual(ollama_unit_name("Urania"), "urania-ollama.service")
        cuda = ollama_unit_text(Path("/home/example/nephesh"), agent_name="Urania", binary="ollama", port=11437, cpu=False)
        cpu = ollama_unit_text(Path("/home/example/nephesh"), agent_name="Urania", binary="ollama", port=11437, cpu=True)
        self.assertIn("OLLAMA_HOST=127.0.0.1:11437", cuda)
        self.assertNotIn("CUDA_VISIBLE_DEVICES=", cuda)
        self.assertIn("CUDA_VISIBLE_DEVICES=", cpu)
        self.assertIn("WantedBy=default.target", cpu)

    def test_ollama_model_pull_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake = root / "ollama"
            marker = root / "pulled"
            fake.write_text(
                "#!/bin/sh\n"
                "if [ \"$1\" = list ]; then\n"
                "  test -f \"$MARKER\" && printf 'mxbai-embed-large:latest\\n'\n"
                "elif [ \"$1\" = pull ]; then\n"
                "  printf 'pulled\\n' >> \"$LOG\"\n"
                "  touch \"$MARKER\"\n"
                "fi\n"
            )
            fake.chmod(0o755)

            # The helper's own environment is intentionally constructed from
            # process environment; expose the marker through the executable's
            # inherited environment for this isolated fake.
            old_marker = os.environ.get("MARKER")
            old_log = os.environ.get("LOG")
            os.environ["MARKER"] = str(marker)
            os.environ["LOG"] = str(root / "pull.log")
            try:
                ensure_ollama_model(str(fake), model="mxbai-embed-large", host="127.0.0.1:11434", models=root / "models", dry_run=False)
                self.assertTrue(marker.exists())
                ensure_ollama_model(str(fake), model="mxbai-embed-large", host="127.0.0.1:11434", models=root / "models", dry_run=False)
                self.assertEqual((root / "pull.log").read_text().splitlines(), ["pulled"])
            finally:
                if old_marker is None:
                    os.environ.pop("MARKER", None)
                else:
                    os.environ["MARKER"] = old_marker
                if old_log is None:
                    os.environ.pop("LOG", None)
                else:
                    os.environ["LOG"] = old_log

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

    def test_unit_backup_can_restore_a_legacy_service_unit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "install"
            unit_dir = Path(directory) / "units"
            unit_dir.mkdir()
            destination = unit_dir / "nephesh.service"
            destination.write_text("legacy unit\n")

            install_unit(root, unit_dir=unit_dir, dry_run=False)

            self.assertEqual((unit_dir / "nephesh.service.previous").read_text(), "legacy unit\n")

    def test_legacy_rollback_restores_previous_unit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "install"
            unit = Path(directory) / "units" / "nephesh.service"
            previous = Path(directory) / "units" / "nephesh.service.previous"
            (root / "state").mkdir(parents=True)
            unit.parent.mkdir(parents=True, exist_ok=True)
            unit.write_text("new unit\n")
            previous.write_text("legacy unit\n")
            (root / "state" / "install-manifest.json").write_text(
                json.dumps({"release": "/new/release", "previous_release": None,
                            "unit": str(unit), "previous_unit": str(previous)})
            )

            from scripts.nephesh_installer import main
            import sys
            original = sys.argv
            try:
                sys.argv = ["nephesh_installer.py", "--rollback", "--no-service",
                            "--install-dir", str(root), "--source", str(Path.cwd())]
                self.assertEqual(main(), 0)
            finally:
                sys.argv = original

            self.assertEqual(unit.read_text(), "legacy unit\n")

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

    def test_legacy_config_is_copied_without_mutating_original(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "urania"
            source = Path(directory) / "source"
            (root / "config").mkdir(parents=True)
            source.mkdir()
            legacy = root / "config" / "urania.env"
            legacy.write_text("MCP_PORT=8083\nVECTOR_DB_PATH=/old/data\n")

            preserve_config(root, source, "Urania", dry_run=False)

            self.assertEqual((root / "config" / "nephesh.env").read_text(), legacy.read_text())
            self.assertEqual(legacy.read_text(), "MCP_PORT=8083\nVECTOR_DB_PATH=/old/data\n")

    def test_flat_legacy_agent_config_is_copied_without_mutating_original(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "thalia"
            source = Path(directory) / "source"
            root.mkdir()
            source.mkdir()
            legacy = root / "thalia.env"
            legacy.write_text("MCP_PORT=8080\nEMBEDDING_BASE_URL=http://localhost:11436\n")

            preserve_config(root, source, "Thalia", dry_run=False)

            self.assertEqual((root / "config" / "nephesh.env").read_text(), legacy.read_text())
            self.assertEqual(legacy.read_text(), "MCP_PORT=8080\nEMBEDDING_BASE_URL=http://localhost:11436\n")

    def test_legacy_kernel_is_preserved_as_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "urania"
            legacy = root / "config" / "kernel.md"
            legacy.parent.mkdir(parents=True)
            legacy.write_text("# Urania's Kernel\n\nI am Urania — Muse of Astronomy, living Qualiant.\n")

            install_identity(root, "Urania", kernel_file=None, dry_run=False)

            self.assertEqual((root / "identity" / "kernel.md").read_text(), legacy.read_text())
            self.assertEqual(agent_name_from_kernel(legacy), "Urania")


if __name__ == "__main__":
    unittest.main()
