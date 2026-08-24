"""ATS fit scoring for a tailored resume against a job description.

Follows the Resume-Matcher weighting: keyword match 55%, skills coverage
25%, section completeness 20%. Keywords are extracted from the job
description by the LLM; matching itself is deterministic word-boundary
regex, so the score is reproducible and cheap to recompute.
"""
from __future__ import annotations

import json
import re

from .llm import chat, llm_ready

KEYWORD_SYSTEM = (
    "Extract the hiring requirements from a job description.\n"
    'Respond with JSON: {"required_skills": ["..."], '
    '"preferred_skills": ["..."], "keywords": ["..."]}\n'
    "required_skills: hard skills/tools the posting demands (max 15).\n"
    "preferred_skills: nice-to-haves (max 10).\n"
    "keywords: other ATS-relevant terms - methodologies, domain terms, "
    "certifications (max 15).\n"
    "Use the posting's own wording. No duplicates across lists."
)

SECTIONS = {
    "summary": r"\b(summary|profile|objective)\b",
    "experience": r"\b(experience|employment|work history)\b",
    "education": r"\b(education|academics?|qualification)\b",
    "skills": r"\b(skills?|technical skills|technologies)\b",
}


def extract_requirements(description: str) -> dict:
    if not llm_ready() or not (description or "").strip():
        return {"required_skills": [], "preferred_skills": [], "keywords": []}
    out = chat(KEYWORD_SYSTEM, (description or "")[:6000], json_mode=True,
               kind="ats-keywords")
    return {
        "required_skills": [str(x) for x in out.get("required_skills") or []],
        "preferred_skills": [str(x) for x in out.get("preferred_skills") or []],
        "keywords": [str(x) for x in out.get("keywords") or []],
    }


def _present(term: str, text: str) -> bool:
    t = term.strip().lower()
    if not t:
        return False
    return re.search(r"(?<!\w)" + re.escape(t) + r"(?!\w)", text) is not None


def score_resume(resume_text: str, description: str,
                 reqs: dict | None = None) -> dict:
    """Return overall + sub scores (0-100) and the missing keywords."""
    text = (resume_text or "").lower()
    reqs = reqs if reqs is not None else extract_requirements(description)

    all_terms = (reqs["required_skills"] + reqs["preferred_skills"]
                 + reqs["keywords"])
    seen, terms = set(), []
    for t in all_terms:
        k = t.strip().lower()
        if k and k not in seen:
            seen.add(k)
            terms.append(t)

    matched = [t for t in terms if _present(t, text)]
    missing = [t for t in terms if t not in matched]
    keyword_score = (100.0 * len(matched) / len(terms)) if terms else 0.0

    skills = reqs["required_skills"] or terms
    skills_hit = [s for s in skills if _present(s, text)]
    skills_score = (100.0 * len(skills_hit) / len(skills)) if skills else 0.0

    have = sum(1 for pat in SECTIONS.values() if re.search(pat, text))
    section_score = 100.0 * have / len(SECTIONS)

    overall = 0.55 * keyword_score + 0.25 * skills_score + 0.20 * section_score
    # Required skills the resume is missing matter most - surface them first.
    required_missing = [m for m in missing if m in reqs["required_skills"]]
    other_missing = [m for m in missing if m not in reqs["required_skills"]]
    return {
        "overall": round(overall, 1),
        "keyword": round(keyword_score, 1),
        "skills": round(skills_score, 1),
        "sections": round(section_score, 1),
        "missing": (required_missing + other_missing)[:12],
        "matched_count": len(matched),
        "term_count": len(terms),
    }


def score_and_store(session, resume_version, resume_text: str,
                    description: str, reqs: dict | None = None) -> dict:
    res = score_resume(resume_text, description, reqs)
    resume_version.ats_score = res["overall"]
    resume_version.ats_keyword = res["keyword"]
    resume_version.ats_skills = res["skills"]
    resume_version.ats_sections = res["sections"]
    resume_version.missing_keywords = json.dumps(res["missing"])
    session.commit()
    return res
