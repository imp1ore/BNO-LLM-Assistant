#!/bin/bash
# One-stop health check + auto-fix for the BNO LLM Assistant.
#
# Run this any time something seems off (after a git pull, a failed restart,
# a fresh server, etc.) instead of guessing which of the other scripts to run.
# It only fixes things that are unambiguously safe (missing deps, missing
# models, missing .env) - it never touches an already-working config or
# passwords. Everything else is reported so you know exactly what to fix.
#
# Usage:
#     ./scripts/doctor.sh

set -uo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
ISSUES=0
note_issue() { ISSUES=$((ISSUES + 1)); echo -e "${RED}✗ $1${NC}"; }
note_warn()  { echo -e "${YELLOW}! $1${NC}"; }
note_ok()    { echo -e "${GREEN}✓ $1${NC}"; }

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

echo "========== BNO LLM ASSISTANT - DOCTOR =========="
echo "Project: $PROJECT_DIR"
echo

# --- If the systemd service exists and isn't healthy, show why FIRST -------
# This is almost always the most useful thing to see, so it goes before the
# slower checks below.
if command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files 2>/dev/null | grep -q '^bnollm\.service'; then
    STATE=$(systemctl is-active bnollm 2>/dev/null || echo "unknown")
    if [ "$STATE" != "active" ]; then
        note_issue "systemd service 'bnollm' is not active (state: $STATE)"
        echo "--- Last 30 log lines (sudo journalctl -u bnollm -n 30) ---"
        sudo journalctl -u bnollm -n 30 --no-pager 2>/dev/null || journalctl -u bnollm -n 30 --no-pager 2>/dev/null || echo "  (need sudo to read the journal - run: sudo journalctl -u bnollm -n 50 --no-pager)"
        echo "-------------------------------------------------------------"
    else
        note_ok "systemd service 'bnollm' is active"
    fi
    echo
fi

# --- 1. Python version -------------------------------------------------------
PYTHON=""
for cand in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$cand" >/dev/null 2>&1 && "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null; then
        PYTHON="$cand"; break
    fi
done
if [ -z "$PYTHON" ]; then
    note_issue "No Python 3.10+ found. Install one (e.g. 'sudo dnf install python3.11')."
else
    note_ok "Python: $("$PYTHON" --version)"
fi

# --- 2. Virtual environment + dependencies ----------------------------------
if [ ! -d "venv" ]; then
    note_warn "venv/ missing - creating it..."
    "$PYTHON" -m venv venv && note_ok "Created venv/" || note_issue "Failed to create venv/"
fi
if [ -d "venv" ]; then
    # shellcheck disable=SC1091
    source venv/bin/activate
    MISSING_DEPS=0
    for mod in fastapi ollama openai fitz sqlalchemy chromadb; do
        python -c "import $mod" 2>/dev/null || MISSING_DEPS=1
    done
    if [ "$MISSING_DEPS" -eq 1 ]; then
        note_warn "Some Python dependencies are missing - installing from requirements.txt..."
        python -m pip install -q -r requirements.txt && note_ok "Dependencies installed" \
            || note_issue "pip install failed - check disk space and network access"
    else
        note_ok "Python dependencies present"
    fi
fi

# --- 3. .env -----------------------------------------------------------------
if [ ! -f ".env" ]; then
    note_warn ".env missing - creating from .env.example with a fresh SECRET_KEY..."
    cp .env.example .env
    SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))")
    SECRET="$SECRET" python3 - <<'PY'
import os, pathlib
secret = os.environ["SECRET"]
p = pathlib.Path(".env")
out = [f"SECRET_KEY={secret}" if line.startswith("SECRET_KEY=") else line for line in p.read_text().splitlines()]
p.write_text("\n".join(out) + "\n")
PY
    note_ok ".env created - set ADMIN_PASSWORD before real use"
else
    note_ok ".env exists"
    if grep -qE '^SECRET_KEY=(change-me|verysecretivekey200)?$' .env 2>/dev/null || ! grep -q '^SECRET_KEY=' .env; then
        note_issue "SECRET_KEY is missing or still a placeholder in .env - login tokens are forgeable. Run: python3 -c \"import secrets; print(secrets.token_urlsafe(48))\" and set SECRET_KEY."
    fi
    if grep -qE '^ADMIN_PASSWORD=(admin|change-me)?$' .env 2>/dev/null; then
        note_warn "ADMIN_PASSWORD is still the default - change it (python scripts/reset_admin_password.py)."
    fi
    # Whitespace check for OPENAI_API_KEY - the #1 cause of a false 401.
    OPENAI_LINE=$(grep '^OPENAI_API_KEY=' .env 2>/dev/null | head -1)
    if [ -n "$OPENAI_LINE" ]; then
        RAW_VAL="${OPENAI_LINE#OPENAI_API_KEY=}"
        STRIPPED_VAL=$(printf '%s' "$RAW_VAL" | tr -d '[:space:]')
        if [ "$RAW_VAL" != "$STRIPPED_VAL" ]; then
            note_issue "OPENAI_API_KEY in .env has leading/trailing whitespace - re-run ./scripts/set_openai_key.sh to fix."
        elif [ -n "$STRIPPED_VAL" ]; then
            note_ok "OPENAI_API_KEY is set (${#STRIPPED_VAL} chars, no whitespace issues)"
        fi
    fi
