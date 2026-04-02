"""PersonalityProfile — data contract for VarietyEngine personalities.

Recycled from nebu/agent/src/personality.py. Stripped LiveKit-specific
fields, kept the engine contract intact.
"""

from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class PersonalityProfile:
    """All cultural/behavioral data for a personality."""

    # Identity
    id: str
    display_name: str
    description: str

    # Moods: [{"name": "FOCUSED", "value": "focused", "tone": "..."}]
    moods: list[dict] = field(default_factory=list)
    default_mood: str = "neutral"
    mood_transitions: dict[str, list[str]] = field(default_factory=dict)

    # Rapport levels: [{"name": "...", "value": "...", "threshold": 0, "flavor": "..."}]
    rapport_levels: list[dict] = field(default_factory=list)

    # Catchphrases: {"pre": [...], "post": [...], "chaining": [...]}
    catchphrases: dict = field(default_factory=dict)

    # Delivery & narrative
    delivery_styles: list[str] = field(default_factory=list)
    narrative_patterns: list[str] = field(default_factory=list)
    pattern_instructions: dict[str, str] = field(default_factory=dict)
    imperfections: list[str] = field(default_factory=list)

    # Content categories
    fact_categories: list[dict] = field(default_factory=list)
    category_specifics: dict[str, list[str]] = field(default_factory=dict)

    # Wildcards
    wildcard_events: list[dict] = field(default_factory=list)

    # Time awareness
    time_flavors: dict[str, str] = field(default_factory=dict)

    # Persona anchor template
    persona_anchor_template: str = ""

    # FSM signal-to-mood mapping
    signal_mood_map: dict[str, list[str] | None] = field(default_factory=dict)

    # Labels
    chain_label: str = "TOPIC LINK"
    combo_flavor: str = "a roll"
    favorite_mention: str = "'I see you like that!'"
    personality_label: str = "helpful assistant"

    def get_mood_tone(self, mood_value: str) -> str:
        for m in self.moods:
            if m["value"] == mood_value:
                return m["tone"]
        return ""

    def get_mood_values(self) -> list[str]:
        return [m["value"] for m in self.moods]

    def get_rapport_by_turns(self, turns: int) -> dict:
        result = self.rapport_levels[0] if self.rapport_levels else {}
        for level in self.rapport_levels:
            if turns >= level["threshold"]:
                result = level
        return result
