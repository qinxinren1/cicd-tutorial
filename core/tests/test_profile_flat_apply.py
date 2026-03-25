"""Tests for apply-stage profile flattening (no Playwright)."""

from jobpilot_apply.profile_flat import available_keys, flatten_profile_for_apply


def test_flatten_profile_includes_personal_and_cover_letter():
    profile = {
        "personal": {
            "full_name": "A B",
            "email": "a@b.com",
            "phone": "+310000",
            "city": "Amsterdam",
            "postal_code": "1234 AB",
            "password": "secret",
        },
        "education": [
            {
                "school": "Uni",
                "degree": "MSc",
                "field": "CS",
                "start_date": "2023-09",
                "end_date": "2025-12",
                "gpa": "8.5",
                "honors": ["Cum Laude"],
            }
        ],
        "experience": {
            "work_experiences": [
                {
                    "company": "Acme",
                    "title": "Dev",
                    "start_date": "2024-01",
                    "end_date": None,
                    "bullets": ["Did X", "Did Y"],
                }
            ],
        },
        "work_authorization": {"legally_authorized_to_work": True, "work_permit_type": "Search Year"},
    }
    job = {"cover_letter": "Dear…"}
    flat = flatten_profile_for_apply(profile, job)
    assert flat["email"] == "a@b.com"
    assert flat["cover_letter"] == "Dear…"
    assert flat["education_school"] == "Uni"
    assert flat["education_field"] == "CS"
    assert flat["education_start_date"] == "2023-09"
    assert flat["work_company"] == "Acme"
    assert flat["work_bullets"] == "Did X\nDid Y"
    assert "work_description" not in flat
    assert flat["postal_code"] == "1234 AB"
    assert flat["work_authorization_work_permit_type"] == "Search Year"
    assert "password" not in flat
    keys = available_keys(flat)
    assert "email" in keys
    assert "cover_letter" in keys
