"""Export cover letter to ``~/.jobpilot/cover_letters`` as ``.txt`` and ``.pdf``.

PDF: WeasyPrint first; if that fails or is missing, Playwright Chromium (same as ``jobpilot enrich``).
"""

from __future__ import annotations

import html
import re
import sys
from pathlib import Path
from typing import Any

from jobpilot_core.linkedin import parse_linkedin_job_id
from jobpilot_core.paths import cover_letters_dir

_CSS = """
@page {{
    size: A4;
    margin: 1in;
}}
body {{
    font-family: 'Calibri', 'Segoe UI', Arial, sans-serif;
    font-size: 11pt;
    line-height: 1.6;
    color: #1a1a1a;
    margin: 0;
    padding: 0;
}}
.header {{
    margin-bottom: 1.75em;
    text-align: left;
    font-size: 9.5pt;
    color: #333;
    line-height: 1.5;
}}
.header .header-name {{
    display: block;
    font-size: 12pt;
    font-weight: bold;
    color: #1a1a1a;
    margin-bottom: 0.35em;
    letter-spacing: 0.01em;
}}
.header .header-line {{
    display: block;
    margin-top: 0.15em;
    word-wrap: break-word;
    overflow-wrap: anywhere;
}}
.header .header-links {{
    display: block;
    margin-top: 0.15em;
    word-wrap: break-word;
    overflow-wrap: anywhere;
}}
.header .header-link-sep {{
    color: #888;
    padding: 0 0.15em;
    user-select: none;
}}
.header a.header-link {{
    color: #0b57d0;
    text-decoration: none;
    border-bottom: 1px solid transparent;
}}
.header a.header-link:hover {{
    border-bottom-color: #0b57d0;
}}
.content {{
    text-align: left;
}}
.content p {{
    margin: 0 0 1em 0;
    text-align: justify;
}}
.content p:last-child {{
    margin-bottom: 0;
}}
.signature {{
    margin-top: 1.5em;
}}
"""


def sanitize_job_title_for_filename(title: str, max_len: int = 100) -> str:
    """
    Turn a job title into a single path segment safe for shells (zsh/bash).

    Removes/replaces characters that break unquoted paths (e.g. ``()`` glob, ``?*[]``,
    ``/``, ``:``) so ``open path`` works without quoting.
    """
    t = (title or "").strip()
    if not t:
        return ""
    # Path-reserved and control chars
    t = re.sub(r'[<>:"/\\|*\x00-\x1f]', "", t)
    # Shell/glob-sensitive: parens, brackets, glob metacharacters, backticks
    t = re.sub(r"[()\[\]{}?&!`$]", "_", t)
    t = re.sub(r"[,;]", "_", t)
    t = re.sub(r"\s+", "_", t)
    t = re.sub(r"[-_]+", "_", t).strip("_-")
    return t[:max_len] if t else ""


def cover_letter_file_stem(job_url: str, job: dict[str, Any] | None = None) -> str:
    """
    Filename stem for exports: sanitized ``job["title"]`` when present, else ``job_<linkedin_id>``
    or ``cover_<hash>``.
    """
    if job is not None:
        raw = job.get("title")
        if raw is not None and str(raw).strip():
            stem = sanitize_job_title_for_filename(str(raw))
            if stem:
                return stem
    jid = parse_linkedin_job_id(job_url)
    if jid:
        return f"job_{jid}"
    import hashlib

    return f"cover_{hashlib.sha256(job_url.encode()).hexdigest()[:12]}"


def cover_letter_export_paths(job_url: str, job: dict[str, Any] | None = None) -> tuple[Path, Path]:
    """Resolved ``.txt`` and ``.pdf`` paths for this job (under ``cover_letters_dir()``)."""
    stem = cover_letter_file_stem(job_url, job)
    d = cover_letters_dir()
    return d / f"{stem}.txt", d / f"{stem}.pdf"


def _primary_display_name(personal: dict[str, Any]) -> str | None:
    """One name line: prefer full name; otherwise preferred name (never both)."""
    fn = personal.get("full_name")
    if fn is not None and str(fn).strip():
        return str(fn).strip()
    pn = personal.get("preferred_name")
    if pn is not None and str(pn).strip():
        return str(pn).strip()
    return None


def _location_one_line(personal: dict[str, Any]) -> str | None:
    """City, region, country on a single line."""
    parts: list[str] = []
    for key in ("city", "province_state", "country"):
        v = personal.get(key)
        if v is not None and str(v).strip():
            parts.append(str(v).strip())
    if not parts:
        return None
    return ", ".join(parts)


