"""Recruiters who publish their own address in a hiring post.

"We're hiring an AI Engineer - send your CV to priya@acme.com" is a
direct invitation to email, and the address is already public. This
searches for those posts, pulls out the address plus the role and
company around it, and files each as a job with the contact attached.

Needs a real search API (GOOGLE_API_KEY + GOOGLE_CSE_ID) - scraped Bing
results ignore quoted phrases, which makes these searches useless.
"""
from __future__ import annotations

import os
import re

from ..contacts import (BAD_PARTS, EMAIL_RE, NON_HR_BOX, PLACEHOLDER_NAME,
                        _clean, _emails_from_page, _search)
from ..llm import chat, llm_ready

# The phrasings recruiters actually use when inviting applications.
QUERIES = [
    '"hiring" "{role}" "{where}" "share your resume at"',
    '"we are hiring" "{role}" "{where}" "send your CV to"',
    '"hiring" "{role}" "{where}" "drop your resume at"',
    '"{role}" "{where}" hiring "interested candidates can mail"',
    '"hiring" "{role}" "{where}" "reach out at" email',
]

EXTRACT_SYSTEM = (
    "You are reading a snippet of a recruitment post that contains an "
    "email address. Pull out what is being advertised.\n"
    'Respond with JSON: {"is_hiring_post": true|false, '
    '"role": "<job title, or \'\'>", "company": "<employer, or \'\'>", '
    '"location": "<city/country, or \'\'>", '
    '"recruiter_name": "<person named as the contact, or \'\'>"}\n'
    "is_hiring_post must be false unless this is genuinely someone "
    "advertising a job opening and inviting applications by email."
)


# Domains that are platforms, mail providers or aggregators - never the
# employer, however confidently a post quotes them.
NOT_EMPLOYER_DOMAIN = re.compile(
    r"@(gmail|googlemail|google|yahoo|outlook|hotmail|live|proton|rediff|"
    r"icloud|aol)\.|@(internshala|naukri|indeed|linkedin|glassdoor|"
    r"monster|shine|timesjobs|foundit|apna|cutshort|instahyre|hirist|"
    r"wellfound|angel)\.", re.I)


def _looks_personal(email: str) -> bool:
    local = email.split("@")[0]
    if NON_HR_BOX.match(local) or PLACEHOLDER_NAME.search(email):
        return False
    # A free mail provider or a job platform is not an employer address.
    if NOT_EMPLOYER_DOMAIN.search(email):
        return False
    return not any(b in email for b in BAD_PARTS)


# Last run, so a 45-minute pipeline cycle cannot drain a monthly search
# allowance. Brave's free tier is ~1,000 searches/month; at 8 queries
# twice a day this uses roughly 480.
_last_run: list = [0.0]


def _due() -> bool:
    import time
    gap = float(os.getenv("HIRING_POSTS_EVERY_HOURS", "12")) * 3600
    if time.time() - _last_run[0] < gap:
        return False
    _last_run[0] = time.time()
    return True


def fetch(profile):
    if os.getenv("HIRING_POSTS", "true").lower() != "true":
        return []
    # Needs a real search API. Scraped results ignore quoted phrases and
    # return junk for these queries, and Google's API is closed to new
    # customers - so require Brave or Serper specifically.
    if not (os.getenv("BRAVE_API_KEY") or os.getenv("SERPER_API_KEY")):
        return []
    # Paid-per-query APIs: run twice a day, not every pipeline cycle.
    if not _due():
        return []

    roles = (profile.get("target_roles") or ["AI Engineer"])[:3]
    places = [l for l in (profile.get("locations_priority") or [])
              if l.lower() != "remote"][:2] or ["India"]
    seen: set[str] = set()
    out = []
    budget = int(os.getenv("HIRING_POST_QUERIES", "8"))
    spent = 0

    for role in roles:
        for where in places:
            for template in QUERIES:
                if spent >= budget:
                    return out
                spent += 1
                query = template.format(role=role, where=where)
                urls, snippet_emails = _search(query, max_links=8,
                                               keep_all=True)
                candidates = list(snippet_emails)
                for u in urls[:3]:
                    candidates += _emails_from_page(u, follow_contact=False)

                for email in _clean(candidates):
                    if email in seen or not _looks_personal(email):
                        continue
                    seen.add(email)
                    info = {"role": role, "company": "", "location": where,
                            "recruiter_name": ""}
                    if llm_ready():
                        try:
                            got = chat(EXTRACT_SYSTEM,
                                       f"SEARCH QUERY: {query}\n\n"
                                       f"EMAIL FOUND: {email}\n\n"
                                       f"CONTEXT:\n{query}",
                                       json_mode=True)
                            if not got.get("is_hiring_post"):
                                continue
                            info.update({k: str(got.get(k) or info.get(k, ""))
                                         for k in info})
                        except Exception:
                            pass
                    company = info["company"] or email.split("@")[1].split(".")[0]
                    out.append(dict(
                        source="hiring-post",
                        external_id=email,
                        title=info["role"] or role,
                        company=company.title(),
                        location=info["location"] or where,
                        remote=False,
                        url="",
                        description=(
                            f"Recruiter published this opening and invited "
                            f"applications by email.\n\n"
                            f"Contact: {info['recruiter_name'] or email}\n"
                            f"Role: {info['role'] or role}\n"
                            f"Company: {company}\n"
                            f"Location: {info['location'] or where}\n\n"
                            f"Found via a public search for hiring posts."),
                        posted_at="",
                        # carried through so the contact can be attached
                        _contact_email=email,
                        _contact_name=info["recruiter_name"],
                    ))
    return out
