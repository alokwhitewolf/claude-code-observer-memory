#!/usr/bin/env python3
"""PreToolUse hook - injects relevant memories before tool calls."""
import json, os, sys

if os.environ.get("CLAUDE_OBSERVER_ACTIVE"):
    sys.exit(0)

def main():
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
            inj = r.json().get("inject")
            if inj:
                print(inj)
    except:
        pass

    sys.exit(0)

if __name__ == "__main__":
    main()
