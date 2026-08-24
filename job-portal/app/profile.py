"""Loads the candidate profile from profile.yaml."""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent

DEFAULTS = {
    "name": "",
    "email": "",
    "phone": "",
    "current_location": "India",
    "links": {},
    "experience_years": 2,
    "current_title": "AI Engineer",
    "target_roles": ["AI Engineer", "Generative AI Engineer",
                     "Machine Learning Engineer", "Software Engineer"],
    "locations_priority": ["Noida", "Gurgaon", "Delhi NCR", "Bangalore", "Remote"],
    "open_to_remote": True,
    "open_to_relocation_abroad": True,
    "needs_visa_sponsorship": True,
    "notice_period": "",
    "current_ctc": "",
    "expected_ctc": "",
    "notes": "",
    "greenhouse_boards": [],
    "lever_companies": [],
    "ashby_companies": [],
    "company_blocklist": [],
    "title_blocklist": [],
    "max_experience_years": 2,
    "abroad_countries": ["au", "nz", "gb", "de", "nl", "ca", "ie", "sg"],
}


def load_profile() -> dict:
    prof = dict(DEFAULTS)
    p = ROOT / "profile.yaml"
    if p.exists():
        loaded = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        prof.update({k: v for k, v in loaded.items() if v is not None})
    # The base resume: whatever was uploaded through the dashboard wins,
    # otherwise the copy committed in assets/ - data/ is gitignored, so a
    # cloud run would have no resume to tailor without this fallback.
    prof["base_resume"] = ""
    for folder in ("data", "assets"):
        found = sorted((ROOT / folder).glob("base_resume.*"))
        if found:
            prof["base_resume"] = str(found[0])
            break
    return prof


def profile_summary(prof: dict) -> str:
    links = ", ".join(f"{k}: {v}" for k, v in (prof.get("links") or {}).items() if v)
    return (
        f"Name: {prof['name']}\n"
        f"Current title: {prof['current_title']} ({prof['experience_years']} years experience)\n"
        f"Based in: {prof['current_location']}\n"
        f"Target roles: {', '.join(prof['target_roles'])}\n"
        f"Preferred locations (soft preference, all-India is fine): "
        f"{', '.join(prof['locations_priority'])}\n"
        f"Open to remote: {prof['open_to_remote']}; "
        f"open to relocating abroad: {prof['open_to_relocation_abroad']} "
        f"(needs visa sponsorship: {prof['needs_visa_sponsorship']})\n"
        f"Notice period: {prof.get('notice_period') or 'not specified'}\n"
        f"Links: {links or 'none'}\n"
        f"Notes: {prof.get('notes', '').strip()}"
    )
