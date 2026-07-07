#!/bin/bash
# Watch document indexing progress live.
#
# Shows, in real time, each document as it moves through the pipeline:
#   START -> extracting text -> chunks created -> embedded X/Y -> indexed (or failed)
#
# Useful when a big upload sits on "Processing" and you want to confirm it's
# actually making progress (not stuck).
#
# Usage:
#     ./scripts/watch_indexing.sh
#
# Press Ctrl+C to stop watching (this does NOT stop the app).

set -uo pipefail

# Highlight helper - color the important lines so progress is easy to spot.
colorize() {
    while IFS= read -r line; do
        case "$line" in
            *"[INDEX][ERROR]"*|*"failed"*) printf '\033[0;31m%s\033[0m\n' "$line" ;;   # red
            *"indexed:"*)                  printf '\033[0;32m%s\033[0m\n' "$line" ;;   # green
            *"[INDEX]"*|*"[VISION]"*)      printf '\033[1;33m%s\033[0m\n' "$line" ;;   # yellow
            *)                             printf '%s\n' "$line" ;;
        esac
    done
}

echo "Watching indexing activity (Ctrl+C to stop)..."
echo "Look for: START -> extracting -> chunks -> embedded X/Y -> indexed"
echo "-----------------------------------------------------------------------"

# Prefer the systemd journal (production). Fall back to a plain hint otherwise.
if command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files 2>/dev/null | grep -q '^bnollm\.service'; then
    # --no-hostname keeps lines short; grep keeps only the pipeline lines.
    if ! sudo journalctl -u bnollm -f --no-hostname 2>/dev/null | grep --line-buffered -E '\[INDEX\]|\[VISION\]|\[DEBUG\] Document' | colorize; then
        echo
        echo "Could not read the journal (need sudo?). Try:"
        echo "    sudo journalctl -u bnollm -f | grep -E '\\[INDEX\\]|\\[VISION\\]'"
        exit 1
    fi
else
    echo "No bnollm systemd service found."
    echo "If you started the app manually, watch its terminal output instead,"
    echo "or look for [INDEX] lines there."
    exit 1
fi
