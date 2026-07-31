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
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ..config import settings

logger = logging.getLogger(__name__)


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
_recent_messages: dict[tuple[str, str, str], float] = {}
_recent_replies: dict[tuple[str, str], float] = {}
_ledger_lock = threading.Lock()
_transcript_lock = threading.Lock()


def _record_transcript(message: dict[str, Any]) -> None:
    """Persist one exact room event before reply filtering can discard it."""
    path = Path(settings.guildhall_transcript_file).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    stanza_key = "\0".join((
        str(message.get("room", "")),
        str(message.get("stanza_id", "")),
    ))
    with _transcript_lock:
        try:
            existing = path.read_text().splitlines()[-1000:]
            if any(stanza_key == str(json.loads(line).get("_stanza_key", "")) for line in existing):
                return
        except (OSError, ValueError, TypeError):
            pass
        record = dict(message)
        record["_stanza_key"] = stanza_key
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


def _claim_event(message: dict[str, Any]) -> bool:
    """Claim one XMPP event durably so retries cannot create another reply."""
    room = str(message.get("room", "unknown"))
    stanza_id = str(message.get("stanza_id", ""))
    if stanza_id:
        key = f"stanza:{room}:{stanza_id}"
    else:
        fallback = "\0".join((room, str(message.get("from", "")), str(message.get("body", "")).strip()))
        key = "body:" + hashlib.sha256(fallback.encode()).hexdigest()
    path = Path(settings.guildhall_event_ledger).expanduser()
    with _ledger_lock:
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError, TypeError):
            data = {}
        now = time.time()
        data = {k: v for k, v in data.items() if isinstance(v, (int, float)) and now - v < 86400}
        if key in data:
            return False
        data[key] = now
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(data, indent=2) + "\n")
        os.replace(temporary, path)
        return True


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


