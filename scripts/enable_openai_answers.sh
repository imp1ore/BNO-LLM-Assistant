#!/bin/bash
# Switch chat answer generation to OpenAI (fast) while keeping embeddings on
# Ollama (so already-indexed documents keep working). See DEPLOYMENT.md
# "Fast chat answers via OpenAI" for the full explanation.
#
# Usage:
#     ./scripts/enable_openai_answers.sh
#
# Requires OPENAI_API_KEY to already be set in .env (run
# ./scripts/set_openai_key.sh first if it isn't).

set -uo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

if [ ! -f ".env" ]; then
    echo -e "${RED}No .env found. Run ./scripts/setup.sh first.${NC}"
    exit 1
fi

if ! grep -q '^OPENAI_API_KEY=.\+' .env 2>/dev/null; then
    echo -e "${RED}No OPENAI_API_KEY set in .env yet.${NC}"
    echo "Run ./scripts/set_openai_key.sh first, then re-run this script."
    exit 1
fi

echo "This sends every chat question + retrieved document context to OpenAI"
echo "(gpt-4o-mini by default) instead of your local Ollama model. Embeddings"
echo "stay on Ollama so already-indexed documents keep working."
echo
read -rp "Continue? [y/N] " CONFIRM
if [[ ! "$CONFIRM" =~ ^[Yy]$ ]]; then
    echo "Aborted - .env not changed."
    exit 0
fi

python3 - <<'PY'
from pathlib import Path

p = Path(".env")
lines = p.read_text().splitlines()
out = []
found = False
for line in lines:
    if line.strip().startswith("ANSWER_PROVIDER="):
        out.append("ANSWER_PROVIDER=openai")
        found = True
    elif line.strip().startswith("EMBEDDING_PROVIDER="):
        # Explicitly drop any EMBEDDING_PROVIDER=openai left over from earlier
        # experiments - it must stay on Ollama or existing documents break.
        continue
    else:
        out.append(line)
if not found:
    out.append("ANSWER_PROVIDER=openai")
p.write_text("\n".join(out) + "\n")
print("done")
PY

echo -e "${GREEN}✓ ANSWER_PROVIDER=openai set in .env (EMBEDDING_PROVIDER left on Ollama)${NC}"
echo

if command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files 2>/dev/null | grep -q '^bnollm\.service'; then
    echo "Restarting bnollm service..."
    if [ "$(id -u)" -eq 0 ]; then
        systemctl restart bnollm
    else
        sudo systemctl restart bnollm
    fi
    sleep 3
    STATE=$(systemctl is-active bnollm 2>/dev/null || echo "unknown")
    if [ "$STATE" = "active" ]; then
        echo -e "${GREEN}✓ bnollm restarted and is active${NC}"
    else
        echo -e "${RED}✗ bnollm is not active (state: $STATE) - showing last 20 log lines:${NC}"
        sudo journalctl -u bnollm -n 20 --no-pager 2>/dev/null || journalctl -u bnollm -n 20 --no-pager 2>/dev/null
    fi
else
    echo -e "${YELLOW}No bnollm systemd service found - restart however you normally run the app.${NC}"
fi

echo
echo "Test it: ask a question in the app and it should answer in a couple of"
echo "seconds instead of 30-60s. If retrieval seems broken (wrong/no answers"
echo "for documents that used to work), run ./scripts/doctor.sh to check for"
echo "the EMBEDDING_PROVIDER mismatch warning."
