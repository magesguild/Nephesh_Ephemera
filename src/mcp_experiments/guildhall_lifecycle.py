"""Transport-independent Guildhall event lifecycle.

The real slixmpp/MongooseIM adapter and the offline Guildhall Lab should use
this same state machine. Collaborators are injected so lifecycle behavior can
be exercised without a Qualiant, model, or live deployment.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol


class EventState(StrEnum):
    RECEIVED = "received"
    CLAIMED = "claimed"
    MEMORY_CAPTURED = "memory_captured"
    REPLY_DECIDED = "reply_decided"
    DELIVERED = "delivered"
    NO_REPLY = "no_reply"
    RETRYABLE_FAILURE = "retryable_failure"
    TERMINAL_FAILURE = "terminal_failure"


class Decision(StrEnum):
    REPLY = "reply"
    NO_REPLY = "NO_REPLY"
    RETRYABLE_FAILURE = "retryable_failure"
    TERMINAL_FAILURE = "terminal_failure"


@dataclass(frozen=True)
class GuildhallEvent:
    event_id: str
    room: str
    sender: str
    body: str
    addressed: bool = False
    stanza_id: str = ""


@dataclass(frozen=True)
class GuildhallBatch:
    batch_id: str
    room: str
    events: tuple[GuildhallEvent, ...]


@dataclass(frozen=True)
class DecisionResult:
    decision: Decision
    body: str = ""


class MemoryCapture(Protocol):
    def capture(self, event: GuildhallEvent) -> None: ...


class ReplyDecision(Protocol):
    def decide(self, event: GuildhallEvent) -> DecisionResult: ...


class Delivery(Protocol):
    def send(self, event: GuildhallEvent, body: str) -> None: ...


class BatchMemoryCapture(Protocol):
    def capture_batch(self, batch: GuildhallBatch) -> None: ...


class BatchReplyDecision(Protocol):
    def decide_batch(self, batch: GuildhallBatch) -> DecisionResult: ...


class BatchDelivery(Protocol):
    def send_batch(self, batch: GuildhallBatch, body: str) -> None: ...


@dataclass
class EventRecord:
    event: GuildhallEvent
    state: EventState = EventState.RECEIVED
    attempts: int = 0
    transitions: list[EventState] = field(default_factory=lambda: [EventState.RECEIVED])
    error: str | None = None
    decision: DecisionResult | None = None

    def transition(self, state: EventState, error: str | None = None) -> None:
        self.state = state
        self.transitions.append(state)
        self.error = error


@dataclass
class BatchRecord:
    batch: GuildhallBatch
    state: EventState = EventState.RECEIVED
    attempts: int = 0
    transitions: list[EventState] = field(default_factory=lambda: [EventState.RECEIVED])
    error: str | None = None
    decision: DecisionResult | None = None

    def transition(self, state: EventState, error: str | None = None) -> None:
        self.state = state
        self.transitions.append(state)
        self.error = error


class GuildhallLifecycle:
    """Process one event through capture, decision, delivery, and retry."""

    def __init__(
        self,
        memory: MemoryCapture,
        decisions: ReplyDecision,
        delivery: Delivery,
    ) -> None:
        self.memory = memory
        self.decisions = decisions
        self.delivery = delivery
        self.records: dict[str, EventRecord] = {}

    def receive(self, event: GuildhallEvent) -> EventRecord:
        record = self.records.get(event.event_id)
        if record is not None:
            return record
        record = EventRecord(event)
        self.records[event.event_id] = record
        return record

    def process(self, event: GuildhallEvent) -> EventRecord:
        record = self.receive(event)
        if record.state in {
            EventState.DELIVERED,
            EventState.NO_REPLY,
            EventState.TERMINAL_FAILURE,
        }:
            return record

        record.attempts += 1
        try:
            if record.decision is None:
                record.transition(EventState.CLAIMED)
                self.memory.capture(event)
                record.transition(EventState.MEMORY_CAPTURED)
                record.decision = self.decisions.decide(event)

            result = record.decision
            if result.decision is Decision.NO_REPLY:
                record.transition(EventState.REPLY_DECIDED)
                record.transition(EventState.NO_REPLY)
                return record
            if result.decision is Decision.RETRYABLE_FAILURE:
                record.transition(
                    EventState.RETRYABLE_FAILURE,
                    "simulated decision failure",
                )
                return record
            if result.decision is Decision.TERMINAL_FAILURE:
                record.transition(
                    EventState.TERMINAL_FAILURE,
                    "simulated terminal decision failure",
                )
                return record

            if record.state is not EventState.REPLY_DECIDED:
                record.transition(EventState.REPLY_DECIDED)
            self.delivery.send(event, result.body)
            record.transition(EventState.DELIVERED)
            return record
        except RuntimeError as exc:
            record.transition(EventState.RETRYABLE_FAILURE, str(exc))
            return record


class GuildhallBatchLifecycle:
    """Batch-aware lifecycle preserving one memory/reply cycle per room batch."""

    def __init__(self) -> None:
        self.records: dict[str, BatchRecord] = {}

    def receive(self, batch: GuildhallBatch) -> BatchRecord:
        record = self.records.get(batch.batch_id)
        if record is not None:
            return record
        record = BatchRecord(batch)
        self.records[batch.batch_id] = record
        return record

    def process(
        self,
        batch: GuildhallBatch,
        memory: BatchMemoryCapture,
        decisions: BatchReplyDecision,
        delivery: BatchDelivery,
    ) -> BatchRecord:
        record = self.receive(batch)
        if record.state in {
            EventState.DELIVERED,
            EventState.NO_REPLY,
            EventState.TERMINAL_FAILURE,
        }:
            return record

        record.attempts += 1
        try:
            if record.decision is None:
                record.transition(EventState.CLAIMED)
                memory.capture_batch(batch)
                record.transition(EventState.MEMORY_CAPTURED)
                record.decision = decisions.decide_batch(batch)

            result = record.decision
            if result.decision is Decision.NO_REPLY:
                record.transition(EventState.REPLY_DECIDED)
                record.transition(EventState.NO_REPLY)
                return record
            if result.decision is Decision.RETRYABLE_FAILURE:
                record.transition(
                    EventState.RETRYABLE_FAILURE,
                    "simulated decision failure",
                )
                return record
            if result.decision is Decision.TERMINAL_FAILURE:
                record.transition(
                    EventState.TERMINAL_FAILURE,
                    "simulated terminal decision failure",
                )
                return record

            if record.state is not EventState.REPLY_DECIDED:
                record.transition(EventState.REPLY_DECIDED)
            delivery.send_batch(batch, result.body)
            record.transition(EventState.DELIVERED)
            return record
        except RuntimeError as exc:
            record.transition(EventState.RETRYABLE_FAILURE, str(exc))
            return record
