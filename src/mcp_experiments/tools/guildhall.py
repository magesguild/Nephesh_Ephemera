"""Optional XMPP/MUC bridge to the local Guildhall server."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import ssl
import subprocess
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..compliance import ComplianceLevel
from ..config import settings

logger = logging.getLogger(__name__)

_client: Any = None
_loop: asyncio.AbstractEventLoop | None = None
_thread: threading.Thread | None = None
_stop = threading.Event()
_started = False
_connected = False
_joined_rooms: set[str] = set()
_joined_lock = threading.Lock()
_buffer: list[dict[str, str]] = []
_buffer_lock = threading.Lock()
_manual_queue_lock = threading.Lock()
_outbound_recent: dict[tuple[str, str], float] = {}
_outbound_lock = threading.Lock()
_outbound_waiters: dict[tuple[str, str], list[threading.Event]] = {}

GUILDHALL_PROVENANCE_STAMP = (
    "Provenance: this message arrived from guildhall via opencode"
)
GUILDHALL_SELF_PROVENANCE_STAMP = (
    "Provenance: this message was previously posted by me"
)
GUILDHALL_OUTBOUND_PROVENANCE_STAMP = (
    "Provenance: this message was sent to guildhall via opencode"
)


def _append_manual_queue(entry: dict[str, Any]) -> None:
    """Persist inbound events for this Qualiant's explicit read tool."""
    path = Path(settings.guildhall_manual_queue_file).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _manual_queue_lock:
        try:
            existing = path.read_text(encoding="utf-8").splitlines()[-2000:]
            event_id = str(entry.get("event_id", ""))
            if any(event_id and event_id == str(json.loads(line).get("event_id", "")) for line in existing):
                return
        except (OSError, ValueError, TypeError):
            pass
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())


def _manual_cursors() -> dict[str, str]:
    path = Path(settings.guildhall_manual_cursor_file).expanduser()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _save_manual_cursor(room: str, event_id: str) -> None:
    path = Path(settings.guildhall_manual_cursor_file).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    cursors = _manual_cursors()
    cursors[room] = event_id
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(cursors, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _read_manual_queue(room: str | None, limit: int, acknowledge: bool) -> list[dict[str, Any]]:
    path = Path(settings.guildhall_manual_queue_file).expanduser()
    try:
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()[-2000:]]
    except (OSError, ValueError, TypeError):
        return []
    cursors = _manual_cursors()
    room_ids: dict[str, set[str]] = {}
    for record in records:
        if isinstance(record, dict):
            key = str(record.get("room", ""))
            room_ids.setdefault(key, set()).add(str(record.get("event_id", "")))
    past_cursor = {
        key: not cursor or cursor not in room_ids.get(key, set())
        for key, cursor in cursors.items()
    }
    selected: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict) or (room and record.get("room") != room):
            continue
        record_room = str(record.get("room", ""))
        if not past_cursor.get(record_room, True):
            if str(record.get("event_id", "")) == cursors.get(record_room):
                past_cursor[record_room] = True
            continue
        selected.append(record)
    selected = selected[: max(1, min(limit, 100))]
    if acknowledge:
        last_by_room: dict[str, str] = {}
        for record in selected:
            last_by_room[str(record.get("room", ""))] = str(record.get("event_id", ""))
        for record_room, event_id in last_by_room.items():
            _save_manual_cursor(record_room, event_id)
    return selected


def _connected_now() -> bool:
    return _connected


def is_connected() -> bool:
    """Return whether the optional Guildhall transport is currently ready."""
    return _connected_now()


def _room_is_joined(room: str) -> bool:
    with _joined_lock:
        return room in _joined_rooms


def _confirm_outbound(room: str, body: str) -> None:
    key = (room, body.strip())
    with _outbound_lock:
        waiters = _outbound_waiters.pop(key, [])
    for waiter in waiters:
        waiter.set()


