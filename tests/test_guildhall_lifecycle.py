from __future__ import annotations

import unittest

from mcp_experiments.guildhall_lifecycle import (
    Decision,
    DecisionResult,
    EventState,
    GuildhallEvent,
    GuildhallLifecycle,
)


class GuildhallLifecycleTests(unittest.TestCase):
    def test_unexpected_adapter_error_is_retryable(self) -> None:
        class Memory:
            def capture(self, event):
                raise ValueError("temporary embedding outage")

        class Decisions:
            def decide(self, event):
                return DecisionResult(Decision.NO_REPLY)

        class Delivery:
            def send(self, event, body):
                raise AssertionError("delivery should not run")

        record = GuildhallLifecycle(Memory(), Decisions(), Delivery()).process(
            GuildhallEvent("event-1", "room", "sender", "hello")
        )
        self.assertEqual(record.state, EventState.RETRYABLE_FAILURE)
        self.assertIn("temporary embedding outage", record.error or "")


if __name__ == "__main__":
    unittest.main()
