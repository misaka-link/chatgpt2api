from __future__ import annotations

import threading
from dataclasses import dataclass, replace
from typing import Any

from services import hero_sms_country_reputation as country_reputation
from services.hero_sms_service import OPENAI_SERVICE_CODE, HeroSmsActivation, HeroSmsClient, HeroSmsError


DEFAULT_COUNTRY_POOL = [6, 117, 31, 33, 2, 39, 48, 37, 13, 40, 15, 8, 129, 32, 86, 173, 43, 49, 34, 7, 85, 27, 172, 63, 56, 177, 54, 24, 1, 46, 175, 14, 67, 83, 59, 187, 36]
DEFAULT_COUNTRY_BLACKLIST = [16, 10, 4]
FATAL_HERO_SMS_ERRORS = (
    "BAD_KEY",
    "WRONG_KEY",
    "BANNED",
    "NO_BALANCE",
    "BAD_SERVICE",
    "NO_SERVICE",
    "BAD_ACTION",
)
_country_lock = threading.Lock()
_country_cursor = 0
_runtime_country_blacklist: set[int] = set()


@dataclass(frozen=True)
class _PhoneCandidate:
    country: int
    operator: str
    price: float | None = None
    count: int | None = None
    physical_count: int | None = None
    provider_rank: int = 999


def _positive_float(value: object, default: float) -> float:
    try:
        parsed = float(value)
    except Exception:
        return default
    return parsed if parsed > 0 else default


