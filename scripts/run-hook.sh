#!/bin/bash
# Wrapper for python hooks

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(dirname "$(dirname "$0")")}"

# show status if setup incomplete
if [ ! -f "$PLUGIN_ROOT/.setup_complete" ]; then
    if [ -f "$PLUGIN_ROOT/.setup_failed" ]; then
        echo '{"continue":true,"systemMessage":"[Observer] setup failed. Check daemon.log"}'
    elif [ -f "$PLUGIN_ROOT/.setup_in_progress" ]; then
        echo '{"continue":true,"systemMessage":"[Observer] installing dependencies..."}'
    fi
    exit 0
fi

[ -f "$PLUGIN_ROOT/venv/bin/python3" ] || exit 0

exec "$PLUGIN_ROOT/venv/bin/python3" "$1"
