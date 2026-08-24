"""Background loop: fetch -> score -> find contacts -> draft -> send -> poll."""
from __future__ import annotations

import json
import os
import threading
import time
import traceback
from datetime import datetime

from . import (apply, contacts, emailer, enrich, matching, replies, sources,
               tailor)
from .db import Application, Job, Outreach, SessionLocal
from .llm import llm_ready
from .profile import load_profile

STATE: dict = {"last_cycle": None, "last_fetch": None, "log": []}
_started = False

# The hourly cycle and any task triggered from the dashboard run in the
# same process but different threads, and SQLite allows one writer. Hold
# this for the duration of a pipeline step so they queue instead of
# colliding with "database is locked".
PIPELINE_LOCK = threading.Lock()


def log(msg: str) -> None:
    STATE["log"].insert(0, (datetime.now().strftime("%d %b %H:%M"), str(msg)[:400]))
    del STATE["log"][60:]


def run_fetch(session, prof) -> str:
    counts = sources.fetch_all(session, prof)
    STATE["last_fetch"] = datetime.now()
    msg = "fetch: " + ", ".join(f"{k}: {v}" for k, v in counts.items())
    log(msg)
    return msg


def run_score(session, prof, limit: int | None = None) -> str:
    if not llm_ready():
        return "LLM not configured"
    limit = limit or int(os.getenv("SCORE_LIMIT_PER_CYCLE", "25"))
    new = (session.query(Job).filter(Job.status == "found")
           .order_by(Job.found_at.desc()).limit(limit).all())
    done, failed = 0, 0
    for j in new:
        try:
            matching.score_job(session, j, prof)
            done += 1
        except Exception as e:
            failed += 1
            if failed >= 3:
                log(f"scoring aborted after repeated errors: {e}")
                break
    msg = f"scored {done} jobs" + (f" ({failed} failed)" if failed else "")
    if done or failed:
        log(msg)
    return msg


def run_enrich(session, limit: int = 25) -> str:
    """Fetch the real posting for jobs that arrived as a bare title+link."""
    thin = [j for j in session.query(Job)
            .filter(Job.status.in_(["found", "scored", "shortlisted"]))
            .order_by(Job.found_at.desc()).limit(200).all()
            if enrich.needs_enrichment(j)]
    done = 0
    for j in thin[:limit]:
        try:
            if enrich.enrich_job(session, j):
                done += 1
                # A fuller posting deserves a fresh score.
                if j.status in ("scored", "shortlisted"):
                    j.status = "found"
        except Exception:
            pass
    session.commit()
    msg = f"enriched {done} of {len(thin)} thin postings"
    if done:
        log(msg)
    return msg


def run_cleanup(session, prof) -> str:
    """Retire jobs that no longer pass the role/experience rules - e.g.
    after tightening max_experience_years or the title blocklist."""
    from .matching import _regex_experience
    from .sources import role_matches

    max_exp = float(prof.get("max_experience_years") or 2)
    blocked = [b.lower() for b in (prof.get("title_blocklist") or []) if b]
    active = ["found", "scored", "shortlisted", "tailored"]
    jobs = session.query(Job).filter(Job.status.in_(active)).all()
    senior = offrole = 0
    for j in jobs:
        title = (j.title or "").lower()
        # Jobs scored before experience extraction existed have no value
        # yet - read it straight out of the posting, no LLM call needed.
        if j.exp_min_years is None:
            exp, exp_min = _regex_experience(
                f"{j.title}\n{j.description or ''}")
            if exp_min is not None:
                j.experience_required = exp
                j.exp_min_years = exp_min
        if j.exp_min_years is not None and j.exp_min_years > max_exp:
            j.status = "skipped"
            senior += 1
        elif any(b in title for b in blocked) or not role_matches(j.title):
            j.status = "skipped"
            offrole += 1
    session.commit()
    msg = (f"cleanup: skipped {senior} over-experience and {offrole} "
           f"off-target jobs")
    if senior or offrole:
        log(msg)
    return msg


def run_contacts(session, limit: int | None = None) -> str:
    limit = limit or int(os.getenv("CONTACTS_PER_CYCLE", "20"))
    jobs = (session.query(Job)
            .filter(Job.status.in_(["shortlisted", "tailored"]),
                    Job.contact_email == "")
            .order_by(Job.match_score.desc().nullslast())
            .limit(limit).all())
    n = people = 0
    for j in jobs:
        try:
            contacts.discover(session, j)
            n += 1
            if any(c.is_person for c in j.contacts):
                people += 1
        except Exception:
            pass
    # Re-check jobs whose contacts predate LLM verification.
    stale = (session.query(Job)
             .filter(Job.status.in_(["shortlisted", "tailored"]))
             .limit(60).all())
    rechecked = 0
    for j in stale:
        if rechecked >= limit:
            break
        if any(c.verified is None for c in j.contacts):
            try:
                contacts.verify_contacts(session, j)
                contacts._choose_primary(session, j)
                rechecked += 1
            except Exception:
                pass
    msg = (f"contact discovery on {n} jobs ({people} found a real person)"
           + (f"; re-verified {rechecked}" if rechecked else ""))
    if n or rechecked:
        log(msg)
    return msg


