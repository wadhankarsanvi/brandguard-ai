"""End-to-end API tests (stdlib unittest, no extra deps).  Run:  python -m unittest discover -s tests -v"""
import io
import os
import sys
import tempfile
import unittest

_tmp = tempfile.mkdtemp()
os.environ["DATA_DIR"] = _tmp
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from backend.app import app  # noqa: E402

PW = "BrandGuard@123"


class Api(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = app.test_client()

    def auth(self, who):
        r = self.c.post("/api/auth/login", json={"email": f"{who}@brandguard.ai", "password": PW})
        self.assertEqual(r.status_code, 200)
        return {"Authorization": "Bearer " + r.json["token"]}

    def new_text(self, text, who="creator", title="t"):
        r = self.c.post("/api/submissions", data={"title": title, "text": text}, headers=self.auth(who))
        self.assertEqual(r.status_code, 201, r.json)
        return r.json["id"]

    def test_login_and_isolation(self):
        self.assertEqual(self.c.post("/api/auth/login", json={"email": "x@y.z", "password": "no"}).status_code, 401)
        self.assertEqual(self.c.get("/api/submissions").status_code, 401)
        sid = self.new_text("Hello from Verdant.", "creator")
        self.assertEqual(self.c.get(f"/api/submissions/{sid}", headers=self.auth("creator2")).status_code, 403)
        self.assertEqual(self.c.get(f"/api/submissions/{sid}", headers=self.auth("manager")).status_code, 200)

    def test_text_rules_and_claims(self):
        sid = self.new_text("VerdantCo guys love it! Our customers say it is cheap and 100% eco-friendly. "
                            "Mail me at jane.doe@gmail.com or 98765 43210. BUY NOW and get 20% off.")
        d = self.c.get(f"/api/submissions/{sid}", headers=self.auth("creator")).json
        keys = {i["rule_key"] for i in d["issues"]}
        for k in ("term-brand-name", "term-guys", "term-members", "term-cheap", "claim-unverified", "pii-exposure", "legal-disclaimer", "tone-caps"):
            self.assertIn(k, keys)
        self.assertEqual(sum(1 for i in d["issues"] if i["rule_key"] == "pii-exposure"), 2)
        self.assertLess(d["submission"]["score"], 50)
        claim = next(i for i in d["issues"] if i["rule_key"] == "claim-unverified")
        self.assertTrue(claim["citation"]["quote"])

    def test_supported_claim_is_verified(self):
        sid = self.new_text("The Verdant Everyday Bottle is made with 70% recycled stainless steel and is fully recyclable at end of life.")
        d = self.c.get(f"/api/submissions/{sid}", headers=self.auth("creator")).json
        self.assertEqual([i for i in d["issues"] if i["category"] == "claims"], [])
        self.assertEqual(len(d["verified_claims"]), 1)

    def test_wrong_number_is_flagged(self):
        sid = self.new_text("The Verdant Solar Lantern runs for 35 hours on a full charge.")
        d = self.c.get(f"/api/submissions/{sid}", headers=self.auth("creator")).json
        self.assertTrue(any(i["rule_key"] == "claim-unverified" for i in d["issues"]))

    def test_apply_fix_and_full_workflow(self):
        h = self.auth("creator")
        sid = self.new_text("Verdant guys love the product.\n\nOur customers are happy.", title="wf")
        d = self.c.get(f"/api/submissions/{sid}", headers=h).json
        fix = next(i for i in d["issues"] if i["rule_key"] == "term-guys")
        self.assertEqual(self.c.post(f"/api/submissions/{sid}/issues/{fix['id']}/apply", headers=h).status_code, 200)
        d = self.c.get(f"/api/submissions/{sid}", headers=h).json
        self.assertIn("everyone love", d["submission"]["content_text"])
        self.assertEqual(d["submission"]["current_version"], 2)
        diff = self.c.get(f"/api/submissions/{sid}/diff?from=1&to=2", headers=h).json
        self.assertTrue(any(o["op"] != "equal" for o in diff["ops"]))
        self.assertEqual(self.c.post(f"/api/submissions/{sid}/apply-all", headers=h).status_code, 200)

        # creator cannot approve; wrong-stage reviewer blocked
        self.assertEqual(self.c.post(f"/api/submissions/{sid}/review", json={"decision": "approve"}, headers=h).status_code, 403)
        self.assertEqual(self.c.post(f"/api/submissions/{sid}/submit-review", headers=h).status_code, 200)
        self.assertEqual(self.c.post(f"/api/submissions/{sid}/review", json={"decision": "approve"}, headers=self.auth("legal")).status_code, 403)
        # locked while in review
        self.assertEqual(self.c.put(f"/api/submissions/{sid}/content", json={"text": "x"}, headers=h).status_code, 400)
        m = self.auth("manager")
        self.c.post(f"/api/submissions/{sid}/comments", json={"body": "Nice work"}, headers=m)
        r = self.c.post(f"/api/submissions/{sid}/review", json={"decision": "approve", "note": "ok"}, headers=m)
        self.assertEqual(r.status_code, 200)
        d = self.c.get(f"/api/submissions/{sid}", headers=h).json["submission"]
        self.assertEqual(d["status"], "approved")
        self.assertTrue(d["badge"].startswith("BG1."))
        v = self.c.get("/api/verify", query_string={"token": d["badge"]}).json
        self.assertTrue(v["valid"])
        # editing after approval invalidates the badge
        self.assertEqual(self.c.put(f"/api/submissions/{sid}/content", json={"text": "Changed."}, headers=h).status_code, 400)  # locked for creators
        self.c.put(f"/api/submissions/{sid}/content", json={"text": "Changed after approval."}, headers=m)
        self.assertFalse(self.c.get("/api/verify", query_string={"token": d["badge"]}).json["valid"])
        self.assertFalse(self.c.get("/api/verify", query_string={"token": d["badge"][:-3] + "abc"}).json["valid"])

    def test_legal_escalation(self):
        h = self.auth("creator2")
        sid = self.new_text("Verdant Terra is biodegradable within 28 days.", "creator2", "legal-needed")
        self.assertEqual(self.c.post(f"/api/submissions/{sid}/submit-review", headers=h).status_code, 200)
        self.c.post(f"/api/submissions/{sid}/review", json={"decision": "approve"}, headers=self.auth("manager"))
        s = self.c.get(f"/api/submissions/{sid}", headers=h).json["submission"]
        self.assertEqual(s["stage"], "legal" if s["requires_legal"] else "published")

    def test_critical_blocks_review(self):
        h = self.auth("creator")
        sid = self.new_text("Contact jane.doe@gmail.com for details.")
        self.assertEqual(self.c.post(f"/api/submissions/{sid}/submit-review", headers=h).status_code, 400)

    def test_image_checks(self):
        img = np.full((600, 1000, 3), 255, np.uint8)
        cv2.rectangle(img, (0, 0), (1000, 200), (200, 30, 160), -1)                 # off-palette magenta band
        cv2.putText(img, "SUMMER SALE", (60, 400), cv2.FONT_HERSHEY_SIMPLEX, 2.4, (205, 205, 205), 5)  # low-contrast text
        cv2.putText(img, "Dark readable text", (60, 520), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (20, 20, 20), 3)
        ok, buf = cv2.imencode(".png", img)
        r = self.c.post("/api/submissions", headers=self.auth("creator"), content_type="multipart/form-data",
                        data={"title": "banner", "text": "Eco-friendly recyclable packaging", "alt_text": "",
                              "file": (io.BytesIO(buf.tobytes()), "banner.png")})
        self.assertEqual(r.status_code, 201, r.json)
        d = self.c.get(f"/api/submissions/{r.json['id']}", headers=self.auth("creator")).json
        keys = {i["rule_key"] for i in d["issues"]}
        self.assertIn("img-alt-missing", keys)
        self.assertIn("img-palette", keys)
        self.assertIn("img-contrast", keys)
        self.assertIn("mm-claim-mismatch", keys)
        box = next(i for i in d["issues"] if i["rule_key"] == "img-contrast")["bbox"]
        self.assertEqual(len(box), 4)
        self.assertEqual(self.c.get(d["submission"]["image_url"], headers=self.auth("creator")).status_code, 200)

    def test_kb_rules_analytics(self):
        m = self.auth("manager")
        r = self.c.post("/api/kb/documents", headers=m, data={"title": "Extra facts", "text": "# Facts\n\nThe Verdant Compass lasts 3 years."})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(self.c.post("/api/kb/documents", headers=self.auth("creator"), data={"text": "x"}).status_code, 403)
        hits = self.c.get("/api/kb/search?q=recycled stainless steel bottle", headers=m).json
        self.assertTrue(hits and hits[0]["score"] > 0)
        rr = self.c.post("/api/rules", headers=m, json={"key": "t-x", "name": "X", "category": "terminology", "kind": "term",
                                                      "pattern": "synergy", "preferred": "teamwork", "severity": "minor"})
        self.assertEqual(rr.status_code, 201)
        sid = self.new_text("We love synergy.")
        d = self.c.get(f"/api/submissions/{sid}", headers=self.auth("creator")).json
        self.assertTrue(any(i["rule_key"] == "t-x" for i in d["issues"]))
        a = self.c.get("/api/analytics", headers=m).json
        self.assertGreater(a["kpis"]["submissions"], 5)
        self.assertTrue(a["by_rule"] and a["by_team"])
        self.assertEqual(self.c.get("/api/audit", headers=self.auth("creator")).status_code, 403)

    def test_spa_served(self):
        res = self.c.get("/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers.get("X-Frame-Options"), "DENY")
        self.assertEqual(res.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertIn("default-src 'self'", res.headers.get("Content-Security-Policy", ""))
        self.assertEqual(self.c.get("/api/health").json["status"], "ok")

    def test_login_rate_limiting(self):
        from backend.common import reset_login_rate_limits
        reset_login_rate_limits()
        email = "rate_limit_test@brandguard.ai"
        for _ in range(5):
            r = self.c.post("/api/auth/login", json={"email": email, "password": "wrong"})
            self.assertEqual(r.status_code, 401)
        r = self.c.post("/api/auth/login", json={"email": email, "password": "wrong"})
        self.assertEqual(r.status_code, 429)
        self.assertIn("Too many failed login attempts", r.json.get("error", ""))
        reset_login_rate_limits()

    def test_production_secret_key_check(self):
        from backend.app import create_app
        import os
        old_render = os.environ.get("RENDER")
        try:
            os.environ["RENDER"] = "true"
            with self.assertRaises(RuntimeError) as ctx:
                create_app()
            self.assertIn("Refusing to boot in production", str(ctx.exception))
        finally:
            if old_render is None:
                os.environ.pop("RENDER", None)
            else:
                os.environ["RENDER"] = old_render

    def test_upload_magic_bytes(self):
        h = self.auth("creator")
        # Fake PNG
        fake_png = io.BytesIO(b"NOT A REAL PNG FILE CONTENT")
        r = self.c.post("/api/submissions", headers=h, content_type="multipart/form-data",
                        data={"title": "fake png", "file": (fake_png, "fake.png")})
        self.assertEqual(r.status_code, 400)
        self.assertIn("not a valid PNG", r.json.get("error", ""))

        # Fake PDF
        fake_pdf = io.BytesIO(b"NOT A REAL PDF FILE CONTENT")
        r = self.c.post("/api/submissions", headers=h, content_type="multipart/form-data",
                        data={"title": "fake pdf", "file": (fake_pdf, "fake.pdf")})
        self.assertEqual(r.status_code, 400)
        self.assertIn("not a valid PDF", r.json.get("error", ""))

    def test_change_password(self):
        h = self.auth("creator")
        r = self.c.post("/api/auth/change-password", headers=h, json={"current_password": "wrong", "new_password": "NewSecret123!"})
        self.assertEqual(r.status_code, 400)
        r = self.c.post("/api/auth/change-password", headers=h, json={"current_password": PW, "new_password": "short"})
        self.assertEqual(r.status_code, 400)
        r = self.c.post("/api/auth/change-password", headers=h, json={"current_password": PW, "new_password": "NewPassword@123"})
        self.assertEqual(r.status_code, 200)
        # Login with new password works
        r = self.c.post("/api/auth/login", json={"email": "creator@brandguard.ai", "password": "NewPassword@123"})
        self.assertEqual(r.status_code, 200)
        new_token = {"Authorization": "Bearer " + r.json["token"]}
        # Revert password back to original PW
        self.c.post("/api/auth/change-password", headers=new_token, json={"current_password": "NewPassword@123", "new_password": PW})

    def test_pdf_page_mapping_and_preview(self):
        try:
            from reportlab.lib.pagesizes import letter
            from reportlab.pdfgen import canvas
        except ImportError:
            self.skipTest("reportlab not installed")

        h = self.auth("creator")
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=letter)
        # Page 1 contains "guys" rule violation
        c.drawString(72, 700, "Hello Verdant guys and friends.")
        c.showPage()
        # Page 2 contains "cheap" rule violation
        c.drawString(72, 700, "Our prices are cheap and affordable.")
        c.save()
        buf.seek(0)

        r = self.c.post("/api/submissions", headers=h, content_type="multipart/form-data",
                        data={"title": "sample pdf", "file": (buf, "document.pdf")})
        self.assertEqual(r.status_code, 201)
        sid = r.json["id"]

        d = self.c.get(f"/api/submissions/{sid}", headers=h).json
        s = d["submission"]
        self.assertEqual(s["kind"], "pdf")
        self.assertTrue(s["page_map"])
        self.assertEqual(len(s["page_map"]), 2)
        self.assertEqual(s["page_map"][0]["page"], 1)
        self.assertEqual(s["page_map"][1]["page"], 2)

        # Check issues have page assigned
        issues = d["issues"]
        issue_guys = next((i for i in issues if i["rule_key"] == "term-guys"), None)
        self.assertIsNotNone(issue_guys)
        self.assertEqual(issue_guys.get("page"), 1)

        issue_cheap = next((i for i in issues if i["rule_key"] == "term-cheap"), None)
        self.assertIsNotNone(issue_cheap)
        self.assertEqual(issue_cheap.get("page"), 2)

        # If pypdfium2 rendered pages, verify page endpoints
        if s.get("pdf_pages"):
            self.assertEqual(len(s["pdf_pages"]), 2)
            page1_res = self.c.get(s["pdf_pages"][0], headers=h)
            self.assertEqual(page1_res.status_code, 200)
            self.assertEqual(page1_res.mimetype, "image/png")

    def test_embeddings_combined_scoring(self):
        from backend.services import rag
        # Test cosine similarity calculation
        self.assertAlmostEqual(rag._cosine_similarity([1.0, 0.0], [1.0, 0.0]), 1.0)
        self.assertAlmostEqual(rag._cosine_similarity([1.0, 0.0], [0.0, 1.0]), 0.0)
        self.assertAlmostEqual(rag._cosine_similarity([1.0, 1.0], [1.0, 1.0]), 1.0)
        self.assertEqual(rag._cosine_similarity([], []), 0.0)

    def test_embeddings_backend(self):
        try:
            import fastembed
        except ImportError:
            self.skipTest("fastembed not installed")

        from backend import config, db
        from backend.services import rag
        old_emb = config.EMBEDDINGS
        try:
            config.EMBEDDINGS = True
            doc_id = rag.add_document("Embedding Test Doc", "Sustainable bamboo packaging is carbon negative.", "guideline")
            chunks = db.query("SELECT * FROM chunks WHERE document_id=?", (doc_id,))
            self.assertTrue(chunks)
            self.assertIsNotNone(chunks[0]["embedding"])
            hits = rag.search("bamboo packaging carbon")
            self.assertTrue(hits)
            self.assertTrue(hits[0]["score"] > 0)
            self.assertIn("chunk_id", hits[0])
            self.assertIn("score", hits[0])
        finally:
            config.EMBEDDINGS = old_emb

    def test_notifications_triggers(self):
        from backend import db
        h_creator = self.auth("creator")
        h_manager = self.auth("manager")

        with app.app_context():
            db.execute("DELETE FROM notifications")

        # 1. Trigger 1: A submission enters your review stage
        sid = self.new_text("Verdant clean copy for notification test.", "creator", "Notif Test")
        r = self.c.post(f"/api/submissions/{sid}/submit-review", headers=h_creator)
        self.assertEqual(r.status_code, 200)

        notifs_mgr = self.c.get("/api/notifications", headers=h_manager).json
        self.assertGreater(notifs_mgr["unread"], 0)
        entry_notif = next((n for n in notifs_mgr["notifications"] if n["submission_id"] == sid), None)
        self.assertIsNotNone(entry_notif)
        self.assertIn("ready for manager review", entry_notif["message"])

        # 2. Trigger 2: A decision is made on your submission
        r = self.c.post(f"/api/submissions/{sid}/review", headers=h_manager, json={"decision": "changes", "note": "Please revise the tone."})
        self.assertEqual(r.status_code, 200)

        notifs_cr = self.c.get("/api/notifications", headers=h_creator).json
        self.assertGreater(notifs_cr["unread"], 0)
        decision_notif = next((n for n in notifs_cr["notifications"] if n["submission_id"] == sid), None)
        self.assertIsNotNone(decision_notif)
        self.assertIn("requested changes", decision_notif["message"])

        # 3. Trigger 3: You are mentioned (@name) in a comment
        r = self.c.post(f"/api/submissions/{sid}/comments", headers=h_creator, json={"body": "Hey @Maya please take a look at the revised draft."})
        self.assertEqual(r.status_code, 201)

        notifs_mgr_after = self.c.get("/api/notifications", headers=h_manager).json
        mention_notif = next((n for n in notifs_mgr_after["notifications"] if "mentioned you" in n["message"]), None)
        self.assertIsNotNone(mention_notif)
        self.assertIn("mentioned you in a comment", mention_notif["message"])

        # 4. Trigger 4: Badge is issued on approval
        self.c.post(f"/api/submissions/{sid}/submit-review", headers=h_creator)
        self.c.post(f"/api/submissions/{sid}/review", headers=h_manager, json={"decision": "approve", "note": "All good"})
        notifs_cr_badge = self.c.get("/api/notifications", headers=h_creator).json
        badge_notif = next((n for n in notifs_cr_badge["notifications"] if "Compliance badge issued" in n["message"]), None)
        self.assertIsNotNone(badge_notif)

        # 5. Verify read-all endpoint
        r_read = self.c.post("/api/notifications/read-all", headers=h_manager)
        self.assertEqual(r_read.status_code, 200)
        notifs_mgr_read = self.c.get("/api/notifications", headers=h_manager).json
        self.assertEqual(notifs_mgr_read["unread"], 0)

    def test_image_font_size_and_contrast_suggestion(self):
        # 800x400 white background image (so width >= 800 min_width)
        img = np.full((400, 800, 3), 255, np.uint8)
        # Small text: height under 14px (cv2.FONT_HERSHEY_SIMPLEX, 0.35 gives ~9-11px height)
        cv2.putText(img, "Tiny text under 14px copyright 2026", (40, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 0, 0), 1)
        # Low contrast text: normal font size (~22px height), but color (200, 200, 200) on white (255, 255, 255)
        cv2.putText(img, "Low contrast text needing fix", (40, 200), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (200, 200, 200), 2)

        ok, buf = cv2.imencode(".png", img)
        self.assertTrue(ok)
        r = self.c.post("/api/submissions", headers=self.auth("creator"), content_type="multipart/form-data",
                        data={"title": "synthetic image test", "alt_text": "Meaningful descriptive text for synthetic test image.",
                              "file": (io.BytesIO(buf.tobytes()), "synthetic.png")})
        self.assertEqual(r.status_code, 201)
        sid = r.json["id"]
        d = self.c.get(f"/api/submissions/{sid}", headers=self.auth("creator")).json
        issues = d["issues"]

        # Check item 3: font-size legibility check (img-text-small)
        small_issue = next((i for i in issues if i["rule_key"] == "img-text-small"), None)
        self.assertIsNotNone(small_issue, "Expected img-text-small issue for tiny text")
        self.assertEqual(small_issue["category"], "accessibility")
        self.assertEqual(small_issue["severity"], "medium")
        self.assertIsNotNone(small_issue["bbox"])
        self.assertLess(small_issue["bbox"][3], 14)

        # Check item 4: Suggested fix for img-contrast with hex
        contrast_issue = next((i for i in issues if i["rule_key"] == "img-contrast"), None)
        self.assertIsNotNone(contrast_issue, "Expected img-contrast issue for low-contrast text")
        self.assertIn("#", contrast_issue["suggestion"])
        import re
        m = re.search(r"#[0-9A-Fa-f]{6}", contrast_issue["suggestion"])
        self.assertIsNotNone(m, f"Hex colour not found in suggestion: {contrast_issue['suggestion']}")
        sug_hex = m.group(0)
        from backend.services.image_checker import _hex_to_rgb, contrast_ratio
        ratio = contrast_ratio(_hex_to_rgb(sug_hex), (255, 255, 255))
        self.assertGreaterEqual(ratio, 4.5)

    def test_logo_management_and_palette_editor(self):
        m = self.auth("manager")
        # 1. Upload logo
        logo_img = np.full((50, 100, 3), 128, np.uint8)
        ok, buf = cv2.imencode(".png", logo_img)
        r = self.c.post("/api/kb/logos", headers=m, content_type="multipart/form-data",
                        data={"file": (io.BytesIO(buf.tobytes()), "test_logo.png")})
        self.assertEqual(r.status_code, 201)

        # 2. List logos
        r = self.c.get("/api/kb/logos", headers=m)
        self.assertEqual(r.status_code, 200)
        logos = r.json
        self.assertTrue(any(l["name"] == "test_logo.png" for l in logos))

        # 3. Delete logo
        r = self.c.delete("/api/kb/logos/test_logo.png", headers=m)
        self.assertEqual(r.status_code, 200)
        r = self.c.get("/api/kb/logos", headers=m)
        self.assertFalse(any(l["name"] == "test_logo.png" for l in r.json))

        # 4. Palette editor via PUT /api/settings
        new_palette = [{"name": "Brand Teal", "hex": "#008080"}, {"name": "Brand Gold", "hex": "#FFD700"}]
        r = self.c.put("/api/settings", headers=m, json={"palette": new_palette})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json["palette"], new_palette)


if __name__ == "__main__":
    unittest.main()
