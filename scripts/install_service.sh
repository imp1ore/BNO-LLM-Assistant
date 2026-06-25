#!/bin/bash
# Install the BNO LLM Assistant as an always-on systemd service.
#
# It auto-fills the project path and the user for THIS machine, so you don't have
# to edit anything by hand. Run it with sudo on the server:
#
#     sudo ./scripts/install_service.sh
#
# After this, the app starts on boot and restarts automatically if it crashes.
# Manage it with:
#     sudo systemctl status bnollm
#     sudo systemctl restart bnollm
#     sudo journalctl -u bnollm -f

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# The user the service should run as (the one who checked out the project,
# not root, when possible).
RUN_USER="${SUDO_USER:-$(whoami)}"
PY_BIN="$PROJECT_DIR/venv/bin/python"

if [ ! -x "$PY_BIN" ]; then
    echo -e "${RED}ERROR: $PY_BIN not found. Run ./scripts/setup.sh first.${NC}"
    exit 1
fi
if [ ! -f "$PROJECT_DIR/.env" ]; then
    echo -e "${YELLOW}WARNING: no .env found. Run ./scripts/setup.sh first so the service has its config.${NC}"
fi

UNIT_CONTENT="[Unit]
Description=BNO LLM Assistant (API + RAG)
After=network-online.target ollama.service
Wants=network-online.target

[Service]
Type=simple
User=${RUN_USER}
WorkingDirectory=${PROJECT_DIR}
ExecStart=${PY_BIN} -m backend.api_server.main
EnvironmentFile=${PROJECT_DIR}/.env
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
"

if [ "$(id -u)" -ne 0 ]; then
    OUT="/tmp/bnollm.service"
    echo "$UNIT_CONTENT" > "$OUT"
    echo -e "${YELLOW}Not running as root - wrote the generated unit to ${OUT}${NC}"
    echo "Install it with:"
    echo "    sudo cp ${OUT} /etc/systemd/system/bnollm.service"
    echo "    sudo systemctl daemon-reload && sudo systemctl enable --now bnollm"
    exit 0
fi

echo "$UNIT_CONTENT" > /etc/systemd/system/bnollm.service
echo -e "${GREEN}✓ Wrote /etc/systemd/system/bnollm.service${NC}"
echo "   User=${RUN_USER}"
echo "   WorkingDirectory=${PROJECT_DIR}"

systemctl daemon-reload
systemctl enable --now bnollm
echo -e "${GREEN}✓ Service enabled and started${NC}"
echo
systemctl status bnollm --no-pager || true
