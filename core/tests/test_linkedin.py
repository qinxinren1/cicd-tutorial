"""Tests for LinkedIn URL helpers (`jobpilot_core.linkedin`)."""

from jobpilot_core.linkedin import (
    canonical_linkedin_job_view_url,
    parse_linkedin_job_id,
)


def test_parse_job_id_from_view_path():
    assert (
        parse_linkedin_job_id("https://www.linkedin.com/jobs/view/4374815003")
        == "4374815003"
    )


def test_parse_job_id_from_collections_current_job_id():
    url = (
        "https://www.linkedin.com/jobs/collections/recommended/"
        "?currentJobId=4373977976"
    )
    assert parse_linkedin_job_id(url) == "4373977976"


def test_canonical_from_collections():
    url = (
        "https://www.linkedin.com/jobs/collections/recommended/"
        "?currentJobId=4373977976"
    )
    assert (
        canonical_linkedin_job_view_url(url)
        == "https://www.linkedin.com/jobs/view/4373977976"
    )


def test_parse_job_id_from_fragment():
    assert (
        parse_linkedin_job_id(
            "https://www.linkedin.com/jobs/search/#currentJobId=999"
        )
        == "999"
    )


def test_non_linkedin_returns_none():
    assert parse_linkedin_job_id("https://example.com/job/1") is None


def test_canonical_passthrough_when_no_id():
    u = "https://example.com/page"
    assert canonical_linkedin_job_view_url(u) == u
