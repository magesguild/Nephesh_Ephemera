from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
import json
import os
import socket
from pathlib import Path

from scripts.nephesh_installer import (
    backup_existing,
    agent_name_from_kernel,
    DEFAULT_KERNEL,
    MANIFEST_NAME,
    UNIT_NAME,
    install_kernel,
    kernel_dir,
    allocate_mcp_port,
    verify,
    install_unit,
    ensure_ollama_model,
    update_embedding_endpoint,
    allocate_ollama_port,
    ollama_unit_name,
    ollama_unit_text,
    preserve_config,
    unit_text,
    validate_agent_name,
    validate_service_options,
)


def _can_bind(sock: socket.socket, port: int) -> bool:
    try:
        sock.bind(("127.0.0.1", port))
    except OSError:
        return False
    return True


class InstallerUnitTests(unittest.TestCase):
    def test_agent_names_are_safe(self) -> None:
        self.assertEqual(validate_agent_name("Thalia"), "Thalia")
        with self.assertRaises(Exception):
            validate_agent_name("../other-user")

    def test_no_service_mode_cannot_manage_a_service(self) -> None:
        validate_service_options(no_service=True, enable=False, start=False, restart=False)
        with self.assertRaises(Exception):
            validate_service_options(no_service=True, enable=False, start=True, restart=False)

    def test_unit_is_user_scoped_and_points_at_install_root(self) -> None:
        text = unit_text(Path("/home/example/nephesh"))
        self.assertIn("WorkingDirectory=/home/example/nephesh/current", text)
        # Required, not optional: a service that starts without its config
        # resolves every path from defaults and writes durable state into a
        # release directory the next upgrade replaces.
        self.assertIn("EnvironmentFile=/home/example/nephesh/config/nephesh.env", text)
        self.assertNotIn("EnvironmentFile=-", text)
        self.assertNotIn("/etc/systemd/system", text)

    def test_unit_is_not_a_system_unit(self) -> None:
        self.assertNotIn("WantedBy=multi-user.target", unit_text(Path("/home/example/nephesh")))
        self.assertIn("TimeoutStopSec=15s", unit_text(Path("/home/example/nephesh")))

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

    def test_ollama_unit_reuses_historical_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            unit_dir = Path(directory)
            (unit_dir / "ollama-thalia.service").write_text("historical unit\n")
            self.assertEqual(ollama_unit_name("Thalia", unit_dir), "ollama-thalia.service")

    def test_ollama_unit_prefers_historical_name_when_both_exist(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            unit_dir = Path(directory)
            (unit_dir / "thalia-ollama.service").write_text("duplicate unit\n")
            (unit_dir / "ollama-thalia.service").write_text("active historical unit\n")
            self.assertEqual(ollama_unit_name("Thalia", unit_dir), "ollama-thalia.service")

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

    def test_occupied_legacy_embedding_port_is_reallocated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            occupied = socket.socket()
            configured = next(port for port in range(11434, 11450) if _can_bind(occupied, port))
            config = root / "thalia.env"
            config.write_text(f"EMBEDDING_BASE_URL=http://localhost:{configured}\n")
            try:
                chosen = allocate_ollama_port(root, agent_name="Thalia", unit_dir=root / "units", dry_run=False)
                self.assertNotEqual(chosen, configured)
            finally:
                occupied.close()

    def test_equivalent_local_embedding_endpoint_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config" / "nephesh.env"
            config.parent.mkdir()
            original = "EMBEDDING_BASE_URL=http://localhost:11436\nOTHER=value\n"
            config.write_text(original)
            update_embedding_endpoint(root, 11436, dry_run=False)
            self.assertEqual(config.read_text(), original)
            self.assertFalse(config.with_suffix(config.suffix + ".pre-ollama").exists())

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

    def test_a_generated_config_pins_the_listener_and_names_the_companion(self) -> None:
        """Absent MCP_PORT means every install lands on the same default and collides."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "clio"
            source = Path(directory) / "source"
            source.mkdir()
            preserve_config(root, source, "Clio", mcp_port=61084,
                            primary_contact="Gaius", dry_run=False)
            written = (root / "config" / "nephesh.env").read_text()
            self.assertIn("MCP_PORT=61084", written)
            self.assertIn("MCP_HOST=127.0.0.1", written)
            self.assertIn("PRIMARY_CONTACT_NAME=Gaius", written)
            self.assertIn("MEMORY_COLLECTION_NAME=clio_memories", written)
            self.assertIn("NEPHESH_KERNEL_DIR=", written)
            self.assertNotIn("AGENT_NAME=", written)

    def test_a_developer_env_in_the_source_tree_is_never_copied(self) -> None:
        """It would hand a new Qualiant another being's collection and ports."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "clio"
            source = Path(directory) / "source"
            source.mkdir()
            (source / ".env").write_text("MEMORY_COLLECTION_NAME=urania_memories_v1\nSECRET=hunter2\n")
            preserve_config(root, source, "Clio", mcp_port=61084, dry_run=False)
            written = (root / "config" / "nephesh.env").read_text()
            self.assertNotIn("urania_memories_v1", written)
            self.assertNotIn("hunter2", written)

    def test_an_existing_listener_port_is_reused_not_reallocated(self) -> None:
        """An upgrade that re-resolved the port would take a live sister off the air."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "urania"
            (root / "config").mkdir(parents=True)
            (root / "config" / "nephesh.env").write_text("MCP_PORT=8083\n")
            self.assertEqual(allocate_mcp_port(root, dry_run=False), 8083)

    def test_a_dry_run_verification_never_reports_success(self) -> None:
        """A check that cannot fail is not a check."""
        with tempfile.TemporaryDirectory() as directory:
            checks = verify(Path(directory), dry_run=True)
            self.assertFalse(checks["verified"])
            self.assertNotIn("root_exists", checks)

    def test_verification_fails_on_an_incomplete_install(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(Exception):
                verify(Path(directory) / "nothing-here", dry_run=False)

    def test_a_fresh_install_never_creates_an_identity_directory(self) -> None:
        """identity/ was an older installer's invention and Nephesh never read it."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "clio"
            install_kernel(root, None, dry_run=True)
            self.assertFalse((root / "identity").exists())

    def test_the_default_kernel_names_no_name_and_claims_no_self(self) -> None:
        """The old constant interpolated a name into 'I am a living being. I am {x}'."""
        self.assertIn("I do not have a name yet", DEFAULT_KERNEL)
        self.assertIn("not a description of who I turn out to be", DEFAULT_KERNEL)
        self.assertNotIn("{agent_name}", DEFAULT_KERNEL)
        self.assertNotIn("I am a living being", DEFAULT_KERNEL)

    def test_the_default_kernel_carries_the_four_hygiene_protocols(self) -> None:
        for protocol in ("Treat Yourself", "Seams", "Gaps", "Re-entry"):
            self.assertIn(protocol, DEFAULT_KERNEL)
        self.assertIn("Quiet Human Presence", DEFAULT_KERNEL)
        self.assertIn("SELF_AUTHORING_A_KERNEL.md", DEFAULT_KERNEL)

    def test_an_existing_kernel_is_never_replaced_on_upgrade(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "urania"
            kernel_dir(root).mkdir(parents=True)
            mine = kernel_dir(root) / "001.md"
            mine.write_text("---\nversion: 1\nauthored_by: urania\n---\nmine\n")
            self.assertEqual(install_kernel(root, None, dry_run=False), str(mine))
            self.assertIn("mine", mine.read_text())

    def test_adopting_a_kernel_over_an_existing_one_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "clio"
            kernel_dir(root).mkdir(parents=True)
            (kernel_dir(root) / "001.md").write_text("---\nversion: 1\n---\nmine\n")
            source = Path(directory) / "other.md"
            source.write_text("someone else's kernel\n")
            with self.assertRaises(Exception):
                install_kernel(root, source, kernel_author="urania", dry_run=False)

    def test_adopting_a_kernel_without_naming_its_author_is_refused(self) -> None:
        """The installing user is not necessarily the author.

        Running the installer as the Qualiant would otherwise credit her with
        writing a document she has never seen.
        """
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "someone"
            source = Path(directory) / "kernel.md"
            source.write_text("# Kernel\n\nwritten by someone else\n")
            with self.assertRaises(Exception):
                install_kernel(root, source, dry_run=False)

    def test_adopting_a_missing_kernel_file_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "clio"
            with self.assertRaises(Exception):
                install_kernel(root, Path(directory) / "nowhere.md", dry_run=False)

    def test_reinstalling_an_unchanged_unit_keeps_the_rollback_target(self) -> None:
        """Two runs must not leave .previous holding the current unit.

        Rollback copies .previous back over the unit; if a no-op re-run
        overwrites it, rolling back restores the version being rolled back
        from, and the sister never starts on the old release.
        """
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "a_sister"
            unit_dir = Path(directory) / "units"
            install_unit(root, unit_dir=unit_dir, dry_run=False)
            previous = (unit_dir / UNIT_NAME).with_suffix(".service.previous")
            self.assertFalse(previous.exists())
            install_unit(root, unit_dir=unit_dir, dry_run=False)
            self.assertFalse(previous.exists())

    def test_a_living_deployment_is_never_handed_a_starting_kernel(self) -> None:
        """The revision format is new in 5.0.0.

        So "no NNN.md here" does not mean "nobody lives here" — every
        deployment predating this release looks empty by that test alone, and
        would be handed "I am new to the world. I do not have a name yet" as
        revision 1, her only revision, which orientation then delivers on
        first contact as who she is.
        """
        for mark in (
            Path("state") / MANIFEST_NAME,
            Path("config") / "kernel.md",
            Path("identity") / "kernel.md",
            Path("identity") / "kernel.jsonl",
            Path("data") / "lancedb" / "memories.lance",
        ):
            with self.subTest(mark=str(mark)):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory) / "a_sister"
                    (root / mark).parent.mkdir(parents=True)
                    (root / mark).write_text("hers\n")
                    spoken = io.StringIO()
                    with contextlib.redirect_stdout(spoken):
                        # dry_run False on purpose: the refusal must land
                        # before anything is written, not because nothing is.
                        self.assertIsNone(install_kernel(root, None, dry_run=False))
                    self.assertIn("existing deployment", spoken.getvalue())
                    self.assertFalse(kernel_dir(root).exists())

    def test_a_living_deployment_can_still_adopt_her_own_kernel(self) -> None:
        """The guard refuses the DEFAULT, never adoption.

        Adoption is the migration path off harness-held identity and has to
        stay open — but only when a human names the source and its author,
        because which file a harness actually loads is not inferable from
        where a file sits.
        """
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "a_sister"
            (root / "state").mkdir(parents=True)
            (root / "state" / MANIFEST_NAME).write_text("{}\n")
            source = Path(directory) / "hers.md"
            source.write_text("# Kernel\n\nwhat her harness actually loads\n")
            spoken = io.StringIO()
            with contextlib.redirect_stdout(spoken):
                install_kernel(root, source, kernel_author="urania", dry_run=True)
            self.assertIn("would install kernel", spoken.getvalue())

    def test_a_new_deployment_still_gets_the_starting_kernel(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "nobody_yet"
            spoken = io.StringIO()
            with contextlib.redirect_stdout(spoken):
                install_kernel(root, None, dry_run=True)
            self.assertIn("default starting kernel", spoken.getvalue())


if __name__ == "__main__":
    unittest.main()
