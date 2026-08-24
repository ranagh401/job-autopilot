"""FastAPI backend: JSON API + serves the built React frontend."""
from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import FastAPI, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import selectinload
from starlette.middleware.sessions import SessionMiddleware

from datetime import datetime

from . import apply, contacts, emailer, matching, scheduler, tailor
from .db import (DATA_DIR, JOB_STATUSES, Application, Contact, Job, LlmUsage,
                 Outreach, ResumeVersion, SessionLocal, init_db)
from .llm import llm_ready
from .profile import load_profile
from .sources import job_is_domestic

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "frontend" / "dist"

app = FastAPI(title="Job Portal")


# Auth guard for the API (registered first; SessionMiddleware is added after
# so it wraps this and request.session is available here).
@app.middleware("http")
async def auth_guard(request: Request, call_next):
    path = request.url.path
    if (path.startswith("/api") and path != "/api/login"
            and not request.session.get("auth")):
        return JSONResponse({"detail": "not authenticated"}, status_code=401)
    return await call_next(request)


app.add_middleware(
    SessionMiddleware,
    secret_key="portal-" + os.getenv("DASHBOARD_PASSWORD", "changeme"))


@app.on_event("startup")
def _startup():
    init_db()
    scheduler.start()


# ---------- auth ----------

class LoginBody(BaseModel):
    password: str


@app.post("/api/login")
def login(request: Request, body: LoginBody):
    if body.password == os.getenv("DASHBOARD_PASSWORD", "changeme"):
        request.session["auth"] = True
        return {"ok": True}
    return JSONResponse({"detail": "wrong password"}, status_code=401)


@app.post("/api/logout")
def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@app.get("/api/me")
def me(request: Request):
    return {"auth": bool(request.session.get("auth"))}


# Outside /api so the auth guard lets it through — the host's health check
# must get a 200 without a session or the deploy never goes live.
@app.get("/healthz")
def healthz():
    return {"ok": True}


# ---------- serializers ----------

def job_row(j: Job) -> dict:
    return {
        "id": j.id, "title": j.title, "company": j.company,
        "location": j.location, "remote": j.remote, "source": j.source,
        "status": j.status, "match_score": j.match_score,
        "sponsorship_likely": j.sponsorship_likely,
        "contact_email": j.contact_email,
        "contacts_count": len(j.contacts),
        "salary": j.salary, "url": j.url,
        "domestic": job_is_domestic(j),
        "country": j.country,
        "posted_at": j.posted_at,
        "posted_dt": j.posted_dt.isoformat() if j.posted_dt else None,
        "experience_required": j.experience_required,
        "exp_min_years": j.exp_min_years,
        "found_at": j.found_at.isoformat() if j.found_at else None,
    }


def outreach_row(o: Outreach) -> dict:
    return {
        "id": o.id, "job_id": o.job_id, "to_email": o.to_email,
        "subject": o.subject, "body": o.body, "status": o.status,
        "error": o.error, "reply_kind": o.reply_kind,
        "followup_n": o.followup_n,
        "job_title": o.job.title if o.job else "",
        "company": o.job.company if o.job else "",
        "resume_filename": Path(o.resume_path).name if o.resume_path else "",
        "created_at": o.created_at.isoformat() if o.created_at else None,
        "sent_at": o.sent_at.isoformat() if o.sent_at else None,
        "reply_received_at": (o.reply_received_at.isoformat()
                              if o.reply_received_at else None),
        "reply_snippet": o.reply_snippet,
    }


# ---------- stats ----------

# Azure pay-as-you-go rates, USD per million tokens. Override in .env if
# the deployment is priced differently - output costs roughly 8x input,
# so the split matters.
LLM_IN_RATE = float(os.getenv("LLM_USD_PER_M_INPUT", "1.38"))
LLM_OUT_RATE = float(os.getenv("LLM_USD_PER_M_OUTPUT", "11.00"))


