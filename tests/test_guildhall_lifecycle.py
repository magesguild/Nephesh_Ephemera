from __future__ import annotations

import unittest

from mcp_experiments.guildhall_lifecycle import (
    Decision,
    DecisionResult,
    EventState,
    GuildhallEvent,
    GuildhallLifecycle,
    TerminalDeliveryFailure,
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

    def test_terminal_delivery_failure_is_never_retried(self) -> None:
        class Memory:
            def capture(self, event):
                pass

        class Decisions:
            def decide(self, event):
                return DecisionResult(Decision.REPLY, "already queued")

        class Delivery:
            def __init__(self):
                self.calls = 0

            def send(self, event, body):
                self.calls += 1
                raise TerminalDeliveryFailure("delivery uncertain")

        delivery = Delivery()
        lifecycle = GuildhallLifecycle(Memory(), Decisions(), delivery)
        event = GuildhallEvent("event-terminal", "room", "sender", "hello")
        first = lifecycle.process(event)
        second = lifecycle.process(event)
        self.assertEqual(first.state, EventState.TERMINAL_FAILURE)
        self.assertIs(second, first)
        self.assertEqual(delivery.calls, 1)


if __name__ == "__main__":
    unittest.main()
