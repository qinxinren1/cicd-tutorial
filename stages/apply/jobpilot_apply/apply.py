"""CLI: open ``apply_url`` in Playwright, map fields via Claude CLI, fill from ``profile.json``."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from jobpilot_core.linkedin import canonical_linkedin_job_view_url
from jobpilot_core.paths import default_database_path, load_jobpilot_dotenv, profile_path
from jobpilot_core.storage import (
    STAGE_APPLIED,
    STAGE_APPLY_FAILED,
    STAGE_TAILORED,
    apply_job_application,
    fetch_job,
    open_database,
)
from jobpilot_tailor.profile_load import load_profile

from jobpilot_apply.claude_form_map import (
    build_mapping_prompt,
    heuristic_fills,
    parse_fills_json,
    run_claude_mapping,
)
from jobpilot_apply.playwright_apply import (
    apply_fill_mapping,
    extract_form_fields,
    mapping_to_values,
    navigate_to_fillable_form,
)
from jobpilot_apply.profile_flat import available_keys, flatten_profile_for_apply


def _require_apply_ready(job: dict[str, Any]) -> str | None:
    au = job.get("apply_url")
    if not (au and str(au).strip()):
        return "missing apply_url; run jobpilot enrich"
    st = job.get("stage")
    allowed = {STAGE_TAILORED, STAGE_APPLY_FAILED, STAGE_APPLIED}
    if st not in allowed:
        return f"expected stage one of {sorted(allowed)}, got {st!r}; run jobpilot tailor first"
    cl = job.get("cover_letter")
    if not (cl and str(cl).strip()):
        return "missing cover letter; run jobpilot tailor"
    return None


def run_apply(
    raw_url: str,
    *,
    headless: bool = False,
    dry_run: bool = False,
    no_claude: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    """
    Load job, map form fields (Claude CLI or heuristic), fill via Playwright.

    On success updates stage to ``applied``; on failure ``apply_failed``.

    Set ``JOBPILOT_APPLY_CDP_ENDPOINT`` (e.g. ``http://localhost:9222``) to attach to your Chrome
    (start Chrome with ``--remote-debugging-port=9222``) instead of launching bundled Chromium.
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

        err = _require_apply_ready(job)
        if err:
            return {"ok": False, "url": url, "error": err}

        if job.get("stage") == STAGE_APPLIED and not force:
            return {
                "ok": True,
                "url": url,
                "skipped": True,
                "message": "already applied; pass --force to run again",
            }

        profile_raw = load_profile(prof)
        flat = flatten_profile_for_apply(profile_raw, job)
        keys = available_keys(flat)
        if not keys:
            return {"ok": False, "url": url, "error": "profile has no values to fill (check profile.json)"}

        apply_url = str(job.get("apply_url")).strip()

        goto_timeout_ms = int(os.environ.get("JOBPILOT_APPLY_GOTO_TIMEOUT_MS", "120000"))
        keep_open_ms = int(os.environ.get("JOBPILOT_APPLY_KEEP_OPEN_MS", "0"))
        block_until_enter = os.environ.get("JOBPILOT_APPLY_BLOCK_UNTIL_ENTER", "1").strip().lower() not in (
            "0",
            "false",
            "no",
        )

        from playwright.sync_api import sync_playwright

        fills_spec: list[dict[str, Any]]
        claude_text = ""
        nav_logs: list[str] = []

        cdp_endpoint = os.environ.get("JOBPILOT_APPLY_CDP_ENDPOINT", "").strip()
        use_cdp = bool(cdp_endpoint)
        if use_cdp and headless:
            print(
                "warn: --headless ignored when JOBPILOT_APPLY_CDP_ENDPOINT is set (using your browser).",
                file=sys.stderr,
            )

        with sync_playwright() as p:
            if use_cdp:
                browser = p.chromium.connect_over_cdp(cdp_endpoint)
                print(
                    f"info: Playwright attached over CDP ({cdp_endpoint}); your browser stays open after exit.",
                    file=sys.stderr,
                )
            else:
                browser = p.chromium.launch(headless=headless)
            try:
                settle_ms = int(os.environ.get("JOBPILOT_APPLY_SETTLE_MS", "2500"))

                if use_cdp:
                    context = browser.contexts[0] if browser.contexts else browser.new_context()
                    use_existing_tab = os.environ.get(
                        "JOBPILOT_APPLY_CDP_USE_EXISTING_TAB", ""
                    ).strip().lower() in ("1", "true", "yes")
                    if use_existing_tab:
                        if not context.pages:
                            return {
                                "ok": False,
                                "url": url,
                                "error": "CDP: no open tab; open the apply page in Chrome or unset JOBPILOT_APPLY_CDP_USE_EXISTING_TAB",
                                "apply_url": apply_url,
                            }
                        page = context.pages[-1]
                        page.bring_to_front()
                        page.wait_for_timeout(max(0, settle_ms))
                    else:
                        page = context.new_page()
                        page.goto(apply_url, wait_until="domcontentloaded", timeout=max(1, goto_timeout_ms))
                        page.wait_for_timeout(max(0, settle_ms))
                else:
                    state = os.environ.get("JOBPILOT_APPLY_STORAGE_STATE", "").strip()
                    if state:
                        sp = Path(state).expanduser()
                        context = (
                            browser.new_context(storage_state=str(sp))
                            if sp.is_file()
                            else browser.new_context()
                        )
                    else:
                        context = browser.new_context()
                    page = context.new_page()
                    page.goto(apply_url, wait_until="domcontentloaded", timeout=max(1, goto_timeout_ms))
                    page.wait_for_timeout(max(0, settle_ms))

                page, _nav_ok, nav_logs = navigate_to_fillable_form(page)
                fields = extract_form_fields(page)
                if not fields:
                    msg = "no fillable fields found (landing page may need manual navigation)"
                    if not dry_run:
                        apply_job_application(conn, url, error=msg)
                    return {
                        "ok": False,
                        "url": url,
                        "error": msg,
                        "apply_url": apply_url,
                        "navigation_logs": nav_logs,
                    }

                if no_claude:
                    fills_spec = heuristic_fills(fields)
                else:
                    prompt = build_mapping_prompt(
                        fields=fields,
                        available_keys=keys,
                        job_title=job.get("title"),
                        company=job.get("company"),
                    )
                    try:
                        claude_text = run_claude_mapping(prompt)
                        fills_spec = parse_fills_json(claude_text)
                    except (RuntimeError, ValueError, json.JSONDecodeError) as e:
                        print(f"warn: Claude mapping failed ({e}); using heuristic.", file=sys.stderr)
                        fills_spec = heuristic_fills(fields)

                value_maps = mapping_to_values(fills_spec, flat)

                if dry_run:
                    return {
                        "ok": True,
                        "url": url,
                        "apply_url": apply_url,
                        "cdp": use_cdp,
                        "dry_run": True,
                        "navigation_logs": nav_logs,
                        "fields": fields,
                        "fills_spec": fills_spec,
                        "values": value_maps,
                        "claude_raw_preview": (claude_text[:2000] + "…") if len(claude_text) > 2000 else claude_text,
                    }

                fill_result = apply_fill_mapping(page, value_maps)

                if keep_open_ms > 0 and (use_cdp or not headless):
                    page.wait_for_timeout(keep_open_ms)

                apply_job_application(conn, url, error=None)
                return {
                    "ok": True,
                    "url": url,
                    "apply_url": apply_url,
                    "cdp": use_cdp,
                    "navigation_logs": nav_logs,
                    "filled": fill_result.get("filled"),
                    "field_count": fill_result.get("count"),
                    "fill_errors": fill_result.get("errors"),
                    "values_applied": value_maps,
                }
            except Exception as e:
                if not dry_run:
                    apply_job_application(conn, url, error=str(e))
                return {
                    "ok": False,
                    "url": url,
                    "error": str(e),
                    "apply_url": apply_url,
                    "navigation_logs": nav_logs,
                }
            finally:
                if (use_cdp or not headless) and block_until_enter and not dry_run:
                    print(
                        "Browser left open — review the page. Press Enter to disconnect Playwright.",
                        file=sys.stderr,
                    )
                    try:
                        input()
                    except EOFError:
                        pass
                try:
                    browser.close()
                except Exception:
                    pass
    finally:
        conn.close()


def main() -> None:
    p = argparse.ArgumentParser(
        description=(
            "Apply stage: open the job's external apply URL in Playwright, map form fields with "
            "Claude Code CLI (``claude -p ... --output-format=json``), and fill from profile + cover letter. "
            "Requires: ``tailored`` stage, ``apply_url``, ``cover_letter``. "
            "Install: pip install -e \".[apply]\" and ``playwright install chromium``. "
            "Env: JOBPILOT_CLAUDE_BIN, JOBPILOT_APPLY_SETTLE_MS, JOBPILOT_APPLY_GOTO_TIMEOUT_MS (ms, default 120000), "
            "JOBPILOT_APPLY_NAV_MAX_STEPS (default 8), JOBPILOT_APPLY_KEEP_OPEN_MS (headed, ms before DB update), "
            "JOBPILOT_APPLY_BLOCK_UNTIL_ENTER=0 to skip “Press Enter” wait (default: headed mode waits for Enter), "
            "JOBPILOT_APPLY_STORAGE_STATE (Playwright storage_state.json after manual login on that site), "
            "JOBPILOT_APPLY_CDP_ENDPOINT (e.g. http://localhost:9222) to attach to your Chrome with --remote-debugging-port; "
            "JOBPILOT_APPLY_CDP_USE_EXISTING_TAB=1 to fill the front/last tab (skip goto); omit to open a new tab and navigate to apply_url. "
            "JOBPILOT_APPLY_SKIP_OVERLAY_DISMISS=1 to disable cookie/login-dismiss clicks, "
            "JOBPILOT_JOBS_DB, JOBPILOT_PROFILE."
        )
    )
    p.add_argument("url", help="LinkedIn job page URL (same canonical form as discover/enrich)")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print mapping and values only; do not fill or update DB stage.",
    )
    p.add_argument(
        "--no-claude",
        action="store_true",
        help="Skip Claude CLI; use keyword heuristics only.",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Run even when stage is already ``applied``.",
    )
    p.add_argument(
        "--headless",
        action="store_true",
        help="Headless Chromium (default: headed).",
    )
    args = p.parse_args()

    result = run_apply(
        args.url,
        headless=args.headless,
        dry_run=args.dry_run,
        no_claude=args.no_claude,
        force=args.force,
    )

    out = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if result.get("ok"):
        sys.stdout.write(out)
        raise SystemExit(0)
    sys.stderr.write(out)
    raise SystemExit(1)


if __name__ == "__main__":
    main()
