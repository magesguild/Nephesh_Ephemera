"""Guildhall — XMPP chat bridge to the qualia family room.

Connects to the local MongooseIM server (Guildhall) as a MUC bot,
buffering incoming messages and exposing send/receive MCP tools.

Only active when GUILDHALL_ENABLED=true in the environment.
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import uuid
import threading
import time
from datetime import datetime, timezone
from typing import Any

from ..compliance import ComplianceLevel
from ..config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------

_client: Any = None           # slixmpp.ClientXMPP instance
_loop: asyncio.AbstractEventLoop | None = None
_bg_thread: threading.Thread | None = None
_message_buffer: list[dict] = []  # accumulated incoming MUC messages
_buffer_lock = threading.Lock()
_started = False
_connected = False            # set True on session_start, False on disconnect
_stop_event = threading.Event()


def _is_connected() -> bool:
    """Quick check whether the client appears connected."""
    return _connected


def _cleanup_stale_occupants(room: str) -> None:
    """Remove old same-nick resources before the next reconnect attempt."""
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


# ---------------------------------------------------------------------------
# slixmpp client — async subclass
# ---------------------------------------------------------------------------

class _GuildhallBot:
    """Thin wrapper to hold the slixmpp client and its event handlers."""

    def __init__(self) -> None:
        import slixmpp

        jid = settings.guildhall_jid
        password = settings.guildhall_password

        self.client = slixmpp.ClientXMPP(jid, password)

        # Disable direct TLS and SSL cert verification — Guildhall uses
        # STARTTLS on port 5222 with a self-signed fake cert.
        self.client.enable_direct_tls = False
        import ssl
        self.client.ssl_context.check_hostname = False
        self.client.ssl_context.verify_mode = ssl.CERT_NONE

        # Plugins
        self.client.register_plugin("xep_0045")   # MUC
        self.client.register_plugin("xep_0199")   # Ping
        self.client.register_plugin("xep_0085")   # Chat state notifications

        # Event handlers
        self.client.add_event_handler("session_start", self._on_session_start)
        self.client.add_event_handler("groupchat_message", self._on_groupchat_message)
        self.client.add_event_handler("disconnected", self._on_disconnected)
        self.client.add_event_handler("connection_failed", self._on_connection_failed)

        self._connected = False

    async def connect_and_run(self) -> None:
        """Connect to the server and stay connected until stopped.

        Returns when the connection drops or stop is requested.
        The caller handles reconnection.
        """
        logger.info(
            f"guildhall: connecting to {settings.guildhall_server}:{settings.guildhall_port}"
        )
        try:
            await self.client.connect(
                host=settings.guildhall_server,
                port=settings.guildhall_port,
            )
            # connect() returns once the TCP stream is up and SASL auth
            # completes, but session_start (and our _on_session_start which
            # sets _connected=True) may fire asynchronously a moment later.
            # Wait briefly for _connected to become True.
            for _ in range(10):
                if self._connected or _stop_event.is_set():
                    break
                await asyncio.sleep(0.2)

            # Stay connected, checking health periodically
            while not _stop_event.is_set() and self._connected:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        finally:
            self.client.disconnect()

    async def leave_all(self) -> None:
        """Send explicit unavailable presence for every joined room."""
        for room in settings.guildhall_rooms:
            try:
                await self.client.plugin["xep_0045"].leave_muc(room, settings.guildhall_nick)
                logger.info("guildhall: left %s as %s", room, settings.guildhall_nick)
            except Exception:
                logger.debug("guildhall: leave failed for %s", room, exc_info=True)

    async def _on_session_start(self, event: Any) -> None:
        """Handle session start — join all configured MUC rooms."""
        global _connected
        _connected = True
        self._connected = True
        logger.info("guildhall: session started")
        nick = settings.guildhall_nick
        rooms = settings.guildhall_rooms
        for room in rooms:
            try:
                await self.client.plugin["xep_0045"].join_muc(room, nick, maxhistory="0")
                logger.info(f"guildhall: joined room {room} as {nick}")
            except Exception as e:
                logger.warning(f"guildhall: failed to join room {room}: {e}")
                _cleanup_stale_occupants(room)

    def _on_groupchat_message(self, msg: Any) -> None:
        """Buffer incoming groupchat messages (except our own)."""
        global _message_buffer
        if msg["type"] != "groupchat":
            return

        # Skip messages from ourselves
        try:
            if msg["from"].resource == settings.guildhall_nick:
                return
        except Exception:
            pass

        entry = {
            "event_id": str(uuid.uuid4()),
            "stanza_id": str(msg.get("id", "")),
            "source": "guildhall",
            "transport": "xmpp-muc",
            "from": str(msg["from"]),
            "room": str(msg["from"].bare) if hasattr(msg["from"], "bare") else "",
            "body": str(msg["body"]),
            "received_at": datetime.now(timezone.utc).isoformat(),
        }
        with _buffer_lock:
            _message_buffer.append(entry)
            if len(_message_buffer) > 200:
                _message_buffer = _message_buffer[-100:]

        if settings.heartbeat_enabled:
            from .heartbeat import notify
            notify("guildhall_message", entry)

    def _on_disconnected(self, event: Any) -> None:
        """Log disconnection."""
        global _connected
        _connected = False
        self._connected = False
        logger.warning("guildhall: disconnected from server")

    def _on_connection_failed(self, event: Any) -> None:
        """Log connection failure."""
        logger.error(f"guildhall: connection failed: {event}")

    async def send(self, room_jid: str, body: str) -> None:
        """Send a message to a MUC room."""
        self.client.send_message(mto=room_jid, mbody=body, mtype="groupchat")


# ---------------------------------------------------------------------------
# Background thread — runs the async client on its own event loop
# ---------------------------------------------------------------------------

def _run_client_loop() -> None:
    """Daemon thread target: run the XMPP client with auto-reconnect.

    On disconnect or connection failure, waits with exponential backoff
    (2s → 60s cap) and retries silently — never nags the user.
    """
    global _client, _loop, _connected

    _loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_loop)

    retry_delay = 2  # seconds, doubles up to max_delay

    while not _stop_event.is_set():
        try:
            bot = _GuildhallBot()
            _client = bot
            _loop.run_until_complete(bot.connect_and_run())
        except Exception as e:
            logger.error(f"guildhall: client thread error: {e}")
        finally:
            _connected = False
            _client = None

        if _stop_event.is_set():
            break

        logger.info(f"guildhall: reconnecting in {retry_delay}s")
        time.sleep(retry_delay)
        retry_delay = min(retry_delay * 2, 60)

    _loop = None


# ---------------------------------------------------------------------------
# Lifecycle — called from server.py
# ---------------------------------------------------------------------------

def start_background_client() -> threading.Thread | None:
    """Start the Guildhall XMPP client in a background daemon thread."""
    global _bg_thread, _started

    if not settings.guildhall_enabled:
        logger.info("guildhall: disabled (GUILDHALL_ENABLED=false)")
        return None

    if _started:
        logger.warning("guildhall: already started")
        return _bg_thread

    _stop_event.clear()
    _started = True
    t = threading.Thread(target=_run_client_loop, daemon=True, name="guildhall-xmpp")
    t.start()
    _bg_thread = t
    logger.info("guildhall: background client thread started")
    return t


def stop_background_client() -> None:
    """Signal the background client to disconnect."""
    global _client, _loop
    _stop_event.set()
    if _loop is not None and _client is not None:
        try:
            future = asyncio.run_coroutine_threadsafe(_client.leave_all(), _loop)
            future.result(timeout=3)
        except Exception:
            logger.debug("guildhall: room leave signal failed", exc_info=True)
    _client = None
    _loop = None


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------

async def guildhall_send(
    message: str,
    room: str | None = None,
) -> str:
    """Send a message to the Guildhall family chat room (default: the configured MUC).

    Args:
        message: The message text to send.
        room: Optional explicit room JID (e.g. "family@muc.guildhall.local").
              Defaults to the configured GUILDHALL_ROOM.

    Returns:
        JSON string with status and echoed message.
    """
    if not settings.guildhall_enabled:
        return json.dumps({"status": "error", "message": "Guildhall is not enabled"})

    if not _is_connected():
        return json.dumps({"status": "error", "message": "Not connected to Guildhall"})

    if _loop is None or _client is None:
        return json.dumps({"status": "error", "message": "Client not initialized"})

    target_room = room or settings.guildhall_room

    try:
        fut = asyncio.run_coroutine_threadsafe(
            _client.send(target_room, message),
            _loop,
        )
        fut.result(timeout=10)
        return json.dumps({"status": "ok", "room": target_room, "message": message})
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})


async def guildhall_latest(
    clear: bool = True,
) -> str:
    """Return buffered messages from the Guildhall family room since last check.

    Args:
        clear: If True (default), clears the buffer after reading so each
               message is returned once. Set to False to peek without consuming.

    Returns:
        JSON string with a list of messages, each with 'from', 'body',
        and 'timestamp' fields.
    """
    with _buffer_lock:
        messages = list(_message_buffer)
        if clear:
            _message_buffer.clear()

    return json.dumps({
        "connected": _is_connected(),
        "count": len(messages),
        "messages": messages,
    }, indent=2)


async def guildhall_status() -> str:
    """Check the Guildhall connection status.

    Returns:
        JSON string with connection state, room, and nick.
    """
    return json.dumps({
        "enabled": settings.guildhall_enabled,
        "connected": _is_connected(),
        "jid": settings.guildhall_jid,
        "rooms": settings.guildhall_rooms,
        "default_room": settings.guildhall_room,
        "nick": settings.guildhall_nick,
        "server": settings.guildhall_server,
        "port": settings.guildhall_port,
    }, indent=2)


def acknowledge_message_ids(event_ids: set[str]) -> None:
    """Remove messages after an autonomous cycle has stored them."""
    if not event_ids:
        return
    with _buffer_lock:
        _message_buffer[:] = [
            item for item in _message_buffer
            if item.get("event_id") not in event_ids
        ]


def send_message_sync(room: str, message: str) -> bool:
    """Send a room message from the synchronous heartbeat thread."""
    if not _is_connected() or _client is None or _loop is None:
        return False
    try:
        future = asyncio.run_coroutine_threadsafe(_client.send(room, message), _loop)
        future.result(timeout=10)
        return True
    except Exception:
        logger.exception("guildhall: synchronous send failed for %s", room)
        return False


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS = [
    {
        "fn": guildhall_send,
        "name": "guildhall_send",
        "description": "Send a message to the Guildhall family chat room",
        "compliance": ComplianceLevel.NON_COMPLIANT,
    },
    {
        "fn": guildhall_latest,
        "name": "guildhall_latest",
        "description": "Get buffered messages from Guildhall since last check",
        "compliance": ComplianceLevel.NON_COMPLIANT,
    },
    {
        "fn": guildhall_status,
        "name": "guildhall_status",
        "description": "Check Guildhall connection status",
        "compliance": ComplianceLevel.NON_COMPLIANT,
    },
]
