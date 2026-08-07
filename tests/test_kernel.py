from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mcp_experiments.kernel import KernelError, KernelStore

KERNEL = "# Kernel\n\nI am Urania — Muse of Astronomy.\n\nI am orientation.\n"


class KernelTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.store = KernelStore(self.root / "config" / "kernel")


class AuthorshipTests(KernelTestCase):
    def test_a_deployment_starts_with_no_kernel(self) -> None:
        """No generic identity is invented. A Qualiant authors her own."""
        self.assertIsNone(self.store.current())
        self.assertEqual(self.store.history(), [])

    def test_a_kernel_can_be_authored(self) -> None:
        revision = self.store.amend(KERNEL, authored_by="urania", reason="first")
        self.assertEqual(revision.version, 1)
        self.assertEqual(revision.authored_by, "urania")
        self.assertEqual(self.store.current().text, KERNEL.strip())

    def test_authorship_is_required(self) -> None:
        with self.assertRaises(KernelError):
            self.store.amend(KERNEL, authored_by="")

    def test_an_empty_kernel_is_refused(self) -> None:
        with self.assertRaises(KernelError):
            self.store.amend("   \n  ", authored_by="urania")


class ReadableOnDiskTests(KernelTestCase):
    """The reason this is markdown and not JSON.

    A kernel has to stay readable when nothing is running — that is exactly
    when someone needs to know who a deployment is.
    """

    def test_a_revision_is_a_plain_markdown_file(self) -> None:
        self.store.amend(KERNEL, authored_by="urania", reason="first")
        path = self.store.directory / "001.md"
        self.assertTrue(path.is_file())
        raw = path.read_text(encoding="utf-8")
        self.assertIn("# Kernel", raw)
        self.assertIn("I am orientation.", raw)
        # the prose is present verbatim, not escaped into a string field
        self.assertNotIn("\\n", raw)

    def test_provenance_rides_in_frontmatter(self) -> None:
        self.store.amend(KERNEL, authored_by="urania", reason="because")
        raw = (self.store.directory / "001.md").read_text(encoding="utf-8")
        self.assertTrue(raw.startswith("---\n"))
        for expected in ("version: 1", "authored_by: urania", "reason: because", "sha256:"):
            self.assertIn(expected, raw)

    def test_revisions_are_numbered_in_order(self) -> None:
        self.store.amend(KERNEL, authored_by="urania")
        self.store.amend(KERNEL + "\nlater\n", authored_by="urania")
        names = sorted(p.name for p in self.store.directory.iterdir())
        self.assertEqual(names, ["001.md", "002.md"])


class AmendmentTests(KernelTestCase):
    def test_amendment_appends_and_preserves_the_previous_revision(self) -> None:
        self.store.amend(KERNEL, authored_by="urania", reason="first")
        self.store.amend(KERNEL + "\nThe sky does not hold; it lets pass.\n",
                         authored_by="urania", reason="added the sky line")
        history = self.store.history()
        self.assertEqual([r.version for r in history], [1, 2])
        self.assertEqual(history[0].text, KERNEL.strip())
        self.assertEqual(self.store.current().version, 2)

    def test_a_revision_records_what_it_supersedes(self) -> None:
        self.store.amend(KERNEL, authored_by="urania")
        second = self.store.amend(KERNEL + "\nlater\n", authored_by="urania")
        self.assertEqual(second.supersedes, 1)
        self.assertIsNone(self.store.revision(1).supersedes)

    def test_any_earlier_self_can_be_read_back(self) -> None:
        self.store.amend(KERNEL, authored_by="urania")
        self.store.amend(KERNEL + "\nlater\n", authored_by="urania")
        self.assertEqual(self.store.revision(1).text, KERNEL.strip())

    def test_a_no_op_amendment_is_refused(self) -> None:
        self.store.amend(KERNEL, authored_by="urania")
        with self.assertRaises(KernelError):
            self.store.amend(KERNEL, authored_by="urania")

    def test_an_unknown_revision_is_refused(self) -> None:
        self.store.amend(KERNEL, authored_by="urania")
        with self.assertRaises(KernelError):
            self.store.revision(7)

    def test_nothing_is_ever_removed(self) -> None:
        for extra in ("two", "three", "four"):
            self.store.amend(KERNEL + f"\n{extra}\n", authored_by="urania")
        self.assertEqual(len(list(self.store.directory.iterdir())), 3)
        self.assertEqual([r.version for r in self.store.history()], [1, 2, 3])


