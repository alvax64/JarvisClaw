"""ElevenLabs streaming TTS with mpv playback and API key rotation."""

from __future__ import annotations

import asyncio
import logging
import re

import httpx

from ultratype.config import JarvisConfig
from ultratype.jarvis.chunker import TextChunker

log = logging.getLogger(__name__)

ELEVENLABS_API = "https://api.elevenlabs.io/v1/text-to-speech"

# HTTP codes that mean "this key is exhausted, try the next one"
_EXHAUSTED_CODES = {401, 402, 429}

# Strip markdown formatting from text before speaking
_MD_PATTERNS = re.compile(r"\*\*|__|\*|_|`{1,3}|#{1,6}\s|>\s|\[([^\]]+)\]\([^)]+\)")


def _clean_for_speech(text: str) -> str:
    """Remove markdown formatting so TTS sounds natural."""
    text = _MD_PATTERNS.sub(r"\1", text)
    text = text.replace("```", "").replace("**", "").replace("__", "")
    return text.strip()


class ElevenLabsTTS:
    """Streaming text-to-speech via ElevenLabs API + mpv playback.

    Supports automatic API key rotation: when a key runs out of credits
    (401/402/429), it moves to the next key in the pool.
    """

    def __init__(self, config: JarvisConfig) -> None:
        self._config = config
        self._client: httpx.AsyncClient | None = None
        self._playback_process: asyncio.subprocess.Process | None = None
        self._cancelled = False

        # Build key pool: primary key + rotation keys
        self._keys: list[str] = []
        if config.elevenlabs_api_key:
            self._keys.append(config.elevenlabs_api_key)
        if config.elevenlabs_api_keys:
            for k in config.elevenlabs_api_keys.split(","):
                k = k.strip()
                if k and k not in self._keys:
                    self._keys.append(k)
        self._current_key_idx: int = 0
        self._exhausted: set[int] = set()

        if self._keys:
            log.info("TTS initialized with %d API key(s)", len(self._keys))
        else:
            log.warning("No ElevenLabs API keys configured — TTS disabled")

    @property
    def _has_keys(self) -> bool:
        return len(self._keys) > 0

    @property
    def _current_key(self) -> str | None:
        if not self._keys:
            return None
        return self._keys[self._current_key_idx]

    def _rotate_key(self) -> bool:
        """Mark current key as exhausted and rotate to the next available one.

        Returns True if a working key was found, False if all keys are exhausted.
        """
        self._exhausted.add(self._current_key_idx)
        log.warning(
            "API key #%d exhausted (%d/%d depleted)",
            self._current_key_idx + 1,
            len(self._exhausted),
            len(self._keys),
        )

        # Find next non-exhausted key
        for i in range(len(self._keys)):
            candidate = (self._current_key_idx + 1 + i) % len(self._keys)
            if candidate not in self._exhausted:
                self._current_key_idx = candidate
                log.info("Rotated to API key #%d", candidate + 1)
                return True

        log.error("All %d API keys exhausted — TTS disabled until reset", len(self._keys))
        return False

    def reset_exhausted(self) -> None:
        """Reset exhausted keys (call monthly or on daemon restart)."""
        self._exhausted.clear()
        self._current_key_idx = 0

    async def start(self) -> None:
        self._client = httpx.AsyncClient(timeout=30.0)
        # Reset exhausted keys on start (new month might have refreshed credits)
        self.reset_exhausted()

    async def close(self) -> None:
        await self.stop()
        if self._client:
            await self._client.aclose()
            self._client = None

    async def speak(self, text: str) -> None:
        """Speak a single string. Blocks until playback finishes."""
        text = _clean_for_speech(text)
        if not text:
            return
        if not self._has_keys:
            log.warning("No ElevenLabs API keys — skipping TTS")
            return

        log.debug("TTS speaking: %s", text[:80])

        try:
            audio_data = await self._fetch_audio_with_rotation(text)
            if audio_data and not self._cancelled:
                await self._play_audio_bytes(audio_data)
        except Exception as e:
            log.error("TTS speak failed: %s", e)

    async def speak_stream(self, events) -> None:
        """Speak a stream of text chunks, splitting into sentences."""
        if not self._has_keys:
            log.warning("No ElevenLabs API keys — skipping TTS")
            # Still drain the generator so brain events are processed
            async for _ in events:
                pass
            return

        self._cancelled = False
        chunker = TextChunker()

        try:
            async for text_chunk in events:
                if self._cancelled:
                    return
                sentences = chunker.feed(text_chunk)
                for sentence in sentences:
                    if self._cancelled:
                        return
                    await self.speak(sentence)

            remaining = chunker.drain()
            if remaining and not self._cancelled:
                await self.speak(remaining)
        except Exception as e:
            log.error("TTS stream failed: %s", e)

    async def stop(self) -> None:
        """Interrupt current speech."""
        self._cancelled = True
        if self._playback_process and self._playback_process.returncode is None:
            try:
                self._playback_process.kill()
                await self._playback_process.wait()
            except ProcessLookupError:
                pass
            self._playback_process = None

    @property
    def is_speaking(self) -> bool:
        return self._playback_process is not None and self._playback_process.returncode is None

    async def _fetch_audio_with_rotation(self, text: str) -> bytes | None:
        """Fetch audio, rotating API keys on exhaustion."""
        # Try current key, then rotate on failure
        while True:
            key = self._current_key
            if key is None:
                return None

            result = await self._fetch_audio(text, key)

            if isinstance(result, bytes):
                return result

            # result is an HTTP status code indicating failure
            if result in _EXHAUSTED_CODES:
                if not self._rotate_key():
                    return None  # All keys exhausted
                continue  # Try next key
            else:
                return None  # Non-rotation error

    async def _fetch_audio(self, text: str, api_key: str) -> bytes | int | None:
        """Fetch audio from ElevenLabs API.

        Returns audio bytes on success, HTTP status code on known failure,
        or None on unexpected error.
        """
        assert self._client is not None

        url = f"{ELEVENLABS_API}/{self._config.elevenlabs_voice_id}/stream"

        try:
            resp = await self._client.post(
                url,
                headers={
                    "xi-api-key": api_key,
                    "Content-Type": "application/json",
                },
                params={"optimize_streaming_latency": "3"},
                json={
                    "text": text,
                    "model_id": self._config.elevenlabs_model,
                    "voice_settings": {
                        "stability": 0.4,
                        "similarity_boost": 0.85,
                    },
                },
            )

            if resp.status_code == 200:
                return resp.content

            log.error("ElevenLabs error %d: %s", resp.status_code, resp.text[:200])
            return resp.status_code

        except Exception as e:
            log.error("ElevenLabs request failed: %s", e)
            return None

    async def _play_audio_bytes(self, audio: bytes) -> None:
        """Play audio bytes via mpv."""
        cmd_parts = self._config.playback_command.split()

        self._playback_process = await asyncio.create_subprocess_exec(
            *cmd_parts,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )

        try:
            self._playback_process.stdin.write(audio)
            self._playback_process.stdin.close()
            await self._playback_process.wait()
        except (BrokenPipeError, OSError):
            log.debug("Playback process closed early")
        finally:
            self._playback_process = None
