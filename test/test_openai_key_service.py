import tempfile
import unittest
from pathlib import Path


class OpenAIKeyServiceTests(unittest.TestCase):
    def test_add_key_redacts_secret_in_list_output(self) -> None:
        from services.api_key_service import OpenAIKeyService

        with tempfile.TemporaryDirectory() as tmp_dir:
            service = OpenAIKeyService(Path(tmp_dir) / "api_keys.json", checker=lambda _: {"status": "unchecked"})

            item = service.add_key("main project", "sk-proj-abcdefghijklmnopqrstuvwxyz1234567890")
            listed = service.list_keys()

            self.assertEqual(item["name"], "main project")
            self.assertEqual(listed[0]["id"], item["id"])
            self.assertNotIn("key", listed[0])
            self.assertNotIn("abcdefghijklmnopqrstuvwxyz", str(listed[0]))
            self.assertTrue(listed[0]["key_hint"].startswith("sk-"))
            self.assertEqual(listed[0]["status"], "unchecked")

    def test_add_key_rejects_duplicate_secret(self) -> None:
        from services.api_key_service import OpenAIKeyService

        with tempfile.TemporaryDirectory() as tmp_dir:
            service = OpenAIKeyService(Path(tmp_dir) / "api_keys.json", checker=lambda _: {"status": "unchecked"})
            service.add_key("one", "sk-test-duplicate-secret")

            with self.assertRaises(ValueError) as ctx:
                service.add_key("two", "sk-test-duplicate-secret")

            self.assertIn("already exists", str(ctx.exception))

    def test_check_key_updates_status_and_model_summary(self) -> None:
        from services.api_key_service import OpenAIKeyService

        with tempfile.TemporaryDirectory() as tmp_dir:
            service = OpenAIKeyService(
                Path(tmp_dir) / "api_keys.json",
                checker=lambda _: {
                    "status": "ok",
                    "models_count": 2,
                    "sample_models": ["gpt-4.1-mini", "gpt-4.1"],
                    "last_error": None,
                },
            )
            item = service.add_key("project", "sk-test-check-secret")

            checked = service.check_key(item["id"])

            self.assertEqual(checked["status"], "ok")
            self.assertEqual(checked["models_count"], 2)
            self.assertEqual(checked["sample_models"], ["gpt-4.1-mini", "gpt-4.1"])
            self.assertIsNone(checked["last_error"])
            self.assertTrue(checked["last_checked_at"])


if __name__ == "__main__":
    unittest.main()
