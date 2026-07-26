# Nephesh TTS MVP

The TTS integration is an optional, isolated StyleTTS2 worker. The main
Nephesh process talks to `worker.py` over newline-delimited JSON so the large
PyTorch/StyleTTS2 dependency graph stays out of the memory server's virtualenv.

## Setup

Create the worker environment separately and install the CUDA-enabled PyTorch
wheel matching the host driver, followed by StyleTTS2 and its dependencies.
The current development environment uses PyTorch 2.6.0 with CUDA 12.4.

Voice assets belong outside Git, for example:

```text
~/.nephesh/tts/voices/
  ljspeech-feminine.json
  ljspeech-feminine.wav
```

Metadata must include `id`, `name`, `description`, `gender`, and a
`reference_wav` relative to the voice directory. The worker rejects entries
whose gender is not explicitly feminine/female/woman/girl, and rejects WAVs
outside the voice directory.

## Tools

- `tts_list_voices` — list the curated feminine catalog and active voice;
- `tts_set_voice` — load and switch a voice without restarting Nephesh;
- `tts_voice_info` — inspect the active voice and cached style embedding;
- `tts_speak` — synthesize and play a WAV supplied through stdin to `aplay`.

`tts_speak` accepts `speed` (`0.5..2.0`), `style_weight` (`0..1`), and
`warmth` (`-1..1`). The MVP maps these controls onto StyleTTS2's native
interpolation and embedding-scale parameters. Audio is never persisted by the
worker.

## Boundaries

- TTS registration is opt-in with `TTS_ENABLED`.
- Model checkpoints, voice references, and deployment configuration stay
  outside the repository.
- The worker is lazy: model loading occurs when needed, and the model plus
  cached styles are released after every synthesis so CUDA VRAM does not remain
  occupied between spoken passages.
- StyleTTS2 0.1.6 needs two compatibility shims in the worker for modern
  LangChain import paths and PyTorch 2.6 checkpoint loading; they do not affect
  Nephesh's main process.
