#!/usr/bin/env python3
"""
Observer daemon - learns from Claude Code sessions and injects relevant context.
Runs on http://127.0.0.1:7888
"""
import asyncio
import json
import os
import time
from collections import defaultdict

from fastapi import FastAPI
from pydantic import BaseModel
import uvicorn

os.environ["CLAUDE_OBSERVER_ACTIVE"] = "1"  # prevent hook loops

from memory import MemoryStore, load_claude_md_to_memory

app = FastAPI()

# state
client = None
analyzing = defaultdict(bool)
md_loaded = set()
msg_counts = defaultdict(int)
last_activity = time.time()
notifications = defaultdict(list)  # per-workspace notifications

ANALYZE_EVERY = 10
WINDOW_SIZE = 30
IDLE_TIMEOUT = 1800  # 30 min

TOOLS = """[
  {"name": "search_memories", "description": "Semantic search. Use before adding to check duplicates.", "input_schema": {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer", "default": 5}}, "required": ["query"]}},
  {"name": "list_memories", "description": "List memories by source (learned/claude_md/user)", "input_schema": {"type": "object", "properties": {"source": {"type": "string", "enum": ["learned", "claude_md", "user"]}, "limit": {"type": "integer", "default": 10}}}},
  {"name": "add_memory", "description": "Store new memory", "input_schema": {"type": "object", "properties": {"content": {"type": "string"}, "category": {"type": "string"}}, "required": ["content"]}},
  {"name": "update_memory", "description": "Update existing memory by ID", "input_schema": {"type": "object", "properties": {"id": {"type": "integer"}, "content": {"type": "string"}}, "required": ["id", "content"]}},
  {"name": "delete_memory", "description": "Delete memory by ID", "input_schema": {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]}},
  {"name": "done", "description": "Signal completion", "input_schema": {"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"]}}
]"""

SYSTEM = """You are a memory manager for Claude Code sessions.

Your job:
1. Analyze conversation snapshots for things worth remembering
2. Use tools to check existing memories before adding
3. Avoid duplicates - update existing memories instead
4. Keep memories concise and actionable

WORKFLOW:
1. First, search_memories to see what's already stored
2. If similar exists: update_memory or skip
3. If new insight: add_memory
4. When done: call done() with summary

Types of things to remember:
- User corrections ("no, do it this way instead")
- Explicit preferences ("always use X", "never do Y")
- Project conventions discovered
- Important architectural decisions
- Specs/requirements that were decided (things that can't be discovered from files alone)

NOTE: You receive a SNAPSHOT of recent messages, not the complete conversation.
Be selective. Most snapshots have nothing worth remembering."""


class AnalyzeReq(BaseModel):
    cwd: str
    transcript: str
    context: str
    hook_type: str = "post_tool"

class InjectReq(BaseModel):
    cwd: str
    transcript: str
    context: str


def parse_messages(transcript, n=30):
    """Parse JSONL transcript, return (recent_n, total_count)"""
    if not transcript:
        return [], 0
    msgs = []
    for line in transcript.strip().split('\n'):
        if line.strip():
            try:
                msgs.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return msgs[-n:], len(msgs)

def format_messages(msgs):
    """Format for the agent - skip tool results (too verbose)"""
    out = []
    for m in msgs:
        t = m.get("type")
        if t == "user":
            out.append(f"[USER]: {m.get('message', '')[:500]}")
        elif t == "assistant" and m.get("message"):
            out.append(f"[CLAUDE]: {m.get('message', '')[:500]}")
        elif t == "tool_use":
            out.append(f"[TOOL]: {m.get('tool', '?')}")
    return "\n".join(out)


async def get_client():
    global client
    if client:
        return client
    try:
        from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions
        options = ClaudeAgentOptions(
            model="haiku",
            tools=TOOLS,
            system_prompt=SYSTEM
        )
        client = ClaudeSDKClient(options=options)
        await client.__aenter__()
        print("[Observer] Claude client ready (with memory tools)")
        return client
    except Exception as e:
        print(f"[Observer] Failed to initialize Claude client: {e}")
        return None


