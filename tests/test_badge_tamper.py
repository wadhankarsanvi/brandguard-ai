import unittest
from tests.base import BaseTestCase


class BadgeVerifyAfterContentEditTest(BaseTestCase):
    def test_badge_verify_after_content_edit(self):
        h_creator = self.auth("creator")
        h_mgr = self.auth("manager")

        # 1. Create clean compliant submission and submit for review
        sid = self.new_text("The Verdant Everyday Bottle is made with 70% recycled stainless steel and is fully recyclable at end of life.",
                            "creator", "Badge Integrity Test")
        r = self.c.post(f"/api/submissions/{sid}/submit-review", headers=h_creator)
        self.assertEqual(r.status_code, 200)

        # 2. Manager approves, issuing cryptographic compliance badge
        r = self.c.post(f"/api/submissions/{sid}/review", headers=h_mgr,
                        json={"decision": "approve", "note": "Fully on-brand"})
        self.assertEqual(r.status_code, 200)

        submission = self.c.get(f"/api/submissions/{sid}", headers=h_creator).json["submission"]
        self.assertEqual(submission["status"], "approved")
        badge_token = submission["badge"]
        self.assertTrue(badge_token and badge_token.startswith("BG1."))

        # 3. Public /api/verify confirms badge is valid before any edits
        v_initial = self.c.get("/api/verify", query_string={"token": badge_token}).json
        self.assertTrue(v_initial["valid"])
        self.assertNotEqual(v_initial.get("content_unchanged"), False)

        # 4. Creator cannot edit approved submission (locked)
        r = self.c.put(f"/api/submissions/{sid}/content", headers=h_creator,
                       json={"text": "Creator trying to edit approved content."})
        self.assertEqual(r.status_code, 400)

        # 5. Manager edits content post-approval
        r = self.c.put(f"/api/submissions/{sid}/content", headers=h_mgr,
                       json={"text": "Manager modified content post-approval."})
        self.assertEqual(r.status_code, 200)

        # 6. Verify badge again: must now fail validation because content changed
        v_after_edit = self.c.get("/api/verify", query_string={"token": badge_token}).json
        self.assertFalse(v_after_edit["valid"])
        self.assertEqual(v_after_edit.get("content_unchanged"), False)

        # 7. Forged or tampered token fails validation
        tampered_token = badge_token[:-4] + "wxyz"
        v_tampered = self.c.get("/api/verify", query_string={"token": tampered_token}).json
        self.assertFalse(v_tampered["valid"])


if __name__ == "__main__":
    unittest.main()

