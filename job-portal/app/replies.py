"""Polls Gmail (IMAP) for replies to sent outreach and records them."""
from __future__ import annotations

import email as email_lib
import imaplib
import os
from email.utils import parsedate_to_datetime

from .db import Outreach
from .llm import chat, llm_ready

CLASSIFY_SYSTEM = (
    "Classify a recruiter's reply to a job application email.\n"
    'Respond with JSON: {"kind": "<one of: interview, offer, rejection, '
    'info_request, auto_ack, other>", "summary": "<max 15 words>"}\n'
    "interview: they want to talk, schedule a call, or move forward.\n"
    "offer: an actual job offer.\n"
    "rejection: not moving forward.\n"
    "info_request: they ask for details (CTC, notice period, documents).\n"
    "auto_ack: automated acknowledgement or out-of-office."
)
# A reply of these kinds moves the job card to that column.
KIND_TO_STATUS = {
    "interview": "interview",
    "offer": "interview",
    "rejection": "closed",
}


def classify(text: str) -> dict:
    if not llm_ready() or not (text or "").strip():
        return {"kind": "", "summary": ""}
    try:
        out = chat(CLASSIFY_SYSTEM, (text or "")[:3000], json_mode=True,
                   kind="classify-reply")
    except Exception:
        return {"kind": "", "summary": ""}
    kind = str(out.get("kind") or "").strip().lower()
    valid = {"interview", "offer", "rejection", "info_request",
             "auto_ack", "other"}
    return {"kind": kind if kind in valid else "other",
            "summary": str(out.get("summary") or "")[:200]}


def _plain_text(msg) -> str:
    for part in msg.walk():
        if part.get_content_type() == "text/plain":
            try:
                return part.get_payload(decode=True).decode(
                    part.get_content_charset() or "utf-8", errors="ignore")
            except Exception:
                pass
    return ""


def poll(session) -> str:
    user = os.getenv("GMAIL_ADDRESS")
    pw = os.getenv("GMAIL_APP_PASSWORD")
    if not (user and pw):
        return "gmail not configured"
    pending = (session.query(Outreach)
               .filter(Outreach.status == "sent",
                       Outreach.reply_received_at.is_(None))
               .order_by(Outreach.sent_at.desc())
               .limit(60).all())
    if not pending:
        return "nothing pending"
    M = imaplib.IMAP4_SSL("imap.gmail.com")
    found = 0
    try:
        M.login(user, pw)
        M.select("INBOX")
        for o in pending:
            if not o.to_email or not o.sent_at:
                continue
            since = o.sent_at.strftime("%d-%b-%Y")
            typ, data = M.search(
                None, f'(FROM "{o.to_email}" SINCE {since})')
            if typ != "OK" or not data or not data[0]:
                continue
            for num in data[0].split()[-3:]:
                typ, msgdata = M.fetch(num, "(RFC822)")
                if typ != "OK":
                    continue
                msg = email_lib.message_from_bytes(msgdata[0][1])
                try:
                    dt = parsedate_to_datetime(msg["Date"])
                    dt = dt.astimezone().replace(tzinfo=None)
                except Exception:
                    continue
                if dt <= o.sent_at:
                    continue
                body = _plain_text(msg)
                o.reply_received_at = dt
                o.reply_snippet = body[:500]
                cls = classify(body)
                o.reply_kind = cls["kind"]
                if o.job:
                    # An interview/offer/rejection wins; anything else just
                    # marks the thread as replied.
                    o.job.status = KIND_TO_STATUS.get(cls["kind"], "replied")
                found += 1
                break
        session.commit()
    finally:
        try:
            M.logout()
        except Exception:
            pass
    return f"{found} new replies"