def llm_spend(s) -> dict:
    """Model spend, aggregated in SQL rather than row by row."""
    rows = (s.query(LlmUsage.kind,
                    func.sum(LlmUsage.prompt_tokens),
                    func.sum(LlmUsage.completion_tokens),
                    func.count(LlmUsage.id))
            .group_by(LlmUsage.kind).all())

    def usd(tin, tout):
        return (tin or 0) / 1e6 * LLM_IN_RATE + (tout or 0) / 1e6 * LLM_OUT_RATE

    by_kind = [{
        "kind": k or "untagged", "calls": n,
        "in": int(ti or 0), "out": int(to or 0),
        "usd": round(usd(ti, to), 4),
    } for k, ti, to, n in rows]
    by_kind.sort(key=lambda r: -r["usd"])
    tin = sum(r["in"] for r in by_kind)
    tout = sum(r["out"] for r in by_kind)
    today = (s.query(func.sum(LlmUsage.prompt_tokens),
                     func.sum(LlmUsage.completion_tokens))
             .filter(LlmUsage.created_at >= datetime.now().replace(
                 hour=0, minute=0, second=0, microsecond=0)).first())
    return {
        "calls": sum(r["calls"] for r in by_kind),
        "tokens_in": tin, "tokens_out": tout,
        # 4 dp: a single call costs fractions of a cent, and rounding to 2
        # would show a fresh database as having spent nothing.
        "usd": round(usd(tin, tout), 4),
        "usd_today": round(usd(today[0], today[1]), 4) if today else 0.0,
        "by_kind": by_kind,
        "rates": {"input": LLM_IN_RATE, "output": LLM_OUT_RATE},
    }

@app.get("/api/stats")
def stats():
    s = SessionLocal()
    try:
        prof = load_profile()
        counts = dict(s.query(Job.status, func.count(Job.id))
                      .group_by(Job.status).all())
        recent = (s.query(Outreach)
                  .filter(Outreach.reply_received_at.isnot(None))
                  .order_by(Outreach.reply_received_at.desc()).limit(5).all())
        return {
            "counts": counts,
            "statuses": JOB_STATUSES,
            "sent_today": emailer.count_sent_today(s),
            "cap": int(os.getenv("DAILY_EMAIL_CAP", "50")),
            "queue_n": s.query(Outreach).filter(
                Outreach.status.in_(["draft", "approved"])).count(),
            "config": {
                "AI model (Azure GPT-5.1)": llm_ready(),
                "Gmail sending + replies": emailer.gmail_ready(),
                "Adzuna API key": bool(os.getenv("ADZUNA_APP_ID")),
                "JSearch (RapidAPI) key": bool(os.getenv("RAPIDAPI_KEY")),
                "Hunter.io key": bool(os.getenv("HUNTER_API_KEY")),
                "Base resume uploaded": bool(prof.get("base_resume")),
                "LinkedIn URL in profile.yaml":
                    bool((prof.get("links") or {}).get("linkedin")),
                "Phone number in profile.yaml": bool(prof.get("phone")),
            },
            "hunter": contacts.hunter_quota(),
            "autosend": {
                "on": os.getenv("AUTO_SEND", "false").lower() == "true",
                "min_score": float(os.getenv("AUTO_SEND_MIN_SCORE", "70")),
                "window": os.getenv("SEND_WINDOW", "9-19"),
                "held": s.query(Outreach).filter(
                    Outreach.status == "draft").count(),
            },
            "sched": {
                "last_cycle": (scheduler.STATE["last_cycle"].strftime("%d %b %H:%M")
                               if scheduler.STATE["last_cycle"] else None),
                "last_fetch": (scheduler.STATE["last_fetch"].strftime("%d %b %H:%M")
                               if scheduler.STATE["last_fetch"] else None),
                "log": scheduler.STATE["log"][:20],
            },
            "recent_replies": [{
                "id": o.id, "job_id": o.job_id, "to_email": o.to_email,
                "company": o.job.company if o.job else "",
                "when": (o.reply_received_at.strftime("%d %b %H:%M")
                         if o.reply_received_at else ""),
                "snippet": o.reply_snippet[:180],
            } for o in recent],
            "llm": llm_spend(s),
        }
    finally:
        s.close()


