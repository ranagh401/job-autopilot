"""Find recruiter / hiring contact emails for a job: from the posting text,
the posting page, a web search for the company's HR/careers contacts, and
(optionally) the Hunter.io API."""
from __future__ import annotations

import base64
import os
import re
from urllib.parse import parse_qs, unquote, urlparse

import requests
from bs4 import BeautifulSoup

from .db import Contact, Job
from .llm import chat, llm_ready

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
BAD_PARTS = ["noreply", "no-reply", "donotreply", "example.", "sentry",
             "linkedin.com", "naukri.com", "indeed.com", "greenhouse.io",
             "lever.co", "adzuna", "remotive", "remoteok", "arbeitnow",
             "themuse", "glassdoor", "wixpress", "schema.org", "@2x",
             ".png", ".jpg", ".gif", ".webp", "@sentry", "godaddy"]
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def _clean(emails) -> list[str]:
    out = []
    for e in emails:
        e = e.strip().strip(".").lower()
        if any(b in e for b in BAD_PARTS):
            continue
        if e not in out:
            out.append(e)
    return out


HR_TITLE_RE = re.compile(
    r"recruit|talent|hr\b|human resource|people|hiring|staffing|"
    r"sourcer|acquisition", re.I)


# Company names that are really job boards, staffing agencies or listing
# aggregators - Hunter has nothing useful for these, so don't spend a
# search on them.
NOT_AN_EMPLOYER = re.compile(
    r"\bjobs?\b|hiring|careers|recruit|staffing|consultanc|manpower|"
    r"placement|talent\s+solutions|hr\s+services|outsourc|"
    r"top\s+gen|remote\s+ok|jobgether|weekday|hirist|instahyre", re.I)

_quota_cache: dict = {"left": None, "checked": 0.0}


def hunter_searches_left(max_age: float = 300.0) -> int | None:
    """Remaining Hunter searches, cached so we don't spend a request per
    lookup just to ask."""
    import time as _t
    if (_quota_cache["left"] is not None
            and _t.time() - _quota_cache["checked"] < max_age):
        return _quota_cache["left"]
    q = hunter_quota()
    _quota_cache["left"] = q.get("remaining") if q else None
    _quota_cache["checked"] = _t.time()
    return _quota_cache["left"]


def _hunter_worth_it(company: str, domain: str) -> tuple[bool, str]:
    """Hunter's free tier is 50 searches a month. Spend them only where
    they can plausibly pay off."""
    if NOT_AN_EMPLOYER.search(company or ""):
        return False, "not a real employer (job board / staffing agency)"
    if not domain:
        return False, "no company domain resolved"
    left = hunter_searches_left()
    reserve = int(os.getenv("HUNTER_MIN_RESERVE", "3"))
    if left is not None and left <= reserve:
        return False, f"only {left} Hunter searches left (reserve {reserve})"
    return True, ""


def _hunter_domain(company: str, domain: str = "") -> list[dict]:
    """Hunter domain-search, asking specifically for HR/recruiting people."""
    key = os.getenv("HUNTER_API_KEY")
    if not key or not (company or domain):
        return []
    ok, _why = _hunter_worth_it(company, domain)
    if not ok:
        return []
    if _quota_cache["left"]:
        _quota_cache["left"] -= 1
    # limit is capped at 10 on the free plan; anything higher 400s.
    params = {"api_key": key, "limit": 10, "type": "personal"}
    if domain:
        params["domain"] = domain
    else:
        params["company"] = company
    try:
        r = requests.get("https://api.hunter.io/v2/domain-search",
                         params={**params, "department": "hr"}, timeout=25)
        if r.status_code != 200:
            return []
        data = r.json().get("data") or {}
        emails = data.get("emails") or []
        # Nobody tagged "hr" - fall back to everyone, filtered by job title.
        if not emails:
            r = requests.get("https://api.hunter.io/v2/domain-search",
                             params=params, timeout=25)
            if r.status_code != 200:
                return []
            data = r.json().get("data") or {}
            emails = data.get("emails") or []
    except Exception:
        return []

    people = []
    for e in emails:
        if not e.get("value"):
            continue
        name = " ".join(x for x in [e.get("first_name"),
                                    e.get("last_name")] if x).strip()
        position = e.get("position") or ""
        if not name:
            continue
        people.append(dict(
            email=e["value"].lower(), name=name, role=position,
            linkedin=e.get("linkedin") or "",
            confidence=e.get("confidence"),
            hr=bool(HR_TITLE_RE.search(position)),
        ))
    # Named HR people first, then by Hunter's confidence score.
    people.sort(key=lambda p: (0 if p["hr"] else 1,
                               -(p.get("confidence") or 0)))
    return people[:6]


