#!/bin/bash
# Enable Ollama performance settings that only exist as server (daemon) env vars,
# not per-request options: flash attention and a quantized KV cache. Both cut
# memory-bandwidth usage during generation, which is the main bottleneck for
# CPU-only inference - typically a free 15-30% speedup with no quality loss.
#
# Usage (must be run with sudo, since it edits the systemd service):
#     sudo ./scripts/tune_ollama_performance.sh
#
# Safe to re-run.

set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "Run this with sudo: sudo ./scripts/tune_ollama_performance.sh"
    exit 1
fi

OVERRIDE_DIR="/etc/systemd/system/ollama.service.d"
OVERRIDE_FILE="$OVERRIDE_DIR/override.conf"

mkdir -p "$OVERRIDE_DIR"
touch "$OVERRIDE_FILE"

set_env_line() {
    local key="$1"
    local value="$2"
    grep -v "^Environment=\"${key}=" "$OVERRIDE_FILE" > "${OVERRIDE_FILE}.tmp" 2>/dev/null || true
    mv "${OVERRIDE_FILE}.tmp" "$OVERRIDE_FILE"
    echo "Environment=\"${key}=${value}\"" >> "$OVERRIDE_FILE"
}

if ! grep -q '^\[Service\]' "$OVERRIDE_FILE"; then
    sed -i '1i [Service]' "$OVERRIDE_FILE"
fi

echo "Enabling flash attention and quantized KV cache..."
set_env_line "OLLAMA_FLASH_ATTENTION" "1"
set_env_line "OLLAMA_KV_CACHE_TYPE" "q8_0"

echo "Current override:"
sed 's/^/  /' "$OVERRIDE_FILE"

echo "Restarting Ollama..."
systemctl daemon-reload
systemctl restart ollama
sleep 3

if curl -s http://127.0.0.1:9000/api/tags >/dev/null 2>&1 || curl -s http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
    echo "✓ Ollama restarted successfully with the new settings."
else
    echo "WARNING: Ollama did not respond after restart. Check: sudo journalctl -u ollama -n 40 --no-pager"
    exit 1
fi

echo "Done."
