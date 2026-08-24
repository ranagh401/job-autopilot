"""Adzuna - aggregator API with a free tier.

Used twice: once for India, and once across the countries that actually
sponsor Indian AI engineers (Australia, New Zealand, UK, Germany, ...).
Adzuna runs a separate index per country, hence the country code in the
path - the same key works for all of them.
"""
import os

from .util import get

COUNTRY_NAMES = {
    "au": "Australia", "nz": "New Zealand", "gb": "United Kingdom",
    "de": "Germany", "nl": "Netherlands", "ca": "Canada", "ie": "Ireland",
    "sg": "Singapore", "pl": "Poland", "at": "Austria", "ch": "Switzerland",
    "us": "United States", "fr": "France", "es": "Spain", "it": "Italy",
    "in": "India", "za": "South Africa", "be": "Belgium", "br": "Brazil",
    "mx": "Mexico",
}
# Words that suggest the employer will sponsor / relocate.
SPONSOR_HINTS = ["visa", "sponsor", "relocat", "work permit", "skilled",
                 "482", "186", "accredited employer", "tier 2",
                 "blue card", "blaue karte", "hsmp"]


def _search(country: str, what: str, where: str, key: tuple,
            extra: dict | None = None) -> list[dict]:
    app_id, app_key = key
    r = get(f"https://api.adzuna.com/v1/api/jobs/{country}/search/1",
            params={"app_id": app_id, "app_key": app_key,
                    "what": what, "where": where,
                    "results_per_page": 20, "max_days_old": 14,
                    "sort_by": "date", **(extra or {})})
    if r.status_code != 200:
        return []
    out = []
    for j in r.json().get("results", []):
        sal = ""
        if j.get("salary_min"):
            sal = (f"{int(j['salary_min'])}-"
                   f"{int(j.get('salary_max') or j['salary_min'])}")
        desc = j.get("description", "")
        loc = (j.get("location") or {}).get("display_name", "")
        if country != "in" and COUNTRY_NAMES.get(country, "") not in loc:
            loc = f"{loc}, {COUNTRY_NAMES.get(country, country.upper())}"
        out.append(dict(
            source=f"adzuna-{country}",
            external_id=str(j.get("id")),
            title=(j.get("title", "").replace("<strong>", "")
                   .replace("</strong>", "")),
            company=(j.get("company") or {}).get("display_name", ""),
            location=loc,
            remote="remote" in (desc + loc).lower(),
            url=j.get("redirect_url", ""),
            description=desc[:15000],
            salary=sal,
            posted_at=j.get("created", ""),
        ))
    return out


def fetch(profile):
    app_id = os.getenv("ADZUNA_APP_ID")
    app_key = os.getenv("ADZUNA_APP_KEY")
    if not (app_id and app_key):
        return []
    key = (app_id, app_key)
    roles = (profile.get("target_roles") or ["AI Engineer"])[:3]
    out = []

    # India
    locs = [l for l in profile.get("locations_priority", [])
            if l.lower() != "remote"][:4] or ["India"]
    for what in roles:
        for where in locs:
            out += _search("in", what, where, key)

    # Sponsorship markets abroad: bias the query toward postings that
    # actually mention visa sponsorship or relocation.
    if profile.get("open_to_relocation_abroad", True):
        for cc in (profile.get("abroad_countries") or [])[:8]:
            for what in roles[:2]:
                out += _search(cc, what, "", key,
                               {"what_or": "visa sponsorship relocation"})
    return out
