"""Job source registry: fetch from every provider, dedupe, store."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from ..db import Contact, Job
from . import (adzuna, arbeitnow, ashby, gmail_alerts, greenhouse,
               hiring_posts, instahyre, jobspy, jsearch, lever, remoteok,
               remotive, seek, themuse, wellfound)

PROVIDERS = [remotive, remoteok, arbeitnow, themuse, adzuna, jsearch,
             greenhouse, lever, ashby, gmail_alerts, seek, hiring_posts,
             instahyre, wellfound, jobspy]

# Noise words stripped before building a job's dedupe key.
_TITLE_NOISE = re.compile(
    r"\b(senior|sr|junior|jr|lead|staff|principal|i{1,3}|iv|v|"
    r"[0-9]+|full[- ]?time|part[- ]?time|remote|hybrid|onsite|"
    r"contract|permanent|new|urgent|hiring|immediate|joiner)\b", re.I)
_LEGAL_SUFFIX = re.compile(
    r"\b(pvt|private|ltd|limited|llp|inc|llc|plc|gmbh|corp|corporation|"
    r"technologies|technology|solutions|systems|services|software|labs|"
    r"india|global|group|co)\b", re.I)

# A title must look like one of the candidate's target roles.
ROLE_ALLOW = re.compile(
    r"\b(ai|a\.i\.|ml|machine\s*learning|deep\s*learning|gen\s*ai|"
    r"generative|llm|nlp|rag|agentic|data\s*scien\w*|"
    r"software\s+(engineer|developer|dev)|backend|back-end|back\s+end|"
    r"full\s*stack|python|sde|applied\s+scien\w*|research\s+engineer|"
    r"platform\s+engineer|mlops)\b", re.I)

# Seniority the candidate (~2 yrs) cannot credibly claim, when it appears
# in the title itself.
SENIOR_TITLE = re.compile(
    r"\b(senior|sr\.?|lead|staff|principal|architect|manager|head|"
    r"director|vp|vice\s+president|chief|expert|specialist\s+iv|"
    r"iii|iv|v)\b", re.I)

INDIA_HINTS = re.compile(
    r"\b(india|indian|bengaluru|bangalore|hyderabad|pune|chennai|mumbai|"
    r"delhi|noida|gurgaon|gurugram|kolkata|ahmedabad|jaipur|kochi|"
    r"cochin|coimbatore|indore|chandigarh|trivandrum|thiruvananthapuram|"
    r"vizag|visakhapatnam|mysore|mysuru|nagpur|bhubaneswar|"
    r"navi\s*mumbai|thane|pimpri|karnataka|telangana|maharashtra|"
    r"tamil\s*nadu|kerala|haryana|gujarat|punjab|rajasthan|"
    r"uttar\s*pradesh|west\s*bengal|ncr)\b", re.I)


def role_matches(title: str) -> bool:
    """True when the title is one of the roles the candidate targets."""
    t = title or ""
    if not ROLE_ALLOW.search(t):
        return False
    return not SENIOR_TITLE.search(t)


# Country/city words that mean the role is definitely NOT in India.
ABROAD_HINTS = re.compile(
    r"\b(usa|u\.s\.|united states|canada|toronto|vancouver|uk|"
    r"united kingdom|london|manchester|ireland|dublin|germany|berlin|"
    r"munich|münchen|hamburg|frankfurt|osnabrück|netherlands|amsterdam|"
    r"france|paris|spain|madrid|barcelona|portugal|lisbon|poland|warsaw|"
    r"sweden|stockholm|norway|oslo|denmark|copenhagen|finland|helsinki|"
    r"switzerland|zurich|zürich|austria|vienna|belgium|brussels|"
    r"australia|sydney|melbourne|new zealand|singapore|dubai|uae|"
    r"abu dhabi|qatar|doha|saudi|riyadh|japan|tokyo|"
    r"new york|san francisco|seattle|austin|boston|chicago|atlanta|"
    r"remote, us|us remote|emea|apac)\b", re.I)


def is_domestic(location: str, remote: bool = False,
                *extra: str) -> bool:
    """India-based (or India-inclusive remote) rather than abroad.

    Alert-email sources often leave `location` blank and bury the city in
    the title or company, so callers pass those in as `extra`.
    """
    blob = " ".join(x for x in (location or "", *extra) if x)
    if INDIA_HINTS.search(blob):
        return True
    if ABROAD_HINTS.search(blob):
        return False
    loc = (location or "").strip()
    if remote and (not loc or re.search(
            r"\b(worldwide|anywhere|global|remote)\b", loc, re.I)):
        return True
    return False


def job_is_domestic(job) -> bool:
    """Is this role in India?

    The LLM decides this while scoring (it reads the whole posting, so it
    catches the country wherever it is mentioned). The keyword heuristic
    below is only a stand-in for jobs that have not been scored yet.
    """
    if job.is_india is not None:
        return job.is_india
    return is_domestic(job.location, job.remote, job.company or "",
                       job.title or "", (job.description or "")[:400])


_REL_RE = re.compile(r"(\d+)\s*(minute|hour|day|week|month)s?\s*ago", re.I)
_REL_UNITS = {"minute": 1 / 1440, "hour": 1 / 24, "day": 1,
              "week": 7, "month": 30}


def parse_posted(value) -> datetime | None:
    """Normalise the many date shapes the sources emit to a datetime."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    s = str(value).strip()
    if not s or s.lower() in ("nan", "none", "null"):
        return None
    # Epoch seconds/millis (RemoteOK, Lever)
    if s.isdigit():
        n = int(s)
        if n > 10_000_000_000:
            n //= 1000
        if 946_684_800 < n < 4_102_444_800:  # 2000..2100
            return datetime.fromtimestamp(n)
        return None
    low = s.lower()
    if low.startswith("today") or low.startswith("just"):
        return datetime.now()
    if low.startswith("yesterday"):
        return datetime.now() - timedelta(days=1)
    m = _REL_RE.search(low)
    if m:
        return datetime.now() - timedelta(
            days=int(m.group(1)) * _REL_UNITS[m.group(2)])
    iso = s.replace("Z", "+00:00")
    for candidate in (iso, iso[:19], iso[:10]):
        try:
            dt = datetime.fromisoformat(candidate)
            if dt.tzinfo:
                dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
            return dt
        except ValueError:
            continue
    for fmt in ("%a, %d %b %Y %H:%M:%S", "%d %b %Y", "%Y/%m/%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(s[:len(fmt) + 6].strip(), fmt)
        except ValueError:
            continue
    return None


def dedupe_key(title: str, company: str) -> str:
    """Normalised company+title so the same role from two boards collapses."""
    t = _TITLE_NOISE.sub(" ", (title or "").lower())
    c = _LEGAL_SUFFIX.sub(" ", (company or "").lower())
    t = re.sub(r"[^a-z ]", " ", t)
    c = re.sub(r"[^a-z ]", " ", c)
    t = " ".join(sorted(set(w for w in t.split() if len(w) > 2)))
    c = " ".join(w for w in c.split() if len(w) > 1)
    return f"{c}|{t}"[:200]


def fetch_all(session, profile) -> dict:
    counts = {}
    for mod in PROVIDERS:
        name = mod.__name__.rsplit(".", 1)[-1]
        try:
            items = mod.fetch(profile) or []
        except Exception as e:
            counts[name] = f"error: {type(e).__name__}: {e}"
            continue
        added, dup = store(session, items, profile)
        counts[name] = f"{added} new of {len(items)}"
        if dup:
            counts[name] += f" ({dup} dupes)"
    session.commit()
    return counts


def store(session, items: list[dict], profile: dict | None = None):
    """Insert new jobs, skipping duplicates and blocked companies.

    Returns (added, duplicates_skipped).
    """
    profile = profile or {}
    blocked = [c.lower() for c in (profile.get("company_blocklist") or [])]
    title_block = [t.lower() for t in (profile.get("title_blocklist") or [])]
    added = dup = 0
    for it in items:
        title = (it.get("title") or "").strip()
        if not title:
            continue
        company = (it.get("company") or "").strip()
        if any(b in company.lower() for b in blocked if b):
            continue
        if any(b in title.lower() for b in title_block if b):
            continue
        # Only roles the candidate actually targets, at a level they can claim.
        if not role_matches(title):
            continue
        src = str(it.get("source") or "unknown")[:80]
        ext = str(it.get("external_id") or it.get("url") or "")[:300]
        if not ext:
            continue
        if session.query(Job.id).filter_by(source=src, external_id=ext).first():
            continue
        url = it.get("url") or ""
        if url and session.query(Job.id).filter(Job.url == url).first():
            dup += 1
            continue
        # Same role from another board: keep the first, drop the rest.
        key = dedupe_key(title, company)
        if company and session.query(Job.id).filter(
                Job.dedupe_key == key).first():
            dup += 1
            continue
        job = Job(
            source=src,
            external_id=ext,
            title=title[:300],
            company=company[:300],
            location=(it.get("location") or "")[:300],
            remote=bool(it.get("remote")),
            url=url,
            description=it.get("description") or "",
            salary=(it.get("salary") or "")[:200],
            posted_at=str(it.get("posted_at") or "")[:60],
            posted_dt=parse_posted(it.get("posted_at")),
            dedupe_key=key,
        )
        # A hiring post already names who to write to - keep it.
        contact_email = (it.get("_contact_email") or "").strip().lower()
        if contact_email:
            job.contact_email = contact_email
        session.add(job)
        if contact_email:
            session.flush()
            # Left unverified on purpose: the normal LLM check decides
            # whether this is a real person, a shared inbox or somebody
            # else entirely. Trusting a scraped address blindly is how
            # you end up emailing "googlers@google.com".
            session.add(Contact(
                job_id=job.id, email=contact_email,
                name=it.get("_contact_name") or "",
                source="hiring-post", is_person=False, verified=None))
        added += 1
    return added, dup
