"""CLI: generate a cover letter from ``profile.json`` and an enriched job row."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from jobpilot_core.linkedin import canonical_linkedin_job_view_url
from jobpilot_core.paths import default_database_path, load_jobpilot_dotenv, profile_path
from jobpilot_core.storage import (
    STAGE_ENRICHED,
    STAGE_TAILOR_FAILED,
    STAGE_TAILORED,
    apply_job_tailoring,
    fetch_job,
    open_database,
)
from jobpilot_tailor.cover_letter_export import (
    cover_letter_export_paths,
    export_cover_letter_txt_and_pdf,
)
from jobpilot_tailor.llm_cover_letter import generate_cover_letter
from jobpilot_tailor.profile_load import load_profile, sanitize_profile_for_llm


def _require_enriched_job(job: dict) -> str | None:
    """Return error string if job cannot be tailored, else None."""
    desc = job.get("description")
    if not (desc and str(desc).strip()):
        return "job has no description; run jobpilot enrich first"
    stage = job.get("stage")
    allowed = {STAGE_ENRICHED, STAGE_TAILORED, STAGE_TAILOR_FAILED}
    if stage not in allowed:
        return f"expected stage one of {sorted(allowed)}, got {stage!r}"
    return None


def run_tailor(raw_url: str, *, force: bool = False) -> dict:
    """
    Load job by canonical URL, generate cover letter, persist with stage ``tailored``.

    If the job is already ``tailored`` with non-empty ``cover_letter`` and ``force`` is false,
    skips the LLM (and skips writing ``.txt``/``.pdf`` when both files already exist).

    Uses ``default_database_path()`` / ``profile_path()`` (env ``JOBPILOT_JOBS_DB``,
    ``JOBPILOT_PROFILE`` to override). Writes ``cover_letters/<stem>.txt`` and ``.pdf``.

    Returns ``ok``, ``url``, ``cover_letter``, ``txt_path``, ``pdf_path``, ``skipped_generation``,
    ``error``.
    """
    load_jobpilot_dotenv()
    url = canonical_linkedin_job_view_url(raw_url.strip())
    db = default_database_path()
    prof = profile_path()

    conn = open_database(db)
    try:
        job = fetch_job(conn, url)
        if job is None:
            return {"ok": False, "url": url, "error": "job not found in database"}

        err = _require_enriched_job(job)
        if err:
            return {"ok": False, "url": url, "error": err}

        profile_raw = load_profile(prof)
        profile_safe = sanitize_profile_for_llm(profile_raw)

        existing_cl = job.get("cover_letter")
        has_stored_letter = bool(
            job.get("stage") == STAGE_TAILORED
            and existing_cl
            and str(existing_cl).strip()
        )

        if has_stored_letter and not force:
            letter = str(existing_cl).strip()
            print(
                "Using existing cover letter from database (skip LLM). "
                "Pass --force to regenerate.",
                file=sys.stderr,
            )
            txt_path, pdf_path = cover_letter_export_paths(url, job)
            if txt_path.is_file() and pdf_path.is_file():
                return {
                    "ok": True,
                    "url": url,
                    "cover_letter": letter,
                    "txt_path": txt_path,
                    "pdf_path": pdf_path,
                    "skipped_generation": True,
                }
            try:
                txt_path, pdf_path = export_cover_letter_txt_and_pdf(
                    letter_text=letter,
                    profile=profile_raw,
                    job_url=url,
                    job=job,
                )
            except OSError as e:
                print(f"warn: could not export cover letter files: {e}", file=sys.stderr)
                txt_path, pdf_path = None, None
            return {
                "ok": True,
                "url": url,
                "cover_letter": letter,
                "txt_path": txt_path,
                "pdf_path": pdf_path,
                "skipped_generation": True,
            }

        try:
            letter = generate_cover_letter(job=job, profile=profile_safe)
        except Exception as e:
            apply_job_tailoring(conn, url, error=str(e))
            return {"ok": False, "url": url, "error": str(e)}

        apply_job_tailoring(conn, url, cover_letter=letter)
        try:
            txt_path, pdf_path = export_cover_letter_txt_and_pdf(
                letter_text=letter,
                profile=profile_raw,
                job_url=url,
                job=job,
            )
        except OSError as e:
            print(f"warn: could not export cover letter files: {e}", file=sys.stderr)
            txt_path, pdf_path = None, None
        return {
            "ok": True,
            "url": url,
            "cover_letter": letter,
            "txt_path": txt_path,
            "pdf_path": pdf_path,
            "skipped_generation": False,
        }
    finally:
        conn.close()


def main() -> None:
    p = argparse.ArgumentParser(
        description=(
            "Tailored cover letter from profile.json and an enriched job in jobs.db. "
            "Set OPENAI_API_KEY in ~/.jobpilot/.env or project .env. "
            "Opening: ~/.jobpilot/cl-framework/opening.txt — placeholders {title} and {company} only. "
            "Optional env: JOBPILOT_JOBS_DB, JOBPILOT_PROFILE, JOBPILOT_LLM_MODEL, "
            "JOBPILOT_COVER_LETTER_LANG, JOBPILOT_CL_OPENING, JOBPILOT_COVER_SALUTATION, "
            "JOBPILOT_COVER_CLOSING, JOBPILOT_COVER_LETTERS_DIR. "
            "Also saves cover_letters/<sanitized_job_title>.txt and .pdf "
            "(WeasyPrint, or Playwright fallback; run `playwright install chromium` once). "
            "Skips LLM if the job is already tailored with a stored letter; use --force to regenerate."
        )
    )
    p.add_argument("url", help="LinkedIn job page URL (same canonical form as discover/enrich)")
    p.add_argument("-o", type=Path, metavar="FILE", help="Write cover letter text to FILE")
    p.add_argument(
        "--force",
        action="store_true",
        help="Regenerate even when a cover letter is already stored (tailored stage).",
    )
    args = p.parse_args()

    result = run_tailor(args.url, force=args.force)

    if not result.get("ok"):
        print(f"error: {result.get('error')}", file=sys.stderr)
        raise SystemExit(1)

    letter = result.get("cover_letter", "")
    if args.o is not None:
        args.o.write_text(letter + "\n", encoding="utf-8")
    else:
        sys.stdout.write(letter + "\n")

    tp = result.get("txt_path")
    pp = result.get("pdf_path")
    if tp is not None:
        print(f"Saved: {tp}", file=sys.stderr)
    if pp is not None:
        print(f"Saved: {pp}", file=sys.stderr)

    raise SystemExit(0)


if __name__ == "__main__":
    main()
