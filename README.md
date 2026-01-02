# claude-code-observer-memory

A Claude Code plugin that learns from your sessions and injects relevant context.

## What it does

- Learns corrections, preferences, conventions from conversations
- Reinforces CLAUDE.md rules that Claude tends to forget
- Injects relevant memories when you're working on something related

## Install

```bash
/plugin marketplace add alokwhitewolf/claude-code-observer-memory
/plugin install claude-code-observer-memory
```

Then restart Claude Code. First run installs dependencies automatically.

### Alternative: local install

```bash
git clone https://github.com/alokwhitewolf/claude-code-observer-memory.git
claude --plugin-dir /path/to/claude-code-observer-memory
```

## How it works

```
SessionStart hook
  -> Start daemon (or install deps first time)

PreToolUse hook
  -> Query daemon for relevant memories
  -> Inject as context

PostToolUse hook (every 10 messages)
  -> Send conversation snapshot to daemon
  -> Haiku agent analyzes for learnings
  -> Stores in per-workspace SQLite
```

## Files

```
.claude-plugin/plugin.json   # manifest
hooks/hooks.json             # hook config
hooks/*.py                   # hook scripts
daemon.py                    # FastAPI server
memory.py                    # embeddings + storage
scripts/*.sh                 # setup/lifecycle
```

## API

```bash
curl http://127.0.0.1:7888/status
curl http://127.0.0.1:7888/memories/path/to/workspace
curl -X DELETE "http://127.0.0.1:7888/memories/path/to/workspace?source=learned"
curl -X POST http://127.0.0.1:7888/memories/path/to/workspace/reload-rules
```

## Data

Each workspace stores:
```
{workspace}/.claude-observer/
  memory.db          # SQLite + embeddings
  .claude_md_hash    # cache for CLAUDE.md parsing
```

Add `.claude-observer/` to `.gitignore`.

## Config

In `daemon.py`:
```python
ANALYZE_EVERY = 10   # analyze every N messages
WINDOW_SIZE = 30     # messages in context window
```

## License

MIT