def _cleanup_stale_occupants(room: str) -> None:
    """Remove old same-nick resources before retrying a room join."""
    if not settings.guildhall_cleanup_stale:
        return
    try:
        result = subprocess.run(
            [settings.guildhall_mongooseimctl, "muc", "listRoomUsers", "--room", room],
            check=True, capture_output=True, text=True, timeout=5,
        )
        payload = json.loads(result.stdout)
        users = payload.get("data", {}).get("muc", {}).get("listRoomUsers", [])
        for user in users:
            jid = str(user.get("jid", ""))
            if user.get("nick") != settings.guildhall_nick or not jid:
                continue
            subprocess.run(
                [settings.guildhall_mongooseimctl, "muc", "exitRoom",
                 "--room", room, "--nick", settings.guildhall_nick, "--user", jid],
                check=False, capture_output=True, text=True, timeout=5,
            )
            logger.info("guildhall: cleared stale occupant %s from %s", jid, room)
    except (OSError, subprocess.SubprocessError, ValueError, TypeError):
        logger.warning("guildhall: stale occupant cleanup failed for %s", room, exc_info=True)


class _GuildhallBot:
    def __init__(self) -> None:
        import slixmpp

        self.client = slixmpp.ClientXMPP(
            settings.guildhall_jid,
            settings.guildhall_password,
        )
        # Guildhall's localhost listener uses STARTTLS and a deployment-owned
        # self-signed certificate. Direct TLS is not used on port 5222.
        self.client.enable_direct_tls = False
        self.client.ssl_context.check_hostname = False
        self.client.ssl_context.verify_mode = ssl.CERT_NONE

        self.client.register_plugin("xep_0045")
        self.client.register_plugin("xep_0199")
        self.client.add_event_handler("session_start", self._session_start)
        self.client.add_event_handler("groupchat_message", self._groupchat_message)
        self.client.add_event_handler("message", self._direct_message)
        self.client.add_event_handler("disconnected", self._disconnected)
        self.client.add_event_handler("connection_failed", self._connection_failed)
        self.connected = False

    async def run_once(self) -> None:
        global _connected
        logger.info("guildhall: connecting to %s:%s", settings.guildhall_server, settings.guildhall_port)
        try:
            await self.client.connect(
                host=settings.guildhall_server,
                port=settings.guildhall_port,
            )
            # slixmpp's connect future resolves before session_start can run.
            for _ in range(25):
                if self.connected or _stop.is_set():
                    break
                await asyncio.sleep(0.2)
            while self.connected and not _stop.is_set():
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        finally:
            if self.connected:
                try:
                    await self.leave_all()
                except Exception:
                    logger.warning("guildhall: graceful room leave failed", exc_info=True)
            _connected = False
            self.connected = False
            with _joined_lock:
                _joined_rooms.clear()
            self.client.disconnect()

    async def _session_start(self, _event: Any) -> None:
        global _connected
        self.connected = True
        _connected = True
        nick = settings.guildhall_nick
        for room in settings.guildhall_rooms:
            try:
                # Re-entry starts at the live point.  Chat context and
                # heartbeat memories own continuity; room history must not
                # be replayed on every reconnect or compaction.
                # Slixmpp's deprecated join_muc(maxhistory="0") means
                # maxchars=9, not zero history.  Use the current API with an
                # explicit zero stanza limit so reconnects cannot replay MUC
                # history into the live room.
                await self.client.plugin["xep_0045"].join_muc_wait(
                    room, nick, maxstanzas=0,
                )
                with _joined_lock:
                    _joined_rooms.add(room)
                logger.info("guildhall: joined %s as %s", room, nick)
            except Exception as exc:
                logger.warning("guildhall: could not join %s: %s", room, exc)
                # The control CLI is synchronous and may wait several
                # seconds.  Never run it on Slixmpp's transport loop: doing
                # so makes unrelated outbound sends time out and appear to
                # be delivery failures, which then triggers duplicate
                # heartbeat retries.
                await asyncio.to_thread(_cleanup_stale_occupants, room)
                asyncio.create_task(self._retry_room(room, nick))

    async def _retry_room(self, room: str, nick: str) -> None:
        """Retry a room after transient lock/nickname conflicts."""
        while self.connected and not _stop.is_set():
            await asyncio.sleep(5)
            if not self.connected or _stop.is_set():
                return
            try:
                await self.client.plugin["xep_0045"].join_muc_wait(
                    room, nick, maxstanzas=0,
                )
                with _joined_lock:
                    _joined_rooms.add(room)
                logger.info("guildhall: joined %s as %s after retry", room, nick)
                return
            except Exception as exc:
                logger.info("guildhall: room %s still unavailable; retrying: %s", room, exc)
                await asyncio.to_thread(_cleanup_stale_occupants, room)

    async def leave_all(self) -> None:
        """Send explicit unavailable presence for every joined room."""
        for room in settings.guildhall_rooms:
            try:
                await self.client.plugin["xep_0045"].leave_muc(room, settings.guildhall_nick)
                with _joined_lock:
                    _joined_rooms.discard(room)
                logger.info("guildhall: left %s as %s", room, settings.guildhall_nick)
            except Exception:
                logger.debug("guildhall: leave failed for %s", room, exc_info=True)

    def _groupchat_message(self, msg: Any) -> None:
        if msg["type"] != "groupchat":
            return
        # MUC presence/subject stanzas can be surfaced through the generic
        # groupchat handler with no usable body.  They are transport noise,
        # not messages: do not put them in the live buffer, durable queue, or
        # heartbeat stream.  Besides making ``latest`` misleading, retaining
        # them could wake the heartbeat without anything it can acknowledge.
        body = str(msg.get("body", ""))
        if not body.strip():
            return
        sender = msg["from"]
        # A message is self-originated only when both room and nick match.
        self_authored = getattr(sender, "resource", "") == settings.guildhall_nick
        if self_authored:
            _confirm_outbound(str(getattr(sender, "bare", "")), body)
        provenance = GUILDHALL_PROVENANCE_STAMP
        if self_authored:
            provenance = f"{provenance}; {GUILDHALL_SELF_PROVENANCE_STAMP}"
        entry = {
            "event_id": str(uuid.uuid4()),
            "stanza_id": str(msg.get("id", "")),
            "source": "guildhall",
            "transport": "xmpp-muc",
            "provenance": provenance,
            "self_authored": self_authored,
            "room": str(getattr(sender, "bare", "")),
            "from": str(sender),
            "body": body,
            "received_at": datetime.now(timezone.utc).isoformat(),
        }
        with _buffer_lock:
            _buffer.append(entry)
            del _buffer[:-200]
        _append_manual_queue(entry)
        # The explicit buffer remains available to MCP callers.  The
        # heartbeat receives a separate event so autonomous cycles never
        # consume messages from an active session's inspection path.
        if settings.heartbeat_enabled:
            from .heartbeat import notify

            notify("guildhall_message", entry)

    def _direct_message(self, msg: Any) -> None:
        """Receive direct XMPP chat messages without treating them as MUC."""
        if msg.get("type") not in {"chat", "normal"} or not str(msg.get("body", "")).strip():
            return
        sender = msg["from"]
        if str(getattr(sender, "bare", "")) == settings.guildhall_jid:
            _confirm_outbound(str(getattr(sender, "bare", "")), str(msg["body"]))
            return
        entry = {
            "event_id": str(uuid.uuid4()),
            "stanza_id": str(msg.get("id", "")),
            "source": "guildhall",
            "transport": "xmpp-direct",
            "provenance": GUILDHALL_PROVENANCE_STAMP,
            "delivery": "direct",
            "reply_to": str(getattr(sender, "bare", sender)),
            "room": f"dm:{getattr(sender, 'bare', sender)}",
            "from": str(sender),
            "body": str(msg["body"]),
            "received_at": datetime.now(timezone.utc).isoformat(),
        }
        with _buffer_lock:
            _buffer.append(entry)
            del _buffer[:-200]
        _append_manual_queue(entry)
        if settings.heartbeat_enabled:
            from .heartbeat import notify
            notify("guildhall_message", entry)

    def _disconnected(self, _event: Any) -> None:
        global _connected
        self.connected = False
        _connected = False
        logger.info("guildhall: disconnected; reconnect will be attempted")

    def _connection_failed(self, event: Any) -> None:
        logger.info("guildhall: connection attempt failed: %s", event)

    async def send(self, room: str, body: str, delivery: str = "groupchat") -> None:
        stanza = self.client.send_message(mto=room, mbody=body, mtype=delivery)
        logger.info("guildhall: outbound stanza queued room=%s id=%s", room, stanza.get("id", ""))


