from __future__ import annotations

import unittest
from unittest import mock


class FakeResponse:
    ok = True
    status_code = 200

    def json(self):
        return {"ok": True}


class FakeSession:
    def __init__(self):
        self.calls = []
        self.closed = False

    def post(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return FakeResponse()

    def close(self):
        self.closed = True


class CPAPushServiceTests(unittest.TestCase):
    def test_upload_auth_file_uses_curl_mime_file_field(self):
        from services.cpa_push_service import upload_auth_file

        session = FakeSession()
        mime = mock.Mock()

        with mock.patch("services.cpa_push_service.CurlMime", return_value=mime):
            result = upload_auth_file(
                {"base_url": "http://cpa.local:8317", "secret_key": "secret"},
                "user@example.com.json",
                b'{"type":"codex"}',
                session=session,
            )

        self.assertEqual(result, {"ok": True})
        self.assertEqual(session.calls[0]["url"], "http://cpa.local:8317/v0/management/auth-files")
        self.assertEqual(session.calls[0]["headers"]["Authorization"], "Bearer secret")
        self.assertIs(session.calls[0]["multipart"], mime)
        mime.addpart.assert_called_once_with(
            name="file",
            filename="user@example.com.json",
            content_type="application/json",
            data=b'{"type":"codex"}',
        )
        mime.close.assert_called_once()

    def test_local_cpa_urls_bypass_global_proxy(self):
        from services.proxy_service import proxy_settings

        with mock.patch("services.proxy_service.config.get_proxy_settings", return_value="http://proxy.local:7890"):
            kwargs = proxy_settings.build_session_kwargs_for_url("http://host.docker.internal:8317/v0/management/auth-files", verify=True)

        self.assertEqual(kwargs, {"verify": True})

    def test_remote_cpa_urls_keep_global_proxy(self):
        from services.proxy_service import proxy_settings

        with mock.patch("services.proxy_service.config.get_proxy_settings", return_value="http://proxy.local:7890"):
            kwargs = proxy_settings.build_session_kwargs_for_url("https://cpa.example.test/v0/management/auth-files", verify=True)

        self.assertEqual(kwargs, {"verify": True, "proxy": "http://proxy.local:7890"})


if __name__ == "__main__":
    unittest.main()
