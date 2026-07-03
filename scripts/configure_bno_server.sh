#!/bin/bash
# Apply BNO-server settings when Ollama is already on port 9000.
#
# On this environment the app must NOT use 9000 (Ollama owns it). This sets:
#   API_SERVER_PORT=8000
#   OLLAMA_BASE_URL=http://localhost:9000
#   API_SERVER_HOST=0.0.0.0
#
# Usage (after git pull):
#     ./scripts/configure_bno_server.sh
#     sudo systemctl restart bnollm
#     curl localhost:8000/health

set -euo pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

if [ ! -f ".env" ]; then
    echo "No .env found. Run ./scripts/setup.sh first."
    exit 1
fi

python3 - <<'PY'
from pathlib import Path

updates = {
    "API_SERVER_HOST": "0.0.0.0",
    "API_SERVER_PORT": "8000",
    "OLLAMA_BASE_URL": "http://localhost:9000",
}

p = Path(".env")
lines = p.read_text().splitlines()
seen = set()
out = []

for line in lines:
    if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
        out.append(line)
        continue
    key = line.split("=", 1)[0].strip()
    if key in updates:
        out.append(f"{key}={updates[key]}")
        seen.add(key)
    else:
        out.append(line)

for key, val in updates.items():
    if key not in seen:
        out.append(f"{key}={val}")

p.write_text("\n".join(out) + "\n")
print("✓ .env updated: app on port 8000, Ollama at http://localhost:9000")
PY
