"""Push a freshly registered account as a CPA auth file to CLIProxyAPI."""

from __future__ import annotations

import json
from typing import Any

from curl_cffi import CurlMime
from curl_cffi.requests import Session

from services.cpa_export_service import build_cpa_payload, safe_cpa_filename
from services.proxy_service import proxy_settings


def _clean(value: object) -> str:
    return str(value or "").strip()


def _management_headers(secret_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {secret_key}",
        "Accept": "application/json",
    }


def build_cpa_upload_file(register_result: dict[str, Any], account_snapshot: dict[str, Any] | None = None) -> tuple[str, bytes]:
    """Build one CPA JSON file from the token bundle plus the refreshed account snapshot."""
    source = {**(account_snapshot or {}), **(register_result or {})}
    payload = build_cpa_payload(source)
    filename = safe_cpa_filename(payload.get("email") or payload.get("account_id"), 0)
    content = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    return filename, content


def push_cpa_auth_file(
    register_result: dict[str, Any],
    cpa_auto_import: dict[str, Any] | None,
    account_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Upload one CPA JSON auth file through CLIProxyAPI Management API.

    Failure is reported as data, not raised, so callers can keep registration success intact.
    """
    config = cpa_auto_import if isinstance(cpa_auto_import, dict) else {}
    if not bool(config.get("enabled")):
        return {"ok": True, "uploaded": False, "skipped": True, "reason": "disabled"}

    base_url = _clean(config.get("base_url")).rstrip("/")
    secret_key = _clean(config.get("secret_key"))
    if not base_url or not secret_key:
        return {
            "ok": False,
            "uploaded": False,
            "skipped": False,
            "error": "CPA 自动导入已启用，但 base_url 或 secret_key 为空",
        }

    filename, content = build_cpa_upload_file(register_result, account_snapshot)
    url = f"{base_url}/v0/management/auth-files"
    session = Session(**proxy_settings.build_session_kwargs(verify=True))
    multipart = CurlMime()
    try:
        multipart.addpart(
            name="file",
            filename=filename,
            content_type="application/json",
            data=content,
        )
        response = session.post(
            url,
            headers=_management_headers(secret_key),
            multipart=multipart,
            timeout=30,
        )
        try:
            response_payload = response.json()
        except Exception:
            response_payload = {"raw": _clean(getattr(response, "text", ""))}

        if not response.ok:
            error_text = ""
            if isinstance(response_payload, dict):
                error_text = _clean(response_payload.get("error") or response_payload.get("message") or response_payload.get("raw"))
            if not error_text:
                error_text = _clean(getattr(response, "text", ""))
            return {
                "ok": False,
                "uploaded": False,
                "skipped": False,
                "name": filename,
                "status_code": int(getattr(response, "status_code", 0) or 0),
                "error": f"HTTP {getattr(response, 'status_code', 0)}{': ' + error_text if error_text else ''}",
                "response": response_payload,
            }

        return {
            "ok": True,
            "uploaded": True,
            "skipped": False,
            "name": filename,
            "status_code": int(getattr(response, "status_code", 0) or 0),
            "response": response_payload,
        }
    except Exception as exc:
        return {
            "ok": False,
            "uploaded": False,
            "skipped": False,
            "name": filename,
            "error": str(exc) or exc.__class__.__name__,
        }
    finally:
        multipart.close()
        session.close()
