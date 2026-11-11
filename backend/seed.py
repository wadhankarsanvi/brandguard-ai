"""First-boot seeding: demo users, brand rules, settings, knowledge base and (optionally) demo submissions
that are pushed through the *real* pipeline and workflow so the dashboards are alive on first open."""
import datetime as dt
import json

from werkzeug.security import generate_password_hash

from backend import config, db
from backend.common import now
from backend.services import pipeline, rag, workflow

USERS = [
    ("creator@brandguard.ai", "Aisha Rao", "creator", "Marketing"),
    ("creator2@brandguard.ai", "Dev Patel", "creator", "Social"),
    ("agency@brandguard.ai", "Lena Fischer", "creator", "Agency"),
    ("manager@brandguard.ai", "Maya Iyer", "manager", "Brand"),
    ("legal@brandguard.ai", "Rohan Mehta", "legal", "Legal"),
]

G = "Brand Guidelines v4.2"
RULES = [  # key, name, category, kind, pattern, preferred, severity, description, source, case_sensitive
    ("term-brand-name", "Brand name spelling", "terminology", "term", r"VerdantCo|Verdant Co|verdant", "Verdant", "high",
     "Our name is written Verdant with a capital V. Never write VerdantCo.", G + " §2 Terminology", 1),
    ("term-members", "Say “members”, not “customers”", "terminology", "term", r"customer(s)?", r"member\1", "medium",
     "We call buyers members, never customers.", G + " §2 Terminology", 0),
    ("term-cheap", "Say “affordable”, not “cheap”", "terminology", "term", r"cheap|inexpensive", "affordable", "medium",
     "Describe prices as affordable or fairly priced, never cheap.", G + " §2 Terminology", 0),
    ("term-guys", "Inclusive address", "terminology", "term", r"guys", "everyone", "medium",
     "Address readers as everyone or friends, never guys.", G + " §2 Terminology", 0),
    ("term-utilize", "Plain language: “use”", "terminology", "term", r"utili[sz]e", "use", "minor",
     "Use plain words: use instead of utilize.", G + " §2 Terminology", 0),
    ("tone-hype", "Avoid hype words", "tone", "term", r"revolutionary|game[- ]chang(?:ing|er)|mind[- ]blowing|unbeatable|best[- ]ever", "",
     "medium", "Avoid hype words such as revolutionary, game-changing, mind-blowing. Let facts persuade.", G + " §1 Voice & Tone", 0),
    ("tone-exclaim", "Exclamation marks", "tone", "exclaim", "1", "", "minor",
     "Use at most one exclamation mark per 100 words.", G + " §1 Voice & Tone", 0),
    ("tone-caps", "No shouting in ALL CAPS", "tone", "caps", "0", "", "minor",
     "Avoid writing words in ALL CAPS.", G + " §1 Voice & Tone", 0),
    ("a11y-link-text", "Descriptive link text", "accessibility", "term", r"click here|read more", "", "medium",
     "Link text must describe the destination: never use click here or read more.", G + " §7 Accessibility · WCAG 2.4.4", 0),
    ("claim-unverified", "Claims must be substantiated", "claims", "claim",
     r"100\s?%|guarantee\w*|\balways\b|#1|number one|\bbest\b|clinically proven|zero[- ]waste|carbon[- ]neutral|eco[- ]friendly|biodegradable|compostable|recyclable|sustainable|\b\d+(?:\.\d+)?\s?(?:hours?|%(?!\s+off)|x faster|years?)",
     "", "high", "Every environmental, performance or comparative claim must be backed by an approved source in the Product Fact Sheet.",
     G + " §3 Claims & Substantiation", 0),
    ("legal-disclaimer", "Required legal disclaimer", "legal", "disclaimer",
     r"\d+\s?%\s+off|free trial|money[- ]back|guarantee\w*|save up to", "Terms and conditions apply.", "high",
     "Any promotion, discount, free trial or guarantee must include the line Terms and conditions apply.", G + " §4 Legal Disclaimers", 0),
]

