from __future__ import annotations

import unittest
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

import api.openai_keys as openai_keys_module


AUTH_HEADERS = {"Authorization": "Bearer test-admin"}


class FakeOpenAIKeyService:
    def __init__(self):
        self.items = []
        self.checked_ids = []

    def list_keys(self):
        return list(self.items)

    def add_key(self, name: str, secret: str, *, check: bool = False):
        item = {
            "id": "key-1",
            "name": name,
            "key_hint": "sk-proj...1234",
            "status": "unchecked",
            "models_count": 0,
            "sample_models": [],
            "last_error": None,
            "last_checked_at": "",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        }
        self.items = [item]
        return item

    def check_key(self, key_id: str):
        self.checked_ids.append(key_id)
        checked = {**self.items[0], "status": "ok", "models_count": 1, "sample_models": ["gpt-4.1-mini"]}
        self.items = [checked]
        return checked

    def delete_key(self, key_id: str):
        if self.items and self.items[0]["id"] == key_id:
            self.items = []
            return True
        return False


class OpenAIKeysApiTests(unittest.TestCase):
    def setUp(self):
        self.fake_service = FakeOpenAIKeyService()
        self.service_patcher = mock.patch.object(openai_keys_module, "openai_key_service", self.fake_service)
        self.auth_patcher = mock.patch.object(openai_keys_module, "require_admin", lambda _authorization: {"role": "admin"})
        self.service_patcher.start()
        self.auth_patcher.start()
        self.addCleanup(self.service_patcher.stop)
        self.addCleanup(self.auth_patcher.stop)
        app = FastAPI()
        app.include_router(openai_keys_module.create_router())
        self.client = TestClient(app)

    def test_create_list_check_and_delete_key(self):
        create_response = self.client.post(
            "/api/openai-keys",
            headers=AUTH_HEADERS,
            json={"name": "Project key", "key": "sk-proj-secret"},
        )
        self.assertEqual(create_response.status_code, 200, create_response.text)
        self.assertEqual(create_response.json()["item"]["name"], "Project key")

        list_response = self.client.get("/api/openai-keys", headers=AUTH_HEADERS)
        self.assertEqual(list_response.status_code, 200, list_response.text)
        self.assertEqual(list_response.json()["items"][0]["key_hint"], "sk-proj...1234")

        check_response = self.client.post("/api/openai-keys/key-1/check", headers=AUTH_HEADERS)
        self.assertEqual(check_response.status_code, 200, check_response.text)
        self.assertEqual(check_response.json()["item"]["status"], "ok")
        self.assertEqual(self.fake_service.checked_ids, ["key-1"])

        delete_response = self.client.delete("/api/openai-keys/key-1", headers=AUTH_HEADERS)
        self.assertEqual(delete_response.status_code, 200, delete_response.text)
        self.assertEqual(delete_response.json()["items"], [])


if __name__ == "__main__":
    unittest.main()
