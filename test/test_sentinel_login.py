import base64
import json
import unittest
from typing import Any
from unittest.mock import patch

import services.account_service as account_service_module
from services.account_service import AccountService
from utils import sentinel as sentinel_utils


class MemoryStorage:
    def load_accounts(self) -> list[dict[str, Any]]:
        return []

    def save_accounts(self, accounts: list[dict[str, Any]]) -> None:
        pass

    def load_auth_keys(self) -> list[dict[str, Any]]:
        return []

    def save_auth_keys(self, auth_keys: list[dict[str, Any]]) -> None:
        pass

    def health_check(self) -> dict[str, Any]:
        return {"ok": True}

    def get_backend_info(self) -> dict[str, Any]:
        return {"type": "memory"}


def make_jwt(payload: dict[str, Any]) -> str:
    def encode(value: dict[str, Any]) -> str:
        raw = json.dumps(value, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    return f'{encode({"alg": "none", "typ": "JWT"})}.{encode(payload)}.sig'


class FakeResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        payload: dict[str, Any] | None = None,
        text: str | None = None,
        url: str = "https://auth.openai.com/email-verification",
        json_error: Exception | None = None,
    ) -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self._json_error = json_error
        self.text = text if text is not None else json.dumps(self._payload)
        self.url = url
        self.headers = {}

    def json(self) -> dict[str, Any]:
        if self._json_error is not None:
            raise self._json_error
        return dict(self._payload)


class FakeCookieJar:
    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []

    def set(self, name: str, value: str, domain: str | None = None) -> None:
        self.items.append({"name": name, "value": value, "domain": domain})


class FakeSession:
    def __init__(self, access_token: str) -> None:
        self.access_token = access_token
        self.cookies = FakeCookieJar()
        self.headers = {}
        self.post_calls: list[dict[str, Any]] = []
        self.get_calls: list[dict[str, Any]] = []
        self.closed = False

    def get(self, url: str, headers: dict[str, str] | None = None, **kwargs) -> FakeResponse:
        self.get_calls.append({"url": url, "headers": dict(headers or {}), "kwargs": kwargs})
        if "api/accounts/authorize" in url:
            return FakeResponse(status_code=200, text="authorize-ok", url="https://auth.openai.com/email-verification")
        if url == "https://chatgpt.com/backend-api/me":
            return FakeResponse(status_code=200, payload={"account": {"account_id": "acct_from_me"}})
        raise AssertionError(f"unexpected GET url: {url}")

    def post(self, url: str, headers: dict[str, str] | None = None, json: dict[str, Any] | None = None, **kwargs) -> FakeResponse:
        self.post_calls.append({"url": url, "headers": dict(headers or {}), "json": dict(json or {}), "kwargs": kwargs})
        if url.endswith("/api/accounts/password/verify"):
            return FakeResponse(
                status_code=200,
                payload={"continue_url": "https://platform.openai.com/auth/callback?code=test-auth-code"},
            )
        if url.endswith("/api/accounts/oauth/token"):
            return FakeResponse(
                status_code=200,
                payload={
                    "access_token": self.access_token,
                    "refresh_token": "refresh-token",
                    "id_token": "id-token",
                },
            )
        raise AssertionError(f"unexpected POST url: {url}")

    def close(self) -> None:
        self.closed = True


class SentinelTokenTests(unittest.TestCase):
    def test_build_sentinel_token_returns_so_token_when_present(self) -> None:
        class Session:
            def post(self, *args, **kwargs):
                return FakeResponse(
                    status_code=200,
                    payload={
                        "token": "challenge-token",
                        "proofofwork": {"required": False},
                        "so_token": "so-token",
                    },
                )

        with patch.object(sentinel_utils.SentinelTokenGenerator, "generate_requirements_token", return_value="REQ"):
            sentinel_value, oai_sc_value, so_token = sentinel_utils.build_sentinel_token(
                Session(),
                "device-1",
                "password_verify",
            )

        self.assertEqual(
            json.loads(sentinel_value),
            {"p": "REQ", "t": "", "c": "challenge-token", "id": "device-1", "flow": "password_verify"},
        )
        self.assertEqual(oai_sc_value, "0challenge-token")
        self.assertEqual(so_token, "so-token")

    def test_build_sentinel_token_fallback_keeps_three_tuple_shape(self) -> None:
        class Session:
            def post(self, *args, **kwargs):
                return FakeResponse(status_code=200, text="not-json", json_error=ValueError("bad json"))

        with patch.object(sentinel_utils.SentinelTokenGenerator, "generate_requirements_token", return_value="REQ"):
            sentinel_value, oai_sc_value, so_token = sentinel_utils.build_sentinel_token(
                Session(),
                "device-1",
                "password_verify",
            )

        self.assertEqual(
            json.loads(sentinel_value),
            {"p": "REQ", "t": "", "c": "", "id": "device-1", "flow": "password_verify"},
        )
        self.assertEqual(oai_sc_value, "")
        self.assertEqual(so_token, "")


class AccountPasswordLoginTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = AccountService(MemoryStorage())
        self.access_token = make_jwt(
            {
                "exp": 4102444800,
                "https://api.openai.com/auth": {"chatgpt_account_id": "acct_from_jwt"},
                "https://api.openai.com/profile": {"email": "jwt@example.com"},
            }
        )

    def test_login_with_password_adds_so_token_header_when_present(self) -> None:
        fake_session = FakeSession(self.access_token)

        with patch("curl_cffi.requests.Session", return_value=fake_session), patch(
            "utils.pkce.generate_pkce",
            return_value=("verifier", "challenge"),
        ), patch("utils.sentinel.build_sentinel_token", return_value=("sentinel-token", "oai-cookie", "so-token")), patch.object(
            account_service_module.config,
            "get_proxy_settings",
            return_value="",
        ):
            result = self.service._login_with_password("user@example.com", "password")

        self.assertTrue(result["ok"])
        self.assertEqual(fake_session.post_calls[0]["headers"]["openai-sentinel-token"], "sentinel-token")
        self.assertEqual(fake_session.post_calls[0]["headers"]["OpenAI-Sentinel-SO-Token"], "so-token")
        self.assertIn({"name": "oai-sc", "value": "oai-cookie", "domain": ".openai.com"}, fake_session.cookies.items)
        self.assertTrue(fake_session.closed)

    def test_login_with_password_skips_so_token_header_when_absent(self) -> None:
        fake_session = FakeSession(self.access_token)

        with patch("curl_cffi.requests.Session", return_value=fake_session), patch(
            "utils.pkce.generate_pkce",
            return_value=("verifier", "challenge"),
        ), patch("utils.sentinel.build_sentinel_token", return_value=("sentinel-token", "oai-cookie", "")), patch.object(
            account_service_module.config,
            "get_proxy_settings",
            return_value="",
        ):
            result = self.service._login_with_password("user@example.com", "password")

        self.assertTrue(result["ok"])
        self.assertEqual(fake_session.post_calls[0]["headers"]["openai-sentinel-token"], "sentinel-token")
        self.assertNotIn("OpenAI-Sentinel-SO-Token", fake_session.post_calls[0]["headers"])
        self.assertIn({"name": "oai-sc", "value": "oai-cookie", "domain": ".openai.com"}, fake_session.cookies.items)
        self.assertTrue(fake_session.closed)


if __name__ == "__main__":
    unittest.main()
