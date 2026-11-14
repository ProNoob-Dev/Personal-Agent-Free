import os
import tempfile
import unittest

# Set an isolated database before importing the application module.
_tmp = tempfile.TemporaryDirectory()
os.environ["DATABASE_PATH"] = os.path.join(_tmp.name, "test-nexus.db")

from fastapi.testclient import TestClient
from app.main import app


class NexusApiSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client_context = TestClient(app)
        cls.client = cls.client_context.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client_context.__exit__(None, None, None)
        _tmp.cleanup()

    def test_health_endpoint(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])

    def test_seeded_agents_are_available(self):
        response = self.client.get("/api/agents")
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(len(response.json()), 3)

    def test_create_agent(self):
        response = self.client.post(
            "/api/agents",
            json={
                "name": "CI Test Agent",
                "provider": "cloudflare",
                "system_prompt": "Reply clearly.",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json().get("id"))


if __name__ == "__main__":
    unittest.main()
