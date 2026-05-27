from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from api.deps import require_runtime

router = APIRouter()


class RagModeRequest(BaseModel):
    enabled: bool


class PermissionModeRequest(BaseModel):
    mode: str


class ContextBudgetPresetRequest(BaseModel):
    preset_id: str


class ModelProviderRequest(BaseModel):
    provider: str
    model: str
    base_url: str
    api_key: str | None = None


class RuntimeConfigGroupRequest(BaseModel):
    group_id: str
    values: dict[str, object]


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


@router.get("/config/context-budget")
async def get_context_budget() -> dict[str, object]:
    runtime = require_runtime()
    return runtime.settings.context_budget_payload()


@router.put("/config/context-budget")
async def set_context_budget(payload: ContextBudgetPresetRequest) -> dict[str, object]:
    runtime = require_runtime()
    runtime.settings.set_context_budget_preset(payload.preset_id)
    return runtime.settings.context_budget_payload()


@router.get("/config/model-provider")
async def get_model_provider() -> dict[str, object]:
    runtime = require_runtime()
    return runtime.settings.model_provider_payload()


@router.put("/config/model-provider")
async def set_model_provider(payload: ModelProviderRequest) -> dict[str, object]:
    runtime = require_runtime()
    return runtime.settings.set_model_provider(
        provider=payload.provider,
        model=payload.model,
        base_url=payload.base_url,
        api_key=payload.api_key,
    )


@router.get("/config/runtime-console")
async def get_runtime_config_console() -> dict[str, object]:
    runtime = require_runtime()
    return runtime.settings.runtime_config_console_payload()


@router.put("/config/runtime-console")
async def set_runtime_config_group(payload: RuntimeConfigGroupRequest) -> dict[str, object]:
    runtime = require_runtime()
    return runtime.settings.set_runtime_config_group(payload.group_id, dict(payload.values))


