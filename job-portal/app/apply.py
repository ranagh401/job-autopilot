"""Applying through a company's own web form.

Reality check on automation here: Greenhouse and Lever render a
predictable form we can fill and POST. Workday, Taleo, SuccessFactors and
friends are multi-step wizards behind sessions and custom screening
questions - blind submission there produces broken applications under the
candidate's name, which cannot be withdrawn. So we submit where it is
reliable, and everywhere else we prepare the answers and hand over a
ready-to-paste application.
"""
from __future__ import annotations

import mimetypes
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .llm import chat, llm_ready
from .profile import profile_summary

UA = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                     "AppleWebKit/537.36 (KHTML, like Gecko) "
                     "Chrome/120.0.0.0 Safari/537.36")}

# Which applicant-tracking system is behind this URL.
ATS_PATTERNS = [
    ("greenhouse", r"(boards\.)?greenhouse\.io|job-boards\.greenhouse\.io"),
    ("lever", r"jobs\.lever\.co"),
    ("ashby", r"jobs\.ashbyhq\.com"),
    ("workable", r"apply\.workable\.com"),
    ("smartrecruiters", r"jobs\.smartrecruiters\.com"),
    ("recruitee", r"\.recruitee\.com"),
    ("personio", r"\.jobs\.personio\.(de|com)"),
    ("workday", r"myworkdayjobs\.com|workday\.com"),
    ("taleo", r"taleo\.net"),
    ("successfactors", r"successfactors\.(com|eu)"),
    ("icims", r"icims\.com"),
    ("linkedin", r"linkedin\.com/jobs"),
    ("naukri", r"naukri\.com"),
    ("indeed", r"indeed\.com"),
]
# Where an automated POST is realistic.
#
# Verified against live boards (Aug 2026): Lever still serves a classic
# HTML form - real `name` attributes, method=POST, a plain file input -
# so it can be filled and submitted over HTTP. Greenhouse no longer can:
# its form carries `id` attributes but NO `name`s and declares method=get,
# because JavaScript gathers the values and posts them itself. Anything
# built on scraping that would silently submit nothing, so Greenhouse is
# treated like Workday - answers prepared, submission left to the user.
AUTOMATABLE = {"lever"}

COVER_SYSTEM = (
    "Write the answers a job application form asks for, in the "
    "candidate's own voice. Never invent experience, employers or "
    "qualifications beyond the profile given. Plain text, no markdown, "
    "and no hint that this was machine-written.\n"
    'Respond with JSON: {"cover_letter": "<180-260 words, addressed to '
    'the hiring team, specific to this role>", '
    '"why_company": "<60-90 words>", '
    '"notice_period": "<short>", "salary_expectation": "<short, or '
    '\'Negotiable\'>", "work_authorisation": "<short statement of visa '
    'status/need for this country>"}'
)


def detect_ats(url: str) -> str:
    u = (url or "").lower()
    for name, pattern in ATS_PATTERNS:
        if re.search(pattern, u):
            return name
    return "other"


def can_auto_submit(url: str) -> bool:
    return detect_ats(url) in AUTOMATABLE


def build_answers(job, profile: dict) -> dict:
    """The free-text answers every application form wants."""
    if not llm_ready():
        return {}
    user = (
        "CANDIDATE:\n" + profile_summary(profile) + "\n\n"
        f"ROLE: {job.title}\nCOMPANY: {job.company}\n"
        f"LOCATION: {job.location} ({job.country or 'India'})\n"
        f"POSTING:\n{(job.description or '')[:5000]}"
    )
    try:
        return chat(COVER_SYSTEM, user, json_mode=True, kind="cover-letter")
    except Exception:
        return {}


# ---------- Greenhouse ----------

def _greenhouse_ids(url: str) -> tuple[str, str]:
    """(board token, job id) from a Greenhouse posting URL."""
    m = re.search(r"greenhouse\.io/(?:embed/job_app\?for=)?([\w-]+)", url)
    board = m.group(1) if m else ""
    m2 = (re.search(r"[?&]gh_jid=(\d+)", url)
          or re.search(r"/jobs/(\d+)", url)
          or re.search(r"[?&]token=(\d+)", url))
    return board, (m2.group(1) if m2 else "")


