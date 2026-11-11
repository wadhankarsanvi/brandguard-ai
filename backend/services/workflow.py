"""Stage 3 + 4: collaborative review state machine and publishing.

draft/analyzed --submit--> in_review(stage=manager) --approve--> [legal needed? stage=legal : approved]
legal --approve--> approved (cryptographic badge issued)
manager/legal --changes/reject--> changes_requested / rejected (back to creator, who edits & resubmits)
"""
from backend import db
from backend.common import ApiError, audit, create_notification, now
from backend.services import badge

EDITABLE = ("draft", "analyzed", "changes_requested", "rejected")


def add_revision(sub, text, user, note):
    ver = sub["current_version"] + 1
    db.execute("INSERT INTO revisions(submission_id,version,content_text,author_id,note,created_at) VALUES(?,?,?,?,?,?)",
               (sub["id"], ver, text, user["id"], note, now()))
    db.execute("UPDATE submissions SET content_text=?, current_version=?, updated_at=?, badge=NULL WHERE id=?", (text, ver, now(), sub["id"]))
    return ver


def open_critical(sub_id, version):
    return db.query("SELECT COUNT(*) n FROM issues WHERE submission_id=? AND version=? AND status='open' AND severity='critical'",
                    (sub_id, version), one=True)["n"]


def submit_for_review(sub, user):
    if sub["status"] not in EDITABLE:
        raise ApiError("This submission is already in review or approved")
    if open_critical(sub["id"], sub["current_version"]):
        raise ApiError("Resolve critical issues (e.g. personal data) before requesting review")
    db.execute("UPDATE submissions SET status='in_review', stage='manager', updated_at=? WHERE id=?", (now(), sub["id"]))
    audit(user, "review.submitted", "submission", sub["id"], f"score {sub['score']}")
    for m in db.query("SELECT id FROM users WHERE role='manager'"):
        create_notification(m["id"], sub["id"], f"Submission '{sub['title']}' is ready for manager review.")


def decide(sub, user, decision, note):
    if sub["status"] != "in_review":
        raise ApiError("Submission is not awaiting review")
    if user["role"] != sub["stage"]:
        raise ApiError(f"This item is waiting for a {sub['stage']} reviewer", 403)
    if decision not in ("approve", "changes", "reject"):
        raise ApiError("Unknown decision")
    if decision != "approve" and not (note or "").strip():
        raise ApiError("Please explain what needs to change")
    if decision == "approve" and open_critical(sub["id"], sub["current_version"]):
        raise ApiError("Cannot approve while critical issues are open")
    db.execute("INSERT INTO approvals(submission_id,stage,reviewer_id,decision,note,created_at) VALUES(?,?,?,?,?,?)",
               (sub["id"], sub["stage"], user["id"], decision, note, now()))
    if decision == "approve":
        if sub["stage"] == "manager" and sub["requires_legal"]:
            db.execute("UPDATE submissions SET stage='legal', updated_at=? WHERE id=?", (now(), sub["id"]))
            audit(user, "review.escalated_to_legal", "submission", sub["id"], note or "")
            for l in db.query("SELECT id FROM users WHERE role='legal'"):
                create_notification(l["id"], sub["id"], f"Submission '{sub['title']}' requires legal review.")
            create_notification(sub["creator_id"], sub["id"], f"{user['name']} approved '{sub['title']}' (escalated to Legal).")
        else:
            names = [r["name"] for r in db.query(
                "SELECT DISTINCT u.name FROM approvals a JOIN users u ON u.id=a.reviewer_id WHERE a.submission_id=? AND a.decision='approve'", (sub["id"],))]
            token = badge.issue(sub["id"], sub["content_text"], sub["image_path"], sub["score"], now(), names)
            db.execute("UPDATE submissions SET status='approved', stage='published', badge=?, updated_at=? WHERE id=?", (token, now(), sub["id"]))
            audit(user, "review.approved", "submission", sub["id"], "compliance badge issued")
            create_notification(sub["creator_id"], sub["id"], f"{user['name']} approved your submission '{sub['title']}'.")
            create_notification(sub["creator_id"], sub["id"], f"Compliance badge issued for '{sub['title']}'.")
    else:
        status = "changes_requested" if decision == "changes" else "rejected"
        db.execute("UPDATE submissions SET status=?, stage='creator', updated_at=? WHERE id=?", (status, now(), sub["id"]))
        audit(user, f"review.{status}", "submission", sub["id"], note or "")
        action_text = "requested changes on" if decision == "changes" else "rejected"
        create_notification(sub["creator_id"], sub["id"], f"{user['name']} {action_text} your submission '{sub['title']}': {note}")
