"""Run LinkedIn job discovery via JobSpy and store results in SQLite.

Environment:
    JOBPILOT_LOG_LEVEL — logging level (default: INFO). Examples: DEBUG, WARNING.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import pandas as pd
from jobspy import scrape_jobs

from jobpilot.config import ConfigError, parse_discovery_config
from jobpilot_core.paths import default_database_path
from jobpilot_core.storage import open_database, persist_jobs

logger = logging.getLogger(__name__)


def _configure_logging() -> None:
    level_name = os.environ.get("JOBPILOT_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,
    )


def run_discovery(
    config_path: Path | None = None,
    database_path: Path | None = None,
) -> int:
    """
    Load ~/.jobpilot/searches.yaml, scrape jobs, persist to SQLite.
    Returns exit code (0 = success).
    """
    if not logging.root.handlers:
        _configure_logging()

    try:
        cfg_file, db_override, scrape_calls = parse_discovery_config(config_path)
    except ConfigError as e:
        logger.error("%s", e)
        return 1

    db_path = database_path or db_override or default_database_path()
    logger.info(
        "Starting discovery (config=%s, %d scrape run(s), db=%s)",
        cfg_file,
        len(scrape_calls),
        db_path,
    )

    try:
        frames: list[pd.DataFrame] = []
        for i, kwargs in enumerate(scrape_calls, start=1):
            term = kwargs.get("search_term", "")
            loc = kwargs.get("location")
            site = kwargs.get("site_name", "")
            logger.info(
                "Scrape %d/%d: site=%s search_term=%r location=%r",
                i,
                len(scrape_calls),
                site,
                term,
                loc,
            )
            df = scrape_jobs(**kwargs)
            logger.info("Scrape %d/%d: got %d row(s)", i, len(scrape_calls), len(df))
            frames.append(df)
        jobs_df = (
            pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        )
        logger.info("Combined %d row(s) before persist", len(jobs_df))
    except Exception:
        logger.exception("Scrape failed")
        return 2

    conn = open_database(db_path)
    try:
        n = persist_jobs(conn, jobs_df)
    finally:
        conn.close()

    logger.info("Inserted %d new job(s) in %s (existing URLs skipped)", n, db_path)
    return 0


def main() -> None:
    """Console script entrypoint."""
    _configure_logging()
    raise SystemExit(run_discovery())
