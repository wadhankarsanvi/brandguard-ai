import unittest
from tests.base import BaseTestCase


class ProductionImprovementsTest(BaseTestCase):
    def test_registration_and_auth(self):
        # Register a new creator
        r = self.c.post("/api/auth/register", json={
            "email": "newbie@brandguard.ai",
            "name": "Newbie Creator",
            "password": "Password123!",
            "team": "Growth"
        })
        self.assertEqual(r.status_code, 201, r.json)
        self.assertIn("token", r.json)
        self.assertEqual(r.json["user"]["email"], "newbie@brandguard.ai")
        self.assertEqual(r.json["user"]["role"], "creator")

        # Duplicate registration fails
        r_dup = self.c.post("/api/auth/register", json={
            "email": "newbie@brandguard.ai",
            "name": "Another Person",
            "password": "Password123!"
        })
        self.assertEqual(r_dup.status_code, 400)

        # Login with newly registered user
        r_login = self.c.post("/api/auth/login", json={
            "email": "newbie@brandguard.ai",
            "password": "Password123!"
        })
        self.assertEqual(r_login.status_code, 200)
        self.assertIn("token", r_login.json)

    def test_rule_versioning_and_rollback(self):
        hm = self.auth("manager")

        # 1. Create a new rule
        rule_key = "term-test-vers"
        r = self.c.post("/api/rules", headers=hm, json={
            "key": rule_key,
            "name": "Test Versioning Rule",
            "category": "terminology",
            "kind": "term",
            "pattern": r"legacy_word",
            "preferred": "modern_word",
            "severity": "medium",
            "description": "Original rule description"
        })
        self.assertEqual(r.status_code, 201, r.json)
        rid = r.json["id"]

        # Check version history (should have version 1)
        r_ver = self.c.get(f"/api/rules/{rid}/versions", headers=hm)
        self.assertEqual(r_ver.status_code, 200)
        versions = r_ver.json
        self.assertEqual(len(versions), 1)
        self.assertEqual(versions[0]["version"], 1)
        self.assertEqual(versions[0]["pattern"], r"legacy_word")

        # 2. Update the rule
        r_up = self.c.put(f"/api/rules/{rid}", headers=hm, json={
            "pattern": r"legacy_word_v2",
            "preferred": "modern_word_v2",
            "reason": "Refined pattern to v2"
        })
        self.assertEqual(r_up.status_code, 200)

        # Check versions (should now have version 2 and 1)
        r_ver2 = self.c.get(f"/api/rules/{rid}/versions", headers=hm)
        self.assertEqual(r_ver2.status_code, 200)
        versions2 = r_ver2.json
        self.assertEqual(len(versions2), 2)
        self.assertEqual(versions2[0]["version"], 2)
        self.assertEqual(versions2[0]["pattern"], r"legacy_word_v2")

        # 3. Rollback to version 1
        r_rb = self.c.post(f"/api/rules/{rid}/rollback/1", headers=hm)
        self.assertEqual(r_rb.status_code, 200)
        self.assertEqual(r_rb.json["rolled_back_to"], 1)

        # Verify active rule is back to legacy_word
        rules = self.c.get("/api/rules", headers=hm).json
        active = next(x for x in rules if x["id"] == rid)
        self.assertEqual(active["pattern"], r"legacy_word")

    def test_ambiguity_reword_suggestion(self):
        hm = self.auth("manager")
        # Trigger analytics and check structure of ambiguous guidelines
        analytics = self.c.get("/api/analytics", headers=hm).json
        self.assertIn("ambiguous_guidelines", analytics)
        # Even if list is empty or populated, keys must be valid
        for g in analytics["ambiguous_guidelines"]:
            self.assertIn("ambiguity", g)
            self.assertIn("hint", g)


if __name__ == "__main__":
    unittest.main()

