"""Playwright: collect visible form fields and apply fill mapping by index."""

from __future__ import annotations

import os
import re
from typing import Any

_EXTRACT_JS = """
() => {
  function visible(el) {
    if (!el || el.disabled) return false;
    const st = window.getComputedStyle(el);
    if (st.display === "none" || st.visibility === "hidden" || st.opacity === "0") return false;
    const r = el.getBoundingClientRect();
    if (r.width < 1 && r.height < 1) return false;
    return true;
  }
  function labelFor(el) {
    if (el.labels && el.labels.length) return (el.labels[0].innerText || "").trim();
    const al = el.getAttribute("aria-label");
    if (al) return al.trim();
    const id = el.id;
    if (id) {
      const lab = document.querySelector("label[for='" + CSS.escape(id) + "']");
      if (lab) return (lab.innerText || "").trim();
    }
    let p = el.parentElement;
    for (let d = 0; d < 5 && p; d++, p = p.parentElement) {
      const lab = p.querySelector(":scope > label");
      if (lab) return (lab.innerText || "").trim();
    }
    return "";
  }
  const tags = Array.from(document.querySelectorAll("input, textarea, select"));
  const out = [];
  for (const el of tags) {
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute("type") || "text").toLowerCase();
    if (tag === "input") {
      if (type === "hidden" || type === "submit" || type === "button" || type === "reset" || type === "image" || type === "checkbox" || type === "radio")
        continue;
      if (type === "file") continue;
    }
    if (!visible(el)) continue;
    out.push({
      index: out.length,
      tag,
      type: type,
      name: el.getAttribute("name") || "",
      id: el.getAttribute("id") || "",
      placeholder: el.getAttribute("placeholder") || "",
      label: labelFor(el),
      aria_label: el.getAttribute("aria-label") || "",
    });
  }
  return out;
}
"""

_FILL_JS = """
(mapping) => {
  // Must match _EXTRACT_JS visibility so indices align with extract_form_fields().
  function visible(el) {
    if (!el || el.disabled) return false;
    const st = window.getComputedStyle(el);
    if (st.display === "none" || st.visibility === "hidden" || st.opacity === "0") return false;
    const r = el.getBoundingClientRect();
    if (r.width < 1 && r.height < 1) return false;
    return true;
  }
  /** React / other frameworks: plain .value often does not update internal state. */
  function setReactFriendlyInputValue(el, sval) {
    const lastValue = el.value;
    const proto = el.tagName === "TEXTAREA"
      ? window.HTMLTextAreaElement.prototype
      : window.HTMLInputElement.prototype;
    const desc = Object.getOwnPropertyDescriptor(proto, "value");
    if (desc && desc.set) {
      desc.set.call(el, sval);
    } else {
      el.value = sval;
    }
    const tracker = el._valueTracker;
    if (tracker && typeof tracker.setValue === "function") {
      tracker.setValue(lastValue);
    }
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  }
  function setReactFriendlySelectValue(el, sval) {
    const lastValue = el.value;
    const desc = Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype, "value");
    if (desc && desc.set) {
      desc.set.call(el, sval);
    } else {
      el.value = sval;
    }
    const tracker = el._valueTracker;
    if (tracker && typeof tracker.setValue === "function") {
      tracker.setValue(lastValue);
    }
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  }
  const tags = Array.from(document.querySelectorAll("input, textarea, select"));
  const els = [];
  for (const el of tags) {
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute("type") || "text").toLowerCase();
    if (tag === "input") {
      if (type === "hidden" || type === "submit" || type === "button" || type === "reset" || type === "image" || type === "checkbox" || type === "radio")
        continue;
      if (type === "file") continue;
    }
    if (!visible(el)) continue;
    els.push(el);
  }
  let filled = 0;
  const errors = [];
  for (const m of mapping) {
    const idx = m.index;
    const val = m.value;
    if (typeof idx !== "number" || idx < 0 || idx >= els.length) {
      errors.push("bad index " + idx);
      continue;
    }
    if (val == null || String(val) === "") continue;
    const el = els[idx];
    const tag = el.tagName.toLowerCase();
    const sval = String(val);
    try {
      el.focus();
      if (tag === "select") {
        setReactFriendlySelectValue(el, sval);
      } else {
        setReactFriendlyInputValue(el, sval);
      }
      filled++;
    } catch (e) {
      errors.push("idx " + idx + ": " + e);
    }
  }
  return { filled, count: els.length, errors };
}
"""


