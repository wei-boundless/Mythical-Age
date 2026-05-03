from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from api.deps import require_runtime
from soul.projection_store import delete_projection_card, list_projection_cards, reconcile_projection_store, select_projection_card, upsert_projection_card
from soul.projection_instances import ProjectionInstanceRegistry
from soul.projection_templates import ProjectionTemplateRegistry
from soul.registry import (
    ACTIVE_SEED_PATH,
    BUILTIN_SEED_PATHS,
    BUILTIN_SOUL_NAMES,
    CORE_PATH,
    SEED_CATALOG_PATH,
    SoulRegistry,
    normalize_path,
    read_text,
    write_text,
)

router = APIRouter()

SOUL_PORTRAIT_MAX_BYTES = 8 * 1024 * 1024
SEED_PATHS = BUILTIN_SEED_PATHS
SOUL_NAMES = BUILTIN_SOUL_NAMES
EDITABLE_SOUL_PATHS = {
    ACTIVE_SEED_PATH,
    CORE_PATH,
    SEED_CATALOG_PATH,
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
    agent_id: str = Field(default="agent:health:maintainer")
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
    registry = SoulRegistry(base_dir)
    try:
        return registry.resolve_editable_path(path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def build_soul_catalog(base_dir: Path) -> dict[str, Any]:
    return SoulRegistry(base_dir).build_catalog()


def _projection_profiles(registry: SoulRegistry) -> list[dict[str, Any]]:
    return [profile.to_dict() for profile in registry.profiles().values()]


@router.get("/soul/catalog")
async def soul_catalog() -> dict[str, Any]:
    runtime = require_runtime()
    return build_soul_catalog(runtime.base_dir)


@router.post("/soul/switch")
async def switch_soul(payload: SoulSwitchRequest) -> dict[str, Any]:
    runtime = require_runtime()
    key = payload.key.strip().lower()
    registry = SoulRegistry(runtime.base_dir)
    try:
        registry.switch(key)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown soul seed") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Soul seed is empty or missing") from exc
    runtime.refresh_indexes_for_path(ACTIVE_SEED_PATH)
    return registry.build_catalog()


@router.put("/soul/files")
async def save_soul_file(payload: SoulFileSaveRequest) -> dict[str, Any]:
    runtime = require_runtime()
    normalized = normalize_path(payload.path)
    file_path = _resolve_soul_path(runtime.base_dir, normalized)
    write_text(file_path, payload.content)
    runtime.refresh_indexes_for_path(normalized)
    return build_soul_catalog(runtime.base_dir)


@router.get("/soul/projections")
async def soul_projection_cards() -> dict[str, Any]:
    runtime = require_runtime()
    registry = SoulRegistry(runtime.base_dir)
    return list_projection_cards(
        runtime.base_dir,
        soul_profiles=_projection_profiles(registry),
        active_soul_id=registry.active_soul_id(),
    )


@router.get("/soul/projection-templates")
async def soul_projection_templates() -> dict[str, Any]:
    runtime = require_runtime()
    return ProjectionTemplateRegistry(runtime.base_dir).build_catalog()


@router.get("/soul/projection-templates/{template_id}")
async def soul_projection_template_detail(template_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    template = ProjectionTemplateRegistry(runtime.base_dir).get_template(template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Unknown projection template")
    return template.to_dict()


@router.post("/soul/projection-instances/preview")
async def soul_projection_instance_preview(payload: ProjectionInstancePreviewRequest) -> dict[str, Any]:
    runtime = require_runtime()
    try:
        instance = ProjectionInstanceRegistry(runtime.base_dir).preview_instance(
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
    return instance.to_dict()


@router.post("/soul/projections")
async def create_soul_projection_card(payload: SoulProjectionCardRequest) -> dict[str, Any]:
    runtime = require_runtime()
    registry = SoulRegistry(runtime.base_dir)
    profile = registry.get_profile(payload.soul_id.strip().lower())
    if profile is None or not profile.enabled:
        raise HTTPException(status_code=404, detail="Unknown or disabled soul")
    request_payload = payload.model_dump()
    request_payload["soul_id"] = request_payload["soul_id"].strip().lower()
    request_payload["projection_id"] = request_payload.get("projection_id", "").strip()
    store = upsert_projection_card(
        runtime.base_dir,
        request=request_payload,
        soul_name=profile.display_name,
        selected=payload.select_after_create,
    )
    return reconcile_projection_store(
        runtime.base_dir,
        store=store,
        soul_profiles=_projection_profiles(registry),
        active_soul_id=registry.active_soul_id(),
        persist=True,
    )


@router.post("/soul/projections/{projection_id}/select")
async def select_soul_projection(projection_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    registry = SoulRegistry(runtime.base_dir)
    try:
        store = select_projection_card(runtime.base_dir, projection_id)
        return reconcile_projection_store(
            runtime.base_dir,
            store=store,
            soul_profiles=_projection_profiles(registry),
            active_soul_id=registry.active_soul_id(),
            persist=True,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown projection card") from exc


@router.delete("/soul/projections/{projection_id}")
async def delete_soul_projection(projection_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    registry = SoulRegistry(runtime.base_dir)
    try:
        store = delete_projection_card(runtime.base_dir, projection_id)
        return reconcile_projection_store(
            runtime.base_dir,
            store=store,
            soul_profiles=_projection_profiles(registry),
            active_soul_id=registry.active_soul_id(),
            persist=True,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown projection card") from exc


@router.post("/soul/custom")
async def create_custom_soul(payload: CustomSoulSaveRequest) -> dict[str, Any]:
    runtime = require_runtime()
    soul_id = payload.soul_id.strip().lower()
    if soul_id in SEED_PATHS:
        raise HTTPException(status_code=400, detail="自制灵魂不能覆盖内置灵魂")
    soul_dir = (runtime.base_dir / "soul" / "custom" / soul_id).resolve()
    custom_root = (runtime.base_dir / "soul" / "custom").resolve()
    if custom_root not in soul_dir.parents:
        raise HTTPException(status_code=400, detail="Invalid custom soul path")
    profile = {
        "soul_id": soul_id,
        "name": payload.name,
        "source": "user",
        "description": payload.description,
        "preferred_role_types": payload.preferred_role_types,
        "preferred_task_modes": payload.preferred_task_modes,
        "enabled": payload.enabled,
    }
    write_text(soul_dir / "SOUL.md", payload.soul_markdown)
    write_text(soul_dir / "profile.json", json.dumps(profile, ensure_ascii=False, indent=2))
    return build_soul_catalog(runtime.base_dir)


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


def _set_custom_soul_enabled(soul_id: str, enabled: bool) -> dict[str, Any]:
    runtime = require_runtime()
    normalized = soul_id.strip().lower()
    profile_path = runtime.base_dir / "soul" / "custom" / normalized / "profile.json"
    if not profile_path.exists():
        raise HTTPException(status_code=404, detail="Unknown custom soul")
    raw = json.loads(read_text(profile_path) or "{}")
    raw["enabled"] = enabled
    write_text(profile_path, json.dumps(raw, ensure_ascii=False, indent=2))
    return build_soul_catalog(runtime.base_dir)


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
    profile = SoulRegistry(runtime.base_dir).get_profile(soul_id.strip().lower())
    if profile is None:
        raise HTTPException(status_code=404, detail="Unknown soul")
    return profile.to_dict()
