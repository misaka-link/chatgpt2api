from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from services.log_service import LOG_TYPE_ACCOUNT, LOG_TYPE_CALL, LogService


class LogServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.path = Path(self.temp_dir.name) / "logs.jsonl"
        self.service = LogService(self.path)

    def write_lines(self, *lines: str) -> None:
        content = "\n".join(lines)
        if content:
            content += "\n"
        self.path.write_text(content, encoding="utf-8")

    @staticmethod
    def dump(item: dict[str, object]) -> str:
        return json.dumps(item, ensure_ascii=False, separators=(",", ":"))

    def test_clear_respects_type_and_date_filters(self) -> None:
        self.write_lines(
            self.dump({"id": "call-1", "time": "2026-07-01T01:00:00+00:00", "type": LOG_TYPE_CALL, "summary": "keep"}),
            self.dump({"id": "call-2", "time": "2026-07-02T01:00:00+00:00", "type": LOG_TYPE_CALL, "summary": "remove"}),
            self.dump({"id": "account-1", "time": "2026-07-02T02:00:00+00:00", "type": LOG_TYPE_ACCOUNT, "summary": "keep"}),
        )

        result = self.service.clear(type=LOG_TYPE_CALL, start_date="2026-07-02", end_date="2026-07-02")

        self.assertEqual(result, {"removed": 1})
        remaining = [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([item["id"] for item in remaining], ["call-1", "account-1"])

    def test_clear_all_keeps_unparseable_lines(self) -> None:
        self.write_lines(
            "not-json",
            self.dump({"id": "call-1", "time": "2026-07-02T01:00:00+00:00", "type": LOG_TYPE_CALL, "summary": "remove"}),
            self.dump({"id": "account-1", "time": "2026-07-02T02:00:00+00:00", "type": LOG_TYPE_ACCOUNT, "summary": "remove"}),
        )

        result = self.service.clear()

        self.assertEqual(result, {"removed": 2})
        self.assertEqual(self.path.read_text(encoding="utf-8"), "not-json\n")


if __name__ == "__main__":
    unittest.main()
