#!/bin/bash
# Install or repair Python dependencies for the BNO LLM Assistant.
#
# Use this instead of running "pip install -r requirements.txt" directly.
# It finds a suitable Python, creates/repairs the venv, bootstraps pip, installs
# everything, and verifies the packages the app actually needs (including
# sharepoint-to-text for .doc/.xlsx files).
#
# Usage (from the project folder, after git pull):
#     ./scripts/install_deps.sh
#
# Then restart the app:
#     sudo systemctl restart bnollm

set -uo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

echo "========== BNO LLM ASSISTANT - INSTALL DEPENDENCIES =========="
echo "Project: $PROJECT_DIR"
echo

# --- 1. Find Python 3.10+ ---------------------------------------------------
PYTHON=""
for cand in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$cand" >/dev/null 2>&1 && "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null; then
        PYTHON="$cand"
        break
    fi
done
if [ -z "$PYTHON" ]; then
    echo -e "${RED}ERROR: Python 3.10+ is required but was not found.${NC}"
    echo "Install a newer Python, then re-run this script, e.g.:"
    echo "    sudo dnf install python3.11 python3.11-pip   # RHEL / Rocky / Alma"
    echo "    sudo apt install python3.11 python3.11-venv  # Debian / Ubuntu"
    exit 1
fi
echo -e "${GREEN}✓ Using Python:${NC} $("$PYTHON" --version) ($PYTHON)"

# --- 2. Disk space (pip/chromadb need room) ---------------------------------
AVAIL_KB=$(df -Pk . 2>/dev/null | tail -1 | awk '{print $4}')
if [ -n "${AVAIL_KB:-}" ]; then
    AVAIL_GB=$((AVAIL_KB / 1024 / 1024))
    if [ "$AVAIL_GB" -lt 1 ]; then
        echo -e "${RED}ERROR: Only ${AVAIL_GB}GB free on this disk - pip install will likely fail.${NC}"
        echo "Free up space first (see scripts/relocate_ollama_models.sh if Ollama models are the issue)."
        exit 1
    fi
    echo -e "${GREEN}✓ Disk space OK (${AVAIL_GB}GB free)${NC}"
fi

# --- 3. Virtual environment --------------------------------------------------
if [ ! -d "venv" ]; then
    echo "Creating virtual environment (venv/)..."
    if ! "$PYTHON" -m venv venv; then
        echo -e "${RED}ERROR: Failed to create venv/.${NC}"
        echo "On RHEL/Rocky you may need: sudo dnf install python3.11 python3.11-pip"
        echo "On Debian/Ubuntu:          sudo apt install python3.11-venv"
        exit 1
    fi
    echo -e "${GREEN}✓ Created venv/${NC}"
else
    echo -e "${GREEN}✓ venv/ already exists${NC}"
fi

# shellcheck disable=SC1091
source venv/bin/activate

# --- 4. Bootstrap + upgrade pip (always use python -m pip, never bare pip) ---
echo "Bootstrapping pip inside venv..."
python -m ensurepip --upgrade >/dev/null 2>&1 || true
if ! python -m pip install --upgrade pip setuptools wheel; then
    echo -e "${RED}ERROR: Could not upgrade pip inside venv.${NC}"
    echo "Try removing the broken venv and re-running:"
    echo "    rm -rf venv && ./scripts/install_deps.sh"
    exit 1
fi
echo -e "${GREEN}✓ pip ready:${NC} $(python -m pip --version)"

# --- 5. Quick network check (PyPI) -------------------------------------------
if ! python -m pip index versions pip >/dev/null 2>&1; then
    echo -e "${YELLOW}! Could not reach PyPI - install may fail if this server has no internet.${NC}"
    echo "  If you're behind a proxy, set HTTPS_PROXY in the environment and re-run."
fi

# --- 6. Install requirements -------------------------------------------------
echo
echo "Installing packages from requirements.txt (this can take a few minutes)..."
echo "---"
if ! python -m pip install -r requirements.txt; then
    echo "---"
    echo -e "${RED}ERROR: pip install failed.${NC}"
    echo "Common fixes:"
    echo "  • Free disk space:  df -h ."
    echo "  • Broken venv:      rm -rf venv && ./scripts/install_deps.sh"
    echo "  • No internet:      ask network team to allow outbound HTTPS to pypi.org"
    echo "  • Old OS / no wheels: may need build tools:"
    echo "      sudo dnf install gcc python3.11-devel    # RHEL/Rocky"
    echo "      sudo apt install build-essential python3.11-dev  # Debian/Ubuntu"
    exit 1
fi
echo "---"
echo -e "${GREEN}✓ requirements.txt installed${NC}"

