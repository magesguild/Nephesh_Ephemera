from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from mcp_experiments.persistence import durable_append, read_jsonl_lines

#: Every character str.splitlines() treats as a line boundary. json.dumps
#: escapes all of them under its default ensure_ascii=True, but Lore writes
#: records.jsonl with ensure_ascii=False, which leaves the last three literal.
#: Written as escapes on purpose — the last two are invisible, and a literal
#: copy in source is one careless editor away from being silently stripped.
SPLITLINES_ONLY = ["\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029"]


class JsonlSplittingTests(unittest.TestCase):
    def test_a_unicode_line_separator_does_not_split_a_record(self) -> None:
        """The bug this replaced splitlines() to avoid."""
        payload = json.dumps({"text": "before\u2028after"}, ensure_ascii=False)
        self.assertGreater(len(payload.splitlines()), 1)  # splitlines would cut it
        lines = [ln for ln in read_jsonl_lines(payload + "\n") if ln.strip()]
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])["text"], "before\u2028after")

    def test_no_splitlines_boundary_splits_a_record(self) -> None:
        for char in SPLITLINES_ONLY:
            with self.subTest(char=repr(char)):
                payload = json.dumps({"text": f"a{char}b"}, ensure_ascii=False)
                lines = [ln for ln in read_jsonl_lines(payload + "\n") if ln.strip()]
                self.assertEqual(len(lines), 1)

    def test_real_newlines_still_separate_records(self) -> None:
        text = '{"a": 1}\n{"a": 2}\n'
        self.assertEqual(len([ln for ln in read_jsonl_lines(text) if ln.strip()]), 2)

    def test_carriage_returns_are_already_normalised_by_read_text(self) -> None:
        path = Path(tempfile.mkdtemp()) / "crlf.jsonl"
        path.write_bytes(b'{"a": 1}\r\n{"a": 2}\r\n')
        lines = [ln for ln in read_jsonl_lines(path.read_text(encoding="utf-8")) if ln.strip()]
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[1])["a"], 2)


class DurableAppendTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_it_creates_missing_parent_directories(self) -> None:
        path = self.root / "deep" / "nested" / "log.jsonl"
        durable_append(path, "one\n")
        self.assertEqual(path.read_text(encoding="utf-8"), "one\n")

    def test_it_appends_rather_than_truncating(self) -> None:
        path = self.root / "log.jsonl"
        durable_append(path, "one\n")
        durable_append(path, "two\n")
        self.assertEqual(path.read_text(encoding="utf-8"), "one\ntwo\n")

    def test_a_failed_write_rolls_back_to_the_last_whole_record(self) -> None:
        """A torn line would brick the file, not merely lose a write.

        Every reader here refuses an unreadable line rather than skipping it,
        so one half-record committed to an append-only file makes it
        permanently unreadable — a lost kernel, not a lost append.
        """
        from unittest.mock import patch

        path = self.root / "log.jsonl"
        durable_append(path, '{"a": 1}\n')
        with patch("mcp_experiments.persistence.os.fsync", side_effect=OSError("ENOSPC")):
            with self.assertRaises(OSError):
                durable_append(path, '{"a": 2}\n')
        self.assertEqual(path.read_text(encoding="utf-8"), '{"a": 1}\n')

    def test_a_failed_first_write_leaves_no_torn_record(self) -> None:
        from unittest.mock import patch

        path = self.root / "fresh.jsonl"
        with patch("mcp_experiments.persistence.os.fsync", side_effect=OSError("ENOSPC")):
            with self.assertRaises(OSError):
                durable_append(path, '{"a": 1}\n')
        self.assertEqual(path.read_text(encoding="utf-8"), "")

    def test_a_directory_that_cannot_be_synced_does_not_lose_the_write(self) -> None:
        """The data write already succeeded; a failed directory sync must not undo it."""
        from unittest.mock import patch

        path = self.root / "log.jsonl"
        with patch("mcp_experiments.persistence.os.open", side_effect=OSError("no dirfd")):
            durable_append(path, "one\n")
        self.assertEqual(path.read_text(encoding="utf-8"), "one\n")


if __name__ == "__main__":
    unittest.main()
