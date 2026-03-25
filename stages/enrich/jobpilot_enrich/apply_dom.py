"""LinkedIn job page: one ``scope`` (top card or whole doc) → apply URL + title / company / location."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, unquote, urlparse

from bs4 import BeautifulSoup, Tag

_APPLY_URL_IN_CODE = re.compile(r"(?<=\?url=)[^\"]+")

_SKIP_BULLET = frozenset(
    {
        "full-time",
        "part-time",
        "internship",
        "contract",
        "temporary",
        "volunteer",
        "other",
        "on-site",
        "onsite",
        "remote",
        "hybrid",
    }
)


def _job_top_card_root(soup: BeautifulSoup) -> Tag | None:
    """Single job header container (the block with title, company, Apply, etc.)."""
    for div in soup.find_all(
        "div",
        class_=lambda c: c and "job-details-jobs-unified-top-card" in str(c).lower(),
    ):
        if div.find("h1"):
            return div
    for node in _nodes_with_top_card_class(soup):
        if node.find("h1"):
            return node
    nodes = _nodes_with_top_card_class(soup)
    return nodes[0] if nodes else None


def _nodes_with_top_card_class(soup: BeautifulSoup):
    return soup.find_all(
        class_=lambda x: x
        and isinstance(x, (list, str))
        and (
            "top-card" in str(x).lower()
            or "job-details-jobs-unified-top-card" in str(x).lower()
        )
    )


def _normalized_apply_href(a: Tag) -> str | None:
    h = (a.get("href") or "").strip()
    if not h.startswith("http") or not _looks_external_apply(h):
        return None
    return _normalize_href(h)


def _anchor_looks_like_external_apply(a: Tag) -> bool:
    aria = (a.get("aria-label") or "").lower()
    if "apply" in aria and "easy" not in aria:
        return True
    meta = ((a.get("data-tracking-control-name") or "") + " " + (a.get("aria-label") or "")).lower()
    if "apply" in meta and ("external" in meta or "offsite" in meta or "off-site" in meta):
        return True
    cls = a.get("class")
    s = " ".join(cls) if isinstance(cls, list) else (cls or "")
    if "apply" in s.lower():
        return True
    label = ((a.get_text() or "") + " " + (a.get("aria-label") or "")).lower()
    return "apply" in label


def _parse_linkedin_scope(scope: BeautifulSoup | Tag) -> dict[str, str | None]:
    """
    Everything from one DOM subtree: external apply URL, title, company, location.
    """
    title: str | None = None
    company: str | None = None
    location: str | None = None
    apply_raw: str | None = None

    block = scope.find("code", id="applyUrl")
    if block:
        text = block.decode_contents().strip()
        m = _APPLY_URL_IN_CODE.search(text)
        if m:
            apply_raw = unquote(m.group())

    if not apply_raw:
        el = scope.select_one(
            "a[data-testid='job-details-apply-external'], "
            "a[class*='jobs-apply-button'], "
            "a.job-details-jobs-unified-top-card__apply-button",
        )
        if el and el.get("href"):
            apply_raw = _normalized_apply_href(el)

    if not apply_raw:
        for a in scope.find_all("a", href=True):
            out = _normalized_apply_href(a)
            if not out:
                continue
            if _anchor_looks_like_external_apply(a):
                apply_raw = out
                break

    anchors = scope.find_all("a", href=True)

    h = scope.find("h1")
    if not h and getattr(scope, "name", None) == "h1":
        h = scope
    if not h:
        h = scope.select_one('[class*="job-title"], h2[class*="title"]')
    if h:
        t = (h.get_text() or "").strip()
        if t and len(t) < 500:
            title = t

    for a in anchors:
        href = (a.get("href") or "").strip().lower()
        if "/company/" in href and "linkedin.com" in href:
            c = (a.get_text() or "").strip()
            if c and len(c) < 300:
                company = c
                break

    if not company:
        el = scope.select_one(
            "a.job-details-jobs-unified-top-card__company-name, "
            "span.job-details-jobs-unified-top-card__company-name, "
            "[data-testid='job-details-company-name']",
        )
        if el:
            c = (el.get_text() or "").strip()
            if c:
                company = c

    for span in scope.find_all("span"):
        cls = span.get("class") or []
        cs = " ".join(cls) if isinstance(cls, list) else str(cls)
        if "bullet" not in cs.lower():
            continue
        loc = (span.get_text() or "").strip()
        if not loc or len(loc) > 300:
            continue
        if company and loc == company:
            continue
        if title and loc == title:
            continue
        if loc.lower() in _SKIP_BULLET:
            continue
        location = loc
        break

    if not location:
        el = scope.select_one(
            ".job-details-jobs-unified-top-card__primary-description, "
            "[data-testid='job-details-location']"
        )
        if el:
            loc = (el.get_text() or "").strip()
            if loc and len(loc) < 400:
                location = loc

    apply_url = sanitize_apply_url(_normalize_href(apply_raw)) if apply_raw else None

    return {
        "apply_url": apply_url,
        "title": title,
        "company": company,
        "location": location,
    }


def parse_linkedin_job_html(html: str) -> dict[str, str | None]:
    soup = BeautifulSoup(html, "html.parser")
    root = _job_top_card_root(soup)
    scope: BeautifulSoup | Tag = root if root is not None else soup
    return _parse_linkedin_scope(scope)


def extract_apply_from_linkedin_html(html: str) -> str | None:
    """Return the external apply URL, or ``None`` if not found."""
    return parse_linkedin_job_html(html)["apply_url"]


def _looks_external_apply(href: str) -> bool:
    if not href.startswith("http"):
        return False
    host = urlparse(href).netloc.lower()
    if "linkedin.com" in host:
        return "redir" in href or "redirect" in href or "url=" in href
    skip = ("google.com", "facebook.com", "twitter.com", "linkedin.com")
    return not any(s in host for s in skip)


def _normalize_href(href: str) -> str | None:
    href = href.strip()
    if not href.startswith("http"):
        return None
    if "linkedin.com" in href and "url=" in href:
        try:
            q = parse_qs(urlparse(href).query)
            if "url" in q:
                return unquote(q["url"][0]).strip()
        except (IndexError, ValueError):
            pass
    if "linkedin.com" in urlparse(href).netloc.lower() and "/jobs/" in href:
        return None
    return href


def sanitize_apply_url(href: str | None) -> str | None:
    if not href:
        return None
    low = href.lower()
    bad_substrings = (
        "/signup/",
        "cold-join",
        "/login",
        "uas/login",
        "session_redirect",
        "/checkpoint/",
    )
    if any(s in low for s in bad_substrings):
        return None
    return href