# --- 6b. Ensure the modern SQLite shim on Linux -----------------------------
# ChromaDB needs sqlite3 >= 3.35; older Linux (RHEL 8 / CentOS) ships an older
# one. pysqlite3-binary bundles a modern SQLite the app swaps in at runtime.
# It's in requirements.txt (linux-only), but make sure it's really present -
# a missing one is the exact cause of the "unsupported version of sqlite3" error.
if [ "$(uname -s)" = "Linux" ]; then
    if python -c "import pysqlite3" 2>/dev/null; then
        echo -e "${GREEN}✓ pysqlite3 (modern SQLite for ChromaDB) present${NC}"
    else
        echo -e "${YELLOW}! pysqlite3 not found - installing it (needed for ChromaDB on this OS)...${NC}"
        python -m pip install "pysqlite3-binary>=0.5.0" \
            && echo -e "${GREEN}✓ pysqlite3-binary installed${NC}" \
            || echo -e "${YELLOW}! Could not install pysqlite3-binary - see the sqlite note if the app fails to start.${NC}"
    fi
fi

# --- 7. Verify the packages the app actually imports -------------------------
# IMPORTANT: import chromadb the SAME way the app does - after swapping in the
# modern pysqlite3 SQLite (see backend/shared/vector_db.py). Importing chromadb
# directly triggers its "unsupported sqlite3" RuntimeError on older Linux
# (RHEL 8 etc.) even though the app runs fine, so a naive check gives a false alarm.
echo
echo "Verifying imports (the same way the app loads them)..."
VERIFY_FAILED=0
python - <<'PY' || VERIFY_FAILED=1
import sys

# Mirror the app's SQLite swap so this check matches runtime behavior exactly.
try:
    __import__("pysqlite3")
    sys.modules["sqlite3"] = sys.modules.pop("pysqlite3")
    _sqlite_swapped = True
except ImportError:
    _sqlite_swapped = False

simple_mods = [
    "fastapi", "uvicorn", "ollama", "openai",
    "fitz", "docx", "pptx", "sharepoint2text", "sqlalchemy",
]
missing = []
for mod in simple_mods:
    try:
        __import__(mod)
    except ImportError:
        missing.append(mod)

# chromadb is the one with the sqlite dependency - check it separately so we
# can give a specific, useful message instead of a generic failure.
chroma_error = None
try:
    import chromadb  # noqa: F401
except ImportError:
    missing.append("chromadb")
except Exception as e:  # e.g. RuntimeError: unsupported sqlite3
    chroma_error = str(e)

if missing:
    print("MISSING:", ", ".join(missing))
if chroma_error:
    print("SQLITE_PROBLEM:", chroma_error)
    print("pysqlite3 swap active:", _sqlite_swapped)

if missing or chroma_error:
    raise SystemExit(1)

import sqlite3
print(f"All core imports OK. Using SQLite {sqlite3.sqlite_version} "
      f"({'pysqlite3 bundled' if _sqlite_swapped else 'system'}); "
      "sharepoint2text present for .doc/.xlsx files.")
PY

if [ "$VERIFY_FAILED" -ne 0 ]; then
    echo -e "${RED}ERROR: Some packages failed to import after install.${NC}"
    echo
    echo "If you saw 'SQLITE_PROBLEM ... unsupported version of sqlite3' above,"
    echo "the modern SQLite shim (pysqlite3-binary) isn't installed for this"
    echo "platform. Try installing it explicitly, then re-run this script:"
    echo "    python -m pip install pysqlite3-binary"
    echo
    echo "Your installed packages are NOT deleted - you do not need to remove venv/."
    exit 1
fi
echo -e "${GREEN}✓ Import check passed${NC}"

# --- 8. Restart service if present -------------------------------------------
echo
if command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files 2>/dev/null | grep -q '^bnollm\.service'; then
    echo "Restarting bnollm service so it picks up the new packages..."
    if sudo systemctl restart bnollm; then
        sleep 2
        STATE=$(systemctl is-active bnollm 2>/dev/null || echo "unknown")
        if [ "$STATE" = "active" ]; then
            echo -e "${GREEN}✓ bnollm service restarted and is active${NC}"
        else
            echo -e "${YELLOW}! bnollm restarted but state is: $STATE${NC}"
            echo "  Check logs: sudo journalctl -u bnollm -n 30 --no-pager"
        fi
    else
        echo -e "${YELLOW}! Could not restart bnollm (sudo may be required). Run manually:${NC}"
        echo "    sudo systemctl restart bnollm"
    fi
else
    echo "No bnollm systemd service found - start manually with:"
    echo "    ./scripts/start_prod.sh"
fi

echo
echo -e "${GREEN}=== Dependencies installed successfully ===${NC}"
echo "You can now upload .doc, .xlsx, and all other supported file types."
