"""Personality registry — load YAML profiles from this directory."""

from pathlib import Path

import yaml

from brain.personality import PersonalityProfile

_DIR = Path(__file__).parent
_REGISTRY: dict[str, PersonalityProfile] = {}


def _deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_profile(profile_id: str) -> PersonalityProfile:
    if profile_id in _REGISTRY:
        return _REGISTRY[profile_id]

    defaults_path = _DIR / "defaults.yaml"
    defaults = {}
    if defaults_path.exists():
        with open(defaults_path) as f:
            defaults = yaml.safe_load(f) or {}

    path = _DIR / f"{profile_id}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"No profile: {path}")

    with open(path) as f:
        data = yaml.safe_load(f) or {}

    merged = _deep_merge(defaults, data)

    # YAML parses milestone keys as int, ensure consistency
    if "catchphrases" in merged and "milestone" in merged.get("catchphrases", {}):
        merged["catchphrases"]["milestone"] = {
            int(k): v for k, v in merged["catchphrases"]["milestone"].items()
        }

    # Drop keys not in PersonalityProfile
    valid = {f.name for f in PersonalityProfile.__dataclass_fields__.values()}
    cleaned = {k: v for k, v in merged.items() if k in valid}

    profile = PersonalityProfile(**cleaned)
    _REGISTRY[profile_id] = profile
    return profile


def get_profile(profile_id: str = "jarvis") -> PersonalityProfile:
    return load_profile(profile_id)
