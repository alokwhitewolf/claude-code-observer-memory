#!/usr/bin/env python3
"""Embedding-based memory store with hybrid search (semantic + FTS5)."""
import hashlib
import json
import sqlite3
import numpy as np
from pathlib import Path
from dataclasses import dataclass

_embedder = None

def get_embedder():
    global _embedder
    if not _embedder:
        from sentence_transformers import SentenceTransformer
        _embedder = SentenceTransformer('all-MiniLM-L6-v2')
    return _embedder


@dataclass
class Memory:
    id: int
    content: str
    source: str
    category: str
    times_used: int
    similarity: float = 0.0


class MemoryStore:
    def __init__(self, cwd: str):
        self.db_path = Path(cwd) / ".claude-observer" / "memory.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY,
                content TEXT NOT NULL UNIQUE,
                embedding BLOB,
                source TEXT DEFAULT 'learned',
                category TEXT,
                created_at INTEGER DEFAULT (strftime('%s', 'now')),
                times_used INTEGER DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_source ON memories(source);

            CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(content, content_rowid=id);

            CREATE TRIGGER IF NOT EXISTS mem_ins AFTER INSERT ON memories BEGIN
                INSERT INTO memories_fts(rowid, content) VALUES (new.id, new.content);
            END;
            CREATE TRIGGER IF NOT EXISTS mem_del AFTER DELETE ON memories BEGIN
                DELETE FROM memories_fts WHERE rowid = old.id;
            END;
            CREATE TRIGGER IF NOT EXISTS mem_upd AFTER UPDATE ON memories BEGIN
                DELETE FROM memories_fts WHERE rowid = old.id;
                INSERT INTO memories_fts(rowid, content) VALUES (new.id, new.content);
            END;
        """)
        conn.commit()
        conn.close()

    def _embed_to_bytes(self, emb):
        return emb.astype(np.float32).tobytes()

    def _bytes_to_embed(self, blob):
        return np.frombuffer(blob, dtype=np.float32)

    def store(self, content, source="learned", category=None):
        emb = get_embedder().encode(content, convert_to_numpy=True)
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                "INSERT OR IGNORE INTO memories (content, embedding, source, category) VALUES (?,?,?,?)",
                (content, self._embed_to_bytes(emb), source, category)
            )
            conn.commit()
            return conn.total_changes > 0
        finally:
            conn.close()

    def store_batch(self, items):
        """items: [(content, source, category), ...]"""
        if not items:
            return
        embedder = get_embedder()
        contents = [i[0] for i in items]
        embs = embedder.encode(contents, convert_to_numpy=True)

        conn = sqlite3.connect(self.db_path)
        try:
            for (content, source, cat), emb in zip(items, embs):
                conn.execute(
                    "INSERT OR IGNORE INTO memories (content, embedding, source, category) VALUES (?,?,?,?)",
                    (content, self._embed_to_bytes(emb), source, cat)
                )
            conn.commit()
        finally:
            conn.close()

    def keyword_search(self, query, top_k=10, source_filter=None):
        conn = sqlite3.connect(self.db_path)
        try:
            sql = """
                SELECT m.id, m.content, m.source, m.category, m.times_used, bm25(memories_fts) as rank
                FROM memories_fts f JOIN memories m ON f.rowid = m.id
                WHERE memories_fts MATCH ?
            """
            params = [query]
            if source_filter:
                sql += " AND m.source = ?"
                params.append(source_filter)
            sql += " ORDER BY rank LIMIT ?"
            params.append(top_k)

            rows = conn.execute(sql, params).fetchall()
            conn.close()

            return [Memory(
                id=r[0], content=r[1], source=r[2], category=r[3], times_used=r[4],
                similarity=max(0, min(1, 1 + r[5] / 25))  # normalize bm25
            ) for r in rows]
        except:
            conn.close()
            return []

    def semantic_search(self, query, top_k=10, min_sim=0.2, source_filter=None):
        q_emb = get_embedder().encode(query, convert_to_numpy=True)
        conn = sqlite3.connect(self.db_path)

        sql = "SELECT id, content, embedding, source, category, times_used FROM memories"
        if source_filter:
            rows = conn.execute(sql + " WHERE source = ?", (source_filter,)).fetchall()
        else:
            rows = conn.execute(sql).fetchall()
        conn.close()

        results = []
        for r in rows:
            if not r[2]:
                continue
            stored = self._bytes_to_embed(r[2])
            sim = float(np.dot(q_emb, stored) / (np.linalg.norm(q_emb) * np.linalg.norm(stored)))
            if sim >= min_sim:
                results.append(Memory(id=r[0], content=r[1], source=r[3], category=r[4], times_used=r[5], similarity=sim))

        results.sort(key=lambda m: m.similarity, reverse=True)
        return results[:top_k]

    def retrieve(self, query, top_k=5, min_similarity=0.3, source_filter=None, hybrid=True):
        """Hybrid search: 70% semantic, 30% keyword, boosted if both match."""
        if not hybrid:
            return self.semantic_search(query, top_k, min_similarity, source_filter)

        sem = self.semantic_search(query, top_k * 2, min_similarity * 0.5, source_filter)
        kw = self.keyword_search(query, top_k * 2, source_filter)

        merged = {}
        for m in sem:
            merged[m.id] = Memory(
                id=m.id, content=m.content, source=m.source,
                category=m.category, times_used=m.times_used,
                similarity=m.similarity * 0.7
            )
        for m in kw:
            if m.id in merged:
                merged[m.id].similarity += m.similarity * 0.3
            else:
                merged[m.id] = Memory(
                    id=m.id, content=m.content, source=m.source,
                    category=m.category, times_used=m.times_used,
                    similarity=m.similarity * 0.3
                )

        results = [m for m in merged.values() if m.similarity >= min_similarity]
        results.sort(key=lambda m: m.similarity, reverse=True)
        return results[:top_k]

    def increment_usage(self, mid):
        conn = sqlite3.connect(self.db_path)
        conn.execute("UPDATE memories SET times_used = times_used + 1 WHERE id = ?", (mid,))
        conn.commit()
        conn.close()

    def get_all(self, source_filter=None):
        conn = sqlite3.connect(self.db_path)
        sql = "SELECT id, content, source, category, times_used FROM memories"
        if source_filter:
            rows = conn.execute(sql + " WHERE source = ? ORDER BY times_used DESC", (source_filter,)).fetchall()
        else:
            rows = conn.execute(sql + " ORDER BY times_used DESC").fetchall()
        conn.close()
        return [Memory(id=r[0], content=r[1], source=r[2], category=r[3], times_used=r[4]) for r in rows]

    def delete(self, mid):
        conn = sqlite3.connect(self.db_path)
        conn.execute("DELETE FROM memories WHERE id = ?", (mid,))
        conn.commit()
        conn.close()

    def update(self, mid, content):
        conn = sqlite3.connect(self.db_path)
        row = conn.execute("SELECT 1 FROM memories WHERE id = ?", (mid,)).fetchone()
        if not row:
            conn.close()
            return False
        emb = get_embedder().encode(content, convert_to_numpy=True)
        conn.execute("UPDATE memories SET content = ?, embedding = ? WHERE id = ?",
                     (content, self._embed_to_bytes(emb), mid))
        conn.commit()
        conn.close()
        return True

    def clear(self, source_filter=None):
        conn = sqlite3.connect(self.db_path)
        if source_filter:
            conn.execute("DELETE FROM memories WHERE source = ?", (source_filter,))
        else:
            conn.execute("DELETE FROM memories")
        conn.commit()
        conn.close()


# --- CLAUDE.md parsing ---

def _md_paths(cwd):
    return [
        Path.home() / ".claude" / "CLAUDE.md",  # global
        Path(cwd) / "CLAUDE.md",
        Path(cwd) / ".claude" / "CLAUDE.md",
        Path(cwd) / "CLAUDE.local.md"
    ]

def _md_hash(cwd):
    h = hashlib.md5()
    for p in _md_paths(cwd):
        if p.exists():
            try:
                h.update(p.read_bytes())
            except:
                pass
    return h.hexdigest()

def _read_md(cwd):
    parts = []
    for p in _md_paths(cwd):
        if p.exists():
            try:
                parts.append(p.read_text())
            except:
                pass
    return "\n\n".join(parts)

def _cache_path(cwd):
    return Path(cwd) / ".claude-observer" / ".claude_md_hash"

def _get_cached_hash(cwd):
    p = _cache_path(cwd)
    return p.read_text().strip() if p.exists() else ""

def _save_hash(cwd, h):
    p = _cache_path(cwd)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(h)


EXTRACT_RULES_TOOL = """[{
  "name": "submit_rules",
  "description": "Submit extracted rules from CLAUDE.md",
  "input_schema": {
    "type": "object",
    "properties": {
      "rules": {
        "type": "array",
        "items": {"type": "string"},
        "description": "List of rules extracted from CLAUDE.md. Each should be a single, clear, actionable statement."
      }
    },
    "required": ["rules"]
  }
}]"""


async def _parse_with_haiku(content, retries=2):
    """Extract rules via Haiku. Retries if model doesn't use submit_rules tool."""
    import os
    os.environ["CLAUDE_OBSERVER_ACTIVE"] = "1"
    try:
        from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions
        opts = ClaudeAgentOptions(
            model="haiku",
            tools=EXTRACT_RULES_TOOL,
            system_prompt="You extract rules from CLAUDE.md files. Use the submit_rules tool to return results."
        )
        async with ClaudeSDKClient(options=opts) as client:
            prompt = f"""Extract instructions from this CLAUDE.md as consolidated rules.

Content:
{content}

Group related points into single dense statements. Combine bullets under the same section/topic into one rule. Include key info from prose and code examples. Aim for fewer comprehensive rules rather than many fragments.

Use the submit_rules tool to return the rules."""

            await client.query(prompt)

            for attempt in range(retries + 1):
                rules, saw_text = [], False

                async for msg in client.receive_response():
                    for block in getattr(msg, 'content', []):
                        if getattr(block, 'type', None) == 'tool_use' and block.name == 'submit_rules':
                            rules.extend(getattr(block, 'input', {}).get('rules', []))
                        elif getattr(block, 'type', None) == 'text':
                            saw_text = True

                if rules:
                    return [r for r in rules if isinstance(r, str) and len(r) > 10]

                if saw_text and attempt < retries:
                    print(f"[Observer] CLAUDE.md parse: retrying ({attempt + 1}/{retries})")
                    await client.query("Use the submit_rules tool to submit the extracted rules.")
                else:
                    break

            return []
    except Exception as e:
        print(f"[Observer] CLAUDE.md parse failed: {e}")
        return []


