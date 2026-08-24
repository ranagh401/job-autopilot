"""Auto-apply on Wellfound (formerly AngelList Talent).

Approach adapted from ankitbaghel01/wellfound_autoApply, which solves the
problem the rest of our apply code could not: Wellfound is entirely behind
Cloudflare and needs a signed-in session, so no requests-based scrape works.
The answer is a *persistent* browser profile - the user signs in by hand
once, the profile directory keeps the session, and later runs reuse it.

Differences from that project, all deliberate:
  * screening answers fall back to our Azure GPT-5.1 client, not Gemini
  * state lives in our database (Application rows), not a JSON file, so a
    restart cannot re-apply to something already done
  * DRY RUN is the default here too - nothing is submitted unless the
    caller passes dry_run=False

Because this drives the user's own logged-in account, it is never run by
the scheduler. It is triggered explicitly, same as the other apply paths.
"""
from __future__ import annotations

import json
import random
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

from .browser_apply import _ask_llm, _required_but_empty, has_captcha
from .db import DATA_DIR, Application, Job, safe_commit

PROFILE_DIR = DATA_DIR / "browser-profiles" / "wellfound"
SHOTS = DATA_DIR / "screenshots"

FEED_URL = "https://wellfound.com/jobs"
LOGIN_URL = "https://wellfound.com/login"

# Pacing. The upstream project uses 60-150s between applications; keeping
# that is the point - a burst of instant applications is what gets an
# account flagged.
MIN_GAP_S = 60
MAX_GAP_S = 150
STEP_PAUSE = (3, 6)

DAILY_CAP = 20

JOB_LINK = 'a[href*="/jobs/"]'
JOB_ID = re.compile(r"/jobs/(\d+)")
APPLY_BTN = re.compile(r"^apply$|apply now", re.I)
SUBMIT_BTN = re.compile(r"^apply$|^send$|submit|send application", re.I)
APPLIED_MARK = re.compile(r"^applied$", re.I)
POSTED_AGE = re.compile(r"posted (?:about )?(\d+)\+? ?(day|week|month)s? ago",
                        re.I)


def _pause(lo: float, hi: float) -> None:
    time.sleep(random.uniform(lo, hi))


def _age_days(text: str) -> int | None:
    m = POSTED_AGE.search(text or "")
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2).lower()
    return n * {"day": 1, "week": 7, "month": 30}[unit]


def _qa_bank(profile: dict, answers: dict) -> list[tuple[re.Pattern, str]]:
    """Canned replies for the questions Wellfound asks most often.

    First match wins, so the specific patterns are listed before the
    generic ones.
    """
    name = profile.get("name", "")
    years = str(profile.get("experience_years", 2))
    notice = str(answers.get("notice_period") or
                 profile.get("notice_period") or "30 days")
    loc = profile.get("location", "Delhi NCR, India")
    return [
        (re.compile(r"years? of (work |professional |relevant )?experience",
                    re.I), years),
        (re.compile(r"notice period|when can you (start|join)", re.I), notice),
        (re.compile(r"current (ctc|salary|compensation)", re.I),
         str(profile.get("current_ctc", ""))),
        (re.compile(r"expected (ctc|salary|compensation)", re.I),
         str(profile.get("expected_ctc", ""))),
        (re.compile(r"remote|work from home", re.I), "Yes"),
        (re.compile(r"require (visa )?sponsorship|work authoriz", re.I),
         str(answers.get("work_authorisation") or
             "I am an Indian citizen and would require visa sponsorship "
             "for roles outside India.")),
        (re.compile(r"(full|first|your) name", re.I), name),
        (re.compile(r"\bphone\b|mobile|contact number", re.I),
         str(profile.get("phone", ""))),
        (re.compile(r"\bemail\b", re.I), str(profile.get("email", ""))),
        (re.compile(r"linkedin", re.I),
         str((profile.get("links") or {}).get("linkedin", ""))),
        (re.compile(r"github", re.I),
         str((profile.get("links") or {}).get("github", ""))),
        (re.compile(r"(current )?(location|city)|where are you based", re.I),
         loc),
        (re.compile(r"willing to relocate", re.I), "Yes"),
    ]


