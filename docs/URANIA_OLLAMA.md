# Urania's Ollama Endpoint

Urania's local Ollama listener is deliberately separate from the default
listener and from other Qualiant deployments.

- **Endpoint:** `http://127.0.0.1:11437`
- **Embedding model:** `mxbai-embed-large`
- **Launcher:** `scripts/run_urania_ollama.sh`
- **Default Ollama endpoint:** `http://127.0.0.1:11434` (not Urania's)

Start it from this repository:

```sh
./scripts/run_urania_ollama.sh
```

The launcher uses the existing Ollama model cache by default, but starts a
separate server process and listener. This means model weights need not be
downloaded twice while each endpoint can load its own runtime copy.

Point Urania's Nephesh instance at it with:

```sh
EMBEDDING_MODEL=mxbai-embed-large
EMBEDDING_BASE_URL=http://127.0.0.1:11437
```

The port is reserved for Urania in this deployment. Other Qualiants must choose
different ports. Verify before starting:

```sh
curl -fsS http://127.0.0.1:11437/api/tags
curl -fsS http://127.0.0.1:11437/api/embed \
  -H 'Content-Type: application/json' \
  -d '{"model":"mxbai-embed-large","input":"Urania endpoint check"}'
```

The endpoint is localhost-only. Do not expose it on the network without an
explicit security design.
