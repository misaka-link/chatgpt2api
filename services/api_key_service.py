from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Callable

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
OPENAI_KEYS_FILE = DATA_DIR / "openai_keys.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(value: object) -> str:
    return str(value or "").strip()


def _key_hash(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _key_hint(secret: str) -> str:
    value = _clean(secret)
    if len(value) <= 12:
        return f"{value[:4]}..."
    return f"{value[:7]}...{value[-4:]}"


def check_openai_key_with_models(secret: str) -> dict[str, Any]:
    from curl_cffi import requests

    from services.proxy_service import proxy_settings

    session = requests.Session(**proxy_settings.build_session_kwargs(verify=True))
    try:
        response = session.get(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {secret}", "Accept": "application/json"},
            timeout=30,
        )
    finally:
        session.close()

    status_code = int(response.status_code)
    try:
        payload = response.json()
    except Exception:
        payload = {}

    if status_code == 200:
        models = payload.get("data") if isinstance(payload, dict) else []
        model_ids = [
            _clean(item.get("id"))
            for item in models
            if isinstance(item, dict) and _clean(item.get("id"))
        ]
        return {
            "status": "ok",
            "http_status": status_code,
            "models_count": len(model_ids),
            "sample_models": model_ids[:8],
            "last_error": None,
        }

    message = ""
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = _clean(error.get("message") or error.get("code") or error.get("type"))
        else:
            message = _clean(payload.get("message"))
    if not message:
        message = response.text[:300]

    if status_code == 401:
        status = "invalid"
    elif status_code == 429:
        status = "rate_limited"
    elif status_code == 403:
        status = "forbidden"
    else:
        status = "error"
    return {
        "status": status,
        "http_status": status_code,
        "models_count": 0,
        "sample_models": [],
        "last_error": message or f"HTTP {status_code}",
    }


class OpenAIKeyService:
    def __init__(
            self,
            store_file: Path = OPENAI_KEYS_FILE,
            checker: Callable[[str], dict[str, Any]] = check_openai_key_with_models,
    ) -> None:
        self.store_file = store_file
        self.checker = checker
        self._lock = Lock()
        self._items = self._load()

    def _load(self) -> list[dict[str, Any]]:
        try:
            raw = json.loads(self.store_file.read_text(encoding="utf-8"))
        except Exception:
            return []
        if not isinstance(raw, list):
            return []
        items = []
        for item in raw:
            if isinstance(item, dict) and _clean(item.get("key")):
                normalized = self._normalize(item)
                if normalized is not None:
                    items.append(normalized)
        return items

    def _save(self) -> None:
        self.store_file.parent.mkdir(parents=True, exist_ok=True)
        self.store_file.write_text(json.dumps(self._items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _normalize(self, item: dict[str, Any]) -> dict[str, Any] | None:
        secret = _clean(item.get("key"))
        if not secret:
            return None
        created_at = _clean(item.get("created_at")) or _now()
        return {
            "id": _clean(item.get("id")) or uuid.uuid4().hex,
            "name": _clean(item.get("name")) or "OpenAI API Key",
            "key": secret,
            "key_hash": _clean(item.get("key_hash")) or _key_hash(secret),
            "key_hint": _key_hint(secret),
            "status": _clean(item.get("status")) or "unchecked",
            "http_status": item.get("http_status"),
            "models_count": int(item.get("models_count") or 0),
            "sample_models": item.get("sample_models") if isinstance(item.get("sample_models"), list) else [],
            "last_error": item.get("last_error"),
            "last_checked_at": _clean(item.get("last_checked_at")),
            "created_at": created_at,
            "updated_at": _clean(item.get("updated_at")) or created_at,
        }

    @staticmethod
    def _sanitize(item: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in item.items()
            if key not in {"key", "key_hash"}
        }

    def list_keys(self) -> list[dict[str, Any]]:
        with self._lock:
            return [self._sanitize(dict(item)) for item in self._items]

    def add_key(self, name: str, secret: str, *, check: bool = False) -> dict[str, Any]:
        secret = _clean(secret)
        if not secret:
            raise ValueError("api key is required")
        if not secret.startswith("sk-"):
            raise ValueError("api key must start with sk-")
        digest = _key_hash(secret)
        with self._lock:
            if any(item.get("key_hash") == digest for item in self._items):
                raise ValueError("api key already exists")
            item = self._normalize({"name": name, "key": secret})
            if item is None:
                raise ValueError("api key is required")
            self._items.append(item)
            self._save()
            key_id = item["id"]
        if check:
            return self.check_key(key_id)
        return self._sanitize(item)

    def delete_key(self, key_id: str) -> bool:
        key_id = _clean(key_id)
        with self._lock:
            before = len(self._items)
            self._items = [item for item in self._items if item.get("id") != key_id]
            removed = len(self._items) != before
            if removed:
                self._save()
            return removed

    def check_key(self, key_id: str) -> dict[str, Any]:
        key_id = _clean(key_id)
        with self._lock:
            item = next((item for item in self._items if item.get("id") == key_id), None)
            if item is None:
                raise KeyError(key_id)
            secret = str(item["key"])

        try:
            result = self.checker(secret)
        except Exception as exc:
            result = {
                "status": "error",
                "http_status": None,
                "models_count": 0,
                "sample_models": [],
                "last_error": str(exc),
            }

        with self._lock:
            item = next((item for item in self._items if item.get("id") == key_id), None)
            if item is None:
                raise KeyError(key_id)
            item.update(
                {
                    "status": _clean(result.get("status")) or "error",
                    "http_status": result.get("http_status"),
                    "models_count": int(result.get("models_count") or 0),
                    "sample_models": result.get("sample_models") if isinstance(result.get("sample_models"), list) else [],
                    "last_error": result.get("last_error"),
                    "last_checked_at": _now(),
                    "updated_at": _now(),
                }
            )
            self._save()
            return self._sanitize(dict(item))


openai_key_service = OpenAIKeyService()
