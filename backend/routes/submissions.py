"""Submissions: create/analyse, fix, comment, review, diff."""
import difflib
import json
import re
import uuid
from pathlib import Path

from flask import Blueprint, g, jsonify, request, send_file
from werkzeug.utils import secure_filename

from backend import config, db
from backend.common import ApiError, audit, now, require_auth, validate_magic_bytes
from backend.services import pipeline, workflow

bp = Blueprint("submissions", __name__, url_prefix="/api/submissions")
IMG_EXT = (".png", ".jpg", ".jpeg")


def _load(sub_id, edit=False):
    s = db.query("SELECT s.*, u.name creator_name FROM submissions s JOIN users u ON u.id=s.creator_id WHERE s.id=?", (sub_id,), one=True)
    if not s:
        raise ApiError("Submission not found", 404)
    if g.user["role"] == "creator" and s["creator_id"] != g.user["id"]:
        raise ApiError("You can only see your own submissions", 403)   # role-based data isolation
    if edit and g.user["role"] == "creator" and s["status"] not in workflow.EDITABLE:
        raise ApiError("Locked while in review or approved")
    return s


def _issue_row(i):
    i["citation"] = json.loads(i["citation"]) if i["citation"] else None
    i["bbox"] = json.loads(i["bbox"]) if i["bbox"] else None
    return i


def create_submission(user, title, text, upload, alt_text, team=None):
    kind, filename, image_path, page_map_data = "text", None, None, None
    if upload and upload.filename:
        filename = secure_filename(upload.filename)
        ext = Path(filename).suffix.lower()
        dest = config.UPLOAD_DIR / f"{uuid.uuid4().hex}_{filename}"
        upload.save(dest)
        try:
            validate_magic_bytes(dest)
        except ApiError:
            dest.unlink(missing_ok=True)
            raise
        if ext in IMG_EXT:
            kind, image_path = "image", str(dest)
            try:
                from backend.services.image_checker import load_rgb
                load_rgb(dest)
            except Exception:
                dest.unlink(missing_ok=True)
                raise ApiError("Could not read that image file")
        elif ext == ".pdf":
            try:
                from backend.services import pdf
                text, page_map = pipeline.extract_file_text(dest, filename, with_pages=True)
                p_prefix = f"pdf_{uuid.uuid4().hex}_"
                page_imgs = pdf.render_pages(dest, config.UPLOAD_DIR, prefix=p_prefix)
                for i, pm in enumerate(page_map):
                    if i < len(page_imgs):
                        pm["image"] = page_imgs[i]
                page_map_data = json.dumps(page_map)
            except ValueError as e:
                dest.unlink(missing_ok=True)
                raise ApiError(str(e))
            kind = "pdf"
            dest.unlink(missing_ok=True)
        else:
            try:
                text = pipeline.extract_file_text(dest, filename)
            except ValueError as e:
                dest.unlink(missing_ok=True)
                raise ApiError(str(e))
            kind = "text"
            dest.unlink(missing_ok=True)
    if kind != "image" and not (text or "").strip():
        raise ApiError("Paste some content or upload a file")
    sid = db.execute(
        "INSERT INTO submissions(title,kind,content_text,filename,image_path,alt_text,creator_id,team,status,stage,current_version,page_map,created_at,updated_at)"
        " VALUES(?,?,?,?,?,?,?,?,'draft','creator',1,?,?,?)",
        (title or filename or "Untitled", kind, text or "", filename, image_path, alt_text or "", user["id"], team or user["team"], page_map_data, now(), now()))
    db.execute("INSERT INTO revisions(submission_id,version,content_text,author_id,note,created_at) VALUES(?,?,?,?,?,?)",
               (sid, 1, text or "", user["id"], "Initial submission", now()))
    audit(user, "submission.created", "submission", sid, f"{kind}: {title}")
    pipeline.run_analysis(sid, user, "initial")
    return sid


@bp.get("")
@require_auth()
def list_submissions():
    sql, args = "SELECT s.id,s.title,s.kind,s.status,s.stage,s.score,s.team,s.updated_at,s.requires_legal,u.name creator_name FROM submissions s JOIN users u ON u.id=s.creator_id WHERE 1=1", []
    if g.user["role"] == "creator":
        sql += " AND s.creator_id=?"; args.append(g.user["id"])
    if request.args.get("status"):
        sql += " AND s.status=?"; args.append(request.args["status"])
    if request.args.get("queue"):       # reviewer inbox
        sql += " AND s.status='in_review' AND s.stage=?"; args.append(g.user["role"])
    return jsonify(db.query(sql + " ORDER BY s.updated_at DESC, s.id DESC", args))


