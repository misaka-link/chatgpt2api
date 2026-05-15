import json
import unittest
from unittest import mock


class FakeResponse:
    def __init__(self, status_code: int = 200, payload: dict | None = None) -> None:
        self.status_code = status_code
        self.ok = status_code < 400
        self._payload = payload or {"status": "ok"}
        self.text = json.dumps(self._payload, ensure_ascii=False)

    def json(self) -> dict:
        return dict(self._payload)


class FakeSession:
    last_instance = None

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.calls: list[dict] = []
        FakeSession.last_instance = self

    def post(self, url, headers=None, files=None, multipart=None, timeout=None):
        self.calls.append(
            {
                "url": url,
                "headers": headers,
                "files": files,
                "multipart": multipart,
                "timeout": timeout,
            }
        )
        return FakeResponse()

    def close(self):
        return None


class FakeMultipart:
    last_instance = None

    def __init__(self) -> None:
        self.parts: list[dict] = []
        self.closed = False
        FakeMultipart.last_instance = self

    def addpart(self, **kwargs):
        self.parts.append(dict(kwargs))

    def close(self):
        self.closed = True


class CpaPushServiceTests(unittest.TestCase):
    def test_build_cpa_upload_file_uses_full_register_result(self) -> None:
        from services.cpa_push_service import build_cpa_upload_file

        filename, content = build_cpa_upload_file(
            {
                "email": "deandrea.northey@outlook.com",
                "access_token": "access-token",
                "refresh_token": "refresh-token",
                "id_token": "id-token",
            },
            {
                "user_id": "user-123",
                "status": "正常",
            },
        )

        payload = json.loads(content.decode("utf-8"))
        self.assertEqual(filename, "deandrea.northey@outlook.com.json")
        self.assertEqual(payload["access_token"], "access-token")
        self.assertEqual(payload["refresh_token"], "refresh-token")
        self.assertEqual(payload["id_token"], "id-token")
        self.assertEqual(payload["email"], "deandrea.northey@outlook.com")
        self.assertEqual(payload["account_id"], "user-123")
        self.assertFalse(payload["disabled"])

    def test_push_cpa_auth_file_posts_multipart_to_management_api(self) -> None:
        with mock.patch("services.cpa_push_service.Session", FakeSession), mock.patch(
            "services.cpa_push_service.CurlMime",
            FakeMultipart,
        ), mock.patch(
            "services.cpa_push_service.proxy_settings.build_session_kwargs",
            return_value={"verify": True},
        ):
            from services.cpa_push_service import push_cpa_auth_file

            result = push_cpa_auth_file(
                {
                    "email": "deandrea.northey@outlook.com",
                    "access_token": "access-token",
                    "refresh_token": "refresh-token",
                    "id_token": "id-token",
                },
                {
                    "enabled": True,
                    "base_url": "http://host.docker.internal:8317",
                    "secret_key": "secret-key",
                },
            )

        self.assertTrue(result["ok"])
        self.assertTrue(result["uploaded"])
        self.assertEqual(result["name"], "deandrea.northey@outlook.com.json")

        session = FakeSession.last_instance
        self.assertIsNotNone(session)
        self.assertEqual(session.calls[0]["url"], "http://host.docker.internal:8317/v0/management/auth-files")
        self.assertEqual(session.calls[0]["headers"]["Authorization"], "Bearer secret-key")
        self.assertIsNone(session.calls[0]["files"])

        multipart = FakeMultipart.last_instance
        self.assertIs(session.calls[0]["multipart"], multipart)
        self.assertEqual(multipart.parts[0]["name"], "file")
        self.assertEqual(multipart.parts[0]["filename"], "deandrea.northey@outlook.com.json")
        self.assertEqual(multipart.parts[0]["content_type"], "application/json")
        self.assertIsInstance(multipart.parts[0]["data"], (bytes, bytearray))
        self.assertIn(b'"access_token": "access-token"', multipart.parts[0]["data"])
        self.assertTrue(multipart.closed)


if __name__ == "__main__":
    unittest.main()
