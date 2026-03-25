"""Call the configured chat model to produce a cover letter."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from jobpilot_core.paths import cl_framework_opening_path

# Opening template ``opening.txt``: only ``{title}`` and ``{company}`` are substituted from the job row.

SYSTEM_PROMPT_BODY = """You are an expert career writer for the Dutch/European market. Write only paragraphs 2–4 of the cover letter (three paragraphs total). Tone: direct, concrete, not promotional.

A fixed opening is already in the user message. Do not repeat its wording, or the same biographical facts (schools, employers, metrics, named projects) unless you add a clearly new angle (e.g. a different responsibility, tool, or outcome not already stated).

Paragraph 1 — Proof you fit the role (one paragraph):
- Choose the single best-matching work experience or project from the candidate profile for this job’s core tasks (use keywords from the JOB “description” when possible).
- Structure it as Situation → Action → Result: context or constraint; what you did (tools, scope); outcome using numbers or concrete facts from the profile only.
- Prefer one deep example. Only add a second, shorter example if it fits in 2–3 sentences and does not rehash the opening.

Paragraph 2 — Why this employer (no generic praise):
- Base your points on the JOB JSON, especially “description” and “listing_description”. Name specific themes: product area, customer or domain, tech stack, team type, or problems the posting emphasises.
- Do not invent mission statements or values that do not appear in that text. Paraphrase the posting’s language rather than guessing “the company values innovation.”
- Link each point to why that matters for you, using facts from the profile where relevant.

Paragraph 3 — Closing:
- Two or three short sentences: willingness to discuss further in an interview; you may add one line on availability or next step if it fits naturally.
- Do not sign your name (added separately).

Rules:
- Candidate facts must come only from the candidate profile JSON. Job-specific claims must be grounded in the JOB JSON (especially “description”).
- Write in the language specified by the user message.
- Output exactly three paragraphs, separated by one blank line. No “Dear …”, no salutation, no sign-off with name.
"""


def job_payload_for_prompt(job: dict[str, Any]) -> dict[str, Any]:
    """Subset of DB job row relevant for tailoring."""
    return {
        "title": job.get("title"),
        "company": job.get("company"),
        "location": job.get("location"),
        "listing_description": job.get("listing_description"),
        "description": job.get("description"),
        "apply_url": job.get("apply_url"),
    }


def build_user_message_body(
    *,
    language: str,
    job_payload: dict[str, Any],
    profile: dict[str, Any],
    opening_paragraph_done: str,
) -> str:
    return (
        f"Language for the letter: {language}\n\n"
        "=== OPENING (already written; do not repeat) ===\n"
        f"{opening_paragraph_done}\n\n"
        "=== JOB ===\n"
        f"{json.dumps(job_payload, ensure_ascii=False, indent=2)}\n\n"
        "=== CANDIDATE PROFILE ===\n"
        f"{json.dumps(profile, ensure_ascii=False, indent=2)}\n"
    )


def _read_opening_template() -> str:
    """``~/.jobpilot/cl-framework/opening.txt``, ``JOBPILOT_CL_OPENING``, or ``./.jobpilot/...``."""
    candidates = [cl_framework_opening_path(), Path.cwd() / ".jobpilot" / "cl-framework" / "opening.txt"]
    for path in candidates:
        if not path.is_file():
            continue
        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError as e:
            print(f"warn: could not read opening template {path}: {e}", file=sys.stderr)
    return ""


def _safe_str(val: object | None) -> str:
    if val is None:
        return ""
    return str(val).strip()


def apply_opening_placeholders(template: str, job: dict[str, Any]) -> str:
    """Replace ``{title}`` and ``{company}`` from the job row. Other ``{...}`` tokens are left unchanged."""
    subs: dict[str, str] = {
        "title": _safe_str(job.get("title")),
        "company": _safe_str(job.get("company")),
    }
    out = template
    for key, val in subs.items():
        out = out.replace("{" + key + "}", val)
    return out.strip()


def _candidate_name(profile: dict[str, Any]) -> str:
    personal = profile.get("personal")
    if isinstance(personal, dict):
        name = personal.get("full_name") or personal.get("preferred_name")
        if name and str(name).strip():
            return str(name).strip()
    return "Candidate"


def _default_salutation() -> str:
    return os.environ.get("JOBPILOT_COVER_SALUTATION", "Dear Hiring Manager,").strip() or "Dear Hiring Manager,"


def _chat(
    client: Any,
    *,
    model: str,
    system: str,
    user: str,
    temperature: float,
) -> str:
    resp = client.chat.completions.create(
        model=model,
        temperature=temperature,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    choice = resp.choices[0].message.content
    if not choice or not str(choice).strip():
        raise RuntimeError("LLM returned empty text")
    return str(choice).strip()


def generate_cover_letter(
    *,
    job: dict[str, Any],
    profile: dict[str, Any],
    language: str | None = None,
) -> str:
    """
    Opening from ``cl-framework/opening.txt`` (``{title}``, ``{company}`` from the job row), then one
    LLM call for paragraphs 2–4. Requires ``OPENAI_API_KEY``.
    """
    try:
        from openai import OpenAI
    except ImportError as e:
        raise ImportError(
            "The tailor stage requires the 'openai' package in the same Python that runs "
            f"`jobpilot tailor` (this interpreter: {sys.executable}). "
            'Install with: pip install -e ".[tailor]". '
            "If PATH mixes conda and a venv, use: python -m jobpilot_core tailor … "
            "with the same `python` you used for `pip install`."
        ) from e

    lang = language if language is not None else os.environ.get("JOBPILOT_COVER_LETTER_LANG", "English")
    lang = (lang or "English").strip() or "English"

    model = os.environ.get("JOBPILOT_LLM_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
    client = OpenAI()
    job_payload = job_payload_for_prompt(job)

    raw_opening = _read_opening_template()
    if not raw_opening:
        raise ValueError(
            "Missing opening template: create ~/.jobpilot/cl-framework/opening.txt "
            "(or .jobpilot/cl-framework/opening.txt under the repo, or set JOBPILOT_CL_OPENING)."
        )
    opening_paragraph = apply_opening_placeholders(raw_opening, job)
    if not opening_paragraph.strip():
        raise ValueError("Opening template is empty after placeholder substitution.")

    body = _chat(
        client,
        model=model,
        system=SYSTEM_PROMPT_BODY,
        user=build_user_message_body(
            language=lang,
            job_payload=job_payload,
            profile=profile,
            opening_paragraph_done=opening_paragraph,
        ),
        temperature=0.3,
    )

    name = _candidate_name(profile)
    salutation = _default_salutation()
    closing = os.environ.get("JOBPILOT_COVER_CLOSING", "Kind regards,").strip() or "Kind regards,"

    parts = [
        salutation,
        "",
        opening_paragraph,
        "",
        body,
        "",
        closing,
        name,
    ]
    return "\n".join(parts).strip()
