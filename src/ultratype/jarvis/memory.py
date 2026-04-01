"""Simple file-based memory for Jarvis conversations.

After each conversation, gemini-flash-lite extracts key facts and saves them
as individual .md files. The compact index (MEMORY.md) is injected into the
system prompt each call (~200-500 tokens). Claude reads specific files on demand.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path

from ultratype.config import LLMConfig

log = logging.getLogger(__name__)

MEMORY_DIR = Path.home() / ".local" / "share" / "ultratype" / "jarvis-memory"
MEMORY_INDEX = MEMORY_DIR / "MEMORY.md"
MAX_INDEX_LINES = 50  # cap to keep token cost low

EXTRACT_PROMPT = """\
You are a memory extraction system for a voice assistant called Jarvis.
You receive a conversation between a user (Diego) and Jarvis.

Extract ONLY facts worth remembering for future conversations:
- User preferences, names, relationships ("mi novia se llama X")
- Recurring topics or projects ("estoy trabajando en X")
- Important decisions or context ("decidimos usar Postgres")
- User corrections or feedback ("no me gusta cuando haces X")
- Technical setup details the user mentioned

Do NOT extract:
- Temporary tasks ("abre Firefox", "qué hora es")
- Things obvious from context
- The assistant's own responses (only user facts)

Return a JSON array of objects, each with:
- "key": short snake_case identifier (e.g. "novia_nombre")
- "summary": one-line description in Spanish (max 80 chars)
- "content": the full fact to remember (1-3 sentences, Spanish)

If nothing is worth remembering, return an empty array: []
Return ONLY valid JSON, nothing else."""


def ensure_memory_dir() -> None:
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    if not MEMORY_INDEX.exists():
        MEMORY_INDEX.write_text("# Jarvis Memory\n")


def load_memory_index() -> str:
    """Return the memory index contents, or empty string if none."""
    ensure_memory_dir()
    content = MEMORY_INDEX.read_text().strip()
    if content and content != "# Jarvis Memory":
        return content
    return ""


def build_memory_prompt(base_system_prompt: str) -> str:
    """Append memory context to the system prompt."""
    memory_content = load_memory_index()

    if not memory_content:
        memory_section = (
            "\n\n## Memory\nNo memories saved yet. "
            "If the user references past conversations, let them know this is "
            "a fresh start but you'll remember things from now on.\n"
        )
    else:
        # Load all memory file contents (they're small)
        details = _load_all_memories()
        memory_section = f"""

## Memory — things you know about the user from past conversations
{memory_content}

### Details
{details}

Use this context naturally. Don't announce that you "remember" unless asked.
If the user asks about something in memory, use it. If a memory seems relevant
to the current task, apply it silently.
"""
    return base_system_prompt + memory_section


def _load_all_memories() -> str:
    """Load contents of all memory .md files (excluding index)."""
    ensure_memory_dir()
    parts: list[str] = []
    for f in sorted(MEMORY_DIR.glob("*.md")):
        if f.name == "MEMORY.md":
            continue
        content = f.read_text().strip()
        if content:
            parts.append(f"**{f.stem}**: {content}")
    return "\n".join(parts) if parts else "(no details)"


async def extract_and_save(
    user_text: str, assistant_response: str, llm_config: LLMConfig
) -> None:
    """Extract memories from a conversation turn and save them.

    Uses the same LLM provider configured for corrections (gemini-flash-lite).
    Runs in background — errors are logged but never raised.
    """
    if not user_text.strip():
        return

    try:
        from ultratype.llm import LLMClient

        conversation = (
            f"Usuario: {user_text}\n\n"
            f"Jarvis: {assistant_response[:500] if assistant_response else '(no response)'}"
        )

        # Also pass existing memories so the LLM can avoid duplicates
        existing = load_memory_index()
        if existing:
            conversation += f"\n\n--- Memorias existentes ---\n{existing}\n--- No duplicar estas ---"

        async with LLMClient(llm_config) as client:
            raw = await client._complete(EXTRACT_PROMPT, conversation)

        # Parse JSON from response (handle markdown code blocks)
        raw = raw.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```\w*\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)
            raw = raw.strip()

        memories = json.loads(raw)
        if not isinstance(memories, list) or not memories:
            return

        ensure_memory_dir()

        for mem in memories:
            key = mem.get("key", "")
            summary = mem.get("summary", "")
            content = mem.get("content", "")
            if not key or not content:
                continue

            # Sanitize filename
            safe_key = re.sub(r"[^a-z0-9_]", "", key.lower())[:40]
            if not safe_key:
                safe_key = hashlib.md5(content.encode()).hexdigest()[:8]

            filepath = MEMORY_DIR / f"{safe_key}.md"

            # Write or update memory file
            filepath.write_text(content)
            log.info("Memory saved: %s — %s", safe_key, summary)

            # Update index
            _update_index(safe_key, summary)

    except json.JSONDecodeError as e:
        log.warning("Memory extraction returned invalid JSON: %s", e)
    except Exception as e:
        log.warning("Memory extraction failed (non-critical): %s", e)


def _update_index(key: str, summary: str) -> None:
    """Add or update an entry in MEMORY.md."""
    ensure_memory_dir()
    index_text = MEMORY_INDEX.read_text()
    filename = f"{key}.md"

    # Check if entry already exists
    lines = index_text.splitlines()
    new_lines: list[str] = []
    found = False
    for line in lines:
        if filename in line:
            new_lines.append(f"- [{key}]({filename}) — {summary}")
            found = True
        else:
            new_lines.append(line)

    if not found:
        # Enforce max lines
        entry_lines = [l for l in new_lines if l.startswith("- ")]
        if len(entry_lines) >= MAX_INDEX_LINES:
            # Remove oldest entry (first one after header)
            for i, l in enumerate(new_lines):
                if l.startswith("- "):
                    new_lines.pop(i)
                    break
        new_lines.append(f"- [{key}]({filename}) — {summary}")

    MEMORY_INDEX.write_text("\n".join(new_lines) + "\n")
