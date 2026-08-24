"""The Muse - free public jobs API (global companies, many sponsor visas)."""
from .util import get, strip_html, title_matches


def fetch(profile):
    out = []
    for page in range(3):
        r = get("https://www.themuse.com/api/public/jobs",
                params={"page": page,
                        "category": ["Software Engineering",
                                     "Data and Analytics"]})
        if r.status_code != 200:
            break
        for j in r.json().get("results", []):
            if not title_matches(j.get("name", "")):
                continue
            locs = ", ".join(l.get("name", "") for l in j.get("locations", []))
            out.append(dict(
                source="themuse",
                external_id=str(j.get("id")),
                title=j.get("name", ""),
                company=(j.get("company") or {}).get("name", ""),
                location=locs,
                remote="flexible" in locs.lower() or "remote" in locs.lower(),
                url=(j.get("refs") or {}).get("landing_page", ""),
                description=strip_html(j.get("contents", ""))[:15000],
                posted_at=j.get("publication_date", ""),
            ))
    return out
