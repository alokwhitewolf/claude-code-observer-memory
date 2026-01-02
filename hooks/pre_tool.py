#!/usr/bin/env python3
"""PreToolUse hook - injects relevant memories before tool calls."""
import json, os, sys
from pathlib import Path

if os.environ.get("CLAUDE_OBSERVER_ACTIVE"):
    sys.exit(0)

def check_setup_status():
    root = os.environ.get("CLAUDE_PLUGIN_ROOT", "")
    if not root:
        return None
    failed = Path(root) / ".setup_failed"
    lock = Path(root) / ".setup_in_progress"
    done = Path(root) / ".setup_complete"

    if failed.exists():
        reason = failed.read_text().strip() or "unknown error"
        return f"[Observer] setup failed: {reason}. Check daemon.log"
    if lock.exists() and not done.exists():
        return "[Observer] still installing dependencies..."
    return None

def main():
    # check for setup issues - show message but don't block
    msg = check_setup_status()
    if msg:
        print(json.dumps({"continue": True, "systemMessage": msg}))
        sys.exit(0)

    try:
        import requests
    except ImportError:
        sys.exit(0)

    try:
        data = json.load(sys.stdin)
    except:
        sys.exit(0)

    cwd = data.get("cwd", "")
    transcript = ""
    tp = data.get("transcript_path", "")
    if tp and os.path.exists(tp):
        try:
            with open(tp) as f:
                f.seek(0, 2)
                sz = f.tell()
                f.seek(max(0, sz - 30000))
                transcript = f.read()
        except:
            pass

    context = json.dumps({
        "tool": data.get("tool_name", ""),
        "input": str(data.get("tool_input", {}))[:500]
    })

    try:
        r = requests.post(
            "http://127.0.0.1:7888/get-context",
            json={"cwd": cwd, "transcript": transcript, "context": context},
            timeout=0.15
        )
        if r.status_code == 200:
            resp = r.json()
            # show notifications as user message
            notifs = resp.get("notifications", [])
            if notifs:
                msg = "[observer-memory] " + "; ".join(notifs)
                print(json.dumps({"continue": True, "systemMessage": msg}))
            # inject context
            inj = resp.get("inject")
            if inj:
                print(inj)
    except:
        pass

    sys.exit(0)

if __name__ == "__main__":
    main()
