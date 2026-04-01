"""Always-on wake word listener for Jarvis.

Continuously monitors the microphone, detects speech segments via energy-based
VAD, transcribes them with Whisper, and classifies whether the user is giving
a direct command to Jarvis or merely mentioning Jarvis in conversation.
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import struct
import tempfile
import wave
from pathlib import Path
from typing import Awaitable, Callable

from ultratype.config import JarvisConfig, LLMConfig, RecordingConfig, WhisperConfig
from ultratype.jarvis.sounds import SOUND_LISTEN_START, play_sound
from ultratype.transcriber import Transcriber

log = logging.getLogger(__name__)

# Audio constants — must match pw-cat config
SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2  # 16-bit signed
FRAME_MS = 30  # milliseconds per frame
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000  # 480
FRAME_BYTES = FRAME_SAMPLES * SAMPLE_WIDTH * CHANNELS  # 960

# Common Whisper mis-transcriptions of "Jarvis"
_JARVIS_VARIANTS = {
    "jarvis", "jarbis", "garbis", "harbys", "harvis", "yarbis",
    "jarbi", "garvis", "charvis", "jarvys", "jarves", "jarbs",
    "harvys", "garvys", "yarbys", "jarby", "garby", "jarbys",
}

CLASSIFY_PROMPT = (
    "You receive a speech-to-text transcription in Spanish (may contain English "
    "technical terms). Determine whether the speaker is giving a DIRECT command "
    "or question TO a voice assistant named Jarvis, or merely MENTIONING Jarvis "
    "while talking to someone else.\n\n"
    "COMMAND — the speaker addresses Jarvis directly:\n"
    "  'Jarvis abre Firefox'\n"
    "  'oye Jarvis que hora es'\n"
    "  'Jarvis manda un mensaje a Maria'\n"
    "  'Jarvis pon musica'\n"
    "  'Jarvis que ves en la pantalla'\n\n"
    "MENTION — the speaker talks ABOUT Jarvis to another person:\n"
    "  'Jarvis es mi asistente'\n"
    "  'yo tengo un Jarvis'\n"
    "  'Jarvis puede hacer esto'\n"
    "  'le dije a Jarvis que lo hiciera'\n"
    "  'con Jarvis puedo controlar todo'\n\n"
    "Reply with EXACTLY one word: COMMAND or MENTION"
)


class WakeWordListener:
    """Continuous microphone listener with wake-word detection and intent
    classification.

    Pipeline:  mic → pw-cat → energy VAD → whisper → 'jarvis' check → LLM classify → callback
    """

    def __init__(
        self,
        jarvis_config: JarvisConfig,
        recording_config: RecordingConfig,
        whisper_config: WhisperConfig,
        llm_config: LLMConfig,
        on_command: Callable[[str], Awaitable[None]],
    ) -> None:
        self._jarvis_config = jarvis_config
        self._recording_config = recording_config
        self._llm_config = llm_config

        # Custom whisper config with --prompt to help recognize "Jarvis"
        listener_whisper = WhisperConfig(
            model_path=whisper_config.model_path,
            model_name=whisper_config.model_name,
            language=whisper_config.language,
            extra_args=f'{whisper_config.extra_args} --prompt "Jarvis"'.strip(),
        )
        self._transcriber = Transcriber(listener_whisper)
        self._on_command = on_command
        self._process: asyncio.subprocess.Process | None = None
        self._running = False
        self._suppressed = False

        # Tunable thresholds
        self._energy_threshold = jarvis_config.listen_energy_threshold
        self._silence_frames = int(
            jarvis_config.listen_silence_duration * 1000 / FRAME_MS
        )
        self._min_frames = int(
            jarvis_config.listen_min_duration * 1000 / FRAME_MS
        )
        self._max_frames = int(
            jarvis_config.listen_max_duration * 1000 / FRAME_MS
        )

    # ── Public API ───────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the listener loop (blocks until stop)."""
        self._running = True
        log.info(
            "Wake-word listener started (threshold=%d, silence=%.1fs)",
            self._energy_threshold,
            self._jarvis_config.listen_silence_duration,
        )
        while self._running:
            try:
                await self._listen_loop()
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error("Listener error, restarting in 2s: %s", e)
                await asyncio.sleep(2)
        log.info("Wake-word listener stopped")

    def stop(self) -> None:
        self._running = False
        self._kill_process()

    def suppress(self) -> None:
        """Mute the listener (call during TTS to avoid echo)."""
        self._suppressed = True

    def unsuppress(self) -> None:
        self._suppressed = False

    @property
    def is_running(self) -> bool:
        return self._running

    # ── Core loop ────────────────────────────────────────────────────

    async def _listen_loop(self) -> None:
        cmd = [
            "pw-cat", "--record",
            "--rate", str(SAMPLE_RATE),
            "--channels", str(CHANNELS),
            "--format", "s16",
            "-",
        ]
        device = self._recording_config.device
        if device and device != "default":
            cmd.insert(2, f"--target={device}")

        self._process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        assert self._process.stdout is not None

        buf = bytearray()
        silent_count = 0
        speech_count = 0
        in_speech = False

        try:
            while self._running:
                data = await self._process.stdout.readexactly(FRAME_BYTES)

                # While suppressed, discard everything and reset state
                if self._suppressed:
                    if in_speech:
                        buf.clear()
                        in_speech = False
                        speech_count = 0
                        silent_count = 0
                    continue

                rms = _rms(data)

                if rms >= self._energy_threshold:
                    if not in_speech:
                        in_speech = True
                        log.debug("Speech onset (rms=%d)", rms)
                    buf.extend(data)
                    speech_count += 1
                    silent_count = 0

                    if speech_count >= self._max_frames:
                        log.debug("Max duration, flushing")
                        await self._handle_segment(bytes(buf))
                        buf.clear()
                        in_speech = False
                        speech_count = 0

                elif in_speech:
                    buf.extend(data)
                    silent_count += 1

                    if silent_count >= self._silence_frames:
                        if speech_count >= self._min_frames:
                            log.debug(
                                "Speech segment: %d frames (%.1fs)",
                                speech_count,
                                speech_count * FRAME_MS / 1000,
                            )
                            await self._handle_segment(bytes(buf))
                        else:
                            log.debug("Too short (%d frames), skipping", speech_count)
                        buf.clear()
                        in_speech = False
                        speech_count = 0
                        silent_count = 0

        except asyncio.IncompleteReadError:
            log.debug("Audio stream EOF")
        finally:
            self._kill_process()

    # ── Speech handling ──────────────────────────────────────────────

    async def _handle_segment(self, pcm: bytes) -> None:
        """Transcribe a speech segment and check for wake word."""
        fd, wav_path = tempfile.mkstemp(suffix=".wav", prefix="jarvis_ww_")
        os.close(fd)

        try:
            # Write raw PCM as WAV
            with wave.open(wav_path, "wb") as wf:
                wf.setnchannels(CHANNELS)
                wf.setsampwidth(SAMPLE_WIDTH)
                wf.setframerate(SAMPLE_RATE)
                wf.writeframes(pcm)

            text = await self._transcriber.transcribe(Path(wav_path))
            text = text.strip()

            if not text or text.strip("[] ").upper() in (
                "BLANK_AUDIO", "BLANK AUDIO", "",
            ):
                return

            log.info("Heard: %s", text)

            # Check for wake word (including common mis-transcriptions)
            if not _contains_wake_word(text):
                return

            # Immediate audio feedback — user knows they were heard
            await play_sound(SOUND_LISTEN_START)

            # Normalize the text: replace variant with "Jarvis"
            text = _normalize_wake_word(text)
            log.info("Wake word detected: %s", text)

            if _is_mention(text):
                log.info("MENTION (ignored): %s", text)
            else:
                command = _extract_command(text)
                log.info("COMMAND: %s", command)
                asyncio.get_event_loop().create_task(self._on_command(command))

        except Exception as e:
            log.error("Segment processing failed: %s", e)
        finally:
            Path(wav_path).unlink(missing_ok=True)

    # ── Helpers ──────────────────────────────────────────────────────

    def _kill_process(self) -> None:
        if self._process and self._process.returncode is None:
            try:
                self._process.terminate()
            except ProcessLookupError:
                pass


