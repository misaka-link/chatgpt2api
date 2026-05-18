from __future__ import annotations

import tempfile
import unittest
from pathlib import Path


class HeroSmsCountryReputationTests(unittest.TestCase):
    def make_store(self):
        from services import hero_sms_country_reputation

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return hero_sms_country_reputation.CountryReputationStore(Path(tmp.name) / "hero_sms_country_reputation.json")

    def test_country_score_rewards_cpa_success_and_penalizes_bad_phone_failures(self):
        from services import hero_sms_country_reputation

        store = self.make_store()
        store.record_event(33, "fraud_guard", price=0.05, reason="add_phone_send_failed:fraud_guard")
        store.record_event(31, "cpa_success", price=0.05)

        bad = hero_sms_country_reputation.CountryCandidate(country=33, price=0.05, count=9000, physical_count=1500, provider_rank=1)
        good = hero_sms_country_reputation.CountryCandidate(country=31, price=0.05, count=3500, physical_count=3400, provider_rank=6)

        ranked = store.rank_candidates([bad, good])

        self.assertEqual([item.country for item in ranked], [31, 33])

    def test_sms_timeout_is_weak_penalty_until_repeated_failures(self):
        store = self.make_store()

        first = store.record_event(67, "sms_code_timeout", price=0.1)
        second = store.record_event(67, "sms_code_timeout", price=0.1)

        self.assertEqual(first["cooldown_until"], "")
        self.assertEqual(second["cooldown_until"], "")
        self.assertEqual(second["consecutive_fail"], 2)

        third = store.record_event(67, "sms_code_timeout", price=0.1)

        self.assertTrue(third["cooldown_until"])
        self.assertEqual(third["consecutive_fail"], 3)

    def test_success_clears_cooldown_after_repeated_transient_failures(self):
        store = self.make_store()

        store.record_event(67, "sms_code_timeout", price=0.1)
        store.record_event(67, "sms_code_timeout", price=0.1)
        failed = store.record_event(67, "sms_code_timeout", price=0.1)
        self.assertTrue(failed["cooldown_until"])

        recovered = store.record_event(67, "add_phone_success", price=0.1)

        self.assertEqual(recovered["consecutive_fail"], 0)
        self.assertEqual(recovered["cooldown_until"], "")

    def test_fraud_guard_still_cools_down_immediately(self):
        store = self.make_store()

        failed = store.record_event(33, "fraud_guard", price=0.05)

        self.assertTrue(failed["cooldown_until"])
        self.assertEqual(failed["consecutive_fail"], 1)

    def test_phone_number_in_use_is_weak_until_repeated_failures(self):
        store = self.make_store()

        first = store.record_event(31, "phone_number_in_use", price=0.05)
        second = store.record_event(31, "phone_number_in_use", price=0.05)
        third = store.record_event(31, "phone_number_in_use", price=0.05)

        self.assertEqual(first["cooldown_until"], "")
        self.assertEqual(second["cooldown_until"], "")
        self.assertTrue(third["cooldown_until"])

    def test_cpa_success_beats_stale_add_phone_only_history(self):
        from services import hero_sms_country_reputation

        store = self.make_store()
        for _ in range(8):
            store.record_event(117, "send_ok", price=0.05)
            store.record_event(117, "sms_ok", price=0.05)
            store.record_event(117, "add_phone_success", price=0.05)
        store.record_event(117, "sms_code_timeout", price=0.05)
        store.record_event(117, "sms_code_timeout", price=0.05)
        store.record_event(31, "cpa_success", price=0.05)
        store.record_event(31, "sms_code_timeout", price=0.05)
        store.record_event(31, "sms_code_timeout", price=0.05)

        candidates = [
            hero_sms_country_reputation.CountryCandidate(country=117, price=0.05, count=1800, physical_count=1800, provider_rank=2),
            hero_sms_country_reputation.CountryCandidate(country=31, price=0.05, count=3200, physical_count=3200, provider_rank=1),
        ]

        self.assertEqual(store.rank_candidates(candidates)[0].country, 31)

    def test_active_cooldown_overrides_stale_cpa_success(self):
        from services import hero_sms_country_reputation

        store = self.make_store()
        for _ in range(12):
            store.record_event(31, "cpa_success", price=0.05)
        for _ in range(3):
            store.record_event(31, "sms_code_timeout", price=0.05)
        for _ in range(4):
            store.record_event(117, "send_ok", price=0.05)
            store.record_event(117, "sms_ok", price=0.05)
            store.record_event(117, "add_phone_success", price=0.05)

        candidates = [
            hero_sms_country_reputation.CountryCandidate(country=31, price=0.05, count=3200, physical_count=3200, provider_rank=1),
            hero_sms_country_reputation.CountryCandidate(country=117, price=0.05, count=900, physical_count=890, provider_rank=2),
        ]

        self.assertEqual(store.rank_candidates(candidates)[0].country, 117)

    def test_bad_receive_rate_overrides_stale_cpa_success(self):
        from services import hero_sms_country_reputation

        store = self.make_store()
        bad_record = {
            "cpa_success": 18,
            "add_phone_success": 8,
            "send_ok": 65,
            "sms_ok": 8,
            "sms_code_timeout": 55,
            "consecutive_fail": 0,
            "cooldown_until": "",
        }
        healthy_record = {
            "cpa_success": 0,
            "add_phone_success": 6,
            "send_ok": 8,
            "sms_ok": 6,
            "sms_code_timeout": 1,
            "consecutive_fail": 0,
            "cooldown_until": "",
        }

        bad = hero_sms_country_reputation.CountryCandidate(country=31, price=0.05, count=3200, physical_count=3000, provider_rank=1)
        healthy = hero_sms_country_reputation.CountryCandidate(country=117, price=0.05, count=900, physical_count=890, provider_rank=2)

        self.assertLess(store.score_candidate(bad, bad_record), store.score_candidate(healthy, healthy_record))

    def test_long_failure_streak_overrides_old_add_phone_success(self):
        from services import hero_sms_country_reputation

        store = self.make_store()
        stale_record = {
            "cpa_success": 0,
            "add_phone_success": 36,
            "send_ok": 63,
            "sms_ok": 36,
            "sms_code_timeout": 27,
            "consecutive_fail": 20,
            "cooldown_until": "",
        }
        clean_record = {
            "cpa_success": 0,
            "add_phone_success": 0,
            "send_ok": 0,
            "sms_ok": 0,
            "sms_code_timeout": 0,
            "consecutive_fail": 0,
            "cooldown_until": "",
        }

        stale = hero_sms_country_reputation.CountryCandidate(country=117, price=0.05, count=900, physical_count=890, provider_rank=1)
        clean = hero_sms_country_reputation.CountryCandidate(country=33, price=0.05, count=4000, physical_count=3500, provider_rank=2)

        self.assertLess(store.score_candidate(stale, stale_record), store.score_candidate(clean, clean_record))

    def test_provider_rank_zero_is_not_treated_as_missing_rank(self):
        from services import hero_sms_country_reputation

        store = self.make_store()
        first = hero_sms_country_reputation.CountryCandidate(country=33, price=0.05, count=3000, physical_count=2800, provider_rank=0)
        later = hero_sms_country_reputation.CountryCandidate(country=49, price=0.05, count=3000, physical_count=2800, provider_rank=5)

        self.assertGreater(store.score_candidate(first, {}), store.score_candidate(later, {}))

    def test_spend_is_counted_once_when_number_is_bought(self):
        store = self.make_store()

        store.record_event(31, "bought", price=0.05)
        store.record_event(31, "send_ok", price=0.05)
        store.record_event(31, "sms_ok", price=0.05)
        record = store.record_event(31, "cpa_success", price=0.05)

        self.assertEqual(record["spent_usd"], 0.05)
        self.assertEqual(record["consecutive_fail"], 0)


if __name__ == "__main__":
    unittest.main()
