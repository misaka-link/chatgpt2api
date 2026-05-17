from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REGISTER_CARD = ROOT / "web" / "src" / "app" / "register" / "components" / "register-card.tsx"
SETTINGS_STORE = ROOT / "web" / "src" / "app" / "settings" / "store.ts"
CODEX_POC = ROOT / "scripts" / "codex_oauth_poc.py"


class RegisterHeroSmsConfigTests(unittest.TestCase):
    def test_default_register_config_contains_hero_sms_defaults(self) -> None:
        from services.register_service import _normalize_hero_sms

        hero_sms = _normalize_hero_sms({})

        self.assertEqual(
            hero_sms,
            {
                "enabled": False,
                "api_key": "",
                "service": "dr",
                "country": 16,
                "country_pool": [16, 187, 10, 36],
                "operator": "any",
                "wait_timeout": 30,
                "poll_interval": 5,
                "reuse_activation_id": "",
                "reuse_phone": "",
                "auto_buy": True,
                "max_price_usd": 0.03,
                "cancel_on_send_fail": True,
            },
        )

    def test_normalize_preserves_and_sanitizes_hero_sms_config(self) -> None:
        from services.register_service import _normalize

        cfg = _normalize(
            {
                "hero_sms": {
                    "enabled": True,
                    "api_key": "  hero-key  ",
                    "service": "",
                    "country": "187",
                    "country_pool": ["", "36", "187", "bad", 36],
                    "operator": "",
                    "wait_timeout": "120",
                    "poll_interval": "2",
                    "reuse_activation_id": "  12345 ",
                    "reuse_phone": " +84901234567 ",
                    "auto_buy": False,
                    "max_price_usd": "0.025",
                    "cancel_on_send_fail": False,
                }
            }
        )

        self.assertEqual(cfg["hero_sms"]["enabled"], True)
        self.assertEqual(cfg["hero_sms"]["api_key"], "hero-key")
        self.assertEqual(cfg["hero_sms"]["service"], "dr")
        self.assertEqual(cfg["hero_sms"]["country"], 187)
        self.assertEqual(cfg["hero_sms"]["country_pool"], [36, 187])
        self.assertEqual(cfg["hero_sms"]["operator"], "any")
        self.assertEqual(cfg["hero_sms"]["wait_timeout"], 30)
        self.assertEqual(cfg["hero_sms"]["poll_interval"], 2)
        self.assertEqual(cfg["hero_sms"]["reuse_activation_id"], "")
        self.assertEqual(cfg["hero_sms"]["reuse_phone"], "")
        self.assertEqual(cfg["hero_sms"]["auto_buy"], True)
        self.assertEqual(cfg["hero_sms"]["max_price_usd"], 0.025)
        self.assertEqual(cfg["hero_sms"]["cancel_on_send_fail"], True)

    def test_register_ui_only_exposes_hero_sms_budget_and_secret(self) -> None:
        source = REGISTER_CARD.read_text(encoding="utf-8")

        self.assertIn("HeroSMS 接码配置", source)
        self.assertIn("setHeroSmsField", source)
        self.assertIn("config.hero_sms.api_key", source)
        self.assertIn("config.hero_sms.max_price_usd", source)
        self.assertIn("自动轮询国家", source)
        self.assertNotIn('setHeroSmsField("country"', source)
        self.assertNotIn('setHeroSmsField("operator"', source)
        self.assertNotIn('setHeroSmsField("service"', source)
        self.assertNotIn('setHeroSmsField("wait_timeout"', source)
        self.assertNotIn('setHeroSmsField("poll_interval"', source)
        self.assertNotIn('setHeroSmsField("reuse_activation_id"', source)
        self.assertNotIn('setHeroSmsField("reuse_phone"', source)
        self.assertNotIn('setHeroSmsField("auto_buy"', source)
        self.assertNotIn('setHeroSmsField("cancel_on_send_fail"', source)
        self.assertIn("启动 Codex CPA 注册", source)

    def test_register_store_saves_hero_sms_config(self) -> None:
        source = SETTINGS_STORE.read_text(encoding="utf-8")

        self.assertIn("setRegisterHeroSmsField", source)
        self.assertIn("normalizeRegisterHeroSmsForSave", source)
        self.assertIn("hero_sms: normalizeRegisterHeroSmsForSave(registerConfig.hero_sms)", source)
        self.assertIn("max_price_usd", source)
        self.assertIn("startCodexRegister", source)

    def test_codex_poc_reads_hero_sms_config_without_printing_key(self) -> None:
        source = CODEX_POC.read_text(encoding="utf-8")

        self.assertIn("config.get(\"hero_sms\")", source)
        self.assertIn("HeroSMS enabled", source)
        self.assertIn("api_key", source)
        self.assertNotIn("hero_sms['api_key']", source)


if __name__ == "__main__":
    unittest.main()
