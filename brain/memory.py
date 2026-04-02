"""Conversation memory — local SQLite + optional embeddings.

Stores conversation turns and summaries. Provides context for the
LLM system prompt so Jarvis remembers past interactions.

No external dependencies (SQLite is stdlib). Embeddings are optional
(require OpenAI API or a local embedding model).

Schema:
    conversations: id, timestamp, user_text, assistant_text, summary
    facts:         id, timestamp, fact, source

Usage in config.toml:
    [memory]
    enabled = true
    max_context_turns = 5
    summarize = true           # LLM-summarize old conversations
"""

import json
import logging
import os
import sqlite3
import time
from pathlib import Path

log = logging.getLogger(__name__)

_DATA_DIR = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "jarvis"
_DB_PATH = _DATA_DIR / "memory.db"


class Memory:
    """Local conversation memory backed by SQLite."""

    def __init__(self, max_context_turns: int = 5) -> None:
        self._max_turns = max_context_turns
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(_DB_PATH))
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                user_text TEXT NOT NULL,
                assistant_text TEXT NOT NULL,
                summary TEXT
            );
            CREATE TABLE IF NOT EXISTS facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                fact TEXT NOT NULL,
                source TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_conv_ts ON conversations(timestamp DESC);
            CREATE INDEX IF NOT EXISTS idx_facts_ts ON facts(timestamp DESC);
        """)
        self._conn.commit()

    def save_turn(self, user_text: str, assistant_text: str, summary: str = "") -> None:
        """Save a conversation turn."""
        self._conn.execute(
            "INSERT INTO conversations (timestamp, user_text, assistant_text, summary) VALUES (?, ?, ?, ?)",
            (time.time(), user_text, assistant_text, summary),
        )
        self._conn.commit()

    def save_fact(self, fact: str, source: str = "conversation") -> None:
        """Save a learned fact about the user."""
        self._conn.execute(
            "INSERT INTO facts (timestamp, fact, source) VALUES (?, ?, ?)",
            (time.time(), fact, source),
        )
        self._conn.commit()

    def get_recent_turns(self, limit: int | None = None) -> list[dict]:
        """Get recent conversation turns, newest first."""
        n = limit or self._max_turns
        rows = self._conn.execute(
            "SELECT user_text, assistant_text, summary, timestamp FROM conversations ORDER BY timestamp DESC LIMIT ?",
            (n,),
        ).fetchall()
        return [dict(r) for r in reversed(rows)]  # chronological order

    def get_facts(self, limit: int = 20) -> list[str]:
        """Get stored facts about the user."""
        rows = self._conn.execute(
            "SELECT fact FROM facts ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [r["fact"] for r in rows]

    def build_context(self) -> str:
        """Build memory context string for the system prompt."""
        parts = []

        facts = self.get_facts()
        if facts:
            parts.append("Known facts about the user:")
            for f in facts:
                parts.append(f"- {f}")

        turns = self.get_recent_turns()
        if turns:
            parts.append("\nRecent conversation history:")
            for t in turns:
                summary = t.get("summary") or t["assistant_text"][:100]
                parts.append(f"- User: {t['user_text'][:80]}")
                parts.append(f"  Jarvis: {summary}")

        if not parts:
            return ""

        return "\n".join(parts)

    def close(self) -> None:
        self._conn.close()