def _apollo_people(company: str, domain: str) -> list[dict]:
    """Apollo.io people search - a second source of named recruiters.

    Note: verified Aug 2026 that Apollo's FREE plan returns 403 for both
    people/match and mixed_people/search, so this yields nothing until the
    account is on a paid plan. It fails quietly and costs one request.
    """
    key = os.getenv("APOLLO_API_KEY")
    if not key or not (domain or company):
        return []
    payload = {
        "person_titles": ["talent acquisition", "recruiter",
                          "technical recruiter", "hr manager",
                          "head of people", "talent partner"],
        "per_page": 10,
    }
    if domain:
        payload["q_organization_domains"] = [domain]
    else:
        payload["q_organization_name"] = company
    try:
        r = requests.post(
            "https://api.apollo.io/api/v1/mixed_people/search",
            json=payload, timeout=30,
            headers={"Content-Type": "application/json",
                     "Cache-Control": "no-cache", "x-api-key": key})
        if r.status_code != 200:
            return []
        people = r.json().get("people") or []
    except Exception:
        return []
    out = []
    for p in people:
        email = (p.get("email") or "").strip().lower()
        # Apollo hides some addresses behind a credit unlock; skip those.
        if not email or "email_not_unlocked" in email or "@" not in email:
            continue
        name = " ".join(x for x in [p.get("first_name"),
                                    p.get("last_name")] if x).strip()
        title = p.get("title") or ""
        out.append(dict(email=email, name=name, role=title,
                        linkedin=p.get("linkedin_url") or "",
                        confidence=None,
                        hr=bool(HR_TITLE_RE.search(title))))
    out.sort(key=lambda p: 0 if p["hr"] else 1)
    return out[:6]


def _hunter_find(first: str, last: str, domain: str) -> dict:
    """Hunter email-finder: resolve a known person's address at a domain."""
    key = os.getenv("HUNTER_API_KEY")
    if not (key and domain and (first or last)):
        return {}
    try:
        r = requests.get("https://api.hunter.io/v2/email-finder",
                         params={"api_key": key, "domain": domain,
                                 "first_name": first, "last_name": last},
                         timeout=25)
        if r.status_code != 200:
            return {}
        d = r.json().get("data") or {}
    except Exception:
        return {}
    if not d.get("email"):
        return {}
    return dict(email=d["email"].lower(),
                name=f"{first} {last}".strip(),
                role=d.get("position") or "",
                linkedin=d.get("linkedin_url") or "",
                confidence=d.get("score"), hr=True)


PATTERNS = {
    "first.last": lambda f, l: f"{f}.{l}",
    "firstlast": lambda f, l: f"{f}{l}",
    "f.last": lambda f, l: f"{f[0]}.{l}",
    "flast": lambda f, l: f"{f[0]}{l}",
    "first_last": lambda f, l: f"{f}_{l}",
    "first": lambda f, l: f,
    "last.first": lambda f, l: f"{l}.{f}",
    "first.l": lambda f, l: f"{f}.{l[0]}",
}


def _split_name(name: str) -> tuple[str, str]:
    parts = [p for p in re.split(r"[^A-Za-z]+", (name or "").lower()) if p]
    if len(parts) < 2:
        return (parts[0] if parts else ""), ""
    return parts[0], parts[-1]


def detect_pattern(known: list[tuple[str, str]]) -> str:
    """Work out a company's address format from (email, full name) pairs
    we already know are real."""
    for email, name in known:
        local = email.split("@")[0].lower()
        first, last = _split_name(name)
        if not (first and last):
            continue
        for pname, build in PATTERNS.items():
            if build(first, last) == local:
                return pname
    return ""


def _harvest_people(company: str, domain: str) -> list[dict]:
    """Free name harvesting: search the public web for people who work in
    recruiting/engineering at this company. Costs nothing but a request."""
    if not company:
        return []
    people: dict[str, dict] = {}
    queries = [
        f'site:linkedin.com/in "{company}" ("talent acquisition" OR '
        f'recruiter OR "technical recruiter")',
        f'site:linkedin.com/in "{company}" ("HR manager" OR "people '
        f'partner" OR "hiring manager")',
        f'"{company}" "talent acquisition" OR recruiter India',
    ]
    for q in queries:
        # keep_all: the LinkedIn URL is what carries the person's name.
        urls, _ = _search(q, max_links=10, keep_all=True)
        for u in urls:
            m = re.search(r"linkedin\.com/in/([a-z]+)-([a-z]+)(?:-[a-z0-9]+)?",
                          u, re.I)
            if not m:
                continue
            first, last = m.group(1).lower(), m.group(2).lower()
            if len(first) < 2 or len(last) < 2:
                continue
            if PLACEHOLDER_NAME.search(f"{first} {last}"):
                continue
            key = f"{first} {last}"
            people.setdefault(key, {
                "first": first, "last": last,
                "name": f"{first.title()} {last.title()}",
                "linkedin": u.split("?")[0],
            })
        if len(people) >= 6:
            break
    return list(people.values())[:6]


