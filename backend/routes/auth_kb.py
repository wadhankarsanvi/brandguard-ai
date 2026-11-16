"""Auth, knowledge base (Stage 1: ingestion), rules/settings, analytics, audit, badge verification."""
import json
import uuid
from pathlib import Path

from flask import Blueprint, g, jsonify, request, send_from_directory
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from backend import config, db
from backend.common import (
    ApiError,
    audit,
    check_login_rate_limit,
    make_token,
    now,
    record_failed_login,
    record_successful_login,
    require_auth,
    validate_magic_bytes,
)
from backend.services import analytics, badge, pipeline, rag

bp = Blueprint("core", __name__, url_prefix="/api")


@bp.get("/health")
def health():
    return {"status": "ok"}


# ------------------------------------------------------------------ auth
@bp.post("/auth/login")
def login():
    d = request.get_json(silent=True) or {}
    email = (d.get("email") or "").strip().lower()
    check_login_rate_limit(email)
    u = db.query("SELECT * FROM users WHERE email=?", (email,), one=True)
    if not u or not check_password_hash(u["password_hash"], d.get("password") or ""):
        record_failed_login(email)
        raise ApiError("Invalid email or password", 401)
    record_successful_login(email)
    audit(u, "auth.login")
    return {"token": make_token(u), "user": {k: u[k] for k in ("id", "email", "name", "role", "team")}}


@bp.post("/auth/register")
def register():
    if not getattr(config, "ALLOW_REGISTRATION", True):
        raise ApiError("Self-registration is disabled", 403)
    d = request.get_json(silent=True) or {}
    email = (d.get("email") or "").strip().lower()
    name = (d.get("name") or "").strip()
    password = d.get("password") or ""
    role = d.get("role", "creator")
    team = (d.get("team") or "Marketing").strip()
    if role not in ("creator", "manager", "legal"):
        role = "creator"
    if not email or "@" not in email:
        raise ApiError("Valid email required", 400)
    if not name:
        raise ApiError("Name required", 400)
    if len(password) < 6:
        raise ApiError("Password must be at least 6 characters", 400)
    if db.query("SELECT id FROM users WHERE email=?", (email,), one=True):
        raise ApiError("User with this email already exists", 400)
    uid = db.execute(
        "INSERT INTO users(email,name,role,team,password_hash) VALUES(?,?,?,?,?)",
        (email, name, role, team, generate_password_hash(password))
    )
    user = {"id": uid, "email": email, "name": name, "role": role, "team": team}
    audit(user, "auth.register")
    return {"token": make_token(user), "user": user}, 201


@bp.post("/auth/change-password")
@require_auth()
def change_password():
    d = request.get_json(silent=True) or {}
    cur_pw = d.get("current_password") or d.get("old_password") or ""
    new_pw = d.get("new_password") or ""
    if not cur_pw or not new_pw:
        raise ApiError("Current and new passwords are required", 400)
    u = db.query("SELECT * FROM users WHERE id=?", (g.user["id"],), one=True)
    if not u or not check_password_hash(u["password_hash"], cur_pw):
        raise ApiError("Current password is incorrect", 400)
    if len(new_pw) < 6:
        raise ApiError("New password must be at least 6 characters", 400)
    new_hash = generate_password_hash(new_pw)
    db.execute("UPDATE users SET password_hash=? WHERE id=?", (new_hash, g.user["id"]))
    audit(g.user, "auth.password_changed")
    return {"ok": True}


@bp.get("/auth/me")
@require_auth()
def me():
    return g.user


# ------------------------------------------------------------------ notifications
@bp.get("/notifications")
@require_auth()
def get_notifications():
    items = db.query(
        "SELECT * FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT 50",
        (g.user["id"],)
    )
    unread = db.query(
        "SELECT COUNT(*) n FROM notifications WHERE user_id=? AND read=0",
        (g.user["id"],),
        one=True
    )["n"]
    return jsonify({"notifications": items, "unread": unread})


@bp.post("/notifications/read-all")
@require_auth()
def read_all_notifications():
    db.execute("UPDATE notifications SET read=1 WHERE user_id=?", (g.user["id"],))
    return {"ok": True}


# ------------------------------------------------------------------ knowledge base
@bp.get("/kb/documents")
@require_auth()
def kb_list():
    return jsonify(db.query(
        "SELECT d.*, (SELECT COUNT(*) FROM chunks c WHERE c.document_id=d.id) chunks FROM documents d ORDER BY d.id DESC"))


