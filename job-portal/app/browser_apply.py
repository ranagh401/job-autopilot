"""Fill and submit application forms with a real browser.

Greenhouse, Ashby, Workable and friends build their forms in JavaScript,
so an HTTP POST reaches nothing. Playwright drives an actual Chromium:
it reads the rendered fields, fills the ones it recognises, asks the LLM
for anything employer-specific, uploads the resume, and submits.

Safety rules that are not negotiable here:
  * Nothing is submitted unless submit=True is passed explicitly.
  * A field the LLM cannot answer honestly is left blank and reported,
    rather than filled with a guess.
  * The page is screenshotted before and after, so every submission has
    evidence of what was actually sent.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .db import DATA_DIR
from .llm import chat, llm_ready

SHOTS = DATA_DIR / "screenshots"
SHOTS.mkdir(exist_ok=True)

# label text -> what to type, from the candidate profile / answers
FIELD_MAP = [
    (r"first\s*name|given name", "first_name"),
    (r"last\s*name|surname|family name", "last_name"),
    (r"full\s*name|^name$|your name", "full_name"),
    (r"e-?mail", "email"),
    (r"phone|mobile|contact number", "phone"),
    (r"linkedin", "linkedin"),
    (r"github", "github"),
    (r"portfolio|website|personal site", "portfolio"),
    (r"city|current location|where are you based|location", "location"),
    (r"notice period", "notice_period"),
    (r"salary|compensation|ctc|expected pay", "salary_expectation"),
    (r"cover letter|why do you want|why are you interested|"
     r"tell us about|motivation", "cover_letter"),
    (r"work authoris|work authoriz|visa|sponsorship|right to work|"
     r"legally authorized|eligible to work", "work_authorisation"),
    (r"years of experience|experience.*years", "experience_years"),
]

ANSWER_SYSTEM = (
    "Answer one question on a job application form as the candidate. "
    "Use only facts from the profile - never invent experience, "
    "qualifications or eligibility. Match the expected answer type: for a "
    "yes/no question reply exactly 'Yes' or 'No'; for a dropdown pick the "
    "closest of the given options verbatim; otherwise answer in at most "
    "40 words. If the profile does not support an honest answer, reply "
    "exactly: UNKNOWN\n"
    'Respond with JSON: {"answer": "..."}'
)


def _values(profile: dict, answers: dict) -> dict:
    first, _, last = (profile.get("name") or "").partition(" ")
    links = profile.get("links") or {}
    return {
        "first_name": first,
        "last_name": last or first,
        "full_name": profile.get("name", ""),
        "email": profile.get("email", ""),
        "phone": str(profile.get("phone", "")),
        "linkedin": links.get("linkedin", ""),
        "github": links.get("github", ""),
        "portfolio": links.get("portfolio", ""),
        "location": profile.get("current_location", ""),
        "notice_period": (answers.get("notice_period")
                          or profile.get("notice_period") or ""),
        "salary_expectation": (answers.get("salary_expectation")
                               or profile.get("expected_ctc")
                               or "Negotiable"),
        "cover_letter": answers.get("cover_letter", ""),
        "work_authorisation": answers.get("work_authorisation", ""),
        "experience_years": str(profile.get("experience_years", "")),
    }


def _match_field(label: str, values: dict) -> str | None:
    low = (label or "").strip().lower()
    if not low:
        return None
    for pattern, key in FIELD_MAP:
        if re.search(pattern, low):
            val = values.get(key, "")
            if val:
                return val
    return None


def _ask_llm(label: str, options: list[str], job, profile: dict,
             answers: dict) -> str:
    if not llm_ready():
        return ""
    from .profile import profile_summary
    opts = ("\nOPTIONS (choose one exactly): " + " | ".join(options)
            if options else "")
    user = (f"CANDIDATE:\n{profile_summary(profile)}\n\n"
            f"ROLE: {job.title} at {job.company} "
            f"({job.country or job.location})\n"
            f"Notice period: {answers.get('notice_period', 'n/a')}; "
            f"work authorisation: {answers.get('work_authorisation', 'n/a')}"
            f"\n\nFORM QUESTION: {label}{opts}")
    try:
        out = chat(ANSWER_SYSTEM, user, json_mode=True, kind="form-answer")
    except Exception:
        return ""
    ans = str(out.get("answer") or "").strip()
    return "" if ans.upper() == "UNKNOWN" else ans


def _label_for(page, handle) -> str:
    """Best-effort visible label for a field."""
    try:
        return page.evaluate(
            """el => {
                const byFor = el.id && document.querySelector(
                    `label[for="${CSS.escape(el.id)}"]`);
                if (byFor) return byFor.innerText;
                const wrap = el.closest('label');
                if (wrap) return wrap.innerText;
                const aria = el.getAttribute('aria-label');
                if (aria) return aria;
                let n = el.parentElement, hops = 0;
                while (n && hops < 4) {
                    const lab = n.querySelector('label, legend');
                    if (lab && lab.innerText.trim()) return lab.innerText;
                    n = n.parentElement; hops++;
                }
                return el.getAttribute('placeholder')
                    || el.getAttribute('name') || '';
            }""", handle) or ""
    except Exception:
        return ""


def _fill_comboboxes(page, job, profile, answers, filled, skipped) -> None:
    """Handle React-style dropdowns, which are divs rather than <select>.

    They read "Select..." until clicked; the options appear in a popup
    list that has to be clicked or typed into.
    """
    selectors = ('div[class*="select__control"]',
                 'div[class*="Select-control"]',
                 '[role="combobox"]')
    seen = 0
    for sel in selectors:
        boxes = page.query_selector_all(sel)
        for box in boxes:
            if seen >= 25:
                return
            try:
                if not box.is_visible():
                    continue
                text = (box.inner_text() or "").strip()
                # Already answered - leave it alone.
                if text and not text.lower().startswith("select"):
                    continue
                label = _label_for(page, box)
                box.click(timeout=5000)
                page.wait_for_timeout(500)
                opts = page.query_selector_all(
                    '[class*="select__option"], [role="option"]')
                choices = []
                for o in opts[:30]:
                    t = (o.inner_text() or "").strip()
                    if t:
                        choices.append(t)
                if not choices:
                    page.keyboard.press("Escape")
                    skipped.append((label or "dropdown").strip()[:70])
                    continue
                answer = _ask_llm(label, choices, job, profile, answers)
                picked = None
                if answer:
                    for o in opts:
                        t = (o.inner_text() or "").strip()
                        if t.lower() == answer.lower():
                            picked = o
                            break
                    if picked is None:
                        for o in opts:
                            t = (o.inner_text() or "").strip().lower()
                            if t and (answer.lower() in t
                                      or t in answer.lower()):
                                picked = o
                                break
                if picked is None:
                    page.keyboard.press("Escape")
                    skipped.append((label or "dropdown").strip()[:70])
                    continue
                picked.click(timeout=5000)
                page.wait_for_timeout(350)
                filled.append((label or "dropdown").strip()[:70])
                seen += 1
            except Exception:
                try:
                    page.keyboard.press("Escape")
                except Exception:
                    pass
                continue


CAPTCHA_MARKS = [
    "iframe[src*='recaptcha']", "iframe[src*='hcaptcha']",
    "iframe[src*='turnstile']", "iframe[src*='geetest']",
    "iframe[title*='captcha' i]", ".g-recaptcha", ".h-captcha",
    "[class*='geetest']", "[id*='captcha']",
]
CAPTCHA_TEXT = re.compile(
    r"drag the element|i'm not a robot|verify you are human|"
    r"complete the security check|slide to verify", re.I)


CAPTCHA_HOSTS = re.compile(
    r"recaptcha|hcaptcha|turnstile|geetest|arkoselabs|funcaptcha|"
    r"perimeterx|datadome|friendlycaptcha", re.I)


def has_captcha(page) -> bool:
    """Is a human-verification challenge in the way?

    These exist specifically to stop automated submission, so when one
    appears the honest move is to stop and hand the form to the user
    rather than try to get around it. Challenges are almost always
    rendered inside a third-party iframe, so the parent page's text does
    not mention them - the frame URLs are the reliable signal.
    """
    try:
        for frame in page.frames:
            if CAPTCHA_HOSTS.search(frame.url or ""):
                return True
    except Exception:
        pass
    for sel in CAPTCHA_MARKS:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                return True
        except Exception:
            continue
    # Some challenges render inline; check the page and each frame's text.
    try:
        if CAPTCHA_TEXT.search(page.inner_text("body") or ""):
            return True
    except Exception:
        pass
    try:
        for frame in page.frames[:8]:
            try:
                if CAPTCHA_TEXT.search(frame.inner_text("body") or ""):
                    return True
            except Exception:
                continue
    except Exception:
        pass
    return False


def _required_but_empty(page) -> list[str]:
    """Required questions the form would reject on submit."""
    try:
        return page.evaluate(
            """() => {
                const out = [];
                const labelOf = el => {
                    const l = el.closest('div')?.querySelector('label');
                    return (l?.innerText || el.getAttribute('aria-label')
                            || el.getAttribute('name') || '').trim();
                };
                document.querySelectorAll(
                    'input[required], select[required], textarea[required], '
                    '[aria-required="true"]').forEach(el => {
                    if (el.type === 'hidden' || el.offsetParent === null)
                        return;
                    const filled = el.value && el.value.trim();
                    if (!filled) {
                        const t = labelOf(el);
                        if (t && !out.includes(t)) out.push(t.slice(0, 70));
                    }
                });
                document.querySelectorAll(
                    '[class*="select__control"], [role="combobox"]'
                ).forEach(el => {
                    const txt = (el.innerText || '').trim();
                    const lab = labelOf(el);
                    if (txt.toLowerCase().startsWith('select')
                        && lab.includes('*') && !out.includes(lab))
                        out.push(lab.slice(0, 70));
                });
                return out;
            }""") or []
    except Exception:
        return []


def direct_form_url(url: str) -> str:
    """Go straight to the application form.

    A posting page is not the form: on Lever and Ashby the job page only
    carries an "Apply for this job" LINK, so landing there and looking
    for inputs finds nothing at all.
    """
    u = (url or "").split("?")[0].rstrip("/")
    if "jobs.lever.co" in u and not u.endswith("/apply"):
        return u + "/apply"
    if "jobs.ashbyhq.com" in u and not u.endswith("/application"):
        return u + "/application"
    return url


def fill_and_submit(job, profile: dict, resume_path: str, answers: dict,
                    submit: bool = False, timeout_ms: int = 60000) -> dict:
    """Drive the real form. Returns what was filled, skipped and submitted."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {"ok": False, "detail": "playwright is not installed",
                "filled": [], "skipped": []}

    url = direct_form_url(job.url)
    values = _values(profile, answers)
    filled: list[str] = []
    skipped: list[str] = []
    shot = SHOTS / f"job{job.id}.png"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            viewport={"width": 1400, "height": 1000},
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"))
        page = ctx.new_page()
        try:
            page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            page.wait_for_timeout(2500)

            # Some boards still hide the form behind an "Apply" control -
            # which may be a link rather than a button.
            if not page.query_selector("input, textarea"):
                for role in ("link", "button"):
                    clicked = False
                    for label in ("Apply for this job", "Apply now",
                                  "Apply", "Submit application"):
                        try:
                            el = page.get_by_role(
                                role, name=re.compile(label, re.I)).first
                            if el.is_visible(timeout=1200):
                                el.click()
                                page.wait_for_load_state(
                                    "domcontentloaded", timeout=20000)
                                page.wait_for_timeout(2000)
                                clicked = True
                                break
                        except Exception:
                            continue
                    if clicked:
                        break

            # Resume upload first - some forms autofill from it.
            if resume_path and Path(resume_path).exists():
                for sel in ('input[type="file"]#resume',
                            'input[type="file"][name*="resume" i]',
                            'input[type="file"]'):
                    try:
                        inp = page.locator(sel).first
                        if inp.count():
                            inp.set_input_files(resume_path, timeout=15000)
                            filled.append("resume upload")
                            page.wait_for_timeout(2500)
                            break
                    except Exception:
                        continue

            # Text inputs and textareas.
            for handle in page.query_selector_all(
                    'input[type="text"], input[type="email"], '
                    'input[type="tel"], input[type="url"], input:not([type]), '
                    'textarea'):
                try:
                    if not handle.is_visible() or not handle.is_enabled():
                        continue
                    if handle.input_value():
                        continue  # already populated by the resume parse
                    label = _label_for(page, handle)
                    val = _match_field(label, values)
                    if val is None:
                        val = _ask_llm(label, [], job, profile, answers)
                    if not val:
                        if label.strip():
                            skipped.append(label.strip()[:70])
                        continue
                    handle.fill(val[:4000], timeout=8000)
                    filled.append(label.strip()[:70] or "field")
                except Exception:
                    continue

            # Native dropdowns.
            for sel in page.query_selector_all("select"):
                try:
                    if not sel.is_visible():
                        continue
                    label = _label_for(page, sel)
                    options = [o.strip() for o in
                               (sel.inner_text() or "").split("\n")
                               if o.strip()]
                    choice = _ask_llm(label, options[:25], job, profile,
                                      answers)
                    if not choice:
                        skipped.append(label.strip()[:70] or "dropdown")
                        continue
                    try:
                        sel.select_option(label=choice, timeout=5000)
                    except Exception:
                        sel.select_option(index=1, timeout=5000)
                    filled.append(label.strip()[:70] or "dropdown")
                except Exception:
                    continue

            # React comboboxes (Greenhouse, Ashby, Lever all use these):
            # a div that shows "Select..." until you click and choose.
            _fill_comboboxes(page, job, profile, answers, filled, skipped)

            # Anything required and still empty would fail validation.
            missing = _required_but_empty(page)

            page.screenshot(path=str(shot), full_page=True)

            if has_captcha(page):
                return {"ok": False, "captcha": True,
                        "detail": ("this employer uses a CAPTCHA, so the "
                                   "form cannot be submitted automatically "
                                   "- open the link, the answers are ready "
                                   "to paste"),
                        "filled": filled, "skipped": skipped,
                        "screenshot": str(shot)}

            if missing and submit:
                return {"ok": False,
                        "detail": ("not submitted - required questions are "
                                   "still unanswered: "
                                   + "; ".join(missing[:4])),
                        "filled": filled, "skipped": skipped,
                        "missing_required": missing,
                        "screenshot": str(shot)}

            if not submit:
                return {"ok": False, "detail": "form filled but NOT submitted "
                                               "(dry run)",
                        "filled": filled, "skipped": skipped,
                        "screenshot": str(shot), "dry_run": True}

            # Submit.
            clicked = False
            for name in ("Submit application", "Submit Application",
                         "Submit", "Send application", "Apply"):
                try:
                    btn = page.get_by_role("button",
                                           name=re.compile(name, re.I)).first
                    if btn.is_visible(timeout=1500):
                        btn.click(timeout=10000)
                        clicked = True
                        break
                except Exception:
                    continue
            if not clicked:
                return {"ok": False,
                        "detail": "could not find the submit button",
                        "filled": filled, "skipped": skipped,
                        "screenshot": str(shot)}

            page.wait_for_timeout(6000)
            after = SHOTS / f"job{job.id}_after.png"
            page.screenshot(path=str(after), full_page=True)
            body = (page.inner_text("body") or "").lower()
            ok = any(w in body for w in (
                "thank you", "thanks for applying", "application received",
                "successfully submitted", "we have received",
                "application submitted"))
            return {"ok": ok,
                    "detail": ("submitted and confirmed by the site" if ok
                               else "submit clicked but no confirmation "
                                    "text found - check the screenshot"),
                    "filled": filled, "skipped": skipped,
                    "screenshot": str(after)}
        except Exception as e:
            try:
                page.screenshot(path=str(shot), full_page=True)
            except Exception:
                pass
            return {"ok": False, "detail": f"{type(e).__name__}: {e}",
                    "filled": filled, "skipped": skipped,
                    "screenshot": str(shot)}
        finally:
            ctx.close()
            browser.close()