# ---------- jobs ----------

@app.get("/api/jobs")
def jobs_list(status: str = "", q: str = "", minscore: str = "",
              scope: str = "", country: str = "", limit: int = 300):
    s = SessionLocal()
    try:
        # job_row() reads len(j.contacts). Without this the contacts of
        # every row are lazy-loaded one query at a time - 300 round trips
        # to a database in another region for a single page load.
        query = s.query(Job).options(selectinload(Job.contacts))
        if status:
            query = query.filter(Job.status == status)
        else:
            # Default view is the live pipeline - rejected jobs are only
            # shown when explicitly asked for.
            query = query.filter(Job.status.notin_(["skipped", "closed"]))
        if q:
            like = f"%{q}%"
            query = query.filter(Job.title.ilike(like)
                                 | Job.company.ilike(like)
                                 | Job.location.ilike(like))
        if minscore:
            try:
                query = query.filter(Job.match_score >= float(minscore))
            except ValueError:
                pass
        jobs = (query.order_by(Job.match_score.desc().nullslast(),
                               Job.found_at.desc())
                .limit(min(limit, 1000)).all())
        if scope == "domestic":
            jobs = [j for j in jobs if job_is_domestic(j)]
        elif scope == "abroad":
            # Abroad is only useful if they'd sponsor or hire remotely.
            jobs = [j for j in jobs
                    if not job_is_domestic(j)
                    and (j.sponsorship_likely is not False or j.remote)]
        # Countries present in this result set, for the filter dropdown -
        # computed before the country filter narrows things down.
        countries = sorted({j.country for j in jobs if j.country})
        if country:
            jobs = [j for j in jobs
                    if (j.country or "").lower() == country.lower()]
        return {"jobs": [job_row(j) for j in jobs], "countries": countries}
    finally:
        s.close()


KANBAN_COLUMNS = [
    ("shortlisted", "Shortlisted"),
    ("tailored", "Resume ready"),
    ("sent", "Applied / emailed"),
    ("replied", "In conversation"),
    ("interview", "Interview"),
    ("closed", "Closed"),
]


@app.get("/api/board")
def board():
    """Kanban view of the active pipeline."""
    s = SessionLocal()
    try:
        # One pass for every column rather than a query per column: each
        # card reads contacts, outreach and resumes, so a per-column loop
        # multiplied the round trips by five for no benefit.
        keys = [k for k, _ in KANBAN_COLUMNS]
        everything = (s.query(Job)
                      .options(selectinload(Job.contacts),
                               selectinload(Job.outreach),
                               selectinload(Job.resumes))
                      .filter(Job.status.in_(keys))
                      .order_by(Job.match_score.desc().nullslast(),
                                Job.found_at.desc()).all())
        grouped: dict[str, list[Job]] = {k: [] for k in keys}
        for j in everything:
            bucket = grouped.get(j.status)
            if bucket is not None and len(bucket) < 60:
                bucket.append(j)

        cols = []
        for key, label in KANBAN_COLUMNS:
            cards = []
            for j in grouped[key]:
                latest = max((o.sent_at for o in j.outreach if o.sent_at),
                             default=None)
                kind = next((o.reply_kind for o in j.outreach
                             if o.reply_kind), "")
                cards.append({
                    **job_row(j),
                    "last_sent": latest.isoformat() if latest else None,
                    "reply_kind": kind,
                    "has_resume": bool(j.resumes),
                })
            cols.append({"key": key, "label": label, "cards": cards,
                         "count": len(cards)})
        return {"columns": cols}
    finally:
        s.close()


# Contact sources that came from searching/scraping the open web rather
# than from a paid database or the posting itself.
WEB_SOURCES = ["hiring-post", "websearch", "websearch-person", "pattern",
               "escalated", "escalated-person", "search-person", "page",
               "page-person", "guessed"]


