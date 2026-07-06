#!/bin/bash
# Interactively set OPENAI_API_KEY in .env without ever printing it to the
# screen, shell history, or git. Run this directly on the server (via
# PuTTY/SSH) - never paste a real key into chat or a git commit.
#
# Usage:
#     ./scripts/set_openai_key.sh
#
# What it does:
#   1. Prompts for the key with input hidden (like a password prompt).
#   2. Writes/updates OPENAI_API_KEY in .env (adds the line if missing).
#   3. Offers to test connectivity to OpenAI's API right away.
#   4. Offers to turn on image/diagram vision extraction (ENABLE_VISION_EXTRACTION).

set -euo pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

if [ ! -f ".env" ]; then
    echo "No .env found. Run ./scripts/setup.sh first."
    exit 1
fi

echo "Paste your OpenAI API key below. Input is hidden and will NOT be shown"
echo "on screen, saved to shell history, or sent anywhere except into .env."
echo -n "OpenAI API key: "
read -rs OPENAI_KEY_RAW
echo
echo

# Trim leading/trailing whitespace (paste artifacts are the #1 cause of
# "network is fine but key rejected" - a real OpenAI key never has spaces).
OPENAI_KEY="$(printf '%s' "$OPENAI_KEY_RAW" | tr -d '[:space:]')"
unset OPENAI_KEY_RAW

if [ -z "$OPENAI_KEY" ]; then
    echo "No key entered - aborting, .env not changed."
    exit 1
fi

if [ "${#OPENAI_KEY}" -lt 40 ]; then
    echo "Warning: that key looks unusually short (${#OPENAI_KEY} chars) for an OpenAI key."
    echo "It may have been cut off during paste."
    read -rp "Continue anyway? [y/N] " CONFIRM_LEN
    if [[ ! "$CONFIRM_LEN" =~ ^[Yy]$ ]]; then
        echo "Aborted - .env not changed."
        exit 1
    fi
fi

if [[ "$OPENAI_KEY" != sk-* ]]; then
    echo "Warning: that doesn't look like a typical OpenAI key (expected it to start with 'sk-')."
    read -rp "Continue anyway? [y/N] " CONFIRM
    if [[ ! "$CONFIRM" =~ ^[Yy]$ ]]; then
        echo "Aborted - .env not changed."
        exit 1
    fi
fi

# Pass the key to Python via an environment variable (not a CLI arg or heredoc
# interpolation) so it never appears in `ps`, logs, or the script's own output.
OPENAI_KEY="$OPENAI_KEY" python3 - <<'PY'
import os
from pathlib import Path

key = os.environ["OPENAI_KEY"]
p = Path(".env")
lines = p.read_text().splitlines()
out = []
found = False

for line in lines:
    if line.strip().startswith("OPENAI_API_KEY="):
        out.append(f"OPENAI_API_KEY={key}")
        found = True
    else:
        out.append(line)

if not found:
    out.append(f"OPENAI_API_KEY={key}")

p.write_text("\n".join(out) + "\n")
print("done")
PY

unset OPENAI_KEY
echo "✓ OPENAI_API_KEY saved to .env (not printed, not committed - .env is gitignored)."
echo

read -rp "Test connectivity to OpenAI's API right now? [Y/n] " TEST_NOW
if [[ ! "$TEST_NOW" =~ ^[Nn]$ ]]; then
    echo "Testing..."
    KEY_FOR_TEST=$(grep '^OPENAI_API_KEY=' .env | head -1 | cut -d'=' -f2-)
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 15 \
        https://api.openai.com/v1/models \
        -H "Authorization: Bearer $KEY_FOR_TEST" || echo "CONN_FAIL")
    unset KEY_FOR_TEST

    case "$HTTP_CODE" in
        200)
            echo "✓ Success (HTTP 200) - the server can reach OpenAI and the key works."
            ;;
        401)
            echo "✗ HTTP 401 - network is fine, but the key was rejected (invalid/revoked)."
            ;;
        403)
            echo "✗ HTTP 403 - request reached OpenAI but was forbidden (check account/billing status)."
            ;;
        CONN_FAIL|000)
            echo "✗ Could not connect at all - this server likely has no outbound internet"
            echo "  access to api.openai.com (firewall/proxy blocking it). Ask your network"
            echo "  team to allowlist api.openai.com before enabling OpenAI-backed features."
            ;;
        *)
            echo "? Got HTTP $HTTP_CODE - unexpected, but the network connection itself succeeded."
            ;;
    esac
fi

echo
read -rp "Enable image/diagram vision extraction now (ENABLE_VISION_EXTRACTION=true)? [y/N] " ENABLE_VISION
if [[ "$ENABLE_VISION" =~ ^[Yy]$ ]]; then
    python3 - <<'PY'
from pathlib import Path

p = Path(".env")
lines = p.read_text().splitlines()
out = []
found = False
for line in lines:
    if line.strip().startswith("ENABLE_VISION_EXTRACTION="):
        out.append("ENABLE_VISION_EXTRACTION=true")
        found = True
    else:
        out.append(line)
if not found:
    out.append("ENABLE_VISION_EXTRACTION=true")
p.write_text("\n".join(out) + "\n")
print("✓ ENABLE_VISION_EXTRACTION=true set in .env")
PY
    echo "Remember: this sends embedded document images to OpenAI. Confirm that's"
    echo "cleared with BNO's data policy before uploading real/sensitive documents."
fi

echo
echo "Next step: sudo systemctl restart bnollm   (to pick up the new .env)"
