#!/bin/bash
# Start observer daemon, handle first-time setup in background

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(dirname "$(dirname "$0")")}"
PID_FILE="$PLUGIN_ROOT/.daemon.pid"
LOG_FILE="$PLUGIN_ROOT/daemon.log"
SETUP_DONE="$PLUGIN_ROOT/.setup_complete"
SETUP_LOCK="$PLUGIN_ROOT/.setup_in_progress"
SETUP_FAILED="$PLUGIN_ROOT/.setup_failed"
VERSION_FILE="$PLUGIN_ROOT/.installed_version"
VENV="$PLUGIN_ROOT/venv"

get_version() {
    grep -o '"version"[[:space:]]*:[[:space:]]*"[^"]*"' "$PLUGIN_ROOT/.claude-plugin/plugin.json" 2>/dev/null | cut -d'"' -f4
}

stop_daemon() {
    if [ -f "$PID_FILE" ]; then
        pid=$(cat "$PID_FILE" 2>/dev/null)
        [ -n "$pid" ] && kill "$pid" 2>/dev/null
        rm -f "$PID_FILE"
    fi
    pkill -f "claude-code-observer-memory.*daemon.py" 2>/dev/null
}

reset_setup() {
    stop_daemon
    rm -f "$SETUP_DONE" "$SETUP_LOCK" "$SETUP_FAILED" "$VERSION_FILE"
    rm -rf "$VENV"
}

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
    local ver="$2"
    (
        [ -f "$SETUP_LOCK" ] && exit 0
        touch "$SETUP_LOCK"
        rm -f "$SETUP_FAILED"
        exec >> "$LOG_FILE" 2>&1

        echo "[Observer] setup using $py"

        if ! "$py" -m venv "$VENV" 2>&1; then
            echo "venv creation failed" > "$SETUP_FAILED"
            rm -f "$SETUP_LOCK"
            exit 1
        fi

        source "$VENV/bin/activate"
        pip install --upgrade pip -q
        if ! pip install -r "$PLUGIN_ROOT/requirements.txt" 2>&1; then
            echo "pip install failed" > "$SETUP_FAILED"
            rm -f "$SETUP_LOCK"
            deactivate
            exit 1
        fi
        deactivate

        touch "$SETUP_DONE"
        touch "$PLUGIN_ROOT/.setup_just_completed"
        echo "$ver" > "$VERSION_FILE"
        rm -f "$SETUP_LOCK"

        "$VENV/bin/python3" "$PLUGIN_ROOT/daemon.py" &
        echo $! > "$PID_FILE"
    ) &
}

# main

# helper for user messages
msg() { echo "{\"continue\":true,\"systemMessage\":\"[observer-memory] $1\"}"; }

# check version change
CURRENT_VER=$(get_version)
INSTALLED_VER=$(cat "$VERSION_FILE" 2>/dev/null)
if [ -n "$CURRENT_VER" ] && [ "$CURRENT_VER" != "$INSTALLED_VER" ]; then
    reset_setup
fi

daemon_running && exit 0

# cleanup stale pid
if [ -f "$PID_FILE" ]; then
    pid=$(cat "$PID_FILE" 2>/dev/null)
    [ -n "$pid" ] && ! kill -0 "$pid" 2>/dev/null && rm -f "$PID_FILE"
fi

# first time?
if [ ! -f "$SETUP_DONE" ]; then
    if [ -f "$SETUP_LOCK" ]; then
        msg "installing dependencies..."
        exit 0
    fi
    if [ -f "$SETUP_FAILED" ]; then
        msg "setup failed - check daemon.log"
        exit 0
    fi
    PYTHON=$(find_python)
    if [ -z "$PYTHON" ]; then
        msg "python 3.10+ required"
        exit 2
    fi
    msg "installing dependencies (~2-5 min)..."
    setup_bg "$PYTHON" "$CURRENT_VER"
    exit 0
fi

# start
start_daemon
exit 0
