"""Call Claude Code CLI to map form field indices → profile keys (no secret values in the prompt)."""

from __future__ import annotations

import json
import os
import re
import subprocess
from typing import Any


def _strip_json_fence(text: str) -> str:
    t = text.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", t)
    if m:
        return m.group(1).strip()
    return t


def _parse_claude_stdout(raw: bytes) -> str:
    """Decode CLI JSON wrapper; return the assistant text in ``result``."""
    text = raw.decode("utf-8", errors="replace").strip()
    if not text:
        return ""
    try:
        outer = json.loads(text)
    except json.JSONDecodeError:
        return text
    if isinstance(outer, dict) and "result" in outer:
        return str(outer.get("result") or "").strip()
    return text


def build_mapping_prompt(
    *,
    fields: list[dict[str, Any]],
    available_keys: list[str],
    job_title: str | None,
    company: str | None,
) -> str:
    jt = (job_title or "").strip() or "(unknown)"
    co = (company or "").strip() or "(unknown)"
    return (
        "You map job application form fields to profile data keys.\n\n"
        f"JOB: {jt} at {co}\n\n"
        "FORM_FIELDS (JSON array; index order matches visible DOM order):\n"
        f"{json.dumps(fields, ensure_ascii=False, indent=2)}\n\n"
        "AVAILABLE_PROFILE_KEYS (use exactly these strings, or the literal skip for optional/unknown):\n"
        f"{json.dumps(available_keys, ensure_ascii=False)}\n\n"
        "Rules:\n"
        '- Map obvious email fields to "email"; phone/tel/mobile to "phone"; '
        'given/first/last/full name to "full_name" or "preferred_name".\n'
        '- Motivation/cover/motivation letter / letter / why us → "cover_letter".\n'
        '- LinkedIn → "linkedin_url"; GitHub → "github_url"; portfolio/website → matching keys.\n'
        '- Address: postal/zip → "postal_code"; city/town → "city"; country → "country"; state/province → "province_state".\n'
        '- Education (school, degree, major/field, dates, GPA) → education_* keys (e.g. education_school, education_field, education_start_date).\n'
        '- Work history → work_* keys (e.g. work_company, work_title, work_description, work_start_date).\n'
        '- Salary/compensation → keys like compensation_salary_expectation (from JSON under compensation).\n'
        '- Visa/sponsorship → work_authorization_* (e.g. work_authorization_work_permit_type).\n'
        '- EEO/diversity → eeo_voluntary_*.\n'
        '- Skills → skills_boundary_* (lists are comma-separated in the profile).\n'
        '- File uploads and captchas → skip.\n'
        '- If unsure, use skip.\n'
        "- Do not invent keys outside AVAILABLE_PROFILE_KEYS.\n\n"
        "Return ONLY valid JSON (no markdown fences) with this exact shape:\n"
        '{"fills":[{"index":0,"key":"email"},{"index":1,"key":"skip"}]}\n'
    )


def run_claude_mapping(prompt: str, *, timeout_sec: int = 300) -> str:
    """
    Invoke ``claude -p ... --output-format=json``. ``JOBPILOT_CLAUDE_BIN`` overrides the binary name.
    """
    exe = os.environ.get("JOBPILOT_CLAUDE_BIN", "claude").strip() or "claude"
    cmd = [exe, "-p", prompt, "--output-format=json"]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        timeout=timeout_sec,
        check=False,
    )
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", errors="replace").strip()
        out = proc.stdout.decode("utf-8", errors="replace").strip()
        msg = err or out or f"exit {proc.returncode}"
        raise RuntimeError(f"claude CLI failed: {msg}")
    return _parse_claude_stdout(proc.stdout)


def parse_fills_json(text: str) -> list[dict[str, Any]]:
    """Parse {\"fills\": [...]} from model output."""
    inner = _strip_json_fence(text)
    data = json.loads(inner)
    fills = data.get("fills")
    if not isinstance(fills, list):
        raise ValueError("missing fills array")
    out: list[dict[str, Any]] = []
    for item in fills:
        if not isinstance(item, dict):
            continue
        idx = item.get("index")
        key = item.get("key")
        if not isinstance(idx, int):
            continue
        if key == "skip" or key is None:
            out.append({"index": idx, "key": "skip"})
        elif isinstance(key, str) and key.strip():
            out.append({"index": idx, "key": key.strip()})
    return out


def heuristic_fills(fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keyword-based mapping when Claude CLI is unavailable."""
    out: list[dict[str, Any]] = []
    for i, f in enumerate(fields):
        blob = " ".join(
            str(f.get(k) or "")
            for k in ("label", "aria_label", "name", "id", "placeholder")
        ).lower()
        key = "skip"
        if "cover" in blob or "motivation" in blob or (
            "letter" in blob and "newsletter" not in blob
        ):
            key = "cover_letter"
        elif "email" in blob or blob.endswith(" e-mail"):
            key = "email"
        elif "phone" in blob or "tel" in blob or "mobile" in blob:
            key = "phone"
        elif "linkedin" in blob:
            key = "linkedin_url"
        elif "github" in blob or "git hub" in blob:
            key = "github_url"
        elif "first" in blob and "name" in blob:
            key = "preferred_name"
        elif "full name" in blob or ("name" in blob and "company" not in blob and "last" not in blob):
            key = "full_name"
        elif "zip" in blob or "postal" in blob or "post code" in blob:
            key = "postal_code"
        elif "city" in blob or "town" in blob:
            key = "city"
        elif "country" in blob or "nation" in blob:
            key = "country"
        elif "state" in blob or "province" in blob:
            key = "province_state"
        elif "salary" in blob or "compensation" in blob or "pay" in blob or "wage" in blob:
            key = "compensation_salary_expectation"
        elif "sponsor" in blob or "visa" in blob or "work author" in blob or "legally" in blob:
            key = "work_authorization_work_permit_type"
        elif "gender" in blob:
            key = "eeo_voluntary_gender"
        elif "race" in blob or "ethnicity" in blob:
            key = "eeo_voluntary_race_ethnicity"
        elif "disability" in blob:
            key = "eeo_voluntary_disability_status"
        elif "gpa" in blob or "grade" in blob:
            key = "education_gpa"
        elif "university" in blob or "school" in blob or "college" in blob:
            key = "education_school"
        elif "degree" in blob and "education" in blob:
            key = "education_degree"
        elif "employer" in blob or "company" in blob and "name" in blob:
            key = "work_company"
        elif "job title" in blob or "position" in blob:
            key = "work_title"
        out.append({"index": i, "key": key})
    return out
