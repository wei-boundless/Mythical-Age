from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from api.deps import require_runtime
from agent_system.registry.agent_registry import AgentRegistry
from soul import SoulFacade
from soul.image_asset_service import SoulImageAssetError, SoulImageAssetService
from soul.registry import (
    ACTIVE_SEED_PATH,
    BUILTIN_SEED_PATHS,
    CORE_PATH,
    normalize_path,
    read_text,
)

router = APIRouter()

SOUL_PORTRAIT_MAX_BYTES = 8 * 1024 * 1024
SEED_PATHS = BUILTIN_SEED_PATHS
EDITABLE_SOUL_PATHS = {
    ACTIVE_SEED_PATH,
    CORE_PATH,
    *SEED_PATHS.values(),
}
HIDDEN_STYLE_SECTION_PATTERN = re.compile(r"^##\s+(?:身份锚点|Identity Anchor)\s*[\r\n]+[\s\S]*?(?=^##\s+|\Z)", re.MULTILINE)


class SoulSwitchRequest(BaseModel):
    key: str = Field(..., min_length=1)
    source: str = Field(default="frontend")


class SoulFileSaveRequest(BaseModel):
    path: str = Field(..., min_length=1)
    content: str
    reason: str = Field(default="frontend_edit")


class SoulSkillViewPayload(BaseModel):
    skill_id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    capability_summary: str = ""
    use_when: str = ""
    input_boundary: str = ""
    output_boundary: str = ""
    forbidden_uses: str = ""
    current_task_reason: str = ""


class SoulToolViewPayload(BaseModel):
    tool_id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    capability_summary: str = ""
    input_schema_summary: str = ""
    output_schema_summary: str = ""
    risk_summary: str = ""
    authorized: bool = False
    authorization_owner: str = "ResourcePolicy"
    requires_approval: bool = False
    available_to_model: bool = False
    runtime_executable: bool = False
    denied_reason: str = ""
    policy_decision: str = "unknown"


class SoulProjectionCardRequest(BaseModel):
    projection_id: str = ""
    soul_id: str = Field(..., min_length=1)
    projection_kind: str = "soul_projection"
    owner_system: str = "soul_system"
    source_task_graph_refs: list[str] = Field(default_factory=list)
    projection_nodes: list[dict[str, Any]] = Field(default_factory=list)
    identity_anchor: str = ""
    role_type: str = "dialogue"
    task_mode: str = "general_qa"
    agent_profile_id: str = "general_agent"
    projection_name: str = ""
    posture_tags: list[str] = Field(default_factory=list)
    expression_density: str = "normal"
    attention_focus: list[str] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)
    projection_prompt: str = ""
    skill_views: list[SoulSkillViewPayload] = Field(default_factory=list)
    tool_views: list[SoulToolViewPayload] = Field(default_factory=list)
    usage_summary: str = "可被任务系统选用的灵魂投影资源。"
    memory_policy_summary: str = "预览模式不授予记忆写回权。"
    output_contract_summary: str = "预览当前灵魂如何收束 prompt sections。"
    select_after_create: bool = True


class ProjectionInstancePreviewRequest(BaseModel):
    template_id: str = Field(..., min_length=1)
    task_id: str = Field(default="task-preview")
    task_run_id: str = ""
    agent_id: str = Field(default="agent:3")
    runtime_lane: str = Field(default="health_issue_read")
    resource_policy_ref: str = ""
    context_snapshot_ref: str = ""


class CustomSoulSaveRequest(BaseModel):
    soul_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    description: str = ""
    soul_markdown: str = Field(default="# Soul Seed\n")
    preferred_role_types: list[str] = Field(default_factory=list)
    preferred_task_modes: list[str] = Field(default_factory=list)
    enabled: bool = True


class SoulModePreviewRequest(BaseModel):
    mode: str = Field(default="work_mode", min_length=1)
    soul_id: str = Field(default="hebo", min_length=1)
    projection_id: str = ""
    work_prompt_id: str = ""
    task_contract: str = ""


class SoulImageAssetGenerateRequest(BaseModel):
    target_id: str = Field(..., min_length=1)
    asset_kind: str = Field(default="world", min_length=1)
    prompt: str = Field(..., min_length=1)
    size: str = Field(default="1024x1024")
    overwrite: bool = False


def _project_root_from_backend(base_dir: Path) -> Path:
    return base_dir.resolve().parent


