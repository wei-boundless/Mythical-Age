from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.deps import require_runtime
from capability_system.skills.authoring import set_skill_prompt_view
from capability_system.skills.paths import CapabilitySkillPaths
from capability_system import (
    TOOL_TYPE_OPTIONS,
    build_capability_catalog,
)
from core.config import runtime_config
from capability_system.supply import build_capability_supply_package, build_capability_supply_package_from_base_dir
from orchestration import (
    RuntimeApprovalContext,
    build_resource_policy_candidate,
    build_resource_runtime_views,
)
from permissions.operations import build_default_operation_registry
from task_system.contracts.capability_requirements import build_operation_requirement

router = APIRouter()

SKILL_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{1,63}$")


class CreateSkillRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=64)
    title: str = Field(..., min_length=1, max_length=80)
    description: str = Field(..., min_length=1, max_length=400)
    content: str | None = None


class SaveSkillRequest(BaseModel):
    content: str = Field(..., min_length=1)


class SkillPromptViewRequest(BaseModel):
    title: str = Field(default="", max_length=120)
    capability: str = Field(default="", max_length=800)
    use_when: str = Field(default="", max_length=1200)
    output_rule: str = Field(default="", max_length=1200)


class ToolMetadataRequest(BaseModel):
    tool_type: str = Field(default="通用能力", max_length=40)
    note: str = Field(default="", max_length=240)
    llm_description: str = Field(default="", max_length=1200)


class ApprovalContextRequest(BaseModel):
    interactive_ui_available: bool = True
    approval_hook_available: bool = False
    bubble_to_parent_allowed: bool = False
    headless_mode: bool = False


class ResourcePolicyCandidateRequest(BaseModel):
    task_id: str = Field(default="task-candidate")
    source: str = Field(default="task_binding_candidate")
    operation_scope: list[str] = Field(default_factory=list)
    denied_operations: list[str] = Field(default_factory=list)
    default_operation_requirements: list[str] = Field(default_factory=list)
    capability_operations: list[str] = Field(default_factory=list)
    approval_policy: str = Field(default="default")
    review_policy: str = Field(default="optional")
    reason: str = ""
    approval_context: ApprovalContextRequest = Field(default_factory=ApprovalContextRequest)


def _capability_config() -> dict[str, Any]:
    payload = runtime_config.load()
    config = payload.get("capability_system")
    if not isinstance(config, dict):
        config = {}
    overrides = config.get("tool_overrides")
    if not isinstance(overrides, dict):
        overrides = {}
    config["tool_overrides"] = {
        str(key): value
        for key, value in overrides.items()
        if isinstance(value, dict)
    }
    return config


def _save_capability_config(config: dict[str, Any]) -> None:
    payload = runtime_config.load()
    payload["capability_system"] = config
    runtime_config.save(payload)


def _safe_skill_name(name: str) -> str:
    normalized = str(name or "").strip()
    if not SKILL_NAME_PATTERN.fullmatch(normalized):
        raise HTTPException(status_code=400, detail="Skill name must be 2-64 letters, numbers, hyphens, or underscores")
    return normalized


def _skill_path(base_dir: Path, skill_name: str) -> Path:
    normalized = _safe_skill_name(skill_name)
    root = CapabilitySkillPaths.from_base_dir(base_dir).skills_dir.resolve()
    path = (root / normalized / "SKILL.md").resolve()
    if root not in path.parents:
        raise HTTPException(status_code=400, detail="Invalid skill path")
    return path


def _find_skill_path(runtime, skill_name: str) -> Path:
    target = _safe_skill_name(skill_name).lower()
    skill_paths = CapabilitySkillPaths.from_base_dir(runtime.base_dir)
    for skill in runtime.skill_registry.skills:
        if skill.runtime.name.lower() == target:
            return (skill_paths.base_dir / skill.runtime.path).resolve()
    fallback = _skill_path(runtime.base_dir, skill_name)
    if fallback.exists():
        return fallback
    raise HTTPException(status_code=404, detail="Skill not found")


def _default_skill_content(name: str, title: str, description: str) -> str:
    quoted_description = json.dumps(description, ensure_ascii=False)
    quoted_title = json.dumps(title, ensure_ascii=False)
    return f"""---
name: {name}
description: {quoted_description}
metadata:
  display_name: {quoted_title}
  supported_modalities:
    - text
  supported_task_kinds: []
  supported_source_kinds: []
  capability_tags: []
  preferred_route: capability_authoring
  requires_operations:
    - op.read_file
    - op.write_file
    - op.edit_file
  requires_capabilities:
    - tool:read_file
    - tool:write_file
    - tool:edit_file
  activation_policy: model_visible
  context_mode: inline
  route_authority: candidate_only
---

# {title}

{description}

## 适用场景

- 描述这个 skill 应该在什么用户任务下被激活。

## 执行准则

- 如果这个 skill 需要工具、MCP 或文件能力，先声明 `requires_operations` 和 `requires_capabilities`，不要假设权限会自动扩大。
- 直接完成用户任务，不暴露内部路由、工具协议或调度细节。
"""


def build_capability_catalog_payload() -> dict[str, Any]:
    runtime = require_runtime()
    config = _capability_config()
    catalog = build_capability_catalog(runtime, config["tool_overrides"])
    catalog["capability_supply_package"] = build_capability_supply_package(
        runtime,
        config["tool_overrides"],
    ).to_dict()
    return catalog