def run_tool(name, inp, store, cwd=None):
    """Execute memory tool, return result string"""
    try:
        if name == "search_memories":
            mems = store.retrieve(inp.get("query", ""), top_k=inp.get("limit", 5), min_similarity=0.2)
            if not mems:
                return "No matches."
            return "\n".join(f"[{m.id}] ({m.similarity:.2f}) {m.content}" for m in mems)

        if name == "list_memories":
            mems = store.get_all(source_filter=inp.get("source"))[:inp.get("limit", 10)]
            if not mems:
                return "Empty."
            return "\n".join(f"[{m.id}] [{m.source}] {m.content}" for m in mems)

        if name == "add_memory":
            content = inp.get("content", "")
            if not content:
                return "Error: empty content"
            ok = store.store(content, source="learned", category=inp.get("category"))
            if ok and cwd:
                notifications[cwd].append(f"learned: {content}")
            return f"Added: {content[:50]}..." if ok else "Duplicate"

        if name == "update_memory":
            mid, content = inp.get("id"), inp.get("content", "")
            if not mid or not content:
                return "Error: need id and content"
            return f"Updated {mid}" if store.update(mid, content) else f"Not found: {mid}"

        if name == "delete_memory":
            mid = inp.get("id")
            if not mid:
                return "Error: need id"
            store.delete(mid)
            return f"Deleted {mid}"

        if name == "done":
            return f"Done: {inp.get('summary', '')}"

        return f"Unknown: {name}"
    except Exception as e:
        return f"Error: {e}"


async def analyze(cwd, transcript, context):
    """Run the memory agent"""
    claude = await get_client()
    if not claude:
        return {"ok": False, "reason": "no client"}

    store = MemoryStore(cwd)
    msgs, total = parse_messages(transcript, WINDOW_SIZE)
    formatted = format_messages(msgs)

    prompt = f"""=== SNAPSHOT ({len(msgs)}/{total} messages) ===
{formatted}
=== END ===

Context: {context[:300]}

Search existing memories, look for corrections/preferences/conventions/specs, add if new, update if similar exists, then done()."""

    try:
        await claude.query(prompt)
        result = {"ok": True, "actions": []}

        for _ in range(10):  # max tool iterations
            async for msg in claude.receive_response():
                if not hasattr(msg, 'content'):
                    continue
                for block in msg.content:
                    if getattr(block, 'type', None) == 'tool_use':
                        name = block.name
                        inp = getattr(block, 'input', {})
                        tid = getattr(block, 'id', None)

                        out = run_tool(name, inp, store, cwd)
                        result["actions"].append({"tool": name, "result": out[:80]})

                        if name == "done":
                            result["summary"] = inp.get("summary", "")
                            return result
                        if tid:
                            await claude.respond_to_tool(tid, out)
                            break
            else:
                break
        return result
    except Exception as e:
        print(f"[Observer] analyze error: {e}")
        return {"ok": False, "reason": str(e)}


async def analyze_bg(cwd, transcript, context):
    """Background wrapper"""
    analyzing[cwd] = True
    try:
        r = await analyze(cwd, transcript, context)
        if r.get("ok") and r.get("actions"):
            print(f"[Observer] {', '.join(a['tool'] for a in r['actions'])}")
        if r.get("summary"):
            print(f"[Observer] {r['summary'][:80]}")
    except Exception as e:
        print(f"[Observer] bg error: {e}")
    finally:
        analyzing[cwd] = False


def load_md(cwd):
    """Load CLAUDE.md once per workspace"""
    if cwd in md_loaded:
        return
    try:
        n = load_claude_md_to_memory(cwd)
        if n:
            notifications[cwd].append(f"loaded {n} rules from CLAUDE.md")
    except Exception as e:
        print(f"[Observer] CLAUDE.md load failed: {e}")
    md_loaded.add(cwd)


# --- endpoints ---