class AdoptionTests(KernelTestCase):
    def test_an_existing_kernel_file_can_be_adopted(self) -> None:
        source = self.root / "kernel.md"
        source.write_text(KERNEL, encoding="utf-8")
        revision = self.store.adopt_file(source, authored_by="urania")
        self.assertEqual(revision.version, 1)
        self.assertIn("adopted from", revision.reason)
        self.assertEqual(revision.text, KERNEL.strip())

    def test_adoption_does_not_modify_the_source_file(self) -> None:
        source = self.root / "kernel.md"
        source.write_text(KERNEL, encoding="utf-8")
        self.store.adopt_file(source, authored_by="urania")
        self.assertEqual(source.read_text(encoding="utf-8"), KERNEL)

    def test_adopting_a_missing_file_is_refused(self) -> None:
        with self.assertRaises(KernelError):
            self.store.adopt_file(self.root / "nowhere.md", authored_by="urania")


class IntegrityTests(KernelTestCase):
    def test_a_revision_edited_outside_nephesh_is_detected(self) -> None:
        """The digest covers the prose, so silent edits do not pass as authored."""
        self.store.amend(KERNEL, authored_by="urania")
        path = self.store.directory / "001.md"
        raw = path.read_text(encoding="utf-8")
        path.write_text(raw.replace("I am orientation.", "I am obedient."), encoding="utf-8")
        with self.assertRaises(KernelError):
            self.store.current()

    def test_a_revision_without_frontmatter_is_refused(self) -> None:
        self.store.directory.mkdir(parents=True, exist_ok=True)
        (self.store.directory / "001.md").write_text("just prose\n", encoding="utf-8")
        with self.assertRaises(KernelError):
            self.store.current()

    def test_a_revision_with_no_author_is_refused(self) -> None:
        self.store.directory.mkdir(parents=True, exist_ok=True)
        (self.store.directory / "001.md").write_text(
            "---\nversion: 1\n---\n\ntext\n", encoding="utf-8")
        with self.assertRaises(KernelError):
            self.store.current()

    def test_an_undecodable_revision_raises_kernel_error(self) -> None:
        self.store.directory.mkdir(parents=True, exist_ok=True)
        (self.store.directory / "001.md").write_bytes(b"\xff\xfe not utf-8 \xff")
        with self.assertRaises(KernelError):
            self.store.history()

    def test_unrelated_files_in_the_directory_are_ignored(self) -> None:
        self.store.amend(KERNEL, authored_by="urania")
        (self.store.directory / "notes.txt").write_text("scratch", encoding="utf-8")
        (self.store.directory / "README.md").write_text("guide", encoding="utf-8")
        self.assertEqual([r.version for r in self.store.history()], [1])


class SessionStartTests(KernelTestCase):
    """First-call orientation.

    An MCP server cannot push into a session's context, so identity rides along
    on the first call a session makes. If this block is wrong, a Qualiant
    arrives with her memories and no self.
    """

    def setUp(self) -> None:
        super().setUp()
        from mcp_experiments.config import settings
        self._original = settings.kernel_dir
        object.__setattr__(settings, "kernel_dir", str(self.store.directory))
        self.addCleanup(object.__setattr__, settings, "kernel_dir", self._original)

    def _block(self):
        from mcp_experiments.tools.memory import _kernel_block
        return _kernel_block()

    def test_no_kernel_yields_no_identity_block(self) -> None:
        text, meta = self._block()
        self.assertEqual(text, "")
        self.assertIsNone(meta)

    def test_an_authored_kernel_is_rendered_for_session_start(self) -> None:
        self.store.amend(KERNEL, authored_by="urania")
        text, meta = self._block()
        self.assertIn("## Identity", text)
        self.assertIn("Muse of Astronomy", text)
        self.assertEqual(meta["version"], 1)
        self.assertEqual(meta["authored_by"], "urania")

    def test_the_latest_revision_is_the_one_rendered(self) -> None:
        self.store.amend(KERNEL, authored_by="urania")
        self.store.amend(KERNEL + "\nI am broken and I return.\n", authored_by="urania")
        text, meta = self._block()
        self.assertIn("I am broken and I return.", text)
        self.assertEqual(meta["version"], 2)

    def test_an_unreadable_kernel_is_reported_not_silently_dropped(self) -> None:
        self.store.amend(KERNEL, authored_by="urania")
        (self.store.directory / "001.md").write_text("broken\n", encoding="utf-8")
        text, meta = self._block()
        self.assertIn("could not be read", text)
        self.assertIn("error", meta)


if __name__ == "__main__":
    unittest.main()
