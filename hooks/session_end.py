#!/usr/bin/env python3
"""SessionEnd hook - final analysis before session closes."""
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
                f.seek(max(0, sz - 100000))  # read more at end
                transcript = f.read()
        except:
            pass

    try:
        requests.post(
            "http://127.0.0.1:7888/analyze",
            json={"cwd": cwd, "transcript": transcript, "context": "session_end", "hook_type": "session_end"},
            timeout=2.0
        )
    except:
        pass

    sys.exit(0)

if __name__ == "__main__":
    main()
