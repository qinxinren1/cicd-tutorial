"""Unified CLI: ``jobpilot <command> …`` runs in the same Python that imported this module."""

from __future__ import annotations

import sys


def _print_help() -> None:
    sys.stderr.write(
        """usage: jobpilot {discover|enrich|tailor|apply|linkedin-login} …

Run all stages with one installed interpreter (avoids conda vs venv PATH mix-ups).

  jobpilot discover
  jobpilot enrich <url> [--force] [-o FILE]
  jobpilot tailor <url> [--force] [-o FILE]
  jobpilot apply <url> [--dry-run] [--no-claude] [--force] [--headless]
  jobpilot linkedin-login [--state-file PATH]

Also: python -m jobpilot_core <command> …  (uses the current ``python``)
"""
    )


def main() -> None:
    if len(sys.argv) < 2:
        _print_help()
        raise SystemExit(1)
    cmd = sys.argv[1]
    if cmd in ("-h", "--help", "help"):
        _print_help()
        raise SystemExit(0)

    rest = sys.argv[2:]

    if cmd == "discover":
        from jobpilot.discover import main as discover_main

        sys.argv = ["jobpilot discover"]
        discover_main()
        return

    if cmd == "enrich":
        from jobpilot_enrich.enrich import main as enrich_main

        sys.argv = ["jobpilot enrich", *rest]
        enrich_main()
        return

    if cmd == "tailor":
        from jobpilot_tailor.tailor import main as tailor_main

        sys.argv = ["jobpilot tailor", *rest]
        tailor_main()
        return

    if cmd == "apply":
        from jobpilot_apply.apply import main as apply_main

        sys.argv = ["jobpilot apply", *rest]
        apply_main()
        return

    if cmd == "linkedin-login":
        from jobpilot_core.linkedin import main_linkedin_login

        sys.argv = ["jobpilot linkedin-login", *rest]
        main_linkedin_login()
        return

    sys.stderr.write(f"error: unknown command {cmd!r}\n\n")
    _print_help()
    raise SystemExit(1)
