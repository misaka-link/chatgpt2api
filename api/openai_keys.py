from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from api.support import require_admin
from services.api_key_service import openai_key_service


class OpenAIKeyCreateRequest(BaseModel):
    name: str = ""
    key: str = ""
    check: bool = False


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/openai-keys")
    async def list_openai_keys(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"items": openai_key_service.list_keys()}

    @router.post("/api/openai-keys")
    async def create_openai_key(body: OpenAIKeyCreateRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            item = await run_in_threadpool(openai_key_service.add_key, body.name, body.key, check=body.check)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        return {"item": item, "items": openai_key_service.list_keys()}

    @router.post("/api/openai-keys/{key_id}/check")
    async def check_openai_key(key_id: str, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            item = await run_in_threadpool(openai_key_service.check_key, key_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"error": "api key not found"}) from exc
        return {"item": item, "items": openai_key_service.list_keys()}

    @router.delete("/api/openai-keys/{key_id}")
    async def delete_openai_key(key_id: str, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        if not openai_key_service.delete_key(key_id):
            raise HTTPException(status_code=404, detail={"error": "api key not found"})
        return {"items": openai_key_service.list_keys()}

    return router
