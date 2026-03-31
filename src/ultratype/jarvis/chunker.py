"""Text chunker for streaming TTS — splits text into speakable sentences."""

from __future__ import annotations

import re

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_MAX_CHUNK = 200


class TextChunker:
    """Accumulates streamed text and yields complete sentences for TTS."""

    def __init__(self) -> None:
        self._buffer = ""

    def feed(self, text: str) -> list[str]:
        """Add text and return any complete sentences ready for TTS."""
        self._buffer += text
        return self._flush()

    def drain(self) -> str:
        """Return any remaining buffered text (call when stream ends)."""
        remaining = self._buffer.strip()
        self._buffer = ""
        return remaining

    def _flush(self) -> list[str]:
        sentences: list[str] = []

        # Split on paragraph breaks
        while "\n\n" in self._buffer:
            before, self._buffer = self._buffer.split("\n\n", 1)
            chunk = before.strip()
            if chunk:
                sentences.append(chunk)

        # Split on sentence boundaries
        parts = _SENTENCE_END.split(self._buffer)
        if len(parts) > 1:
            # All but the last part are complete sentences
            for part in parts[:-1]:
                chunk = part.strip()
                if chunk:
                    sentences.append(chunk)
            self._buffer = parts[-1]

        # Force flush if buffer is too long without a sentence boundary
        if len(self._buffer) >= _MAX_CHUNK:
            chunk = self._buffer.strip()
            if chunk:
                sentences.append(chunk)
            self._buffer = ""

        return sentences
