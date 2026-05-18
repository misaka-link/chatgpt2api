from __future__ import annotations

import time

from services.codex_cpa_service import build_codex_upload_file
from services.cpa_push_service import upload_auth_file
from services.cpa_service import cpa_config, list_remote_files
from services import hero_sms_country_reputation as country_reputation
from services.register import openai_register
from services.register.openai_register import PlatformRegistrar

CPA_UPLOAD_VERIFY_ATTEMPTS = 3
CPA_UPLOAD_VERIFY_DELAY_SECONDS = 1.0


def _first_cpa_pool() -> dict:
    pools = cpa_config.list_pools()
    if not pools:
        raise RuntimeError("未配置 CPA 号池，无法上传 Codex auth file")
    return pools[0]


def _codex_tokens(result: dict) -> dict:
    return {
        "email": str(result.get("email") or "").strip(),
        "access_token": str(result.get("access_token") or "").strip(),
        "refresh_token": str(result.get("refresh_token") or "").strip(),
        "id_token": str(result.get("id_token") or "").strip(),
    }


def _hero_sms_meta(result: dict) -> dict:
    hero_sms = result.get("hero_sms") if isinstance(result.get("hero_sms"), dict) else {}
    return hero_sms if isinstance(hero_sms, dict) else {}


def _record_cpa_fail(result: dict, reason: str) -> None:
    hero_sms = _hero_sms_meta(result)
    if not hero_sms:
        return
    country_reputation.store.record_event(
        hero_sms.get("country"),
        "cpa_fail",
        price=hero_sms.get("price"),
        reason=reason,
    )


def _verify_uploaded_file(pool: dict, filename: str) -> dict:
    expected = str(filename or "").strip()
    if not expected:
        raise RuntimeError("CPA 上传验证失败: filename 为空")
    last_files: list[dict] = []
    attempts = max(1, int(CPA_UPLOAD_VERIFY_ATTEMPTS or 1))
    delay = max(0.0, float(CPA_UPLOAD_VERIFY_DELAY_SECONDS or 0))
    for attempt in range(1, attempts + 1):
        last_files = list_remote_files(pool)
        for item in last_files:
            if str(item.get("name") or "").strip() == expected:
                return {"verified": True, "attempt": attempt, "remote_count": len(last_files)}
        if attempt < attempts and delay:
            time.sleep(delay)
    preview = ", ".join(str(item.get("name") or "").strip() for item in last_files[:8] if item.get("name"))
    raise RuntimeError(
        "CPA 上传后未在远端列表中确认: "
        f"pool={pool.get('id') or '-'}, file={expected}, remote_count={len(last_files)}, preview={preview or '-'}"
    )


def run_codex_registration(index: int, *, pool: dict | None = None) -> dict:
    pool = pool or _first_cpa_pool()
    start = time.time()
    registrar = PlatformRegistrar(openai_register.config.get("proxy") or "")
    try:
        openai_register.step(index, "Codex CPA 注册任务启动")
        result = registrar.register(index, profile=openai_register.codex_oauth_profile)
        openai_register._record_mail_success(result)

        filename, body = build_codex_upload_file(_codex_tokens(result))
        try:
            upload_auth_file(pool, filename, body)
            verify_result = _verify_uploaded_file(pool, filename)
        except Exception as exc:
            _record_cpa_fail(result, f"codex_cpa_upload_failed:{openai_register.redact_sensitive_text(exc)}")
            openai_register.step(index, f"Codex CPA 上传/确认失败: {openai_register.redact_sensitive_text(exc)}", "red")
            raise
        hero_sms = _hero_sms_meta(result)
        if hero_sms:
            country_reputation.store.record_event(
                hero_sms.get("country"),
                "cpa_success",
                price=hero_sms.get("price"),
                reason="codex_cpa_uploaded",
            )
        cost = time.time() - start
        openai_register.step(index, f"Codex CPA 上传完成: pool={pool.get('id')}, file={filename}, 耗时{cost:.1f}s", "green")
        return {
            "ok": True,
            "index": index,
            "result": result,
            "cpa": {
                "pool_id": str(pool.get("id") or "").strip(),
                "filename": filename,
                "verified": bool(verify_result.get("verified")),
                "verify_attempt": int(verify_result.get("attempt") or 0),
                "remote_count": int(verify_result.get("remote_count") or 0),
            },
        }
    finally:
        registrar.close()
