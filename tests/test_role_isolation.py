import unittest
from tests.base import BaseTestCase


class RoleIsolationSubmissionsTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.h1 = self.auth("creator")
        self.h2 = self.auth("creator2")
        self.hm = self.auth("manager")
        self.hl = self.auth("legal")
        # Submissions created by creator1
        self.sid = self.new_text("Verdant guys love our bottle.\n\nOur customers are happy.", "creator", "Isolation Test")
        detail = self.c.get(f"/api/submissions/{self.sid}", headers=self.h1).json
        self.iid = detail["issues"][0]["id"]

    def test_list_isolation(self):
        # Creator 1 sees sid; Creator 2 does not see sid
        list1 = self.c.get("/api/submissions", headers=self.h1).json
        self.assertTrue(any(s["id"] == self.sid for s in list1))
        list2 = self.c.get("/api/submissions", headers=self.h2).json
        self.assertFalse(any(s["id"] == self.sid for s in list2))
        listm = self.c.get("/api/submissions", headers=self.hm).json
        self.assertTrue(any(s["id"] == self.sid for s in listm))

    def test_detail_and_diff_isolation(self):
        self.assertEqual(self.c.get(f"/api/submissions/{self.sid}", headers=self.h2).status_code, 403)
        self.assertEqual(self.c.get(f"/api/submissions/{self.sid}/diff?from=1&to=1", headers=self.h2).status_code, 403)

    def test_content_and_analyze_isolation(self):
        self.assertEqual(self.c.put(f"/api/submissions/{self.sid}/content", headers=self.h2, json={"text": "hacked"}).status_code, 403)
        self.assertEqual(self.c.post(f"/api/submissions/{self.sid}/analyze", headers=self.h2).status_code, 403)

    def test_rewrite_and_apply_all_isolation(self):
        self.assertEqual(self.c.get(f"/api/submissions/{self.sid}/rewrite", headers=self.h2).status_code, 403)
        self.assertEqual(self.c.post(f"/api/submissions/{self.sid}/apply-all", headers=self.h2).status_code, 403)

    def test_issues_actions_isolation(self):
        self.assertEqual(self.c.post(f"/api/submissions/{self.sid}/issues/{self.iid}/apply", headers=self.h2).status_code, 403)
        self.assertEqual(self.c.post(f"/api/submissions/{self.sid}/issues/{self.iid}/dismiss", headers=self.h2, json={"reason": "skip"}).status_code, 403)
        self.assertEqual(self.c.post(f"/api/submissions/{self.sid}/issues/{self.iid}/reopen", headers=self.h2).status_code, 403)

    def test_comments_isolation(self):
        self.assertEqual(self.c.post(f"/api/submissions/{self.sid}/comments", headers=self.h2, json={"body": "intruder"}).status_code, 403)
        self.assertEqual(self.c.post(f"/api/submissions/{self.sid}/comments", headers=self.h1, json={"body": "author comment"}).status_code, 201)

    def test_submit_and_review_workflow_isolation(self):
        # Creator 2 cannot submit creator 1's submission
        self.assertEqual(self.c.post(f"/api/submissions/{self.sid}/submit-review", headers=self.h2).status_code, 403)
        # Creator 1 cannot review own submission
        self.assertEqual(self.c.post(f"/api/submissions/{self.sid}/review", headers=self.h1, json={"decision": "approve"}).status_code, 403)
        # Creator 1 submits
        self.assertEqual(self.c.post(f"/api/submissions/{self.sid}/submit-review", headers=self.h1).status_code, 200)
        # Legal cannot review when stage is manager
        self.assertEqual(self.c.post(f"/api/submissions/{self.sid}/review", headers=self.hl, json={"decision": "approve"}).status_code, 403)


if __name__ == "__main__":
    unittest.main()

