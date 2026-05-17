from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.account_service import AccountService
from services.register import openai_register
from services.storage.json_storage import JSONStorageBackend


class AccountPasswordRecordingTests(unittest.TestCase):
    def test_add_accounts_still_accepts_plain_token_strings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = AccountService(JSONStorageBackend(Path(tmp_dir) / "accounts.json"))

            result = service.add_accounts(["token-1", "token-1", "token-2"])

            self.assertEqual(result["added"], 2)
            self.assertEqual(result["skipped"], 0)
            self.assertEqual(service.list_tokens(), ["token-1", "token-2"])

    def test_add_accounts_can_persist_registered_password_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = AccountService(JSONStorageBackend(Path(tmp_dir) / "accounts.json"))

            service.add_accounts(
                [
                    {
                        "access_token": "token-1",
                        "email": "user@example.com",
                        "password": "RandomPassword1!",
                    }
                ]
            )

            account = service.get_account("token-1")

            self.assertIsNotNone(account)
            self.assertEqual(account["email"], "user@example.com")
            self.assertEqual(account["password"], "RandomPassword1!")

    def test_account_update_preserves_existing_password_when_refresh_has_no_password(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = AccountService(JSONStorageBackend(Path(tmp_dir) / "accounts.json"))
            service.add_accounts(
                [
                    {
                        "access_token": "token-1",
                        "email": "user@example.com",
                        "password": "RandomPassword1!",
                    }
                ]
            )

            updated = service.update_account("token-1", {"status": "正常", "quota": 10})

            self.assertIsNotNone(updated)
            self.assertEqual(updated["password"], "RandomPassword1!")

    def test_register_worker_sends_email_and_password_to_account_store(self) -> None:
        result = {
            "email": "ok@example.com",
            "password": "RandomPassword1!",
            "access_token": "token-1",
            "refresh_token": "refresh-1",
            "id_token": "id-1",
            "mail_provider": "yyds_mail",
            "mail_domain": "example.com",
        }

        with (
            mock.patch.object(openai_register.PlatformRegistrar, "register", return_value=result),
            mock.patch.object(openai_register.PlatformRegistrar, "close"),
            mock.patch.object(openai_register.account_service, "add_accounts") as add_accounts,
            mock.patch.object(openai_register.account_service, "refresh_accounts"),
        ):
            worker_result = openai_register.worker(1)

        self.assertTrue(worker_result["ok"])
        add_accounts.assert_called_once_with(
            [
                {
                    "access_token": "token-1",
                    "email": "ok@example.com",
                    "password": "RandomPassword1!",
                }
            ]
        )


class AccountPasswordTableTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[1]
    API_TS = ROOT / "web" / "src" / "lib" / "api.ts"
    ACCOUNTS_PAGE = ROOT / "web" / "src" / "app" / "accounts" / "page.tsx"

    def test_account_type_exposes_password_field(self) -> None:
        source = self.API_TS.read_text(encoding="utf-8")

        self.assertIn("password?: string | null;", source)

    def test_accounts_table_renders_password_column_with_copy_action(self) -> None:
        source = self.ACCOUNTS_PAGE.read_text(encoding="utf-8")

        self.assertIn(">密码<", source)
        self.assertIn("account.password", source)
        self.assertIn("密码已复制", source)

    def test_accounts_table_prioritizes_rows_with_recorded_passwords(self) -> None:
        source = self.ACCOUNTS_PAGE.read_text(encoding="utf-8")

        self.assertIn("sortAccountsForDisplay", source)
        self.assertIn("Boolean(account.password)", source)


if __name__ == "__main__":
    unittest.main()
