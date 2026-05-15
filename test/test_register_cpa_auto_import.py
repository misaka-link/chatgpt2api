import tempfile
import unittest
from pathlib import Path
from unittest import mock


class RegisterCpaAutoImportConfigTests(unittest.TestCase):
    def test_default_config_includes_cpa_auto_import(self) -> None:
        from services.register_service import _default_config

        config = _default_config()

        self.assertIn("cpa_auto_import", config)
        self.assertFalse(config["cpa_auto_import"]["enabled"])
        self.assertEqual(config["cpa_auto_import"]["base_url"], "http://host.docker.internal:8317")
        self.assertEqual(config["cpa_auto_import"]["secret_key"], "")

    def test_update_preserves_cpa_auto_import(self) -> None:
        from services.register_service import RegisterService

        with tempfile.TemporaryDirectory() as tmp_dir:
            store_file = Path(tmp_dir) / "register.json"
            service = RegisterService(store_file)

            data = service.update(
                {
                    "cpa_auto_import": {
                        "enabled": True,
                        "base_url": "http://host.docker.internal:8317",
                        "secret_key": "secret-key",
                    }
                }
            )

            self.assertTrue(data["cpa_auto_import"]["enabled"])
            self.assertEqual(data["cpa_auto_import"]["base_url"], "http://host.docker.internal:8317")
            self.assertEqual(data["cpa_auto_import"]["secret_key"], "secret-key")

    def test_worker_still_succeeds_when_cpa_push_fails(self) -> None:
        from services.register import openai_register

        class FakeRegistrar:
            def __init__(self, proxy: str = "") -> None:
                self.proxy = proxy

            def register(self, index: int) -> dict:
                return {
                    "email": "deandrea.northey@outlook.com",
                    "access_token": "access-token",
                    "refresh_token": "refresh-token",
                    "id_token": "id-token",
                    "created_at": "2026-05-15T00:00:00+00:00",
                }

            def close(self) -> None:
                return None

        with (
            mock.patch.object(openai_register, "PlatformRegistrar", FakeRegistrar),
            mock.patch.object(openai_register.account_service, "add_accounts", return_value={"added": 1, "skipped": 0, "items": []}),
            mock.patch.object(openai_register.account_service, "refresh_accounts", return_value={"refreshed": 1, "errors": [], "items": []}),
            mock.patch.object(openai_register, "push_cpa_auth_file", return_value={"ok": False, "uploaded": False, "error": "boom"}),
            mock.patch.object(openai_register, "log"),
        ):
            old_cpa = dict(openai_register.config.get("cpa_auto_import") or {})
            old_proxy = openai_register.config.get("proxy", "")
            try:
                openai_register.config["cpa_auto_import"] = {
                    "enabled": True,
                    "base_url": "http://host.docker.internal:8317",
                    "secret_key": "secret-key",
                }
                openai_register.config["proxy"] = ""
                result = openai_register.worker(1)
            finally:
                openai_register.config["cpa_auto_import"] = old_cpa
                openai_register.config["proxy"] = old_proxy

        self.assertTrue(result["ok"])
        self.assertEqual(result["result"]["email"], "deandrea.northey@outlook.com")


if __name__ == "__main__":
    unittest.main()
