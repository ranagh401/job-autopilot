"""Seek - the dominant job board in Australia and New Zealand.

Uses the same public JSON search endpoint the website's own front end
calls; no login and no personal account involved. Australia and NZ both
run large skilled-visa programmes (subclass 482/186, NZ Accredited
Employer Work Visa), so these are among the best markets for a sponsored
move out of India.
"""
from __future__ import annotations

from .util import get, strip_html, title_matches

SITES = [
    ("seek-au", "seek.com.au", "AU-Main", "Australia"),
    ("seek-nz", "seek.co.nz", "NZ-Main", "New Zealand"),
]
KEYWORDS = ["artificial intelligence engineer", "machine learning engineer",
            "software engineer python"]


def _locations(job) -> str:
    names = []
    for loc in job.get("locations") or []:
        if isinstance(loc, dict):
            label = loc.get("label") or loc.get("name") or ""
            if label:
                names.append(label)
    return ", ".join(names)


def fetch(profile):
    if not profile.get("open_to_relocation_abroad", True):
        return []
    out = []
    for source, host, sitekey, country in SITES:
        for kw in KEYWORDS[:2]:
            try:
                r = get(f"https://www.{host}/api/jobsearch/v5/search",
                        params={"siteKey": sitekey,
                                "sourcesystem": "houston",
                                "keywords": kw,
                                "page": 1,
                                "pageSize": 30,
                                "sortmode": "ListedDate"},
                        headers={"Accept": "application/json"})
            except Exception:
                continue
            if r.status_code != 200:
                continue
            try:
                data = r.json().get("data") or []
            except ValueError:
                continue
            for j in data:
                if not isinstance(j, dict):
                    continue
                title = j.get("title") or ""
                if not title_matches(title):
                    continue
                jid = str(j.get("id") or "")
                if not jid:
                    continue
                area = _locations(j)
                teaser = strip_html(j.get("teaser") or "")
                bullets = " ".join(j.get("bulletPoints") or [])
                company = (j.get("companyName")
                           or (j.get("advertiser") or {}).get("description", ""))
                out.append(dict(
                    source=source,
                    external_id=jid,
                    title=title,
                    company=company,
                    location=", ".join(x for x in (area, country) if x),
                    remote="remote" in (teaser + bullets + area).lower(),
                    url=f"https://www.{host}/job/{jid}",
                    description=(f"{teaser}\n{bullets}").strip()[:15000],
                    salary=j.get("salaryLabel") or "",
                    posted_at=j.get("listingDate") or "",
                ))
    return out