def _answer_for(label: str, job, profile: dict, answers: dict,
                bank) -> str:
    for pattern, value in bank:
        if pattern.search(label) and value:
            return value
    return _ask_llm(label, [], job, profile, answers)


def logged_in(page) -> bool:
    """Wellfound bounces anonymous visitors to /login."""
    try:
        page.goto(FEED_URL, timeout=45000, wait_until="domcontentloaded")
        _pause(2, 4)
        return "/login" not in page.url and "/jobs" in page.url
    except Exception:
        return False


def login(timeout_s: int = 300) -> str:
    """Open a real browser so the user can sign in once.

    The session is kept in PROFILE_DIR and reused by every later run.
    Deleting that directory forces a fresh sign-in.
    """
    from playwright.sync_api import sync_playwright

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR), headless=False,
            args=["--disable-blink-features=AutomationControlled"])
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(LOGIN_URL, wait_until="domcontentloaded")

        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if "/login" not in page.url:
                _pause(2, 3)
                ctx.close()
                return "signed in - session saved"
            time.sleep(3)
        ctx.close()
        return f"timed out after {timeout_s}s without a completed sign-in"


def _collect_jobs(page, want: int, max_age_days: int) -> list[dict]:
    """Scroll the feed and gather candidate job links."""
    found, seen = [], set()
    for _ in range(12):
        cards = page.query_selector_all(JOB_LINK)
        for c in cards:
            try:
                href = c.get_attribute("href") or ""
                m = JOB_ID.search(href)
                if not m or m.group(1) in seen:
                    continue
                row = c.evaluate(
                    "el => (el.closest('[data-test],li,div') || el).innerText")
                if APPLIED_MARK.search(row or ""):
                    continue
                age = _age_days(row or "")
                if age is not None and age > max_age_days:
                    continue
                seen.add(m.group(1))
                url = href if href.startswith("http") \
                    else "https://wellfound.com" + href
                found.append({"id": m.group(1), "url": url,
                              "text": (row or "")[:300]})
            except Exception:
                continue
        if len(found) >= want:
            break
        page.mouse.wheel(0, 4000)
        _pause(1.5, 3)
    return found[:want]


def _fill_modal(page, job, profile, answers, resume_path, bank) -> dict:
    """Fill the apply dialog. Returns what was filled and what blocked."""
    filled, skipped = {}, []
    modal = page.query_selector('[role="dialog"]') or page

    for ta in modal.query_selector_all("textarea"):
        try:
            if not ta.is_visible():
                continue
            from .browser_apply import _label_for
            label = _label_for(page, ta) or "cover letter"
            text = _answer_for(label, job, profile, answers, bank)
            if not text:
                continue
            ta.fill(text)
            filled[label[:60]] = text[:80]
            _pause(*STEP_PAUSE)
        except Exception:
            continue

    for inp in modal.query_selector_all(
            'input[type="text"], input[type="tel"], input[type="email"], '
            'input[type="url"], input:not([type])'):
        try:
            if not inp.is_visible() or inp.input_value():
                continue
            from .browser_apply import _label_for
            label = _label_for(page, inp)
            value = _answer_for(label, job, profile, answers, bank)
            if not value:
                skipped.append(label[:60])
                continue
            inp.fill(value)
            filled[label[:60]] = value[:60]
        except Exception:
            continue

    if resume_path and Path(resume_path).exists():
        for fi in modal.query_selector_all('input[type="file"]'):
            try:
                fi.set_input_files(resume_path)
                filled["resume"] = Path(resume_path).name
                _pause(*STEP_PAUSE)
                break
            except Exception:
                continue

    return {"filled": filled, "skipped": skipped}