def _portrait_path(base_dir: Path, key: str) -> Path:
    if key not in SEED_PATHS:
        raise HTTPException(status_code=404, detail="Unknown soul seed")
    souls_dir = (_project_root_from_backend(base_dir) / "frontend" / "public" / "souls").resolve()
    path = (souls_dir / f"{key}.png").resolve()
    if souls_dir not in path.parents:
        raise HTTPException(status_code=400, detail="Invalid portrait path")
    return path


def _resolve_soul_path(base_dir: Path, path: str) -> Path:
    registry = SoulFacade(base_dir).registry_service.registry
    try:
        return registry.resolve_editable_path(path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def build_soul_catalog(base_dir: Path) -> dict[str, Any]:
    return SoulFacade(base_dir).build_catalog()


@router.get("/soul/catalog")
async def soul_catalog() -> dict[str, Any]:
    runtime = require_runtime()
    return build_soul_catalog(runtime.base_dir)


@router.get("/soul/resources")
async def soul_resources() -> dict[str, Any]:
    runtime = require_runtime()
    return SoulFacade(runtime.base_dir).build_resource_catalog()


@router.post("/soul/switch")
async def switch_soul(payload: SoulSwitchRequest) -> dict[str, Any]:
    runtime = require_runtime()
    key = payload.key.strip().lower()
    facade = SoulFacade(runtime.base_dir)
    try:
        catalog = facade.switch(key)
        facade.list_projection_cards()
        AgentRegistry(runtime.base_dir).upsert_agent(
            agent_id="agent:0",
            default_soul_id=key,
            default_projection_id=f"{key}__primary",
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown soul seed") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Soul seed is empty or missing") from exc
    runtime.refresh_indexes_for_path(ACTIVE_SEED_PATH)
    return catalog


@router.put("/soul/files")
async def save_soul_file(payload: SoulFileSaveRequest) -> dict[str, Any]:
    runtime = require_runtime()
    normalized = normalize_path(payload.path)
    catalog = SoulFacade(runtime.base_dir).save_managed_file(normalized, payload.content)
    runtime.refresh_indexes_for_path(normalized)
    return catalog


@router.get("/soul/projections")
async def soul_projection_cards() -> dict[str, Any]:
    runtime = require_runtime()
    return SoulFacade(runtime.base_dir).list_projection_cards()


@router.get("/soul/projection-templates")
async def soul_projection_templates() -> dict[str, Any]:
    runtime = require_runtime()
    return SoulFacade(runtime.base_dir).build_template_catalog()


@router.get("/soul/projection-templates/{template_id}")
async def soul_projection_template_detail(template_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    template = SoulFacade(runtime.base_dir).get_template(template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Unknown projection template")
    return template.to_dict()


@router.get("/soul/{soul_id}/activity")
async def soul_work_log(soul_id: str, limit: int = 20) -> dict[str, Any]:
    runtime = require_runtime()
    normalized_soul_id = soul_id.strip().lower()
    facade = SoulFacade(runtime.base_dir)
    if facade.get_profile(normalized_soul_id) is None:
        raise HTTPException(status_code=404, detail="Unknown soul")
    return facade.get_work_log(normalized_soul_id, limit=limit)


@router.get("/soul/image-assets/config")
async def soul_image_asset_config() -> dict[str, Any]:
    runtime = require_runtime()
    return SoulImageAssetService(runtime.base_dir).config_summary()


@router.post("/soul/image-assets/generate")
async def generate_soul_image_asset(payload: SoulImageAssetGenerateRequest) -> dict[str, Any]:
    runtime = require_runtime()
    try:
        return await SoulImageAssetService(runtime.base_dir).generate(
            prompt=payload.prompt,
            target_id=payload.target_id,
            asset_kind=payload.asset_kind,
            size=payload.size,
            overwrite=payload.overwrite,
        )
    except SoulImageAssetError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/soul/modes/preview")
async def soul_mode_preview(payload: SoulModePreviewRequest) -> dict[str, Any]:
    runtime = require_runtime()
    facade = SoulFacade(runtime.base_dir)
    try:
        return facade.preview_mode(
            mode=payload.mode.strip(),
            soul_id=payload.soul_id.strip().lower(),
            projection_id=payload.projection_id.strip(),
            work_prompt_id=payload.work_prompt_id.strip(),
            task_contract=payload.task_contract,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/soul/projection-instances/preview")
async def soul_projection_instance_preview(payload: ProjectionInstancePreviewRequest) -> dict[str, Any]:
    runtime = require_runtime()
    try:
        return SoulFacade(runtime.base_dir).preview_instance(
            template_id=payload.template_id,
            task_id=payload.task_id,
            task_run_id=payload.task_run_id,
            agent_id=payload.agent_id,
            runtime_lane=payload.runtime_lane,
            resource_policy_ref=payload.resource_policy_ref,
            context_snapshot_ref=payload.context_snapshot_ref,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown projection template") from exc


@router.post("/soul/projections")
async def create_soul_projection_card(payload: SoulProjectionCardRequest) -> dict[str, Any]:
    runtime = require_runtime()
    facade = SoulFacade(runtime.base_dir)
    request_payload = payload.model_dump()
    try:
        return facade.upsert_projection_card(
            request=request_payload,
            select_after_create=payload.select_after_create,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown or disabled soul") from exc


@router.post("/soul/projections/{projection_id}/select")
async def select_soul_projection(projection_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    try:
        return SoulFacade(runtime.base_dir).select_projection_card(projection_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown projection card") from exc


@router.delete("/soul/projections/{projection_id}")
async def delete_soul_projection(projection_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    try:
        return SoulFacade(runtime.base_dir).delete_projection_card(projection_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown projection card") from exc


@router.post("/soul/custom")
async def create_custom_soul(payload: CustomSoulSaveRequest) -> dict[str, Any]:
    runtime = require_runtime()
    try:
        return SoulFacade(runtime.base_dir).create_or_update_custom_soul(
            soul_id=payload.soul_id,
            name=payload.name,
            description=payload.description,
            soul_markdown=payload.soul_markdown,
            preferred_role_types=list(payload.preferred_role_types),
            preferred_task_modes=list(payload.preferred_task_modes),
            enabled=payload.enabled,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/soul/custom/{soul_id}")
async def update_custom_soul(soul_id: str, payload: CustomSoulSaveRequest) -> dict[str, Any]:
    if payload.soul_id.strip().lower() != soul_id.strip().lower():
        raise HTTPException(status_code=400, detail="soul_id 不一致")
    return await create_custom_soul(payload)


@router.post("/soul/custom/{soul_id}/enable")
async def enable_custom_soul(soul_id: str) -> dict[str, Any]:
    return _set_custom_soul_enabled(soul_id, True)


@router.post("/soul/custom/{soul_id}/disable")
async def disable_custom_soul(soul_id: str) -> dict[str, Any]:
    return _set_custom_soul_enabled(soul_id, False)


@router.delete("/soul/custom/{soul_id}")
async def delete_custom_soul(soul_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    try:
        return SoulFacade(runtime.base_dir).registry_service.delete_custom_soul(soul_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown custom soul")


def _set_custom_soul_enabled(soul_id: str, enabled: bool) -> dict[str, Any]:
    runtime = require_runtime()
    try:
        return SoulFacade(runtime.base_dir).set_custom_soul_enabled(soul_id, enabled)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown custom soul")


@router.post("/soul/portraits/{key}")
async def upload_soul_portrait(key: str, file: UploadFile = File(...)) -> dict[str, Any]:
    runtime = require_runtime()
    normalized_key = key.strip().lower()
    if normalized_key not in SEED_PATHS:
        raise HTTPException(status_code=404, detail="Unknown soul seed")
    if file.content_type not in {"image/png", "application/octet-stream"}:
        raise HTTPException(status_code=400, detail="请上传 PNG 立绘")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="立绘文件为空")
    if len(content) > SOUL_PORTRAIT_MAX_BYTES:
        raise HTTPException(status_code=413, detail="立绘文件不能超过 8MB")
    if not content.startswith(b"\x89PNG\r\n\x1a\n"):
        raise HTTPException(status_code=400, detail="请上传有效的 PNG 立绘")

    portrait_path = _portrait_path(runtime.base_dir, normalized_key)
    portrait_path.parent.mkdir(parents=True, exist_ok=True)
    portrait_path.write_bytes(content)
    return build_soul_catalog(runtime.base_dir)


@router.get("/soul/{soul_id}")
async def soul_profile(soul_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    profile = SoulFacade(runtime.base_dir).get_profile(soul_id.strip().lower())
    if profile is None:
        raise HTTPException(status_code=404, detail="Unknown soul")
    return profile.to_dict()
