"""Tests for enrich helpers and job storage (no network)."""

import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from jobpilot_enrich.apply_dom import extract_apply_from_linkedin_html, parse_linkedin_job_html
from jobpilot_enrich import enrich as enrich_mod
from jobpilot_core.storage import (
    STAGE_DISCOVERED,
    STAGE_ENRICHED,
    STAGE_ENRICH_FAILED,
    apply_job_enrichment,
    open_database,
)


def _pending_enrichment_urls(conn, limit: int = 10) -> list[str]:
    cur = conn.execute(
        """
        SELECT url FROM jobs
        WHERE url LIKE '%linkedin.com/jobs/view%'
          AND stage IN (?, ?)
        LIMIT ?
        """,
        (STAGE_DISCOVERED, STAGE_ENRICH_FAILED, limit),
    )
    return [row[0] for row in cur.fetchall()]


def test_extract_apply_from_code_apply_url():
    html = """
    <html><body>
    <code id="applyUrl">https://www.linkedin.com/redir/redirect?url=https%3A%2F%2Fboards.greenhouse.io%2Fx%2Fjobs%2F1</code>
    </body></html>
    """
    assert (
        extract_apply_from_linkedin_html(html)
        == "https://boards.greenhouse.io/x/jobs/1"
    )


def test_extract_apply_from_aria_apply_on_company_website():
    html = """
    <html><body>
    <a href="https://www.linkedin.com/redir/redirect/?url=https%3A%2F%2Fmiro.com%2Fcareers%2Fvacancy%2F1"
       aria-label="Apply on company website">Apply</a>
    </body></html>
    """
    assert extract_apply_from_linkedin_html(html) == "https://miro.com/careers/vacancy/1"


def test_extract_linkedin_job_metadata_top_card():
    html = """
    <html><body>
    <div class="job-details-jobs-unified-top-card__card-contents">
    <h1 class="job-details-jobs-unified-top-card__job-title">Software Engineer</h1>
    <a class="job-details-jobs-unified-top-card__company-name">Example Inc</a>
    <span class="job-details-jobs-unified-top-card__bullet">London, UK</span>
    </div>
    </body></html>
    """
    p = parse_linkedin_job_html(html)
    assert p["title"] == "Software Engineer"
    assert p["company"] == "Example Inc"
    assert p["location"] == "London, UK"


def test_extract_linkedin_job_metadata_same_top_card_region_as_apply():
    """Same ``top-card`` / ``job-details-jobs-unified-top-card`` subtree as apply heuristics."""
    html = """
    <html><body>
    <div class="job-details-jobs-unified-top-card__card-contents">
      <h1>Fast Track Trainee</h1>
      <a href="https://www.linkedin.com/company/picnic-nl/">Picnic</a>
      <span class="tvm__text tvm__text--low-emphasis job-details-jobs-unified-top-card__bullet">
        Internship
      </span>
      <span class="job-details-jobs-unified-top-card__bullet">Netherlands</span>
    </div>
    </body></html>
    """
    p = parse_linkedin_job_html(html)
    assert p["title"] == "Fast Track Trainee"
    assert p["company"] == "Picnic"
    assert p["location"] == "Netherlands"


def test_extract_apply_prefers_code_block():
    html = """
    <html><body>
    <code id="applyUrl">?url=https%3A%2F%2Fexample.com%2Fapply</code>
    <a href="https://other.com">Apply</a>
    </body></html>
    """
    assert extract_apply_from_linkedin_html(html) == "https://example.com/apply"


def test_pending_enrichment_queue():
    with TemporaryDirectory() as td:
        db = Path(td) / "t.db"
        conn = open_database(db)
        try:
            conn.execute(
                """
                INSERT INTO jobs (
                    url, title, company, listing_description, location, site,
                    discovered_at, stage
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "https://www.linkedin.com/jobs/view/1",
                    "T",
                    None,
                    "d",
                    "L",
                    "linkedin",
                    "2020-01-01T00:00:00+00:00",
                    STAGE_DISCOVERED,
                ),
            )
            conn.execute(
                """
                INSERT INTO jobs (
                    url, title, company, listing_description, location, site,
                    discovered_at, stage
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "https://www.linkedin.com/jobs/view/2",
                    "T2",
                    None,
                    "d",
                    "L",
                    "linkedin",
                    "2020-01-01T00:00:00+00:00",
                    STAGE_DISCOVERED,
                ),
            )
            conn.commit()

            pending = _pending_enrichment_urls(conn, 10)
            assert len(pending) == 2

            apply_job_enrichment(
                conn,
                pending[0],
                description="full",
                apply_url="https://apply.example",
                error=None,
            )
            pending2 = _pending_enrichment_urls(conn, 10)
            assert len(pending2) == 1
            assert pending2[0] == pending[1]
        finally:
            conn.close()


def test_enrich_main_persists_job_enrichment(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        enrich_mod,
        "fetch_linkedin_job_details_jobspy",
        lambda jid: {
            "description": "The JD",
            "job_url_direct": "https://apply.example/job/1",
        },
    )
    monkeypatch.setattr(
        enrich_mod,
        "fetch_url_html",
        lambda url, state_path=None: """
            <html><body>
            <div class="job-details-jobs-unified-top-card__card-contents">
            <h1 class="job-details-jobs-unified-top-card__job-title">DOM Title</h1>
            <a class="job-details-jobs-unified-top-card__company-name">DOM Co</a>
            <span class="job-details-jobs-unified-top-card__bullet">Utrecht</span>
            </div>
            </body></html>
            """,
    )
    db = tmp_path / "jobs.db"
    monkeypatch.setattr(enrich_mod, "default_database_path", lambda: db)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "jobpilot enrich",
            "https://www.linkedin.com/jobs/view/999",
        ],
    )
    enrich_mod.main()
    capsys.readouterr()
    conn = open_database(db)
    try:
        row = conn.execute(
            """
            SELECT url, title, company, location, description, apply_url, last_error, stage
            FROM jobs
            """
        ).fetchone()
        assert row[0] == "https://www.linkedin.com/jobs/view/999"
        assert row[1] == "DOM Title"
        assert row[2] == "DOM Co"
        assert row[3] == "Utrecht"
        assert row[4] == "The JD"
        assert row[5] == "https://apply.example/job/1"
        assert row[6] is None
        assert row[7] == STAGE_ENRICHED
    finally:
        conn.close()


def test_has_description_and_apply_url():
    h = enrich_mod._has_description_and_apply_url
    assert h({"description": "JD text", "apply_url": "https://apply.example/1"})
    assert not h({"description": "JD text", "apply_url": None})
    assert not h({"description": "JD text", "apply_url": ""})
    assert not h({"description": "", "apply_url": "https://apply.example/1"})
