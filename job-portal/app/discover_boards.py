"""Work out which job board a company's careers page runs on.

Nearly every "careers.<company>.com" is really Greenhouse, Lever, Ashby
or Workday under the hood. Given a company name this probes the obvious
board tokens and reports which one answers, so it can be added to
profile.yaml and swept from then on.
"""
from __future__ import annotations

import re

from .sources.util import get

PROBES = [
    ("greenhouse", "https://boards-api.greenhouse.io/v1/boards/{t}/jobs",
     lambda d: len(d.get("jobs") or [])),
    ("lever", "https://api.lever.co/v0/postings/{t}?mode=json",
     lambda d: len(d) if isinstance(d, list) else 0),
    ("ashby", "https://api.ashbyhq.com/posting-api/job-board/{t}",
     lambda d: len(d.get("jobs") or [])),
]


def _tokens(company: str) -> list[str]:
    slug = re.sub(r"[^a-z0-9]", "", (company or "").lower())
    stripped = re.sub(
        r"(pvt|private|ltd|limited|llp|inc|llc|technologies|technology|"
        r"solutions|systems|services|software|labs|india|global|group)",
        "", slug)
    hyphen = re.sub(r"[^a-z0-9]+", "-", (company or "").lower()).strip("-")
    return [t for t in dict.fromkeys([slug, stripped, hyphen])
            if 2 < len(t) < 40]


def find_board(company: str) -> dict:
    """Return {'ats': ..., 'token': ..., 'jobs': n} or {} if none found."""
    for token in _tokens(company):
        for ats, url, count in PROBES:
            try:
                r = get(url.format(t=token), timeout=15)
            except Exception:
                continue
            if r.status_code != 200:
                continue
            try:
                n = count(r.json())
            except Exception:
                continue
            if n > 0:
                return {"ats": ats, "token": token, "jobs": n}
    return {}


def scan(companies: list[str]) -> dict:
    """Map several companies at once, grouped ready for profile.yaml."""
    found, missing = {}, []
    for c in companies:
        hit = find_board(c)
        if hit:
            found.setdefault(hit["ats"], []).append(
                {"company": c, "token": hit["token"], "jobs": hit["jobs"]})
        else:
            missing.append(c)
    return {"found": found, "missing": missing}
