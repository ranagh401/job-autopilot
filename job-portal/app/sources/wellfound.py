"""Wellfound as a job source, using the saved browser session.

Wellfound serves nothing useful to a plain HTTP client - every page is a
Cloudflare challenge - so this reuses the signed-in Playwright profile that
`app.wellfound_apply` creates. That makes it local-only by nature: with no
saved profile, no display, or no Playwright installed it returns an empty
list rather than raising, so the hourly fetch in CI simply skips it.
"""
from __future__ import annotations

import os
import re

from .util import title_matches

SEARCH_URLS = [
    "https://wellfound.com/role/r/machine-learning-engineer",
    "https://wellfound.com/role/r/artificial-intelligence-engineer",
    "https://wellfound.com/role/r/data-scientist",
    "https://wellfound.com/role/r/backend-engineer",
    "https://wellfound.com/role/r/software-engineer",
]

JOB_ID = re.compile(r"/jobs/(\d+)")

# Pull title/company/location out of a result card in the page itself -
# the DOM is far easier to read there than from scraped innerText.
EXTRACT = """
() => {
  const out = [];
  const cards = document.querySelectorAll('[data-test="StartupResult"]');
  for (const card of cards) {
    const company = (card.querySelector('h2, [class*="startup" i] a')
                     || {}).innerText || '';
    for (const a of card.querySelectorAll('a[href*="/jobs/"]')) {
      const row = a.closest('div') || a;
      out.push({
        href: a.getAttribute('href') || '',
        title: (a.innerText || '').trim(),
        company: company.trim(),
        text: (row.innerText || '').trim().slice(0, 400),
      });
    }
  }
  return out;
}
"""

LOCATION = re.compile(
    r"\b(remote|bengaluru|bangalore|hyderabad|pune|chennai|mumbai|delhi|"
    r"noida|gurgaon|gurugram|new york|san francisco|london|berlin|toronto|"
    r"singapore|amsterdam|dublin|sydney|austin|seattle|boston)\b", re.I)


def _available() -> bool:
    from ..wellfound_apply import PROFILE_DIR
    if os.getenv("WELLFOUND_SOURCE", "true").lower() == "false":
        return False
    if not PROFILE_DIR.exists():
        return False
    try:
        import playwright.sync_api  # noqa: F401
    except Exception:
        return False
    return True


def fetch(profile):
    if not _available():
        return []

    from playwright.sync_api import sync_playwright

    from ..wellfound_apply import PROFILE_DIR

    out, seen = [], set()
    try:
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE_DIR), headless=True,
                args=["--disable-blink-features=AutomationControlled"])
            page = ctx.pages[0] if ctx.pages else ctx.new_page()

            for url in SEARCH_URLS:
                try:
                    page.goto(url, timeout=45000,
                              wait_until="domcontentloaded")
                    page.wait_for_timeout(2500)
                    if "/login" in page.url:
                        break  # session expired; nothing to gain from more
                    for _ in range(3):
                        page.mouse.wheel(0, 4000)
                        page.wait_for_timeout(1200)
                    rows = page.evaluate(EXTRACT) or []
                except Exception:
                    continue

                for r in rows:
                    m = JOB_ID.search(r.get("href", ""))
                    if not m or m.group(1) in seen:
                        continue
                    title = r.get("title", "")
                    if not title or not title_matches(title):
                        continue
                    seen.add(m.group(1))
                    loc = LOCATION.search(r.get("text", ""))
                    href = r["href"]
                    out.append(dict(
                        source="wellfound",
                        external_id=m.group(1),
                        title=title,
                        company=r.get("company", ""),
                        location=loc.group(0) if loc else "",
                        remote=bool(re.search(r"remote", r.get("text", ""),
                                              re.I)),
                        url=(href if href.startswith("http")
                             else "https://wellfound.com" + href),
                        description=r.get("text", ""),
                        posted_at="",
                    ))
            ctx.close()
    except Exception:
        return out
    return out
