"""Lever public postings API - direct company career pages.
Add company tokens to lever_companies in profile.yaml."""
from .util import get, title_matches


def fetch(profile):
    out = []
    for comp in profile.get("lever_companies") or []:
        r = get(f"https://api.lever.co/v0/postings/{comp}",
                params={"mode": "json"})
        if r.status_code != 200:
            continue
        for j in r.json():
            if not title_matches(j.get("text", "")):
                continue
            cat = j.get("categories") or {}
            out.append(dict(
                source="lever",
                external_id=f"{comp}-{j.get('id')}",
                title=j.get("text", ""),
                company=comp,
                location=cat.get("location", ""),
                remote="remote" in str(cat.get("location", "")).lower(),
                url=j.get("hostedUrl", ""),
                description=(j.get("descriptionPlain") or "")[:15000],
                posted_at=str(j.get("createdAt", "")),
            ))
    return out