# ── Module-level helpers ─────────────────────────────────────────────


def _rms(data: bytes) -> int:
    """RMS energy of a 16-bit PCM frame."""
    n = len(data) // SAMPLE_WIDTH
    if n == 0:
        return 0
    samples = struct.unpack(f"<{n}h", data)
    return int(math.sqrt(sum(s * s for s in samples) / n))


def _contains_wake_word(text: str) -> bool:
    """Check if text contains 'Jarvis' or any known mis-transcription."""
    words = text.lower().split()
    for word in words:
        # Strip punctuation
        clean = word.strip(".,;:!?¿¡\"'()[]")
        if clean in _JARVIS_VARIANTS:
            return True
    return False


def _normalize_wake_word(text: str) -> str:
    """Replace any Jarvis variant with the canonical 'Jarvis'."""
    words = text.split()
    result = []
    for word in words:
        clean = word.lower().strip(".,;:!?¿¡\"'()[]")
        if clean in _JARVIS_VARIANTS:
            # Preserve surrounding punctuation
            prefix = ""
            suffix = ""
            lo = word.lower()
            i = 0
            while i < len(lo) and not lo[i].isalpha():
                prefix += word[i]
                i += 1
            j = len(lo) - 1
            while j >= i and not lo[j].isalpha():
                suffix = word[j] + suffix
                j -= 1
            result.append(f"{prefix}Jarvis{suffix}")
        else:
            result.append(word)
    return " ".join(result)


def _is_mention(text: str) -> bool:
    """Fast heuristic: return True only if Jarvis is clearly being MENTIONED
    in third person, not addressed directly. Defaults to False (= treat as command)
    so the user gets fast responses."""
    lo = text.lower().strip()

    # "un jarvis", "el jarvis", "mi jarvis", "tengo jarvis" → talking ABOUT
    mention_patterns = (
        "un jarvis", "el jarvis", "mi jarvis", "tu jarvis", "su jarvis",
        "tengo jarvis", "tiene jarvis", "tienen jarvis",
        "como jarvis", "tipo jarvis", "es jarvis",
    )
    for pat in mention_patterns:
        if pat in lo:
            return True

    # "jarvis es", "jarvis puede", "jarvis tiene", "jarvis hace" → describing
    describe_patterns = (
        "jarvis es ", "jarvis puede ", "jarvis tiene ", "jarvis hace ",
        "jarvis sabe ", "jarvis sirve ", "jarvis funciona ",
    )
    for pat in describe_patterns:
        if pat in lo:
            return True

    return False


def _extract_command(text: str) -> str:
    """Strip the wake-word prefix, return the actual command."""
    lo = text.lower()
    prefixes = [
        "oye jarvis ",
        "hey jarvis ",
        "ey jarvis ",
        "eh jarvis ",
        "oiga jarvis ",
        "jarvis, ",
        "jarvis ",
    ]
    for pfx in prefixes:
        idx = lo.find(pfx)
        if idx != -1:
            rest = text[idx + len(pfx) :].strip()
            if rest:
                return rest
    return text
