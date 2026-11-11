"""Optional LLM / VLM layer (Anthropic Messages API over plain HTTP).

Design rule: the LLM is *never* the source of truth. Claims are verified against retrieved evidence by the
RAG engine; the LLM only (a) rewrites text under semantic constraints and (b) gives a second opinion on image
vs. text claims. If no key is configured, or a call fails, every function returns None and the caller falls back
to the deterministic path. PII is masked before any text leaves the server (local-first privacy shield).
"""
import base64
import json
import re

import requests

from backend import config

API = "https://api.anthropic.com/v1/messages"


def enabled():
    return bool(config.ANTHROPIC_API_KEY)


def _call(content, system, max_tokens=900):
    r = requests.post(
        API,
        headers={"x-api-key": config.ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": config.ANTHROPIC_MODEL, "max_tokens": max_tokens, "system": system,
              "messages": [{"role": "user", "content": content}]},
        timeout=45,
    )
    r.raise_for_status()
    return "".join(b.get("text", "") for b in r.json().get("content", []))


def rewrite(text, problems, evidence):
    """Intent-preserving rewrite: fix only the listed problems, keep author's tone, facts and structure."""
    if not enabled():
        return None
    system = ("You are a brand-compliance editor. Rewrite the draft so it fixes ONLY the listed problems. "
              "Preserve the author's intent, voice, structure, facts and length. Never invent facts: use only the "
              "provided evidence for claims. If a claim cannot be supported, soften or remove that claim. "
              "Return only the rewritten text.")
    prompt = (f"DRAFT:\n{text}\n\nPROBLEMS:\n" + "\n".join(f"- {p}" for p in problems) +
              "\n\nEVIDENCE FROM APPROVED SOURCES:\n" + "\n".join(f"- {e}" for e in evidence))
    try:
        return _call(prompt, system).strip() or None
    except Exception:
        return None


def verify_image_claims(image_path, claims):
    """Vision second-opinion: do the text claims match what is visible in the image?"""
    if not enabled() or not claims:
        return None
    try:
        data = base64.b64encode(open(image_path, "rb").read()).decode()
        ext = str(image_path).lower().rsplit(".", 1)[-1]
        media = "image/png" if ext == "png" else "image/jpeg"
        content = [
            {"type": "image", "source": {"type": "base64", "media_type": media, "data": data}},
            {"type": "text", "text": "For each claim, say whether the image visibly supports it. Reply ONLY with JSON: "
             '[{"claim": "...", "supported": true|false, "reason": "..."}]\nClaims:\n' + "\n".join(f"- {c}" for c in claims)},
        ]
        out = _call(content, "You verify marketing claims against images. Be conservative.")
        m = re.search(r"\[.*\]", out, re.S)
        return json.loads(m.group(0)) if m else None
    except Exception:
        return None