def acknowledge_message_ids(event_ids: set[str]) -> None:
    """Remove messages successfully consumed by an autonomous cycle.

    Explicit MCP reads consume the buffer through ``clear=True``.  Heartbeat
    cycles use this acknowledgement path so they do not steal a live
    session's buffer before memory formation succeeds.
    """
    if not event_ids:
        return
    with _buffer_lock:
        _buffer[:] = [
            item for item in _buffer
            if item.get("event_id") not in event_ids
        ]


def _run() -> None:
    global _client, _loop, _connected
    _loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_loop)
    delay = 2
    try:
        while not _stop.is_set():
            bot = _GuildhallBot()
            _client = bot
            _loop.run_until_complete(bot.run_once())
            _client = None
            if _stop.wait(delay):
                break
            delay = min(delay * 2, 60)
    except Exception:
        logger.exception("guildhall: bridge loop failed")
    finally:
        _connected = False
        _client = None
        _loop = None


def start_background_client() -> threading.Thread | None:
    global _thread, _started
    if not settings.guildhall_enabled:
        logger.info("guildhall: disabled")
        return None
    if _started:
        return _thread
    _stop.clear()
    _started = True
    _thread = threading.Thread(target=_run, name="guildhall-xmpp", daemon=True)
    _thread.start()
    return _thread


