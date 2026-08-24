"""Drafts cold emails (LLM), manages the approval queue, sends via Gmail
SMTP with a daily cap and a send window."""
from __future__ import annotations

import mimetypes
import os
import re
import smtplib
import time
from datetime import datetime
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path

from .db import Outreach, ResumeVersion
from .llm import chat, llm_ready
from .profile import profile_summary

SYSTEM = (
    "You write short, personalised cold emails for a job seeker applying to "
    "a specific posting. 120-170 words, plain text (no markdown). Structure: "
    "greeting (use the contact's name if given, else 'Hi,'), one-line hook "
    "naming the exact role and company, one short paragraph mapping the "
    "candidate's 2-3 most relevant achievements to the job requirements, "
    "one closing line saying the resume is attached and asking for a "
    "conversation.\n"
    "The email is FROM the candidate and must read as if they wrote it "
    "themselves: first person throughout, warm and human. Never mention or "
    "hint that it was written, generated or sent by an AI, assistant, bot, "
    "tool or automation, and never add any note, disclaimer or footer to "
    "that effect.\n"
    "Confident but not pushy; no cliches like 'I hope this finds you well'; "
    "no invented facts.\n"
    "END the body with a plain signature block on its own lines, using "
    "EXACTLY the contact details given in the CANDIDATE section - the real "
    "name, phone number and profile URLs, copied verbatim. Never invent, "
    "abbreviate or placeholder them.\n"
    'Respond with JSON: {"subject": "...", "body": "..."}'
)

# Real disclaimers that would reveal the mail was machine-written.
# Deliberately narrow: "as an AI Engineer" is the candidate's actual job
# title and must never match.
AI_MENTION = re.compile(
    r"\bas an ai\s*(,|language model|assistant|model\b)|"
    r"\bi am an ai\b|\bai (assistant|language model)\b|"
    r"\blarge language model\b|\bchatgpt\b|\bgpt-?[45]\b|"
    r"\b(written|generated|composed|drafted|sent) (by|with|using) "
    r"(an? )?(ai|bot|llm|assistant|automation|chatgpt|gpt)\b|"
    r"\bautomated (email|message)\b|"
    r"\bthis (email|message) was (auto|generated|created by)",
    re.I)


def gmail_ready() -> bool:
    return bool(os.getenv("GMAIL_ADDRESS") and os.getenv("GMAIL_APP_PASSWORD"))


def signature(profile: dict) -> str:
    """The candidate's real contact block, straight from profile.yaml."""
    links = profile.get("links") or {}
    lines = [profile.get("name") or ""]
    if profile.get("phone"):
        lines.append(str(profile["phone"]))
    if profile.get("email"):
        lines.append(str(profile["email"]))
    for label, key in (("LinkedIn", "linkedin"), ("GitHub", "github"),
                       ("Portfolio", "portfolio")):
        if links.get(key):
            lines.append(f"{label}: {links[key]}")
    return "\n".join(x for x in lines if x)


def _finalise_signature(body: str, profile: dict) -> str:
    """Guarantee the real phone/LinkedIn are present, and strip anything
    that reveals the email was machine-written."""
    # Drop whole lines that are disclaimers or fill-in-the-blanks - an
    # inline substitution would leave a mangled half-sentence.
    body = "\n".join(l for l in body.splitlines()
                     if not PLACEHOLDER.search(l)
                     and not AI_MENTION.search(l)).strip()
    sig = signature(profile)
    if not sig:
        return body
    phone = str(profile.get("phone") or "")
    linkedin = (profile.get("links") or {}).get("linkedin") or ""
    have_phone = not phone or phone in body
    have_linkedin = not linkedin or linkedin in body
    if have_phone and have_linkedin:
        return body
    # Drop whatever partial sign-off the model wrote, then append the real
    # block so the details are always correct.
    name = (profile.get("name") or "").strip()
    if name:
        lines = body.rstrip().split("\n")
        while lines and (not lines[-1].strip()
                         or name.lower() in lines[-1].lower()
                         or len(lines[-1].strip()) < 40):
            if lines[-1].strip() and name.lower() not in lines[-1].lower() \
                    and not lines[-1].strip().lower().startswith(
                        ("best", "regards", "thanks", "sincerely", "warm")):
                break
            lines.pop()
        body = "\n".join(lines).rstrip()
    return f"{body}\n\nBest regards,\n{sig}"


def draft_outreach(session, job, profile, to_email: str = "") -> Outreach:
    rv = (session.query(ResumeVersion)
          .filter_by(job_id=job.id)
          .order_by(ResumeVersion.created_at.desc()).first())
    resume_path = rv.path if rv else (profile.get("base_resume") or "")
    contact = next((c for c in job.contacts
                    if c.email == (to_email or job.contact_email)), None)
    user = (
        "CANDIDATE:\n" + profile_summary(profile) + "\n\n"
        "EXACT SIGNATURE BLOCK to end the email with (copy verbatim):\n"
        + signature(profile) + "\n\n"
        f"CONTACT NAME: {contact.name if contact and contact.name else 'unknown'}\n\n"
        "JOB POSTING:\n"
        f"Title: {job.title}\nCompany: {job.company}\n"
        f"Location: {job.location}\n"
        f"Description:\n{(job.description or '')[:5000]}"
    )
    out = chat(SYSTEM, user, json_mode=True, kind="draft-email")
    body = _finalise_signature(str(out.get("body") or ""), profile)
    o = Outreach(
        job_id=job.id,
        to_email=(to_email or job.contact_email or "").strip(),
        subject=str(out.get("subject") or f"Application: {job.title}")[:490],
        body=body,
        resume_path=resume_path,
        status="draft",
    )
    session.add(o)
    session.commit()
    return o