def free_people_search(company: str, domain: str,
                       known: list[tuple[str, str]]) -> list[dict]:
    """Find contactable people without spending a Hunter credit.

    Two routes: addresses already published on the web, and - when we can
    confirm the company's address format from a known real address -
    building the address for a named recruiter found on the public web.
    """
    out: list[dict] = []
    if not domain:
        return out

    # 1. Addresses published openly that belong to a named person.
    for q in (f'"@{domain}" ("talent acquisition" OR recruiter OR '
              f'"hiring manager")',
              f'"@{domain}" hr email contact'):
        _, snippet_emails = _search(q, max_links=6)
        for e in snippet_emails:
            if not e.endswith("@" + domain):
                continue
            local = e.split("@")[0]
            if NON_HR_BOX.match(local) or PLACEHOLDER_NAME.search(e):
                continue
            if re.search(r"[._-]", local):  # looks like a person's address
                out.append(dict(email=e, name="", role="", linkedin="",
                                confidence=None, hr=True, source="websearch"))
        if out:
            break

    # 2. Named people + a confirmed address format.
    pattern = detect_pattern(known + [(o["email"], o["name"]) for o in out
                                      if o.get("name")])
    if pattern:
        build = PATTERNS[pattern]
        for p in _harvest_people(company, domain):
            email = f"{build(p['first'], p['last'])}@{domain}"
            if any(o["email"] == email for o in out):
                continue
            out.append(dict(email=email, name=p["name"], role="",
                            linkedin=p.get("linkedin", ""), confidence=70,
                            hr=True, source="pattern"))
    return out[:6]


def _named_recruiters_via_search(company: str, domain: str) -> list[dict]:
    """Find real HR people by name via public web search, then resolve their
    work address with Hunter's email-finder."""
    if not (company and domain):
        return []
    names: list[tuple[str, str]] = []
    for q in (f'"{company}" "talent acquisition" OR recruiter India',
              f'"{company}" "HR manager" OR "hiring manager"'):
        urls, _ = _search(q, max_links=6)
        text = " ".join(urls)
        # LinkedIn profile slugs carry the person's name: /in/first-last-1a2b
        for m in re.finditer(r"linkedin\.com/in/([a-z]+)-([a-z]+)", text, re.I):
            pair = (m.group(1).title(), m.group(2).title())
            if pair not in names:
                names.append(pair)
        if names:
            break
    out = []
    for first, last in names[:3]:
        found = _hunter_find(first, last, domain)
        if found:
            out.append(found)
    return out


def _people_from_posting(text: str) -> list[dict]:
    """Recruiter named in the posting itself, e.g. 'Contact Priya Sharma
    (priya.sharma@acme.com)'."""
    out = []
    for m in re.finditer(
            r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})[^@\n]{0,60}?"
            r"([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})",
            text or ""):
        name, email = m.group(1).strip(), m.group(2).lower()
        if any(b in email for b in BAD_PARTS):
            continue
        local = email.split("@")[0]
        parts = [p for p in re.split(r"[._-]", local) if len(p) > 2]
        # Only trust it when the address actually echoes the name.
        if not any(p.lower() in name.lower() for p in parts):
            continue
        out.append(dict(email=email, name=name, role="", linkedin="",
                        confidence=None, hr=True))
    return out[:3]


HR_WORDS = re.compile(r"hr|recruit|talent|career|job|hiring|people", re.I)
# Generic-but-usable inboxes, ranked below HR ones.
NEUTRAL_BOX = re.compile(r"^(info|contact|hello|hi|enquiry|enquiries|"
                         r"inquiry|admin|office|mail|reach)", re.I)
# Mailboxes that never route to a hiring team.
NON_HR_BOX = re.compile(r"^(press|media|investor|legal|privacy|security|"
                        r"abuse|billing|invoice|accounts|payments|refund|"
                        r"renewal|cancellation|upgrade|dpo|gdpr|compliance|"
                        r"webmaster|postmaster|newsletter|unsubscribe|"
                        r"subscribe|spam|jubao|complaint)", re.I)
SKIP_RESULT_DOMAINS = ["linkedin.com", "glassdoor", "indeed.com", "naukri.com",
                       "youtube.com", "facebook.com", "instagram.com",
                       "wikipedia.org", "reddit.com", "twitter.com", "x.com",
                       "crunchbase.com", "zoominfo.com", "rocketreach",
                       "apollo.io", "signalhire", "lusha.com", "36kr.com"]
COMMON_TLD_PARTS = {"com", "net", "org", "io", "co", "in", "ai", "app", "dev",
                    "inc", "ltd", "llc", "plc", "gmbh", "pvt", "private",
                    "limited", "technologies", "technology", "tech", "labs",
                    "solutions", "systems", "software", "group", "global",
                    "services", "consulting", "corp", "corporation", "the",
                    "and", "company", "india", "us", "uk"}


def _company_tokens(company: str) -> set[str]:
    words = re.split(r"[^A-Za-z0-9]+", (company or "").lower())
    return {w for w in words if len(w) > 2 and w not in COMMON_TLD_PARTS}


def _domain_matches_company(email: str, company: str) -> bool:
    """Keep only emails whose domain plausibly belongs to the company."""
    tokens = _company_tokens(company)
    if not tokens:
        return True  # nothing to verify against
    domain = email.split("@")[-1].lower()
    root = re.sub(r"[^a-z0-9]", "",
                  ".".join(domain.split(".")[:-1]) or domain)
    for t in tokens:
        if t in root or root in t:
            return True
        # "freshworks" vs "freshworks" style prefix overlap
        if len(t) >= 5 and len(root) >= 5 and (t[:5] == root[:5]):
            return True
    return False


