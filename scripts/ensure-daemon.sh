#!/bin/bash
# Start observer daemon, handle first-time setup in background

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(dirname "$(dirname "$0")")}"
PID_FILE="$PLUGIN_ROOT/.daemon.pid"
LOG_FILE="$PLUGIN_ROOT/daemon.log"
SETUP_DONE="$PLUGIN_ROOT/.setup_complete"
SETUP_LOCK="$PLUGIN_ROOT/.setup_in_progress"
VENV="$PLUGIN_ROOT/venv"

daemon_running() {
    curl -s --max-time 1 "http://127.0.0.1:7888/status" > /dev/null 2>&1
}

start_daemon() {
    [ -f "$VENV/bin/python3" ] || return 1
    cd "$PLUGIN_ROOT"
    nohup "$VENV/bin/python3" daemon.py >> "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    sleep 1
}

setup_bg() {
    (
        [ -f "$SETUP_LOCK" ] && exit 0
        touch "$SETUP_LOCK"
        exec >> "$LOG_FILE" 2>&1

        echo "[Observer] first-time setup..."

        # find python
        PYTHON=$(command -v python3 || command -v python)
        [ -z "$PYTHON" ] && { echo "[Observer] python not found"; rm -f "$SETUP_LOCK"; exit 1; }

        # venv
        [ -d "$VENV" ] || $PYTHON -m venv "$VENV"

        # deps
        source "$VENV/bin/activate"
        pip install --upgrade pip -q
        [ -f "$PLUGIN_ROOT/requirements.txt" ] && pip install -r "$PLUGIN_ROOT/requirements.txt" -q
        deactivate

        touch "$SETUP_DONE"
        rm -f "$SETUP_LOCK"
        echo "[Observer] setup complete"

        "$VENV/bin/python3" "$PLUGIN_ROOT/daemon.py" &
        echo $! > "$PID_FILE"
    ) &
}

# main
daemon_running && exit 0

# cleanup stale pid
if [ -f "$PID_FILE" ]; then
    pid=$(cat "$PID_FILE" 2>/dev/null)
    [ -n "$pid" ] && ! kill -0 "$pid" 2>/dev/null && rm -f "$PID_FILE"
fi

# first time?
if [ ! -f "$SETUP_DONE" ]; then
    if [ -f "$SETUP_LOCK" ]; then
        echo "[Observer] setup in progress..." >&2
        exit 0
    fi
    echo "[Observer] installing deps (~2-5 min)..." >&2
    setup_bg
    exit 0
fi

# start
start_daemon && daemon_running && echo "[Observer] ready" >&2
exit 0