FOLLOWUP_SYSTEM = (
    "Write a SHORT follow-up email bumping a previous job-application email "
    "that got no reply. 60-90 words, plain text. Reference the role and "
    "company, add one new angle or piece of value (not a repeat of the "
    "first email), and close with a low-pressure ask. Never guilt-trip or "
    "imply they were rude not to reply.\n"
    "It is FROM the candidate: first person, human. Never mention or hint "
    "that it was written or sent by an AI, assistant, bot or automation.\n"
    "End with the exact signature block given below, copied verbatim.\n"
    'Respond with JSON: {"subject": "...", "body": "..."}'
)
# Days after the previous email before each bump (Mautic day 0/3/7 pattern).
FOLLOWUP_DAYS = [3, 7]


def create_followups(session, profile, limit: int = 10) -> int:
    """Queue follow-up drafts for sent emails that never got a reply.

    A reply anywhere on the job stops the whole sequence.
    """
    if not llm_ready():
        return 0
    made = 0
    now = datetime.now()
    candidates = (session.query(Outreach)
                  .filter(Outreach.status == "sent",
                          Outreach.reply_received_at.is_(None),
                          Outreach.followup_n < len(FOLLOWUP_DAYS))
                  .order_by(Outreach.sent_at.asc()).limit(60).all())
    for o in candidates:
        if made >= limit or not o.sent_at:
            break
        job = o.job
        if not job or job.status in ("closed", "skipped", "interview"):
            continue
        # Any reply on this job at all cancels further follow-ups.
        if any(x.reply_received_at for x in job.outreach):
            continue
        due_days = FOLLOWUP_DAYS[o.followup_n]
        if (now - o.sent_at).days < due_days:
            continue
        # Don't queue a second follow-up while one is still pending.
        if any(x.parent_id == o.id and x.status in ("draft", "approved")
               for x in job.outreach):
            continue
        try:
            out = chat(FOLLOWUP_SYSTEM, (
                "CANDIDATE:\n" + profile_summary(profile) + "\n\n"
                "EXACT SIGNATURE BLOCK (copy verbatim):\n"
                + signature(profile) + "\n\n"
                f"ROLE: {job.title} at {job.company}\n"
                f"SENT {(now - o.sent_at).days} DAYS AGO, NO REPLY.\n"
                f"ORIGINAL SUBJECT: {o.subject}\n"
                f"ORIGINAL BODY:\n{o.body[:1500]}"), json_mode=True)
        except Exception:
            continue
        session.add(Outreach(
            job_id=job.id,
            to_email=o.to_email,
            subject=str(out.get("subject") or f"Re: {o.subject}")[:490],
            body=_finalise_signature(str(out.get("body") or ""), profile),
            resume_path="",  # the resume already went with the first email
            status="draft",
            followup_n=o.followup_n + 1,
            parent_id=o.id,
        ))
        o.followup_n += 1
        made += 1
    session.commit()
    return made


PLACEHOLDER = re.compile(r"\[(name|company|role|title|insert|your)\b|"
                         r"\bTODO\b|\bXXX\b|\{\{|lorem ipsum", re.I)


