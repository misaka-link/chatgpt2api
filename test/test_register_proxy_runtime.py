import unittest
from unittest.mock import patch

from services.proxy_service import ClearanceBundle
from services.register import openai_register


class FakeResponse:
    def __init__(self, status_code=200, text="", headers=None, url="https://auth.openai.com/test", payload=None):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}
        self.url = url
        self._payload = payload or {}

    def json(self):
        return dict(self._payload)


class FakeCookieJar:
    def __init__(self):
        self.items = []

    def set(self, name, value, domain=None):
        self.items.append({"name": name, "value": value, "domain": domain})


class FakeSession:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.headers = {}
        self.cookies = FakeCookieJar()
        self.closed = False

    def close(self):
        self.closed = True


class FakeProxySettings:
    def __init__(self, bundle=None):
        self.bundle = bundle
        self.refreshed = False
        self.session_kwargs_calls = []
        self.build_headers_calls = []
        self.refresh_calls = []

    def build_session_kwargs(self, **kwargs):
        self.session_kwargs_calls.append(kwargs)
        return dict(kwargs, proxy="http://runtime.example:8118")

    def build_headers(self, headers=None, target_url="", proxy="", upstream=True, **kwargs):
        self.build_headers_calls.append({"target_url": target_url, "proxy": proxy, "upstream": upstream})
        merged = dict(headers or {})
        if self.refreshed and self.bundle and self.bundle.cookies:
            merged["Cookie"] = "; ".join(f"{key}={value}" for key, value in self.bundle.cookies.items())
        return merged

    def refresh_clearance(self, target_url="", proxy="", force=False, upstream=True, **kwargs):
        self.refresh_calls.append({"target_url": target_url, "proxy": proxy, "force": force, "upstream": upstream})
        self.refreshed = self.bundle is not None
        return self.bundle


