"""Arbeitnow - free API, strong on European jobs with a visa_sponsorship flag."""
from .util import get, strip_html, title_matches


def fetch(profile):
    out = []
    for page in (1, 2):
        r = get("https://www.arbeitnow.com/api/job-board-api",
                params={"page": page})
        for j in r.json().get("data", []):
            if not title_matches(j.get("title", "")):
                continue
            desc = strip_html(j.get("description", ""))[:15000]
            if j.get("visa_sponsorship"):
                desc = "Visa sponsorship offered (per Arbeitnow flag).\n\n" + desc
            out.append(dict(
                source="arbeitnow",
                external_id=j.get("slug", ""),
                title=j.get("title", ""),
                company=j.get("company_name", ""),
                location=j.get("location", ""),
                remote=bool(j.get("remote")),
                url=j.get("url", ""),
                description=desc,
                posted_at=str(j.get("created_at", "")),
            ))
    return out
