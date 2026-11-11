import unittest
from tests.base import BaseTestCase


class AnalyticsAmbiguityTest(BaseTestCase):
    def test_analytics_ambiguity_detection(self):
        h1 = self.auth("creator")
        h2 = self.auth("creator2")
        hm = self.auth("manager")

        # Creator 1 creates 2 submissions with "guys" rule violation
        sid1 = self.new_text("Verdant guys love our bottle.", "creator", "Ambiguity 1")
        d1 = self.c.get(f"/api/submissions/{sid1}", headers=h1).json
        issue1 = next(i for i in d1["issues"] if i["rule_key"] == "term-guys")
        r = self.c.post(f"/api/submissions/{sid1}/issues/{issue1['id']}/dismiss", headers=h1,
                        json={"reason": "Casual demographic intended"})
        self.assertEqual(r.status_code, 200)

        sid2 = self.new_text("Verdant guys enjoy nature.", "creator", "Ambiguity 2")
        d2 = self.c.get(f"/api/submissions/{sid2}", headers=h1).json
        issue2 = next(i for i in d2["issues"] if i["rule_key"] == "term-guys")
        r = self.c.post(f"/api/submissions/{sid2}/issues/{issue2['id']}/dismiss", headers=h1,
                        json={"reason": "Audience fit for newsletter"})
        self.assertEqual(r.status_code, 200)

        # Creator 2 creates 1 submission with "guys" rule violation
        sid3 = self.new_text("Verdant guys hike together.", "creator2", "Ambiguity 3")
        d3 = self.c.get(f"/api/submissions/{sid3}", headers=h2).json
        issue3 = next(i for i in d3["issues"] if i["rule_key"] == "term-guys")
        r = self.c.post(f"/api/submissions/{sid3}/issues/{issue3['id']}/dismiss", headers=h2,
                        json={"reason": "Social media campaign voice"})
        self.assertEqual(r.status_code, 200)

        # Manager checks analytics
        analytics = self.c.get("/api/analytics", headers=hm).json
        ambiguous = analytics.get("ambiguous_guidelines", [])
        self.assertTrue(len(ambiguous) > 0, "Expected at least one ambiguous guideline")

        # Verify term-guys is detected as ambiguous across multiple creators & dismissals
        target = next((g for g in ambiguous if g.get("rule_key") == "term-guys" or "guys" in g.get("name", "").lower()), None)
        self.assertIsNotNone(target, f"Rule 'term-guys' not found in ambiguous guidelines: {ambiguous}")
        self.assertGreaterEqual(target["creators"], 2)
        self.assertGreaterEqual(target["dismissed"], 3)
        self.assertIn("ambiguity", target)


if __name__ == "__main__":
    unittest.main()