class RegisterProxyRuntimeTests(unittest.TestCase):
    def test_apply_sentinel_headers_includes_so_token_when_present(self):
        headers = {"accept": "application/json"}

        session = FakeSession()
        with patch.object(openai_register, "build_sentinel_token", return_value=("sentinel-token", "oai-cookie", "so-token")):
            openai_register._apply_sentinel_headers(headers, session, "device-1", "authorize_continue")

        self.assertEqual(headers["openai-sentinel-token"], "sentinel-token")
        self.assertEqual(headers["OpenAI-Sentinel-SO-Token"], "so-token")
        self.assertIn({"name": "oai-sc", "value": "oai-cookie", "domain": ".openai.com"}, session.cookies.items)

    def test_apply_sentinel_headers_skips_so_token_when_absent(self):
        headers = {"accept": "application/json"}

        session = FakeSession()
        with patch.object(openai_register, "build_sentinel_token", return_value=("sentinel-token", "oai-cookie", "")):
            openai_register._apply_sentinel_headers(headers, session, "device-1", "authorize_continue")

        self.assertEqual(headers["openai-sentinel-token"], "sentinel-token")
        self.assertNotIn("OpenAI-Sentinel-SO-Token", headers)
        self.assertIn({"name": "oai-sc", "value": "oai-cookie", "domain": ".openai.com"}, session.cookies.items)

    def test_authorize_continue_posts_browser_aligned_payload(self):
        request_calls = []

        def fake_request(session, method, url, retry_attempts=3, **kwargs):
            request_calls.append({"method": method, "url": url, "json": kwargs.get("json"), "headers": dict(kwargs.get("headers") or {})})
            return (
                FakeResponse(
                    status_code=200,
                    payload={
                        "continue_url": "https://auth.openai.com/create-account/password",
                        "page": {"type": "create_account_password"},
                    },
                ),
                "",
            )

        with patch.object(openai_register, "create_session", return_value=FakeSession()), patch.object(
            openai_register,
            "_apply_sentinel_headers",
        ) as sentinel_mock, patch.object(openai_register, "request_with_local_retry", side_effect=fake_request):
            registrar = openai_register.PlatformRegistrar(proxy="")
            registrar._authorize_continue("user@example.com", 1)

        self.assertEqual(len(request_calls), 1)
        self.assertEqual(request_calls[0]["method"], "post")
        self.assertTrue(request_calls[0]["url"].endswith("/api/accounts/authorize/continue"))
        self.assertEqual(
            request_calls[0]["json"],
            {"username": {"value": "user@example.com", "kind": "email"}, "screen_hint": "signup"},
        )
        self.assertEqual(request_calls[0]["headers"]["referer"], f"{openai_register.auth_base}/create-account")
        sentinel_mock.assert_called_once()

    def test_skip_passkey_enrollment_posts_official_skip_endpoint(self):
        request_calls = []

        def fake_request(session, method, url, retry_attempts=3, **kwargs):
            request_calls.append({"method": method, "url": url, "headers": dict(kwargs.get("headers") or {})})
            return (
                FakeResponse(
                    status_code=200,
                    payload={
                        "continue_url": "https://platform.openai.com/auth/callback?code=after-skip",
                    },
                ),
                "",
            )

        with patch.object(openai_register, "create_session", return_value=FakeSession()), patch.object(
            openai_register,
            "request_with_local_retry",
            side_effect=fake_request,
        ):
            registrar = openai_register.PlatformRegistrar(proxy="")
            continue_url = registrar._skip_passkey_enrollment(1)

        self.assertEqual(continue_url, "https://platform.openai.com/auth/callback?code=after-skip")
        self.assertEqual(len(request_calls), 1)
        self.assertEqual(request_calls[0]["method"], "post")
        self.assertTrue(request_calls[0]["url"].endswith("/api/accounts/create-account/passkey/enrollment/skip"))
        self.assertEqual(request_calls[0]["headers"]["referer"], f"{openai_register.auth_base}/create-account-enroll-passkey")

    def test_create_account_skips_passkey_upsell_before_extracting_oauth_code(self):
        responses = [
            (
                FakeResponse(
                    status_code=200,
                    payload={"continue_url": "https://auth.openai.com/create-account-enroll-passkey"},
                ),
                "",
            ),
        ]

        with patch.object(openai_register, "create_session", return_value=FakeSession()), patch.object(
            openai_register,
            "_apply_sentinel_headers",
        ), patch.object(
            openai_register,
            "request_with_local_retry",
            side_effect=responses,
        ), patch.object(
            openai_register.PlatformRegistrar,
            "_skip_passkey_enrollment",
            return_value="https://platform.openai.com/auth/callback?code=from-passkey-skip",
        ) as skip_mock:
            registrar = openai_register.PlatformRegistrar(proxy="")
            registrar._create_account("Test User", "2000-01-01", 1)

        skip_mock.assert_called_once_with(1)
        self.assertEqual(registrar.platform_auth_code, "from-passkey-skip")

    def test_register_flow_calls_authorize_continue_before_password_submit(self):
        registrar = openai_register.PlatformRegistrar(proxy="")
        call_order = []

        def record(name, return_value=None):
            def _inner(*args, **kwargs):
                call_order.append(name)
                return return_value

            return _inner

        mailbox = {"address": "user@example.com", "provider": "mock", "provider_ref": "mock-ref", "domain": "example.com"}
        tokens = {"access_token": "at", "refresh_token": "rt", "id_token": "it"}

        with patch.object(openai_register, "create_mailbox", return_value=mailbox), patch.object(
            openai_register,
            "wait_for_code",
            return_value="123456",
        ), patch.object(openai_register.mail_provider, "mark_mailbox_result", return_value={}), patch.object(
            registrar,
            "_platform_authorize",
            side_effect=record("platform_authorize"),
        ), patch.object(
            registrar,
            "_authorize_continue",
            side_effect=record("authorize_continue"),
        ), patch.object(
            registrar,
            "_register_user",
            side_effect=record("register_user"),
        ), patch.object(
            registrar,
            "_send_otp",
            side_effect=record("send_otp"),
        ), patch.object(
            registrar,
            "_validate_otp",
            side_effect=record("validate_otp"),
        ), patch.object(
            registrar,
            "_create_account",
            side_effect=record("create_account"),
        ), patch.object(
            registrar,
            "_exchange_registered_tokens",
            side_effect=record("exchange_tokens", tokens),
        ):
            result = registrar.register(1)

        self.assertEqual(result["email"], "user@example.com")
        self.assertEqual(
            call_order,
            [
                "platform_authorize",
                "authorize_continue",
                "register_user",
                "send_otp",
                "validate_otp",
                "create_account",
                "exchange_tokens",
            ],
        )

    def test_create_session_uses_proxy_settings_without_breaking_existing_proxy_argument(self):
        fake_proxy = FakeProxySettings()
        created = []

        def fake_session_factory(**kwargs):
            session = FakeSession(**kwargs)
            created.append(session)
            return session

        with patch.object(openai_register, "proxy_settings", fake_proxy), patch.object(
            openai_register.requests,
            "Session",
            side_effect=fake_session_factory,
        ):
            session = openai_register.create_session("http://legacy-register.example:8080")

        self.assertIs(session, created[0])
        self.assertEqual(fake_proxy.session_kwargs_calls[0]["proxy"], "http://legacy-register.example:8080")
        self.assertTrue(fake_proxy.session_kwargs_calls[0]["upstream"])
        self.assertEqual(fake_proxy.session_kwargs_calls[0]["impersonate"], "chrome")
        self.assertFalse(fake_proxy.session_kwargs_calls[0]["verify"])
        self.assertEqual(session.kwargs["proxy"], "http://runtime.example:8118")

    def test_cloudflare_without_clearance_keeps_clear_register_error(self):
        fake_proxy = FakeProxySettings(bundle=None)
        cf_response = FakeResponse(
            status_code=403,
            text="<html><title>Just a moment...</title></html>",
            headers={"server": "cloudflare", "content-type": "text/html"},
            url="https://auth.openai.com/api/accounts/authorize",
        )

        with patch.object(openai_register, "proxy_settings", fake_proxy), patch.object(
            openai_register,
            "create_session",
            return_value=FakeSession(),
        ), patch.object(openai_register, "request_with_local_retry", return_value=(cf_response, "")):
            registrar = openai_register.PlatformRegistrar(proxy="http://legacy-register.example:8080")
            with self.assertRaisesRegex(RuntimeError, "Cloudflare") as ctx:
                registrar._platform_authorize("user@example.com", 1)

        self.assertEqual(len(fake_proxy.refresh_calls), 1)
        self.assertIn("status=403", str(ctx.exception))
        self.assertIn("Just a moment", str(ctx.exception))

    def test_openai_html_behind_cloudflare_is_not_treated_as_challenge(self):
        response = FakeResponse(
            status_code=200,
            text="""
            <!DOCTYPE html><html lang=\"en-US\"><head>
            <title>Create a password - OpenAI</title>
            </head><body>OpenAI account page</body></html>
            """,
            headers={"server": "cloudflare", "content-type": "text/html; charset=utf-8"},
            url="https://auth.openai.com/create-account/password",
        )

        self.assertFalse(openai_register._is_cloudflare_challenge(response))

    def test_cloudflare_challenge_refreshes_clearance_and_retries_once_with_matching_headers(self):
        bundle = ClearanceBundle(
            target_host="auth.openai.com",
            proxy_url="http://runtime.example:8118",
            cookies={"cf_clearance": "flare-token"},
            user_agent="Flare UA",
        )
        fake_proxy = FakeProxySettings(bundle=bundle)
        responses = [
            FakeResponse(
                status_code=403,
                text="<html><title>Just a moment...</title></html>",
                headers={"server": "cloudflare", "content-type": "text/html"},
                url="https://auth.openai.com/api/accounts/authorize",
            ),
            FakeResponse(status_code=200, text="{}", headers={"content-type": "application/json"}),
        ]
        request_calls = []

        def fake_request(session, method, url, retry_attempts=3, **kwargs):
            request_calls.append({"method": method, "url": url, "headers": dict(kwargs.get("headers") or {})})
            return responses.pop(0), ""

        with patch.object(openai_register, "proxy_settings", fake_proxy), patch.object(
            openai_register,
            "create_session",
            return_value=FakeSession(),
        ), patch.object(openai_register, "request_with_local_retry", side_effect=fake_request):
            registrar = openai_register.PlatformRegistrar(proxy="http://legacy-register.example:8080")
            registrar._platform_authorize("user@example.com", 1)

        self.assertEqual(len(request_calls), 2)
        self.assertEqual(len(fake_proxy.refresh_calls), 1)
        retry_headers = {key.lower(): value for key, value in request_calls[1]["headers"].items()}
        self.assertEqual(retry_headers["user-agent"], "Flare UA")
        self.assertEqual(retry_headers["cookie"], "cf_clearance=flare-token")
        self.assertEqual(fake_proxy.refresh_calls[0]["target_url"], openai_register.auth_base)
        self.assertEqual(fake_proxy.refresh_calls[0]["proxy"], "http://legacy-register.example:8080")
        self.assertTrue(fake_proxy.refresh_calls[0]["force"])

    def test_refresh_failure_reports_cloudflare_detail_without_infinite_retry(self):
        fake_proxy = FakeProxySettings(bundle=None)
        cf_response = FakeResponse(
            status_code=403,
            text="<html><title>Just a moment...</title><body>challenge body</body></html>",
            headers={"server": "cloudflare", "content-type": "text/html"},
            url="https://auth.openai.com/api/accounts/authorize",
        )
        request_calls = []

        def fake_request(session, method, url, retry_attempts=3, **kwargs):
            request_calls.append({"method": method, "url": url})
            return cf_response, ""

        with patch.object(openai_register, "proxy_settings", fake_proxy), patch.object(
            openai_register,
            "create_session",
            return_value=FakeSession(),
        ), patch.object(openai_register, "request_with_local_retry", side_effect=fake_request):
            registrar = openai_register.PlatformRegistrar(proxy="")
            with self.assertRaisesRegex(RuntimeError, "Cloudflare") as ctx:
                registrar._platform_authorize("user@example.com", 1)

        self.assertEqual(len(request_calls), 1)
        self.assertEqual(len(fake_proxy.refresh_calls), 1)
        message = str(ctx.exception)
        self.assertIn("status=403", message)
        self.assertIn("challenge body", message)


if __name__ == "__main__":
    unittest.main()
