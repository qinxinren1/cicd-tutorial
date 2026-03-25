"""Tests for opening.txt placeholder substitution (no OpenAI)."""

from jobpilot_tailor.llm_cover_letter import apply_opening_placeholders


def test_apply_opening_placeholders_title_and_company():
    job = {"title": "Engineer", "company": "Acme"}
    text = "Apply for {title} at {company}."
    out = apply_opening_placeholders(text, job)
    assert out == "Apply for Engineer at Acme."


def test_apply_opening_placeholders_missing_title():
    job = {"title": None, "company": "X"}
    out = apply_opening_placeholders("{title} {company}", job)
    assert out == "X"
