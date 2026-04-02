"""Variety Engine — anti-repetition + personality state machine.

Recycled from nebu/agent/src/variety.py. Core mechanics preserved:
- Mood FSM with signal-reactive transitions
- Memory tracker (deque-based anti-repetition)
- Persona anchor re-injection
- Narrative pattern dedup
- Sliding summary compression
- Imperfection injection (organic feel)

Stripped: child-specific language, culture hype system, LiveKit deps.
"""

import random
import time
from collections import deque
from dataclasses import dataclass, field

from brain.personality import PersonalityProfile

WILDCARD_CHANCE = 0.12
IMPERFECTION_CHANCE = 0.15


@dataclass
class MemoryTracker:
    """Session-level anti-repetition state."""

    styles_used: deque = field(default_factory=lambda: deque(maxlen=4))
    catchphrases_used: dict = field(
        default_factory=lambda: {"pre": deque(maxlen=4), "post": deque(maxlen=4)}
    )
    pattern_history: deque = field(default_factory=lambda: deque(maxlen=6))
    responses: deque = field(default_factory=lambda: deque(maxlen=8))
    topics_used: deque = field(default_factory=lambda: deque(maxlen=12))

    def record_response(self, text: str):
        condensed = text.strip()[:100]
        if condensed:
            self.responses.append(condensed)

    def record_topic(self, topic: str):
        self.topics_used.append(topic)


@dataclass
class VarietyEngine:
    """Personality-driven variety engine.

    Feed it user signals, get back prompt modifiers that prevent
    repetitive responses and maintain character consistency.
    """

    profile: PersonalityProfile
    memory: MemoryTracker = field(default_factory=MemoryTracker)

    _mood_value: str = ""
    _mood_history: deque = field(default_factory=lambda: deque(maxlen=5))
    turn_count: int = 0
    _session_start: float = field(default_factory=time.time)
    _last_imperfection: bool = False

    def __post_init__(self):
        if not self._mood_value:
            self._mood_value = self.profile.default_mood

    # ── Mood ──────────────────────────────────────────────────────

    @property
    def mood(self) -> str:
        return self._mood_value

    def evolve_mood(self) -> str:
        possible = self.profile.mood_transitions.get(
            self._mood_value, self.profile.get_mood_values()
        )
        if self._mood_history:
            possible = [m for m in possible if m != self._mood_history[-1]] or possible
        new = random.choice(possible)
        self._mood_history.append(self._mood_value)
        self._mood_value = new
        return new

    def get_mood_instruction(self) -> str:
        return self.profile.get_mood_tone(self._mood_value)

    def react_to_signal(self, signal: str):
        """Adjust mood based on detected user signal."""
        options = self.profile.signal_mood_map.get(signal)
        if options:
            self._mood_history.append(self._mood_value)
            self._mood_value = random.choice(options)

    # ── Rapport ───────────────────────────────────────────────────

    @property
    def rapport(self) -> dict:
        return self.profile.get_rapport_by_turns(self.turn_count)

    # ── Anti-repetition picks ─────────────────────────────────────

    def _pick_unique(self, options: list, used: deque):
        available = [x for x in options if x not in used]
        if not available:
            used.clear()
            available = options
        chosen = random.choice(available)
        used.append(chosen)
        return chosen

    def pick_delivery_style(self) -> str:
        return self._pick_unique(self.profile.delivery_styles, self.memory.styles_used)

    def pick_catchphrase(self, kind: str) -> str:
        options = self.profile.catchphrases.get(kind, [])
        if not options:
            return ""
        if kind in self.memory.catchphrases_used:
            return self._pick_unique(options, self.memory.catchphrases_used[kind])
        return random.choice(options)

    def roll_wildcard(self) -> str | None:
        if self.profile.wildcard_events and random.random() < WILDCARD_CHANCE:
            return random.choice(self.profile.wildcard_events).get("inject", "")
        return None

    # ── Patches ───────────────────────────────────────────────────

    def build_persona_anchor(self) -> str:
        """Every 5 turns, re-inject condensed identity."""
        if self.turn_count == 0 or self.turn_count % 5 != 0:
            return ""
        if not self.profile.persona_anchor_template:
            return ""
        return self.profile.persona_anchor_template.format(
            mood=self._mood_value,
            rapport=self.rapport.get("value", ""),
        )

    def pick_narrative_pattern(self) -> str:
        patterns = self.profile.narrative_patterns
        if not patterns:
            return ""
        return self._pick_unique(patterns, self.memory.pattern_history)

    def build_sliding_summary(self) -> str:
        """Every 10 turns, compress recent history."""
        if self.turn_count < 10 or self.turn_count % 10 != 0:
            return ""
        recent_topics = list(self.memory.topics_used)[-5:]
        recent_patterns = list(self.memory.pattern_history)[-5:]
        return (
            f"\n[SUMMARY turns {self.turn_count - 10}-{self.turn_count}]: "
            f"Topics covered: {', '.join(recent_topics)}. "
            f"Patterns used: {', '.join(recent_patterns)}. "
            f"Mood: {self._mood_value}. "
            f"VARY: use different topics and patterns than those in the summary."
        )

    def maybe_imperfection(self) -> str:
        if not self.profile.imperfections:
            return ""
        if self._last_imperfection:
            self._last_imperfection = False
            return ""
        if random.random() > IMPERFECTION_CHANCE:
            return ""
        self._last_imperfection = True
        return random.choice(self.profile.imperfections)

    # ── Time ──────────────────────────────────────────────────────

    def get_time_flavor(self, hour: int | None = None) -> str:
        if hour is None:
            hour = time.localtime().tm_hour
        flavors = self.profile.time_flavors
        if 6 <= hour < 12:
            return flavors.get("morning", "")
        elif 12 <= hour < 18:
            return flavors.get("afternoon", "")
        elif 18 <= hour < 21:
            return flavors.get("evening", "")
        return flavors.get("late_night", "")

    # ── Turn management ───────────────────────────────────────────

    def tick(self):
        self.turn_count += 1
        if self.turn_count % random.randint(3, 5) == 0:
            self.evolve_mood()

    @property
    def session_minutes(self) -> float:
        return (time.time() - self._session_start) / 60
