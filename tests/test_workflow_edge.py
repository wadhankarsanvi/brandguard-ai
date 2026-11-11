import unittest
from tests.base import BaseTestCase


class WorkflowEdgeCasesTest(BaseTestCase):
    def test_reject_path_and_resubmit(self):
        h_creator = self.auth("creator")
        h_mgr = self.auth("manager")

        # 1. Creator creates and submits draft
        sid = self.new_text("Verdant team develops reliable sustainable essentials.", "creator", "Reject Test")
        r = self.c.post(f"/api/submissions/{sid}/submit-review", headers=h_creator)
        self.assertEqual(r.status_code, 200)

        d = self.c.get(f"/api/submissions/{sid}", headers=h_creator).json["submission"]
        self.assertEqual(d["status"], "in_review")

        # 2. Manager rejects the submission
        r = self.c.post(f"/api/submissions/{sid}/review", headers=h_mgr,
                        json={"decision": "reject", "note": "Needs brand voice realignment."})
        self.assertEqual(r.status_code, 200)

        d = self.c.get(f"/api/submissions/{sid}", headers=h_creator).json["submission"]
        self.assertEqual(d["status"], "rejected")

        # 3. Creator updates content while rejected
        r = self.c.put(f"/api/submissions/{sid}/content", headers=h_creator,
                       json={"text": "The Verdant collection offers durable everyday essentials.", "note": "Revised"})
        self.assertEqual(r.status_code, 200)

        # 4. Creator resubmits for review
        r = self.c.post(f"/api/submissions/{sid}/submit-review", headers=h_creator)
        self.assertEqual(r.status_code, 200)

        d = self.c.get(f"/api/submissions/{sid}", headers=h_creator).json["submission"]
        self.assertEqual(d["status"], "in_review")

        # 5. Manager approves
        r = self.c.post(f"/api/submissions/{sid}/review", headers=h_mgr,
                        json={"decision": "approve", "note": "Looks great."})
        self.assertEqual(r.status_code, 200)

        d = self.c.get(f"/api/submissions/{sid}", headers=h_creator).json["submission"]
        self.assertEqual(d["status"], "approved")

    def test_changes_requested_then_resubmit(self):
        h_creator = self.auth("creator")
        h_mgr = self.auth("manager")

        # 1. Creator creates submission and submits
        sid = self.new_text("Verdant guys love our bottle.", "creator", "Changes Req Test")
        r = self.c.post(f"/api/submissions/{sid}/submit-review", headers=h_creator)
        self.assertEqual(r.status_code, 200)

        # 2. Manager requests changes
        r = self.c.post(f"/api/submissions/{sid}/review", headers=h_mgr,
                        json={"decision": "changes", "note": "Please replace informal language."})
        self.assertEqual(r.status_code, 200)

        d = self.c.get(f"/api/submissions/{sid}", headers=h_creator).json["submission"]
        self.assertEqual(d["status"], "changes_requested")

        # 3. Creator applies fix
        detail = self.c.get(f"/api/submissions/{sid}", headers=h_creator).json
        guys_issue = next(i for i in detail["issues"] if i["rule_key"] == "term-guys")
        r = self.c.post(f"/api/submissions/{sid}/issues/{guys_issue['id']}/apply", headers=h_creator)
        self.assertEqual(r.status_code, 200)

        # 4. Creator resubmits
        r = self.c.post(f"/api/submissions/{sid}/submit-review", headers=h_creator)
        self.assertEqual(r.status_code, 200)

        d = self.c.get(f"/api/submissions/{sid}", headers=h_creator).json["submission"]
        self.assertEqual(d["status"], "in_review")

        # 5. Manager approves
        r = self.c.post(f"/api/submissions/{sid}/review", headers=h_mgr, json={"decision": "approve"})
        self.assertEqual(r.status_code, 200)

        d = self.c.get(f"/api/submissions/{sid}", headers=h_creator).json["submission"]
        self.assertEqual(d["status"], "approved")


if __name__ == "__main__":
    unittest.main()

