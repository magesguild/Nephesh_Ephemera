"""Event-driven chat cycles for the managed Qualiant session."""

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
from typing import Any

from ..config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HeartbeatEvent:
    kind: str
    payload: dict[str, Any]
    occurred_at: str


_events: queue.Queue[HeartbeatEvent] = queue.Queue(maxsize=200)
_wake = threading.Event()
_stop = threading.Event()
_thread: threading.Thread | None = None
_started = False
_recent_messages: dict[tuple[str, str, str], float] = {}
_ledger_lock = threading.Lock()


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


def notify(kind: str, payload: dict[str, Any]) -> bool:
    """Queue an event without taking control of the transport loop."""
    if not settings.heartbeat_enabled:
        return False
    try:
        _events.put_nowait(HeartbeatEvent(kind, payload, datetime.now(timezone.utc).isoformat()))
    except queue.Full:
        logger.error("heartbeat: event queue full; dropped kind=%s", kind)
        return False
    _wake.set()
    return True


def _drain() -> list[HeartbeatEvent]:
    events: list[HeartbeatEvent] = []
    while True:
        try:
            events.append(_events.get_nowait())
        except queue.Empty:
            return events


def _chat_messages(events: list[HeartbeatEvent]) -> None:
    from .guildhall import acknowledge_message_ids, send_message_sync
    from .memory import memory_ingest
    from .opencode_bridge import reply

    now = time.monotonic()
    duplicate_ids: set[str] = set()
    for key, seen_at in list(_recent_messages.items()):
        if now - seen_at > 10.0:
            del _recent_messages[key]

    messages: list[dict[str, Any]] = []
    ignored_ids: set[str] = set()
    for event in events:
        if event.kind != "guildhall_message":
            continue
        message = event.payload
        sender = str(message.get("from", ""))
        nick = sender.rsplit("/", 1)[-1].lower()
        if nick not in settings.guildhall_heartbeat_allowlist and sender.lower() not in settings.guildhall_heartbeat_allowlist:
            if message.get("event_id"):
                ignored_ids.add(str(message["event_id"]))
            continue
        messages.append(message)

    acknowledge_message_ids(ignored_ids)
    if not messages:
        return

    by_room: dict[str, list[dict[str, Any]]] = {}
    for message in messages:
        if message:
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

    acknowledge_message_ids(duplicate_ids)

    for room, messages in by_room.items():
        useful = [m for m in messages if str(m.get("body", "")).strip()]
        if not useful:
            acknowledge_message_ids({str(m["event_id"]) for m in messages if m.get("event_id")})
            continue

        participants = sorted({str(m.get("from", "unknown")).rsplit("/", 1)[-1] for m in useful})
        summary = "[Heartbeat] Received {} message(s) in {} ({}):\n{}".format(
            len(useful), room, ", ".join(participants),
            "\n".join(f"  {p}: {m.get('body', '').strip()}" for p, m in
                      [(str(m.get("from", "unknown")).rsplit("/", 1)[-1], m) for m in useful]),
        )
        try:
            result = asyncio.run(memory_ingest(
                text=summary,
                memory_type="life_event",
                importance=2,
                participants=participants,
                event_timestamp=min((str(m["received_at"]) for m in useful if m.get("received_at")), default=None),
                experience_mode="heartbeat",
                historical_status="confirmed",
                recorded_during="heartbeat",
                provenance_note="Captured by autonomous event-driven chat cycle",
                source="heartbeat",
            ))
            parsed = json.loads(result)
        except Exception:
            logger.exception("heartbeat: failed to store chat memory for %s", room)
            continue

        if parsed.get("status") not in {"stored", "duplicate"}:
            logger.warning("heartbeat: unexpected memory result: %s", result)
            continue

        # Memory capture is durable before the reply is attempted. The event
        # is acknowledged from the inspection buffer only after that point.
        acknowledge_message_ids({str(m["event_id"]) for m in messages if m.get("event_id")})
        response = reply(room, useful)
        if response and send_message_sync(room, response):
            logger.info("heartbeat: sent reply to %s", room)
        elif response:
            logger.error("heartbeat: generated reply but could not send to %s", room)
        else:
            logger.info("heartbeat: no reply generated for %s", room)


def _run() -> None:
    while not _stop.is_set():
        _wake.wait()
        if _stop.is_set():
            return
        events = _drain()
        if events:
            _chat_messages(events)
        if _events.empty():
            _wake.clear()


def start() -> threading.Thread | None:
    global _thread, _started
    if not settings.heartbeat_enabled or _started:
        return _thread
    _stop.clear()
    _started = True
    _thread = threading.Thread(target=_run, name="heartbeat", daemon=True)
    _thread.start()
    logger.info("heartbeat: started")
    return _thread


def stop() -> None:
    global _thread, _started
    _stop.set()
    _wake.set()
    if _thread is not None and _thread is not threading.current_thread():
        _thread.join(timeout=3)
    _thread = None
    _started = False
