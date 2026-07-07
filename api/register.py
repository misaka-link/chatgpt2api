from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.support import require_admin
from services.register_service import register_service


class RegisterConfigRequest(BaseModel):
    mail: dict | None = None
    proxy: str | None = None
    total: int | None = None
    threads: int | None = None
    mode: str | None = None
    target_quota: int | None = None
    target_available: int | None = None
    check_interval: int | None = None
    account_refresh_interval_minute: int | None = None


class OutlookPoolResetRequest(BaseModel):
    scope: str | None = None


class RegisterReputationBlacklistedDomainRequest(BaseModel):
    provider: str
    provider_ref: str | None = None
    domain: str
    reason: str | None = None
    previous_domain: str | None = None


class RegisterReputationBlacklistedDomainDeleteRequest(BaseModel):
    provider: str
    provider_ref: str | None = None
    domain: str


class RegisterReputationTrustedDomainRequest(BaseModel):
    provider: str
    provider_ref: str | None = None
    domain: str
    previous_domain: str | None = None


class RegisterReputationTrustedDomainDeleteRequest(BaseModel):
    provider: str
    provider_ref: str | None = None
    domain: str


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/register")
    async def get_register_config(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"register": register_service.get()}

    @router.post("/api/register")
    async def update_register_config(body: RegisterConfigRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"register": register_service.update(body.model_dump(exclude_none=True))}

    @router.post("/api/register/start")
    async def start_register(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"register": register_service.start()}

    @router.post("/api/register/stop")
    async def stop_register(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"register": register_service.stop()}

    @router.post("/api/register/reset")
    async def reset_register(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"register": register_service.reset()}

    @router.post("/api/register/outlook-pool/reset")
    async def reset_outlook_pool(body: OutlookPoolResetRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"register": register_service.reset_outlook_pool(body.scope or "all")}

    @router.get("/api/register/reputation")
    async def get_register_reputation(provider: str = "", provider_ref: str = "", authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"reputation": register_service.get_reputation(provider, provider_ref)}

    @router.post("/api/register/reputation/blacklisted-domains")
    async def upsert_register_reputation_blacklisted_domain(body: RegisterReputationBlacklistedDomainRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            return {
                "reputation": register_service.upsert_reputation_blacklisted_domain(
                    body.provider,
                    body.provider_ref or "",
                    body.domain,
                    body.reason or "",
                    body.previous_domain or "",
                )
            }
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @router.post("/api/register/reputation/blacklisted-domains/delete")
    async def delete_register_reputation_blacklisted_domain(body: RegisterReputationBlacklistedDomainDeleteRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            return {"reputation": register_service.delete_reputation_blacklisted_domain(body.provider, body.provider_ref or "", body.domain)}
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @router.post("/api/register/reputation/trusted-domains")
    async def upsert_register_reputation_domain(body: RegisterReputationTrustedDomainRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            return {"reputation": register_service.upsert_reputation_domain(body.provider, body.provider_ref or "", body.domain, body.previous_domain or "")}
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @router.post("/api/register/reputation/trusted-domains/delete")
    async def delete_register_reputation_domain(body: RegisterReputationTrustedDomainDeleteRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            return {"reputation": register_service.delete_reputation_domain(body.provider, body.provider_ref or "", body.domain)}
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @router.get("/api/register/events")
    async def register_events(token: str = ""):
        require_admin(f"Bearer {token}")

        async def stream():
            last = ""
            while True:
                payload = json.dumps(register_service.get(), ensure_ascii=False)
                if payload != last:
                    last = payload
                    yield f"data: {payload}\n\n"
                await asyncio.sleep(0.5)

        return StreamingResponse(stream(), media_type="text/event-stream")

    return router