@router.get("/capability-system/catalog")
async def capability_catalog() -> dict[str, Any]:
    return build_capability_catalog_payload()


@router.post("/capability-system/resource-policy/candidate")
async def resource_policy_candidate(payload: ResourcePolicyCandidateRequest) -> dict[str, Any]:
    registry = build_default_operation_registry()
    requirement = build_operation_requirement(
        task_id=payload.task_id,
        source=payload.source,
        required_task_operations=payload.operation_scope,
        denied_operations=payload.denied_operations,
        default_operation_requirements=payload.default_operation_requirements,
        capability_operations=payload.capability_operations,
        approval_policy=payload.approval_policy,
        review_policy=payload.review_policy,
        reason=payload.reason,
    )
    policy = build_resource_policy_candidate(
        requirement,
        registry,
        approval_context=RuntimeApprovalContext(
            interactive_ui_available=payload.approval_context.interactive_ui_available,
            approval_hook_available=payload.approval_context.approval_hook_available,
            bubble_to_parent_allowed=payload.approval_context.bubble_to_parent_allowed,
            headless_mode=payload.approval_context.headless_mode,
        ),
    )
    views = build_resource_runtime_views(policy, registry)
    capability_supply_package = build_capability_supply_package_from_base_dir(
        Path(__file__).resolve().parents[1],
        task_id=payload.task_id,
        operation_scope=[*list(requirement.required_operations), *list(requirement.optional_operations)],
    )
    return {
        "operation_requirement": requirement.to_dict(),
        "capability_supply_package": capability_supply_package.to_dict(),
        "resource_policy": policy.to_dict(),
        "decisions": [decision.to_dict() for decision in policy.decisions],
        "resource_runtime_views": [view.to_dict() for view in views],
        "diagnostics": {
            **policy.diagnostics,
            "fail_closed": True,
        },
    }


@router.post("/capability-system/catalog/refresh")
async def refresh_capability_catalog() -> dict[str, Any]:
    runtime = require_runtime()
    runtime.refresh_catalogs()
    return build_capability_catalog_payload()


@router.post("/capability-system/skills")
async def create_capability_skill(payload: CreateSkillRequest) -> dict[str, Any]:
    runtime = require_runtime()
    name = _safe_skill_name(payload.name)
    path = _skill_path(runtime.base_dir, name)
    if path.exists():
        raise HTTPException(status_code=409, detail="Skill already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        payload.content or _default_skill_content(name, payload.title.strip(), payload.description.strip()),
        encoding="utf-8",
    )
    runtime.refresh_catalogs()
    return build_capability_catalog_payload()


@router.put("/capability-system/skills/{skill_name}")
async def save_capability_skill(skill_name: str, payload: SaveSkillRequest) -> dict[str, Any]:
    runtime = require_runtime()
    path = _find_skill_path(runtime, skill_name)
    root = CapabilitySkillPaths.from_base_dir(runtime.base_dir).skills_dir.resolve()
    if root not in path.parents or path.name != "SKILL.md":
        raise HTTPException(status_code=400, detail="Invalid skill path")
    path.write_text(payload.content, encoding="utf-8")
    runtime.refresh_catalogs()
    return build_capability_catalog_payload()


@router.put("/capability-system/skills/{skill_name}/prompt-view")
async def update_capability_skill_prompt_view(skill_name: str, payload: SkillPromptViewRequest) -> dict[str, Any]:
    runtime = require_runtime()
    path = _find_skill_path(runtime, skill_name)
    root = CapabilitySkillPaths.from_base_dir(runtime.base_dir).skills_dir.resolve()
    if root not in path.parents or path.name != "SKILL.md":
        raise HTTPException(status_code=400, detail="Invalid skill path")
    current_name = _safe_skill_name(skill_name)
    set_skill_prompt_view(
        path,
        {
            "name": current_name,
            "title": payload.title,
            "capability": payload.capability,
            "use_when": payload.use_when,
            "output_rule": payload.output_rule,
        },
    )
    runtime.refresh_catalogs()
    return build_capability_catalog_payload()


@router.delete("/capability-system/skills/{skill_name}")
async def delete_capability_skill(skill_name: str) -> dict[str, Any]:
    runtime = require_runtime()
    path = _find_skill_path(runtime, skill_name)
    root = CapabilitySkillPaths.from_base_dir(runtime.base_dir).skills_dir.resolve()
    skill_dir = path.parent.resolve()
    if root not in skill_dir.parents or skill_dir == root:
        raise HTTPException(status_code=400, detail="Invalid skill path")
    shutil.rmtree(skill_dir)
    runtime.refresh_catalogs()
    return build_capability_catalog_payload()


@router.put("/capability-system/tools/{tool_name}")
async def update_capability_tool(tool_name: str, payload: ToolMetadataRequest) -> dict[str, Any]:
    runtime = require_runtime()
    known_tools = {definition.name for definition in runtime.tool_runtime.definitions}
    if tool_name not in known_tools:
        raise HTTPException(status_code=404, detail="Tool not found")
    tool_type = payload.tool_type if payload.tool_type in TOOL_TYPE_OPTIONS else "通用能力"
    config = _capability_config()
    overrides = config["tool_overrides"]
    overrides[tool_name] = {
        "tool_type": tool_type,
        "note": payload.note.strip(),
        "llm_description": payload.llm_description.strip(),
    }
    _save_capability_config(config)
    return build_capability_catalog_payload()



