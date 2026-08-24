"""Ashby job boards - the careers page of a great many AI/tech companies.

Public posting API, no key needed. Each posting carries the full
description and a direct apply URL, which is exactly what the contact
finder and the browser form-filler need.
Add company tokens to `ashby_companies` in profile.yaml - the token is
the slug from jobs.ashbyhq.com/<token>.
"""
from __future__ import annotations

from .util import get, title_matches

API = "https://api.ashbyhq.com/posting-api/job-board/{}"


def _location(j: dict) -> str:
    parts = [j.get("location") or ""]
    for extra in (j.get("secondaryLocations") or [])[:2]:
        if isinstance(extra, dict) and extra.get("location"):
            parts.append(extra["location"])
    addr = j.get("address") or {}
    if isinstance(addr, dict):
        postal = addr.get("postalAddress") or {}
        country = postal.get("addressCountry")
        if country and country not in parts:
            parts.append(country)
    return ", ".join(p for p in dict.fromkeys(parts) if p)


def _salary(j: dict) -> str:
    comp = j.get("compensation") or {}
    if not isinstance(comp, dict):
        return ""
    summary = (comp.get("compensationTierSummary")
               or comp.get("scrapeableCompensationSalarySummary") or "")
    return str(summary)[:200] if summary else ""


def fetch(profile):
    out = []
    for company in profile.get("ashby_companies") or []:
        try:
            r = get(API.format(company),
                    params={"includeCompensation": "true"})
        except Exception:
            continue
        if r.status_code != 200:
            continue
        try:
            jobs = r.json().get("jobs") or []
        except ValueError:
            continue
        for j in jobs:
            if not isinstance(j, dict) or not j.get("isListed", True):
                continue
            title = j.get("title") or ""
            if not title_matches(title):
                continue
            out.append(dict(
                source="ashby",
                external_id=f"{company}-{j.get('id')}",
                title=title,
                company=company,
                location=_location(j),
                remote=bool(j.get("isRemote"))
                or str(j.get("workplaceType", "")).lower() == "remote",
                # applyUrl is the form itself, which is what we want.
                url=j.get("applyUrl") or j.get("jobUrl") or "",
                description=(j.get("descriptionPlain") or "")[:15000],
                salary=_salary(j),
                posted_at=j.get("publishedAt") or "",
            ))
    return out
