from __future__ import annotations

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from mcp_experiments.tools.heartbeat import _message_dedupe_key


class GuildhallHeartbeatTests(unittest.TestCase):
    def test_same_body_with_distinct_stanzas_is_not_collapsed(self) -> None:
        first = {
            "room": "family@muc.guildhall.local",
            "stanza_id": "stanza-a",
            "from": "gaius@guildhall.local/gaius",
            "body": "repeat this",
        }
        second = {**first, "stanza_id": "stanza-b"}
        self.assertNotEqual(_message_dedupe_key(first), _message_dedupe_key(second))

    def test_replayed_stanza_has_the_same_dedupe_key(self) -> None:
        message = {
            "room": "family@muc.guildhall.local",
            "stanza_id": "stanza-a",
            "from": "gaius@guildhall.local/gaius",
            "body": "same event",
        }
        self.assertEqual(_message_dedupe_key(message), _message_dedupe_key(dict(message)))


if __name__ == "__main__":
    unittest.main()