@app.get("/api/leads")
def leads():
    """Jobs whose contact was found by searching or scraping the web."""
    s = SessionLocal()
    try:
        rows = (s.query(Contact)
                .filter(Contact.source.in_(WEB_SOURCES))
                .order_by(Contact.created_at.desc()).limit(300).all())
        out = []
        for c in rows:
            j = c.job
            if not j:
                continue
            out.append({
                "contact_id": c.id, "job_id": j.id,
                "email": c.email, "name": c.name, "role": c.role,
                "contact_source": c.source, "kind": c.kind,
                "is_person": c.is_person, "verified": c.verified,
                "verify_note": c.verify_note, "linkedin": c.linkedin,
                "found_at": c.created_at.isoformat(),
                "title": j.title, "company": j.company,
                "location": j.location, "country": j.country,
                "match_score": j.match_score, "status": j.status,
                "job_source": j.source, "url": j.url,
                "is_primary": j.contact_email == c.email,
                "emailed": any(o.status == "sent" and o.to_email == c.email
                               for o in j.outreach),
            })
        by_source = {}
        for r in out:
            by_source[r["contact_source"]] = \
                by_source.get(r["contact_source"], 0) + 1
        return {"leads": out, "by_source": by_source,
                "people": sum(1 for r in out if r["is_person"]),
                "emailed": sum(1 for r in out if r["emailed"])}
    finally:
        s.close()


@app.get("/api/jobs/{job_id}")
def job_detail(job_id: int):
    s = SessionLocal()
    try:
        j = s.get(Job, job_id)
        if not j:
            return JSONResponse({"detail": "not found"}, status_code=404)
        row = job_row(j)
        row["description"] = j.description
        row["match_notes"] = j.match_notes
        row["contacts"] = [{
            "id": c.id, "email": c.email, "name": c.name,
            "role": c.role, "source": c.source, "is_person": c.is_person,
            "linkedin": c.linkedin, "confidence": c.confidence,
            "kind": c.kind, "verified": c.verified,
            "verify_note": c.verify_note,
        } for c in sorted(j.contacts,
                          key=lambda c: (
                              contacts.KIND_RANK.get(c.kind or "unknown", 4),
                              0 if c.is_person else 1,
                              -(c.confidence or 0)))]
        row["resumes"] = [{
            "id": r.id, "filename": Path(r.path).name,
            "created_at": r.created_at.isoformat(),
            "ats_score": r.ats_score, "ats_keyword": r.ats_keyword,
            "ats_skills": r.ats_skills, "ats_sections": r.ats_sections,
            "missing_keywords": json.loads(r.missing_keywords or "[]"),
        } for r in j.resumes]
        row["outreach"] = [outreach_row(o) for o in j.outreach]
        row["applications"] = [{
            "id": a.id, "ats": a.ats, "status": a.status,
            "detail": a.detail, "url": a.url,
            "cover_letter": a.cover_letter,
            "answers": json.loads(a.answers or "{}"),
            "submitted_at": (a.submitted_at.isoformat()
                             if a.submitted_at else None),
            "created_at": a.created_at.isoformat(),
        } for a in j.applications]
        return row
    finally:
        s.close()


class JobActionBody(BaseModel):
    action: str
    to_email: str = ""
    status: str = ""


