from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from mcp_experiments.config import settings
from mcp_experiments.tools import guildhall
from mcp_experiments.tools.info import nephesh_info


class GuildhallManualToolTests(unittest.TestCase):
    def test_leave_all_sends_unavailable_for_each_configured_room(self) -> None:
        class FakeMuc:
            def __init__(self):
                self.left = []

            async def leave_muc(self, room, nick):
                self.left.append((room, nick))

        class FakeClient:
            def __init__(self, muc):
                self.plugin = {"xep_0045": muc}

        old_rooms = settings.guildhall_rooms_raw
        old_nick = settings.guildhall_nick
        muc = FakeMuc()
        bot = guildhall._GuildhallBot.__new__(guildhall._GuildhallBot)
        bot.client = FakeClient(muc)
        try:
            settings.guildhall_rooms_raw = "family@muc.guildhall.local,guildhall@muc.guildhall.local"
            settings.guildhall_nick = "test-agent"
            asyncio.run(bot.leave_all())
            self.assertEqual(muc.left, [
                ("family@muc.guildhall.local", "test-agent"),
                ("guildhall@muc.guildhall.local", "test-agent"),
            ])
        finally:
            settings.guildhall_rooms_raw = old_rooms
            settings.guildhall_nick = old_nick

    def test_manual_queue_cursor_is_durable_and_independent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old_queue = settings.guildhall_manual_queue_file
            old_cursor = settings.guildhall_manual_cursor_file
            try:
                settings.guildhall_manual_queue_file = str(root / "queue.jsonl")
                settings.guildhall_manual_cursor_file = str(root / "cursor.json")
                guildhall._append_manual_queue({"event_id": "one", "room": "family", "body": "first"})
                guildhall._append_manual_queue({"event_id": "two", "room": "family", "body": "second"})
                guildhall._append_manual_queue({"event_id": "other", "room": "guildhall", "body": "other"})

                first = guildhall._read_manual_queue("family", 10, True)
                second = guildhall._read_manual_queue("family", 10, True)
                other = guildhall._read_manual_queue("guildhall", 10, True)
                self.assertEqual([item["event_id"] for item in first], ["one", "two"])
                self.assertEqual(second, [])
                self.assertEqual([item["event_id"] for item in other], ["other"])
            finally:
                settings.guildhall_manual_queue_file = old_queue
                settings.guildhall_manual_cursor_file = old_cursor

    def test_outbound_confirmation_releases_waiter(self) -> None:
        import threading
        key = ("family@muc.guildhall.local", "hello")
        waiter = threading.Event()
        with guildhall._outbound_lock:
            guildhall._outbound_waiters[key] = [waiter]
        guildhall._confirm_outbound(*key)
        self.assertTrue(waiter.is_set())
        with guildhall._outbound_lock:
            self.assertNotIn(key, guildhall._outbound_waiters)

    def test_manual_send_stamps_once_and_scopes_room(self) -> None:
        old_rooms = settings.guildhall_rooms_raw
        old_room = settings.guildhall_room
        original_send = guildhall.send_message_sync
        sent: list[tuple[str, str]] = []
        try:
            settings.guildhall_rooms_raw = "family@guildhall.local"
            settings.guildhall_room = "family@guildhall.local"
            guildhall.send_message_sync = lambda room, body, delivery="groupchat": sent.append((room, body)) or True
            result = asyncio.run(guildhall.guildhall_send_as_self("hello"))
            payload = json.loads(result)
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(len(sent), 1)
            self.assertEqual(sent[0][1].count(guildhall.GUILDHALL_OUTBOUND_PROVENANCE_STAMP), 1)
            self.assertEqual(json.loads(asyncio.run(guildhall.guildhall_send_as_self("x", "other@room")))["status"], "error")
        finally:
            settings.guildhall_rooms_raw = old_rooms
            settings.guildhall_room = old_room
            guildhall.send_message_sync = original_send

    def test_nephesh_info_returns_version_field(self) -> None:
        payload = json.loads(nephesh_info())
        self.assertIn("version", payload)
        self.assertTrue(payload["version"])


if __name__ == "__main__":
    unittest.main()