def _simple_parse(content):
    """Fallback: extract bullet points and numbered items."""
    rules = []
    for line in content.split('\n'):
        line = line.strip()
        if not line or line.startswith('#') or line.startswith('```'):
            continue
        if line[0] in '-*' and len(line) > 15:
            rules.append(line[1:].strip())
        elif len(line) > 3 and line[0].isdigit() and '.' in line[:3]:
            rules.append(line[line.find('.')+1:].strip())
    return [r for r in rules if len(r) > 10][:50]


async def load_claude_md_to_memory(cwd, force=False):
    """Load CLAUDE.md rules into memory using Haiku."""
    h = _md_hash(cwd)
    if not h or h == "d41d8cd98f00b204e9800998ecf8427e":  # empty
        return 0

    if not force and h == _get_cached_hash(cwd):
        return len(MemoryStore(cwd).get_all(source_filter='claude_md'))

    content = _read_md(cwd)
    if not content:
        return 0

    print(f"[Observer] parsing CLAUDE.md ({h[:8]}...)")
    rules = await _parse_with_haiku(content)
    if not rules:
        return 0

    store = MemoryStore(cwd)
    store.clear(source_filter='claude_md')
    store.store_batch([(r, 'claude_md', None) for r in rules])
    _save_hash(cwd, h)

    print(f"[Observer] loaded {len(rules)} rules")
    return len(rules)


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        s = MemoryStore(d)
        s.store("Use const not var in JS", source="learned")
        s.store("Never push to main", source="learned")
        s.store("Run tests first", source="learned")

        for m in s.retrieve("editing javascript", top_k=3):
            print(f"  [{m.similarity:.2f}] {m.content}")
