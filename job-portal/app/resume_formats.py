"""Country-specific resume conventions.

A CV that works in India is not what a German or US recruiter expects, and
several of these differences are legal rather than stylistic (anti-
discrimination rules mean US/UK/Australian employers must not see a photo,
date of birth, marital status or nationality). Each entry sets the
document name, length, what to include, and what to strip out.
"""
from __future__ import annotations

DEFAULT = {
    "label": "International",
    "doc_name": "Resume",
    "pages": "1-2 pages",
    "date_format": "%b %Y",
    "include": [
        "Full name, phone with country code, email, city and country",
        "LinkedIn and GitHub URLs",
        "A 2-3 line professional summary",
    ],
    "exclude": [
        "Photograph", "Date of birth or age", "Marital status",
        "Gender", "Religion", "Father's or spouse's name",
        "Full postal address", "Expected salary", "References",
    ],
    "notes": "Reverse-chronological. Lead every bullet with a strong verb "
             "and quantify impact.",
    "work_auth": "",
}

FORMATS = {
    "india": {
        **DEFAULT,
        "label": "India",
        "doc_name": "Resume",
        "pages": "1-2 pages",
        "notes": "Reverse-chronological. Indian recruiters expect notice "
                 "period and current/expected CTC to be discussed, but keep "
                 "them out of the document itself.",
        "work_auth": "",
    },
    "united states": {
        **DEFAULT,
        "label": "United States",
        "doc_name": "Resume",
        "pages": "strictly 1 page",
        "notes": "US resumes are 1 page and achievement-dense. Use American "
                 "spelling. No personal details of any kind - US employers "
                 "are legally barred from considering them.",
        "work_auth": "State visa sponsorship needs plainly, e.g. "
                     "'Requires H-1B sponsorship'.",
    },
    "united kingdom": {
        **DEFAULT,
        "label": "United Kingdom",
        "doc_name": "CV",
        "pages": "2 pages",
        "notes": "Called a CV. British spelling (optimise, specialise, "
                 "programme). A short personal-statement paragraph opens it.",
        "work_auth": "State right-to-work status, e.g. 'Requires Skilled "
                     "Worker visa sponsorship'.",
    },
    "ireland": {
        **DEFAULT,
        "label": "Ireland",
        "doc_name": "CV",
        "pages": "2 pages",
        "notes": "Called a CV. British/Irish spelling. Personal statement "
                 "at the top.",
        "work_auth": "State visa status, e.g. 'Requires Critical Skills "
                     "Employment Permit sponsorship'.",
    },
    "germany": {
        **DEFAULT,
        "label": "Germany",
        "doc_name": "Lebenslauf (CV)",
        "pages": "1-2 pages",
        "date_format": "%m/%Y",
        "notes": "German CVs are factual and tabular in tone, strictly "
                 "reverse-chronological with MM/YYYY dates and no gaps. "
                 "Photos and personal data were traditional but are now "
                 "discouraged under the AGG - leave them out. Add a "
                 "Languages section with CEFR levels (e.g. English C1).",
        "work_auth": "Mention EU Blue Card eligibility / that you require "
                     "visa sponsorship.",
    },
    "netherlands": {
        **DEFAULT,
        "label": "Netherlands",
        "doc_name": "CV",
        "pages": "2 pages",
        "notes": "Direct and factual. Add a Languages section with CEFR "
                 "levels. Dutch employers value clear, unembellished claims.",
        "work_auth": "Mention that you need the Highly Skilled Migrant "
                     "permit (kennismigrant) sponsorship.",
    },
    "australia": {
        **DEFAULT,
        "label": "Australia",
        "doc_name": "Resume",
        "pages": "2-3 pages",
        "notes": "Australian resumes run longer and expect more detail per "
                 "role, plus a Key Skills block near the top. Australian "
                 "spelling (organisation, specialise).",
        "work_auth": "State visa status explicitly - Australian job ads "
                     "almost always ask. E.g. 'Requires employer "
                     "sponsorship (subclass 482 / Skills in Demand visa)'.",
    },
    "new zealand": {
        **DEFAULT,
        "label": "New Zealand",
        "doc_name": "CV",
        "pages": "2-3 pages",
        "notes": "Similar to Australia; a Key Skills block up top and fuller "
                 "role detail. NZ/British spelling.",
        "work_auth": "State visa status, e.g. 'Requires Accredited Employer "
                     "Work Visa (AEWV) sponsorship'.",
    },
    "canada": {
        **DEFAULT,
        "label": "Canada",
        "doc_name": "Resume",
        "pages": "1-2 pages",
        "notes": "Close to the US format but 2 pages is acceptable. "
                 "Canadian spelling (favour, centre, but 'organization').",
        "work_auth": "State work-permit status, e.g. 'Requires LMIA-based "
                     "work permit sponsorship'.",
    },
    "singapore": {
        **DEFAULT,
        "label": "Singapore",
        "doc_name": "Resume",
        "pages": "1-2 pages",
        "notes": "Concise and metrics-led. British spelling.",
        "work_auth": "State pass requirement, e.g. 'Requires Employment "
                     "Pass (EP) sponsorship'.",
    },
    "spain": {
        **DEFAULT,
        "label": "Spain",
        "doc_name": "CV",
        "pages": "1-2 pages",
        "notes": "Spanish CVs are concise. Add a Languages section with "
                 "CEFR levels; Spanish ability is a plus but English-only "
                 "is fine for tech roles.",
        "work_auth": "Mention that you require EU work authorisation / "
                     "Blue Card sponsorship.",
    },
    "france": {
        **DEFAULT,
        "label": "France",
        "doc_name": "CV",
        "pages": "1-2 pages",
        "notes": "French CVs are compact and factual. Add a Languages "
                 "section with CEFR levels.",
        "work_auth": "Mention that you require a Talent Passport / EU Blue "
                     "Card sponsorship.",
    },
    "poland": {
        **DEFAULT,
        "label": "Poland",
        "doc_name": "CV",
        "pages": "1-2 pages",
        "notes": "Concise, skills-led. Add a Languages section with CEFR "
                 "levels.",
        "work_auth": "Mention that you require a work permit / Blue Card.",
    },
    "switzerland": {
        **DEFAULT,
        "label": "Switzerland",
        "doc_name": "CV",
        "pages": "2 pages",
        "notes": "Precise and factual, like the German format. Add a "
                 "Languages section with CEFR levels.",
        "work_auth": "Mention that you require a Swiss work permit "
                     "(non-EU quota).",
    },
    "austria": {
        **DEFAULT,
        "label": "Austria",
        "doc_name": "Lebenslauf (CV)",
        "pages": "1-2 pages",
        "date_format": "%m/%Y",
        "notes": "Follows the German convention: strictly reverse-"
                 "chronological, MM/YYYY dates, no gaps. Add Languages "
                 "with CEFR levels.",
        "work_auth": "Mention Red-White-Red Card / EU Blue Card "
                     "sponsorship.",
    },
    "united arab emirates": {
        **DEFAULT,
        "label": "United Arab Emirates",
        "doc_name": "CV",
        "pages": "2 pages",
        "notes": "Gulf employers do expect nationality and visa status, "
                 "and often a photo - but keep date of birth and marital "
                 "status out unless the posting asks.",
        "work_auth": "State current visa status and that you need employment "
                     "visa sponsorship.",
    },
}
FORMATS["uae"] = FORMATS["dubai"] = FORMATS["united arab emirates"]
FORMATS["usa"] = FORMATS["us"] = FORMATS["united states"]
FORMATS["uk"] = FORMATS["great britain"] = FORMATS["united kingdom"]
FORMATS["nz"] = FORMATS["new zealand"]
FORMATS["holland"] = FORMATS["netherlands"]
FORMATS["deutschland"] = FORMATS["germany"]