def run_tailor(session, prof, limit: int = 6) -> str:
    """Build a market-appropriate resume for shortlisted jobs."""
    if not llm_ready() or not prof.get("base_resume"):
        return "tailoring unavailable"
    jobs = (session.query(Job).filter(Job.status == "shortlisted")
            .order_by(Job.match_score.desc().nullslast()).limit(40).all())
    made = 0
    for j in jobs:
        if made >= limit:
            break
        if j.resumes:
            continue
        try:
            res = tailor.tailor_resume(session, j, prof)
            made += 1
            log(f"tailored {res['format']} {res['doc_name']} for "
                f"{j.company[:24]} (ATS {res['ats']['overall']:.0f})")
        except Exception as e:
            log(f"tailoring failed for job {j.id}: {e}")
            break
    return f"tailored {made} resumes"


def run_apply(session, prof, limit: int | None = None) -> str:
    """Prepare applications for review - nothing is submitted here.

    Each one records exactly which company, role, ATS and URL it targets,
    plus the cover letter and answers, and waits at `pending_approval`
    until approved from the dashboard.
    """
    limit = limit or int(os.getenv("APPLY_PER_CYCLE", "10"))
    if os.getenv("AUTO_APPLY", "true").lower() != "true":
        return "application prep off"
    jobs = (session.query(Job)
            .filter(Job.status.in_(["shortlisted", "tailored"]),
                    Job.url != "")
            .order_by(Job.match_score.desc().nullslast()).limit(120).all())

    def worth_applying(j) -> tuple:
        """Order by how likely the application is to go anywhere: forms we
        can submit ourselves first, then India, then places that would
        actually sponsor - a US-only role that never sponsors is a waste
        of an application."""
        auto = 0 if apply.can_auto_submit(j.url) else 1
        india = 0 if j.is_india else 1
        sponsor = 0 if (j.is_india or j.sponsorship_likely
                        or j.remote) else 1
        return (auto, sponsor, india, -(j.match_score or 0))

    jobs.sort(key=worth_applying)
    prepared = 0
    for j in jobs:
        if prepared >= limit:
            break
        if j.applications:
            continue
        if not contacts.has_identifiable_employer(j):
            continue
        ats = apply.detect_ats(j.url)
        if ats in ("linkedin", "naukri", "indeed", "other"):
            continue  # aggregator link, not the employer's own form
        try:
            if not j.resumes:
                tailor.tailor_resume(session, j, prof)
                # The relationship is stale until refreshed, and without
                # this the generic base resume gets attached instead of
                # the tailored one.
                session.refresh(j)
            resume = (sorted(j.resumes, key=lambda r: r.created_at)[-1].path
                      if j.resumes else prof.get("base_resume", ""))
            answers = apply.build_answers(j, prof)
            auto = apply.can_auto_submit(j.url)
            session.add(Application(
                job_id=j.id, ats=ats,
                url=(apply.greenhouse_apply_url(j) if ats == "greenhouse"
                     else j.url),
                status="pending_approval",
                detail=("will be submitted automatically once you approve"
                        if auto else
                        f"{ats} needs the form filled by hand - approve to "
                        f"mark it done, the answers are ready to paste"),
                cover_letter=answers.get("cover_letter", ""),
                answers=json.dumps(answers),
                resume_path=resume,
            ))
            prepared += 1
        except Exception as e:
            log(f"could not prepare application for job {j.id}: {e}")
    session.commit()
    msg = f"prepared {prepared} application(s) awaiting your approval"
    if prepared:
        log(msg)
    return msg


def submit_application(session, rec, prof) -> dict:
    """Actually send an approved application.

    Lever accepts a direct POST. Everything else is a JavaScript form, so
    a real browser fills it - and refuses to submit if any required
    question is still unanswered.
    """
    job = rec.job
    answers = json.loads(rec.answers or "{}")
    if apply.can_auto_submit(job.url):
        res = apply.apply_to_job(job, prof, rec.resume_path, answers=answers)
    elif os.getenv("BROWSER_APPLY", "true").lower() == "true":
        from . import browser_apply
        res = browser_apply.fill_and_submit(
            job, prof, rec.resume_path, answers, submit=True)
        res.setdefault("ats", rec.ats)
        if res.get("filled"):
            res["detail"] = (f"{res['detail']} "
                             f"[filled {len(res['filled'])} fields"
                             + (f", {len(res['skipped'])} left blank]"
                                if res.get("skipped") else "]"))
        if res.get("screenshot"):
            rec.detail = res["detail"][:2000]
    else:
        res = apply.apply_to_job(job, prof, rec.resume_path, answers=answers)
    if res["ok"]:
        rec.status = "submitted"
        rec.submitted_at = datetime.now()
        if job and job.status in ("shortlisted", "tailored"):
            job.status = "sent"
        log(f"applied on {res['ats']} to {job.company[:24]} - "
            f"{job.title[:36]}")
    elif res.get("captcha"):
        # Not a failure on our side: the employer requires a human check.
        rec.status = "manual_needed"
    else:
        rec.status = ("manual_needed" if res["ats"] not in apply.AUTOMATABLE
                      else "failed")
    rec.detail = res["detail"][:2000]
    session.commit()
    return res


