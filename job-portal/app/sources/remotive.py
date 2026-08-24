"""Remotive - free API for remote jobs worldwide."""
from .util import get, strip_html


def fetch(profile):
    out = []
    for kw in ["ai engineer", "machine learning", "generative ai"]:
        r = get("https://remotive.com/api/remote-jobs",
                params={"search": kw, "limit": 50})
        for j in r.json().get("jobs", []):
            out.append(dict(
                source="remotive",
                external_id=str(j.get("id")),
                title=j.get("title", ""),
                company=j.get("company_name", ""),
                location=j.get("candidate_required_location", "") or "Remote",
                remote=True,
                url=j.get("url", ""),
                description=strip_html(j.get("description", ""))[:15000],
                salary=j.get("salary", ""),
                posted_at=j.get("publication_date", ""),
            ))
    return out
