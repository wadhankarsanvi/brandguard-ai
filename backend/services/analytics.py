"""Stage 4 insights: brand health metrics and *bidirectional guideline feedback*.

A guideline is flagged as ambiguous when many different creators trip over it and a large share of the
flags are dismissed as wrong/irrelevant — a signal that the rule (not the creators) needs rewording.
"""
from backend import db


BUILTIN = {
    "pii-exposure": {"name": "Personal data exposed", "category": "privacy"}, "readability": {"name": "Readability", "category": "tone"},
    "img-alt-missing": {"name": "Missing alt text", "category": "accessibility"}, "img-alt-weak": {"name": "Weak alt text", "category": "accessibility"},
    "img-contrast": {"name": "Low text contrast (WCAG)", "category": "accessibility"}, "img-palette": {"name": "Off-palette colour", "category": "visual"},
    "img-resolution": {"name": "Low resolution", "category": "visual"}, "img-logo-clearspace": {"name": "Logo clear space", "category": "visual"},
    "mm-claim-mismatch": {"name": "Text/image claim mismatch", "category": "multimodal"},
}


def build(user):
    scope, args = ("", ()) if user["role"] != "creator" else (" WHERE s.creator_id=?", (user["id"],))
    subs = db.query(f"SELECT s.* FROM submissions s{scope}", args)
    ids = [s["id"] for s in subs] or [0]
    ph = ",".join("?" * len(ids))
    scored = [s["score"] for s in subs if s["score"] is not None]

    rules = {r["key"]: r for r in db.query("SELECT key,name,category FROM rules")}
    rows = db.query(
        f"""SELECT i.rule_key, COUNT(DISTINCT i.submission_id||'|'||COALESCE(i.match,'')) occ,
                   COUNT(DISTINCT s.creator_id) creators,
                   COUNT(DISTINCT CASE WHEN i.status='dismissed' THEN i.submission_id||'|'||COALESCE(i.match,'') END) dismissed
            FROM issues i JOIN submissions s ON s.id=i.submission_id WHERE i.submission_id IN ({ph}) GROUP BY i.rule_key""", ids)
    by_rule, ambiguous = [], []
    for r in rows:
        meta = rules.get(r["rule_key"]) or BUILTIN.get(r["rule_key"], {"name": r["rule_key"], "category": "other"})
        dismiss_rate = r["dismissed"] / r["occ"] if r["occ"] else 0
        amb = round(0.6 * dismiss_rate + 0.4 * min(1, r["creators"] / 3), 2)
        item = {"rule_key": r["rule_key"], "name": meta["name"], "category": meta["category"], "count": r["occ"],
                "creators": r["creators"], "dismissed": r["dismissed"], "ambiguity": amb}
        by_rule.append(item)
        if r["occ"] >= 3 and r["creators"] >= 2 and amb >= 0.5:
            ambiguous.append({**item, "hint": "Many creators hit this rule and a high share of flags are dismissed. "
                              "Clarify the wording or add examples to the guideline."})
    by_rule.sort(key=lambda x: -x["count"])
    ambiguous.sort(key=lambda x: -x["ambiguity"])

    teams = {}
    for s in subs:
        t = teams.setdefault(s["team"] or "Unassigned", {"team": s["team"] or "Unassigned", "submissions": 0, "scores": [], "approved": 0})
        t["submissions"] += 1
        t["approved"] += s["status"] == "approved"
        if s["score"] is not None:
            t["scores"].append(s["score"])
    team_rows = [{"team": t["team"], "submissions": t["submissions"], "approved": t["approved"],
                  "avg_score": round(sum(t["scores"]) / len(t["scores"]), 1) if t["scores"] else None} for t in teams.values()]

    cats = db.query(f"SELECT category, COUNT(*) n FROM issues WHERE submission_id IN ({ph}) AND version=1 GROUP BY category ORDER BY n DESC", ids)
    trend = db.query(f"SELECT substr(created_at,1,10) day, ROUND(AVG(score),1) avg_score, COUNT(*) n FROM submissions WHERE id IN ({ph}) AND score IS NOT NULL GROUP BY day ORDER BY day", ids)
    status = {}
    for s in subs:
        status[s["status"]] = status.get(s["status"], 0) + 1
    fixed = db.query(f"SELECT COUNT(*) n FROM issues WHERE submission_id IN ({ph}) AND status='fixed'", ids, one=True)["n"]
    detected = db.query(f"SELECT COUNT(DISTINCT submission_id||'|'||COALESCE(match,'')||rule_key) n FROM issues WHERE submission_id IN ({ph})", ids, one=True)["n"]
    return {
        "kpis": {"submissions": len(subs), "avg_score": round(sum(scored) / len(scored), 1) if scored else None,
                 "approved": status.get("approved", 0), "in_review": status.get("in_review", 0),
                 "issues_detected": detected, "issues_fixed": fixed},
        "by_rule": by_rule[:10], "by_category": cats, "by_team": sorted(team_rows, key=lambda t: -(t["avg_score"] or 0)),
        "ambiguous_guidelines": ambiguous, "trend": trend, "status": status,
    }
