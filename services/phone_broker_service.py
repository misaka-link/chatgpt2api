from __future__ import annotations

from typing import Any

from services.hero_sms_service import OPENAI_SERVICE_CODE, HeroSmsActivation, HeroSmsClient, HeroSmsError


DEFAULT_COUNTRY_POOL = [16, 187, 10, 36]
FATAL_HERO_SMS_ERRORS = (
    "BAD_KEY",
    "WRONG_KEY",
    "BANNED",
    "NO_BALANCE",
    "BAD_SERVICE",
    "NO_SERVICE",
    "BAD_ACTION",
)


def _positive_float(value: object, default: float) -> float:
    try:
        parsed = float(value)
    except Exception:
        return default
    return parsed if parsed > 0 else default


def _country_pool(config: dict) -> list[int]:
    raw_pool = config.get("country_pool")
    countries: list[int] = []

    def add(value: object) -> None:
        try:
            country = int(value)
        except Exception:
            return
        if country > 0 and country not in countries:
            countries.append(country)

    if isinstance(raw_pool, str):
        for item in raw_pool.replace(";", ",").replace("\n", ",").split(","):
            add(item.strip())
    elif isinstance(raw_pool, (list, tuple)):
        for item in raw_pool:
            add(item)

    if not countries:
        add(config.get("country"))
        for country in DEFAULT_COUNTRY_POOL:
            add(country)
    return countries or list(DEFAULT_COUNTRY_POOL)


def _can_try_next_country(error: Exception) -> bool:
    text = str(error or "").strip().upper()
    return bool(text) and not text.startswith(FATAL_HERO_SMS_ERRORS)


def reserve_phone(config: dict, *, session: Any | None = None) -> HeroSmsActivation:
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
    client = HeroSmsClient(
        api_key,
        session=session,
        poll_interval=_positive_float(config.get("poll_interval"), 5.0),
    )
    errors: list[str] = []
    try:
        for country in _country_pool(config):
            try:
                return client.get_number(
                    service=service,
                    country=country,
                    operator=operator,
                    max_price=max_price,
                )
            except HeroSmsError as exc:
                errors.append(f"{country}:{exc}")
                if not _can_try_next_country(exc):
                    raise RuntimeError(f"HeroSMS 买号失败: {exc}") from exc
        raise RuntimeError(f"HeroSMS 国家池买号失败: {'; '.join(errors)}")
    finally:
        client.close()
