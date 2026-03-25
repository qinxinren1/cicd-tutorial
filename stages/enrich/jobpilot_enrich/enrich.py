"""CLI: JobSpy fetches JD text; Playwright (or HTTP fallback) fills title/location/company."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from jobpilot_core.linkedin import (
    canonical_linkedin_job_view_url,
    fetch_linkedin_job_details_jobspy,
    fetch_url_html,
    parse_linkedin_job_id,
)
from jobpilot_core.paths import default_database_path
from jobpilot_core.storage import apply_job_enrichment, fetch_job, open_database
from jobpilot_enrich.apply_dom import parse_linkedin_job_html, sanitize_apply_url


def _normalize_field(val: str | None) -> str | None:
    if val is None:
        return None
    t = val.strip() if isinstance(val, str) else str(val).strip()
    return t or None


def _fetch_job_html_http(url: str) -> str | None:
    """Plain HTTP GET for the job page (fallback when Playwright HTML is missing or unparsed)."""
    try:
        req = Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        with urlopen(req, timeout=25) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except (OSError, HTTPError, URLError, ValueError):
        return None


def _json_safe_jobspy(val: object) -> object:
    if isinstance(val, list):
        return [_json_safe_jobspy(v) for v in val]
    if hasattr(val, "value"):
        return getattr(val, "value", val)
    return val


def enrich_linkedin_job(raw_url: str) -> tuple[dict, str, dict]:
    """
    Fetch LinkedIn job details: JobSpy for description/apply hint; Playwright (or HTTP)
    for ``title``, ``company``, ``location`` and external apply URL when needed.

    Returns ``(payload, storage_url, jobspy_details)`` where ``storage_url`` is the
    canonical ``/jobs/view/{id}`` URL (primary key in the ``jobs`` table).
    """
    raw_url = raw_url.strip()
    fetch_url = canonical_linkedin_job_view_url(raw_url)
    job_id = parse_linkedin_job_id(raw_url)

    details: dict = {}
    if job_id:
        details = fetch_linkedin_job_details_jobspy(job_id)

    apply_url = sanitize_apply_url(details.get("job_url_direct"))

    description = details.get("description")

    need_playwright = (not job_id) or (apply_url is None)
    html = None
    playwright_fetched = False
    if need_playwright:
        try:
            html = fetch_url_html(fetch_url, state_path=None)
            playwright_fetched = True
        except Exception as e:
            print(f"error: {e}", file=sys.stderr)
            raise SystemExit(1) from e

    html_for_meta = html
    if html_for_meta is None and job_id:
        try:
            html_for_meta = fetch_url_html(fetch_url, state_path=None)
        except Exception as e:
            print(f"warn: could not fetch page for metadata: {e}", file=sys.stderr)
            html_for_meta = None

    parsed = parse_linkedin_job_html(html_for_meta) if html_for_meta else None
    if apply_url is None and parsed:
        apply_url = parsed["apply_url"]
    title = _normalize_field((parsed.get("title") if parsed else None) or details.get("title"))
    company = _normalize_field((parsed.get("company") if parsed else None) or details.get("company"))
    location = _normalize_field((parsed.get("location") if parsed else None) or details.get("location"))

    # JobSpy ``_get_job_details`` does not return title/company/location; fill gaps via HTTP HTML.
    if job_id and (not title or not company or not location):
        html_http = _fetch_job_html_http(fetch_url)
        if html_http:
            p_http = parse_linkedin_job_html(html_http)
            title = title or _normalize_field(p_http.get("title"))
            company = company or _normalize_field(p_http.get("company"))
            location = location or _normalize_field(p_http.get("location"))

    data: dict = {
        "apply_url": apply_url,
        "description": description,
        "playwright_fetched": playwright_fetched,
        "title": title,
        "company": company,
        "location": location,
    }
    if job_id is not None:
        data["job_id"] = job_id
    if fetch_url != raw_url:
        data["resolved_url"] = fetch_url

    for key in ("job_type", "job_level", "company_industry", "job_function"):
        val = details.get(key)
        if val:
            data[key] = _json_safe_jobspy(val)

    return data, fetch_url, details


def _has_description_and_apply_url(job: dict) -> bool:
    """True when both full job text and an external apply URL are already stored."""
    d = job.get("description")
    a = job.get("apply_url")
    return bool(d and str(d).strip() and a and str(a).strip())


def _payload_from_stored_job(job: dict, raw_url: str) -> dict:
    """Build the same shape as ``enrich_linkedin_job`` for stdout/``-o`` when skipping fetch."""
    fetch_url = canonical_linkedin_job_view_url(raw_url.strip())
    job_id = parse_linkedin_job_id(raw_url)
    data: dict = {
        "apply_url": job.get("apply_url"),
        "description": job.get("description"),
        "playwright_fetched": False,
        "title": job.get("title"),
        "company": job.get("company"),
        "location": job.get("location"),
        "skipped_enrichment": True,
    }
    if job_id is not None:
        data["job_id"] = job_id
    if fetch_url != raw_url.strip():
        data["resolved_url"] = fetch_url
    return data


def run_enrich(raw_url: str, *, force: bool = False) -> dict:
    """
    Fetch one LinkedIn job and persist enrich fields to SQLite at
    ``default_database_path()`` (same default as ``jobpilot discover``).

    If the job row already has both ``description`` and ``apply_url`` and ``force`` is false,
    skips JobSpy/Playwright and returns the stored payload.

    Returns the JSON payload dict.
    """
    storage_url = canonical_linkedin_job_view_url(raw_url.strip())
    db_path = default_database_path()
    conn = open_database(db_path)
    try:
        job = fetch_job(conn, storage_url)
        if job is not None and not force and _has_description_and_apply_url(job):
            print(
                "Using existing enrich data from database (skip fetch). "
                "Pass --force to refetch.",
                file=sys.stderr,
            )
            return _payload_from_stored_job(job, raw_url)
    finally:
        conn.close()

    data, storage_url2, _details = enrich_linkedin_job(raw_url)

    conn = open_database(db_path)
    try:
        apply_job_enrichment(
            conn,
            storage_url2,
            description=data.get("description"),
            apply_url=data.get("apply_url"),
            title=data.get("title"),
            company=data.get("company"),
            location=data.get("location"),
            error=None,
        )
    finally:
        conn.close()

    return data


def main() -> None:
    p = argparse.ArgumentParser(
        description=(
            "LinkedIn job: JobSpy loads the job description; Playwright (or HTTP) loads "
            "title/company/location; Playwright runs when the external apply URL must "
            "be taken from the live page DOM. "
            "Skips fetch when the job row already has both description and apply_url; use --force to refetch."
        )
    )
    p.add_argument("url", help="Job page URL (collections /jobs/view/… both work)")
    p.add_argument("-o", type=Path, metavar="FILE", help="Write JSON to FILE instead of stdout")
    p.add_argument(
        "--force",
        action="store_true",
        help="Refetch even when description and apply_url are already stored.",
    )
    args = p.parse_args()

    data = run_enrich(args.url, force=args.force)

    out = json.dumps(data, ensure_ascii=False, indent=2) + "\n"

    if args.o is not None:
        args.o.write_text(out, encoding="utf-8")
    else:
        sys.stdout.write(out)


if __name__ == "__main__":
    main()
