#!/bin/bash
# Stand up (or re-verify) a RunPod GPU pod as an Ollama inference
# backend, in one command.
#
# Handles both RunPod SSH-gateway quirks documented in AGENTS.md:
#   1. ssh.runpod.io never runs a passed command directly — it always
#      allocates a PTY and drops into an interactive shell. Every remote
#      command here goes through piped stdin + `exit`, not `ssh ... "cmd"`.
#   2. Large payloads (scripts, Modelfiles) must be transferred as
#      base64 wrapped at ~76 chars/line via a heredoc, never as one
#      giant unbroken line — that chokes the PTY.
#
# This script is idempotent. Re-running it against a pod that's
# already set up just re-verifies everything and exits quickly.
#
# Usage:
#   ./scripts/runpod_deploy.sh <pod-ssh-target> [modelfile] [base_model] [target_model] [proxy_port]
#
# Example:
#   ./scripts/runpod_deploy.sh bm5mabv3ssu67e-64410ec8@ssh.runpod.io \
#       ~/src/AiEntityWork/Thalia_Kernel_Modelfile qwen2.5:14b thalia:Uncensored 7860
#
# On success, prints the OLLAMA_URL / OLLAMA_API_KEY
# lines ready to paste into .env or opencode.jsonc.

set -e

POD_TARGET="${1:?Usage: $0 <pod-ssh-target> [modelfile] [base_model] [target_model] [proxy_port]}"
MODELFILE="${2:-$HOME/src/AiEntityWork/Thalia_Kernel_Modelfile}"
BASE_MODEL="${3:-qwen2.5:14b}"
TARGET_MODEL="${4:-thalia:Uncensored}"
PROXY_PORT="${5:-7860}"

SSH_KEY="${RUNPOD_SSH_KEY:-$HOME/.ssh/id_ed25519}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
API_KEY_FILE="$SCRIPT_DIR/../data/runpod_api_key.txt"
BOOTSTRAP_SCRIPT="$SCRIPT_DIR/runpod_bootstrap_remote.sh"

# Extract pod ID (portion before the first hyphen-separated suffix in the
# user@ part) — RunPod's proxy URL format is https://<pod-id>-<port>.proxy.runpod.net
POD_USER="${POD_TARGET%%@*}"
POD_ID="${POD_USER%%-*}"

ssh_exec() {
    # Pipe commands through stdin with -tt, terminated by exit — the
    # only way to run non-interactive commands against ssh.runpod.io.
    printf '%s\nexit\n' "$1" | ssh -tt -o StrictHostKeyChecking=no -o ConnectTimeout=15 \
        "$POD_TARGET" -i "$SSH_KEY" 2>&1
}

transfer_file() {
    # $1 = local path, $2 = remote path. Sends as line-wrapped base64
    # through a heredoc — never as one giant unbroken line.
    local local_path="$1" remote_path="$2"
    local b64_tmp
    b64_tmp="$(mktemp)"
    base64 "$local_path" > "$b64_tmp"
    (
        printf 'cat > %s.b64 <<'"'"'B64EOF'"'"'\n' "$remote_path"
        cat "$b64_tmp"
        printf 'B64EOF\nbase64 -d %s.b64 > %s\nrm %s.b64\nmd5sum %s\nexit\n' \
            "$remote_path" "$remote_path" "$remote_path" "$remote_path"
    ) | ssh -tt -o StrictHostKeyChecking=no -o ConnectTimeout=15 "$POD_TARGET" -i "$SSH_KEY" 2>&1
    rm -f "$b64_tmp"

    local_md5="$(md5sum "$local_path" | awk '{print $1}')"
    echo "Local md5:  $local_md5 (verify this matches the remote md5sum printed above)"
}

echo "=== RunPod Deploy: $POD_TARGET (pod id: $POD_ID) ==="

# --- API key: reuse if we have one for this pod already, else generate ---
if [ -f "$API_KEY_FILE" ]; then
    API_KEY="$(cat "$API_KEY_FILE")"
    echo "Reusing existing API key from $API_KEY_FILE"
else
    API_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
    mkdir -p "$(dirname "$API_KEY_FILE")"
    echo "$API_KEY" > "$API_KEY_FILE"
    chmod 600 "$API_KEY_FILE"
    echo "Generated new API key, saved to $API_KEY_FILE"
fi

# --- Transfer the Modelfile ---
echo "--- Transferring Modelfile ($MODELFILE) ---"
transfer_file "$MODELFILE" "/root/inference_Modelfile"

# --- Transfer the bootstrap script ---
echo "--- Transferring bootstrap script ---"
transfer_file "$BOOTSTRAP_SCRIPT" "/root/runpod_bootstrap_remote.sh"

# --- Run it in the background (survives disconnects), then poll ---
echo "--- Running bootstrap (this can take several minutes for model pulls) ---"
ssh_exec "chmod +x /root/runpod_bootstrap_remote.sh; API_KEY='$API_KEY' BASE_MODEL='$BASE_MODEL' TARGET_MODEL='$TARGET_MODEL' nohup /root/runpod_bootstrap_remote.sh > /root/bootstrap.log 2>&1 & disown; echo BOOTSTRAP_STARTED"

echo "--- Polling for completion (checking every 20s) ---"
for i in $(seq 1 60); do
    sleep 20
    OUTPUT="$(ssh_exec 'tail -5 /root/bootstrap.log 2>/dev/null')"
    echo "[poll $i] $(echo "$OUTPUT" | grep -E 'Bootstrap complete|status=|models' | tail -3)"
    if echo "$OUTPUT" | grep -q "Bootstrap complete"; then
        echo "--- Bootstrap finished ---"
        ssh_exec "cat /root/bootstrap.log"
        break
    fi
done

PROXY_URL="https://${POD_ID}-${PROXY_PORT}.proxy.runpod.net"

echo ""
echo "=== Verifying from this workstation ==="
NOKEY_STATUS="$(curl -s -o /dev/null -w '%{http_code}' "$PROXY_URL/api/tags")"
echo "No-key status (expect 403): $NOKEY_STATUS"
WITHKEY_RESPONSE="$(curl -s -H "X-Api-Key: $API_KEY" "$PROXY_URL/api/tags")"
echo "With-key response: $WITHKEY_RESPONSE"

echo ""
echo "=== Paste into .env or opencode.jsonc ==="
echo "OLLAMA_URL=$PROXY_URL"
echo "OLLAMA_API_KEY=$API_KEY"
