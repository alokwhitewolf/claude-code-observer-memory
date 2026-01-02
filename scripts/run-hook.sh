#!/bin/bash
# Wrapper for python hooks

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(dirname "$(dirname "$0")")}"
VERSION_FILE="$PLUGIN_ROOT/.installed_version"

# check if daemon running from different version - kill it
get_version() {
    grep -o '"version"[[:space:]]*:[[:space:]]*"[^"]*"' "$PLUGIN_ROOT/.claude-plugin/plugin.json" 2>/dev/null | cut -d'"' -f4
}
CURRENT_VER=$(get_version)
INSTALLED_VER=$(cat "$VERSION_FILE" 2>/dev/null)
if [ -n "$CURRENT_VER" ] && [ "$CURRENT_VER" != "$INSTALLED_VER" ]; then
    # kill any observer daemon from our plugin (any version)
    pkill -f "claude-code-observer-memory.*daemon.py" 2>/dev/null
    rm -f "$PLUGIN_ROOT/.setup_complete" "$VERSION_FILE"
fi

# show status if setup incomplete
if [ ! -f "$PLUGIN_ROOT/.setup_complete" ]; then
    if [ -f "$PLUGIN_ROOT/.setup_failed" ]; then
        echo '{"continue":true,"systemMessage":"[observer-memory] setup failed. Check daemon.log"}'
    elif [ -f "$PLUGIN_ROOT/.setup_in_progress" ]; then
        echo '{"continue":true,"systemMessage":"[observer-memory] installing dependencies..."}'
    fi
    exit 0
fi

[ -f "$PLUGIN_ROOT/venv/bin/python3" ] || exit 0

exec "$PLUGIN_ROOT/venv/bin/python3" "$1"
