from __future__ import annotations

from typing import Any

from curl_cffi import CurlMime
from curl_cffi.requests import Session

from services.proxy_service import proxy_settings


def _management_headers(secret_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {secret_key}",
        "Accept": "application/json",
    }


def upload_auth_file(pool: dict, filename: str, content: bytes, *, session: Any | None = None) -> dict:
    base_url = str(pool.get("base_url") or "").strip()
    secret_key = str(pool.get("secret_key") or "").strip()
    filename = str(filename or "").strip()
    if not base_url or not secret_key:
        raise ValueError("CPA base_url and secret_key are required")
    if not filename or not content:
        raise ValueError("auth file filename and content are required")

    owned_session = session is None
    upload_url = f"{base_url.rstrip('/')}/v0/management/auth-files"
    session = session or Session(**proxy_settings.build_session_kwargs_for_url(upload_url, verify=True))
    multipart = CurlMime()
    try:
        multipart.addpart(
            name="file",
            filename=filename,
            content_type="application/json",
            data=content,
        )
        response = session.post(
            upload_url,
            headers=_management_headers(secret_key),
            multipart=multipart,
            timeout=30,
        )
        if not getattr(response, "ok", False):
            raise RuntimeError(f"CPA upload failed: HTTP {getattr(response, 'status_code', 'unknown')}")
        try:
            payload = response.json()
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}
    finally:
        try:
            multipart.close()
        finally:
            if owned_session:
                session.close()