def _form_fields(html: str, form_selector: str = "form") -> tuple[str, dict]:
    """Action URL plus the hidden/default values a form expects."""
    soup = BeautifulSoup(html, "html.parser")
    form = soup.select_one(form_selector)
    if not form:
        return "", {}
    data = {}
    for inp in form.find_all(["input", "textarea", "select"]):
        name = inp.get("name")
        if not name or inp.get("type") == "file":
            continue
        if inp.get("type") in ("submit", "button"):
            continue
        data[name] = inp.get("value") or ""
    return form.get("action") or "", data


def greenhouse_apply_url(job) -> str:
    """The page a human should open to apply."""
    board, jid = _greenhouse_ids(job.url or "")
    if board and jid:
        return (f"https://boards.greenhouse.io/embed/job_app"
                f"?for={board}&token={jid}")
    return job.url or ""


# ---------- Lever ----------

def submit_lever(job, profile: dict, resume_path: str,
                 answers: dict) -> dict:
    m = re.search(r"jobs\.lever\.co/([\w-]+)/([\w-]+)", job.url or "")
    if not m:
        return {"ok": False, "detail": "could not read the Lever ids"}
    company, posting = m.group(1), m.group(2)
    apply_url = f"https://jobs.lever.co/{company}/{posting}/apply"
    sess = requests.Session()
    sess.headers.update(UA)
    try:
        page = sess.get(apply_url, timeout=30)
    except Exception as e:
        return {"ok": False, "detail": f"form fetch failed: {e}"}
    if page.status_code != 200:
        return {"ok": False, "detail": f"form fetch HTTP {page.status_code}"}

    _, data = _form_fields(page.text)
    links = profile.get("links") or {}
    data.update({
        "name": profile.get("name", ""),
        "email": profile.get("email", ""),
        "phone": str(profile.get("phone", "")),
        "location": profile.get("current_location", ""),
        "urls[LinkedIn]": links.get("linkedin", ""),
        "urls[GitHub]": links.get("github", ""),
        "comments": answers.get("cover_letter", ""),
    })
    files = {}
    if resume_path and Path(resume_path).exists():
        ctype = (mimetypes.guess_type(resume_path)[0]
                 or "application/octet-stream")
        files["resume"] = (Path(resume_path).name,
                           Path(resume_path).read_bytes(), ctype)
    try:
        r = sess.post(apply_url, data=data, files=files, timeout=60)
    except Exception as e:
        return {"ok": False, "detail": f"submit failed: {e}"}
    body = (r.text or "").lower()
    if r.status_code in (200, 201, 302) and (
            "thank" in body or "received" in body or "applied" in body):
        return {"ok": True, "detail": "Lever accepted the application"}
    return {"ok": False,
            "detail": f"Lever returned HTTP {r.status_code} without a "
                      f"confirmation - submit this one by hand"}


def apply_to_job(job, profile: dict, resume_path: str,
                 answers: dict | None = None) -> dict:
    """Submit where that is reliable; otherwise prepare the application."""
    ats = detect_ats(job.url)
    answers = answers if answers is not None else build_answers(job, profile)
    apply_url = job.url
    if ats == "lever":
        res = submit_lever(job, profile, resume_path, answers)
    elif ats == "greenhouse":
        apply_url = greenhouse_apply_url(job)
        res = {"ok": False,
               "detail": "Greenhouse builds its form in JavaScript, so it "
                         "cannot be filled over HTTP - your answers and "
                         "resume are ready, submit from the link"}
    else:
        res = {"ok": False,
               "detail": f"{ats} forms are multi-step and vary per employer "
                         f"- answers prepared, submit from the link"}
    res.update({"ats": ats, "answers": answers, "url": apply_url})
    return res