def extract_form_fields(page: Any) -> list[dict[str, Any]]:
    raw = page.evaluate(_EXTRACT_JS)
    if not isinstance(raw, list):
        return []
    return raw


def dismiss_cookie_and_overlays(page: Any) -> list[str]:
    """
    Best-effort: close cookie / consent banners (OneTrust, Cookiebot, generic Accept buttons).

    Short timeouts; safe to call every navigation step. Returns log lines for debugging.
    """
    if os.environ.get("JOBPILOT_APPLY_SKIP_OVERLAY_DISMISS", "").strip() in ("1", "true", "yes"):
        return []

    logs: list[str] = []
    id_selectors = (
        "#onetrust-accept-btn-handler",
        "button#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
        "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowall",
        "[data-testid='cookie-accept']",
        "[data-testid='uc-accept-all-button']",
        "button.fc-button.fc-cta-consent",
        ".cc-compliance .cc-btn.cc-allow",
    )
    for sel in id_selectors:
        loc = page.locator(sel).first
        try:
            if loc.is_visible(timeout=200):
                loc.click(timeout=5000)
                logs.append(f"overlay:{sel}")
                page.wait_for_timeout(350)
        except Exception:
            pass

    name_patterns: list[re.Pattern[str]] = [
        re.compile(r"^accept all( cookies)?$", re.I),
        re.compile(r"^allow all( cookies)?$", re.I),
        re.compile(r"^i agree$", re.I),
        re.compile(r"^accept( cookies)?$", re.I),
        re.compile(r"^allow( cookies)?$", re.I),
        re.compile(r"^got it!?$", re.I),
        re.compile(r"^ok$", re.I),
        re.compile(r"^i understand$", re.I),
        re.compile(r"^agree( to all)?$", re.I),
    ]
    for pat in name_patterns:
        for role in ("button", "link"):
            loc = page.get_by_role(role, name=pat)  # type: ignore[arg-type]
            if _click_first_matching(page, loc):
                logs.append(f"overlay:role={role}:{pat.pattern}")
                page.wait_for_timeout(350)
                return logs
    return logs


def try_login_wall_bypass(page: Any) -> list[str]:
    """
    Best-effort: dismiss login / signup prompts that block the page (not full SSO sign-in).

    Cannot replace real credentials; use ``JOBPILOT_APPLY_STORAGE_STATE`` for logged-in sessions.
    """
    if os.environ.get("JOBPILOT_APPLY_SKIP_OVERLAY_DISMISS", "").strip() in ("1", "true", "yes"):
        return []

    logs: list[str] = []
    patterns: list[re.Pattern[str]] = [
        re.compile(r"^not now$", re.I),
        re.compile(r"^maybe later$", re.I),
        re.compile(r"^skip$", re.I),
        re.compile(r"^no thanks$", re.I),
        re.compile(r"^close$", re.I),
        re.compile(r"^continue without (signing in|logging in)( an account)?$", re.I),
        re.compile(r"^continue as guest$", re.I),
    ]
    for pat in patterns:
        for role in ("button", "link"):
            loc = page.get_by_role(role, name=pat)  # type: ignore[arg-type]
            if _click_first_matching(page, loc):
                logs.append(f"login_dismiss:{pat.pattern}")
                page.wait_for_timeout(350)
                return logs
    return logs


def _click_first_matching(page: Any, locator: Any) -> bool:
    """Click the first visible match (up to 20 candidates)."""
    try:
        n = locator.count()
        for i in range(min(n, 20)):
            loc = locator.nth(i)
            try:
                if loc.is_visible(timeout=400):
                    loc.scroll_into_view_if_needed(timeout=3000)
                    loc.click(timeout=10000)
                    return True
            except Exception:
                continue
    except Exception:
        pass
    return False


_APPLY_IN_NAME = re.compile(r"apply", re.I)


