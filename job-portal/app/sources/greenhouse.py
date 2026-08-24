"""Greenhouse public board API - direct company career pages.
Add board tokens to greenhouse_boards in profile.yaml."""
from .util import get, strip_html, title_matches


def fetch(profile):
    out = []
    for board in profile.get("greenhouse_boards") or []:
        r = get(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs",
                params={"content": "true"})
        if r.status_code != 200:
            continue
        for j in r.json().get("jobs", []):
            if not title_matches(j.get("title", "")):
                continue
            out.append(dict(
                source="greenhouse",
                external_id=f"{board}-{j.get('id')}",
                title=j.get("title", ""),
                company=board,
                location=(j.get("location") or {}).get("name", ""),
                remote="remote" in str(j.get("location", "")).lower(),
                url=j.get("absolute_url", ""),
                description=strip_html(j.get("content", ""))[:15000],
                posted_at=j.get("updated_at", ""),
            ))
    return out
