"""Flatten ``profile.json`` + job row into string values for form filling."""

from __future__ import annotations

from typing import Any

_EXPERIENCE_SKIP_KEYS = frozenset({"work_experiences", "projects", "education", "awards"})


def _nonempty_str(val: Any) -> str | None:
    if val is None:
        return None
    s = str(val).strip()
    return s or None


def _join_list(items: Any, sep: str = ", ") -> str | None:
    if not isinstance(items, list) or not items:
        return None
    parts = [_nonempty_str(x) for x in items]
    parts = [x for x in parts if x is not None]
    return sep.join(parts) if parts else None


def _bool_phrase(val: Any) -> str | None:
    if val is True:
        return "Yes"
    if val is False:
        return "No"
    return None


def _merge_leaf_dict(
    prefix: str,
    d: dict[str, Any],
    out: dict[str, str],
    *,
    skip_keys: frozenset[str] | None = None,
) -> None:
    """
    Copy scalar / bool / list-of-string leaves from ``d`` into ``out``.

    Output keys: ``{prefix}_{json_key}`` (e.g. ``education_school`` from key ``school``).
    Skips ``_*`` keys, dict values, and non-string lists. ``bullets`` → newline join; ``honors`` → ``; ``.
    """
    skip = skip_keys or frozenset()
    for k, v in d.items():
        if k.startswith("_") or k in skip:
            continue
        pk = f"{prefix}_{k}"
        if isinstance(v, bool):
            out[pk] = _bool_phrase(v) or ("Yes" if v else "No")
        elif isinstance(v, list):
            if not v:
                continue
            if not all(isinstance(x, str) for x in v):
                continue
            if k == "bullets":
                sep = "\n"
            elif k == "honors":
                sep = "; "
            else:
                sep = ", "
            joined = _join_list(v, sep)
            if joined:
                out[pk] = joined
        elif isinstance(v, dict):
            continue
        else:
            s = _nonempty_str(v)
            if s is not None:
                out[pk] = s


def flatten_profile_for_apply(profile: dict[str, Any], job: dict[str, Any]) -> dict[str, str]:
    """
    Build key → value for application forms. Keys are ``<section>_<json_field_name>`` for each
    block (e.g. ``education_school``, ``work_company``), matching leaves in ``profile.json``.

    ``personal`` fields are copied without a prefix (same names as in JSON). ``password`` is never
    included. ``cover_letter`` comes from the job row when present.
    """
    out: dict[str, str] = {}

    personal = profile.get("personal")
    if isinstance(personal, dict):
        for k, v in personal.items():
            if k == "password" or k.startswith("_"):
                continue
            if isinstance(v, bool):
                out[k] = _bool_phrase(v) or ("Yes" if v else "No")
            elif isinstance(v, list):
                continue
            elif isinstance(v, dict):
                continue
            else:
                s = _nonempty_str(v)
                if s is not None:
                    out[k] = s

    education = profile.get("education")
    if isinstance(education, list) and education:
        e0 = education[0]
        if isinstance(e0, dict):
            _merge_leaf_dict("education", e0, out)

    experience = profile.get("experience")
    if isinstance(experience, dict):
        _merge_leaf_dict("experience", experience, out, skip_keys=_EXPERIENCE_SKIP_KEYS)
        we = experience.get("work_experiences")
        if isinstance(we, list) and we:
            w0 = we[0]
            if isinstance(w0, dict):
                _merge_leaf_dict("work", w0, out)

    wa = profile.get("work_authorization")
    if isinstance(wa, dict):
        _merge_leaf_dict("work_authorization", wa, out)

    av = profile.get("availability")
    if isinstance(av, dict):
        _merge_leaf_dict("availability", av, out)

    comp = profile.get("compensation")
    if isinstance(comp, dict):
        _merge_leaf_dict("compensation", comp, out)

    eeo = profile.get("eeo_voluntary")
    if isinstance(eeo, dict):
        _merge_leaf_dict("eeo_voluntary", eeo, out)

    skills = profile.get("skills_boundary")
    if isinstance(skills, dict):
        _merge_leaf_dict("skills_boundary", skills, out)

    extras = profile.get("application_defaults")
    if isinstance(extras, dict):
        for k, v in extras.items():
            if isinstance(k, str) and k.strip():
                vs = _nonempty_str(v)
                if vs is not None:
                    out[f"extra_{k.strip()}"] = vs

    cl = _nonempty_str(job.get("cover_letter"))
    if cl is not None:
        out["cover_letter"] = cl

    return out


def available_keys(flat: dict[str, str]) -> list[str]:
    """Sorted list of keys with non-empty values (for Claude: map fields → key names only)."""
    return sorted(flat.keys())
