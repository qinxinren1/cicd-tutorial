"""Filesystem paths for Job Pilot configuration and storage."""

import os
from pathlib import Path


def jobpilot_dir() -> Path:
    """Return ~/.jobpilot, creating it if missing."""
    path = Path.home() / ".jobpilot"
    path.mkdir(parents=True, exist_ok=True)
    return path


def searches_config_path() -> Path:
    """Path to searches.yaml (~/.jobpilot/searches.yaml)."""
    return jobpilot_dir() / "searches.yaml"


def default_database_path() -> Path:
    """
    Default SQLite database path (~/.jobpilot/jobs.db).

    Override with env ``JOBPILOT_JOBS_DB`` (absolute or ``~`` path).
    """
    override = os.environ.get("JOBPILOT_JOBS_DB", "").strip()
    if override:
        return Path(override).expanduser()
    return jobpilot_dir() / "jobs.db"


def profile_path() -> Path:
    """
    Path to profile.json (~/.jobpilot/profile.json).

    Override with env ``JOBPILOT_PROFILE``.
    """
    override = os.environ.get("JOBPILOT_PROFILE", "").strip()
    if override:
        return Path(override).expanduser()
    return jobpilot_dir() / "profile.json"


def cover_letters_dir() -> Path:
    """
    Directory for exported cover letter ``.txt`` and ``.pdf`` files.

    Override with ``JOBPILOT_COVER_LETTERS_DIR``. Otherwise, if ``./.jobpilot`` exists under
    the current working directory (e.g. repo-local config), use ``./.jobpilot/cover_letters``;
    else ``~/.jobpilot/cover_letters``.
    """
    override = os.environ.get("JOBPILOT_COVER_LETTERS_DIR", "").strip()
    if override:
        path = Path(override).expanduser()
    elif (Path.cwd() / ".jobpilot").is_dir():
        path = Path.cwd() / ".jobpilot" / "cover_letters"
    else:
        path = jobpilot_dir() / "cover_letters"
    path.mkdir(parents=True, exist_ok=True)
    return path


def cl_framework_opening_path() -> Path:
    """
    Path to the fixed opening paragraph template ``cl-framework/opening.txt``.

    Override with env ``JOBPILOT_CL_OPENING`` (full path to ``opening.txt``).
    """
    override = os.environ.get("JOBPILOT_CL_OPENING", "").strip()
    if override:
        return Path(override).expanduser()
    return jobpilot_dir() / "cl-framework" / "opening.txt"


def dotenv_path() -> Path:
    """Path to ~/.jobpilot/.env (API keys and other secrets for Job Pilot)."""
    return jobpilot_dir() / ".env"


def load_jobpilot_dotenv() -> None:
    """
    Load environment variables from dotenv files.

    Order: ``~/.jobpilot/.env`` first, then ``.env`` in the current working directory
    (the latter overrides keys from the former). Existing process environment variables
    are not overwritten unless ``override=True`` on the second file.

    Requires the optional ``python-dotenv`` package (installed with ``pip install -e ".[tailor]"``).
    If ``python-dotenv`` is missing, this is a no-op.
    """
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(dotenv_path(), override=False)
    load_dotenv(Path.cwd() / ".env", override=True)


def playwright_linkedin_state_path() -> Path:
    """
    Playwright storage state JSON after interactive login (``jobpilot linkedin-login``).
    Override with env JOBPILOT_LINKEDIN_STATE.
    """
    override = os.environ.get("JOBPILOT_LINKEDIN_STATE", "").strip()
    if override:
        return Path(override).expanduser()
    return jobpilot_dir() / "playwright-linkedin-state.json"
