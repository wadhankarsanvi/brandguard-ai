"""Shared helpers: errors, auth, timestamps, audit trail."""
import datetime as dt
import functools
import os
import re
import smtplib
import time
from email.message import EmailMessage
from pathlib import Path
import jwt
from flask import g, request
from backend import config, db

_FAILED_LOGINS = {}
RATE_LIMIT_WINDOW = 15 * 60  # 15 minutes
MAX_FAILED_ATTEMPTS = 5


def check_login_rate_limit(email: str):
    if not email:
        return
    now_t = time.time()
    attempts = [t for t in _FAILED_LOGINS.get(email, []) if now_t - t < RATE_LIMIT_WINDOW]
    _FAILED_LOGINS[email] = attempts
    if len(attempts) >= MAX_FAILED_ATTEMPTS:
        raise ApiError("Too many failed login attempts. Please try again in 15 minutes.", 429)


def record_failed_login(email: str):
    if not email:
        return
    now_t = time.time()
    attempts = [t for t in _FAILED_LOGINS.get(email, []) if now_t - t < RATE_LIMIT_WINDOW]
    attempts.append(now_t)
    _FAILED_LOGINS[email] = attempts


def record_successful_login(email: str):
    _FAILED_LOGINS.pop(email, None)


def reset_login_rate_limits():
    _FAILED_LOGINS.clear()


def validate_magic_bytes(file_path):
    p = Path(file_path)
    ext = p.suffix.lower()
    if ext not in (".png", ".jpg", ".jpeg", ".pdf"):
        return
    with open(p, "rb") as f:
        header = f.read(16)
    if ext == ".png" and not header.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ApiError("Invalid file content: not a valid PNG image", 400)
    if ext in (".jpg", ".jpeg") and not header.startswith(b"\xff\xd8\xff"):
        raise ApiError("Invalid file content: not a valid JPEG image", 400)
    if ext == ".pdf" and not header.startswith(b"%PDF"):
        raise ApiError("Invalid file content: not a valid PDF document", 400)


class ApiError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message, self.status = message, status


def now():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def make_token(user):
    exp = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=config.TOKEN_TTL_HOURS)
    return jwt.encode({"sub": str(user["id"]), "role": user["role"], "exp": exp}, config.SECRET_KEY, algorithm="HS256")


def require_auth(*roles):
    """Decorator: valid JWT required; optionally restrict to roles."""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*a, **kw):
            header = request.headers.get("Authorization", "")
            token = header[7:] if header.startswith("Bearer ") else request.args.get("token_auth", "")
            if not token:
                raise ApiError("Authentication required", 401)
            try:
                data = jwt.decode(token, config.SECRET_KEY, algorithms=["HS256"])
            except jwt.PyJWTError:
                raise ApiError("Session expired, please sign in again", 401)
            user = db.query("SELECT id,email,name,role,team FROM users WHERE id=?", (int(data["sub"]),), one=True)
            if not user:
                raise ApiError("Unknown user", 401)
            if roles and user["role"] not in roles:
                raise ApiError("Your role is not allowed to do this", 403)
            g.user = user
            return fn(*a, **kw)
        return wrapper
    return deco


def audit(user, action, entity=None, entity_id=None, detail=""):
    db.execute(
        "INSERT INTO audit(ts,actor_id,actor_name,action,entity,entity_id,detail) VALUES(?,?,?,?,?,?,?)",
        (now(), user["id"] if user else None, user["name"] if user else "system", action, entity, entity_id, detail),
    )


def send_email_notification(to_email, subject, body):
    """Optional email: if env SMTP_HOST is set, also send mail using smtplib; otherwise skip silently."""
    smtp_host = os.getenv("SMTP_HOST")
    if not smtp_host:
        return
    smtp_port = int(os.getenv("SMTP_PORT", "25"))
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASS")
    sender = os.getenv("SMTP_FROM", "no-reply@brandguard.ai")
    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = sender
        msg["To"] = to_email
        msg.set_content(body)
        with smtplib.SMTP(smtp_host, smtp_port, timeout=5) as server:
            if smtp_user and smtp_pass:
                server.login(smtp_user, smtp_pass)
            server.send_message(msg)
    except Exception:
        pass


def create_notification(user_id, submission_id, message):
    """Create in-app notification and optionally send email."""
    nid = db.execute(
        "INSERT INTO notifications(user_id,submission_id,message,read,created_at) VALUES(?,?,?,0,?)",
        (user_id, submission_id, message, now()),
    )
    u = db.query("SELECT email FROM users WHERE id=?", (user_id,), one=True)
    if u and u.get("email"):
        send_email_notification(u["email"], "BrandGuard Notification", message)
    return nid


def handle_comment_mentions(sub_id, author_id, comment_body):
    """Scan comment body for @name mentions and notify mentioned users."""
    if not comment_body or "@" not in comment_body:
        return
    author = db.query("SELECT name FROM users WHERE id=?", (author_id,), one=True)
    author_name = author["name"] if author else "Someone"
    all_users = db.query("SELECT id, name, email FROM users WHERE id != ?", (author_id,))
    for u in all_users:
        first_name = u["name"].split()[0] if u["name"] else ""
        username = u["email"].split("@")[0] if u["email"] else ""
        pat = rf"@({re.escape(u['name'])}\b|{re.escape(first_name)}\b|{re.escape(username)}\b)"
        if re.search(pat, comment_body, re.IGNORECASE):
            msg = f"{author_name} mentioned you in a comment: \"{comment_body[:80]}\""
            create_notification(u["id"], sub_id, msg)
