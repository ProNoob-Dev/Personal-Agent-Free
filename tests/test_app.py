import os
import tempfile
import unittest
import uuid

_tmp = tempfile.TemporaryDirectory()
os.environ["DATABASE_PATH"] = os.path.join(_tmp.name, "test-nexus.db")
os.environ["ADMIN_API_KEY"] = "test-secret"

from fastapi.testclient import TestClient
from app.main import app


class NexusApiSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client_context = TestClient(app)
        cls.client = cls.client_context.__enter__()
        cls.headers = {"X-API-Key": "test-secret"}

    @classmethod
    def tearDownClass(cls):
        cls.client_context.__exit__(None, None, None)
        _tmp.cleanup()

    def test_health_endpoint(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])

    def test_seeded_agents_are_available(self):
        response = self.client.get("/api/agents", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(len(response.json()), 3)

    def test_create_agent(self):
        response = self.client.post(
            "/api/agents",
            headers=self.headers,
            json={
                "name": "CI Test Agent",
                "provider": "cloudflare",
                "system_prompt": "Reply clearly.",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json().get("id"))


    def test_public_chat_and_document_upload(self):
        guest = str(uuid.uuid4())
        headers = {"X-Guest-ID": guest}
        agents = self.client.get("/api/public/agents")
        self.assertEqual(agents.status_code, 200)
        agent_id = agents.json()[0]["id"]
        created = self.client.post("/api/public/conversations", headers=headers, json={"agent_id": agent_id})
        self.assertEqual(created.status_code, 200)
        conversation_id = created.json()["id"]
        upload = self.client.post(
            f"/api/public/conversations/{conversation_id}/upload",
            headers=headers,
            files={"file": ("notes.txt", b"Project NEXUS supports document analysis.", "text/plain")},
        )
        self.assertEqual(upload.status_code, 200)
        docs = self.client.get(f"/api/public/conversations/{conversation_id}/documents", headers=headers)
        self.assertEqual(docs.status_code, 200)
        self.assertEqual(docs.json()[0]["filename"], "notes.txt")

    def test_public_conversation_is_private_to_guest_session(self):
        guest = str(uuid.uuid4())
        other = str(uuid.uuid4())
        agent_id = self.client.get("/api/public/agents").json()[0]["id"]
        created = self.client.post("/api/public/conversations", headers={"X-Guest-ID": guest}, json={"agent_id": agent_id})
        cid = created.json()["id"]
        denied = self.client.get(f"/api/public/conversations/{cid}/messages", headers={"X-Guest-ID": other})
        self.assertEqual(denied.status_code, 404)

    def test_public_chat_page(self):
        response = self.client.get("/chat")
        self.assertEqual(response.status_code, 200)
        self.assertIn("NEXUS AI", response.text)

    def test_protected_api_rejects_missing_key(self):
        response = self.client.get("/api/agents")
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
