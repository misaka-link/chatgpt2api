from __future__ import annotations

import json
import math
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


DATA_DIR = Path(__file__).resolve().parents[1] / "data"
DEFAULT_FILE = DATA_DIR / "hero_sms_country_reputation.json"

POSITIVE_EVENTS = {"send_ok", "sms_ok", "add_phone_success", "cpa_success"}
NEUTRAL_EVENTS = {"bought"}
FAILURE_COOLDOWNS = {
    "fraud_guard": timedelta(hours=6),
    "phone_otp_validate_fail": timedelta(minutes=40),
    "send_fail": timedelta(minutes=40),
}
SMS_TIMEOUT_COOLDOWN_AFTER = 3
SMS_TIMEOUT_COOLDOWN = timedelta(minutes=15)
PHONE_IN_USE_COOLDOWN_AFTER = 3
PHONE_IN_USE_COOLDOWN = timedelta(hours=1)
LOW_RECEIVE_RATE_MIN_SENDS = 10
LOW_RECEIVE_RATE_THRESHOLD = 0.25
LOW_RECEIVE_RATE_PENALTY = 100000
ACTIVE_COOLDOWN_SCORE = -1_000_000_000.0
LONG_FAILURE_STREAK_THRESHOLD = 5
LONG_FAILURE_STREAK_PENALTY = 1000


@dataclass(frozen=True)
class CountryCandidate:
    country: int
    price: float
    count: int
    physical_count: int = 0
    provider_rank: int = 999


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None = None) -> str:
    return (dt or _now()).isoformat()


def _parse_time(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _country(value: object) -> str:
    try:
        parsed = int(value)
    except Exception:
        return ""
    return str(parsed) if parsed > 0 else ""


def _float(value: object, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except Exception:
        return default
    return parsed if parsed >= 0 else default


def _int(value: object, default: int = 0) -> int:
    try:
        parsed = int(value)
    except Exception:
        return default
    return parsed if parsed >= 0 else default


class CountryReputationStore:
    def __init__(self, file_path: Path = DEFAULT_FILE):
        self.file_path = Path(file_path)
        self._lock = threading.RLock()

    def _load_locked(self) -> dict[str, Any]:
        try:
            data = json.loads(self.file_path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        return data if isinstance(data, dict) else {}

    def _save_locked(self, data: dict[str, Any]) -> None:
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.file_path.with_suffix(self.file_path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.file_path)

    def _record(self, data: dict[str, Any], country: str) -> dict[str, Any]:
        countries = data.setdefault("countries", {})
        record = countries.setdefault(country, {})
        for key in (
            "bought",
            "send_ok",
            "sms_ok",
            "add_phone_success",
            "cpa_success",
            "fraud_guard",
            "phone_number_in_use",
            "sms_code_timeout",
            "send_fail",
            "phone_otp_validate_fail",
            "cpa_fail",
            "consecutive_fail",
        ):
            record.setdefault(key, 0)
        record.setdefault("cooldown_until", "")
        return record

    def _cooldown_for(self, event: str, consecutive_fail: int) -> timedelta | None:
        if event == "sms_code_timeout":
            return SMS_TIMEOUT_COOLDOWN if consecutive_fail >= SMS_TIMEOUT_COOLDOWN_AFTER else None
        if event == "phone_number_in_use":
            return PHONE_IN_USE_COOLDOWN if consecutive_fail >= PHONE_IN_USE_COOLDOWN_AFTER else None
        return FAILURE_COOLDOWNS.get(event)

    def record_event(self, country: object, event: str, *, price: float | None = None, reason: str = "") -> dict[str, Any]:
        country_key = _country(country)
        event = str(event or "").strip()
        if not country_key or not event:
            return {}
        with self._lock:
            data = self._load_locked()
            record = self._record(data, country_key)
            record[event] = int(record.get(event) or 0) + 1
            if price is not None:
                record["last_price_usd"] = round(_float(price), 6)
            if price is not None and event == "bought":
                record["spent_usd"] = round(_float(record.get("spent_usd")) + _float(price), 6)
            record["last_event"] = event
            record["last_event_at"] = _iso()
            if reason:
                record["last_reason"] = str(reason)[:500]
            if event in POSITIVE_EVENTS:
                if event in {"add_phone_success", "cpa_success"}:
                    record["consecutive_fail"] = 0
                    record["cooldown_until"] = ""
                record[f"last_{event}_at"] = _iso()
            elif event not in NEUTRAL_EVENTS:
                record["consecutive_fail"] = int(record.get("consecutive_fail") or 0) + 1
                cooldown = self._cooldown_for(event, int(record.get("consecutive_fail") or 0))
                if cooldown:
                    record["cooldown_until"] = _iso(_now() + cooldown)
            self._save_locked(data)
            return dict(record)

    def _record_for(self, data: dict[str, Any], country: int) -> dict[str, Any]:
        return ((data.get("countries") or {}).get(str(country)) or {})

    def score_candidate(self, candidate: CountryCandidate, record: dict[str, Any] | None = None) -> float:
        record = record or {}
        cooldown_until = _parse_time(record.get("cooldown_until"))
        if cooldown_until and cooldown_until > _now():
            return ACTIVE_COOLDOWN_SCORE
        count = max(0, int(candidate.count or 0))
        physical = max(0, int(candidate.physical_count or 0))
        physical_ratio = min(1.0, physical / max(1, count))
        price = max(0.0, float(candidate.price or 0.0))
        send_ok = int(record.get("send_ok") or 0)
        sms_ok = int(record.get("sms_ok") or 0)
        score = 0.0
        score += int(record.get("cpa_success") or 0) * 3000
        score += int(record.get("add_phone_success") or 0) * 110
        score += sms_ok * 35
        score += send_ok * 10
        score -= int(record.get("fraud_guard") or 0) * 260
        score -= int(record.get("phone_number_in_use") or 0) * 45
        score -= int(record.get("sms_code_timeout") or 0) * 30
        score -= int(record.get("send_fail") or 0) * 60
        score -= int(record.get("phone_otp_validate_fail") or 0) * 70
        consecutive_fail = int(record.get("consecutive_fail") or 0)
        score -= consecutive_fail * 15
        if consecutive_fail >= LONG_FAILURE_STREAK_THRESHOLD:
            score -= (consecutive_fail - LONG_FAILURE_STREAK_THRESHOLD + 1) * LONG_FAILURE_STREAK_PENALTY
        if send_ok >= LOW_RECEIVE_RATE_MIN_SENDS:
            receive_rate = sms_ok / max(1, send_ok)
            if receive_rate < LOW_RECEIVE_RATE_THRESHOLD:
                score -= LOW_RECEIVE_RATE_PENALTY
                score -= (LOW_RECEIVE_RATE_THRESHOLD - receive_rate) * LOW_RECEIVE_RATE_PENALTY
        score += min(60.0, math.log10(count + 1) * 12)
        score += physical_ratio * 60
        score -= price * 260
        provider_rank = candidate.provider_rank if candidate.provider_rank is not None else 999
        score -= min(120, max(0, int(provider_rank))) * 1.2
        return score

    def rank_candidates(self, candidates: list[CountryCandidate]) -> list[CountryCandidate]:
        if not candidates:
            return []
        with self._lock:
            data = self._load_locked()
            scored = [
                (self.score_candidate(candidate, self._record_for(data, candidate.country)), candidate)
                for candidate in candidates
            ]
        return [candidate for _, candidate in sorted(scored, key=lambda item: (-item[0], item[1].price, item[1].provider_rank, item[1].country))]

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return self._load_locked()


store = CountryReputationStore()
