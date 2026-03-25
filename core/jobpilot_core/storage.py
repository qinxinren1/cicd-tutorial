"""SQLite persistence: single ``jobs`` table with pipeline ``stage``."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from jobpilot_core.linkedin import canonical_linkedin_job_view_url

STAGE_DISCOVERED = "discovered"
STAGE_ENRICHED = "enriched"
STAGE_ENRICH_FAILED = "enrich_failed"
STAGE_TAILORED = "tailored"
STAGE_TAILOR_FAILED = "tailor_failed"
STAGE_APPLIED = "applied"
STAGE_APPLY_FAILED = "apply_failed"

JOBS_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS jobs (
    url TEXT PRIMARY KEY NOT NULL,
    title TEXT,
    company TEXT,
    listing_description TEXT,
    description TEXT,
    location TEXT,
    site TEXT,
    discovered_at TEXT NOT NULL,
    apply_url TEXT,
    enriched_at TEXT,
    last_error TEXT,
    cover_letter TEXT,
    tailored_at TEXT,
    applied_at TEXT,
    stage TEXT NOT NULL DEFAULT 'discovered'
);
"""

INSERT_DISCOVER_SQL = """
INSERT INTO jobs (
    url, title, company, listing_description, location, site, discovered_at, stage
)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(url) DO NOTHING
"""

UPSERT_ENRICH_SQL = """
INSERT INTO jobs (
    url, title, company, listing_description, location, site, discovered_at,
    description, apply_url, enriched_at, last_error, stage
)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(url) DO UPDATE SET
    description = excluded.description,
    apply_url = excluded.apply_url,
    enriched_at = excluded.enriched_at,
    last_error = excluded.last_error,
    stage = excluded.stage,
    title = COALESCE(excluded.title, jobs.title),
    company = COALESCE(excluded.company, jobs.company),
    location = COALESCE(excluded.location, jobs.location);
"""


def _ensure_jobs_columns(conn: sqlite3.Connection) -> None:
    cur = conn.execute("PRAGMA table_info(jobs)")
    cols = {row[1] for row in cur.fetchall()}
    if "company" not in cols:
        conn.execute("ALTER TABLE jobs ADD COLUMN company TEXT")
    if "cover_letter" not in cols:
        conn.execute("ALTER TABLE jobs ADD COLUMN cover_letter TEXT")
    if "tailored_at" not in cols:
        conn.execute("ALTER TABLE jobs ADD COLUMN tailored_at TEXT")
    if "applied_at" not in cols:
        conn.execute("ALTER TABLE jobs ADD COLUMN applied_at TEXT")


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(JOBS_SCHEMA_SQL)
    _ensure_jobs_columns(conn)
    conn.commit()


