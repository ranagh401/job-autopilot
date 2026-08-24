"""JobSpy - scrapes Indeed, Naukri, Google Jobs, LinkedIn and Glassdoor
without any login (public/guest endpoints only), so there is no personal
account to ban. Blocking, when it happens, is IP-level and temporary.

Optional: enabled only when `pip install python-jobspy` has been run and
JOBSPY_SITES is set in .env. Keep the site list small and the schedule
infrequent - hammering these endpoints is what gets an IP rate-limited.
"""
from __future__ import annotations

import os


def fetch(profile):
    sites = [s.strip() for s in os.getenv("JOBSPY_SITES", "").split(",")
             if s.strip()]
    if not sites:
        return []
    try:
        from jobspy import scrape_jobs
    except ImportError:
        return []

    roles = (profile.get("target_roles") or ["AI Engineer"])[:2]
    locations = [l for l in (profile.get("locations_priority") or [])
                 if l.lower() != "remote"][:2] or ["India"]
    hours = int(os.getenv("JOBSPY_HOURS_OLD", "72"))
    per_search = int(os.getenv("JOBSPY_RESULTS", "25"))

    out, seen = [], set()
    for role in roles:
        for loc in locations:
            try:
                df = scrape_jobs(
                    site_name=sites,
                    search_term=role,
                    google_search_term=f"{role} jobs near {loc} since last week",
                    location=loc,
                    results_wanted=per_search,
                    hours_old=hours,
                    country_indeed="India",
                    description_format="markdown",
                )
            except Exception:
                continue
            if df is None or df.empty:
                continue
            for _, r in df.iterrows():
                def g(col, default=""):
                    v = r.get(col, default)
                    return default if v is None or str(v) == "nan" else v

                url = str(g("job_url"))
                key = url or f"{g('title')}|{g('company')}"
                if key in seen:
                    continue
                seen.add(key)
                sal = ""
                if g("min_amount"):
                    sal = (f"{g('min_amount')}-{g('max_amount')} "
                           f"{g('currency')}").strip()
                out.append(dict(
                    source=f"jobspy-{g('site', 'x')}",
                    external_id=(str(g("id")) or url)[:300],
                    title=str(g("title")),
                    company=str(g("company")),
                    location=str(g("location")),
                    remote=bool(r.get("is_remote")),
                    url=url,
                    description=str(g("description"))[:15000],
                    salary=sal[:200],
                    posted_at=str(g("date_posted")),
                ))
    return out
