from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DATA_DIR = Path(__file__).resolve().parents[2] / "data"
DEFAULT_FILE = DATA_DIR / "mail_domain_reputation.json"

HARD_FAILURE_MARKERS = (
    "unsupported_email",
    "account_creation_failed",
    "registration_disallowed",
    "Sorry, we cannot create your account with the given information.",
    "The email you provided is not supported",
    "Failed to create account. Please try again.",
)

SOFT_FAILURE_MARKERS = (
    "等待注册验证码超时",
    "独立登录等待验证码超时",
    "YYDSMail 请求异常",
    "SSLError",
    "ProxyError",
    "RemoteDisconnected",
    "token换取失败",
    "oauth_token_exchange_failed",
)

SOFT_FAIL_SCORE_PENALTY = 120
CONSECUTIVE_FAIL_SCORE_PENALTY = 500
HARD_FAIL_SCORE_PENALTY = 2000
CONSECUTIVE_FAIL_SKIP_THRESHOLD = 3


def _stats(record: dict[str, Any]) -> tuple[int, int, int, int]:
    return (
        int(record.get("success") or 0),
        int(record.get("hard_fail") or 0),
        int(record.get("soft_fail") or 0),
        int(record.get("consecutive_fail") or 0),
    )


def _score(record: dict[str, Any]) -> int:
    success, hard_fail, soft_fail, consecutive_fail = _stats(record)
    return (
        success * 100
        - hard_fail * HARD_FAIL_SCORE_PENALTY
        - soft_fail * SOFT_FAIL_SCORE_PENALTY
        - consecutive_fail * CONSECUTIVE_FAIL_SCORE_PENALTY
    )


def _healthy(record: dict[str, Any]) -> bool:
    if bool(record.get("disabled")):
        return False
    success, hard_fail, soft_fail, consecutive_fail = _stats(record)
    if hard_fail:
        return False
    if consecutive_fail >= CONSECUTIVE_FAIL_SKIP_THRESHOLD:
        return False
    if success > 0 and soft_fail > success:
        return False
    if success == 0 and soft_fail > 0:
        return False
    return True


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _domain(value: str) -> str:
    text = str(value or "").strip().lower()
    if "@" in text:
        text = text.rsplit("@", 1)[-1]
    return text.strip(".")


