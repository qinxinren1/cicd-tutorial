"""Tests for SQLite persistence (no network)."""

from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from jobpilot_core.storage import (
    STAGE_APPLIED,
    STAGE_APPLY_FAILED,
    STAGE_TAILOR_FAILED,
    STAGE_TAILORED,
    apply_job_application,
    apply_job_enrichment,
    apply_job_tailoring,
    fetch_job,
    open_database,
    persist_jobs,
)


def test_persist_jobs_inserts_and_skips_existing_url():
    df = pd.DataFrame(
        [
            {
                "job_url": "https://example.com/job/1",
                "title": "Engineer",
                "description": "Short blurb",
                "location": "Amsterdam, NL",
                "site": "linkedin",
            }
        ]
    )

    with TemporaryDirectory() as td:
        db_path = Path(td) / "jobs.db"
        conn = open_database(db_path)
        try:
            assert persist_jobs(conn, df) == 1
            cur = conn.execute(
                "SELECT url, title, company, listing_description, location, site, stage FROM jobs"
            )
            row = cur.fetchone()
            assert row[0] == "https://example.com/job/1"
            assert row[1] == "Engineer"
            assert row[2] is None
            assert row[3] == "Short blurb"
            assert row[4] == "Amsterdam, NL"
            assert row[5] == "linkedin"
            assert row[6] == "discovered"

            df2 = df.copy()
            df2.at[0, "title"] = "Senior Engineer"
            assert persist_jobs(conn, df2) == 0
            cur = conn.execute("SELECT title FROM jobs WHERE url = ?", (row[0],))
            assert cur.fetchone()[0] == "Engineer"
        finally:
            conn.close()


def test_persist_jobs_normalizes_linkedin_job_url():
    """Same job, different LinkedIn URL shapes → one row (canonical ``/jobs/view/{id}``)."""
    canonical = "https://www.linkedin.com/jobs/view/123456"
    with TemporaryDirectory() as td:
        db_path = Path(td) / "jobs.db"
        conn = open_database(db_path)
        try:
            df1 = pd.DataFrame(
                [
                    {
                        "job_url": "https://www.linkedin.com/jobs/collections/recommended/?currentJobId=123456",
                        "title": "First",
                        "description": "d",
                        "location": "L",
                        "site": "linkedin",
                    }
                ]
            )
            assert persist_jobs(conn, df1) == 1
            df2 = pd.DataFrame(
                [
                    {
                        "job_url": "https://www.linkedin.com/jobs/view/123456?trk=foo",
                        "title": "Second",
                        "description": "d2",
                        "location": "L",
                        "site": "linkedin",
                    }
                ]
            )
            assert persist_jobs(conn, df2) == 0
            assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
            row = conn.execute("SELECT url, title FROM jobs").fetchone()
            assert row[0] == canonical
            assert row[1] == "First"
        finally:
            conn.close()


def test_discover_does_not_overwrite_listing_after_enrich():
    url = "https://www.linkedin.com/jobs/view/42"
    with TemporaryDirectory() as td:
        db_path = Path(td) / "jobs.db"
        conn = open_database(db_path)
        try:
            df1 = pd.DataFrame(
                [
                    {
                        "job_url": url,
                        "title": "Listing title",
                        "description": "snippet",
                        "location": "Utrecht",
                        "site": "linkedin",
                    }
                ]
            )
            assert persist_jobs(conn, df1) == 1
            apply_job_enrichment(
                conn,
                url,
                description="Full JD",
                apply_url="https://apply.example",
                error=None,
            )
            df2 = pd.DataFrame(
                [
                    {
                        "job_url": url,
                        "title": "New scrape title",
                        "description": "new snippet",
                        "location": "Amsterdam",
                        "site": "linkedin",
                    }
                ]
            )
            assert persist_jobs(conn, df2) == 0
            row = conn.execute(
                "SELECT title, listing_description, location, stage FROM jobs WHERE url = ?",
                (url,),
            ).fetchone()
            assert row[0] == "Listing title"
            assert row[1] == "snippet"
            assert row[2] == "Utrecht"
            assert row[3] == "enriched"
        finally:
            conn.close()


def test_empty_dataframe():
    df = pd.DataFrame()
    with TemporaryDirectory() as td:
        conn = open_database(Path(td) / "x.db")
        try:
            assert persist_jobs(conn, df) == 0
        finally:
            conn.close()


def test_tailor_columns_and_apply_job_tailoring():
    url = "https://www.linkedin.com/jobs/view/99"
    with TemporaryDirectory() as td:
        db_path = Path(td) / "jobs.db"
        conn = open_database(db_path)
        try:
            df = pd.DataFrame(
                [
                    {
                        "job_url": url,
                        "title": "PM",
                        "description": "snippet",
                        "location": "NL",
                        "site": "linkedin",
                    }
                ]
            )
            assert persist_jobs(conn, df) == 1
            apply_job_enrichment(
                conn,
                url,
                description="Full JD text here.",
                apply_url="https://apply.example",
                error=None,
            )
            letter = "Para1\n\nPara2\n\nPara3\n\nPara4\n"
            apply_job_tailoring(conn, url, cover_letter=letter)
            row = fetch_job(conn, url)
            assert row is not None
            assert row["stage"] == STAGE_TAILORED
            assert row["cover_letter"] == letter.strip()
            assert row["tailored_at"] is not None
            assert row["last_error"] is None

            apply_job_tailoring(conn, url, error="api down")
            row2 = fetch_job(conn, url)
            assert row2["stage"] == STAGE_TAILOR_FAILED
            assert row2["last_error"] == "api down"
            assert row2["cover_letter"] == letter.strip()
        finally:
            conn.close()


def test_apply_job_application():
    url = "https://www.linkedin.com/jobs/view/100"
    with TemporaryDirectory() as td:
        db_path = Path(td) / "jobs.db"
        conn = open_database(db_path)
        try:
            df = pd.DataFrame(
                [
                    {
                        "job_url": url,
                        "title": "Dev",
                        "description": "snippet",
                        "location": "NL",
                        "site": "linkedin",
                    }
                ]
            )
            assert persist_jobs(conn, df) == 1
            apply_job_enrichment(
                conn,
                url,
                description="JD",
                apply_url="https://apply.example",
                error=None,
            )
            apply_job_tailoring(conn, url, cover_letter="Hello\n")
            apply_job_application(conn, url, error=None)
            row = fetch_job(conn, url)
            assert row is not None
            assert row["stage"] == STAGE_APPLIED
            assert row["applied_at"] is not None
            assert row["last_error"] is None

            apply_job_application(conn, url, error="timeout")
            row2 = fetch_job(conn, url)
            assert row2["stage"] == STAGE_APPLY_FAILED
            assert row2["last_error"] == "timeout"
        finally:
            conn.close()