def _unwrap(href: str) -> str:
    """Resolve a search-engine redirect wrapper to the real destination."""
    if "/ck/a" in href:  # Bing: ...&u=a1<base64url>
        m = re.search(r"[?&]u=a1([A-Za-z0-9_\-]+)", href)
        if not m:
            return ""
        raw = m.group(1)
        try:
            return base64.urlsafe_b64decode(
                raw + "=" * (-len(raw) % 4)).decode("utf-8", "ignore")
        except Exception:
            return ""
    if "uddg=" in href:  # DuckDuckGo
        return unquote(parse_qs(urlparse(href).query).get("uddg", [""])[0])
    return href


def _brave_search(query: str, max_links: int) -> tuple[list[str], str]:
    """Brave Search API - 2,000 queries/month free.

    The practical replacement for Google's Custom Search JSON API, which
    Google closed to NEW customers in 2025 and shuts down entirely on
    2027-01-01 - a fresh Cloud project always answers 403 "does not have
    the access to Custom Search JSON API" however it is configured.
    Brave honours quoted phrases, which scraped Bing does not, so precise
    searches like "hiring" + an address actually return the post.
    """
    key = os.getenv("BRAVE_API_KEY")
    if not key:
        return [], ""
    try:
        r = requests.get("https://api.search.brave.com/res/v1/web/search",
                         params={"q": query, "count": min(max_links, 20)},
                         headers={"Accept": "application/json",
                                  "X-Subscription-Token": key}, timeout=25)
        if r.status_code != 200:
            return [], ""
        results = (r.json().get("web") or {}).get("results") or []
    except Exception:
        return [], ""
    urls = [i.get("url", "") for i in results if i.get("url")]
    text = " ".join(f"{i.get('title', '')} {i.get('description', '')}"
                    for i in results)
    return urls[:max_links], text


def _serper_search(query: str, max_links: int) -> tuple[list[str], str]:
    """Serper.dev - real Google results via API, 2,500 free credits."""
    key = os.getenv("SERPER_API_KEY")
    if not key:
        return [], ""
    try:
        r = requests.post("https://google.serper.dev/search",
                          json={"q": query, "num": min(max_links, 20)},
                          headers={"X-API-KEY": key,
                                   "Content-Type": "application/json"},
                          timeout=25)
        if r.status_code != 200:
            return [], ""
        results = r.json().get("organic") or []
    except Exception:
        return [], ""
    urls = [i.get("link", "") for i in results if i.get("link")]
    text = " ".join(f"{i.get('title', '')} {i.get('snippet', '')}"
                    for i in results)
    return urls[:max_links], text


def api_search(query: str, max_links: int) -> tuple[list[str], str]:
    """Whichever real search API is configured, best first."""
    for provider in (_brave_search, _serper_search, _google_cse):
        urls, text = provider(query, max_links)
        if urls:
            return urls, text
    return [], ""


def _google_cse(query: str, max_links: int) -> tuple[list[str], str]:
    """Google Programmable Search - only works for pre-2025 projects."""
    key = os.getenv("GOOGLE_API_KEY")
    cx = os.getenv("GOOGLE_CSE_ID")
    if not (key and cx):
        return [], ""
    try:
        r = requests.get("https://www.googleapis.com/customsearch/v1",
                         params={"key": key, "cx": cx, "q": query,
                                 "num": min(max_links, 10)}, timeout=25)
        if r.status_code != 200:
            return [], ""
        items = r.json().get("items") or []
    except Exception:
        return [], ""
    urls = [i.get("link", "") for i in items if i.get("link")]
    # Snippets often contain the address itself - no page fetch needed.
    text = " ".join(f"{i.get('title', '')} {i.get('snippet', '')}"
                    for i in items)
    return urls[:max_links], text


