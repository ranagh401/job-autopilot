"""Remote OK - free API for remote jobs."""
from .util import get, strip_html, title_matches


def fetch(profile):
    r = get("https://remoteok.com/api")
    out = []
    for j in r.json():
        if not isinstance(j, dict) or not j.get("position"):
            continue
        tags = " ".join(j.get("tags") or []).lower()
        if not (title_matches(j["position"]) or "ai" in tags or "python" in tags):
            continue
        out.append(dict(
            source="remoteok",
            external_id=str(j.get("id") or j.get("slug") or j.get("url")),
            title=j.get("position", ""),
            company=j.get("company", ""),
            location=j.get("location", "") or "Remote",
            remote=True,
            url=j.get("url", ""),
            description=strip_html(j.get("description", ""))[:15000],
            salary=(f"{j.get('salary_min')}-{j.get('salary_max')}"
                    if j.get("salary_min") else ""),
            posted_at=j.get("date", ""),
        ))
    return out
