from __future__ import annotations

import unittest
from unittest import mock


class PhoneBrokerServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        from services import phone_broker_service

        phone_broker_service._country_cursor = 0
        phone_broker_service._runtime_country_blacklist.clear()

    def test_reserve_ignores_stale_reuse_fields_and_buys_fresh_number(self) -> None:
        from services.hero_sms_service import HeroSmsActivation
        from services.phone_broker_service import reserve_phone

        fake_client = mock.Mock()
        fake_client.get_number.return_value = HeroSmsActivation("387677530", "84901234000", "ACCESS_NUMBER:387677530:84901234000", country=6)

        with mock.patch("services.phone_broker_service.HeroSmsClient", return_value=fake_client):
            activation = reserve_phone(
                {
                    "api_key": "hero-key",
                    "service": "dr",
                    "country": 10,
                    "operator": "any",
                    "reuse_activation_id": "387677529",
                    "reuse_phone": "84901234889",
                    "auto_buy": False,
                    "max_price_usd": 0.03,
                }
            )

        self.assertEqual(activation.activation_id, "387677530")
        fake_client.get_number.assert_called_once_with(service="dr", country=6, operator="any", max_price=0.03)

    def test_reserve_requires_api_key(self) -> None:
        from services.phone_broker_service import reserve_phone

        with self.assertRaisesRegex(RuntimeError, "api_key 为空"):
            reserve_phone(
                {
                    "api_key": "",
                    "service": "dr",
                    "country": 10,
                    "operator": "any",
                    "auto_buy": False,
                    "max_price_usd": 0.03,
                }
            )

    def test_reserve_auto_buy_passes_max_price_to_hero_sms(self) -> None:
        from services.hero_sms_service import HeroSmsActivation
        from services.phone_broker_service import reserve_phone

        fake_client = mock.Mock()
        fake_client.get_number.return_value = HeroSmsActivation("387677529", "84901234889", "ACCESS_NUMBER:387677529:84901234889")

        with mock.patch("services.phone_broker_service.HeroSmsClient", return_value=fake_client):
            activation = reserve_phone(
                {
                    "api_key": "hero-key",
                    "service": "dr",
                    "country": 10,
                    "operator": "any",
                    "auto_buy": True,
                    "max_price_usd": 0.03,
                    "poll_interval": 1,
                }
            )

        self.assertEqual(activation.activation_id, "387677529")
        fake_client.get_number.assert_called_once_with(service="dr", country=6, operator="any", max_price=0.03)
        fake_client.close.assert_called_once()

    def test_reserve_round_robins_default_country_start(self) -> None:
        from services.hero_sms_service import HeroSmsActivation
        from services.phone_broker_service import reserve_phone

        fake_client = mock.Mock()
        fake_client.get_number.side_effect = [
            HeroSmsActivation("1", "1001", "ACCESS_NUMBER:1:1001", country=6),
            HeroSmsActivation("2", "1002", "ACCESS_NUMBER:2:1002", country=117),
            HeroSmsActivation("3", "1003", "ACCESS_NUMBER:3:1003", country=31),
        ]

        with mock.patch("services.phone_broker_service.HeroSmsClient", return_value=fake_client):
            for _ in range(3):
                reserve_phone({"api_key": "hero-key", "service": "dr", "operator": "any"})

        countries = [call.kwargs["country"] for call in fake_client.get_number.call_args_list]
        self.assertEqual(countries, [6, 117, 31])

    def test_reserve_min_price_filters_cheap_stock_and_uses_priced_operator(self) -> None:
        from services.hero_sms_service import HeroSmsActivation
        from services.phone_broker_service import reserve_phone

        fake_client = mock.Mock()
        fake_client.get_prices.return_value = {
            "6": {"any": {"cost": 0.01, "count": 9}},
            "117": {"virtual4": {"cost": 0.08, "count": 2}},
            "31": {"any": {"cost": 0.12, "count": 0}},
        }
        fake_client.get_number.return_value = HeroSmsActivation("9", "1009", "ACCESS_NUMBER:9:1009", country=117, operator="any")
        events: list[str] = []

        with mock.patch("services.phone_broker_service.HeroSmsClient", return_value=fake_client):
            activation = reserve_phone(
                {
                    "api_key": "hero-key",
                    "service": "dr",
                    "operator": "any",
                    "country_pool": [6, 117, 31],
                    "min_price_usd": 0.04,
                    "max_price_usd": 0.1,
                },
                on_event=events.append,
            )

        self.assertEqual(activation.activation_id, "9")
        fake_client.get_prices.assert_called_once_with(service="dr")
        fake_client.get_number.assert_called_once_with(service="dr", country=117, operator="any", max_price=0.1)
        self.assertTrue(any("价格过滤命中" in event for event in events))

    def test_reserve_min_price_refuses_to_blind_buy_when_no_priced_candidate(self) -> None:
        from services.phone_broker_service import reserve_phone

        fake_client = mock.Mock()
        fake_client.get_prices.return_value = {"6": {"any": {"cost": 0.01, "count": 9}}}

        with mock.patch("services.phone_broker_service.HeroSmsClient", return_value=fake_client):
            with self.assertRaisesRegex(RuntimeError, "无符合价格区间"):
                reserve_phone(
                    {
                        "api_key": "hero-key",
                        "service": "dr",
                        "country_pool": [6],
                        "min_price_usd": 0.04,
                        "max_price_usd": 0.1,
                    }
                )

        fake_client.get_number.assert_not_called()


if __name__ == "__main__":
    unittest.main()
