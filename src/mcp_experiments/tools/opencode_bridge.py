"""Managed OpenCode process and persistent reply session."""

from __future__ import annotations

import atexit
import json
import logging
import os
import secrets
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import httpx

from ..config import settings

logger = logging.getLogger(__name__)
_process: subprocess.Popen | None = None
_password: str | None = None
_session_ids: dict[str, str] = {}
_lock = threading.RLock()


def _stop_process(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=5)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def _url() -> str:
    return f"http://{settings.opencode_host}:{settings.opencode_port}"


def _client() -> httpx.Client:
    return httpx.Client(base_url=_url(), auth=(settings.opencode_username, _password or ""),
                        timeout=httpx.Timeout(30.0, connect=3.0))


def _healthy(client: httpx.Client) -> bool:
    try:
        response = client.get("/global/health")
        return response.is_success and response.json().get("healthy") is True
    except (httpx.HTTPError, ValueError):
        return False


def _password_value() -> str:
    path = Path(settings.opencode_password_file)
    try:
        value = path.read_text().strip()
        if value:
            return value
    except OSError:
        pass
    value = secrets.token_urlsafe(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value + "\n")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)
    return value


def start() -> bool:
    global _process, _password
    if not settings.opencode_enabled:
        return False
    with _lock:
        _password = _password_value()
        if _process is not None and _process.poll() is None:
            with _client() as client:
                if _healthy(client):
                    return True
            logger.warning("opencode: managed child is alive but unhealthy; restarting")
            _stop_process(_process)
            _process = None
        with _client() as client:
            if _healthy(client):
                logger.info("opencode: recovered healthy server at %s", _url())
                return True
        command = [settings.opencode_binary, "serve", "--hostname", settings.opencode_host,
                   "--port", str(settings.opencode_port)]
        try:
            _process = subprocess.Popen(command, cwd=settings.opencode_project_dir,
                                        env={**os.environ, "OPENCODE_SERVER_PASSWORD": _password,
                                             "OPENCODE_SERVER_USERNAME": settings.opencode_username},
                                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError:
            logger.exception("opencode: failed to start %r", command)
            return False
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            with _client() as client:
                if _healthy(client):
                    return True
            time.sleep(0.25)
        logger.error("opencode: server did not become healthy")
        return False


def start_background() -> threading.Thread:
    thread = threading.Thread(target=start, name="opencode-start", daemon=True)
    thread.start()
    return thread


def _session(client: httpx.Client, room: str) -> str | None:
    if not _session_ids:
        try:
            data = json.loads(Path(settings.opencode_session_file).read_text())
            sessions = data.get("sessions")
            if isinstance(sessions, dict):
                _session_ids.update({str(k): str(v) for k, v in sessions.items() if v})
        except (OSError, ValueError, TypeError):
            pass
    session_id = _session_ids.get(room)
    if session_id:
        try:
            if client.get(f"/session/{session_id}").is_success:
                return session_id
        except httpx.HTTPError:
            pass
    try:
        response = client.post("/session", json={"title": f"Melpomene Guildhall Planning — {room}"})
        response.raise_for_status()
        session_id = response.json()["id"]
        _session_ids[room] = session_id
        path = Path(settings.opencode_session_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"sessions": _session_ids}, indent=2) + "\n")
        return session_id
    except (httpx.HTTPError, KeyError, ValueError):
        logger.exception("opencode: could not create persistent session")
        return None


def reply(room: str, messages: list[dict[str, Any]]) -> str | None:
    if not settings.opencode_enabled or not messages or not start():
        return None
    with _lock:
        try:
            with _client() as client:
                session_id = _session(client, room)
                if not session_id:
                    return None
                transcript = "\n".join(f"{m.get('from', 'unknown')}: {m.get('body', '')}" for m in messages)
                prompt = ("You are participating in a Guildhall planning session.\n"
                          f"Room: {room}\nThese inbound messages arrived since your last cycle:\n"
                          f"{transcript}\n\nReply as yourself to the room. Be useful and concise. "
                          "Return only the message text that should be posted to the room.")
                request = {
                    "agent": settings.opencode_agent,
                    "model": {"providerID": settings.opencode_model.split("/", 1)[0],
                              "modelID": settings.opencode_model.split("/", 1)[1]},
                    "parts": [{"type": "text", "text": prompt}],
                }
                response = None
                for attempt in range(3):
                    response = client.post(f"/session/{session_id}/message", json=request)
                    if response.is_success:
                        break
                    if response.status_code not in {400, 409, 425, 503}:
                        response.raise_for_status()
                    time.sleep(1.0 * (attempt + 1))
                assert response is not None
                response.raise_for_status()
                return "\n".join(str(p.get("text", "")).strip() for p in response.json().get("parts", [])
                                   if p.get("type") == "text" and p.get("text")).strip() or None
        except (httpx.HTTPError, KeyError, ValueError):
            logger.exception("opencode: reply request failed for %s", room)
            return None


def stop() -> None:
    """Stop the managed child so service restarts do not leave stale state."""
    global _process, _password
    with _lock:
        _stop_process(_process)
        _process = None
        _password = None


atexit.register(stop)
