from __future__ import annotations

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from mcp_experiments.tools.heartbeat import _message_dedupe_key
from mcp_experiments.tools.heartbeat import _batch_collaborators
from mcp_experiments.tools.opencode_bridge import (
    GUILDHALL_PROVENANCE_STAMP,
    GUILDHALL_SELF_PROVENANCE_STAMP,
    _format_guildhall_messages,
)


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

    def test_every_opencode_message_line_has_guildhall_provenance(self) -> None:
        rendered = _format_guildhall_messages([
            {"from": "gaius", "body": "first"},
            {"from": "mel", "body": "second"},
        ])
        self.assertEqual(rendered.count("Provenance: this message arrived from guildhall via opencode"), 2)

        already_stamped = _format_guildhall_messages([
            {"from": "gaius", "body": f"[{GUILDHALL_PROVENANCE_STAMP}] first"},
        ])
        self.assertEqual(already_stamped.count(GUILDHALL_PROVENANCE_STAMP), 1)

        own_message = _format_guildhall_messages([
            {
                "from": "family@muc.guildhall.local/urania",
                "body": "my earlier message",
                "self_authored": True,
            },
        ])
        self.assertIn(GUILDHALL_SELF_PROVENANCE_STAMP, own_message)

    def test_batch_collaborators_expose_batch_protocol_methods(self) -> None:
        capture, decide, deliver = _batch_collaborators(lambda batch: None, lambda batch: None, lambda batch, body: None)
        self.assertTrue(callable(capture.capture_batch))
        self.assertTrue(callable(decide.decide_batch))
        self.assertTrue(callable(deliver.send_batch))


if __name__ == "__main__":
    unittest.main()
