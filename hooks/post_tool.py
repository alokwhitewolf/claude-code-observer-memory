#!/usr/bin/env python3
"""PostToolUse hook - triggers async learning analysis."""
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
                f.seek(max(0, sz - 50000))
                transcript = f.read()
        except:
            pass

    context = json.dumps({
        "tool": data.get("tool_name", ""),
        "input": str(data.get("tool_input", {}))[:500],
        "output": str(data.get("tool_response", {}))[:200]
    })

    try:
        requests.post(
            "http://127.0.0.1:7888/analyze",
            json={"cwd": cwd, "transcript": transcript, "context": context, "hook_type": "post_tool"},
            timeout=0.2
        )
    except:
        pass

    sys.exit(0)

if __name__ == "__main__":
    main()