def for_country(country: str, is_india: bool | None = None) -> dict:
    key = (country or "").strip().lower()
    if key in FORMATS:
        return FORMATS[key]
    if is_india or key == "india":
        return FORMATS["india"]
    if key and key not in ("remote", "unknown", "worldwide", "anywhere"):
        # A country we have no table entry for: name it so the writer
        # applies that market's own conventions rather than a generic one.
        return {
            **DEFAULT,
            "label": country.strip().title(),
            "notes": (f"Follow standard {country.strip().title()} resume "
                      "conventions for the local market, including the "
                      "usual document length and whether a photo or "
                      "personal details are customary there. If the "
                      "country is in the EU/EEA, add a Languages section "
                      "with CEFR levels."),
            "work_auth": (f"State that you require work-visa sponsorship "
                          f"for {country.strip().title()}."),
        }
    return DEFAULT


def prompt_block(fmt: dict, needs_sponsorship: bool) -> str:
    """The formatting rules, as instructions for the resume writer."""
    lines = [
        f"TARGET MARKET: {fmt['label']}",
        f"Document type: {fmt['doc_name']}, {fmt['pages']}.",
        f"Convention: {fmt['notes']}",
        "Must include: " + "; ".join(fmt["include"]),
        "Must NOT include: " + "; ".join(fmt["exclude"]),
    ]
    if needs_sponsorship and fmt.get("work_auth"):
        lines.append("Work authorisation: " + fmt["work_auth"]
                     + " Put this as a single short line in the summary.")
    return "\n".join(lines)
