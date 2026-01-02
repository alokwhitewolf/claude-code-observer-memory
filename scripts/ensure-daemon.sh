#!/bin/bash
# Start observer daemon, handle first-time setup in background

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(dirname "$(dirname "$0")")}"
PID_FILE="$PLUGIN_ROOT/.daemon.pid"
LOG_FILE="$PLUGIN_ROOT/daemon.log"
SETUP_DONE="$PLUGIN_ROOT/.setup_complete"
SETUP_LOCK="$PLUGIN_ROOT/.setup_in_progress"
VENV="$PLUGIN_ROOT/venv"

find_python() {
    for p in python3.12 python3.11 python3.10 \
             /opt/homebrew/bin/python3 /usr/local/bin/python3 \
             /usr/bin/python3.12 /usr/bin/python3.11 /usr/bin/python3.10 \
             python3; do
        cmd=$(command -v "$p" 2>/dev/null || echo "$p")
        if [ -x "$cmd" ]; then
            ver=$("$cmd" -c 'import sys; print(sys.version_info[:2] >= (3,10))' 2>/dev/null)
            [ "$ver" = "True" ] && { echo "$cmd"; return 0; }
        fi
    done
    return 1
}

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
    local py="$1"
    (
        [ -f "$SETUP_LOCK" ] && exit 0
        touch "$SETUP_LOCK"
        exec >> "$LOG_FILE" 2>&1

        echo "[Observer] setup using $py"

        [ -d "$VENV" ] || "$py" -m venv "$VENV"

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
    PYTHON=$(find_python)
    if [ -z "$PYTHON" ]; then
        echo "[Observer] python 3.10+ required" >&2
        echo "[Observer] install: brew install python@3.11 (mac) or apt install python3.11 (linux)" >&2
        exit 2
    fi
    echo "[Observer] installing deps (~2-5 min)..." >&2
    setup_bg "$PYTHON"
    exit 0
fi

# start
start_daemon && daemon_running && echo "[Observer] ready" >&2
exit 0