def _non_negative_float(value: object, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except Exception:
        return default
    return parsed if parsed >= 0 else default


def mark_country_bad(country: object, reason: str = "") -> None:
    try:
        parsed = int(country)
    except Exception:
        return
    if parsed <= 0:
        return
    with _country_lock:
        _runtime_country_blacklist.add(parsed)


def _country_pool(config: dict) -> list[int]:
    raw_pool = config.get("country_pool")
    raw_blacklist = config.get("country_blacklist")
    countries: list[int] = []
    blacklist: list[int] = []

    def add_to(target: list[int], value: object) -> None:
        try:
            country = int(value)
        except Exception:
            return
        if country > 0 and country not in target:
            target.append(country)

    if isinstance(raw_pool, str):
        for item in raw_pool.replace(";", ",").replace("\n", ",").split(","):
            add_to(countries, item.strip())
    elif isinstance(raw_pool, (list, tuple)):
        for item in raw_pool:
            add_to(countries, item)

    if isinstance(raw_blacklist, str):
        for item in raw_blacklist.replace(";", ",").replace("\n", ",").split(","):
            add_to(blacklist, item.strip())
    elif isinstance(raw_blacklist, (list, tuple)):
        for item in raw_blacklist:
            add_to(blacklist, item)

    with _country_lock:
        runtime_blacklist = list(_runtime_country_blacklist)
    blacklist = list(dict.fromkeys([*DEFAULT_COUNTRY_BLACKLIST, *blacklist, *runtime_blacklist]))

    if not countries:
        add_to(countries, config.get("country"))
        for country in DEFAULT_COUNTRY_POOL:
            add_to(countries, country)
    countries = [country for country in countries if country not in blacklist]
    return countries or [country for country in DEFAULT_COUNTRY_POOL if country not in blacklist] or list(DEFAULT_COUNTRY_POOL)


def _round_robin_pool(countries: list[int]) -> list[int]:
    global _country_cursor
    if len(countries) <= 1:
        return countries
    with _country_lock:
        offset = _country_cursor % len(countries)
        _country_cursor += 1
    return countries[offset:] + countries[:offset]


def _parse_price(value: object) -> float | None:
    try:
        parsed = float(value)
    except Exception:
        return None
    return parsed if parsed >= 0 else None


def _parse_count(value: object) -> int:
    try:
        parsed = int(value)
    except Exception:
        return 0
    return parsed if parsed > 0 else 0


def _parse_physical_count(info: dict, fallback_count: int) -> int:
    if "physicalCount" in info:
        return _parse_count(info.get("physicalCount"))
    return fallback_count


def _priced_candidates(
    prices: dict,
    countries: list[int],
    *,
    operator: str,
    min_price: float,
    max_price: float,
) -> list[_PhoneCandidate]:
    order = {country: index for index, country in enumerate(countries)}
    wanted_operator = str(operator or "any").strip() or "any"
    candidates: list[_PhoneCandidate] = []
    for raw_country, operators in prices.items():
        try:
            country = int(raw_country)
        except Exception:
            continue
        if country not in order or not isinstance(operators, dict):
            continue
        for raw_operator, info in operators.items():
            op = str(raw_operator or "").strip() or "any"
            if wanted_operator != "any" and op not in {wanted_operator, OPENAI_SERVICE_CODE}:
                continue
            if not isinstance(info, dict):
                continue
            price = _parse_price(info.get("cost"))
            count = _parse_count(info.get("count"))
            physical_count = _parse_physical_count(info, count)
            if price is None or count <= 0:
                continue
            if physical_count <= 0:
                continue
            if min_price <= price <= max_price:
                candidates.append(
                    _PhoneCandidate(
                        country=country,
                        operator=wanted_operator,
                        price=price,
                        count=count,
                        physical_count=physical_count,
                        provider_rank=order[country],
                    )
                )
    return candidates


def _offer_candidates(
    offers: dict,
    countries: list[int],
    *,
    operator: str,
    min_price: float,
    max_price: float,
    service: str,
) -> list[_PhoneCandidate]:
    service_offers = offers.get(service) if isinstance(offers.get(service), dict) else offers
    if not isinstance(service_offers, dict):
        return []
    order = {country: index for index, country in enumerate(countries)}
    wanted_operator = str(operator or "any").strip() or "any"
    candidates: list[_PhoneCandidate] = []
    for provider_rank, (raw_country, info) in enumerate(service_offers.items()):
        try:
            country = int(raw_country)
        except Exception:
            continue
        if country not in order or not isinstance(info, dict):
            continue
        prices = info.get("prices") if isinstance(info.get("prices"), dict) else {}
        counts = info.get("counts") if isinstance(info.get("counts"), dict) else {}
        price = _parse_price(prices.get("default") if "default" in prices else prices.get("min"))
        count = _parse_count(counts.get("defaultPrice") if counts.get("defaultPrice") is not None else counts.get("total"))
        physical_count = _parse_count(counts.get("physical") if counts.get("physical") is not None else count)
        if price is None or count <= 0 or physical_count <= 0:
            continue
        if min_price <= price <= max_price:
            candidates.append(
                _PhoneCandidate(
                    country=country,
                    operator=wanted_operator,
                    price=price,
                    count=count,
                    physical_count=physical_count,
                    provider_rank=provider_rank,
                )
            )
    return candidates


def _rank_priced_candidates(candidates: list[_PhoneCandidate]) -> list[_PhoneCandidate]:
    rank_input = [
        country_reputation.CountryCandidate(
            country=item.country,
            price=float(item.price or 0),
            count=int(item.count or 0),
            physical_count=int(item.physical_count or item.count or 0),
            provider_rank=int(item.provider_rank if item.provider_rank is not None else 999),
        )
        for item in candidates
        if item.price is not None
    ]
    ranked = country_reputation.store.rank_candidates(rank_input)
    rank_by_country = {item.country: index for index, item in enumerate(ranked)}
    return sorted(
        candidates,
        key=lambda item: (
            rank_by_country.get(item.country, 9999),
            item.price if item.price is not None else 999,
            item.provider_rank,
            -int(item.physical_count or 0),
        ),
    )


def _candidate_pool(
    config: dict,
    client: HeroSmsClient,
    *,
    countries: list[int],
    service: str,
    operator: str,
    min_price: float,
    max_price: float,
    emit,
) -> list[_PhoneCandidate]:
    if min_price <= 0:
        return [_PhoneCandidate(country=country, operator=operator) for country in countries]

    candidates: list[_PhoneCandidate] = []
    try:
        offers = client.get_activation_offers(service=service, countries=countries)
        if isinstance(offers, dict):
            candidates = _offer_candidates(offers, countries, operator=operator, min_price=min_price, max_price=max_price, service=service)
    except Exception as exc:
        emit(f"HeroSMS offers 获取失败，回退 getPrices: {exc}")

    if not candidates:
        try:
            prices = client.get_prices(service=service)
        except Exception as exc:
            raise RuntimeError(f"HeroSMS 价格表获取失败，已阻止低价盲买: {exc}") from exc
        candidates = _priced_candidates(prices, countries, operator=operator, min_price=min_price, max_price=max_price)
    if not candidates:
        raise RuntimeError(f"HeroSMS 无符合价格区间的号码: min_price_usd={min_price}, max_price_usd={max_price}")
    candidates = _rank_priced_candidates(candidates)
    preview = ", ".join(
        f"{item.country}/{item.operator}/${item.price:.4f}/stock={item.count}/physical={item.physical_count}/rank={item.provider_rank}"
        for item in candidates[:8]
        if item.price is not None
    )
    emit(f"HeroSMS 价格过滤命中 {len(candidates)} 个候选，已按质量/历史/成本综合排序: {preview}")
    return candidates


def _can_try_next_country(error: Exception) -> bool:
    text = str(error or "").strip().upper()
    return bool(text) and not text.startswith(FATAL_HERO_SMS_ERRORS)


def reserve_phone(config: dict, *, session: Any | None = None, on_event=None) -> HeroSmsActivation:
    """Reserve one phone for Codex add_phone.

    Good taste version: buy a fresh number with one budget and one country pool.
    Stale manual reuse fields are deliberately ignored for batch speed.
    """
    api_key = str(config.get("api_key") or "").strip()
    if not api_key:
        raise RuntimeError("HeroSMS 已启用，但 api_key 为空")

    service = str(config.get("service") or OPENAI_SERVICE_CODE).strip() or OPENAI_SERVICE_CODE
    operator = str(config.get("operator") or "any").strip() or "any"
    max_price = _positive_float(config.get("max_price_usd"), 0.03)
    min_price = _non_negative_float(config.get("min_price_usd"), 0.0)
    if min_price > max_price:
        raise RuntimeError(f"HeroSMS min_price_usd 不能大于 max_price_usd: min={min_price}, max={max_price}")
    client = HeroSmsClient(
        api_key,
        session=session,
        poll_interval=_positive_float(config.get("poll_interval"), 5.0),
    )
    emit = on_event if callable(on_event) else (lambda _message: None)
    errors: list[str] = []
    try:
        countries = _round_robin_pool(_country_pool(config))
        candidates = _candidate_pool(
            config,
            client,
            countries=countries,
            service=service,
            operator=operator,
            min_price=min_price,
            max_price=max_price,
            emit=emit,
        )
        for candidate in candidates:
            try:
                emit(
                    f"HeroSMS getNumber 尝试: country={candidate.country}, operator={candidate.operator}, "
                    f"max_price_usd={max_price}"
                )
                activation = client.get_number(
                    service=service,
                    country=candidate.country,
                    operator=candidate.operator,
                    max_price=max_price,
                )
                country_reputation.store.record_event(candidate.country, "bought", price=candidate.price)
                return replace(activation, country=candidate.country, operator=candidate.operator, price=candidate.price)
            except HeroSmsError as exc:
                errors.append(f"{candidate.country}/{candidate.operator}:{exc}")
                if not _can_try_next_country(exc):
                    raise RuntimeError(f"HeroSMS 买号失败: {exc}") from exc
        raise RuntimeError(f"HeroSMS 国家池买号失败: {'; '.join(errors)}")
    finally:
        client.close()
