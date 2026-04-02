"""Wake word detector — "Hey Jarvis" via openwakeword.

Runs on audio frames while the gate is closed (IDLE state).
When detected, calls the activation callback.

openwakeword expects 16kHz mono, 1280-sample frames (80ms).
Our PipeWire frames are 800 samples (50ms), so we buffer
two frames before feeding the model.

Install: pip install openwakeword
"""

import logging
import struct
from collections.abc import Callable

import numpy as np

log = logging.getLogger(__name__)

# openwakeword expects 1280 samples per prediction (80ms at 16kHz)
OWW_FRAME_SAMPLES = 1280
DEFAULT_THRESHOLD = 0.5


class WakeWordDetector:
    """Detect "Hey Jarvis" in audio frames."""

    def __init__(
        self,
        *,
        threshold: float = DEFAULT_THRESHOLD,
        on_detected: Callable[[], None] | None = None,
    ) -> None:
        self._threshold = threshold
        self._on_detected = on_detected
        self._model = None
        self._buffer = np.array([], dtype=np.int16)
        self._enabled = True

    def _ensure_model(self) -> None:
        if self._model is not None:
            return
        try:
            from openwakeword.model import Model
            self._model = Model()
            log.info(
                "Wake word models loaded: %s (threshold=%.2f)",
                list(self._model.models.keys()), self._threshold,
            )
        except ImportError:
            log.warning("openwakeword not installed — wake word disabled")
            self._enabled = False
        except Exception as e:
            log.error("Failed to load wake word model: %s", e)
            self._enabled = False

    def feed(self, pcm_bytes: bytes) -> bool:
        """Feed raw PCM bytes (16-bit LE mono 16kHz). Returns True on detection."""
        if not self._enabled:
            return False

        self._ensure_model()
        if self._model is None:
            return False

        # Decode PCM to numpy
        n = len(pcm_bytes) // 2
        samples = np.frombuffer(pcm_bytes, dtype=np.int16)
        self._buffer = np.concatenate([self._buffer, samples])

        # Process in 1280-sample chunks
        detected = False
        while len(self._buffer) >= OWW_FRAME_SAMPLES:
            chunk = self._buffer[:OWW_FRAME_SAMPLES]
            self._buffer = self._buffer[OWW_FRAME_SAMPLES:]

            prediction = self._model.predict(chunk)

            for model_name, score in prediction.items():
                if "jarvis" in model_name.lower() and score >= self._threshold:
                    log.info("Wake word '%s' detected (score=%.3f)", model_name, score)
                    detected = True
                    self._model.reset()
                    self._buffer = np.array([], dtype=np.int16)
                    if self._on_detected:
                        self._on_detected()
                    return True

        return detected

    def reset(self) -> None:
        """Clear buffer and model state."""
        self._buffer = np.array([], dtype=np.int16)
        if self._model:
            self._model.reset()

    @property
    def enabled(self) -> bool:
        return self._enabled
