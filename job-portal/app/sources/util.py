"""Shared helpers for job sources."""
from __future__ import annotations

import requests
from bs4 import BeautifulSoup

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) personal-job-tracker"}

ROLE_WORDS = ["ai", "machine learning", "ml", "genai", "generative",
              "llm", "data scientist", "software engineer", "python", "nlp",
              "deep learning"]


def get(url: str, **kwargs):
    kwargs.setdefault("timeout", 30)
    kwargs.setdefault("headers", UA)
    return requests.get(url, **kwargs)


def strip_html(html: str) -> str:
    if not html:
        return ""
    return BeautifulSoup(html, "html.parser").get_text(" ", strip=True)


def title_matches(title: str) -> bool:
    t = (title or "").lower()
    return any(w in t for w in ROLE_WORDS)
