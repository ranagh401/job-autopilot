"""Instahyre - Indian job board, large volume, no login needed.

The site itself sits behind Cloudflare, but its own front-end reads from
`/api/v1/job_search`, which answers plain JSON to any browser-looking
request. That endpoint is what we use.

Two things it does NOT give us, learned by probing it:
  * `q`, `keyword`, `location`, `search` and the experience params are all
    accepted and then ignored - every one returns the same 13,633 rows.
    Only `job_functions` genuinely narrows the set, so titles are filtered
    on our side.
  * there is no description or experience field, and the public job page is
    Cloudflare-protected, so it cannot be scraped for one either. We
    synthesise a description from the employer blurb and the skill
    keywords, which is enough for scoring and keeps the company
    identifiable for contact discovery.
"""
from __future__ import annotations

from .util import title_matches

import requests

API = "https://www.instahyre.com/api/v1/job_search"

# Cloudflare answers the default library UA with a challenge page; a
# browser UA plus the site's own referer gets clean JSON.
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/128.0.0.0 Safari/537.36"),
    "Accept": "application/json",
    "Referer": "https://www.instahyre.com/search-jobs/",
    "Accept-Language": "en-IN,en;q=0.9",
}

# The only filter the API honours. Names come from meta.top_job_functions_count.
JOB_FUNCTIONS = {
    9: "Data Science / Machine Learning",
    10: "Backend Development",
    1: "Full-Stack Development",
    76: "Other Software Development",
}

# The API clamps page size to 35 regardless of what `limit` asks for.
PAGE = 35


def _description(job: dict) -> str:
    """Build usable text from the fields the API does return."""
    emp = job.get("employer") or {}
    bits = []
    company = emp.get("company_name", "")
    if company:
        line = f"{company}"
        if emp.get("company_tagline"):
            line += f" - {emp['company_tagline']}"
        if emp.get("employee_count"):
            line += f" ({emp['employee_count']} employees"
            if emp.get("company_founded"):
                line += f", founded {emp['company_founded']}"
            line += ")"
        bits.append(line)
    if emp.get("instahyre_note"):
        bits.append(str(emp["instahyre_note"]))
    if job.get("keywords"):
        bits.append("Skills required: " + ", ".join(job["keywords"]))
    if job.get("locations"):
        bits.append(f"Location: {job['locations']}")
    if job.get("accept_outstation"):
        bits.append("Open to candidates relocating from another city.")
    return "\n\n".join(bits)


def fetch(profile):
    max_pages = int((profile.get("instahyre_pages") or 6))
    out, seen = [], set()

    for func_id in JOB_FUNCTIONS:
        for page in range(max_pages):
            try:
                r = requests.get(API, headers=HEADERS, timeout=30,
                                 params={"limit": PAGE,
                                         "offset": page * PAGE,
                                         "job_functions": func_id})
                if r.status_code != 200:
                    break
                rows = r.json().get("objects", [])
            except Exception:
                break
            if not rows:
                break

            for j in rows:
                jid = j.get("id")
                if not jid or jid in seen:
                    continue
                seen.add(jid)

                title = j.get("title") or j.get("candidate_title") or ""
                if not title_matches(title):
                    continue
                emp = j.get("employer") or {}
                company = emp.get("company_name", "")
                if not company:
                    continue

                out.append(dict(
                    source="instahyre",
                    external_id=str(jid),
                    title=title,
                    company=company,
                    location=j.get("locations", "") or "India",
                    remote=False,
                    url=j.get("public_url", ""),
                    description=_description(j),
                    posted_at="",
                ))
    return out
