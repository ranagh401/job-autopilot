"""Parses LinkedIn / Naukri / Indeed job-alert emails from the user's own
Gmail inbox via IMAP. This is the ToS-safe way to get listings from those
sites: the user sets up daily alert emails, we read our own mailbox."""
from __future__ import annotations

import email as email_lib
import imaplib
import os
import re
from datetime import date, timedelta

from bs4 import BeautifulSoup

SENDER_DOMAINS = ["linkedin.com", "naukri.com", "indeed.com", "glassdoor.com"]


def _html_parts(msg) -> str:
    chunks = []
    for part in msg.walk():
        if part.get_content_type() == "text/html":
            try:
                chunks.append(part.get_payload(decode=True).decode(
                    part.get_content_charset() or "utf-8", errors="ignore"))
            except Exception:
                pass
    return "\n".join(chunks)


# LinkedIn alert link text runs together as
# "Job Title Company City, Region (Remote) Easy Apply ..." - pull it apart.
_NOISE = re.compile(
    r"\s*(easy apply|actively recruiting|be an early applicant|promoted|"
    r"new|viewed|\$[\d.,]+K?\s*[-–]\s*\$[\d.,]+K?\s*/?\s*\w*)\s*", re.I)
_LOC = re.compile(
    r"([A-Z][A-Za-z .'-]+,\s*[A-Za-z .'-]+?)\s*(\((?:Remote|Hybrid|On-?site)\))?"
    r"\s*$", re.I)


def _split_alert_text(text: str) -> dict:
    """Best-effort split of alert link text into title / company / location."""
    t = _NOISE.sub(" ", text).strip(" ·-–|")
    t = re.sub(r"\s{2,}", " ", t)
    out = {"title": t[:290], "company": "", "location": "",
           "remote": bool(re.search(r"\(remote\)", text, re.I))}
    # Explicit separator form: "Title - Company"
    parts = re.split(r"\s[-–·|]\s", t, maxsplit=1)
    if len(parts) > 1:
        out["title"] = parts[0][:290]
        out["company"] = parts[1][:290]
        t = parts[1]
    m = _LOC.search(t)
    if m:
        out["location"] = m.group(1).strip()[:290]
        head = t[:m.start()].strip()
        if len(parts) > 1:
            out["company"] = head[:290]
        elif head:
            out["title"] = head[:290]
    return out


def _parse_links(html: str) -> list[dict]:
    out, seen = [], set()
    soup = BeautifulSoup(html, "html.parser")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(" ", strip=True)
        item = None
        m = re.search(r"linkedin\.com/(?:comm/)?jobs/view/(\d+)", href)
        if m:
            item = dict(source="linkedin-alert", external_id=m.group(1),
                        url=f"https://www.linkedin.com/jobs/view/{m.group(1)}/")
        elif "naukri.com" in href and "job-listings" in href:
            m = re.search(r"job-listings-([\w-]+)", href)
            if m:
                item = dict(source="naukri-alert", external_id=m.group(1)[:290],
                            url=href.split("?")[0])
                if not text:
                    text = m.group(1).replace("-", " ")
        elif "indeed.com" in href and ("viewjob" in href or "jk=" in href):
            m = re.search(r"jk=([0-9a-f]+)", href)
            if m:
                item = dict(source="indeed-alert", external_id=m.group(1),
                            url=f"https://www.indeed.com/viewjob?jk={m.group(1)}")
        if not item or item["external_id"] in seen:
            continue
        if len(text) < 8 or text.lower() in ("view job", "see all jobs", "apply now"):
            continue
        item.setdefault("description",
                        f"(from a job-alert email; open the link for details)")
        seen.add(item["external_id"])
        item.update(_split_alert_text(text))
        item["description"] = f"(from a job-alert email; open {item['url']} for details)"
        out.append(item)
    return out


def fetch(profile):
    user = os.getenv("GMAIL_ADDRESS")
    pw = os.getenv("GMAIL_APP_PASSWORD")
    if not (user and pw):
        return []
    M = imaplib.IMAP4_SSL("imap.gmail.com")
    try:
        M.login(user, pw)
        M.select("INBOX")
        since = (date.today() - timedelta(days=3)).strftime("%d-%b-%Y")
        out = []
        for dom in SENDER_DOMAINS:
            typ, data = M.search(None, f'(FROM "{dom}" SINCE {since})')
            if typ != "OK" or not data or not data[0]:
                continue
            for num in data[0].split()[-6:]:  # last 6 emails per sender
                typ, msgdata = M.fetch(num, "(RFC822)")
                if typ != "OK":
                    continue
                msg = email_lib.message_from_bytes(msgdata[0][1])
                out.extend(_parse_links(_html_parts(msg)))
        return out
    finally:
        try:
            M.logout()
        except Exception:
            pass
