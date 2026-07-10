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
    def test_quickjs_browser_shim_supports_dom_storage_and_geometry(self) -> None:
        source = """
var P={getRequirementsToken:function(){return 'REQ';},getRequirementsTokenBlocking:function(){return 'REQ';},getEnforcementToken:function(){return Promise.resolve('POW');},getEnforcementTokenSync:function(){return 'POW';}};
var D=function(){}; var C=function(){return 'id';}; var _n=function(){return Promise.resolve('turnstile');};
var $=function(){return '';}; var Ot=function(fn){return fn();}; var jt=function(){return Promise.resolve(null);}; var Nt=function(){return Promise.resolve('snapshot');};
var Zn='test'; var we=function(){}; var t={}; t.init=we,t.sessionObserverToken=async function(t){return null;}; var SentinelSDK=t;
"""
        runtime = sentinel_utils.SentinelSDKRuntime(
            sentinel_utils._SdkBundle(
                version="test",
                source=source,
                sdk_url="https://sentinel.openai.com/sentinel/test/sdk.js",
            ),
            sentinel_utils.DEFAULT_SENTINEL_USER_AGENT,
        )

        result = json.loads(
            runtime._context.eval(
                """
(function(){
  localStorage.setItem('key', 'value');
  sessionStorage.setItem('session-key', 'session-value');
  var parent = document.createElement('div');
  var child = document.createElement('span');
  parent.appendChild(child);
  var before = parent.children.length;
  parent.removeChild(child);
  var rect = parent.getBoundingClientRect();
  return JSON.stringify({
    storage: localStorage.getItem('key'),
    sessionStorage: sessionStorage.getItem('session-key'),
    before: before,
    after: parent.children.length,
    width: rect.width
  });
})()
"""
            )
        )

        self.assertEqual(
            result,
            {
                "storage": "value",
                "sessionStorage": "session-value",
                "before": 1,
                "after": 0,
                "width": 0,
            },
        )

    def test_build_sentinel_token_returns_sdk_backed_headers(self) -> None:
        class Runtime:
            sdk_bundle = type("SdkBundle", (), {"version": "20260219f9f6"})()

            def __init__(self) -> None:
                self.calls: list[tuple[str, tuple[Any, ...]]] = []

            def call(self, name: str, *args, **kwargs):
                self.calls.append((name, args))
                if name == "getRequirementsToken":
                    return "REQ"
                if name == "makeHandle":
                    return "handle-1"
                if name == "attachRequirements":
                    return None
                if name == "getEnforcementToken":
                    return "POW"
                if name == "runTurnstile":
                    return "turnstile-token"
                if name == "runCollector":
                    return "collector-ok"
                if name == "runSnapshot":
                    return "snapshot-b64"
                raise AssertionError(f"unexpected runtime call: {name}")

        class Session:
            def post(self, *args, **kwargs):
                return FakeResponse(
                    status_code=200,
                    payload={
                        "token": "challenge-token",
                        "proofofwork": {"required": False},
                        "turnstile": {"required": True, "dx": "turnstile-dx"},
                        "so": {
                            "required": True,
                            "collector_dx": "collector-dx",
                            "snapshot_dx": "snapshot-dx",
                        },
                    },
                )

        runtime = Runtime()
        with patch.object(sentinel_utils._runtime_pool, "get_runtime", return_value=runtime):
            sentinel_value, oai_sc_value, so_token = sentinel_utils.build_sentinel_token(
                Session(),
                "device-1",
                "password_verify",
            )

        self.assertEqual(
            json.loads(sentinel_value),
            {
                "p": "POW",
                "t": "turnstile-token",
                "c": "challenge-token",
                "id": "device-1",
                "flow": "password_verify",
            },
        )
        self.assertEqual(oai_sc_value, "0challenge-token")
        self.assertEqual(
            json.loads(so_token),
            {"so": "snapshot-b64", "c": "challenge-token", "id": "device-1", "flow": "password_verify"},
        )

    def test_build_sentinel_token_omits_optional_so_token_when_snapshot_generation_fails(self) -> None:
        class Runtime:
            sdk_bundle = type("SdkBundle", (), {"version": "20260219f9f6"})()

            def call(self, name: str, *args, **kwargs):
                if name == "getRequirementsToken":
                    return "REQ"
                if name == "makeHandle":
                    return "handle-1"
                if name == "attachRequirements":
                    return None
                if name == "getEnforcementToken":
                    return "POW"
                if name == "runTurnstile":
                    return ""
                if name == "runCollector":
                    raise RuntimeError("collector failed")
                if name == "runSnapshot":
                    return ""
                raise AssertionError(f"unexpected runtime call: {name}")

        class Session:
            def post(self, *args, **kwargs):
                return FakeResponse(
                    status_code=200,
                    payload={
                        "token": "challenge-token",
                        "proofofwork": {"required": False},
                    },
                )

        with patch.object(sentinel_utils._runtime_pool, "get_runtime", return_value=Runtime()), patch.object(
            sentinel_utils.logger,
            "warning",
        ) as warning_mock:
            sentinel_value, oai_sc_value, so_token = sentinel_utils.build_sentinel_token(
                Session(),
                "device-1",
                "password_verify",
            )

        self.assertEqual(
            json.loads(sentinel_value),
            {"p": "POW", "t": "", "c": "challenge-token", "id": "device-1", "flow": "password_verify"},
        )
        self.assertEqual(oai_sc_value, "0challenge-token")
        self.assertEqual(so_token, "")
        self.assertTrue(warning_mock.called)

    def test_build_sentinel_token_rejects_required_turnstile_runtime_error(self) -> None:
        encoded_error = base64.b64encode(b"TypeError: Cannot read properties of undefined (reading 'bind')").decode("ascii")

        class Runtime:
            sdk_bundle = type("SdkBundle", (), {"version": "20260219f9f6"})()

            def call(self, name: str, *args, **kwargs):
                if name == "getRequirementsToken":
                    return "REQ"
                if name == "makeHandle":
                    return "handle-1"
                if name == "attachRequirements":
                    return None
                if name == "getEnforcementToken":
                    return "POW"
                if name == "runTurnstile":
                    return encoded_error
                if name == "runCollector":
                    return "collector-ok"
                if name == "runSnapshot":
                    return "snapshot-b64"
                raise AssertionError(f"unexpected runtime call: {name}")

        class Session:
            def post(self, *args, **kwargs):
                return FakeResponse(
                    status_code=200,
                    payload={
                        "token": "challenge-token",
                        "proofofwork": {"required": True},
                        "turnstile": {"required": True, "dx": "turnstile-dx"},
                        "so": {
                            "required": True,
                            "collector_dx": "collector-dx",
                            "snapshot_dx": "snapshot-dx",
                        },
                    },
                )

        with patch.object(sentinel_utils._runtime_pool, "get_runtime", return_value=Runtime()):
            with self.assertRaisesRegex(RuntimeError, "sentinel_turnstile_required_missing"):
                sentinel_utils.build_sentinel_token(
                    Session(),
                    "device-1",
                    "oauth_create_account",
                )

    def test_build_sentinel_token_falls_back_to_dx_interpreter_when_sdk_fails(self) -> None:
        requirements_token = "REQ"
        commands = [[3, "fallback-turnstile-token"]]
        encrypted_commands = "".join(
            chr(ord(char) ^ ord(requirements_token[index % len(requirements_token)]))
            for index, char in enumerate(json.dumps(commands, separators=(",", ":")))
        )
        turnstile_dx = base64.b64encode(encrypted_commands.encode("utf-8")).decode("ascii")

        class Runtime:
            sdk_bundle = type("SdkBundle", (), {"version": "20260219f9f6"})()

            def call(self, name: str, *args, **kwargs):
                if name == "getRequirementsToken":
                    return requirements_token
                if name == "makeHandle":
                    return "handle-1"
                if name == "attachRequirements":
                    return None
                if name == "getEnforcementToken":
                    return "POW"
                if name == "runTurnstile":
                    raise RuntimeError("TypeError: not an object")
                if name == "runCollector":
                    return "collector-ok"
                if name == "runSnapshot":
                    return "snapshot-b64"
                raise AssertionError(f"unexpected runtime call: {name}")

        class Session:
            def post(self, *args, **kwargs):
                return FakeResponse(
                    status_code=200,
                    payload={
                        "token": "challenge-token",
                        "proofofwork": {"required": True},
                        "turnstile": {"required": True, "dx": turnstile_dx},
                        "so": {"required": True, "collector_dx": "collector-dx", "snapshot_dx": "snapshot-dx"},
                    },
                )

        with patch.object(sentinel_utils._runtime_pool, "get_runtime", return_value=Runtime()):
            sentinel_value, _, _ = sentinel_utils.build_sentinel_token(
                Session(),
                "device-1",
                "oauth_create_account",
            )

        self.assertEqual(json.loads(sentinel_value)["t"], "ZmFsbGJhY2stdHVybnN0aWxlLXRva2Vu")

    def test_build_sentinel_token_drops_optional_invalid_turnstile_from_payload(self) -> None:
        encoded_error = base64.b64encode(b"TypeError: Cannot read properties of undefined (reading 'bind')").decode("ascii")

        class Runtime:
            sdk_bundle = type("SdkBundle", (), {"version": "20260219f9f6"})()

            def call(self, name: str, *args, **kwargs):
                if name == "getRequirementsToken":
                    return "REQ"
                if name == "makeHandle":
                    return "handle-1"
                if name == "attachRequirements":
                    return None
                if name == "getEnforcementToken":
                    return "POW"
                if name == "runTurnstile":
                    return encoded_error
                if name == "runCollector":
                    return "collector-ok"
                if name == "runSnapshot":
                    return "snapshot-b64"
                raise AssertionError(f"unexpected runtime call: {name}")

        class Session:
            def post(self, *args, **kwargs):
                return FakeResponse(
                    status_code=200,
                    payload={
                        "token": "challenge-token",
                        "proofofwork": {"required": True},
                        "turnstile": {"required": False, "dx": "turnstile-dx"},
                        "so": {
                            "required": True,
                            "collector_dx": "collector-dx",
                            "snapshot_dx": "snapshot-dx",
                        },
                    },
                )

        with patch.object(sentinel_utils._runtime_pool, "get_runtime", return_value=Runtime()):
            sentinel_value, _, so_token = sentinel_utils.build_sentinel_token(
                Session(),
                "device-1",
                "oauth_create_account",
            )

        self.assertEqual(
            json.loads(sentinel_value),
            {
                "p": "POW",
                "t": "",
                "c": "challenge-token",
                "id": "device-1",
                "flow": "oauth_create_account",
            },
        )
        self.assertEqual(
            json.loads(so_token),
            {"so": "snapshot-b64", "c": "challenge-token", "id": "device-1", "flow": "oauth_create_account"},
        )

    def test_build_sentinel_token_rejects_required_so_when_snapshot_generation_fails(self) -> None:
        class Runtime:
            sdk_bundle = type("SdkBundle", (), {"version": "20260219f9f6"})()

            def call(self, name: str, *args, **kwargs):
                if name == "getRequirementsToken":
                    return "REQ"
                if name == "makeHandle":
                    return "handle-1"
                if name == "attachRequirements":
                    return None
                if name == "getEnforcementToken":
                    return "POW"
                if name == "runTurnstile":
                    return "turnstile-token"
                if name == "runCollector":
                    raise RuntimeError("collector failed")
                if name == "runSnapshot":
                    return ""
                raise AssertionError(f"unexpected runtime call: {name}")

        class Session:
            def post(self, *args, **kwargs):
                return FakeResponse(
                    status_code=200,
                    payload={
                        "token": "challenge-token",
                        "proofofwork": {"required": True},
                        "turnstile": {"required": True, "dx": "turnstile-dx"},
                        "so": {"required": True, "collector_dx": "collector-dx", "snapshot_dx": "snapshot-dx"},
                    },
                )

        with patch.object(sentinel_utils._runtime_pool, "get_runtime", return_value=Runtime()):
            with self.assertRaisesRegex(RuntimeError, "sentinel_so_required_missing"):
                sentinel_utils.build_sentinel_token(
                    Session(),
                    "device-1",
                    "oauth_create_account",
                )


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
