"""Cryptographic compliance badge: an HMAC-SHA256 signed token binding a submission id, the exact approved
content hash, score and timestamp. Anyone can verify it via /api/verify, and any later edit invalidates it."""
import base64
import hashlib
import hmac
import json

from backend import config


def content_hash(text, image_path=None):
    h = hashlib.sha256((text or "").encode("utf-8"))
    if image_path:
        with open(image_path, "rb") as f:
            h.update(f.read())
    return h.hexdigest()


def _sig(payload_b64):
    return hmac.new(config.SECRET_KEY.encode(), payload_b64.encode(), hashlib.sha256).hexdigest()[:40]


def issue(sub_id, text, image_path, score, approved_at, approvers):
    payload = {"sid": sub_id, "h": content_hash(text, image_path)[:32], "sc": score, "at": approved_at, "by": approvers}
    b64 = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    return f"BG1.{b64}.{_sig(b64)}"


def verify(token, current_text=None, image_path=None):
    try:
        prefix, b64, sig = token.strip().split(".")
        if prefix != "BG1" or not hmac.compare_digest(sig, _sig(b64)):
            return {"valid": False, "reason": "Signature mismatch — token is forged or altered."}
        payload = json.loads(base64.urlsafe_b64decode(b64 + "=" * (-len(b64) % 4)))
    except Exception:
        return {"valid": False, "reason": "Malformed token."}
    out = {"valid": True, "payload": payload}
    if current_text is not None:
        same = content_hash(current_text, image_path)[:32] == payload["h"]
        out["content_unchanged"] = same
        if not same:
            out["valid"], out["reason"] = False, "Content was modified after approval."
    return out