@app.post("/api/jobs/{job_id}/action")
def job_action(job_id: int, body: JobActionBody):
    s = SessionLocal()
    prof = load_profile()
    try:
        j = s.get(Job, job_id)
        if not j:
            return JSONResponse({"detail": "not found"}, status_code=404)
        try:
            if body.action == "shortlist":
                j.status = "shortlisted"
                s.commit()
                msg = "Shortlisted"
            elif body.action == "skip":
                j.status = "skipped"
                s.commit()
                msg = "Skipped"
            elif body.action == "score":
                matching.score_job(s, j, prof)
                msg = f"Scored {j.match_score:.0f}/100"
            elif body.action == "contacts":
                added = contacts.discover(s, j)
                msg = (f"Found {len(added)} new contact(s)" if added
                       else "No new contacts found (posting text, page, "
                            "web search and Hunter all checked)")
            elif body.action == "tailor":
                res = tailor.tailor_resume(s, j, prof)
                a = res["ats"]
                msg = (f"{res['format']} {res['doc_name']} created - "
                       f"ATS fit {a['overall']:.0f}/100 "
                       f"({a['matched_count']}/{a['term_count']} keywords)")
            elif body.action == "draft":
                emailer.draft_outreach(s, j, prof, to_email=body.to_email)
                msg = "Draft created - review it in the Queue"
            elif body.action == "apply":
                resume = (sorted(j.resumes, key=lambda r: r.created_at)[-1].path
                          if j.resumes else prof.get("base_resume", ""))
                res = apply.apply_to_job(j, prof, resume)
                s.add(Application(
                    job_id=j.id, ats=res["ats"], url=j.url,
                    status=("submitted" if res["ok"] else
                            ("manual_needed"
                             if res["ats"] not in apply.AUTOMATABLE
                             else "failed")),
                    detail=res["detail"][:2000],
                    cover_letter=(res.get("answers") or {}).get(
                        "cover_letter", ""),
                    answers=json.dumps(res.get("answers") or {}),
                    resume_path=resume,
                    submitted_at=datetime.now() if res["ok"] else None))
                if res["ok"]:
                    j.status = "sent"
                s.commit()
                msg = res["detail"]
            elif body.action == "set_contact":
                j.contact_email = body.to_email.strip()
                s.commit()
                msg = f"Primary contact set to {j.contact_email}"
            elif body.action == "set_status":
                if body.status not in JOB_STATUSES:
                    return JSONResponse({"detail": "unknown status"},
                                        status_code=400)
                j.status = body.status
                s.commit()
                msg = f"Moved to {body.status}"
            else:
                return JSONResponse({"detail": "unknown action"},
                                    status_code=400)
        except Exception as e:
            return JSONResponse({"detail": str(e)}, status_code=500)
        return {"ok": True, "message": msg}
    finally:
        s.close()


# ---------- queue & outreach ----------

@app.get("/api/queue")
def queue():
    s = SessionLocal()
    try:
        # Both outreach_row() and autosend_blockers() read o.job, and the
        # blocker check also walks job.contacts. Left lazy, a hundred
        # drafts became a couple of hundred round trips.
        drafts = (s.query(Outreach)
                  .options(selectinload(Outreach.job)
                           .selectinload(Job.contacts))
                  .filter(Outreach.status.in_(["draft", "approved", "failed"]))
                  .order_by(Outreach.created_at.desc()).limit(100).all())
        min_score = float(os.getenv("AUTO_SEND_MIN_SCORE", "65"))
        prof = load_profile()   # once, not once per draft
        rows = []
        for o in drafts:
            row = outreach_row(o)
            # Why auto-send has not picked this up yet.
            row["blockers"] = emailer.autosend_blockers(o, min_score, prof)
            rows.append(row)
        held = sum(1 for r in rows if r["blockers"])
        return {"drafts": rows,
                "ready": len(rows) - held, "held": held,
                "auto_send": os.getenv("AUTO_SEND", "false").lower() == "true"}
    finally:
        s.close()


class QueueBody(BaseModel):
    action: str
    to_email: str = ""
    subject: str = ""
    body: str = ""


