"""JSearch (RapidAPI) - Google for Jobs data: aggregates LinkedIn, Indeed,
Naukri, Glassdoor etc. legitimately. Free tier ~200 requests/month, so
queries are capped via JSEARCH_MAX_QUERIES.

Note: the v5 API renamed the search endpoint to /search-v2; plain /search
now 404s.
"""
import os
import re

from .util import get

ENDPOINT = "https://jsearch.p.rapidapi.com/search-v2"


def fetch(profile):
    key = os.getenv("RAPIDAPI_KEY")
    if not key:
        return []
    max_q = int(os.getenv("JSEARCH_MAX_QUERIES", "5"))
    # (query, country code) - the last few hunt sponsored roles abroad.
    queries = [
        ("AI engineer jobs in India", "in"),
        ("Generative AI engineer jobs in India", "in"),
        ("AI engineer visa sponsorship", "au"),
        ("machine learning engineer visa sponsorship", "nz"),
        ("AI engineer visa sponsorship relocation", "gb"),
        ("AI engineer relocation visa", "de"),
        ("software engineer visa sponsorship", "ca"),
    ][:max_q]
    out = []
    for q, country in queries:
        r = get(ENDPOINT,
                params={"query": q, "num_pages": 1, "date_posted": "week",
                        "country": country},
                headers={"X-RapidAPI-Key": key,
                         "X-RapidAPI-Host": "jsearch.p.rapidapi.com"})
        if r.status_code != 200:
            continue
        data = r.json().get("data") or {}
        # v5 wraps the list: {"data": {"jobs": [...], "cursor": "..."}}
        jobs = data.get("jobs", []) if isinstance(data, dict) else data
        for j in jobs:
            if not isinstance(j, dict):
                continue
            loc = j.get("job_location") or ", ".join(
                x for x in [j.get("job_city"), j.get("job_state"),
                            j.get("job_country")] if x)
            out.append(dict(
                # Publisher names can be long and messy; keep it short.
                source=("jsearch-" + re.split(
                    r"[^a-z0-9.]+",
                    (j.get("job_publisher") or "x").lower().strip())[0])[:40],
                external_id=str(j.get("job_id"))[:300],
                title=j.get("job_title", ""),
                company=j.get("employer_name", ""),
                location=loc,
                remote=bool(j.get("job_is_remote")),
                url=j.get("job_apply_link", ""),
                description=(j.get("job_description") or "")[:15000],
                salary=(j.get("job_salary_string")
                        or (f"{j.get('job_min_salary')}-{j.get('job_max_salary')}"
                            if j.get("job_min_salary") else "")),
                posted_at=(j.get("job_posted_at_datetime_utc")
                           or j.get("job_posted_at_timestamp") or ""),
            ))
    return out
