"""Persistent StyleTTS2 worker used by the Nephesh MCP tool boundary.

The worker owns the heavyweight model and keeps all synthesized audio in
memory.  It communicates with the main server over newline-delimited JSON.
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any


FEMININE_GENDERS = {"female", "feminine", "woman", "girl"}


def _error(message: str) -> dict[str, Any]:
    return {"ok": False, "error": message}


class Worker:
    def __init__(self) -> None:
        self.voice_dir = Path(os.environ.get("TTS_VOICE_DIR", "")).expanduser()
        self.checkpoint = Path(os.environ.get("TTS_MODEL_CHECKPOINT", "")).expanduser()
        self.config = Path(os.environ.get("TTS_MODEL_CONFIG", "")).expanduser()
        self.playback_command = os.environ.get("TTS_PLAYBACK_COMMAND", "aplay")
        self.engine: Any = None
        self.voices: dict[str, dict[str, Any]] = {}
        self.styles: dict[str, Any] = {}
        self.active_voice: str | None = None

    def _load_catalog(self) -> None:
        self.voices = {}
        if not self.voice_dir.is_dir():
            return
        for metadata_path in sorted(self.voice_dir.glob("*.json")):
            try:
                metadata = json.loads(metadata_path.read_text())
                voice_id = str(metadata["id"]).strip()
                gender = str(metadata.get("gender", "")).strip().lower()
                reference = metadata.get("reference_wav")
                if not voice_id or gender not in FEMININE_GENDERS or not reference:
                    continue
                reference_path = (self.voice_dir / str(reference)).resolve()
                if self.voice_dir.resolve() not in reference_path.parents or not reference_path.is_file():
                    continue
                self.voices[voice_id] = {
                    **metadata,
                    "id": voice_id,
                    "gender": "feminine",
                    "reference_wav": str(reference_path),
                }
            except (OSError, ValueError, KeyError, TypeError):
                continue
        if self.active_voice not in self.voices:
            self.active_voice = next(iter(self.voices), None)

    def _ensure_engine(self) -> None:
        if self.engine is not None:
            return
        if not self.checkpoint.is_file() or not self.config.is_file():
            raise RuntimeError("TTS_MODEL_CHECKPOINT and TTS_MODEL_CONFIG must point to existing files")
        # StyleTTS2 0.1.6 imports the pre-1.0 LangChain module path.  Keep the
        # compatibility shim inside the isolated worker rather than pinning
        # Nephesh's main server to its obsolete dependency graph.
        import torch
        import nltk

        # Newer NLTK separates the Punkt tables used by the older StyleTTS2
        # tokenizer.  Keep the data in the user's cache, never in the repo.
        nltk.download("punkt", quiet=True)
        nltk.download("punkt_tab", quiet=True)

        # The StyleTTS2 0.1.6 checkpoints are trusted project artifacts but
        # predate PyTorch 2.6's weights_only default.  Scope the compatibility
        # override to this isolated worker; never alter Nephesh's main process.
        original_torch_load = torch.load

        def trusted_checkpoint_load(*args: Any, **kwargs: Any) -> Any:
            kwargs.setdefault("weights_only", False)
            return original_torch_load(*args, **kwargs)

        torch.load = trusted_checkpoint_load  # type: ignore[method-assign]

        try:
            from langchain.text_splitter import RecursiveCharacterTextSplitter
        except ModuleNotFoundError:
            import types

            from langchain_text_splitters import RecursiveCharacterTextSplitter

            shim = types.ModuleType("langchain.text_splitter")
            shim.RecursiveCharacterTextSplitter = RecursiveCharacterTextSplitter
            sys.modules["langchain.text_splitter"] = shim

        from styletts2.tts import StyleTTS2

        self.engine = StyleTTS2(
            model_checkpoint_path=str(self.checkpoint),
            config_path=str(self.config),
        )

    def _style(self, voice_id: str) -> Any:
        self._ensure_engine()
        if voice_id not in self.voices:
            raise RuntimeError(f"unknown feminine voice: {voice_id}")
        if voice_id not in self.styles:
            self.styles[voice_id] = self.engine.compute_style(self.voices[voice_id]["reference_wav"])
        return self.styles[voice_id]

    def handle(self, request: dict[str, Any]) -> dict[str, Any]:
        action = request.get("action")
        self._load_catalog()
        if action == "list":
            return {"ok": True, "voices": list(self.voices.values()), "active_voice": self.active_voice}
        if action == "info":
            if not self.active_voice:
                return {"ok": True, "voice": None}
            return {"ok": True, "voice": self.voices[self.active_voice], "loaded": self.active_voice in self.styles}
        if action == "set":
            voice_id = str(request.get("voice_id", "")).strip()
            self._style(voice_id)
            self.active_voice = voice_id
            return {"ok": True, "active_voice": voice_id, "voice": self.voices[voice_id]}
        if action == "speak":
            text = str(request.get("text", "")).strip()
            if not text:
                raise RuntimeError("text must not be empty")
            voice_id = str(request.get("voice_id") or self.active_voice or "").strip()
            style = self._style(voice_id)
            warmth = max(-1.0, min(1.0, float(request.get("warmth", 0.0))))
            style_weight = max(0.0, min(1.0, float(request.get("style_weight", 0.5))))
            speed = max(0.5, min(2.0, float(request.get("speed", 1.0))))
            # StyleTTS2 exposes alpha/beta rather than named warmth controls.
            # Keep the public API stable while mapping gently onto its style
            # and prosody interpolation knobs.
            alpha = max(0.05, min(0.8, 0.3 + warmth * 0.15))
            beta = max(0.05, min(0.95, 0.35 + style_weight * 0.5))
            audio = self.engine.inference(
                text,
                ref_s=style,
                alpha=alpha,
                beta=beta,
                embedding_scale=0.8 + style_weight * 0.4,
            )
            if speed != 1.0:
                import librosa

                audio = librosa.effects.time_stretch(audio.astype("float32"), rate=speed)
            import soundfile as sf

            wav = io.BytesIO()
            sf.write(wav, audio, 24000, format="WAV", subtype="PCM_16")
            subprocess.run([self.playback_command, "-q"], input=wav.getvalue(), check=True)
            return {"ok": True, "voice_id": voice_id, "sample_rate": 24000, "duration_seconds": len(audio) / 24000}
        raise RuntimeError(f"unknown TTS action: {action}")


def main() -> None:
    worker = Worker()
    for line in sys.stdin:
        try:
            # Third-party model code prints diagnostics and phonemes.  Keep
            # stdout strictly JSONL so the Nephesh client cannot lose framing.
            with redirect_stdout(sys.stderr):
                result = worker.handle(json.loads(line))
        except Exception as exc:  # worker boundary must remain alive after one bad request
            result = _error(str(exc))
        print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