def autosend_blockers(o: Outreach, min_score: float,
                      prof: dict | None = None) -> list[str]:
    """Reasons this draft must NOT be sent unattended.

    Auto-send is only safe when we are confident about the recipient and
    the content - a wrong or bounced cold email costs real reputation, and
    it cannot be recalled.
    """
    problems = []
    job = o.job
    email = (o.to_email or "").strip().lower()
    if not email or "@" not in email:
        problems.append("no recipient")
    # Whatever contact details are configured must actually appear in the
    # body; details left blank in profile.yaml are simply not required.
    # Callers checking a whole queue pass `prof` in - load_profile() reads
    # and parses YAML off disk, so doing it per draft is pure waste.
    if prof is None:
        from .profile import load_profile
        prof = load_profile()
    phone = str(prof.get("phone") or "")
    linkedin = (prof.get("links") or {}).get("linkedin") or ""
    if linkedin and linkedin not in o.body:
        problems.append("LinkedIn URL not in the email body")
    if phone and phone not in o.body:
        problems.append("phone number not in the email body")
    if AI_MENTION.search(o.body):
        problems.append("body mentions being AI-written")
    if not o.body.strip() or len(o.body) < 120:
        problems.append("body too short")
    if PLACEHOLDER.search(o.body) or PLACEHOLDER.search(o.subject):
        problems.append("unfilled placeholder in the text")
    # Follow-ups deliberately carry no attachment; a first email must.
    if not o.resume_path and not (o.followup_n or 0):
        problems.append("no resume attached")
    if job:
        # Without a real posting we cannot confirm which company this is:
        # alert emails give only a title and a link, and short company
        # names collide with unrelated organisations. Never cold-email on
        # that basis.
        desc = (job.description or "").strip()
        if len(desc) < 200 or desc.startswith("(from a job-alert email"):
            problems.append("no job description - employer unconfirmed")
        contact = next((c for c in job.contacts if c.email == email), None)
        # Never auto-email an address we only guessed at - it may not
        # exist, and bounces hurt the sending domain.
        if contact and contact.source == "guessed":
            problems.append("recipient address was guessed, not verified")
        # Only a real, LLM-verified human at this company gets an
        # unattended cold email - with one exception: an address the
        # recruiter published in their own hiring post is an explicit
        # invitation to apply by email, so a shared inbox is fine there.
        invited = (contact is not None
                   and contact.source == "hiring-post"
                   and contact.kind in ("hr", "engineering", "role_inbox"))
        if contact is None:
            problems.append("recipient is not a known contact for this job")
        elif contact.verified is None:
            problems.append("recipient not verified yet")
        elif contact.kind == "wrong_company":
            problems.append("recipient works at a different company")
        elif not contact.is_person and not invited:
            problems.append(
                f"recipient is a {contact.kind or 'non-person'} address, "
                "not a real person")
        if job.match_score is not None and job.match_score < min_score:
            problems.append(f"match score {job.match_score:.0f} "
                            f"below {min_score:.0f}")
        if job.exp_min_years and job.exp_min_years > 3:
            problems.append("job wants more experience than you have")
    return problems


def auto_approve(session, limit: int = 25) -> tuple[int, list[str]]:
    """Promote clean drafts straight to approved so the sender picks them
    up. Returns (approved, skipped reasons)."""
    min_score = float(os.getenv("AUTO_SEND_MIN_SCORE", "70"))
    drafts = (session.query(Outreach).filter(Outreach.status == "draft")
              .order_by(Outreach.created_at.asc()).limit(limit).all())
    approved, held = 0, []
    for o in drafts:
        problems = autosend_blockers(o, min_score)
        if problems:
            held.append(f"#{o.id}: {problems[0]}")
            continue
        o.status = "approved"
        approved += 1
    session.commit()
    return approved, held


def count_sent_today(session) -> int:
    midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    return (session.query(Outreach)
            .filter(Outreach.status == "sent", Outreach.sent_at >= midnight)
            .count())


def in_send_window() -> bool:
    try:
        start, end = (int(x) for x in os.getenv("SEND_WINDOW", "9-19").split("-"))
    except ValueError:
        start, end = 9, 19
    return start <= datetime.now().hour < end


def send_one(session, o: Outreach) -> None:
    if not gmail_ready():
        raise RuntimeError("Gmail is not configured in .env")
    if not o.to_email or "@" not in o.to_email:
        raise RuntimeError("No recipient email on this draft")
    addr = os.getenv("GMAIL_ADDRESS")
    from .profile import load_profile
    prof = load_profile()

    msg = EmailMessage()
    msg["From"] = f"{prof.get('name') or addr} <{addr}>"
    msg["To"] = o.to_email
    msg["Subject"] = o.subject
    msgid = make_msgid()
    msg["Message-ID"] = msgid
    msg.set_content(o.body)

    if o.resume_path and Path(o.resume_path).exists():
        ctype = (mimetypes.guess_type(o.resume_path)[0]
                 or "application/octet-stream")
        maintype, subtype = ctype.split("/", 1)
        msg.add_attachment(Path(o.resume_path).read_bytes(),
                           maintype=maintype, subtype=subtype,
                           filename=Path(o.resume_path).name)
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=60) as smtp:
            smtp.login(addr, os.getenv("GMAIL_APP_PASSWORD"))
            smtp.send_message(msg)
    except Exception as e:
        o.status = "failed"
        o.error = str(e)[:800]
        session.commit()
        raise
    o.status = "sent"
    o.sent_at = datetime.now()
    o.message_id = msgid
    o.error = ""
    if o.job and o.job.status not in ("replied", "interview"):
        o.job.status = "sent"
    session.commit()


def send_approved(session, limit: int | None = None,
                  gap_seconds: int = 0) -> tuple[int, list[str]]:
    cap = int(os.getenv("DAILY_EMAIL_CAP", "50"))
    remaining = cap - count_sent_today(session)
    if remaining <= 0:
        return 0, [f"daily cap of {cap} reached"]
    batch = (session.query(Outreach)
             .filter(Outreach.status == "approved")
             .order_by(Outreach.created_at.asc())
             .limit(min(limit or remaining, remaining)).all())
    sent, errors = 0, []
    for i, o in enumerate(batch):
        try:
            send_one(session, o)
            sent += 1
        except Exception as e:
            errors.append(f"outreach #{o.id}: {e}")
        if gap_seconds and i < len(batch) - 1:
            time.sleep(gap_seconds)
    return sent, errors
