#!/bin/bash
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Installing claude-observer..."

# venv
[ -d "$DIR/venv" ] || python3 -m venv "$DIR/venv"
source "$DIR/venv/bin/activate"
pip install -q --upgrade pip
pip install -q -r "$DIR/requirements.txt"
deactivate

# permissions
chmod +x "$DIR/scripts/"*.sh 2>/dev/null || true

echo ""
echo "Done! Usage:"
echo ""
echo "  claude --plugin-dir $DIR"
echo ""
echo "Or add to ~/.claude/settings.json:"
echo "  {\"plugins\": [\"$DIR\"]}"
echo ""