@bp.post("")
@require_auth()
def create():
    sid = create_submission(g.user, request.form.get("title", "").strip(), request.form.get("text", ""),
                            request.files.get("file"), request.form.get("alt_text", ""))
    return {"id": sid}, 201


@bp.get("/<int:sid>")
@require_auth()
def detail(sid):
    s = _load(sid)
    issues = [_issue_row(i) for i in db.query("SELECT * FROM issues WHERE submission_id=? AND version=? ORDER BY COALESCE(start,0), id", (sid, s["current_version"]))]
    page_map = json.loads(s.get("page_map") or "[]")
    if page_map:
        for i in issues:
            st = i.get("start")
            if st is not None:
                for pm in page_map:
                    if pm["start"] <= st <= pm["end"]:
                        i["page"] = pm["page"]
                        break
                else:
                    if st > page_map[-1]["end"]:
                        i["page"] = page_map[-1]["page"]
                    elif st < page_map[0]["start"]:
                        i["page"] = page_map[0]["page"]
    s["page_map"] = page_map
    pdf_pages = []
    for pm in page_map:
        if pm.get("image"):
            pdf_pages.append(f"/api/submissions/{sid}/pages/{pm['page']}")
    s["pdf_pages"] = pdf_pages
    s["image_url"] = f"/api/submissions/{sid}/image" if s["image_path"] else None
    s.pop("image_path", None)
    extra = pipeline.extras(sid)
    return {
        "submission": s, "issues": issues,
        "revisions": db.query("SELECT r.id,r.version,r.note,r.created_at,u.name author FROM revisions r LEFT JOIN users u ON u.id=r.author_id WHERE submission_id=? ORDER BY version DESC", (sid,)),
        "comments": db.query("SELECT c.*,u.name author,u.role author_role FROM comments c JOIN users u ON u.id=c.author_id WHERE submission_id=? ORDER BY c.id", (sid,)),
        "approvals": db.query("SELECT a.*,u.name reviewer FROM approvals a JOIN users u ON u.id=a.reviewer_id WHERE submission_id=? ORDER BY a.id", (sid,)),
        "audit": db.query("SELECT * FROM audit WHERE entity='submission' AND entity_id=? ORDER BY id DESC LIMIT 50", (sid,)),
        **extra,
    }


@bp.get("/<int:sid>/pages/<int:page_num>")
@require_auth()
def page_image(sid, page_num):
    s = _load(sid)
    page_map = json.loads(s.get("page_map") or "[]")
    target = next((pm for pm in page_map if pm["page"] == page_num), None)
    if not target or not target.get("image"):
        raise ApiError("Page image not found", 404)
    img_path = config.UPLOAD_DIR / target["image"]
    if not img_path.exists():
        raise ApiError("Page image file missing", 404)
    return send_file(img_path)


@bp.get("/<int:sid>/image")
@require_auth()
def image(sid):
    s = _load(sid)
    if not s["image_path"]:
        raise ApiError("No image", 404)
    return send_file(s["image_path"])


@bp.post("/<int:sid>/analyze")
@require_auth()
def reanalyze(sid):
    _load(sid)
    pipeline.run_analysis(sid, g.user, "manual")
    return {"ok": True}


@bp.put("/<int:sid>/content")
@require_auth()
def edit_content(sid):
    s = _load(sid, edit=True)
    d = request.get_json(force=True)
    if "alt_text" in d:
        db.execute("UPDATE submissions SET alt_text=? WHERE id=?", (d["alt_text"], sid))
    if "text" in d and d["text"] != s["content_text"]:
        workflow.add_revision(s, d["text"], g.user, d.get("note") or "Manual edit")
    if s["status"] == "approved":
        db.execute("UPDATE submissions SET status='analyzed', stage='creator' WHERE id=?", (sid,))
    pipeline.run_analysis(sid, g.user, "edit")
    return {"ok": True}


