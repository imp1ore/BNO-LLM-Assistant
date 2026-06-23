#!/bin/bash
# Production-style start for the BNO LLM Assistant.
#
# Runs the single app process (port 9000); the RAG engine runs in-process.
# Use this for a manual run; prefer the systemd service (deploy/bnollm.service)
# for a real always-on deployment.
#
# Usage:  ./scripts/start_prod.sh

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

# Use the project venv if present
if [ -d "venv" ]; then
    # shellcheck disable=SC1091
    source venv/bin/activate
fi

# Warn (don't fail) if .env is missing - the app still runs on defaults
if [ ! -f ".env" ]; then
    echo -e "${YELLOW}WARNING: no .env found. Copy .env.example to .env and set SECRET_KEY/ADMIN_PASSWORD before real use.${NC}"
fi

# Check Ollama is reachable (read base url from config; fall back to default)
OLLAMA_URL=$(python3 -c "import sys; sys.path.insert(0,'.'); import config; print(config.OLLAMA_CONFIG['base_url'])" 2>/dev/null || echo "http://localhost:11434")
if ! curl -s "${OLLAMA_URL}/api/tags" > /dev/null 2>&1; then
    echo -e "${RED}ERROR: Ollama is not reachable at ${OLLAMA_URL}${NC}"
    echo "Start it first (e.g. 'sudo systemctl start ollama' or 'ollama serve &'),"
    echo "and make sure OLLAMA_BASE_URL in .env matches its port."
    exit 1
fi
echo -e "${GREEN}✓ Ollama reachable at ${OLLAMA_URL}${NC}"

export PYTHONPATH="$PROJECT_DIR:${PYTHONPATH:-}"

echo -e "${GREEN}Starting API server...${NC}"
exec python3 -m backend.api_server.main
