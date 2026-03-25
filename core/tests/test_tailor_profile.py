"""Tests for profile sanitization (no network, no OpenAI)."""

from jobpilot_tailor.profile_load import sanitize_profile_for_llm


def test_sanitize_profile_removes_password_and_trims_personal():
    profile = {
        "personal": {
            "full_name": "A B",
            "email": "a@b.com",
            "phone": "+1",
            "password": "secret",
            "city": "X",
        },
        "experience": {"work_experiences": []},
    }
    out = sanitize_profile_for_llm(profile)
    assert "password" not in out.get("personal", {})
    assert "email" not in out.get("personal", {})
    assert out["personal"]["full_name"] == "A B"
    assert out["personal"]["city"] == "X"
