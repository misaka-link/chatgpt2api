from __future__ import annotations

import unittest

from services.protocol import openai_v1_models


class _FakeAccountService:
    def __init__(self, token: str, accounts: list[dict] | None = None) -> None:
        self.token = token
        self.accounts = accounts or []

    def peek_text_access_token(self) -> str:
        return self.token

    def list_accounts(self) -> list[dict]:
        return self.accounts

    @staticmethod
    def _normalize_source_type(value: object) -> str:
        return str(value or "web").strip().lower() or "web"

    @staticmethod
    def _normalize_account_type(value: object) -> str:
        raw = str(value or "").strip()
        return {"plus": "Plus", "team": "Team", "pro": "Pro"}.get(raw.lower(), raw)


class ModelListFallbackTests(unittest.TestCase):
    def test_list_models_uses_pool_token_when_available(self) -> None:
        calls: list[str] = []

        class FakeBackend:
            def __init__(self, access_token: str = "") -> None:
                calls.append(access_token)

            def list_models(self) -> dict:
                return {"object": "list", "data": [{"id": "gpt-5", "object": "model"}]}

        original_backend = openai_v1_models.OpenAIBackendAPI
        original_account_service = openai_v1_models.account_service
        try:
            openai_v1_models.OpenAIBackendAPI = FakeBackend
            openai_v1_models.account_service = _FakeAccountService("pool-token")

            result = openai_v1_models.list_models()
        finally:
            openai_v1_models.OpenAIBackendAPI = original_backend
            openai_v1_models.account_service = original_account_service

        self.assertEqual(calls, ["pool-token"])
        model_ids = {item["id"] for item in result["data"]}
        self.assertIn("gpt-5", model_ids)
        self.assertIn("auto", model_ids)

    def test_list_models_falls_back_to_anonymous_when_pool_probe_fails(self) -> None:
        calls: list[str] = []

        class FakeBackend:
            def __init__(self, access_token: str = "") -> None:
                self.access_token = access_token
                calls.append(access_token)

            def list_models(self) -> dict:
                if self.access_token:
                    raise RuntimeError("auth_models: HTTP 401")
                return {"object": "list", "data": [{"id": "auto", "object": "model"}]}

        original_backend = openai_v1_models.OpenAIBackendAPI
        original_account_service = openai_v1_models.account_service
        try:
            openai_v1_models.OpenAIBackendAPI = FakeBackend
            openai_v1_models.account_service = _FakeAccountService("bad-pool-token")

            result = openai_v1_models.list_models()
        finally:
            openai_v1_models.OpenAIBackendAPI = original_backend
            openai_v1_models.account_service = original_account_service

        self.assertEqual(calls, ["bad-pool-token", ""])
        model_ids = {item["id"] for item in result["data"]}
        self.assertIn("auto", model_ids)

    def test_list_models_uses_local_catalog_when_remote_model_discovery_fails(self) -> None:
        calls: list[str] = []

        class FakeBackend:
            def __init__(self, access_token: str = "") -> None:
                calls.append(access_token)

            def list_models(self) -> dict:
                raise RuntimeError("bootstrap failed: status=403")

        original_backend = openai_v1_models.OpenAIBackendAPI
        original_account_service = openai_v1_models.account_service
        try:
            openai_v1_models.OpenAIBackendAPI = FakeBackend
            openai_v1_models.account_service = _FakeAccountService("blocked-pool-token")

            result = openai_v1_models.list_models()
        finally:
            openai_v1_models.OpenAIBackendAPI = original_backend
            openai_v1_models.account_service = original_account_service

        self.assertEqual(calls, ["blocked-pool-token", ""])
        model_ids = {item["id"] for item in result["data"]}
        self.assertIn("auto", model_ids)
        self.assertIn("gpt-5", model_ids)
        self.assertIn("gpt-image-2", model_ids)
        self.assertIn("codex-gpt-image-2", model_ids)


if __name__ == "__main__":
    unittest.main()
