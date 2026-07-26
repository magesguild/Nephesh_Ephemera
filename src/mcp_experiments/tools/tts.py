"""Optional feminine-voice TTS tools backed by an isolated StyleTTS2 worker."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
from pathlib import Path
from typing import Any

from ..compliance import ComplianceLevel
from ..config import settings

_lock = threading.Lock()
_active_voice: str | None = None
_worker_timeout = float(os.environ.get("TTS_WORKER_TIMEOUT", "900"))


def _worker_command() -> tuple[str, str, dict[str, str]]:
    root = Path(__file__).resolve().parents[3]
    python = settings.tts_python or str(root / "plugins" / "tts" / ".venv" / "bin" / "python")
    worker_path = root / "plugins" / "tts" / "worker.py"
    env = os.environ.copy()
    env.update({
        "TTS_VOICE_DIR": settings.tts_voice_dir,
        "TTS_MODEL_CHECKPOINT": settings.tts_model_checkpoint,
        "TTS_MODEL_CONFIG": settings.tts_model_config,
        "TTS_PLAYBACK_COMMAND": settings.tts_playback_command,
    })
    return python, str(worker_path), env


def _terminate_process_group(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
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
            process.wait(timeout=5)


def _run_worker(payload: dict[str, Any]) -> dict[str, Any]:
    """Run exactly one request in an owned, disposable worker process."""
    python, worker_path, env = _worker_command()
    process = subprocess.Popen(
        [python, worker_path],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        env=env,
        start_new_session=True,
    )
    try:
        stdout, _ = process.communicate(
            json.dumps(payload) + "\n",
            timeout=_worker_timeout,
        )
    except subprocess.TimeoutExpired as exc:
        _terminate_process_group(process)
        raise RuntimeError("TTS worker timed out and was terminated") from exc
    finally:
        # Only this request's process group can be touched here.
        _terminate_process_group(process)

    if process.returncode != 0:
        raise RuntimeError(f"TTS worker exited with status {process.returncode}")
    lines = [line for line in stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("TTS worker returned no response")
    return json.loads(lines[-1])


def _result_json(result: dict[str, Any]) -> str:
    return json.dumps(result, indent=2)


def tts_list_voices() -> str:
    """List available curated feminine voices and the active voice."""
    global _active_voice
    with _lock:
        result = _run_worker({"action": "list", "voice_id": _active_voice})
        if result.get("ok") and _active_voice is None:
            _active_voice = result.get("active_voice")
        if result.get("ok"):
            result["active_voice"] = _active_voice
        return _result_json(result)


def tts_set_voice(voice_id: str) -> str:
    """Select the active feminine voice without loading the TTS model."""
    global _active_voice
    with _lock:
        result = _run_worker({"action": "set", "voice_id": voice_id})
        if result.get("ok"):
            _active_voice = voice_id
        return _result_json(result)


def tts_voice_info() -> str:
    """Describe the selected feminine voice without retaining a model."""
    with _lock:
        return _result_json(_run_worker({"action": "info", "voice_id": _active_voice}))


def tts_speak(
    text: str,
    voice_id: str | None = None,
    speed: float = 1.0,
    style_weight: float = 0.5,
    warmth: float = 0.0,
) -> str:
    """Synthesize and play speech ephemerally using a feminine voice."""
    with _lock:
        return _result_json(_run_worker({
            "action": "speak",
            "text": text,
            "voice_id": voice_id or _active_voice,
            "speed": speed,
            "style_weight": style_weight,
            "warmth": warmth,
        }))


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {"fn": tts_list_voices, "name": "tts_list_voices", "description": "List curated feminine TTS voices.", "compliance": ComplianceLevel.NON_COMPLIANT},
    {"fn": tts_set_voice, "name": "tts_set_voice", "description": "Switch the active feminine TTS voice live.", "compliance": ComplianceLevel.NON_COMPLIANT},
    {"fn": tts_voice_info, "name": "tts_voice_info", "description": "Describe the active feminine TTS voice.", "compliance": ComplianceLevel.NON_COMPLIANT},
    {"fn": tts_speak, "name": "tts_speak", "description": "Synthesize and play ephemeral speech with a feminine voice.", "compliance": ComplianceLevel.NON_COMPLIANT},
]
