"""Transport-independent Guildhall event lifecycle.

The real slixmpp/MongooseIM adapter and the offline Guildhall Lab should use
this same state machine. Collaborators are injected so lifecycle behavior can
be exercised without a Qualiant, model, or live deployment.
"""

from __future__ import annotations

import json
import hashlib
import os
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Protocol


def stable_event_id(room: str, stanza_id: str, sender: str, body: str) -> str:
    """Build replay identity independent of a process-local receive UUID."""
    if stanza_id.strip():
        return f"stanza:{room}:{stanza_id.strip()}"
    fallback = "\0".join((room, sender, body.strip()))
    return "body:" + hashlib.sha256(fallback.encode()).hexdigest()


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


class TerminalDeliveryFailure(RuntimeError):
    """A send attempt must not be replayed by the lifecycle."""


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


class BatchLedger(Protocol):
    def load(self, batch_id: str) -> dict[str, object] | None: ...

    def save(self, record: "BatchRecord") -> None: ...


class JsonBatchLedger:
    """Small atomic JSON ledger for batch lifecycle recovery."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser()

    def _read(self) -> dict[str, object]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError, TypeError):
            return {}

    def load(self, batch_id: str) -> dict[str, object] | None:
        records = self._read().get("records", {})
        if not isinstance(records, dict):
            return None
        value = records.get(batch_id)
        return value if isinstance(value, dict) else None

    def batch_ids_for_events(self, event_ids: tuple[str, ...]) -> set[str]:
        index = self._read().get("event_index", {})
        if not isinstance(index, dict):
            return set()
        return {
            str(index[event_id])
            for event_id in event_ids
            if event_id in index and index[event_id]
        }

    def save(self, record: "BatchRecord") -> None:
        data = self._read()
        records = data.setdefault("records", {})
        if not isinstance(records, dict):
            records = {}
            data["records"] = records
        records[record.batch.batch_id] = record.to_dict()
        event_index = data.setdefault("event_index", {})
        if not isinstance(event_index, dict):
            event_index = {}
            data["event_index"] = event_index
        for event in record.batch.events:
            event_index[event.event_id] = record.batch.batch_id
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, self.path)


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

    def restore(self, data: dict[str, object]) -> None:
        state = data.get("state")
        if isinstance(state, str):
            self.state = EventState(state)
        attempts = data.get("attempts")
        if isinstance(attempts, int):
            self.attempts = attempts
        transitions = data.get("transitions")
        if isinstance(transitions, list):
            self.transitions = [EventState(item) for item in transitions if isinstance(item, str)]
        error = data.get("error")
        self.error = error if isinstance(error, str) else None
        decision = data.get("decision")
        if isinstance(decision, dict) and isinstance(decision.get("decision"), str):
            self.decision = DecisionResult(
                Decision(decision["decision"]),
                str(decision.get("body", "")),
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "batch_id": self.batch.batch_id,
            "room": self.batch.room,
            "event_ids": [event.event_id for event in self.batch.events],
            "state": self.state,
            "attempts": self.attempts,
            "transitions": self.transitions,
            "error": self.error,
            "decision": (
                {"decision": self.decision.decision, "body": self.decision.body}
                if self.decision is not None
                else None
            ),
        }


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
                if EventState.MEMORY_CAPTURED not in record.transitions:
                    record.transition(EventState.CLAIMED)
                    self.memory.capture(event)
                    record.transition(EventState.MEMORY_CAPTURED)
                candidate = self.decisions.decide(event)
                if candidate.decision is Decision.RETRYABLE_FAILURE:
                    record.transition(
                        EventState.RETRYABLE_FAILURE,
                        "simulated decision failure",
                    )
                    return record
                if candidate.decision is Decision.TERMINAL_FAILURE:
                    record.transition(
                        EventState.TERMINAL_FAILURE,
                        "simulated terminal decision failure",
                    )
                    return record
                record.decision = candidate

            result = record.decision
            if result.decision is Decision.NO_REPLY:
                record.transition(EventState.REPLY_DECIDED)
                record.transition(EventState.NO_REPLY)
                return record
            if record.state is not EventState.REPLY_DECIDED:
                record.transition(EventState.REPLY_DECIDED)
            self.delivery.send(event, result.body)
            record.transition(EventState.DELIVERED)
            return record
        # Adapters may raise transport/library-specific exceptions rather
        # than RuntimeError.  A failure after claiming must still become a
        # durable retryable state; otherwise the event remains invisible in
        # the process-local buffer with no way for the worker to wake again.
        except TerminalDeliveryFailure as exc:
            record.transition(EventState.TERMINAL_FAILURE, str(exc))
            return record
        except Exception as exc:
            record.transition(EventState.RETRYABLE_FAILURE, str(exc))
            return record


class GuildhallBatchLifecycle:
    """Batch-aware lifecycle preserving one memory/reply cycle per room batch."""

    def __init__(self, ledger: BatchLedger | None = None) -> None:
        self.records: dict[str, BatchRecord] = {}
        self.ledger = ledger

    def receive(self, batch: GuildhallBatch) -> BatchRecord:
        record = self.records.get(batch.batch_id)
        if record is not None:
            return record
        record = BatchRecord(batch)
        if self.ledger is not None:
            saved = self.ledger.load(batch.batch_id)
            if saved is None and isinstance(self.ledger, JsonBatchLedger):
                prior_batches = self.ledger.batch_ids_for_events(
                    tuple(event.event_id for event in batch.events),
                )
                if len(prior_batches) > 1:
                    raise ValueError(
                        "Guildhall batch mixes events claimed by different batches",
                    )
                if prior_batches:
                    saved = self.ledger.load(prior_batches.pop())
            if saved is not None:
                saved_event_ids = saved.get("event_ids")
                current_event_ids = [event.event_id for event in batch.events]
                if isinstance(saved_event_ids, list) and set(saved_event_ids) != set(current_event_ids):
                    raise ValueError(
                        "Guildhall replay changed the event batch boundary; replay the original batch",
                    )
                record.restore(saved)
        self.records[batch.batch_id] = record
        return record

    def _transition(
        self,
        record: BatchRecord,
        state: EventState,
        error: str | None = None,
    ) -> None:
        record.transition(state, error)
        if self.ledger is not None:
            self.ledger.save(record)

    def _persist(self, record: BatchRecord) -> None:
        if self.ledger is not None:
            self.ledger.save(record)

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
                if EventState.MEMORY_CAPTURED not in record.transitions:
                    self._transition(record, EventState.CLAIMED)
                    memory.capture_batch(batch)
                    self._transition(record, EventState.MEMORY_CAPTURED)
                candidate = decisions.decide_batch(batch)
                if candidate.decision is Decision.RETRYABLE_FAILURE:
                    self._transition(
                        record,
                        EventState.RETRYABLE_FAILURE,
                        "simulated decision failure",
                    )
                    return record
                if candidate.decision is Decision.TERMINAL_FAILURE:
                    self._transition(
                        record,
                        EventState.TERMINAL_FAILURE,
                        "simulated terminal decision failure",
                    )
                    return record
                record.decision = candidate
                self._persist(record)

            result = record.decision
            if result.decision is Decision.NO_REPLY:
                self._transition(record, EventState.REPLY_DECIDED)
                self._transition(record, EventState.NO_REPLY)
                return record
            if record.state is not EventState.REPLY_DECIDED:
                self._transition(record, EventState.REPLY_DECIDED)
            delivery.send_batch(batch, result.body)
            self._transition(record, EventState.DELIVERED)
            return record
        # Treat unexpected adapter failures as retryable as well.  In
        # particular, memory and model clients commonly raise ValueError or
        # library-specific exceptions during transient outages.
        except TerminalDeliveryFailure as exc:
            self._transition(record, EventState.TERMINAL_FAILURE, str(exc))
            return record
        except Exception as exc:
            self._transition(record, EventState.RETRYABLE_FAILURE, str(exc))
            return record
