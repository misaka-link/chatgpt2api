from __future__ import annotations

from typing import Any

from services.account_service import account_service
from services.openai_backend_api import OpenAIBackendAPI
from utils.helper import CODEX_IMAGE_MODEL, IMAGE_MODELS


LOCAL_TEXT_MODELS = {
    "auto",
    "gpt-5",
    "gpt-5-1",
    "gpt-5-2",
    "gpt-5-3",
    "gpt-5-3-mini",
    "gpt-5-mini",
}


def _model_item(model: str, owned_by: str = "chatgpt2api") -> dict[str, Any]:
    return {
        "id": model,
        "object": "model",
        "created": 0,
        "owned_by": owned_by,
        "permission": [],
        "root": model,
        "parent": None,
    }


def _local_catalog() -> dict[str, Any]:
    models = sorted(LOCAL_TEXT_MODELS | IMAGE_MODELS)
    return {"object": "list", "data": [_model_item(model) for model in models]}


def _append_models(result: dict[str, Any], models: set[str]) -> dict[str, Any]:
    data = result.get("data")
    if not isinstance(data, list):
        return result
    seen = {str(item.get("id") or "").strip() for item in data if isinstance(item, dict)}
    for model in sorted(models):
        if model not in seen:
            data.append(_model_item(model))
    return result


def _append_local_text_models(result: dict[str, Any]) -> dict[str, Any]:
    return _append_models(result, LOCAL_TEXT_MODELS)


def _append_dynamic_image_models(result: dict[str, Any]) -> dict[str, Any]:
    dynamic_models: set[str] = set()
    try:
        accounts = account_service.list_accounts()
    except Exception:
        accounts = []
    web_image_accounts = [
        account
        for account in accounts
        if isinstance(account, dict)
    ]
    codex_types = {
        normalized
        for account in accounts
        if isinstance(account, dict)
           and account_service._normalize_source_type(account.get("source_type")) == "codex"
           and (normalized := account_service._normalize_account_type(account.get("type")))
    }

    if web_image_accounts:
        dynamic_models.add("gpt-image-2")
    if codex_types & {"Plus", "Team", "Pro"}:
        dynamic_models.add(CODEX_IMAGE_MODEL)
    if "Plus" in codex_types:
        dynamic_models.add(f"plus-{CODEX_IMAGE_MODEL}")
    if "Team" in codex_types:
        dynamic_models.add(f"team-{CODEX_IMAGE_MODEL}")
    if "Pro" in codex_types:
        dynamic_models.add(f"pro-{CODEX_IMAGE_MODEL}")

    return _append_models(result, dynamic_models)


def _append_local_models(result: dict[str, Any]) -> dict[str, Any]:
    return _append_dynamic_image_models(_append_local_text_models(result))


def list_models() -> dict[str, Any]:
    access_token = account_service.peek_text_access_token()
    try:
        result = OpenAIBackendAPI(access_token=access_token).list_models()
    except Exception:
        if not access_token:
            return _local_catalog()
        try:
            result = OpenAIBackendAPI().list_models()
        except Exception:
            return _local_catalog()
    return _append_local_models(result)