def _try_one_apply_navigation_click(page: Any) -> tuple[bool, Any]:
    """
    Try one click: first ``button`` whose accessible name contains ``apply``, then ``link``, then
    ``a[href*='apply']``. Covers e.g. "Apply Directly", "Apply now".

    Returns ``(clicked, page)``. If the click opens a new tab, ``page`` is the new page.
    """
    ctx = page.context
    n_before = len(ctx.pages)

    clicked = False
    for role in ("button", "link"):
        loc = page.get_by_role(role, name=_APPLY_IN_NAME)  # type: ignore[arg-type]
        if _click_first_matching(page, loc):
            clicked = True
            break
    if not clicked:
        href_loc = page.locator(
            'a[href*="apply"]:not([href*="linkedin.com"]):not([href*="facebook.com"]):not([href*="twitter.com"])'
        )
        if not _click_first_matching(page, href_loc):
            return False, page

    page.wait_for_timeout(300)
    if len(ctx.pages) > n_before:
        new_page = ctx.pages[-1]
        try:
            new_page.wait_for_load_state("domcontentloaded", timeout=45000)
        except Exception:
            pass
        return True, new_page

    try:
        page.wait_for_load_state("domcontentloaded", timeout=20000)
    except Exception:
        pass
    try:
        page.wait_for_load_state("networkidle", timeout=12000)
    except Exception:
        pass
    return True, page


def navigate_to_fillable_form(
    page: Any,
    *,
    max_steps: int | None = None,
    settle_ms: int | None = None,
) -> tuple[Any, bool, list[str]]:
    """
    If the landing URL is not the real form, click through common Apply / Start application
    controls until ``extract_form_fields`` finds at least one field or nothing more can be done.

    Handles new-tab apply flows by switching to the latest page in the browser context.

    Before each step, runs ``dismiss_cookie_and_overlays`` and ``try_login_wall_bypass`` (unless
    ``JOBPILOT_APPLY_SKIP_OVERLAY_DISMISS`` is set).

    Env: ``JOBPILOT_APPLY_NAV_MAX_STEPS`` (default 8), reuses ``JOBPILOT_APPLY_SETTLE_MS`` when
    ``settle_ms`` is None.
    """
    max_s = max_steps if max_steps is not None else int(os.environ.get("JOBPILOT_APPLY_NAV_MAX_STEPS", "8"))
    wait_ms = settle_ms if settle_ms is not None else int(os.environ.get("JOBPILOT_APPLY_SETTLE_MS", "2500"))
    logs: list[str] = []

    for step in range(max(1, max_s)):
        for line in dismiss_cookie_and_overlays(page):
            logs.append(line)
        for line in try_login_wall_bypass(page):
            logs.append(line)
        if extract_form_fields(page):
            logs.append(f"fillable_fields_ok_step_{step}")
            return page, True, logs
        clicked, page = _try_one_apply_navigation_click(page)
        if not clicked:
            logs.append(f"no_navigation_click_step_{step}")
            break
        logs.append(f"navigation_click_step_{step}")
        page.wait_for_timeout(max(0, wait_ms))
        try:
            page.wait_for_load_state("domcontentloaded", timeout=25000)
        except Exception:
            pass

    has_fields = bool(extract_form_fields(page))
    logs.append(f"final_has_fields={has_fields}")
    return page, has_fields, logs


def apply_fill_mapping(page: Any, mapping: list[dict[str, int | str]]) -> dict[str, Any]:
    """``mapping`` items: {index, value}."""
    result = page.evaluate(_FILL_JS, mapping)
    if not isinstance(result, dict):
        return {"filled": 0, "count": 0, "errors": ["invalid evaluate result"]}
    return result


def mapping_to_values(
    fills: list[dict[str, Any]],
    flat: dict[str, str],
) -> list[dict[str, int | str]]:
    """Resolve key names to string values from ``flat``."""
    out: list[dict[str, int | str]] = []
    for item in fills:
        idx = item.get("index")
        key = item.get("key")
        if not isinstance(idx, int):
            continue
        if key == "skip" or key is None:
            continue
        if not isinstance(key, str):
            continue
        val = flat.get(key)
        if val is None or not str(val).strip():
            continue
        out.append({"index": idx, "value": str(val).strip()})
    return out
