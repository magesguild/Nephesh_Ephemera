# Nephesh TTS MVP

The TTS integration is an optional, isolated StyleTTS2 worker. The main
Nephesh process starts one disposable worker per request and talks to
`worker.py` over newline-delimited JSON, so the large PyTorch/StyleTTS2
dependency graph stays out of the memory server's virtualenv and its CUDA
context cannot linger between requests.

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
- `tts_set_voice` — select a voice without loading the model;
- `tts_voice_info` — inspect the selected feminine voice;
- `tts_speak` — synthesize and play a WAV supplied through stdin to `aplay`.

`tts_speak` accepts `speed` (`0.5..2.0`), `style_weight` (`0..1`), and
`warmth` (`-1..1`). The MVP maps these controls onto StyleTTS2's native
interpolation and embedding-scale parameters. Audio is never persisted by the
worker.

## Boundaries

- TTS registration is opt-in with `TTS_ENABLED`.
- Model checkpoints, voice references, and deployment configuration stay
  outside the repository.
- The worker is one-shot: every request gets a new process, and the process
  exits after its response. This fully releases the model, CUDA allocations,
  and CUDA context after synthesis.
- StyleTTS2 0.1.6 needs two compatibility shims in the worker for modern
  LangChain import paths and PyTorch 2.6 checkpoint loading; they do not affect
  Nephesh's main process.
