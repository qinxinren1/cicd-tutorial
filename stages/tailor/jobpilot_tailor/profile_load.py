"""Load and sanitize ``profile.json`` for LLM prompts."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any


def load_profile(path: Path) -> dict[str, Any]:
    """Load profile JSON; raises ``FileNotFoundError`` if missing."""
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("profile.json must be a JSON object")
    return data


def sanitize_profile_for_llm(profile: dict[str, Any]) -> dict[str, Any]:
    """
    Deep-copy profile and strip secrets / high-risk PII before sending to an LLM.

    Removes ``personal.password`` and trims other ``personal`` fields to names and
    general location only (no email, phone, street).
    """
    out: dict[str, Any] = copy.deepcopy(profile)
    personal = out.get("personal")
    if isinstance(personal, dict):
        personal.pop("password", None)
        # Keep minimal identity/location for salutation and "based in" lines.
        allowed = {
            "full_name",
            "preferred_name",
            "city",
            "country",
            "province_state",
            "linkedin_url",
            "github_url",
            "portfolio_url",
            "website_url",
        }
        out["personal"] = {k: personal[k] for k in allowed if k in personal}
    return out
