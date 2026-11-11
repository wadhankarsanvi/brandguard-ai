import os
import sys
import tempfile
import unittest

_tmp = os.environ.get("DATA_DIR")
if not _tmp:
    _tmp = tempfile.mkdtemp()
    os.environ["DATA_DIR"] = _tmp

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.app import app

PW = "BrandGuard@123"


class BaseTestCase(unittest.TestCase):
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

