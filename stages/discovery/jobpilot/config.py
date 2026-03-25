"""Load ~/.jobpilot/searches.yaml and turn it into jobspy.scrape_jobs() calls."""

from __future__ import annotations

from itertools import product
from pathlib import Path
from typing import Any

import yaml

from jobpilot_core.paths import searches_config_path

# JobSpy boards cap a single search around this many rows; use when results_per_site is 0 ("as many as possible").
_JOBSPY_PRACTICAL_MAX_RESULTS = 1000


class ConfigError(ValueError):
    """Invalid or missing search configuration."""


def parse_discovery_config(
    config_path: Path | None,
) -> tuple[Path, Path | None, list[dict[str, Any]]]:
    """Return (resolved searches.yaml path, optional DB override, scrape_jobs kwargs list)."""
    path = _resolve_config_path(config_path)
    raw = _load_yaml(path)
    return path, _database_path(raw), expand_searches_to_scrape_calls(raw)


def expand_searches_to_scrape_calls(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """Expand YAML into one dict of kwargs per (query × location)."""
    defaults = dict(raw.get("defaults") or {})
    for k in ("experience_level", "database_path"):
        defaults.pop(k, None)
    rps = defaults.pop("results_per_site", None)
    if isinstance(rps, int):
        if rps > 0:
            defaults["results_wanted"] = rps
        elif rps == 0:
            defaults["results_wanted"] = _JOBSPY_PRACTICAL_MAX_RESULTS
    defaults.setdefault("site_name", "linkedin")
    defaults.setdefault("results_wanted", 25)

    terms: list[str] = []
    for q in raw.get("queries") or []:
        if isinstance(q, dict) and q.get("query"):
            t = str(q["query"]).strip()
            if t:
                terms.append(t)
    if not terms:
        raise ConfigError("searches.yaml needs at least one non-empty queries[].query.")

    locations = raw.get("locations") or []
    if not locations:
        loc_rows: list[tuple[str | None, bool]] = [
            (defaults.get("location"), False)
        ]
    else:
        loc_rows = []
        for entry in locations:
            if isinstance(entry, str):
                loc_rows.append((entry, False))
            elif isinstance(entry, dict):
                loc_rows.append(
                    (entry.get("location"), bool(entry.get("remote", False)))
                )
        if not loc_rows:
            raise ConfigError("searches.yaml locations has no valid rows.")

    calls: list[dict[str, Any]] = []
    for term, (loc, is_remote) in product(terms, loc_rows):
        kw = dict(defaults)
        kw["search_term"] = term
        loc = loc if loc else defaults.get("location")
        kw["location"] = None if loc in ("", None) else loc
        kw["is_remote"] = is_remote
        calls.append(kw)
    return calls


def _resolve_config_path(explicit: Path | None) -> Path:
    if explicit is not None:
        if not explicit.is_file():
            raise ConfigError(f"Config file not found: {explicit}")
        return explicit
    path = searches_config_path()
    if not path.is_file():
        raise ConfigError(
            f"Missing config file: {path}. "
            "Copy config/searches.yaml.example from the repository to that path and edit."
        )
    return path


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    if raw is None or not isinstance(raw, dict):
        raise ConfigError(f"{path.name} must be a mapping at the top level.")
    return raw


def _database_path(raw: dict[str, Any]) -> Path | None:
    p = raw.get("database_path")
    if p is None and isinstance(raw.get("defaults"), dict):
        p = raw["defaults"].get("database_path")
    if p is not None and str(p).strip():
        return Path(str(p)).expanduser()
    return None