def _domains(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        domain = _domain(value)
        if not domain or domain in seen:
            continue
        seen.add(domain)
        out.append(domain)
    return out


def _provider(value: str) -> str:
    text = str(value or "").strip()
    return text or "unknown"


def _provider_root(value: str) -> str:
    text = _provider(value)
    return text.split("#", 1)[0].strip() or text


def _manual_domain(value: str) -> str:
    normalized = _domain(value)
    if not normalized or "." not in normalized:
        raise ValueError("域名不能为空")
    return normalized


def classify_failure(reason: str) -> str:
    text = str(reason or "")
    if any(marker in text for marker in HARD_FAILURE_MARKERS):
        return "hard"
    if any(marker in text for marker in SOFT_FAILURE_MARKERS):
        return "soft"
    return "soft"


class DomainReputationStore:
    def __init__(self, file_path: Path = DEFAULT_FILE):
        self.file_path = Path(file_path)
        self._lock = threading.RLock()

    def _load_locked(self) -> dict[str, Any]:
        try:
            data = json.loads(self.file_path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        data = data if isinstance(data, dict) else {}
        if self._migrate_legacy_mailboxes_locked(data):
            self._save_locked(data)
        return data

    def _save_locked(self, data: dict[str, Any]) -> None:
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.file_path.with_suffix(self.file_path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.file_path)

    def _record(self, data: dict[str, Any], provider: str, domain: str) -> dict[str, Any]:
        providers = data.setdefault("providers", {})
        provider_data = providers.setdefault(_provider_root(provider), {})
        domains = provider_data.setdefault("domains", {})
        record = domains.setdefault(domain, {})
        record.setdefault("success", 0)
        record.setdefault("hard_fail", 0)
        record.setdefault("soft_fail", 0)
        record.setdefault("consecutive_fail", 0)
        record.setdefault("disabled", False)
        return record

    def _provider_data(self, data: dict[str, Any], provider: str) -> dict[str, Any]:
        providers = data.setdefault("providers", {})
        return providers.setdefault(_provider_root(provider), {})

    def _domain_payload(self, domain: str, record: dict[str, Any]) -> dict[str, Any]:
        return {
            "domain": str(domain),
            "success": int(record.get("success") or 0),
            "hard_fail": int(record.get("hard_fail") or 0),
            "soft_fail": int(record.get("soft_fail") or 0),
            "consecutive_fail": int(record.get("consecutive_fail") or 0),
            "disabled": bool(record.get("disabled")),
            "healthy": _healthy(record),
            "score": _score(record),
            "last_success_at": str(record.get("last_success_at") or ""),
            "last_failure_at": str(record.get("last_failure_at") or ""),
            "last_failure_reason": str(record.get("last_failure_reason") or ""),
        }

    def _blacklisted_domain_payload(self, domain: str, record: dict[str, Any]) -> dict[str, Any]:
        item = self._domain_payload(domain, record)
        item["reason"] = str(record.get("last_failure_reason") or "")
        item["updated_at"] = str(record.get("last_failure_at") or "")
        return item

    def _migrate_legacy_mailboxes_locked(self, data: dict[str, Any]) -> bool:
        providers = data.get("providers")
        if not isinstance(providers, dict):
            return False
        changed = False
        for provider_key, provider_data in list(providers.items()):
            if not isinstance(provider_data, dict):
                continue
            mailboxes = provider_data.pop("mailboxes", None)
            if not isinstance(mailboxes, dict):
                continue
            changed = True
            for address, record in mailboxes.items():
                if not isinstance(record, dict) or not bool(record.get("disabled")):
                    continue
                domain = _domain(address)
                if not domain:
                    continue
                target = self._record(data, provider_key, domain)
                target["disabled"] = True
                updated_at = str(record.get("updated_at") or "")
                reason = str(record.get("reason") or "")[:500]
                current_updated = str(target.get("last_failure_at") or "")
                if updated_at and (not current_updated or updated_at >= current_updated):
                    target["last_failure_at"] = updated_at
                    target["last_failure_reason"] = reason
                elif reason and not target.get("last_failure_reason"):
                    target["last_failure_reason"] = reason
            if not provider_data:
                providers.pop(provider_key, None)
        return changed

    def record_success(self, provider: str, domain: str) -> dict[str, Any]:
        domain = _domain(domain)
        if not domain:
            return {}
        with self._lock:
            data = self._load_locked()
            record = self._record(data, provider, domain)
            record["success"] = int(record.get("success") or 0) + 1
            record["consecutive_fail"] = 0
            record["disabled"] = False
            record["last_success_at"] = _now()
            self._save_locked(data)
            return dict(record)

    def record_failure(self, provider: str, domain: str, reason: str) -> dict[str, Any]:
        domain = _domain(domain)
        if not domain:
            return {"bucket": classify_failure(reason), "disabled": False, "disabled_changed": False}
        bucket = classify_failure(reason)
        with self._lock:
            data = self._load_locked()
            record = self._record(data, provider, domain)
            was_disabled = bool(record.get("disabled"))
            if bucket == "hard":
                record["hard_fail"] = int(record.get("hard_fail") or 0) + 1
                record["disabled"] = True
            else:
                record["soft_fail"] = int(record.get("soft_fail") or 0) + 1
            record["consecutive_fail"] = int(record.get("consecutive_fail") or 0) + 1
            record["last_failure_at"] = _now()
            record["last_failure_reason"] = str(reason or "")[:500]
            self._save_locked(data)
            out = dict(record)
            out["bucket"] = bucket
            out["disabled_changed"] = bool(record.get("disabled")) and not was_disabled
            return out

    def is_disabled(self, provider: str, domain: str) -> bool:
        domain = _domain(domain)
        if not domain:
            return False
        with self._lock:
            data = self._load_locked()
            record = (((data.get("providers") or {}).get(_provider_root(provider)) or {}).get("domains") or {}).get(domain) or {}
            return bool(record.get("disabled"))

    def filter_domains(self, provider: str, domains: list[str]) -> list[str]:
        normalized = _domains(domains)
        if not normalized:
            return []
        enabled = [item for item in normalized if not self.is_disabled(provider, item)]
        return enabled or normalized

    def preferred_domains(self, provider: str, domains: list[str]) -> list[str]:
        normalized = _domains(domains)
        if not normalized:
            return []
        with self._lock:
            data = self._load_locked()
            records = (((data.get("providers") or {}).get(_provider_root(provider)) or {}).get("domains") or {})
            scored: list[tuple[int, str]] = []
            for domain in normalized:
                record = records.get(domain) or {}
                if bool(record.get("disabled")):
                    continue
                scored.append((_score(record), domain))
            if not scored:
                return []
            healthy = [(score, domain) for score, domain in scored if _healthy(records.get(domain) or {})]
            if healthy:
                scored = healthy
            best = max(score for score, _ in scored)
            return [domain for score, domain in scored if score == best]

    def usable_domains(self, provider: str, domains: list[str]) -> list[str]:
        normalized = _domains(domains)
        if not normalized:
            return []
        with self._lock:
            data = self._load_locked()
            records = (((data.get("providers") or {}).get(_provider_root(provider)) or {}).get("domains") or {})
            scored: list[tuple[int, str]] = []
            for domain in normalized:
                record = records.get(domain) or {}
                if bool(record.get("disabled")):
                    continue
                scored.append((_score(record), domain))
            if not scored:
                return []
            healthy = [(score, domain) for score, domain in scored if _healthy(records.get(domain) or {})]
            candidates = healthy or scored
            return [domain for _, domain in sorted(candidates, key=lambda item: (-item[0], item[1]))]

    def good_domains(self, provider: str) -> list[str]:
        with self._lock:
            data = self._load_locked()
            domains = (((data.get("providers") or {}).get(_provider_root(provider)) or {}).get("domains") or {})
            items = []
            for domain, record in domains.items():
                if not isinstance(record, dict) or bool(record.get("disabled")):
                    continue
                if int(record.get("success") or 0) <= 0 or not _healthy(record):
                    continue
                items.append((_score(record), str(domain)))
            return [domain for _, domain in sorted(items, key=lambda item: (-item[0], item[1]))]

    def list_blacklisted_domains(self, provider: str) -> list[dict[str, Any]]:
        with self._lock:
            data = self._load_locked()
            domains = (((data.get("providers") or {}).get(_provider_root(provider)) or {}).get("domains") or {})
            items = []
            for domain, record in domains.items():
                if not isinstance(record, dict) or not bool(record.get("disabled")):
                    continue
                items.append(self._blacklisted_domain_payload(str(domain), record))
            return sorted(items, key=lambda item: (item["updated_at"], item["domain"]), reverse=True)

    def upsert_blacklisted_domain(self, provider: str, domain: str, reason: str = "", previous_domain: str = "") -> dict[str, Any]:
        normalized = _manual_domain(domain)
        previous = _manual_domain(previous_domain) if str(previous_domain or "").strip() else ""
        with self._lock:
            data = self._load_locked()
            provider_data = self._provider_data(data, provider)
            domains = provider_data.setdefault("domains", {})
            seed = domains.get(previous) if previous and previous != normalized else domains.get(normalized)
            record = dict(seed) if isinstance(seed, dict) else {}
            record.setdefault("success", 0)
            record.setdefault("hard_fail", 0)
            record.setdefault("soft_fail", 0)
            record.setdefault("consecutive_fail", 0)
            if previous and previous != normalized:
                domains.pop(previous, None)
            record["disabled"] = True
            record["last_failure_at"] = _now()
            record["last_failure_reason"] = str(reason or record.get("last_failure_reason") or "")[:500]
            domains[normalized] = record
            self._save_locked(data)
            return self._blacklisted_domain_payload(normalized, record)

    def delete_blacklisted_domain(self, provider: str, domain: str) -> bool:
        normalized = _manual_domain(domain)
        with self._lock:
            data = self._load_locked()
            provider_data = self._provider_data(data, provider)
            domains = provider_data.setdefault("domains", {})
            removed = domains.pop(normalized, None)
            self._save_locked(data)
            return removed is not None

    def list_trusted_domains(self, provider: str) -> list[dict[str, Any]]:
        with self._lock:
            data = self._load_locked()
            domains = (((data.get("providers") or {}).get(_provider_root(provider)) or {}).get("domains") or {})
            items = []
            for domain, record in domains.items():
                if not isinstance(record, dict) or bool(record.get("disabled")):
                    continue
                if int(record.get("success") or 0) <= 0:
                    continue
                items.append(self._domain_payload(str(domain), record))
            return sorted(items, key=lambda item: (-item["score"], item["domain"]))

    def upsert_trusted_domain(self, provider: str, domain: str, previous_domain: str = "") -> dict[str, Any]:
        normalized = _manual_domain(domain)
        previous = _manual_domain(previous_domain) if str(previous_domain or "").strip() else ""
        with self._lock:
            data = self._load_locked()
            provider_data = self._provider_data(data, provider)
            domains = provider_data.setdefault("domains", {})
            seed = domains.get(previous) if previous and previous != normalized else domains.get(normalized)
            record = dict(seed) if isinstance(seed, dict) else {}
            if previous and previous != normalized:
                domains.pop(previous, None)
            record["success"] = max(1, int(record.get("success") or 0))
            record["hard_fail"] = 0
            record["soft_fail"] = 0
            record["consecutive_fail"] = 0
            record["disabled"] = False
            record["last_success_at"] = _now()
            record.pop("last_failure_at", None)
            record.pop("last_failure_reason", None)
            domains[normalized] = record
            self._save_locked(data)
            return self._domain_payload(normalized, record)

    def delete_domain(self, provider: str, domain: str) -> bool:
        normalized = _manual_domain(domain)
        with self._lock:
            data = self._load_locked()
            provider_data = self._provider_data(data, provider)
            domains = provider_data.setdefault("domains", {})
            removed = domains.pop(normalized, None)
            self._save_locked(data)
            return removed is not None


store = DomainReputationStore()
