"""LLM scoring of jobs against the candidate profile."""
from __future__ import annotations

import os
import re

from .llm import chat
from .profile import profile_summary

SYSTEM = (
    "You score how well a job posting matches a candidate looking for their "
    "next role. Consider: role fit (AI/ML/GenAI/software engineering), "
    "seniority fit (the candidate has ~2 years of experience: score 0-25 for "
    "anything demanding 5+ years or a senior/lead/staff/principal title, "
    "0-45 for 3-4 years, and only score above 65 when the posting is open "
    "to roughly 0-3 years), and location fit "
    "(anywhere in India is fine, remote-friendly roles are fine, and roles "
    "abroad are good ONLY if the company plausibly sponsors visas - look for "
    "sponsorship/relocation mentions). Titles-only postings (from alert "
    "emails) should be scored on the title alone, slightly conservatively.\n"
    'Respond with JSON: {"score": <int 0-100>, "reasons": "<1-2 sentences>", '
    '"sponsorship_likely": <true|false|null>, '
    '"experience_required": "<VERY short, max 10 characters, digits+yrs '
    'only, e.g. \'2-4 yrs\', \'5+ yrs\', \'fresher\'; \'\' if not stated. '
    'Never write a sentence>", '
    '"exp_min_years": <minimum years as a number, or null>, '
    '"country": "<the country the role is based in, e.g. \'India\', '
    '\'Germany\', \'United States\'. The location may appear in the title, '
    'company field or description rather than the location field - read '
    'them all. Use \'Remote\' only when the posting is genuinely '
    'location-independent worldwide; use \'\' if you truly cannot tell>", '
    '"is_india": <true if the role is based in India (including '
    'India-based remote), false if it is anywhere outside India, null if '
    'genuinely unknown>, '
    '"clean_title": "<just the job title, e.g. \'Generative AI Engineer\'. '
    'Some listings arrive as one run-on string mixing title, company, '
    'location and UI noise like \'Easy Apply\' - separate them>", '
    '"clean_company": "<just the employer name, e.g. \'The Agentic Loop\'. '
    '\'\' if the listing never names it - never put a location here>"}'
)

# Listing text that clearly still holds scraped UI noise rather than a name.
JUNK_FIELD = re.compile(
    r"easy apply|actively recruiting|be an early applicant|promoted|"
    r"\(remote\)|\(on-?site\)|\(hybrid\)|\$[\d.,]+k?\s*[-–]|full time -",
    re.I)

# Fallback when the posting text states the range but the LLM leaves it blank.
EXP_RE = re.compile(
    r"(\d{1,2})\s*(?:\+|plus)?\s*(?:-|to|–)?\s*(\d{1,2})?\s*\+?\s*"
    r"(?:years?|yrs?)(?:\s+of)?\s+(?:relevant\s+|professional\s+|work\s+)?"
    r"experience", re.I)


def _regex_experience(text: str) -> tuple[str, float | None]:
    m = EXP_RE.search(text or "")
    if not m:
        return "", None
    lo = float(m.group(1))
    hi = m.group(2)
    return (f"{int(lo)}-{int(float(hi))} yrs" if hi else f"{int(lo)}+ yrs"), lo


def _tidy_experience(text: str, minimum: float | None) -> str:
    """Squeeze a wordy answer down to something a table column can show."""
    t = (text or "").strip()
    if not t:
        return ""
    if len(t) <= 12:
        return t
    m = re.search(r"(\d{1,2})\s*(?:-|to|–)\s*(\d{1,2})", t)
    if m:
        return f"{m.group(1)}-{m.group(2)} yrs"
    m = re.search(r"(\d{1,2})\s*\+", t)
    if m:
        return f"{m.group(1)}+ yrs"
    m = re.search(r"(\d{1,2})", t)
    if m:
        return f"{m.group(1)}+ yrs"
    if re.search(r"fresher|entry.level|graduate", t, re.I):
        return "fresher"
    if minimum is not None:
        return f"{int(minimum)}+ yrs"
    return t[:12]


def score_job(session, job, profile) -> None:
    user = (
        "CANDIDATE:\n" + profile_summary(profile) + "\n\n"
        "JOB POSTING:\n"
        f"Title: {job.title}\nCompany: {job.company}\n"
        f"Location: {job.location}{' (remote)' if job.remote else ''}\n"
        f"Salary: {job.salary or 'n/a'}\nSource: {job.source}\n"
        f"Description:\n{(job.description or '')[:6000]}"
    )
    out = chat(SYSTEM, user, json_mode=True, kind="score-job")
    job.match_score = float(out.get("score") or 0)
    job.match_notes = str(out.get("reasons") or "")[:2000]
    sp = out.get("sponsorship_likely")
    job.sponsorship_likely = sp if isinstance(sp, bool) else None

    # Alert-email listings arrive as run-on text; take the LLM's split.
    if JUNK_FIELD.search(f"{job.title} {job.company}"):
        ct = str(out.get("clean_title") or "").strip()[:300]
        cc = str(out.get("clean_company") or "").strip()[:300]
        if ct and not JUNK_FIELD.search(ct):
            job.title = ct
        if cc and not JUNK_FIELD.search(cc):
            job.company = cc
        elif JUNK_FIELD.search(job.company or ""):
            job.company = ""

    job.country = str(out.get("country") or "").strip()[:60]
    ind = out.get("is_india")
    job.is_india = ind if isinstance(ind, bool) else None

    exp = str(out.get("experience_required") or "").strip()[:40]
    try:
        exp_min = float(out["exp_min_years"]) \
            if out.get("exp_min_years") is not None else None
    except (TypeError, ValueError):
        exp_min = None
    if not exp:
        exp, exp_min = _regex_experience(
            f"{job.title}\n{job.description or ''}")
    job.experience_required = _tidy_experience(exp, exp_min)
    job.exp_min_years = exp_min

    max_exp = float(profile.get("max_experience_years") or 2)
    too_senior = exp_min is not None and exp_min > max_exp
    threshold = float(os.getenv("MATCH_THRESHOLD", "65"))
    if job.status in ("found", "scored"):
        if too_senior:
            # Never shortlist a role that outright demands more years than
            # the candidate has - it wastes an application.
            job.status = "skipped"
            job.match_notes = (f"Needs {job.experience_required} "
                               f"(over your {max_exp:.0f}-year ceiling). "
                               + job.match_notes)[:2000]
        else:
            job.status = ("shortlisted" if job.match_score >= threshold
                          else "scored")
    session.commit()
