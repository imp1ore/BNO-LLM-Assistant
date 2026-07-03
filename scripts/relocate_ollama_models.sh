#!/bin/bash
# Move the system Ollama service's model storage off a full root disk onto a
# larger volume (a directory next to this project), then re-download the
# app's models there. Fixes "no space left on device" when Ollama's models
# live under /usr/share/ollama/.ollama on a full root filesystem.
#
# Usage (must be run with sudo):
#     sudo ./scripts/relocate_ollama_models.sh
#
# Safe to re-run.

set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "Run this with sudo: sudo ./scripts/relocate_ollama_models.sh"
    exit 1
fi

RUN_USER="${SUDO_USER:-$(whoami)}"
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

OLD_MODELS_DIR="/usr/share/ollama/.ollama"
TARGET_DIR="$(dirname "$PROJECT_DIR")/ollama-models"
OVERRIDE_DIR="/etc/systemd/system/ollama.service.d"
OVERRIDE_FILE="$OVERRIDE_DIR/override.conf"

echo "Project dir:   $PROJECT_DIR"
echo "New model dir: $TARGET_DIR"
echo

echo "1) Creating new model directory..."
mkdir -p "$TARGET_DIR"
if [ -d "$OLD_MODELS_DIR" ]; then
    chown --reference="$OLD_MODELS_DIR" "$TARGET_DIR"
fi
echo "   ✓ $TARGET_DIR ready"

echo "2) Updating Ollama service override..."
mkdir -p "$OVERRIDE_DIR"
touch "$OVERRIDE_FILE"
# Drop any previous OLLAMA_MODELS line so re-running this script doesn't duplicate it
grep -v '^Environment="OLLAMA_MODELS=' "$OVERRIDE_FILE" > "${OVERRIDE_FILE}.tmp" 2>/dev/null || true
mv "${OVERRIDE_FILE}.tmp" "$OVERRIDE_FILE"
if ! grep -q '^\[Service\]' "$OVERRIDE_FILE"; then
    sed -i '1i [Service]' "$OVERRIDE_FILE"
fi
echo "Environment=\"OLLAMA_MODELS=$TARGET_DIR\"" >> "$OVERRIDE_FILE"
echo "   ✓ Set OLLAMA_MODELS=$TARGET_DIR"
echo "   Current override:"
sed 's/^/     /' "$OVERRIDE_FILE"

echo "3) Restarting Ollama..."
systemctl daemon-reload
systemctl restart ollama
sleep 3

echo "4) Checking Ollama is reachable..."
OLLAMA_URL=$(sudo -u "$RUN_USER" bash -c "cd '$PROJECT_DIR' && [ -f venv/bin/python ] && venv/bin/python -c \"import sys; sys.path.insert(0,'.'); import config; print(config.OLLAMA_CONFIG['base_url'])\"" 2>/dev/null || echo "http://127.0.0.1:9000")
ok=0
for _ in $(seq 1 10); do
    if curl -s "$OLLAMA_URL/api/tags" >/dev/null 2>&1; then ok=1; break; fi
    sleep 1
done
if [ "$ok" -eq 1 ]; then
    echo "   ✓ Ollama reachable at $OLLAMA_URL"
else
    echo "   ERROR: Ollama not responding at $OLLAMA_URL"
    echo "   Check: sudo journalctl -u ollama -n 40 --no-pager"
    exit 1
fi

echo "5) Re-downloading models into the new location (as $RUN_USER, can take a few minutes)..."
sudo -u "$RUN_USER" bash -c "cd '$PROJECT_DIR' && ./scripts/pull_models.sh"

echo "6) Restarting the app..."
systemctl restart bnollm
sleep 5
APP_PORT=$(sudo -u "$RUN_USER" bash -c "cd '$PROJECT_DIR' && [ -f venv/bin/python ] && venv/bin/python -c \"import sys; sys.path.insert(0,'.'); import config; print(config.API_SERVER_PORT)\"" 2>/dev/null || echo "8000")
echo "   Health check (port $APP_PORT):"
curl -s "http://127.0.0.1:$APP_PORT/health" || echo "   (no response yet - give it a few more seconds and re-run: curl localhost:$APP_PORT/health)"
echo
echo

echo "=== Done ==="
echo "Models now stored at: $TARGET_DIR"
echo "Note: old models still occupy space at $OLD_MODELS_DIR on the full root disk."
echo "That's a separate cleanup - check with your infra contact before deleting anything there."
