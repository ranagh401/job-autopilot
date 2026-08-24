"""Thin wrapper around Azure OpenAI (or plain OpenAI as fallback).

No temperature / max_tokens are passed so the same code works with GPT-4o
and GPT-5.x reasoning deployments alike.
"""
from __future__ import annotations

import json
import os
import re


def _get_client():
    if os.getenv("AZURE_OPENAI_API_KEY") and os.getenv("AZURE_OPENAI_ENDPOINT"):
        from openai import AzureOpenAI
        client = AzureOpenAI(
            api_key=os.getenv("AZURE_OPENAI_API_KEY"),
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01-preview"),
        )
        return client, os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
    if os.getenv("OPENAI_API_KEY"):
        from openai import OpenAI
        return OpenAI(), os.getenv("OPENAI_MODEL", "gpt-4o")
    return None, None


def llm_ready() -> bool:
    client, _ = _get_client()
    return client is not None


def _parse_json(text: str) -> dict:
    text = text.strip()
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        text = m.group(0)
    return json.loads(text)


def _record(kind: str, model: str, usage) -> None:
    """Store what a call cost. Never let bookkeeping break the call."""
    if usage is None:
        return
    try:
        from .db import LlmUsage, SessionLocal
        s = SessionLocal()
        try:
            s.add(LlmUsage(
                kind=kind[:40], model=(model or "")[:60],
                prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                completion_tokens=getattr(usage, "completion_tokens", 0) or 0))
            s.commit()
        finally:
            s.close()
    except Exception:
        pass


def chat(system: str, user: str, json_mode: bool = True, kind: str = ""):
    client, model = _get_client()
    if client is None:
        raise RuntimeError(
            "No LLM configured. Fill AZURE_OPENAI_* (or OPENAI_API_KEY) in .env")
    kwargs = {}
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}],
        **kwargs,
    )
    _record(kind, model, getattr(resp, "usage", None))
    text = resp.choices[0].message.content or ""
    return _parse_json(text) if json_mode else text