def open_database(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    ensure_schema(conn)
    return conn


def fetch_job(conn: sqlite3.Connection, url: str) -> dict[str, Any] | None:
    """Return one job row as a dict, or ``None`` if ``url`` is missing."""
    cur = conn.execute(
        """
        SELECT url, title, company, listing_description, description, location,
               site, discovered_at, apply_url, enriched_at, last_error,
               cover_letter, tailored_at, applied_at, stage
        FROM jobs WHERE url = ?
        """,
        (url,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    keys = (
        "url",
        "title",
        "company",
        "listing_description",
        "description",
        "location",
        "site",
        "discovered_at",
        "apply_url",
        "enriched_at",
        "last_error",
        "cover_letter",
        "tailored_at",
        "applied_at",
        "stage",
    )
    return dict(zip(keys, row, strict=True))


def apply_job_tailoring(
    conn: sqlite3.Connection,
    url: str,
    *,
    cover_letter: str | None = None,
    error: str | None = None,
) -> None:
    """
    Record tailor stage: ``cover_letter``, ``tailored_at``, and ``stage``.

    On success (``error`` is None) → ``stage`` = ``tailored`` and ``last_error`` cleared.
    On failure → ``stage`` = ``tailor_failed`` and ``last_error`` set; existing
    ``cover_letter`` is left unchanged.
    """
    now = datetime.now(timezone.utc).isoformat()
    if error:
        conn.execute(
            """
            UPDATE jobs SET stage = ?, last_error = ?
            WHERE url = ?
            """,
            (STAGE_TAILOR_FAILED, error, url),
        )
    else:
        if cover_letter is None or not str(cover_letter).strip():
            raise ValueError("cover_letter is required when error is None")
        conn.execute(
            """
            UPDATE jobs SET cover_letter = ?, tailored_at = ?, stage = ?, last_error = NULL
            WHERE url = ?
            """,
            (cover_letter.strip(), now, STAGE_TAILORED, url),
        )
    conn.commit()


def apply_job_application(
    conn: sqlite3.Connection,
    url: str,
    *,
    error: str | None = None,
) -> None:
    """
    Record apply stage: ``applied_at`` and ``stage``.

    On success (``error`` is None) → ``stage`` = ``applied`` and ``last_error`` cleared.
    On failure → ``stage`` = ``apply_failed`` and ``last_error`` set.
    """
    now = datetime.now(timezone.utc).isoformat()
    if error:
        conn.execute(
            """
            UPDATE jobs SET stage = ?, last_error = ?
            WHERE url = ?
            """,
            (STAGE_APPLY_FAILED, error, url),
        )
    else:
        conn.execute(
            """
            UPDATE jobs SET stage = ?, applied_at = ?, last_error = NULL
            WHERE url = ?
            """,
            (STAGE_APPLIED, now, url),
        )
    conn.commit()


def _cell_str(row: pd.Series, key: str) -> str | None:
    if key not in row.index:
        return None
    val = row[key]
    if pd.isna(val):
        return None
    if isinstance(val, str):
        return val
    return str(val)


def dataframe_to_rows(df: pd.DataFrame, discovered_at: str) -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = []
    for _, row in df.iterrows():
        url = _cell_str(row, "job_url")
        if not url:
            continue
        url = canonical_linkedin_job_view_url(url)
        title = _cell_str(row, "title")
        company = _cell_str(row, "company")
        listing_description = _cell_str(row, "description")
        location = _cell_str(row, "location")
        site = _cell_str(row, "site")
        rows.append(
            (
                url,
                title,
                company,
                listing_description,
                location,
                site,
                discovered_at,
                STAGE_DISCOVERED,
            )
        )
    return rows


def persist_jobs(conn: sqlite3.Connection, df: pd.DataFrame) -> int:
    """
    Insert new jobs from JobSpy (stage ``discovered``).

    Returns how many rows were **newly inserted**. Existing ``url`` values are
    skipped (no overwrite).
    """
    if df.empty:
        return 0

    discovered_at = datetime.now(timezone.utc).isoformat()
    rows = dataframe_to_rows(df, discovered_at)
    if not rows:
        return 0

    before = conn.total_changes
    conn.executemany(INSERT_DISCOVER_SQL, rows)
    conn.commit()
    return conn.total_changes - before


def apply_job_enrichment(
    conn: sqlite3.Connection,
    url: str,
    *,
    description: str | None,
    apply_url: str | None,
    title: str | None = None,
    company: str | None = None,
    location: str | None = None,
    error: str | None = None,
) -> None:
    """
    Record enrich stage: ``description``, ``apply_url``, ``title``, ``company``,
    ``location``, and ``stage``.

    On success ``error`` is None → ``stage`` = ``enriched``. On failure →
    ``enrich_failed`` and ``last_error`` set.
    """
    now = datetime.now(timezone.utc).isoformat()
    if error:
        stage = STAGE_ENRICH_FAILED
    else:
        stage = STAGE_ENRICHED

    conn.execute(
        UPSERT_ENRICH_SQL,
        (
            url,
            title,
            company,
            None,
            location,
            "linkedin",
            now,
            description,
            apply_url,
            now,
            error,
            stage,
        ),
    )
    conn.commit()
