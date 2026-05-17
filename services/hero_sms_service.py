from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import requests


HERO_SMS_HANDLER_URL = "https://hero-sms.com/stubs/handler_api.php"
OPENAI_SERVICE_CODE = "dr"


class HeroSmsError(RuntimeError):
    pass


@dataclass(frozen=True)
class HeroSmsActivation:
    activation_id: str
    phone: str
    raw: str
    country: int | str | None = None
    service: str = OPENAI_SERVICE_CODE
    operator: str = "any"


class HeroSmsClient:
    def __init__(
        self,
        api_key: str,
        *,
        session: Any | None = None,
        base_url: str = HERO_SMS_HANDLER_URL,
        timeout: int = 30,
        poll_interval: float = 5.0,
    ) -> None:
        self.api_key = str(api_key or "").strip()
        self.base_url = str(base_url or HERO_SMS_HANDLER_URL).strip()
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.session = session or requests.Session()

    def close(self) -> None:
        close = getattr(self.session, "close", None)
        if callable(close):
            close()

    def _request(self, action: str, **params) -> str:
        payload = {"api_key": self.api_key, "action": action}
        payload.update({key: value for key, value in params.items() if value is not None})
        response = self.session.get(self.base_url, params=payload, timeout=self.timeout)
        data = self._json_response(response)
        if data:
            title = str(data.get("title") or data.get("error") or data.get("message") or "").strip()
            details = str(data.get("details") or "").strip()
            if title:
                raise HeroSmsError(f"{title}{': ' + details if details else ''}")
            return str(data)
        text = str(getattr(response, "text", "") or "").strip()
        if getattr(response, "ok", True) is False:
            raise HeroSmsError(text or f"HTTP {getattr(response, 'status_code', 'unknown')}")
        if self._is_error_text(text):
            raise HeroSmsError(text)
        return text

    @staticmethod
    def _json_response(response) -> dict:
        try:
            data = response.json()
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _is_error_text(text: str) -> bool:
        if not text:
            return False
        if text.startswith(("ACCESS_", "STATUS_")):
            return False
        return text.isupper() or text.startswith(("BAD_", "NO_", "ERROR_", "WRONG_", "BANNED"))

    def get_balance(self) -> float | None:
        raw = self._request("getBalance")
        if raw.startswith("ACCESS_BALANCE:"):
            try:
                return float(raw.split(":", 1)[1])
            except ValueError:
                return None
        return None

    def get_number(
        self,
        *,
        service: str = OPENAI_SERVICE_CODE,
        country: int | str = 16,
        operator: str | None = "any",
        max_price: float | None = None,
    ) -> HeroSmsActivation:
        raw = self._request("getNumber", service=service, country=country, operator=operator, maxPrice=max_price)
        if not raw.startswith("ACCESS_NUMBER:"):
            raise HeroSmsError(raw or "getNumber returned empty response")
        parts = raw.split(":", 2)
        if len(parts) != 3 or not parts[1] or not parts[2]:
            raise HeroSmsError(f"invalid ACCESS_NUMBER response: {raw}")
        return HeroSmsActivation(
            activation_id=parts[1],
            phone=parts[2],
            raw=raw,
            country=country,
            service=service,
            operator=operator or "any",
        )

    def get_status(self, activation_id: str) -> str:
        return self._request("getStatus", id=str(activation_id or "").strip())

    def poll_code(self, activation_id: str, *, timeout: float = 1200) -> str:
        deadline = time.monotonic() + timeout
        while True:
            raw = self.get_status(activation_id)
            if raw.startswith("STATUS_OK:"):
                code = raw.split(":", 1)[1].strip()
                if code:
                    return code
            elif raw in {"STATUS_WAIT_CODE", "STATUS_WAIT_RETRY", "STATUS_WAIT_RESEND"}:
                pass
            else:
                raise HeroSmsError(raw or "empty status response")
            if time.monotonic() >= deadline:
                raise HeroSmsError("sms_code_timeout")
            time.sleep(self.poll_interval)

    def set_status(self, activation_id: str, status: int | str) -> str:
        return self._request("setStatus", id=str(activation_id or "").strip(), status=status)

    def finish(self, activation_id: str) -> str:
        return self.set_status(activation_id, 6)

    def cancel(self, activation_id: str) -> str:
        return self.set_status(activation_id, 8)


def resolve_activation(config: dict, *, session: Any | None = None) -> HeroSmsActivation:
    activation_id = str(config.get("reuse_activation_id") or "").strip()
    phone = str(config.get("reuse_phone") or "").strip()
    if activation_id and phone:
        return HeroSmsActivation(activation_id=activation_id, phone=phone, raw="REUSE_ACTIVATION")

    client = HeroSmsClient(
        str(config.get("api_key") or "").strip(),
        session=session,
        poll_interval=float(config.get("poll_interval") or 5),
    )
    return client.get_number(
        service=str(config.get("service") or OPENAI_SERVICE_CODE).strip() or OPENAI_SERVICE_CODE,
        country=int(config.get("country") or 16),
        operator=str(config.get("operator") or "any").strip() or "any",
    )
