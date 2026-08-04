"""Event-driven autonomous cycles.

The heartbeat is a generic event engine, not a chat poller.  Sources emit
events, the engine wakes, coalesces the events already waiting, and dispatches
them to registered handlers.  Guildhall room messages are the first source.

Periodic heartbeats, dreaming, and maintenance can be added later as separate
event sources.  Chat itself has no timer: a room message is its wake-up.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import queue
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

from ..config import settings
from ..guildhall_lifecycle import (
    Decision,
    DecisionResult,
    EventState,
    GuildhallBatch,
    GuildhallBatchLifecycle,
    GuildhallEvent,
    JsonBatchLedger,
    stable_event_id,
)

logger = logging.getLogger(__name__)


def _batch_collaborators(capture_memory: Callable[..., Any], decide_reply: Callable[..., Any], deliver_reply: Callable[..., Any]) -> tuple[object, object, object]:
    """Adapt heartbeat callbacks to the batch lifecycle protocol."""
    return (
        SimpleNamespace(capture_batch=capture_memory),
        SimpleNamespace(decide_batch=decide_reply),
        SimpleNamespace(send_batch=deliver_reply),
    )


@dataclass(frozen=True)
class HeartbeatEvent:
    """A fact that may wake an autonomous cycle."""

    kind: str
    payload: dict[str, Any]
    occurred_at: str


_events: queue.Queue[HeartbeatEvent] = queue.Queue(maxsize=200)
_wake = threading.Event()
_stop = threading.Event()
_thread: threading.Thread | None = None
_started = False
_cycle_count = 0
_last_cycle: str | None = None

# Handlers are deliberately explicit and inspectable.  Future event sources
# can register here without making the engine itself know about them.
_handlers: dict[str, Callable[[list[HeartbeatEvent]], None]] = {}
_recent_messages: dict[tuple[str, str], float] = {}
_transcript_lock = threading.Lock()
_batch_lifecycle = GuildhallBatchLifecycle(JsonBatchLedger(settings.guildhall_event_ledger))


def _is_directly_addressed(message: dict[str, Any]) -> bool:
    """Recognize direct address without requiring a model judgment."""
    if message.get("delivery") == "direct":
        return True
    body = str(message.get("body", ""))
    nick = re.escape(settings.guildhall_nick)
    return bool(re.search(rf"(?:^|\s)@?{nick}(?:\b|[:,])", body, re.IGNORECASE))


def _stable_event_id(message: dict[str, Any]) -> str:
    """Derive replay identity independently of the process-local UUID."""
    return stable_event_id(
        str(message.get("room", "unknown")),
        str(message.get("stanza_id", "")),
        str(message.get("from", "")),
        str(message.get("body", "")),
    )


def _message_dedupe_key(message: dict[str, Any]) -> tuple[str, str]:
    """Use transport identity when available, not body text alone."""
    return (
        str(message.get("room", "unknown")),
        _stable_event_id(message),
    )


def _record_transcript(message: dict[str, Any]) -> None:
    """Persist one exact room event before reply filtering can discard it."""
    path = Path(settings.guildhall_transcript_file).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    event_key = _stable_event_id(message)
    stanza_id = str(message.get("stanza_id", ""))
    legacy_stanza_key = (
        "\0".join((str(message.get("room", "")), stanza_id))
        if stanza_id
        else ""
    )
    with _transcript_lock:
        try:
            existing = path.read_text().splitlines()[-1000:]
            if any(
                event_key == str(json.loads(line).get("_event_key", ""))
                or (
                    legacy_stanza_key
                    and legacy_stanza_key == str(json.loads(line).get("_stanza_key", ""))
                )
                for line in existing
            ):
                return
        except (OSError, ValueError, TypeError):
            pass
        record = dict(message)
        record["_event_key"] = event_key
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())


def _recent_transcript(room: str, limit: int = 80) -> list[dict[str, Any]]:
    path = Path(settings.guildhall_transcript_file).expanduser()
    records: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines()[-1000:]:
            record = json.loads(line)
            if record.get("room") == room:
                records.append(record)
    except (OSError, ValueError, TypeError):
        return []
    return records[-limit:]


def register_handler(kind: str, handler: Callable[[list[HeartbeatEvent]], None]) -> None:
    """Register one handler for an event kind.

    Registration is process-local and should happen during startup, not from
    arbitrary event handlers.  Replacing a handler is intentional and keeps
    the extension point small and inspectable.
    """
    _handlers[kind] = handler


def notify(kind: str, payload: dict[str, Any]) -> bool:
    """Publish an event and wake the engine.

    The queue is bounded.  If it is full, the event is dropped and the loss is
    logged rather than allowing an event storm to exhaust Nephesh.
    """
    if not settings.heartbeat_enabled:
        return False

    event = HeartbeatEvent(
        kind=kind,
        payload=payload,
        occurred_at=datetime.now(timezone.utc).isoformat(),
    )
    try:
        _events.put_nowait(event)
    except queue.Full:
        logger.error("heartbeat: event queue full; dropped kind=%s", kind)
        return False
    _wake.set()
    return True


def _run_loop() -> None:
    global _cycle_count, _last_cycle

    # The engine is synchronous at its boundary and creates a short-lived
    # asyncio loop only while writing a memory.  It never owns Guildhall's
    # XMPP loop and therefore cannot block the transport.
    while not _stop.is_set():
        _wake.wait()
        if _stop.is_set():
            break

        events = _drain_events()
        if not events:
            _wake.clear()
            continue

        _cycle_count += 1
        _last_cycle = datetime.now(timezone.utc).isoformat()
        _dispatch(events)

        if _events.empty():
            _wake.clear()


def _drain_events() -> list[HeartbeatEvent]:
    events: list[HeartbeatEvent] = []
    while True:
        try:
            events.append(_events.get_nowait())
        except queue.Empty:
            return events


def _dispatch(events: list[HeartbeatEvent]) -> None:
    by_kind: dict[str, list[HeartbeatEvent]] = {}
    for event in events:
        by_kind.setdefault(event.kind, []).append(event)

    for kind, grouped in by_kind.items():
        handler = _handlers.get(kind)
        if handler is None:
            logger.warning("heartbeat: no handler registered for kind=%s", kind)
            continue
        try:
            handler(grouped)
        except Exception:
            logger.exception("heartbeat: handler failed for kind=%s", kind)


def _chat_messages_v2(events: list[HeartbeatEvent]) -> None:
    """Process room batches through the shared transport-independent lifecycle."""
    from .guildhall import (
        GUILDHALL_PROVENANCE_STAMP,
        acknowledge_message_ids,
        send_message_sync,
    )
    from .memory import memory_ingest, memory_recall
    from .opencode_bridge import reply

    messages: list[dict[str, Any]] = []
    for event in events:
        message = event.payload
        _record_transcript(message)
        messages.append(message)
    if not messages:
        return

    now = time.monotonic()
    unique: list[dict[str, Any]] = []
    for key, seen_at in list(_recent_messages.items()):
        if now - seen_at > 10.0:
            del _recent_messages[key]
    duplicate_event_ids: set[str] = set()
    for message in messages:
        key = _message_dedupe_key(message)
        if key in _recent_messages:
            if message.get("event_id"):
                duplicate_event_ids.add(str(message["event_id"]))
            continue
        _recent_messages[key] = now
        unique.append(message)

    acknowledge_message_ids(duplicate_event_ids)

    by_room: dict[str, list[dict[str, Any]]] = {}
    for message in unique:
        room = str(message.get("room", "unknown"))
        if str(message.get("body", "")).strip():
            by_room.setdefault(room, []).append(message)

    for room, room_messages in by_room.items():
        event_ids = tuple(_stable_event_id(message) for message in room_messages)
        if not all(event_ids):
            logger.error("heartbeat: cannot process batch without event IDs in %s", room)
            continue
        batch_id = hashlib.sha256(
            "\0".join((room, *sorted(event_ids))).encode(),
        ).hexdigest()
        batch = GuildhallBatch(
            batch_id=batch_id,
            room=room,
            events=tuple(
                GuildhallEvent(
                    event_id=_stable_event_id(message),
                    stanza_id=str(message.get("stanza_id", "")),
                    room=room,
                    sender=str(message.get("from", "unknown")),
                    body=str(message.get("body", "")).strip(),
                    addressed=_is_directly_addressed(message),
                )
                for message in room_messages
            ),
        )
        reply_messages = [
            message for message in room_messages
            if (
                str(message.get("from", "")).rsplit("/", 1)[-1].lower()
                in settings.guildhall_heartbeat_allowlist
                or str(message.get("from", "")).lower()
                in settings.guildhall_heartbeat_allowlist
                or str(message.get("from", "")).split("/", 1)[0].split("@", 1)[0].lower()
                in settings.guildhall_heartbeat_allowlist
            )
        ]

        def capture_memory(_batch: GuildhallBatch) -> None:
            participants: list[str] = []
            lines: list[str] = []
            event_times: list[str] = []
            for message in room_messages:
                sender = str(message.get("from", "unknown"))
                nick = sender.rsplit("/", 1)[-1]
                body = str(message.get("body", "")).strip()
                if nick not in participants:
                    participants.append(nick)
                lines.append(f"  {nick}: {body}")
                if message.get("received_at"):
                    event_times.append(str(message["received_at"]))
            result = asyncio.run(memory_ingest(
                text=(
                    f"[Heartbeat] Received {len(lines)} message(s) in {room}"
                    f" ({', '.join(participants)}):\n" + "\n".join(lines)
                ),
                memory_type="life_event",
                importance=2,
                participants=participants,
                event_timestamp=min(event_times) if event_times else None,
                experience_mode="heartbeat",
                historical_status="confirmed",
                recorded_during="heartbeat",
                provenance_note=(
                    f"{GUILDHALL_PROVENANCE_STAMP}; "
                    "captured by autonomous event-driven chat cycle"
                ),
                source="heartbeat",
            ))
            parsed = json.loads(result)
            if parsed.get("status") not in {"stored", "duplicate"}:
                raise RuntimeError(f"memory capture failed: {result}")

        def decide_reply(_batch: GuildhallBatch) -> DecisionResult:
            if not reply_messages:
                return DecisionResult(Decision.NO_REPLY)
            directly_addressed = any(
                _is_directly_addressed(message) for message in reply_messages
            )
            query = "\n".join(str(message.get("body", "")) for message in room_messages)
            try:
                memory_impulse = asyncio.run(memory_recall(query=query, n_results=5))
                memory_impulse = memory_impulse[:12000]
            except Exception:
                logger.warning("heartbeat: memory retrieval impulse failed", exc_info=True)
                memory_impulse = None
            response = reply(
                room,
                _recent_transcript(room) or room_messages,
                directly_addressed=directly_addressed,
                memory_impulse=memory_impulse,
            )
            if response is None:
                return DecisionResult(Decision.RETRYABLE_FAILURE)
            if response.strip().upper() == "NO_REPLY":
                return DecisionResult(Decision.NO_REPLY)
            return DecisionResult(Decision.REPLY, response)

        def deliver_reply(_batch: GuildhallBatch, body: str) -> None:
            delivery = "chat" if any(
                message.get("delivery") == "direct" for message in reply_messages
            ) else "groupchat"
            target = next(
                (str(message.get("reply_to")) for message in reply_messages
                 if message.get("reply_to")),
                room,
            )
            if not send_message_sync(target, body, delivery):
                raise RuntimeError(f"delivery failed for {room}")

        record = _batch_lifecycle.process(batch, *_batch_collaborators(
            capture_memory,
            decide_reply,
            deliver_reply,
        ))
        if record.state in {
            EventState.DELIVERED,
            EventState.NO_REPLY,
            EventState.TERMINAL_FAILURE,
        }:
            acknowledge_message_ids({
                str(message["event_id"])
                for message in room_messages
                if message.get("event_id")
            })
        logger.info(
            "heartbeat: batch %s state=%s attempts=%d room=%s",
            batch_id,
            record.state,
            record.attempts,
            room,
        )


def start() -> threading.Thread | None:
    """Start the event engine if enabled."""
    global _thread, _started

    if not settings.heartbeat_enabled:
        logger.info("heartbeat: disabled by configuration")
        return None
    if _started:
        return _thread

    _handlers.setdefault("guildhall_message", _chat_messages_v2)
    _stop.clear()
    _started = True
    _thread = threading.Thread(target=_run_loop, name="heartbeat", daemon=True)
    _thread.start()
    logger.info(
        "heartbeat: started (event-driven, queue_limit=200, guildhall=%s)",
        "enabled" if settings.guildhall_enabled else "disabled",
    )
    return _thread


def stop() -> None:
    """Stop the event engine and wake it if it is waiting."""
    global _started, _thread

    _stop.set()
    _wake.set()
    if _thread is not None and _thread is not threading.current_thread():
        _thread.join(timeout=3)
    _started = False
    _thread = None
    logger.info("heartbeat: stopped")


def get_status() -> dict[str, Any]:
    """Return internal status; deliberately not exposed as an MCP tool."""
    return {
        "enabled": settings.heartbeat_enabled,
        "running": _thread is not None and _thread.is_alive(),
        "cycle_count": _cycle_count,
        "queued_events": _events.qsize(),
        "last_cycle": _last_cycle,
        "registered_event_kinds": sorted(_handlers),
    }