fi

# --- 4. Disk space -----------------------------------------------------------
AVAIL_KB=$(df -Pk . 2>/dev/null | tail -1 | awk '{print $4}')
if [ -n "${AVAIL_KB:-}" ]; then
    AVAIL_GB=$((AVAIL_KB / 1024 / 1024))
    if [ "$AVAIL_GB" -lt 2 ]; then
        note_issue "Only ${AVAIL_GB}GB free on this disk - indexing/model pulls will likely fail. Free up space or see scripts/relocate_ollama_models.sh."
    else
        note_ok "Disk space OK (${AVAIL_GB}GB free)"
    fi
fi

# --- 5. Ollama + models -------------------------------------------------------
if [ -d "venv" ]; then
    OLLAMA_URL=$(python3 -c "import sys; sys.path.insert(0,'.'); import config; print(config.OLLAMA_CONFIG['base_url'])" 2>/dev/null || echo "http://localhost:11434")
    EMB=$(python3 -c "import sys; sys.path.insert(0,'.'); import config; print(config.OLLAMA_CONFIG['embedding_model'])" 2>/dev/null)
    LANG=$(python3 -c "import sys; sys.path.insert(0,'.'); import config; print(config.OLLAMA_CONFIG['language_model'])" 2>/dev/null)

    if curl -s -m 5 "${OLLAMA_URL}/api/tags" > /dev/null 2>&1; then
        note_ok "Ollama reachable at ${OLLAMA_URL}"
        LIST=$(OLLAMA_HOST="$OLLAMA_URL" ollama list 2>/dev/null || echo "")
        for M in "$EMB" "$LANG"; do
            if [ -n "$M" ] && ! echo "$LIST" | grep -q "$M"; then
                note_warn "Model missing: $M - pulling it now (this can take a while)..."
                OLLAMA_HOST="$OLLAMA_URL" ollama pull "$M" && note_ok "Pulled $M" || note_issue "Failed to pull $M"
            fi
        done
        [ -n "$EMB" ] && echo "$LIST" | grep -q "$EMB" && note_ok "Embedding model available: $EMB"
        [ -n "$LANG" ] && echo "$LIST" | grep -q "$LANG" && note_ok "Language model available: $LANG"
    else
        note_issue "Ollama not reachable at ${OLLAMA_URL} - check: sudo systemctl status ollama"
    fi
fi

# --- 6. Port conflict ---------------------------------------------------------
if [ -d "venv" ]; then
    API_PORT=$(python3 -c "import sys; sys.path.insert(0,'.'); import config; print(config.API_SERVER_PORT)" 2>/dev/null || echo "9000")
    OWNER_PID=$(lsof -Pi :"$API_PORT" -sTCP:LISTEN -t 2>/dev/null || true)
    if [ -n "$OWNER_PID" ]; then
        OWNER_CMD=$(ps -p "$OWNER_PID" -o comm= 2>/dev/null || echo "unknown")
        note_warn "Port $API_PORT is already in use by PID $OWNER_PID ($OWNER_CMD). That's fine if it's bnollm itself, otherwise change API_SERVER_PORT in .env."
    else
        note_ok "Port $API_PORT is free"
    fi
fi

# --- 7. OpenAI connectivity (only if a key is configured) --------------------
if [ -d "venv" ]; then
    OPENAI_KEY_VAL=$(grep '^OPENAI_API_KEY=' .env 2>/dev/null | head -1 | cut -d'=' -f2- | tr -d '[:space:]')
    if [ -n "$OPENAI_KEY_VAL" ]; then
        HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 \
            https://api.openai.com/v1/models -H "Authorization: Bearer $OPENAI_KEY_VAL" 2>/dev/null || echo "CONN_FAIL")
        case "$HTTP_CODE" in
            200) note_ok "OpenAI API reachable and key is valid" ;;
            401|403) note_issue "OpenAI API reachable but key was rejected (HTTP $HTTP_CODE) - re-run ./scripts/set_openai_key.sh" ;;
            CONN_FAIL|000) note_issue "Cannot reach OpenAI's API from this server (network/firewall) - ENABLE_VISION_EXTRACTION will not work" ;;
            *) note_warn "Unexpected HTTP $HTTP_CODE from OpenAI - network works, but check account status" ;;
        esac
        unset OPENAI_KEY_VAL
    fi
fi

echo
if [ "$ISSUES" -eq 0 ]; then
    echo -e "${GREEN}=== All checks passed ===${NC}"
else
    echo -e "${RED}=== $ISSUES issue(s) found - see ✗ lines above ===${NC}"
fi