@bp.post("/<int:sid>/issues/<int:iid>/apply")
@require_auth()
def apply_fix(sid, iid):
    s = _load(sid, edit=True)
    i = db.query("SELECT * FROM issues WHERE id=? AND submission_id=?", (iid, sid), one=True)
    if not i or i["suggestion"] is None or i["start"] is None:
        raise ApiError("This issue has no automatic fix")
    if i["version"] != s["current_version"]:
        raise ApiError("This issue belongs to an older version")
    text = s["content_text"]
    new = text[: i["start"]] + i["suggestion"] + text[i["end"]:]
    db.execute("UPDATE issues SET status='fixed' WHERE id=?", (iid,))
    workflow.add_revision(s, new, g.user, f"Applied fix: {i['rule_key']}")
    audit(g.user, "issue.fix_applied", "submission", sid, i["rule_key"])
    pipeline.run_analysis(sid, g.user, "fix")
    return {"ok": True}


@bp.post("/<int:sid>/issues/<int:iid>/dismiss")
@require_auth()
def dismiss(sid, iid):
    _load(sid, edit=True)
    reason = (request.get_json(silent=True) or {}).get("reason", "")
    db.execute("UPDATE issues SET status='dismissed' WHERE id=? AND submission_id=?", (iid, sid))
    audit(g.user, "issue.dismissed", "submission", sid, f"#{iid} {reason}")
    pipeline.run_analysis(sid, g.user, "dismiss")
    return {"ok": True}


@bp.post("/<int:sid>/issues/<int:iid>/reopen")
@require_auth()
def reopen(sid, iid):
    _load(sid, edit=True)
    db.execute("UPDATE issues SET status='open' WHERE id=? AND submission_id=? AND status='dismissed'", (iid, sid))
    pipeline.rescore(sid)
    return {"ok": True}


@bp.post("/<int:sid>/apply-all")
@require_auth()
def apply_all(sid):
    s = _load(sid, edit=True)
    rw = pipeline.build_rewrite(sid)
    if rw["rewrite"] == s["content_text"]:
        raise ApiError("Nothing to rewrite automatically")
    workflow.add_revision(s, rw["rewrite"], g.user, f"Applied all suggestions ({rw['mode']})")
    audit(g.user, "rewrite.applied", "submission", sid, rw["mode"])
    pipeline.run_analysis(sid, g.user, "rewrite")
    return {"ok": True, "mode": rw["mode"]}


@bp.get("/<int:sid>/rewrite")
@require_auth()
def preview_rewrite(sid):
    _load(sid)
    return pipeline.build_rewrite(sid)


@bp.get("/<int:sid>/diff")
@require_auth()
def diff(sid):
    _load(sid)
    a, b = int(request.args.get("from", 1)), int(request.args.get("to", 0))
    revs = {r["version"]: r["content_text"] or "" for r in db.query("SELECT version,content_text FROM revisions WHERE submission_id=?", (sid,))}
    b = b or max(revs)
    if a not in revs or b not in revs:
        raise ApiError("Unknown version", 404)
    ta, tb = re.findall(r"\s+|\S+", revs[a]), re.findall(r"\s+|\S+", revs[b])
    ops = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, ta, tb, autojunk=False).get_opcodes():
        ops.append({"op": tag, "a": "".join(ta[i1:i2]), "b": "".join(tb[j1:j2])})
    return {"from": a, "to": b, "ops": ops}


@bp.post("/<int:sid>/comments")
@require_auth()
def add_comment(sid):
    _load(sid)
    d = request.get_json(force=True)
    body = (d.get("body") or "").strip()
    if not body:
        raise ApiError("Comment is empty")
    cid = db.execute("INSERT INTO comments(submission_id,issue_id,parent_id,author_id,body,created_at) VALUES(?,?,?,?,?,?)",
                     (sid, d.get("issue_id"), d.get("parent_id"), g.user["id"], body, now()))
    audit(g.user, "comment.added", "submission", sid, body[:80])
    return {"id": cid}, 201


@bp.post("/<int:sid>/submit-review")
@require_auth("creator")
def submit_review(sid):
    s = _load(sid)
    workflow.submit_for_review(s, g.user)
    return {"ok": True}


@bp.post("/<int:sid>/review")
@require_auth("manager", "legal")
def review(sid):
    s = _load(sid)
    d = request.get_json(force=True)
    workflow.decide(s, g.user, d.get("decision"), d.get("note", ""))
    return {"ok": True}