def apply_batch(session, profile: dict, limit: int = 5,
                dry_run: bool = True, max_age_days: int = 14) -> str:
    """Apply to up to `limit` Wellfound jobs using the saved session."""
    from playwright.sync_api import sync_playwright

    if not PROFILE_DIR.exists():
        return ("no saved Wellfound session - run the login step first "
                "(app.wellfound_apply.login())")

    since = datetime.now() - timedelta(days=1)
    today_n = session.query(Application).filter(
        Application.ats == "wellfound",
        Application.status == "submitted",
        Application.submitted_at >= since).count()
    room = max(0, DAILY_CAP - today_n)
    if not room:
        return f"wellfound daily cap reached ({today_n}/{DAILY_CAP})"
    limit = min(limit, room)

    answers = {
        "notice_period": profile.get("notice_period", ""),
        "work_authorisation": profile.get("work_authorisation", ""),
    }
    bank = _qa_bank(profile, answers)
    SHOTS.mkdir(parents=True, exist_ok=True)

    done, blocked, notes = 0, 0, []
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR), headless=False,
            args=["--disable-blink-features=AutomationControlled"])
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        if not logged_in(page):
            ctx.close()
            return "saved Wellfound session has expired - run login again"

        targets = _collect_jobs(page, limit * 3, max_age_days)
        notes.append(f"{len(targets)} candidate jobs on the feed")

        for t in targets:
            if done >= limit:
                break
            existing = session.query(Application).filter(
                Application.ats == "wellfound",
                Application.url == t["url"]).first()
            if existing:
                continue

            job = (session.query(Job)
                   .filter(Job.url == t["url"]).first())
            if job is None:
                title = (t["text"].splitlines() or [""])[0][:200]
                job = Job(source="wellfound", external_id=t["id"],
                          title=title, company="", url=t["url"],
                          description=t["text"], status="found")
                session.add(job)
                safe_commit(session)

            try:
                page.goto(t["url"], timeout=45000,
                          wait_until="domcontentloaded")
                _pause(*STEP_PAUSE)

                if has_captcha(page):
                    blocked += 1
                    session.add(Application(
                        job_id=job.id, ats="wellfound", url=t["url"],
                        status="manual_needed",
                        detail="CAPTCHA shown - solve it by hand"))
                    safe_commit(session)
                    continue

                btn = page.get_by_role("button", name=APPLY_BTN).first
                if not btn or not btn.is_visible():
                    continue
                btn.click()
                _pause(*STEP_PAUSE)

                result = _fill_modal(page, job, profile, answers,
                                     profile.get("resume_path", ""), bank)
                missing = _required_but_empty(page)

                shot = SHOTS / f"wellfound-{t['id']}.png"
                try:
                    page.screenshot(path=str(shot))
                except Exception:
                    pass

                if missing:
                    blocked += 1
                    session.add(Application(
                        job_id=job.id, ats="wellfound", url=t["url"],
                        status="manual_needed",
                        answers=json.dumps(result["filled"])[:4000],
                        detail="unanswered required fields: "
                               + ", ".join(missing[:6])))
                    safe_commit(session)
                    continue

                if dry_run:
                    session.add(Application(
                        job_id=job.id, ats="wellfound", url=t["url"],
                        status="prepared",
                        answers=json.dumps(result["filled"])[:4000],
                        detail="DRY RUN - form filled, not submitted"))
                    safe_commit(session)
                    done += 1
                    _pause(MIN_GAP_S, MAX_GAP_S)
                    continue

                page.get_by_role("button", name=SUBMIT_BTN).first.click(
                    timeout=12000)
                _pause(*STEP_PAUSE)
                session.add(Application(
                    job_id=job.id, ats="wellfound", url=t["url"],
                    status="submitted", submitted_at=datetime.now(),
                    answers=json.dumps(result["filled"])[:4000],
                    detail="submitted via Wellfound"))
                job.status = "applied"
                safe_commit(session)
                done += 1
                _pause(MIN_GAP_S, MAX_GAP_S)

            except Exception as e:
                blocked += 1
                session.add(Application(
                    job_id=job.id, ats="wellfound", url=t["url"],
                    status="failed", detail=str(e)[:400]))
                safe_commit(session)

        ctx.close()

    mode = "prepared (dry run)" if dry_run else "submitted"
    notes.append(f"{done} {mode}, {blocked} need attention")
    return "wellfound: " + "; ".join(notes)