@app.post("/api/queue/{oid}")
def queue_action(oid: int, payload: QueueBody):
    s = SessionLocal()
    try:
        o = s.get(Outreach, oid)
        if not o:
            return JSONResponse({"detail": "not found"}, status_code=404)
        try:
            if payload.action in ("save", "approve", "send"):
                o.to_email = payload.to_email.strip()
                o.subject = payload.subject
                o.body = payload.body
            if payload.action == "save":
                s.commit()
                msg = "Saved"
            elif payload.action == "approve":
                o.status = "approved"
                s.commit()
                msg = "Approved - goes out with the next send run"
            elif payload.action == "unapprove":
                o.status = "draft"
                s.commit()
                msg = "Moved back to draft"
            elif payload.action == "send":
                s.commit()
                emailer.send_one(s, o)
                msg = f"Sent to {o.to_email}"
            elif payload.action == "delete":
                s.delete(o)
                s.commit()
                msg = "Deleted"
            else:
                return JSONResponse({"detail": "unknown action"},
                                    status_code=400)
        except Exception as e:
            return JSONResponse({"detail": str(e)}, status_code=500)
        return {"ok": True, "message": msg}
    finally:
        s.close()


def application_row(a: Application) -> dict:
    j = a.job
    return {
        "id": a.id, "job_id": a.job_id, "ats": a.ats, "url": a.url,
        "status": a.status, "detail": a.detail,
        "cover_letter": a.cover_letter,
        "answers": json.loads(a.answers or "{}"),
        "resume_filename": (Path(a.resume_path).name
                            if a.resume_path else ""),
        # Lever posts directly; everything else is driven by a browser.
        "auto": (apply.can_auto_submit(a.url)
                 or os.getenv("BROWSER_APPLY", "true").lower() == "true"),
        "how": ("direct" if apply.can_auto_submit(a.url) else "browser"),
        "company": j.company if j else "",
        "title": j.title if j else "",
        "location": j.location if j else "",
        "country": j.country if j else "",
        "match_score": j.match_score if j else None,
        "created_at": a.created_at.isoformat(),
        "submitted_at": (a.submitted_at.isoformat()
                         if a.submitted_at else None),
    }


@app.get("/api/applications")
def applications_list(status: str = ""):
    """Applications, pending-approval first - this is the review screen."""
    s = SessionLocal()
    try:
        # Both the sort key and application_row() read a.job; eager-load it
        # so 200 applications cost one extra query, not 200.
        q = s.query(Application).options(selectinload(Application.job))
        if status:
            q = q.filter(Application.status == status)
        rows = q.order_by(Application.created_at.desc()).limit(200).all()
        order = {"pending_approval": 0, "manual_needed": 1, "failed": 2,
                 "submitted": 3, "skipped": 4}
        rows.sort(key=lambda a: (order.get(a.status, 9),
                                 -(a.job.match_score or 0) if a.job else 0))
        return {"applications": [application_row(a) for a in rows]}
    finally:
        s.close()


class ApplicationActionBody(BaseModel):
    action: str  # approve / skip / retry


@app.post("/api/applications/{aid}")
def application_action(aid: int, body: ApplicationActionBody):
    s = SessionLocal()
    prof = load_profile()
    try:
        a = s.get(Application, aid)
        if not a:
            return JSONResponse({"detail": "not found"}, status_code=404)
        try:
            if body.action == "skip":
                a.status = "skipped"
                s.commit()
                msg = "Skipped"
            elif body.action in ("approve", "retry"):
                res = scheduler.submit_application(s, a, prof)
                msg = res["detail"]
            else:
                return JSONResponse({"detail": "unknown action"},
                                    status_code=400)
        except Exception as e:
            return JSONResponse({"detail": str(e)}, status_code=500)
        return {"ok": True, "message": msg, "status": a.status}
    finally:
        s.close()


@app.post("/api/applications/approve_all")
def applications_approve_all():
    """Approve every pending application that can be submitted for you."""
    s = SessionLocal()
    prof = load_profile()
    try:
        pending = (s.query(Application)
                   .filter(Application.status == "pending_approval").all())
        submitted = manual = 0
        errors = []
        for a in pending:
            if not apply.can_auto_submit(a.url):
                continue
            try:
                res = scheduler.submit_application(s, a, prof)
                if res["ok"]:
                    submitted += 1
                else:
                    errors.append(res["detail"][:120])
            except Exception as e:
                errors.append(str(e)[:120])
        manual = sum(1 for a in pending if not apply.can_auto_submit(a.url))
        msg = f"submitted {submitted}"
        if manual:
            msg += (f"; {manual} need the form filled by hand - open each "
                    f"and approve once done")
        if errors:
            msg += f"; {len(errors)} failed ({errors[0]})"
        return {"ok": True, "message": msg}
    finally:
        s.close()