PALETTE = [{"name": "Verdant Green", "hex": "#2E7D32"}, {"name": "Deep Forest", "hex": "#1B3A2D"},
           {"name": "Sunrise Amber", "hex": "#F5A623"}, {"name": "Cloud White", "hex": "#F7F9F7"}]

# file, creator email, days ago, workflow ("draft" | "review" | "legal" | "approved" | "changes")
DEMO = [
    ("01_spring_launch.md", "Spring campaign launch post", "creator@brandguard.ai", 9, "draft"),
    ("02_member_newsletter.md", "Member newsletter — May", "creator@brandguard.ai", 7, "approved"),
    ("03_social_carbon.md", "Social post: sustainability", "creator2@brandguard.ai", 5, "review"),
    ("04_agency_banner_copy.md", "Banner copy: Terra", "agency@brandguard.ai", 4, "changes"),
    ("05_clean_blog.md", "Blog: why kraft paper", "creator2@brandguard.ai", 2, "approved"),
    ("06_promo_email.md", "Promo email: Terra", "agency@brandguard.ai", 1, "legal"),
]


def seed_if_empty():
    if db.query("SELECT COUNT(*) n FROM users", one=True)["n"]:
        return
    for email, name, role, team in USERS:
        db.execute("INSERT INTO users(email,name,role,team,password_hash) VALUES(?,?,?,?,?)",
                   (email, name, role, team, generate_password_hash(config.DEMO_PASSWORD)))
    for r in RULES:
        db.execute("INSERT INTO rules(key,name,category,kind,pattern,preferred,severity,description,source,case_sensitive) VALUES(?,?,?,?,?,?,?,?,?,?)", r)
    db.execute("INSERT INTO settings(key,value) VALUES('palette',?)", (json.dumps(PALETTE),))
    db.execute("INSERT INTO settings(key,value) VALUES('min_contrast','4.5')")
    db.execute("INSERT INTO settings(key,value) VALUES('min_width','800')")
    for fname, title, dtype in (("brand_guidelines.md", "Verdant Brand Guidelines v4.2", "guideline"),
                                ("product_facts.md", "Verdant Product Fact Sheet 2026", "product_facts")):
        rag.add_document(title, (config.SAMPLE_DIR / fname).read_text(encoding="utf-8"), dtype, fname)
    if config.SEED_DEMO_DATA:
        _seed_demo()


def _seed_demo():
    from backend.routes.submissions import create_submission
    users = {u["email"]: u for u in db.query("SELECT * FROM users")}
    mgr, legal = users["manager@brandguard.ai"], users["legal@brandguard.ai"]
    for fname, title, email, days, flow in DEMO:
        cr = users[email]
        text = (config.SAMPLE_DIR / "drafts" / fname).read_text(encoding="utf-8")
        sid = create_submission(cr, title, text, None, "")
        sub = lambda: db.query("SELECT * FROM submissions WHERE id=?", (sid,), one=True)
        if flow in ("review", "legal", "approved", "changes"):
            # a realistic creator applies the safe auto-fixes before requesting review
            rw = pipeline.build_rewrite(sid)
            if rw["rewrite"] != text:
                workflow.add_revision(sub(), rw["rewrite"], cr, "Applied suggestions")
                pipeline.run_analysis(sid, cr, "fix")
            for i in db.query("SELECT id FROM issues WHERE submission_id=? AND version=? AND severity='critical' AND status='open'", (sid, sub()["current_version"])):
                db.execute("UPDATE issues SET status='dismissed' WHERE id=?", (i["id"],))
            pipeline.rescore(sid)
        if flow == "changes":
            workflow.submit_for_review(sub(), cr)
            workflow.decide(sub(), mgr, "changes", "Please substantiate the biodegradable claim with the fact sheet.")
        elif flow in ("review", "legal", "approved"):
            workflow.submit_for_review(sub(), cr)
            if flow in ("legal", "approved"):
                workflow.decide(sub(), mgr, "approve", "Looks on-brand.")
            if flow == "approved" and sub()["status"] == "in_review":
                workflow.decide(sub(), legal, "approve", "Claims verified against fact sheet.")
        ts = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        db.execute("UPDATE submissions SET created_at=?, updated_at=? WHERE id=?", (ts, ts, sid))
