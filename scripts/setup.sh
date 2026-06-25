#!/bin/bash
# One-time setup for the BNO LLM Assistant.
#
# This does everything a fresh machine/server needs:
#   1. Creates the Python virtual environment (venv/)
#   2. Installs all dependencies into it
#   3. Creates .env with a secure, auto-generated SECRET_KEY
#      (and optionally sets your admin password)
#   4. Makes sure Ollama is running and the required models are downloaded
#
# Run it ONCE:
#     ./scripts/setup.sh
#
# Then start the app:
#     ./scripts/start_prod.sh        (manual run)
#   or set up the always-on service: sudo ./scripts/install_service.sh

set -uo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

echo -e "${GREEN}=== BNO LLM Assistant setup ===${NC}"

# --- 1. Python -------------------------------------------------------------
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}ERROR: Python 3 is not installed. Install Python 3.10+ first.${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Python found:${NC} $(python3 --version)"

# --- 2. Virtual environment + dependencies ---------------------------------
if [ ! -d "venv" ]; then
    echo "Creating virtual environment (venv/)..."
    python3 -m venv venv || { echo -e "${RED}Failed to create venv${NC}"; exit 1; }
fi
# shellcheck disable=SC1091
source venv/bin/activate
echo "Installing dependencies (this can take a few minutes the first time)..."
pip install --upgrade pip >/dev/null
pip install -r requirements.txt || { echo -e "${RED}Failed to install dependencies${NC}"; exit 1; }
echo -e "${GREEN}✓ Dependencies installed${NC}"

# --- 3. .env ---------------------------------------------------------------
if [ ! -f ".env" ]; then
    cp .env.example .env
    SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))")

    ADMINPW=""
    if [ -t 0 ]; then
        echo
        read -r -s -p "Choose an admin password (or press Enter to set it later in .env): " ADMINPW
        echo
    fi

    SECRET="$SECRET" ADMINPW="$ADMINPW" python3 - <<'PY'
import os, pathlib
secret = os.environ["SECRET"]
adminpw = os.environ.get("ADMINPW", "")
p = pathlib.Path(".env")
out = []
for line in p.read_text().splitlines():
    if line.startswith("SECRET_KEY="):
        out.append(f"SECRET_KEY={secret}")
    elif line.startswith("ADMIN_PASSWORD=") and adminpw:
        out.append(f"ADMIN_PASSWORD={adminpw}")
    else:
        out.append(line)
p.write_text("\n".join(out) + "\n")
PY
    echo -e "${GREEN}✓ Created .env with a secure SECRET_KEY${NC}"
    if [ -z "$ADMINPW" ]; then
        echo -e "${YELLOW}  NOTE: set ADMIN_PASSWORD in .env before real use (it's currently a placeholder).${NC}"
    fi
else
    echo -e "${YELLOW}✓ .env already exists - leaving it unchanged${NC}"
fi

# --- 4. Ollama + models ----------------------------------------------------
if ! command -v ollama &> /dev/null; then
    echo -e "${YELLOW}WARNING: Ollama is not installed. Install it from https://ollama.com${NC}"
    echo -e "${YELLOW}         then re-run this script to download the models.${NC}"
else
    OLLAMA_URL=$(python3 -c "import sys; sys.path.insert(0,'.'); import config; print(config.OLLAMA_CONFIG['base_url'])" 2>/dev/null || echo "http://localhost:11434")
    if ! curl -s "${OLLAMA_URL}/api/tags" > /dev/null 2>&1; then
        echo "Starting Ollama..."
        ollama serve > /dev/null 2>&1 &
        for _ in {1..10}; do sleep 1; curl -s "${OLLAMA_URL}/api/tags" >/dev/null 2>&1 && break; done
    fi
    if curl -s "${OLLAMA_URL}/api/tags" > /dev/null 2>&1; then
        EMB=$(python3 -c "import sys; sys.path.insert(0,'.'); import config; print(config.OLLAMA_CONFIG['embedding_model'])" 2>/dev/null)
        LANG=$(python3 -c "import sys; sys.path.insert(0,'.'); import config; print(config.OLLAMA_CONFIG['language_model'])" 2>/dev/null)
        LIST=$(ollama list 2>/dev/null || echo "")
        for M in "$EMB" "$LANG"; do
            if [ -n "$M" ] && ! echo "$LIST" | grep -q "$M"; then
                echo "Downloading model: $M ..."
                ollama pull "$M" || echo -e "${YELLOW}Could not pull $M - pull it manually later.${NC}"
            fi
        done
        echo -e "${GREEN}✓ Ollama ready and models available${NC}"
    else
        echo -e "${YELLOW}WARNING: Could not reach Ollama. Start it ('ollama serve') and re-run.${NC}"
    fi
fi

echo
echo -e "${GREEN}=== Setup complete ===${NC}"
echo "Next steps:"
echo "  • Quick manual run:   ./scripts/start_prod.sh"
echo "  • Always-on service:  sudo ./scripts/install_service.sh"
echo "  • Then open:          http://<server-ip>:9000"