def run_draft(session, prof, limit: int | None = None) -> str:
    limit = limit or int(os.getenv("DRAFTS_PER_CYCLE", "20"))
    if not llm_ready():
        return "LLM not configured"
    jobs = (session.query(Job)
            .filter(Job.status.in_(["shortlisted", "tailored"]),
                    Job.contact_email != "")
            .limit(50).all())
    drafted = 0
    for j in jobs:
        if drafted >= limit:
            break
        if session.query(Outreach.id).filter_by(job_id=j.id).first():
            continue
        try:
            # Make sure a market-correct resume exists before writing the
            # email, so the right document gets attached.
            if not j.resumes and prof.get("base_resume"):
                try:
                    tailor.tailor_resume(session, j, prof)
                except Exception:
                    pass
            emailer.draft_outreach(session, j, prof)
            drafted += 1
        except Exception as e:
            log(f"draft failed for job {j.id}: {e}")
            break
    if drafted:
        log(f"drafted {drafted} emails (waiting in the queue for approval)")
    return f"drafted {drafted}"


def run_followups(session, prof) -> str:
    if os.getenv("FOLLOWUPS_ENABLED", "true").lower() != "true":
        return "follow-ups disabled"
    n = emailer.create_followups(session, prof)
    if n:
        log(f"queued {n} follow-up(s) for unanswered emails")
    return f"queued {n} follow-ups"


def run_autosend(session) -> str:
    """Approve clean drafts unattended when AUTO_SEND is on."""
    if os.getenv("AUTO_SEND", "false").lower() != "true":
        return "auto-send off"
    approved, held = emailer.auto_approve(session)
    msg = f"auto-approved {approved} draft(s)"
    if held:
        msg += f"; {len(held)} held for review ({held[0]})"
    if approved or held:
        log(msg)
    return msg


def run_send(session, limit: int | None = None, gap: int = 0) -> str:
    if not emailer.gmail_ready():
        return "Gmail not configured"
    sent, errors = emailer.send_approved(session, limit=limit, gap_seconds=gap)
    msg = f"sent {sent} emails"
    if errors:
        msg += "; " + "; ".join(errors[:3])
    if sent or errors:
        log(msg)
    return msg


def run_replies(session) -> str:
    if not emailer.gmail_ready():
        return "Gmail not configured"
    msg = replies.poll(session)
    if msg and not msg.startswith(("nothing", "0 new")):
        log("replies: " + msg)
    return msg


def cycle() -> None:
    # Skip this tick entirely if the user is running something from the
    # dashboard - it will come round again in CYCLE_MINUTES.
    if not PIPELINE_LOCK.acquire(blocking=False):
        log("cycle skipped - a task is already running")
        return
    try:
        _cycle_inner()
    finally:
        PIPELINE_LOCK.release()


def _cycle_inner() -> None:
    prof = load_profile()
    session = SessionLocal()
    try:
        fetch_hours = float(os.getenv("FETCH_EVERY_HOURS", "12"))
        due = (STATE["last_fetch"] is None or
               (datetime.now() - STATE["last_fetch"]).total_seconds()
               > fetch_hours * 3600)
        if due:
            run_fetch(session, prof)
        # Fill in bare title+link rows before scoring, so the LLM sees the
        # real posting and contacts can be found afterwards.
        run_enrich(session)
        run_score(session, prof)
        run_cleanup(session, prof)
        run_contacts(session)
        if os.getenv("AUTO_DRAFT", "true").lower() == "true":
            run_draft(session, prof)
        run_apply(session, prof)
        run_autosend(session)
        if emailer.in_send_window():
            run_send(session, limit=int(os.getenv("SEND_BATCH", "8")), gap=75)
        run_replies(session)
        run_followups(session, prof)
    except Exception:
        log("cycle error: " + traceback.format_exc(limit=2).replace("\n", " | "))
    finally:
        session.close()
        STATE["last_cycle"] = datetime.now()


def start() -> None:
    """Run the pipeline in a background thread.

    Disabled when SCHEDULER_ENABLED=false - on hosted free tiers the web
    service sleeps, so the schedule is driven externally (GitHub Actions)
    and this process only serves the review UI.
    """
    global _started
    if os.getenv("SCHEDULER_ENABLED", "true").lower() == "false":
        log("in-process scheduler disabled (driven externally)")
        return
    if _started:
        return
    _started = True

    def loop():
        time.sleep(15)  # let the server come up first
        while True:
            cycle()
            time.sleep(float(os.getenv("CYCLE_MINUTES", "60")) * 60)

    threading.Thread(target=loop, daemon=True, name="portal-scheduler").start()