@bp.post("/kb/documents")
@require_auth("manager", "legal")
def kb_add():
    title = (request.form.get("title") or "").strip()
    doc_type = request.form.get("doc_type") or "guideline"
    text, filename = request.form.get("text") or "", None
    f = request.files.get("file")
    if f and f.filename:
        filename = secure_filename(f.filename)
        tmp = config.UPLOAD_DIR / f"kb_{uuid.uuid4().hex}_{filename}"
        f.save(tmp)
        try:
            validate_magic_bytes(tmp)
            text = pipeline.extract_file_text(tmp, filename)
        except (ValueError, ApiError) as e:
            tmp.unlink(missing_ok=True)
            raise ApiError(e.message if isinstance(e, ApiError) else str(e))
        finally:
            tmp.unlink(missing_ok=True)
    if not text.strip():
        raise ApiError("Provide a file or paste some text")
    title = title or filename or "Untitled document"
    doc_id = rag.add_document(title, text, doc_type, filename, g.user["id"])
    audit(g.user, "kb.ingested", "document", doc_id, title)
    n = db.query("SELECT COUNT(*) n FROM chunks WHERE document_id=?", (doc_id,), one=True)["n"]
    return {"id": doc_id, "chunks": n}, 201


@bp.delete("/kb/documents/<int:doc_id>")
@require_auth("manager", "legal")
def kb_delete(doc_id):
    db.execute("DELETE FROM chunks WHERE document_id=?", (doc_id,))
    db.execute("DELETE FROM documents WHERE id=?", (doc_id,))
    audit(g.user, "kb.deleted", "document", doc_id)
    return {"ok": True}


@bp.get("/kb/search")
@require_auth()
def kb_search():
    return jsonify(rag.search(request.args.get("q", ""), k=int(request.args.get("k", 4))))


@bp.get("/kb/logos")
@require_auth()
def kb_logos():
    config.LOGO_DIR.mkdir(parents=True, exist_ok=True)
    logos = []
    for p in sorted(config.LOGO_DIR.iterdir()):
        if p.is_file() and p.suffix.lower() in (".png", ".jpg", ".jpeg"):
            logos.append({
                "name": p.name,
                "filename": p.name,
                "url": f"/api/kb/logos/{p.name}"
            })
    return jsonify(logos)


@bp.get("/kb/logos/<name>")
def kb_logo_get(name):
    filename = secure_filename(name)
    return send_from_directory(config.LOGO_DIR, filename)


@bp.delete("/kb/logos/<name>")
@require_auth("manager")
def kb_logo_delete(name):
    filename = secure_filename(name)
    target = config.LOGO_DIR / filename
    if not target.exists() or not target.is_file():
        raise ApiError("Logo not found", 404)
    target.unlink(missing_ok=True)
    audit(g.user, "kb.logo_deleted", "logo", None, filename)
    return {"ok": True}


@bp.post("/kb/logo")
@bp.post("/kb/logos")
@require_auth("manager")
def kb_logo():
    f = request.files.get("file")
    if not f or Path(f.filename or "").suffix.lower() not in (".png", ".jpg", ".jpeg"):
        raise ApiError("Upload a PNG or JPEG logo")
    config.LOGO_DIR.mkdir(parents=True, exist_ok=True)
    dest = config.LOGO_DIR / secure_filename(f.filename)
    f.save(dest)
    try:
        validate_magic_bytes(dest)
    except ApiError:
        dest.unlink(missing_ok=True)
        raise
    audit(g.user, "kb.logo_uploaded", "logo", None, f.filename)
    return {"ok": True, "name": dest.name, "url": f"/api/kb/logos/{dest.name}"}, 201


# ------------------------------------------------------------------ rules & settings
@bp.get("/rules")
@require_auth()
def rules_list():
    return jsonify(db.query("SELECT * FROM rules ORDER BY category, id"))


@bp.post("/rules")
@require_auth("manager")
def rules_add():
    d = request.get_json(force=True)
    for k in ("key", "name", "category", "kind", "pattern"):
        if not d.get(k):
            raise ApiError(f"Missing field: {k}")
    if d["kind"] not in ("term", "exclaim", "caps", "claim", "disclaimer"):
        raise ApiError("Unknown rule kind")
    try:
        rid = db.execute(
            "INSERT INTO rules(key,name,category,kind,pattern,preferred,severity,description,source,case_sensitive,active) VALUES(?,?,?,?,?,?,?,?,?,?,1)",
            (d["key"], d["name"], d["category"], d["kind"], d["pattern"], d.get("preferred", ""), d.get("severity", "medium"),
             d.get("description", ""), d.get("source", ""), int(bool(d.get("case_sensitive")))))
    except Exception:
        raise ApiError("A rule with this key already exists")
    try:
        db.execute(
            "INSERT INTO rule_versions(rule_id,version,pattern,preferred,severity,description,active,changed_by,change_reason,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (rid, 1, d["pattern"], d.get("preferred", ""), d.get("severity", "medium"), d.get("description", ""), 1, g.user["id"], "Initial rule creation", now())
        )
    except Exception:
        pass
    audit(g.user, "rule.created", "rule", rid, d["key"])
    return {"id": rid}, 201


