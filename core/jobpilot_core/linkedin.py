"""LinkedIn: job URL helpers, Playwright fetch/session, JobSpy job-page details."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

from jobpilot_core.paths import playwright_linkedin_state_path

LINKEDIN_ORIGIN = "https://www.linkedin.com"

_VIEW_PATH_RE = re.compile(r"/jobs/view/(\d+)", re.I)
_CURRENT_JOB_ID_QS_RE = re.compile(r"(?:^|[?&#])currentJobId=(\d+)", re.I)
_JOB_ID_QS_RE = re.compile(r"(?:^|[?&#])jobId=(\d+)", re.I)


def parse_linkedin_job_id(url: str) -> str | None:
    """
    Extract numeric job id from ``/jobs/view/…``, ``currentJobId``, or ``jobId``
    on ``linkedin.com``. Returns ``None`` if not found.
    """
    if not url or not url.strip():
        return None
    s = url.strip()
    if "linkedin.com" not in s.lower():
        return None
    m = _VIEW_PATH_RE.search(s) or _CURRENT_JOB_ID_QS_RE.search(s) or _JOB_ID_QS_RE.search(s)
    return m.group(1) if m else None


def canonical_linkedin_job_view_url(url: str) -> str:
    """``{origin}/jobs/view/{id}`` when parseable; else ``url`` stripped."""
    jid = parse_linkedin_job_id(url)
    if jid:
        return f"{LINKEDIN_ORIGIN}/jobs/view/{jid}"
    return url.strip()


def fetch_url_html(url: str, state_path: Path | None = None) -> str:
    """
    Headless Chromium: load ``url``, return ``page.content()``.
    Uses saved storage state when ``state_path`` or default file exists.
    """
    from playwright.sync_api import sync_playwright

    path = Path(state_path) if state_path is not None else playwright_linkedin_state_path()
    use_state = path.is_file()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            if use_state:
                context = browser.new_context(storage_state=str(path))
            else:
                context = browser.new_context()
            page = context.new_page()
            page.goto(url, wait_until="load", timeout=120000)
            page.wait_for_timeout(2500)
            return page.content()
        finally:
            browser.close()


def save_linkedin_session_interactive(state_path: Path | None = None) -> Path:
    """Headed Chromium on LinkedIn login; Enter saves Playwright storage state."""
    from playwright.sync_api import sync_playwright

    path = state_path or playwright_linkedin_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        try:
            context = browser.new_context()
            page = context.new_page()
            page.goto(
                f"{LINKEDIN_ORIGIN}/login",
                wait_until="domcontentloaded",
                timeout=60000,
            )
            print(
                "\nA Chromium window should open on LinkedIn login.\n"
                "Sign in (2FA if prompted). When you reach feed or home, return here.\n"
                "Press Enter to save the session..."
            )
            input()
            context.storage_state(path=str(path))
        finally:
            browser.close()

    print(f"Saved Playwright storage state to: {path}")
    return path


def fetch_linkedin_job_details_jobspy(
    job_id: str,
    *,
    description_markdown: bool = True,
) -> dict[str, Any]:
    """
    JobSpy ``LinkedIn._get_job_details``: GET ``/jobs/view/{job_id}``, parse
    description, ``code#applyUrl``, job type, etc.
    """
    from jobspy.linkedin import LinkedIn
    from jobspy.model import Country, DescriptionFormat, ScraperInput, Site

    li = LinkedIn()
    li.scraper_input = ScraperInput(
        site_type=[Site.LINKEDIN],
        country=Country.USA,
        description_format=(
            DescriptionFormat.MARKDOWN if description_markdown else DescriptionFormat.HTML
        ),
    )
    return li._get_job_details(job_id)  # noqa: SLF001


def main_linkedin_login() -> None:
    """CLI: ``jobpilot linkedin-login``."""
    parser = argparse.ArgumentParser(
        description=(
            "Open LinkedIn in Chromium; log in manually, then save session to "
            "~/.jobpilot/playwright-linkedin-state.json (or --state-file)."
        )
    )
    parser.add_argument(
        "--state-file",
        type=Path,
        default=None,
        help="Where to write Playwright storage state",
    )
    args = parser.parse_args()
    save_linkedin_session_interactive(state_path=args.state_file)
    print(
        "\nInstall browser binaries if needed: playwright install chromium\n"
        'Install package extras: pip install -e ".[enrich]"'
    )


if __name__ == "__main__":
    main_linkedin_login()
