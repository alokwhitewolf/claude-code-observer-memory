#!/bin/bash
# Show status on user prompt

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(dirname "$(dirname "$0")")}"

if [ -f "$PLUGIN_ROOT/.setup_failed" ]; then
    echo '{"continue":true,"systemMessage":"[observer-memory] setup failed - check daemon.log"}'
elif [ -f "$PLUGIN_ROOT/.setup_in_progress" ]; then
    echo '{"continue":true,"systemMessage":"[observer-memory] installing dependencies..."}'
elif [ -f "$PLUGIN_ROOT/.setup_just_completed" ]; then
    rm -f "$PLUGIN_ROOT/.setup_just_completed"
    echo '{"continue":true,"systemMessage":"[observer-memory] ready"}'
fi
exit 0