def contact_header_html(profile: dict[str, Any]) -> str:
    """
    Left-aligned contact block from ``profile.personal`` (no password).

    Layout: bold name; email and phone on one line (`` · ``) when both exist; location;
    LinkedIn / GitHub / Portfolio / Website on a single line with `` · `` separators.
    """
    personal = profile.get("personal")
    if not isinstance(personal, dict):
        return ""

    chunks: list[str] = []

    name = _primary_display_name(personal)
    if name:
        chunks.append(f'<span class="header-name">{html.escape(name)}</span>')

    contact_bits: list[str] = []
    for key in ("email", "phone"):
        val = personal.get(key)
        if val is not None and str(val).strip():
            contact_bits.append(html.escape(str(val).strip()))
    if contact_bits:
        chunks.append(f'<span class="header-line">{" · ".join(contact_bits)}</span>')

    loc = _location_one_line(personal)
    if loc:
        chunks.append(f'<span class="header-line">{html.escape(loc)}</span>')

    link_defs = [
        ("LinkedIn", "linkedin_url"),
        ("GitHub", "github_url"),
        ("Portfolio", "portfolio_url"),
        ("Website", "website_url"),
    ]
    link_parts: list[str] = []
    for label, key in link_defs:
        raw = personal.get(key)
        if raw is not None and str(raw).strip():
            u = html.escape(str(raw).strip(), quote=True)
            lab = html.escape(label)
            link_parts.append(f'<a class="header-link" href="{u}">{lab}</a>')
    if link_parts:
        sep = '<span class="header-link-sep">·</span>'
        inner = f" {sep} ".join(link_parts)
        chunks.append(f'<span class="header-links">{inner}</span>')

    return "\n".join(chunks)


def letter_text_to_content_html(letter_text: str) -> str:
    """Plain letter → ``<p>`` blocks; blank line = new paragraph; single newlines → ``<br>``."""
    blocks: list[str] = []
    for para in letter_text.strip().split("\n\n"):
        para = para.strip()
        if not para:
            continue
        inner = "<br>\n".join(html.escape(line) for line in para.split("\n"))
        blocks.append(f"<p>{inner}</p>")
    return "\n".join(blocks)


def _write_pdf_weasyprint(doc_html: str, out_dir: Path, pdf_path: Path) -> None:
    from weasyprint import HTML

    HTML(string=doc_html, base_url=str(out_dir)).write_pdf(pdf_path)


def _write_pdf_playwright(doc_html: str, pdf_path: Path) -> None:
    """Render HTML to PDF via headless Chromium (no GTK/Pango)."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.set_content(doc_html, wait_until="load")
            page.pdf(
                path=str(pdf_path),
                format="A4",
                margin={"top": "1in", "right": "1in", "bottom": "1in", "left": "1in"},
            )
        finally:
            browser.close()


def build_cover_letter_html(contact_header: str, formatted_text: str) -> str:
    """Full HTML document for PDF (A4, Calibri stack)."""
    ch = contact_header if contact_header.strip() else "&nbsp;"
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
{_CSS}
</style>
</head>
<body>
<div class="header">
{ch}
</div>
<div class="content">
{formatted_text}
</div>
</body>
</html>"""


def export_cover_letter_txt_and_pdf(
    *,
    letter_text: str,
    profile: dict[str, Any],
    job_url: str,
    job: dict[str, Any] | None = None,
) -> tuple[Path, Path | None]:
    """
    Write ``<stem>.txt`` and ``<stem>.pdf`` under ``cover_letters_dir()``.

    ``stem`` comes from ``job["title"]`` when set (sanitized); otherwise from the URL id/hash.

    Returns ``(txt_path, pdf_path)``. If both PDF backends fail, ``pdf_path`` is ``None``.
    """
    stem = cover_letter_file_stem(job_url, job)
    out_dir = cover_letters_dir()
    txt_path = out_dir / f"{stem}.txt"
    pdf_path = out_dir / f"{stem}.pdf"

    txt_path.write_text(letter_text.rstrip() + "\n", encoding="utf-8")

    header = contact_header_html(profile)
    body_html = letter_text_to_content_html(letter_text)
    doc_html = build_cover_letter_html(header, body_html)

    weasy_ok = False
    try:
        _write_pdf_weasyprint(doc_html, out_dir, pdf_path)
        weasy_ok = True
    except ImportError:
        print(
            "warn: weasyprint not installed; trying Playwright for PDF "
            '(or: pip install -e ".[tailor]").',
            file=sys.stderr,
        )
    except Exception as e:
        print(
            f"warn: WeasyPrint failed ({e}); trying Playwright for PDF. "
            "On macOS, WeasyPrint often needs: brew install pango cairo gdk-pixbuf libffi",
            file=sys.stderr,
        )

    if weasy_ok:
        return txt_path, pdf_path

    try:
        _write_pdf_playwright(doc_html, pdf_path)
        print("info: PDF written via Playwright (Chromium).", file=sys.stderr)
        return txt_path, pdf_path
    except ImportError:
        print(
            "warn: playwright not installed; cannot generate PDF. "
            'Install: pip install "playwright>=1.40,<2" && playwright install chromium',
            file=sys.stderr,
        )
    except Exception as e:
        print(f"warn: Playwright PDF failed ({e})", file=sys.stderr)

    print(
        f"warn: No PDF saved (TXT only: {txt_path}). "
        "Install WeasyPrint system libs + pip install weasyprint, "
        "or install Playwright as above.",
        file=sys.stderr,
    )
    return txt_path, None
