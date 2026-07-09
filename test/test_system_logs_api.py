from __future__ import annotations

import unittest
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

import api.system as system_module


AUTH_HEADERS = {"Authorization": "Bearer test-admin"}


class FakeLogService:
    def __init__(self) -> None:
        self.clear_calls: list[dict[str, str]] = []

    def list(self, type: str = "", start_date: str = "", end_date: str = "", limit: int = 200):
        return []

    def delete(self, ids: list[str]):
        return {"removed": len(ids)}

    def clear(self, type: str = "", start_date: str = "", end_date: str = ""):
        self.clear_calls.append({
            "type": type,
            "start_date": start_date,
            "end_date": end_date,
        })
        return {"removed": 7}


class SystemLogsApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fake_log_service = FakeLogService()
        self.patchers = [
            mock.patch.object(system_module, "log_service", self.fake_log_service),
            mock.patch.object(system_module, "require_admin", lambda _authorization: {"role": "admin"}),
        ]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        app = FastAPI()
        app.include_router(system_module.create_router("9.9.9-test"))
        self.client = TestClient(app)

    def test_clear_logs_endpoint_uses_trimmed_filters(self) -> None:
        response = self.client.post(
            "/api/logs/clear",
            headers=AUTH_HEADERS,
            json={
                "type": " call ",
                "start_date": " 2026-07-01 ",
                "end_date": " 2026-07-02 ",
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"removed": 7})
        self.assertEqual(
            self.fake_log_service.clear_calls,
            [{"type": "call", "start_date": "2026-07-01", "end_date": "2026-07-02"}],
        )


if __name__ == "__main__":
    unittest.main()