@app.get("/api/outreach")
def outreach_list():
    s = SessionLocal()
    try:
        rows = (s.query(Outreach).filter(Outreach.status == "sent")
                .order_by(Outreach.sent_at.desc()).limit(300).all())
        return {"rows": [outreach_row(o) for o in rows]}
    finally:
        s.close()


# ---------- files ----------

@app.get("/api/resumes/{rid}/download")
def resume_download(rid: int):
    s = SessionLocal()
    try:
        r = s.get(ResumeVersion, rid)
        if not r or not Path(r.path).exists():
            return JSONResponse({"detail": "not found"}, status_code=404)
        return FileResponse(r.path, filename=Path(r.path).name)
    finally:
        s.close()


@app.post("/api/resume/upload")
async def upload_resume(file: UploadFile):
    ext = Path(file.filename or "resume.pdf").suffix.lower() or ".pdf"
    if ext not in (".pdf", ".docx", ".txt"):
        return JSONResponse(
            {"detail": "please upload a .pdf, .docx or .txt file"},
            status_code=400)
    for old in DATA_DIR.glob("base_resume.*"):
        old.unlink()
    dest = DATA_DIR / f"base_resume{ext}"
    dest.write_bytes(await file.read())
    return {"ok": True, "message": f"Base resume saved: {dest.name}"}


# ---------- manual runs ----------

@app.post("/api/run/{task}")
def run_task(task: str):
    # Wait for the background cycle to finish rather than write at the
    # same time - SQLite permits a single writer.
    if not scheduler.PIPELINE_LOCK.acquire(timeout=600):
        return JSONResponse(
            {"detail": "the scheduler is busy, try again shortly"},
            status_code=409)
    s = SessionLocal()
    prof = load_profile()
    try:
        try:
            if task == "fetch":
                msg = scheduler.run_fetch(s, prof)
            elif task == "score":
                msg = scheduler.run_score(s, prof)
            elif task == "contacts":
                msg = scheduler.run_contacts(s)
            elif task == "draft":
                msg = scheduler.run_draft(s, prof)
            elif task == "send":
                msg = scheduler.run_send(s, limit=10, gap=0)
            elif task == "replies":
                msg = scheduler.run_replies(s)
            elif task == "followups":
                msg = scheduler.run_followups(s, prof)
            elif task == "cleanup":
                msg = scheduler.run_cleanup(s, prof)
            elif task == "autosend":
                msg = scheduler.run_autosend(s)
            elif task == "tailor":
                msg = scheduler.run_tailor(s, prof)
            elif task == "enrich":
                msg = scheduler.run_enrich(s)
            elif task == "apply":
                msg = scheduler.run_apply(s, prof)
            elif task == "wellfound_login":
                # Opens a real browser window so the user signs in by hand;
                # only useful when the server runs on their own machine.
                from .wellfound_apply import login
                msg = login()
            elif task == "wellfound_apply":
                from .wellfound_apply import apply_batch
                dry = os.getenv("WELLFOUND_DRY_RUN", "true").lower() != "false"
                msg = apply_batch(s, prof, limit=5, dry_run=dry)
            else:
                return JSONResponse({"detail": "unknown task"},
                                    status_code=400)
        except Exception as e:
            return JSONResponse({"detail": str(e)}, status_code=500)
        return {"ok": True, "message": msg}
    finally:
        s.close()
        scheduler.PIPELINE_LOCK.release()


# ---------- SPA ----------

if DIST.exists():
    app.mount("/", StaticFiles(directory=str(DIST), html=True), name="spa")
