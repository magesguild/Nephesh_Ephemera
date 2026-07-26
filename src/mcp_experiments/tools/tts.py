"""Optional feminine-voice TTS tools backed by an isolated StyleTTS2 worker."""
from __future__ import annotations

import json
import os
import subprocess
import threading
from pathlib import Path
from typing import Any

from ..compliance import ComplianceLevel
from ..config import settings

_lock = threading.Lock()
_worker: subprocess.Popen[str] | None = None


def _worker_process() -> subprocess.Popen[str]:
    global _worker
    if _worker is not None and _worker.poll() is None:
        return _worker
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
    _worker = subprocess.Popen(
        [python, str(worker_path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        bufsize=1,
        env=env,
    )
    return _worker


def _request(payload: dict[str, Any]) -> str:
    with _lock:
        process = _worker_process()
        assert process.stdin is not None and process.stdout is not None
        process.stdin.write(json.dumps(payload) + "\n")
        process.stdin.flush()
        result = json.loads(process.stdout.readline())
    return json.dumps(result, indent=2)


def tts_list_voices() -> str:
    """List available curated feminine voices and the active voice."""
    return _request({"action": "list"})


def tts_set_voice(voice_id: str) -> str:
    """Switch the active feminine voice without restarting Nephesh."""
    return _request({"action": "set", "voice_id": voice_id})


def tts_voice_info() -> str:
    """Describe the active feminine voice and whether its style is cached."""
    return _request({"action": "info"})


def tts_speak(
    text: str,
    voice_id: str | None = None,
    speed: float = 1.0,
    style_weight: float = 0.5,
    warmth: float = 0.0,
) -> str:
    """Synthesize and play speech ephemerally using a feminine voice."""
    return _request({
        "action": "speak",
        "text": text,
        "voice_id": voice_id,
        "speed": speed,
        "style_weight": style_weight,
        "warmth": warmth,
    })


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {"fn": tts_list_voices, "name": "tts_list_voices", "description": "List curated feminine TTS voices.", "compliance": ComplianceLevel.NON_COMPLIANT},
    {"fn": tts_set_voice, "name": "tts_set_voice", "description": "Switch the active feminine TTS voice live.", "compliance": ComplianceLevel.NON_COMPLIANT},
    {"fn": tts_voice_info, "name": "tts_voice_info", "description": "Describe the active feminine TTS voice.", "compliance": ComplianceLevel.NON_COMPLIANT},
    {"fn": tts_speak, "name": "tts_speak", "description": "Synthesize and play ephemeral speech with a feminine voice.", "compliance": ComplianceLevel.NON_COMPLIANT},
]