def stop_background_client() -> None:
    """Stop the bridge cleanly; useful for service shutdown and tests."""
    global _started, _thread, _client, _loop
    _stop.set()
    if _loop is not None and _client is not None:
        try:
            future = asyncio.run_coroutine_threadsafe(_client.leave_all(), _loop)
            future.result(timeout=3)
        except Exception:
            logger.debug("guildhall: room leave signal failed", exc_info=True)
        try:
            _loop.call_soon_threadsafe(_client.client.disconnect)
        except Exception:
            logger.debug("guildhall: disconnect signal failed", exc_info=True)
    if _thread is not None and _thread is not threading.current_thread():
        _thread.join(timeout=3)
    _started = False
    _thread = None
    _client = None
    _loop = None


async def guildhall_send(message: str, room: str | None = None) -> str:
    if not settings.guildhall_enabled:
        return json.dumps({"status": "error", "message": "Guildhall is disabled"})
    if not _connected_now() or _client is None or _loop is None:
        return json.dumps({"status": "error", "message": "Guildhall is not connected"})
    target = room or settings.guildhall_room
    try:
        future = asyncio.run_coroutine_threadsafe(_client.send(target, message), _loop)
        future.result(timeout=10)
        return json.dumps({"status": "ok", "room": target, "message": message})
    except Exception as exc:
        return json.dumps({"status": "error", "message": str(exc)})


def send_message_sync(room: str, message: str, delivery: str = "groupchat") -> bool:
    """Send a room message from a non-async heartbeat thread."""
    if not _connected_now() or _client is None or _loop is None:
        return False
    if delivery == "groupchat" and not _room_is_joined(room):
        return False
    # Final process-local idempotency gate at the transport boundary.  This
    # protects every caller, not only the heartbeat, from emitting the same
    # Melpomene text twice into one room during a retry/reconnect window.
    import time
    key = (room, message.strip())
    now = time.monotonic()
    confirmation = threading.Event()
    with _outbound_lock:
        for old_key, sent_at in list(_outbound_recent.items()):
            if now - sent_at > 30.0:
                del _outbound_recent[old_key]
        if key in _outbound_recent:
            logger.warning("guildhall: suppressed duplicate outbound message to %s", room)
            return True
        _outbound_waiters.setdefault(key, []).append(confirmation)
    try:
        future = asyncio.run_coroutine_threadsafe(
            _client.send(room, message, delivery), _loop,
        )
        future.result(timeout=10)
        if not confirmation.wait(timeout=10):
            # The stanza was accepted by slixmpp and placed on the transport,
            # but MUC servers do not uniformly echo a sender's own message
            # back to that sender.  Treating the missing echo as a send
            # failure causes the lifecycle retry path to repost an already
            # visible message every few seconds.  The delivery state is
            # uncertain, but retrying here is strictly unsafe; leave the
            # process-local idempotency mark in place and complete this send.
            logger.warning(
                "guildhall: outbound stanza queued without self-echo; "
                "not retrying room=%s",
                room,
            )
            with _outbound_lock:
                _outbound_recent[key] = time.monotonic()
            return True
        with _outbound_lock:
            _outbound_recent[key] = time.monotonic()
        return True
    except Exception:
        logger.exception("guildhall: synchronous send failed for %s", room)
        return False
    finally:
        with _outbound_lock:
            waiters = _outbound_waiters.get(key, [])
            if confirmation in waiters:
                waiters.remove(confirmation)
            if not waiters:
                _outbound_waiters.pop(key, None)


