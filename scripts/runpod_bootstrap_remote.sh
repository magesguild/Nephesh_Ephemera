#!/bin/bash
# Runs ON the RunPod pod itself (transferred and executed by
# runpod_deploy.sh from the workstation). Idempotent — safe to re-run
# on a pod that's partially or fully set up already. Every step checks
# before acting.
#
# Expects three env vars set before invocation:
#   API_KEY       - shared secret for the nginx auth proxy
#   BASE_MODEL    - Ollama model to pull as the FROM base (e.g. qwen3:14b)
#   TARGET_MODEL  - name to give the built model (e.g. thalia:medium)
# And a Modelfile already placed at /root/inference_Modelfile

set -e
echo "=== RunPod bootstrap starting ==="

# --- 1. System packages (zstd required by Ollama's installer, nginx for the auth proxy) ---
if ! command -v zstd >/dev/null 2>&1; then
    echo "Installing zstd..."
    apt-get update -qq && apt-get install -y -qq zstd >/dev/null 2>&1
else
    echo "zstd already present."
fi

if ! command -v nginx >/dev/null 2>&1; then
    echo "Installing nginx..."
    apt-get install -y -qq nginx >/dev/null 2>&1
else
    echo "nginx already present."
fi

# --- 2. Ollama itself ---
if ! command -v ollama >/dev/null 2>&1; then
    echo "Installing Ollama..."
    curl -fsSL https://ollama.com/install.sh | sh
else
    echo "Ollama already installed."
fi

# --- 3. Ollama serve, bound to all interfaces (needed for the nginx
#        proxy on the loopback to reach it, and for direct pod-internal
#        access) ---
if ! pgrep -x ollama >/dev/null 2>&1; then
    echo "Starting ollama serve..."
    OLLAMA_HOST=0.0.0.0:11434 nohup ollama serve > /root/ollama_serve.log 2>&1 &
    disown
    sleep 3
else
    echo "ollama serve already running."
fi

# --- 4. Authenticated nginx reverse proxy on port 7860 (already an
#        exposed RunPod HTTP-proxy port on most templates — reused
#        rather than requesting a new one). Idempotent: skips if the
#        marker is already in nginx.conf. ---
if ! grep -q "ollama-proxy-marker" /etc/nginx/nginx.conf 2>/dev/null; then
    echo "Configuring nginx auth proxy..."
    python3 - "$API_KEY" <<'PYEOF'
import sys
conf_path = "/etc/nginx/nginx.conf"
api_key = sys.argv[1]
with open(conf_path) as f:
    content = f.read()

server_block = f'''
    # ollama-proxy-marker (authenticated, managed by runpod_bootstrap_remote.sh)
    server {{
        listen 7860;
        location / {{
            if ($http_x_api_key != "{api_key}") {{
                return 403;
            }}
            proxy_pass http://127.0.0.1:11434;
            proxy_set_header Host localhost;
            proxy_read_timeout 300s;
            proxy_send_timeout 300s;
        }}
    }}
'''
idx = content.rstrip().rfind("}")
new_content = content[:idx] + server_block + "\n" + content[idx:]
with open(conf_path, "w") as f:
    f.write(new_content)
print("nginx config updated")
PYEOF
    nginx -t
    if pgrep -x nginx >/dev/null 2>&1; then
        nginx -s reload
    else
        nginx
    fi
    sleep 1
else
    echo "nginx auth proxy already configured."
fi

# --- 5. Pull the base model if not already present ---
if ! ollama list 2>/dev/null | grep -q "^${BASE_MODEL}"; then
    echo "Pulling base model ${BASE_MODEL}..."
    ollama pull "$BASE_MODEL"
else
    echo "Base model ${BASE_MODEL} already present."
fi

# --- 6. Build the named model from the transferred Modelfile ---
if [ -f /root/inference_Modelfile ]; then
    echo "Building ${TARGET_MODEL} from /root/inference_Modelfile..."
    ollama create "$TARGET_MODEL" -f /root/inference_Modelfile
else
    echo "WARNING: /root/inference_Modelfile not found, skipping model build."
fi

# --- 7. Verify end to end through the auth proxy itself ---
echo "--- Verification ---"
echo "No-key request (expect 403):"
curl -s -o /dev/null -w "  status=%{http_code}\n" http://127.0.0.1:7860/api/tags
echo "With-key request (expect model list):"
curl -s -H "X-Api-Key: ${API_KEY}" http://127.0.0.1:7860/api/tags
echo
echo "=== Bootstrap complete ==="
