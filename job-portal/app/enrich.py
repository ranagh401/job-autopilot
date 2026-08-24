"""Fill in the real posting for jobs that arrived as a bare title + link.

Job-alert emails give almost nothing, which means the employer cannot be
confirmed and no contact can safely be found. Fetching the public posting
page turns those into fully usable jobs. Everything here reads pages that
are public to any visitor - no login, no account, no session.
"""
from __future__ import annotations

import json
import re

import requests
from bs4 import BeautifulSoup

UA = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/120.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
THIN = "(from a job-alert email"


def needs_enrichment(job) -> bool:
    desc = (job.description or "").strip()
    return bool(job.url) and (len(desc) < 200 or desc.startswith(THIN))


def _from_jsonld(soup: BeautifulSoup) -> dict:
    """Most job boards publish schema.org JobPosting - the reliable path."""
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "{}")
        except (ValueError, TypeError):
            continue
        for node in (data if isinstance(data, list) else [data]):
            if not isinstance(node, dict):
                continue
            if node.get("@type") not in ("JobPosting", ["JobPosting"]):
                continue
            org = node.get("hiringOrganization") or {}
            loc = node.get("jobLocation") or {}
            if isinstance(loc, list):
                loc = loc[0] if loc else {}
            addr = (loc or {}).get("address") or {}
            parts = [addr.get("addressLocality"), addr.get("addressRegion"),
                     addr.get("addressCountry")]
            if isinstance(parts[-1], dict):
                parts[-1] = parts[-1].get("name")
            return {
                "title": node.get("title") or "",
                "company": (org.get("name") if isinstance(org, dict)
                            else str(org or "")) or "",
                "description": BeautifulSoup(
                    node.get("description") or "", "html.parser"
                ).get_text("\n", strip=True),
                "location": ", ".join(str(p) for p in parts if p),
                "posted_at": node.get("datePosted") or "",
            }
    return {}


def _linkedin_description(soup: BeautifulSoup) -> str:
    for sel in ("div.show-more-less-html__markup",
                "div.description__text",
                "section.description"):
        node = soup.select_one(sel)
        if node:
            return node.get_text("\n", strip=True)
    return ""


def _linkedin_company(soup: BeautifulSoup) -> str:
    for sel in ("a.topcard__org-name-link", "span.topcard__flavor",
                "a[data-tracking-control-name='public_jobs_topcard-org-name']"):
        node = soup.select_one(sel)
        if node:
            return node.get_text(" ", strip=True)
    return ""


def fetch_posting(url: str) -> dict:
    """Return whatever the public posting page reveals."""
    try:
        r = requests.get(url, headers=UA, timeout=25, allow_redirects=True)
    except Exception:
        return {}
    if r.status_code != 200 or not r.text:
        return {}
    soup = BeautifulSoup(r.text, "html.parser")
    out = _from_jsonld(soup)
    if "linkedin.com" in url:
        out.setdefault("title", "")
        desc = _linkedin_description(soup)
        if len(desc) > len(out.get("description", "")):
            out["description"] = desc
        out["company"] = out.get("company") or _linkedin_company(soup)
        crumb = soup.select_one("span.topcard__flavor--bullet")
        if crumb and not out.get("location"):
            out["location"] = crumb.get_text(" ", strip=True)
    if not looks_like_job_text(out.get("description", "")):
        out.pop("description", None)
        # Last resort: the biggest block that actually reads like a posting.
        for node in soup.find_all(["article", "section", "main", "div"]):
            text = node.get_text("\n", strip=True)
            if not (400 < len(text) < 20000) or not looks_like_job_text(text):
                continue
            # Navigation is mostly links; a description is mostly prose.
            link_text = sum(len(a.get_text(" ", strip=True))
                            for a in node.find_all("a"))
            if link_text > len(text) * 0.4:
                continue
            if len(text) > len(out.get("description", "")):
                out["description"] = text
    return {k: v for k, v in out.items() if v}


# A real posting talks about the work; a nav bar does not.
JOB_WORDS = re.compile(
    r"responsibilit|requirement|qualification|you will|we are looking|"
    r"what you.ll|experience (in|with)|skills|role|team|apply|benefits|"
    r"about the (job|role|position)|your profile|tasks|wir suchen|"
    r"deine aufgaben|dein profil", re.I)


def looks_like_job_text(text: str) -> bool:
    if len(text or "") < 200:
        return False
    hits = len(set(m.group(0).lower() for m in JOB_WORDS.finditer(text)))
    if hits < 2:
        return False
    # Menus and link farms have many very short lines.
    lines = [l for l in text.splitlines() if l.strip()]
    if lines and sum(1 for l in lines if len(l) < 25) > len(lines) * 0.7:
        return False
    return True


def enrich_job(session, job) -> bool:
    """Fill in description/company/location from the live posting.

    Returns True when a real description was recovered.
    """
    data = fetch_posting(job.url)
    if not data:
        return False
    desc = re.sub(r"\n{3,}", "\n\n", data.get("description", "")).strip()
    if not looks_like_job_text(desc):
        return False
    job.description = desc[:15000]
    # Only overwrite a company/location that the alert parser guessed at.
    if data.get("company") and len(data["company"]) > 2:
        job.company = data["company"][:300]
    if data.get("location") and not job.location:
        job.location = data["location"][:300]
    if data.get("title") and len(data["title"]) > len(job.title or ""):
        job.title = data["title"][:300]
    session.commit()
    return True