@app.post("/analyze")
async def ep_analyze(req: AnalyzeReq):
    load_md(req.cwd)

    _, total = parse_messages(req.transcript, 1)
    prev = msg_counts.get(req.cwd, 0)
    msg_counts[req.cwd] = total

    should_run = (
        req.hook_type == "session_end" or
        total - prev >= ANALYZE_EVERY or
        (prev == 0 and total > 0)
    )

    if not should_run:
        return {"status": "skip", "progress": f"{total % ANALYZE_EVERY}/{ANALYZE_EVERY}"}

    if not analyzing.get(req.cwd):
        asyncio.create_task(analyze_bg(req.cwd, req.transcript, req.context))
        return {"status": "started", "msgs": total}

    return {"status": "busy", "msgs": total}


@app.post("/get-context")
async def ep_context(req: InjectReq):
    load_md(req.cwd)

    # collect and clear notifications
    notifs = notifications.pop(req.cwd, [])

    try:
        store = MemoryStore(req.cwd)
        query = req.transcript[-500:] + "\n" + req.context[:500] if req.transcript else req.context[:500]
        mems = store.retrieve(query, top_k=5, min_similarity=0.25)

        if not mems and not notifs:
            return {"inject": None}

        lines = []
        for m in mems:
            tag = "[rule]" if m.source == "claude_md" else "[learned]"
            lines.append(f"  {tag} {m.content}")
            store.increment_usage(m.id)

        result = {"count": len(mems)}
        if lines:
            result["inject"] = f"[Observer]:\n" + "\n".join(lines)
        if notifs:
            result["notifications"] = notifs
        return result
    except Exception as e:
        print(f"[Observer] context error: {e}")
        return {"inject": None, "notifications": notifs} if notifs else {"inject": None}


@app.get("/status")
async def ep_status():
    return {
        "status": "ok",
        "client": client is not None,
        "workspaces": len(md_loaded),
        "analyzing": sum(1 for v in analyzing.values() if v)
    }


@app.get("/memories/{path:path}")
async def ep_list(path: str):
    cwd = "/" + path
    try:
        mems = MemoryStore(cwd).get_all()
        return {"workspace": cwd, "count": len(mems), "memories": [
            {"id": m.id, "content": m.content, "source": m.source, "used": m.times_used}
            for m in mems
        ]}
    except Exception as e:
        return {"error": str(e)}


@app.delete("/memories/{path:path}")
async def ep_clear(path: str, source: str = None):
    cwd = "/" + path
    try:
        MemoryStore(cwd).clear(source_filter=source)
        if source in (None, "claude_md"):
            md_loaded.discard(cwd)
        return {"cleared": True}
    except Exception as e:
        return {"error": str(e)}


@app.post("/memories/{path:path}/reload-rules")
async def ep_reload(path: str):
    cwd = "/" + path
    try:
        store = MemoryStore(cwd)
        store.clear(source_filter="claude_md")
        md_loaded.discard(cwd)
        n = load_claude_md_to_memory(cwd)
        md_loaded.add(cwd)
        return {"reloaded": n}
    except Exception as e:
        return {"error": str(e)}


@app.post("/memories/{path:path}/add")
async def ep_add(path: str, content: str, source: str = "user"):
    cwd = "/" + path
    try:
        ok = MemoryStore(cwd).store(content, source=source)
        return {"stored": ok}
    except Exception as e:
        return {"error": str(e)}


@app.middleware("http")
async def track_activity(request, call_next):
    global last_activity
    last_activity = time.time()
    return await call_next(request)


async def idle_checker():
    while True:
        await asyncio.sleep(60)
        if time.time() - last_activity > IDLE_TIMEOUT:
            print("[Observer] idle timeout, shutting down")
            os._exit(0)


@app.on_event("startup")
async def on_start():
    asyncio.create_task(idle_checker())
    print("[Observer] ready on http://127.0.0.1:7888")

@app.on_event("shutdown")
async def on_stop():
    if client:
        try:
            await client.__aexit__(None, None, None)
        except:
            pass


if __name__ == "__main__":
    uvicorn.run("daemon:app", host="127.0.0.1", port=7888, log_level="info")
