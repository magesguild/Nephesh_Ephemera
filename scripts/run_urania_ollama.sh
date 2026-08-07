#!/usr/bin/env bash
set -euo pipefail

# Urania's private Ollama listener. Melpomene and other Qualiants must use
# different ports. Model files may remain in the shared Ollama model cache;
# the listener and loaded runtime are separate.
PORT="${URANIA_OLLAMA_PORT:-11437}"
HOST="${URANIA_OLLAMA_HOST:-127.0.0.1}"
MODELS="${OLLAMA_MODELS:-$HOME/.ollama/models}"

exec env \
  OLLAMA_HOST="${HOST}:${PORT}" \
  OLLAMA_MODELS="${MODELS}" \
  ollama serve
