from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from api.deps import require_runtime

router = APIRouter()


class RagModeRequest(BaseModel):
    enabled: bool


class PermissionModeRequest(BaseModel):
    mode: str


@router.get("/config/rag-mode")
async def get_rag_mode() -> dict[str, bool]:
    runtime = require_runtime()
    return {"enabled": runtime.settings.get_rag_mode()}


@router.put("/config/rag-mode")
async def set_rag_mode(payload: RagModeRequest) -> dict[str, bool]:
    runtime = require_runtime()
    config = runtime.settings.set_rag_mode(payload.enabled)
    return {"enabled": bool(config["rag_mode"])}


@router.get("/config/permission-mode")
async def get_permission_mode() -> dict[str, object]:
    runtime = require_runtime()
    return {
        "mode": runtime.settings.get_permission_mode(),
        "supported_modes": runtime.permission_service.supported_modes(),
    }


@router.put("/config/permission-mode")
async def set_permission_mode(payload: PermissionModeRequest) -> dict[str, object]:
    runtime = require_runtime()
    config = runtime.settings.set_permission_mode(payload.mode)
    return {
        "mode": str(config["permission_mode"]),
        "supported_modes": runtime.permission_service.supported_modes(),
    }