def _search(query: str, max_links: int = 5,
            keep_all: bool = False) -> tuple[list[str], list[str]]:
    """Public web search (Google API if configured, else Bing HTML).

    Returns (result urls, emails visible in the result snippets).
    Set keep_all to skip the domain filter - needed when the URL itself is
    the payload, e.g. reading names out of LinkedIn profile slugs.
    """
    urls, snippet_text = api_search(query, max_links)
    if urls:
        if not keep_all:
            urls = [u for u in urls
                    if not any(d in u for d in SKIP_RESULT_DOMAINS)]
        return urls, _clean(EMAIL_RE.findall(snippet_text))

    urls = []
    snippet_text = ""
    try:
        r = requests.get("https://www.bing.com/search",
                         params={"q": query, "setlang": "en"},
                         headers=UA, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        snippet_text = soup.get_text(" ", strip=True)
        for a in soup.select("li.b_algo h2 a, li.b_algo a[href]"):
            url = _unwrap(a.get("href", ""))
            if url.startswith("http") and url not in urls:
                urls.append(url)
            if len(urls) >= max_links:
                break
    except Exception:
        pass
    if not urls:
        try:
            r = requests.get("https://lite.duckduckgo.com/lite/",
                             params={"q": query}, headers=UA, timeout=15)
            soup = BeautifulSoup(r.text, "html.parser")
            snippet_text += " " + soup.get_text(" ", strip=True)
            for a in soup.find_all("a", href=True):
                url = _unwrap(a["href"])
                if url.startswith("http") and url not in urls:
                    urls.append(url)
                if len(urls) >= max_links:
                    break
        except Exception:
            pass
    if not keep_all:
        urls = [u for u in urls if not any(d in u for d in SKIP_RESULT_DOMAINS)]
    return urls, _clean(EMAIL_RE.findall(snippet_text))


def _company_site_emails(urls: list[str]) -> list[str]:
    """Given search hits for a company, probe the most likely corporate site
    for contact/careers pages carrying an email address."""
    hosts: list[str] = []
    for u in urls:
        host = urlparse(u).netloc
        if host and host not in hosts:
            hosts.append(host)
    found: list[str] = []
    for host in hosts[:2]:
        base = f"https://{host}"
        for path in ("/contact", "/contact-us", "/careers", "/about", "/"):
            for e in _emails_from_page(base + path, follow_contact=False):
                if e not in found:
                    found.append(e)
            if found:
                return found
    return found


def _emails_from_page(url: str, follow_contact: bool = True) -> list[str]:
    """Fetch a page, harvest emails (incl. mailto: links); optionally follow
    one contact/careers link on the same host."""
    try:
        r = requests.get(url, headers=UA, timeout=12)
        html = r.text
    except Exception:
        return []
    soup = BeautifulSoup(html, "html.parser")
    raw = EMAIL_RE.findall(html)
    for a in soup.find_all("a", href=True):
        if a["href"].lower().startswith("mailto:"):
            raw.append(a["href"][7:].split("?")[0])
    emails = _clean(raw)
    if emails or not follow_contact:
        return emails
    host = urlparse(url).netloc
    for a in soup.find_all("a", href=True):
        href = a["href"]
        label = (a.get_text(" ", strip=True) + " " + href).lower()
        if not re.search(r"contact|career|job|hiring|about", label):
            continue
        nxt = requests.compat.urljoin(url, href)
        if urlparse(nxt).netloc != host or nxt.rstrip("/") == url.rstrip("/"):
            continue
        sub = _emails_from_page(nxt, follow_contact=False)
        if sub:
            return sub
    return []


def _web_search_emails(company: str, want_urls: bool = False):
    """Search the public web for a company's HR/recruitment email addresses.

    With want_urls=True returns (emails, result urls) so callers can fall
    back to guessing standard mailboxes on the company's own domain.
    """
    if not company or len(company) < 3:
        return ([], []) if want_urls else []
    found: list[str] = []
    all_urls: list[str] = []
    queries = [
        f'"{company}" ("hr@" OR "careers@" OR "jobs@" OR "recruitment@")',
        f'"{company}" careers contact email hr',
    ]
    for query in queries:
        urls, snippet_emails = _search(query, max_links=5)
        all_urls += [u for u in urls if u not in all_urls]
        for e in snippet_emails:
            if e not in found:
                found.append(e)
        for url in urls[:3]:
            for e in _emails_from_page(url):
                if e not in found:
                    found.append(e)
            if len(found) >= 4:
                break
        if found:
            break
    # Last resort: probe the company's own site for a contact/careers page.
    if not found and all_urls:
        found = _company_site_emails(all_urls)
    # Drop addresses that clearly aren't the company's, or never reach a
    # hiring team, then rank HR > neutral inboxes > everything else.
    found = [e for e in found
             if _domain_matches_company(e, company)
             and not NON_HR_BOX.match(e.split("@")[0])]
    found.sort(key=lambda e: 0 if HR_WORDS.search(e.split("@")[0])
               else (1 if NEUTRAL_BOX.match(e.split("@")[0]) else 2))
    return (found[:5], all_urls) if want_urls else found[:5]


def _mx_exists(domain: str) -> bool:
    """Cheap deliverability check: does the domain resolve for mail?"""
    try:
        import socket
        socket.getaddrinfo(domain, None)
        return True
    except Exception:
        return False


def _guess_hr_addresses(urls: list[str], company: str) -> list[str]:
    """email-sleuth style: try standard HR mailboxes on the company's own
    domain, keeping them only if the domain actually resolves."""
    tokens = _company_tokens(company)
    for u in urls:
        host = urlparse(u).netloc.replace("www.", "")
        if not host or not tokens:
            continue
        root = re.sub(r"[^a-z0-9]", "", ".".join(host.split(".")[:-1]))
        if not any(t in root or root in t for t in tokens):
            continue
        if not _mx_exists(host):
            continue
        return [f"careers@{host}", f"hr@{host}", f"jobs@{host}"]
    return []


def _company_domain(job) -> str:
    """Best guess at the employer's own mail domain."""
    for e in _clean(EMAIL_RE.findall(job.description or "")):
        if _domain_matches_company(e, job.company):
            return e.split("@")[-1]
    if job.url and job.url.startswith("http"):
        host = urlparse(job.url).netloc.replace("www.", "")
        if host and not any(d in host for d in SKIP_RESULT_DOMAINS) \
                and _domain_matches_company("x@" + host, job.company):
            return host
    tokens = _company_tokens(job.company)
    if not tokens:
        return ""
    # Most companies sit on the obvious domain - try that before spending
    # a web search on it. Only accept one that actually resolves.
    slug = re.sub(r"[^a-z0-9]", "", (job.company or "").lower())
    stripped = re.sub(
        r"(pvt|private|ltd|limited|llp|inc|llc|plc|gmbh|corp|corporation|"
        r"technologies|technology|solutions|systems|services|software|"
        r"labs|india|global|group)", "", slug)
    for candidate in dict.fromkeys([s for s in (slug, stripped) if 2 < len(s) < 30]):
        for tld in (".com", ".io", ".ai", ".co", ".in", ".co.in"):
            host = candidate + tld
            if _mx_exists(host):
                return host

    # Ask the web for the company's official site.
    urls, _ = _search(f'"{job.company}" official website careers', max_links=6)
    for u in urls:
        host = urlparse(u).netloc.replace("www.", "")
        root = re.sub(r"[^a-z0-9]", "", ".".join(host.split(".")[:-1]))
        if host and any(t in root or root in t for t in tokens):
            return host
    return ""


def hunter_quota() -> dict:
    """Remaining Hunter searches, so the UI can warn before they run out."""
    key = os.getenv("HUNTER_API_KEY")
    if not key:
        return {}
    try:
        r = requests.get("https://api.hunter.io/v2/account",
                         params={"api_key": key}, timeout=15)
        if r.status_code != 200:
            return {}
        req = (r.json().get("data") or {}).get("requests") or {}
        s = req.get("searches") or {}
        return {"used": s.get("used"), "available": s.get("available"),
                "remaining": (s.get("available") or 0) - (s.get("used") or 0)}
    except Exception:
        return {}


VERIFY_SYSTEM = (
    "You vet contact addresses a job seeker is about to cold-email about a "
    "specific opening. For EACH candidate decide whether it belongs to a "
    "real named individual who works at that employer, and whether that "
    "person is worth contacting about the role.\n"
    "kind must be one of:\n"
    "  hr - a named person in HR, recruiting, talent acquisition or people "
    "ops at this company\n"
    "  engineering - a named engineer, tech lead or engineering manager at "
    "this company who could refer or forward the application\n"
    "  other_person - a real named person at this company but in an "
    "unrelated function (sales, finance, marketing, support)\n"
    "  role_inbox - a shared or functional mailbox (careers@, hr@, jobs@, "
    "info@, contact@, hello@, support@) - NOT an individual\n"
    "  wrong_company - the address clearly belongs to a different "
    "organisation than the employer named below\n"
    "  unknown - not enough information\n"
    "A local part that is a person's name (john.smith, j.smith, priya.n) "
    "indicates an individual; a department or function word indicates a "
    "role inbox. Judge the company by the email DOMAIN: if it does not "
    "plausibly belong to the employer, say wrong_company.\n"
    "Be sceptical of short or generic company names that collide with an "
    "unrelated organisation - e.g. a university, charity or a firm in "
    "another country that merely shares the name or an abbreviation. Use "
    "the role, location and posting details below to judge whether the "
    "domain really is THIS employer; when the domain's country or sector "
    "does not fit the posting, answer wrong_company.\n"
    'Respond with JSON: {"results": [{"email": "...", "kind": "...", '
    '"is_person": true|false, "confidence": 0-100, '
    '"reason": "<max 12 words>"}]}'
)
# Ranked worst-to-best for picking who to write to.
KIND_RANK = {"hr": 0, "engineering": 1, "other_person": 2,
             "role_inbox": 3, "unknown": 4, "wrong_company": 5}
# Sample names companies put in documentation and form examples.
PLACEHOLDER_NAME = re.compile(
    r"\b(joe|john|jane|jo)[.\s_-]?(bloggs|doe|smith\s*example)\b|"
    r"\b(example|sample|test|dummy|firstname|lastname|yourname|"
    r"your\.name|user)\b", re.I)


def verify_contacts(session, job, contacts_list=None) -> list:
    """Ask the LLM which candidate addresses are real people at this
    company, and store the verdicts."""
    items = list(contacts_list if contacts_list is not None else job.contacts)
    items = [c for c in items if c.verified is None]
    if not items or not llm_ready():
        return []
    listing = "\n".join(
        f"- {c.email}" + (f" (name: {c.name})" if c.name else "")
        + (f" (title: {c.role})" if c.role else "")
        + f" [found via: {c.source}]"
        for c in items[:12])
    user = (f"EMPLOYER: {job.company or 'unknown'}\n"
            f"ROLE BEING APPLIED FOR: {job.title}\n"
            f"LOCATION: {job.location or 'n/a'} "
            f"({job.country or 'country unknown'})\n"
            f"POSTING URL: {job.url or 'n/a'}\n"
            f"POSTING EXTRACT: {(job.description or '')[:700]}\n\n"
            f"CANDIDATE ADDRESSES:\n{listing}")
    try:
        out = chat(VERIFY_SYSTEM, user, json_mode=True, kind="verify-contact")
    except Exception:
        return []
    by_email = {c.email.lower(): c for c in items}
    valid = set(KIND_RANK)
    for r in out.get("results") or []:
        c = by_email.get(str(r.get("email", "")).strip().lower())
        if not c:
            continue
        kind = str(r.get("kind") or "unknown").strip().lower()
        c.kind = kind if kind in valid else "unknown"
        # Contactable only when the model both says it is a person AND
        # places them in a function we would write to. "unknown" is not
        # good enough to spend a real cold email on.
        c.is_person = (bool(r.get("is_person"))
                       and c.kind in ("hr", "engineering", "other_person")
                       and not PLACEHOLDER_NAME.search(c.email)
                       and not PLACEHOLDER_NAME.search(c.name or ""))
        c.verified = c.is_person
        c.verify_note = str(r.get("reason") or "")[:300]
        try:
            c.confidence = int(r.get("confidence"))
        except (TypeError, ValueError):
            pass
    # Anything the model ignored is explicitly not verified.
    for c in items:
        if c.verified is None:
            c.verified = False
            c.kind = c.kind or "unknown"
    session.commit()
    return items


def _escalate_for_people(session, job, domain: str) -> list:
    """No verified human yet - go looking specifically for one, first in
    HR/recruiting, then among senior engineers who could refer."""
    added = []
    queries = [
        (f'"{job.company}" ("talent acquisition" OR recruiter OR '
         f'"hiring manager") email', "hr"),
        (f'"{job.company}" ("head of engineering" OR "engineering manager" '
         f'OR "senior engineer") email', "engineering"),
    ]
    existing = {c.email for c in job.contacts}
    for query, _kind in queries:
        urls, snippet_emails = _search(query, max_links=5)
        found: list[str] = list(snippet_emails)
        for u in urls[:3]:
            found += _emails_from_page(u)
        # Named people whose address looks like a person's name.
        for e in _clean(found):
            if e in existing or not _domain_matches_company(e, job.company):
                continue
            local = e.split("@")[0]
            if not re.search(r"[._-]", local) and len(local) > 12:
                continue
            if NON_HR_BOX.match(local) or HR_WORDS.search(local):
                continue  # functional mailbox, not a person
            c = Contact(job_id=job.id, email=e, source="escalated",
                        name="", role="")
            session.add(c)
            added.append(c)
            existing.add(e)
        # Also try resolving names found on LinkedIn slugs via Hunter.
        if domain:
            for h in _named_recruiters_via_search(job.company, domain):
                if h["email"] in existing:
                    continue
                c = Contact(job_id=job.id, email=h["email"],
                            source="escalated-person", name=h["name"],
                            role=h.get("role", ""),
                            linkedin=h.get("linkedin", ""),
                            confidence=h.get("confidence"))
                session.add(c)
                added.append(c)
                existing.add(h["email"])
        if added:
            session.commit()
            verify_contacts(session, job, added)
            if any(c.is_person for c in added):
                break
    session.commit()
    return added


def _reuse_company_contacts(session, job) -> list[dict]:
    """Hunter's free plan allows ~50 searches a month, so never spend a
    credit twice on the same employer: reuse contacts already discovered
    for another posting from that company."""
    if not job.company:
        return []
    prior = (session.query(Contact)
             .join(Job, Contact.job_id == Job.id)
             .filter(Job.company == job.company, Job.id != job.id,
                     Contact.source.in_(["hunter-person", "hunter",
                                         "search-person"]))
             .all())
    return [dict(email=c.email, name=c.name, role=c.role,
                 linkedin=c.linkedin, confidence=c.confidence,
                 person=c.is_person, source=c.source) for c in prior]


def has_identifiable_employer(job) -> bool:
    """Enough information to be sure which company this posting is from?

    Alert emails carry only a title and a link, and a short company name
    like "UNIS" or "Charlie" will happily match an unrelated university or
    firm. Hunting contacts from that is how you email the wrong people.
    """
    desc = (job.description or "").strip()
    if len(desc) < 200 or desc.startswith("(from a job-alert email"):
        return False
    return len((job.company or "").strip()) >= 3


def discover(session, job) -> list[Contact]:
    """Find who to email, strongly preferring a named HR person over a
    generic careers@ inbox - named humans reply far more often."""
    found: dict[str, dict] = {}
    # Only mine the posting itself when we cannot confirm the employer -
    # no external lookups that could attach somebody else's address.
    identifiable = has_identifiable_employer(job)

    def add(email: str, source: str, name="", role="", linkedin="",
            confidence=None, person=False):
        e = (email or "").strip().lower()
        if not e or any(b in e for b in BAD_PARTS):
            return
        found.setdefault(e, dict(source=source, name=name, role=role,
                                 linkedin=linkedin, confidence=confidence,
                                 person=person))

    # 1. A person named in the posting, with a matching address.
    for p in _people_from_posting(job.description or ""):
        add(p["email"], "posting-person", p["name"], p["role"], person=True)
    # 2. Any other address in the posting text.
    for e in _clean(EMAIL_RE.findall(job.description or "")):
        add(e, "posting")
    # 3. The posting page itself.
    if job.url and job.url.startswith("http") and "linkedin.com" not in job.url:
        try:
            page = requests.get(job.url, headers=UA, timeout=15).text
            for p in _people_from_posting(page):
                add(p["email"], "page-person", p["name"], person=True)
            for e in _clean(EMAIL_RE.findall(page)):
                add(e, "page")
        except Exception:
            pass

    if not identifiable:
        # Store only what the posting itself named, then stop.
        added = []
        existing = {c.email for c in job.contacts}
        for e, meta in found.items():
            if e in existing:
                continue
            c = Contact(job_id=job.id, email=e, source=meta["source"],
                        name=meta["name"], role=meta["role"],
                        is_person=meta["person"])
            session.add(c)
            added.append(c)
        session.commit()
        if added:
            verify_contacts(session, job, added)
        _choose_primary(session, job)
        return added

    # 4. Already paid for this employer on another posting? Reuse it.
    cached = _reuse_company_contacts(session, job)
    for c in cached:
        add(c["email"], c["source"], c["name"], c["role"], c["linkedin"],
            c["confidence"], person=c["person"])

    domain = ""
    if not cached:
        domain = _company_domain(job)
        # 5. Free first: addresses published on the web, plus named
        # recruiters whose address we can build from a confirmed format.
        known = [(e, m["name"]) for e, m in found.items() if m["name"]]
        for h in free_people_search(job.company, domain, known):
            add(h["email"],
                "pattern" if h["source"] == "pattern" else "websearch-person",
                h["name"], h["role"], h.get("linkedin", ""),
                h.get("confidence"), person=True)
        # 6. Apollo next - a separate free-tier allowance from Hunter's.
        if not any(m["person"] for m in found.values()):
            for h in _apollo_people(job.company, domain):
                add(h["email"], "apollo-person" if h["hr"] else "apollo",
                    h["name"], h["role"], h.get("linkedin", ""),
                    h.get("confidence"), person=True)
        # 7. Only spend a Hunter credit when everything else found nobody.
        if not any(m["person"] for m in found.values()):
            for h in _hunter_domain(job.company, domain):
                add(h["email"], "hunter-person" if h["hr"] else "hunter",
                    h["name"], h["role"], h.get("linkedin", ""),
                    h.get("confidence"), person=True)
            # Hunter also knows the format - reuse it for free on the
            # other names the web search turned up.
            known += [(e, m["name"]) for e, m in found.items() if m["name"]]
            for h in free_people_search(job.company, domain, known):
                add(h["email"],
                    "pattern" if h["source"] == "pattern" else "websearch-person",
                    h["name"], h["role"], h.get("linkedin", ""),
                    h.get("confidence"), person=True)
    # 7. Only now fall back to shared inboxes.
    if len(found) < 2:
        web, urls = _web_search_emails(job.company, want_urls=True)
        for e in web:
            add(e, "websearch")
        if not found:
            for e in _guess_hr_addresses(urls, job.company):
                add(e, "guessed")

    existing = {c.email for c in job.contacts}
    added = []
    for e, meta in list(found.items())[:10]:
        if e in existing:
            continue
        c = Contact(job_id=job.id, email=e, source=meta["source"],
                    name=meta["name"], role=meta["role"],
                    linkedin=meta["linkedin"], confidence=meta["confidence"],
                    is_person=meta["person"])
        session.add(c)
        added.append(c)
    session.commit()

    # Have the LLM confirm which of these are real people at this company
    # rather than shared inboxes or somebody else's address entirely.
    verify_contacts(session, job, added)
    if not any(c.is_person for c in job.contacts):
        added += _escalate_for_people(session, job, domain)

    _choose_primary(session, job)
    return added


def _choose_primary(session, job) -> None:
    """Pick who to write to: a verified human, best function first."""
    pool = [c for c in job.contacts if c.email]
    if not pool:
        return
    people = [c for c in pool if c.is_person
              and c.kind not in ("role_inbox", "wrong_company")]
    # A shared inbox is worth keeping for manual review, but an address
    # the LLM tied to a different company is worse than none at all.
    fallback = [c for c in pool if c.kind != "wrong_company"]
    if not people and not fallback:
        job.contact_email = ""
        session.commit()
        return
    ranked = sorted(
        people or fallback,
        key=lambda c: (KIND_RANK.get(c.kind or "unknown", 4),
                       0 if c.is_person else 1,
                       {"posting-person": 0, "hunter-person": 1,
                        "apollo-person": 2, "websearch-person": 3,
                        "escalated-person": 4, "search-person": 5,
                        "pattern": 6, "page-person": 7, "posting": 8,
                        "hunter": 9, "apollo": 10, "escalated": 11,
                        "websearch": 12, "page": 13,
                        "guessed": 14}.get(c.source, 15),
                       -(c.confidence or 0)))
    job.contact_email = ranked[0].email
    session.commit()
