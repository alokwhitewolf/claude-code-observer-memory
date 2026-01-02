#!/bin/bash
# Wrapper for python hooks - skips if setup incomplete

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(dirname "$(dirname "$0")")}"

[ -f "$PLUGIN_ROOT/.setup_complete" ] || exit 0
[ -f "$PLUGIN_ROOT/venv/bin/python3" ] || exit 0

exec "$PLUGIN_ROOT/venv/bin/python3" "$1"
