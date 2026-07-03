#!/bin/bash
# Download the two Ollama models the app needs (embedding + chat).
# Uses OLLAMA_BASE_URL from .env (e.g. http://localhost:9000 on BNO server).
#
# Usage:  ./scripts/pull_models.sh

set -euo pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

if [ -d "venv" ]; then
    # shellcheck disable=SC1091
    source venv/bin/activate
fi

OLLAMA_URL=$(python3 -c "import sys; sys.path.insert(0,'.'); import config; print(config.OLLAMA_CONFIG['base_url'])" 2>/dev/null || echo "http://localhost:11434")
EMB=$(python3 -c "import sys; sys.path.insert(0,'.'); import config; print(config.OLLAMA_CONFIG['embedding_model'])" 2>/dev/null)
LANG=$(python3 -c "import sys; sys.path.insert(0,'.'); import config; print(config.OLLAMA_CONFIG['language_model'])" 2>/dev/null)

echo "Ollama at: $OLLAMA_URL"
echo "Pulling models (this can take a few minutes)..."

python3 - <<PY
import config, ollama
client = ollama.Client(host=config.OLLAMA_CONFIG["base_url"])
for name in [config.OLLAMA_CONFIG["embedding_model"], config.OLLAMA_CONFIG["language_model"]]:
    print(f"\n--- {name} ---")
    client.pull(name)
    print(f"✓ {name}")
print("\nDone. Run: OLLAMA_HOST=$OLLAMA_URL ollama list  (optional check)")
PY

echo "✓ Models ready"