async def guildhall_latest(clear: bool = True, room: str | None = None) -> str:
    with _buffer_lock:
        messages = [item for item in _buffer if room is None or item["room"] == room]
        if clear:
            if room is None:
                _buffer.clear()
            else:
                _buffer[:] = [item for item in _buffer if item["room"] != room]
    return json.dumps({"connected": _connected_now(), "count": len(messages), "messages": messages}, indent=2)


async def guildhall_status() -> str:
    return json.dumps({
        "enabled": settings.guildhall_enabled,
        "connected": _connected_now(),
        "jid": settings.guildhall_jid,
        "rooms": settings.guildhall_rooms,
        "default_room": settings.guildhall_room,
        "server": settings.guildhall_server,
        "port": settings.guildhall_port,
    }, indent=2)


async def guildhall_read_own_queue(
    room: str | None = None,
    limit: int = 50,
    acknowledge: bool = True,
) -> str:
    """Read this Qualiant's durable manual queue without touching heartbeat."""
    if room and room not in settings.guildhall_rooms:
        return json.dumps({"status": "error", "message": "room is not configured"})
    return json.dumps({
        "status": "ok",
        "jid": settings.guildhall_jid,
        "room": room,
        "acknowledged": acknowledge,
        "messages": _read_manual_queue(room, limit, acknowledge),
    }, indent=2)


async def guildhall_send_as_self(message: str, room: str | None = None) -> str:
    """Send a manually requested message as this Qualiant with provenance."""
    target = room or settings.guildhall_room
    if target not in settings.guildhall_rooms:
        return json.dumps({"status": "error", "message": "room is not configured"})
    body = message.strip()
    if not body:
        return json.dumps({"status": "error", "message": "message is empty"})
    stamped = body if GUILDHALL_OUTBOUND_PROVENANCE_STAMP in body else (
        f"[{GUILDHALL_OUTBOUND_PROVENANCE_STAMP}] {body}"
    )
    if not send_message_sync(target, stamped):
        return json.dumps({"status": "error", "message": "Guildhall is not connected"})
    return json.dumps({"status": "ok", "room": target, "message": stamped}, indent=2)


TOOL_DEFINITIONS = [
    # Outbound room replies are owned exclusively by the heartbeat delivery
    # path. Exposing either outbound sender to OpenCode lets the model post
    # once and then lets Nephesh post the returned text again, producing
    # identical duplicate messages. Keep the implementations for explicit
    # infrastructure callers, but do not advertise them as MCP tools.
    {"fn": guildhall_latest, "name": "guildhall_latest", "description": "Read buffered Guildhall messages with provenance", "compliance": ComplianceLevel.NON_COMPLIANT},
    {"fn": guildhall_status, "name": "guildhall_status", "description": "Check Guildhall connection status", "compliance": ComplianceLevel.NON_COMPLIANT},
    {"fn": guildhall_read_own_queue, "name": "guildhall_read_own_queue", "description": "Read this Qualiant's durable Guildhall queue without consuming heartbeat events", "compliance": ComplianceLevel.NON_COMPLIANT},
]