@bp.put("/rules/<int:rid>")
@require_auth("manager")
def rules_update(rid):
    cur_rule = db.query("SELECT * FROM rules WHERE id=?", (rid,), one=True)
    if not cur_rule:
        raise ApiError("Rule not found", 404)
    d = request.get_json(force=True)
    allowed = ("name", "pattern", "preferred", "severity", "description", "source", "active", "category")
    sets = [(k, d[k]) for k in allowed if k in d]
    if not sets:
        raise ApiError("Nothing to update")
    db.execute(f"UPDATE rules SET {', '.join(k + '=?' for k, _ in sets)} WHERE id=?", [v for _, v in sets] + [rid])
    
    # Record version snapshot
    try:
        v_row = db.query("SELECT COALESCE(MAX(version),0) m FROM rule_versions WHERE rule_id=?", (rid,), one=True)
        next_ver = (v_row["m"] if v_row else 0) + 1
        updated = db.query("SELECT * FROM rules WHERE id=?", (rid,), one=True)
        db.execute(
            "INSERT INTO rule_versions(rule_id,version,pattern,preferred,severity,description,active,changed_by,change_reason,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (rid, next_ver, updated["pattern"], updated.get("preferred", ""), updated.get("severity", "medium"),
             updated.get("description", ""), updated.get("active", 1), g.user["id"], d.get("reason", "Rule updated"), now())
        )
    except Exception:
        pass
    audit(g.user, "rule.updated", "rule", rid, json.dumps(dict(sets)))
    return {"ok": True}


@bp.get("/rules/<int:rid>/versions")
@require_auth("manager")
def rules_versions(rid):
    versions = db.query(
        "SELECT rv.*, u.name as author_name FROM rule_versions rv LEFT JOIN users u ON u.id=rv.changed_by WHERE rv.rule_id=? ORDER BY rv.version DESC",
        (rid,)
    )
    return jsonify(versions)


@bp.post("/rules/<int:rid>/rollback/<int:ver>")
@require_auth("manager")
def rules_rollback(rid, ver):
    target = db.query("SELECT * FROM rule_versions WHERE rule_id=? AND version=?", (rid, ver), one=True)
    if not target:
        raise ApiError("Rule version not found", 404)
    db.execute(
        "UPDATE rules SET pattern=?, preferred=?, severity=?, description=?, active=? WHERE id=?",
        (target["pattern"], target["preferred"], target["severity"], target["description"], target["active"], rid)
    )
    v_row = db.query("SELECT COALESCE(MAX(version), 0) m FROM rule_versions WHERE rule_id=?", (rid,), one=True)
    next_ver = (v_row["m"] if v_row else 0) + 1
    db.execute(
        "INSERT INTO rule_versions(rule_id,version,pattern,preferred,severity,description,active,changed_by,change_reason,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (rid, next_ver, target["pattern"], target["preferred"], target["severity"], target["description"], target["active"], g.user["id"], f"Rollback to v{ver}", now())
    )
    audit(g.user, "rule.rollback", "rule", rid, f"Rolled back to v{ver}")
    return {"ok": True, "rolled_back_to": ver, "new_version": next_ver}


@bp.delete("/rules/<int:rid>")
@require_auth("manager")
def rules_delete(rid):
    db.execute("DELETE FROM rules WHERE id=?", (rid,))
    audit(g.user, "rule.deleted", "rule", rid)
    return {"ok": True}


@bp.get("/settings")
@require_auth()
def settings_get():
    return pipeline.get_settings()


@bp.put("/settings")
@require_auth("manager")
def settings_put():
    d = request.get_json(force=True)
    for k, v in d.items():
        if k in ("palette", "min_contrast", "min_width"):
            db.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                       (k, json.dumps(v) if k == "palette" else str(v)))
    audit(g.user, "settings.updated", "settings", None, ", ".join(d.keys()))
    return pipeline.get_settings()


# ------------------------------------------------------------------ analytics / audit / verify
@bp.get("/analytics")
@require_auth()
def analytics_get():
    return analytics.build(g.user)


@bp.get("/audit")
@require_auth("manager", "legal")
def audit_get():
    return jsonify(db.query("SELECT * FROM audit ORDER BY id DESC LIMIT 200"))


@bp.get("/verify")
def verify():
    """Public endpoint: verify a compliance badge and (if the item is known) that its content is unchanged."""
    token = request.args.get("token", "")
    res = badge.verify(token)
    if res.get("valid"):
        sub = db.query("SELECT id,title,content_text,image_path,status FROM submissions WHERE id=?", (res["payload"]["sid"],), one=True)
        if sub:
            res = badge.verify(token, sub["content_text"], sub["image_path"])
            res["title"] = sub["title"]
    return res
