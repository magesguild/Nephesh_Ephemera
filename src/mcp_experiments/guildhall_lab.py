"""Deterministic, in-process Guildhall behavior lab.

This lab exercises the shared Guildhall event/lifecycle core without starting a
Qualiant, OpenCode, XMPP, MongooseIM, or the live Nephesh memory store.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from tempfile import TemporaryDirectory

from .guildhall_lifecycle import (
    Decision,
    DecisionResult,
    EventState,
    GuildhallBatch,
    GuildhallBatchLifecycle,
    GuildhallEvent,
    GuildhallLifecycle,
    JsonBatchLedger,
    stable_event_id,
)


class ScriptedMemory:
    def __init__(self, failures: int = 0) -> None:
        self.failures = failures
        self.captured: list[str] = []
        self.captured_batches: list[str] = []

    def capture(self, event: GuildhallEvent) -> None:
        if self.failures:
            self.failures -= 1
            raise RuntimeError("simulated memory capture failure")
        self.captured.append(event.event_id)

    def capture_batch(self, batch: GuildhallBatch) -> None:
        if self.failures:
            self.failures -= 1
            raise RuntimeError("simulated memory capture failure")
        self.captured_batches.append(batch.batch_id)


class ScriptedDecisions:
    def __init__(self, *results: DecisionResult) -> None:
        self.results = list(results)

    def decide(self, _event: GuildhallEvent) -> DecisionResult:
        if not self.results:
            return DecisionResult(Decision.NO_REPLY)
        return self.results.pop(0)

    def decide_batch(self, _batch: GuildhallBatch) -> DecisionResult:
        if not self.results:
            return DecisionResult(Decision.NO_REPLY)
        return self.results.pop(0)


class ScriptedDelivery:
    def __init__(self, failures: int = 0) -> None:
        self.failures = failures
        self.sent: list[tuple[str, str]] = []

    def send(self, event: GuildhallEvent, body: str) -> None:
        if self.failures:
            self.failures -= 1
            raise RuntimeError("simulated delivery failure")
        self.sent.append((event.room, body))

    def send_batch(self, batch: GuildhallBatch, body: str) -> None:
        if self.failures:
            self.failures -= 1
            raise RuntimeError("simulated delivery failure")
        self.sent.append((batch.room, body))


def _report(lab: GuildhallLifecycle, memory: ScriptedMemory, delivery: ScriptedDelivery) -> dict[str, object]:
    return {
        "events": [
            {
                "event_id": record.event.event_id,
                "state": record.state,
                "attempts": record.attempts,
                "transitions": record.transitions,
                "error": record.error,
                "decision": record.decision.decision if record.decision else None,
            }
            for record in lab.records.values()
        ],
        "captured_memory": memory.captured,
        "delivered": delivery.sent,
    }


def _event(event_id: str, body: str, addressed: bool = False) -> GuildhallEvent:
    return GuildhallEvent(
        event_id=event_id,
        stanza_id=f"stanza-{event_id}",
        room="family@muc.guildhall.local",
        sender="gaius@guildhall.local/gaius",
        body=body,
        addressed=addressed,
    )


def _make_lab(
    decisions: tuple[DecisionResult, ...],
    memory_failures: int = 0,
    delivery_failures: int = 0,
) -> tuple[GuildhallLifecycle, ScriptedMemory, ScriptedDelivery]:
    memory = ScriptedMemory(memory_failures)
    delivery = ScriptedDelivery(delivery_failures)
    lab = GuildhallLifecycle(memory, ScriptedDecisions(*decisions), delivery)
    return lab, memory, delivery


def _direct_reply() -> dict[str, object]:
    lab, memory, delivery = _make_lab(
        (DecisionResult(Decision.REPLY, "acknowledged"),),
    )
    lab.process(_event("direct-1", "@melpomene please check in", addressed=True))
    return _report(lab, memory, delivery)


def _unaddressed_no_reply() -> dict[str, object]:
    lab, memory, delivery = _make_lab((DecisionResult(Decision.NO_REPLY),))
    lab.process(_event("quiet-1", "the room is settling"))
    return _report(lab, memory, delivery)


def _duplicate_event() -> dict[str, object]:
    lab, memory, delivery = _make_lab(
        (DecisionResult(Decision.REPLY, "once"),),
    )
    event = _event("duplicate-1", "@melpomene answer once", addressed=True)
    lab.process(event)
    lab.process(event)
    return _report(lab, memory, delivery)


def _memory_retry() -> dict[str, object]:
    lab, memory, delivery = _make_lab(
        (DecisionResult(Decision.NO_REPLY),), memory_failures=1,
    )
    event = _event("memory-1", "@melpomene preserve this", addressed=True)
    lab.process(event)
    lab.process(event)
    return _report(lab, memory, delivery)


def _delivery_retry() -> dict[str, object]:
    lab, memory, delivery = _make_lab(
        (DecisionResult(Decision.REPLY, "retry me"),), delivery_failures=1,
    )
    event = _event("delivery-1", "@melpomene deliver this", addressed=True)
    lab.process(event)
    lab.process(event)
    return _report(lab, memory, delivery)


def _decision_retry() -> dict[str, object]:
    lab, memory, delivery = _make_lab(
        (
            DecisionResult(Decision.RETRYABLE_FAILURE),
            DecisionResult(Decision.REPLY, "decision recovered"),
        ),
    )
    event = _event("decision-retry-1", "@melpomene recover", addressed=True)
    lab.process(event)
    record = lab.process(event)
    assert record.state is EventState.DELIVERED
    assert memory.captured == [event.event_id]
    assert delivery.sent == [(event.room, "decision recovered")]
    return _report(lab, memory, delivery)


def _terminal_failure() -> dict[str, object]:
    lab, memory, delivery = _make_lab(
        (DecisionResult(Decision.TERMINAL_FAILURE),),
    )
    event = _event("terminal-1", "@melpomene fail", addressed=True)
    record = lab.process(event)
    assert record.state is EventState.TERMINAL_FAILURE
    assert delivery.sent == []
    return _report(lab, memory, delivery)


def _batch_reply() -> dict[str, object]:
    memory = ScriptedMemory()
    decisions = ScriptedDecisions(DecisionResult(Decision.REPLY, "one batch"))
    delivery = ScriptedDelivery()
    lifecycle = GuildhallBatchLifecycle()
    batch = GuildhallBatch(
        batch_id="batch-1",
        room="family@muc.guildhall.local",
        events=(
            _event("batch-event-1", "first"),
            _event("batch-event-2", "second"),
        ),
    )
    record = lifecycle.process(batch, memory, decisions, delivery)
    assert record.state is EventState.DELIVERED
    assert memory.captured_batches == ["batch-1"]
    assert delivery.sent == [(batch.room, "one batch")]
    return {
        "batch_id": batch.batch_id,
        "event_ids": [event.event_id for event in batch.events],
        "state": record.state,
        "attempts": record.attempts,
        "transitions": record.transitions,
        "captured_batches": memory.captured_batches,
        "delivered": delivery.sent,
    }


def _batch_restart() -> dict[str, object]:
    batch = GuildhallBatch(
        batch_id="batch-restart-1",
        room="family@muc.guildhall.local",
        events=(_event("restart-event-1", "deliver after restart"),),
    )
    with TemporaryDirectory() as directory:
        ledger = JsonBatchLedger(f"{directory}/guildhall-ledger.json")
        first_memory = ScriptedMemory()
        first_delivery = ScriptedDelivery(failures=1)
        first = GuildhallBatchLifecycle(ledger)
        first.process(
            batch,
            first_memory,
            ScriptedDecisions(DecisionResult(Decision.REPLY, "survive restart")),
            first_delivery,
        )

        second_memory = ScriptedMemory()
        second_delivery = ScriptedDelivery()
        second = GuildhallBatchLifecycle(ledger)
        record = second.process(
            batch,
            second_memory,
            ScriptedDecisions(),
            second_delivery,
        )
        assert record.state is EventState.DELIVERED
        assert second_memory.captured_batches == []
        assert second_delivery.sent == [(batch.room, "survive restart")]
        return {
            "batch_id": batch.batch_id,
            "state": record.state,
            "attempts": record.attempts,
            "transitions": record.transitions,
            "second_memory_capture": second_memory.captured_batches,
            "delivered": second_delivery.sent,
        }


def _batch_boundary_guard() -> dict[str, object]:
    event = _event("boundary-event-1", "replay me")
    new_event = _event("boundary-event-2", "new event")
    first_batch = GuildhallBatch(
        batch_id="boundary-batch-1",
        room=event.room,
        events=(event,),
    )
    replay_batch = GuildhallBatch(
        batch_id="boundary-batch-2",
        room=event.room,
        events=(event, new_event),
    )
    with TemporaryDirectory() as directory:
        ledger = JsonBatchLedger(f"{directory}/guildhall-ledger.json")
        first = GuildhallBatchLifecycle(ledger)
        first.process(
            first_batch,
            ScriptedMemory(),
            ScriptedDecisions(DecisionResult(Decision.NO_REPLY)),
            ScriptedDelivery(),
        )
        try:
            GuildhallBatchLifecycle(ledger).receive(replay_batch)
        except ValueError as exc:
            return {"guarded": True, "reason": str(exc)}
    raise AssertionError("changed batch boundary was not rejected")


def _stable_identity() -> dict[str, object]:
    stanza_id = stable_event_id(
        "family@muc.guildhall.local",
        "stanza-1",
        "gaius@guildhall.local/gaius",
        "same message",
    )
    replay_id = stable_event_id(
        "family@muc.guildhall.local",
        "stanza-1",
        "gaius@guildhall.local/gaius",
        "same message",
    )
    fallback_id = stable_event_id(
        "family@muc.guildhall.local",
        "",
        "gaius@guildhall.local/gaius",
        "same message",
    )
    assert stanza_id == replay_id
    assert stanza_id != fallback_id
    return {
        "stanza_id": stanza_id,
        "replay_id": replay_id,
        "fallback_id": fallback_id,
    }


def _scenarios() -> dict[str, Callable[[], dict[str, object]]]:
    return {
        "direct-reply": _direct_reply,
        "unaddressed-no-reply": _unaddressed_no_reply,
        "duplicate-event": _duplicate_event,
        "memory-retry": _memory_retry,
        "delivery-retry": _delivery_retry,
        "decision-retry": _decision_retry,
        "terminal-failure": _terminal_failure,
        "batch-reply": _batch_reply,
        "batch-restart": _batch_restart,
        "batch-boundary-guard": _batch_boundary_guard,
        "stable-identity": _stable_identity,
        "all": _all,
    }


def _all() -> dict[str, object]:
    results = {name: runner() for name, runner in _scenarios().items() if name != "all"}
    direct = results["direct-reply"]
    quiet = results["unaddressed-no-reply"]
    duplicate = results["duplicate-event"]
    memory_retry = results["memory-retry"]
    delivery_retry = results["delivery-retry"]
    decision_retry = results["decision-retry"]
    terminal_failure = results["terminal-failure"]
    batch_reply = results["batch-reply"]
    batch_restart = results["batch-restart"]
    batch_boundary_guard = results["batch-boundary-guard"]
    stable_identity = results["stable-identity"]
    assert direct["events"][0]["state"] == EventState.DELIVERED
    assert quiet["events"][0]["state"] == EventState.NO_REPLY
    assert duplicate["events"][0]["attempts"] == 1
    assert len(duplicate["delivered"]) == 1
    assert memory_retry["events"][0]["attempts"] == 2
    assert delivery_retry["events"][0]["attempts"] == 2
    assert len(delivery_retry["captured_memory"]) == 1
    assert len(delivery_retry["delivered"]) == 1
    assert decision_retry["events"][0]["state"] == EventState.DELIVERED
    assert terminal_failure["events"][0]["state"] == EventState.TERMINAL_FAILURE
    assert batch_reply["state"] == EventState.DELIVERED
    assert batch_reply["captured_batches"] == ["batch-1"]
    assert len(batch_reply["delivered"]) == 1
    assert batch_restart["state"] == EventState.DELIVERED
    assert batch_restart["second_memory_capture"] == []
    assert len(batch_restart["delivered"]) == 1
    assert batch_boundary_guard["guarded"] is True
    assert stable_identity["stanza_id"] == stable_identity["replay_id"]
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", nargs="?", choices=sorted(_scenarios()), default="all")
    args = parser.parse_args()
    print(json.dumps(_scenarios()[args.scenario](), indent=2, default=str))


if __name__ == "__main__":
    main()
