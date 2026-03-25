"""Tests for cover letter export helpers (no WeasyPrint required)."""

from jobpilot_tailor.cover_letter_export import (
    contact_header_html,
    cover_letter_export_paths,
    cover_letter_file_stem,
    letter_text_to_content_html,
    sanitize_job_title_for_filename,
)


def test_sanitize_job_title_for_filename():
    assert sanitize_job_title_for_filename("Foo / Bar: Baz") == "Foo_Bar_Baz"
    assert sanitize_job_title_for_filename("  Senior   SWE  ") == "Senior_SWE"
    out = sanitize_job_title_for_filename("Fast Track (September 2026) - Technical")
    assert "(" not in out and ")" not in out
    assert "?" not in out
    assert out.startswith("Fast_Track")


def test_cover_letter_file_stem_prefers_title():
    url = "https://www.linkedin.com/jobs/view/1234567890"
    job = {"title": "Software Engineer"}
    assert cover_letter_file_stem(url, job) == "Software_Engineer"


def test_cover_letter_file_stem_fallback_when_empty_title():
    url = "https://www.linkedin.com/jobs/view/1234567890"
    job = {"title": "   "}
    assert cover_letter_file_stem(url, job) == "job_1234567890"


def test_cover_letter_export_paths_uses_title():
    url = "https://www.linkedin.com/jobs/view/1234567890"
    tp, pp = cover_letter_export_paths(url, {"title": "PM Role"})
    assert tp.name == "PM_Role.txt"
    assert pp.name == "PM_Role.pdf"
    assert tp.parent == pp.parent


def test_cover_letter_file_stem_linkedin_id_without_job():
    assert (
        cover_letter_file_stem("https://www.linkedin.com/jobs/view/1234567890")
        == "job_1234567890"
    )


def test_cover_letter_file_stem_hash_when_no_id():
    a = cover_letter_file_stem("https://example.com/job/1")
    b = cover_letter_file_stem("https://example.com/job/1")
    c = cover_letter_file_stem("https://example.com/job/2")
    assert a == b
    assert a.startswith("cover_")
    assert a != c


def test_contact_header_html_skips_password():
    profile = {
        "personal": {
            "full_name": "A B",
            "email": "a@b.com",
            "password": "secret",
        }
    }
    h = contact_header_html(profile)
    assert "secret" not in h
    assert "A B" in h
    assert "a@b.com" in h
    assert "header-name" in h


def test_contact_header_prefers_full_name_not_duplicate_preferred():
    profile = {
        "personal": {
            "full_name": "Qinxin Ren",
            "preferred_name": "Qinxin",
            "email": "x@y.com",
        }
    }
    h = contact_header_html(profile)
    assert "Qinxin Ren" in h
    assert h.count("Qinxin") == 1  # only in full name, not a second line


def test_contact_header_location_one_line():
    profile = {
        "personal": {
            "full_name": "A B",
            "city": "Rotterdam",
            "province_state": "South Holland",
            "country": "Netherlands",
        }
    }
    h = contact_header_html(profile)
    assert "Rotterdam, South Holland, Netherlands" in h


def test_contact_header_linkedin_short_label():
    url = "https://www.linkedin.com/in/example-very-long-name-12345"
    profile = {"personal": {"full_name": "A B", "linkedin_url": url}}
    h = contact_header_html(profile)
    assert "header-links" in h
    assert "header-link" in h
    assert url in h  # in href
    assert ">LinkedIn<" in h or "LinkedIn</a>" in h


def test_contact_header_email_and_phone_one_line():
    profile = {
        "personal": {
            "full_name": "A B",
            "email": "a@b.com",
            "phone": "+1 234",
        }
    }
    h = contact_header_html(profile)
    assert "a@b.com · +1 234" in h


def test_contact_header_social_links_single_row():
    profile = {
        "personal": {
            "full_name": "A B",
            "linkedin_url": "https://linkedin.com/in/a",
            "github_url": "https://github.com/a",
            "portfolio_url": "https://a.dev",
        }
    }
    h = contact_header_html(profile)
    assert "header-links" in h
    assert "LinkedIn</a>" in h or ">LinkedIn<" in h
    assert "GitHub</a>" in h or ">GitHub<" in h
    assert "Portfolio</a>" in h or ">Portfolio<" in h
    assert "header-link-sep" in h
    # All three anchors live in one header-links span (not three separate header-line blocks)
    assert h.count("header-line") == 0  # no extra per-link lines


def test_letter_text_to_content_html_paragraphs():
    html = letter_text_to_content_html("Line1\nLine2\n\nPara2")
    assert "<p>" in html
    assert "Line1" in html
    assert "<br>" in html
    assert "Para2" in html