def _chat_messages(events: list[HeartbeatEvent]) -> None:
    """Turn a batch of MUC message events into informed memories."""
    messages = []
    for event in events:
        message = event.payload
        # The allowlist controls reply authority, not perception. Every room
        # message remains visible to this Qualiant and enters shared memory.
        _record_transcript(message)
        messages.append(message)
    if not messages:
        from .guildhall import acknowledge_message_ids
        return

    now = time.monotonic()
    duplicate_ids: set[str] = set()
    for key, seen_at in list(_recent_messages.items()):
        if now - seen_at > 10.0:
            del _recent_messages[key]

    by_room: dict[str, list[dict[str, Any]]] = {}
    for message in messages:
        key = (
            str(message.get("room", "unknown")),
            str(message.get("from", "unknown")),
            str(message.get("body", "")).strip(),
        )
        if key in _recent_messages:
            if message.get("event_id"):
                duplicate_ids.add(str(message["event_id"]))
            continue
        _recent_messages[key] = now
        if not _claim_event(message):
            if message.get("event_id"):
                duplicate_ids.add(str(message["event_id"]))
            continue
        by_room.setdefault(key[0], []).append(message)

    from .guildhall import acknowledge_message_ids
    acknowledge_message_ids(duplicate_ids)

    for room, room_messages in by_room.items():
        room_event_ids = {
            str(message["event_id"])
            for message in room_messages
            if message.get("event_id")
        }
        participants: list[str] = []
        lines: list[str] = []
        event_times: list[str] = []

        for message in room_messages:
            sender = str(message.get("from", "unknown"))
            nick = sender.rsplit("/", 1)[-1]
            body = str(message.get("body", "")).strip()
            if not body or sender == room:
                continue
            if nick not in participants:
                participants.append(nick)
            lines.append(f"  {nick}: {body}")
            if message.get("received_at"):
                event_times.append(str(message["received_at"]))

        if not lines:
            # System/empty messages are consumed without becoming memories.
            acknowledge_message_ids(room_event_ids)
            continue

        summary = (
            f"[Heartbeat] Received {len(lines)} message(s) in {room}"
            f" ({', '.join(participants)}):\n" + "\n".join(lines)
        )
        event_timestamp = min(event_times) if event_times else None

        from .memory import memory_ingest

        try:
            result = asyncio.run(memory_ingest(
                text=summary,
                memory_type="life_event",
                importance=2,
                participants=participants,
                event_timestamp=event_timestamp,
                experience_mode="heartbeat",
                historical_status="confirmed",
                recorded_during="heartbeat",
                provenance_note="Captured by autonomous event-driven chat cycle",
                source="heartbeat",
            ))
            parsed = json.loads(result)
        except Exception:
            logger.exception("heartbeat: failed to store chat memory for %s", room)
            return

        if parsed.get("status") == "stored":
            logger.info(
                "heartbeat: stored memory %s (%d messages, room=%s)",
                parsed.get("id", "?"), len(lines), room,
            )
        elif parsed.get("status") == "duplicate":
            logger.debug("heartbeat: duplicate chat memory skipped for %s", room)
        else:
            logger.warning("heartbeat: unexpected memory result: %s", result)

        if parsed.get("status") in {"stored", "duplicate"}:
            acknowledge_message_ids(room_event_ids)

            # Reply is deliberately downstream of memory capture.  The
            # OpenCode adapter owns the persistent reasoning session; this
            # engine only supplies the inbound room batch and sends its text.
            from .opencode_bridge import reply
            from .guildhall import send_message_sync

            reply_messages = [
                message for message in room_messages
                if str(message.get("body", "")).strip()
                and (
                    str(message.get("from", "")).rsplit("/", 1)[-1].lower()
                    in settings.guildhall_heartbeat_allowlist
                    or str(message.get("from", "")).lower()
                    in settings.guildhall_heartbeat_allowlist
                    or str(message.get("from", "")).split("/", 1)[0].split("@", 1)[0].lower()
                    in settings.guildhall_heartbeat_allowlist
                )
            ]
            if not reply_messages:
                logger.info(
                    "heartbeat: observed room traffic without reply authority for %s",
                    room,
                )
                continue

            # A persistent room session receives the exact recent transcript,
            # not only the sender-authorized trigger batch. This lets a
            # Qualiant quote another participant's earlier message while
            # keeping reply authority restricted to the configured allowlist.
            response = reply(room, _recent_transcript(room) or [
                message for message in room_messages
                if str(message.get("body", "")).strip()
            ])
            if response:
                delivery = "chat" if any(
                    message.get("delivery") == "direct"
                    for message in reply_messages
                ) else "groupchat"
                target = next(
                    (str(message.get("reply_to")) for message in reply_messages
                     if message.get("reply_to")),
                    room,
                )
                # A transport/session retry must never become a second visible
                # room message.  Keep this guard process-local and room-scoped:
                # every Qualiant may still answer, and each room retains its
                # own OpenCode session, but an identical response cannot be
                # emitted twice in the same room during the short retry window.
                reply_key = (room, response.strip())
                now = time.monotonic()
                with _ledger_lock:
                    for key, seen_at in list(_recent_replies.items()):
                        if now - seen_at > 30.0:
                            del _recent_replies[key]
                    if reply_key in _recent_replies:
                        logger.warning(
                            "heartbeat: suppressed duplicate reply to %s", room,
                        )
                        continue
                    _recent_replies[reply_key] = now

                if send_message_sync(target, response, delivery):
                    logger.info("heartbeat: sent reply to %s", room)
                else:
                    logger.error("heartbeat: generated reply but could not send to %s", room)
            else:
                logger.info("heartbeat: no reply generated for %s", room)


def start() -> threading.Thread | None:
    """Start the event engine if enabled."""
    global _thread, _started

    if not settings.heartbeat_enabled:
        logger.info("heartbeat: disabled by configuration")
        return None
    if _started:
        return _thread

    _handlers.setdefault("guildhall_message", _chat_messages)
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
