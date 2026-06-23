#!/bin/bash
# Start the BNO LLM Assistant (local / development).
#
# Runs a single process (API + RAG on port 9000). RAG runs in-process, so there
# is no separate model server. For production use the systemd service instead
# (see DEPLOYMENT.md and deploy/bnollm.service).

set -uo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

echo -e "${GREEN}Starting BNO LLM Assistant...${NC}"

# --- Prerequisites ---------------------------------------------------------
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}ERROR: Python 3 is not installed.${NC}"
    exit 1
fi

if ! command -v ollama &> /dev/null; then
    echo -e "${RED}ERROR: Ollama is not installed. Get it from https://ollama.com${NC}"
    exit 1
fi

# Activate the project venv if present
if [ -d "venv" ]; then
    # shellcheck disable=SC1091
    source venv/bin/activate
fi

# --- Ensure Ollama is running ----------------------------------------------
OLLAMA_URL=$(python3 -c "import sys; sys.path.insert(0,'.'); import config; print(config.OLLAMA_CONFIG['base_url'])" 2>/dev/null || echo "http://localhost:11434")
if ! curl -s "${OLLAMA_URL}/api/tags" > /dev/null 2>&1; then
    echo -e "${YELLOW}Ollama not reachable at ${OLLAMA_URL}. Trying to start it...${NC}"
    ollama serve > /dev/null 2>&1 &
    for _ in {1..10}; do
        sleep 1
        curl -s "${OLLAMA_URL}/api/tags" > /dev/null 2>&1 && break
    done
    if ! curl -s "${OLLAMA_URL}/api/tags" > /dev/null 2>&1; then
        echo -e "${RED}ERROR: Could not reach Ollama. Start it manually: 'ollama serve'${NC}"
        exit 1
    fi
fi
echo -e "${GREEN}✓ Ollama reachable at ${OLLAMA_URL}${NC}"

# --- Ensure required models are present -------------------------------------
EMBEDDING_MODEL=$(python3 -c "import sys; sys.path.insert(0,'.'); import config; print(config.OLLAMA_CONFIG['embedding_model'])" 2>/dev/null || echo "hf.co/CompendiumLabs/bge-base-en-v1.5-gguf")
LANGUAGE_MODEL=$(python3 -c "import sys; sys.path.insert(0,'.'); import config; print(config.OLLAMA_CONFIG['language_model'])" 2>/dev/null || echo "llama3.2:3b")
MODELS_LIST=$(ollama list 2>/dev/null || echo "")

for MODEL in "$EMBEDDING_MODEL" "$LANGUAGE_MODEL"; do
    if ! echo "$MODELS_LIST" | grep -q "$MODEL"; then
        echo -e "${YELLOW}Pulling missing model: $MODEL ...${NC}"
        ollama pull "$MODEL" || { echo -e "${RED}Failed to pull $MODEL${NC}"; exit 1; }
    fi
done
echo -e "${GREEN}✓ Models available${NC}"

# --- Dependencies ----------------------------------------------------------
if ! python3 -c "import fastapi" 2>/dev/null; then
    echo -e "${YELLOW}Installing Python dependencies...${NC}"
    pip3 install -r requirements.txt || { echo -e "${RED}Failed to install dependencies${NC}"; exit 1; }
fi

# --- Port check ------------------------------------------------------------
API_PORT=$(python3 -c "import sys; sys.path.insert(0,'.'); import config; print(config.API_SERVER_PORT)" 2>/dev/null || echo "9000")
if lsof -Pi :"$API_PORT" -sTCP:LISTEN -t >/dev/null 2>&1; then
    echo -e "${RED}ERROR: Port $API_PORT is already in use.${NC}"
    echo "Stop the other process (try ./scripts/stop.sh) or change API_SERVER_PORT."
    exit 1
fi

# --- Run -------------------------------------------------------------------
export PYTHONPATH="$PROJECT_DIR:${PYTHONPATH:-}"
echo -e "${GREEN}✓ Starting app on http://127.0.0.1:${API_PORT}  (Ctrl+C to stop)${NC}"
exec python3 -m backend.api_server.main
