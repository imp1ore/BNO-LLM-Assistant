#!/bin/bash
# Quick server report — run on the BNO box, paste output to your team/assistant.
# Usage:  ./scripts/server_report.sh

set -uo pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

echo "========== BNO LLM SERVER REPORT =========="
echo "Date: $(date)"
echo "Host: $(hostname)"
echo "Project: $PROJECT_DIR"
echo

echo "--- CPU / RAM / DISK ---"
echo "CPU cores: $(nproc 2>/dev/null || echo '?')"
(lscpu 2>/dev/null | grep "Model name" | sed 's/^[ \t]*//') || true
free -h 2>/dev/null | grep -E "Mem|Swap" || true
df -h ~ 2>/dev/null | tail -1 || true
echo

echo "--- GPU ---"
if command -v nvidia-smi >/dev/null 2>&1; then
    nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader 2>/dev/null || nvidia-smi | head -8
else
    echo "No NVIDIA GPU (CPU-only)"
fi
echo

echo "--- APP ---"
curl -s -m 3 http://127.0.0.1:8000/health 2>/dev/null || curl -s -m 3 http://127.0.0.1:9000/health 2>/dev/null || echo "App not responding on 8000/9000"
systemctl is-active bnollm 2>/dev/null && echo "bnollm service: $(systemctl is-active bnollm)" || echo "bnollm service: unknown"
echo

echo "--- CONFIG (.env) ---"
grep -E "^API_SERVER_PORT=|^OLLAMA_BASE_URL=|^OLLAMA_LANGUAGE_MODEL=|^OLLAMA_EMBEDDING_MODEL=" .env 2>/dev/null || echo "(no .env)"
echo

echo "--- OLLAMA MODELS ---"
if [ -d "venv" ]; then
    OLLAMA_URL=$(venv/bin/python -c "import sys; sys.path.insert(0,'.'); import config; print(config.OLLAMA_CONFIG['base_url'])" 2>/dev/null || echo "http://127.0.0.1:9000")
else
    OLLAMA_URL="http://127.0.0.1:9000"
fi
export OLLAMA_HOST="$OLLAMA_URL"
ollama list 2>/dev/null || echo "Could not reach Ollama at $OLLAMA_URL"
echo

echo "--- QUICK SPEED (chat model, ~15-60s) ---"
CHAT_MODEL=$(venv/bin/python -c "import sys; sys.path.insert(0,'.'); import config; print(config.OLLAMA_CONFIG['language_model'])" 2>/dev/null || echo "llama3.2:3b")
echo "Model: $CHAT_MODEL"
/usr/bin/time -f "Answer time: %e seconds" ollama run "$CHAT_MODEL" "Reply with exactly: OK" 2>/dev/null | tail -3
echo
echo "========== END REPORT =========="
