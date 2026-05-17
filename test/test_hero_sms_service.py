from __future__ import annotations

import unittest
from unittest import mock


class FakeResponse:
    def __init__(self, text: str = "", json_data=None, status_code: int = 200):
        self.text = text
        self._json_data = json_data
        self.status_code = status_code
        self.ok = 200 <= status_code < 300

    def json(self):
        if self._json_data is None:
            raise ValueError("not json")
        return self._json_data


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.closed = False

    def get(self, url, **kwargs):
        self.calls.append({"method": "GET", "url": url, **kwargs})
        if not self.responses:
            raise AssertionError("unexpected request")
        return self.responses.pop(0)

    def close(self):
        self.closed = True


class HeroSmsServiceTests(unittest.TestCase):
    def test_get_number_uses_sms_activate_compatible_params_and_parses_access_number(self):
        from services.hero_sms_service import HeroSmsClient

        session = FakeSession([FakeResponse("ACCESS_NUMBER:12345:447700900123")])
        client = HeroSmsClient("hero-key", session=session)

        activation = client.get_number(service="dr", country=16, operator="any")

        self.assertEqual(activation.activation_id, "12345")
        self.assertEqual(activation.phone, "447700900123")
        call = session.calls[0]
        self.assertEqual(call["url"], "https://hero-sms.com/stubs/handler_api.php")
        self.assertEqual(call["params"]["api_key"], "hero-key")
        self.assertEqual(call["params"]["action"], "getNumber")
        self.assertEqual(call["params"]["service"], "dr")
        self.assertEqual(call["params"]["country"], 16)
        self.assertEqual(call["params"]["operator"], "any")

    def test_poll_code_returns_digits_from_status_ok_and_waits_between_pending_states(self):
        from services.hero_sms_service import HeroSmsClient

        session = FakeSession(
            [
                FakeResponse("STATUS_WAIT_CODE"),
                FakeResponse("STATUS_OK:123456"),
            ]
        )
        client = HeroSmsClient("hero-key", session=session, poll_interval=0.1)

        with mock.patch("services.hero_sms_service.time.sleep") as sleep:
            code = client.poll_code("12345", timeout=5)

        self.assertEqual(code, "123456")
        self.assertEqual([call["params"]["action"] for call in session.calls], ["getStatus", "getStatus"])
        sleep.assert_called_once_with(0.1)

    def test_bad_key_json_response_raises_clear_error(self):
        from services.hero_sms_service import HeroSmsClient, HeroSmsError

        session = FakeSession([FakeResponse(json_data={"title": "BAD_KEY", "details": "Unauthorized"}, status_code=401)])
        client = HeroSmsClient("bad-key", session=session)

        with self.assertRaisesRegex(HeroSmsError, "BAD_KEY"):
            client.get_balance()

    def test_resolve_activation_reuses_existing_id_and_phone_without_buying_number(self):
        from services.hero_sms_service import resolve_activation

        session = FakeSession([])
        activation = resolve_activation(
            {
                "api_key": "hero-key",
                "service": "dr",
                "country": 10,
                "operator": "any",
                "reuse_activation_id": "12345",
                "reuse_phone": "84901234567",
            },
            session=session,
        )

        self.assertEqual(activation.activation_id, "12345")
        self.assertEqual(activation.phone, "84901234567")
        self.assertEqual(session.calls, [])

    def test_reserve_phone_rotates_country_pool_with_max_budget(self):
        from services.phone_broker_service import reserve_phone

        session = FakeSession(
            [
                FakeResponse("NO_NUMBERS"),
                FakeResponse("ACCESS_NUMBER:67890:447700900123"),
            ]
        )

        activation = reserve_phone(
            {
                "api_key": "hero-key",
                "auto_buy": True,
                "service": "dr",
                "operator": "any",
                "country_pool": [10, 16],
                "max_price_usd": 0.05,
            },
            session=session,
        )

        self.assertEqual(activation.activation_id, "67890")
        self.assertEqual(activation.phone, "447700900123")
        self.assertEqual(activation.country, 16)
        self.assertEqual([call["params"]["country"] for call in session.calls], [10, 16])
        self.assertEqual([call["params"]["maxPrice"] for call in session.calls], [0.05, 0.05])


if __name__ == "__main__":
    unittest.main()
