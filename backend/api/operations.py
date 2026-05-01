from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.deps import require_runtime
from capabilities import TOOL_TYPE_OPTIONS
from capabilities import build_operation_catalog as build_capability_operation_catalog
from capabilities import set_skill_allowed_tools, set_skill_prompt_view
from config import runtime_config
from skill_system import SkillWorkflowRegistry
from operations import (
    AgentRegistry,
    RuntimeApprovalContext,
    build_default_operation_registry,
    build_operation_requirement,
    build_resource_policy_candidate,
    build_resource_runtime_views,
)

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


class SkillToolBindingRequest(BaseModel):
    allowed_tools: list[str] = Field(default_factory=list)


class ToolMetadataRequest(BaseModel):
    tool_type: str = Field(default="通用能力", max_length=40)
    note: str = Field(default="", max_length=240)


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
    skill_required_operations: list[str] = Field(default_factory=list)
    approval_policy: str = Field(default="default")
    review_policy: str = Field(default="optional")
    reason: str = ""
    approval_context: ApprovalContextRequest = Field(default_factory=ApprovalContextRequest)


class AgentEnabledRequest(BaseModel):
    enabled: bool = True


def _operation_config() -> dict[str, Any]:
    payload = runtime_config.load()
    config = payload.get("operation_system")
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


def _save_operation_config(config: dict[str, Any]) -> None:
    payload = runtime_config.load()
    payload["operation_system"] = config
    runtime_config.save(payload)


def _safe_skill_name(name: str) -> str:
    normalized = str(name or "").strip()
    if not SKILL_NAME_PATTERN.fullmatch(normalized):
        raise HTTPException(status_code=400, detail="Skill name must be 2-64 letters, numbers, hyphens, or underscores")
    return normalized


def _skill_path(base_dir: Path, skill_name: str) -> Path:
    normalized = _safe_skill_name(skill_name)
    root = (base_dir / "skills").resolve()
    path = (root / normalized / "SKILL.md").resolve()
    if root not in path.parents:
        raise HTTPException(status_code=400, detail="Invalid skill path")
    return path


def _find_skill_path(runtime, skill_name: str) -> Path:
    target = _safe_skill_name(skill_name).lower()
    for skill in runtime.skill_registry.skills:
        if skill.runtime.name.lower() == target:
            return (runtime.base_dir / skill.runtime.path).resolve()
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
  allowed_tools: []
  supported_modalities:
    - text
  supported_task_kinds: []
  supported_source_kinds: []
  capability_tags: []
  preferred_route: rag
  activation_policy: model_visible
  context_mode: inline
  route_authority: candidate_only
---

# {title}

{description}

## 适用场景

- 描述这个 skill 应该在什么用户任务下被激活。

## 执行准则

- 直接完成用户任务，不暴露内部路由、工具协议或调度细节。
"""


def build_operation_catalog() -> dict[str, Any]:
    runtime = require_runtime()
    config = _operation_config()
    return build_capability_operation_catalog(runtime, config["tool_overrides"])


@router.get("/operations/catalog")
async def operation_catalog() -> dict[str, Any]:
    return build_operation_catalog()


@router.get("/skills/workflows")
async def skill_workflows() -> dict[str, Any]:
    runtime = require_runtime()
    return SkillWorkflowRegistry(runtime.base_dir).build_catalog()


@router.get("/skills/workflows/{workflow_id}")
async def skill_workflow_detail(workflow_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    workflow = SkillWorkflowRegistry(runtime.base_dir).get_workflow(workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Unknown skill workflow")
    return workflow.to_dict()


@router.get("/operations/agents")
async def operation_agents() -> dict[str, Any]:
    runtime = require_runtime()
    return AgentRegistry(runtime.base_dir).build_catalog()


@router.get("/operations/agents/{agent_id}")
async def operation_agent_detail(agent_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    registry = AgentRegistry(runtime.base_dir)
    agent = registry.get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Unknown agent")
    return {
        "agent": agent.to_dict(),
        "capability_profile": (registry.get_capability_profile(agent_id).to_dict() if registry.get_capability_profile(agent_id) else {}),
    }


@router.get("/operations/agents/{agent_id}/capability-profile")
async def operation_agent_capability(agent_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    profile = AgentRegistry(runtime.base_dir).get_capability_profile(agent_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Unknown agent capability profile")
    return profile.to_dict()


@router.put("/operations/agents/{agent_id}/enabled")
async def update_operation_agent_enabled(agent_id: str, payload: AgentEnabledRequest) -> dict[str, Any]:
    runtime = require_runtime()
    registry = AgentRegistry(runtime.base_dir)
    try:
        registry.set_agent_enabled(agent_id, payload.enabled)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown agent") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return registry.build_catalog()


@router.post("/operations/resource-policy/candidate")
async def resource_policy_candidate(payload: ResourcePolicyCandidateRequest) -> dict[str, Any]:
    registry = build_default_operation_registry()
    requirement = build_operation_requirement(
        task_id=payload.task_id,
        source=payload.source,
        operation_scope=payload.operation_scope,
        denied_operations=payload.denied_operations,
        default_operation_requirements=payload.default_operation_requirements,
        skill_required_operations=payload.skill_required_operations,
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
    return {
        "operation_requirement": requirement.to_dict(),
        "resource_policy": policy.to_dict(),
        "decisions": [decision.to_dict() for decision in policy.decisions],
        "resource_runtime_views": [view.to_dict() for view in views],
        "diagnostics": {
            **policy.diagnostics,
            "fail_closed": True,
        },
    }


@router.post("/operations/catalog/refresh")
async def refresh_operation_catalog() -> dict[str, Any]:
    runtime = require_runtime()
    runtime.refresh_catalogs()
    return build_operation_catalog()


@router.post("/operations/skills")
async def create_operation_skill(payload: CreateSkillRequest) -> dict[str, Any]:
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
    return build_operation_catalog()


@router.put("/operations/skills/{skill_name}")
async def save_operation_skill(skill_name: str, payload: SaveSkillRequest) -> dict[str, Any]:
    runtime = require_runtime()
    path = _find_skill_path(runtime, skill_name)
    root = (runtime.base_dir / "skills").resolve()
    if root not in path.parents or path.name != "SKILL.md":
        raise HTTPException(status_code=400, detail="Invalid skill path")
    path.write_text(payload.content, encoding="utf-8")
    runtime.refresh_catalogs()
    return build_operation_catalog()


@router.put("/operations/skills/{skill_name}/prompt-view")
async def update_operation_skill_prompt_view(skill_name: str, payload: SkillPromptViewRequest) -> dict[str, Any]:
    runtime = require_runtime()
    path = _find_skill_path(runtime, skill_name)
    root = (runtime.base_dir / "skills").resolve()
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
    return build_operation_catalog()


@router.delete("/operations/skills/{skill_name}")
async def delete_operation_skill(skill_name: str) -> dict[str, Any]:
    runtime = require_runtime()
    path = _find_skill_path(runtime, skill_name)
    root = (runtime.base_dir / "skills").resolve()
    skill_dir = path.parent.resolve()
    if root not in skill_dir.parents or skill_dir == root:
        raise HTTPException(status_code=400, detail="Invalid skill path")
    shutil.rmtree(skill_dir)
    runtime.refresh_catalogs()
    return build_operation_catalog()


@router.put("/operations/skills/{skill_name}/tools")
async def update_operation_skill_tools(skill_name: str, payload: SkillToolBindingRequest) -> dict[str, Any]:
    runtime = require_runtime()
    path = _find_skill_path(runtime, skill_name)
    root = (runtime.base_dir / "skills").resolve()
    if root not in path.parents or path.name != "SKILL.md":
        raise HTTPException(status_code=400, detail="Invalid skill path")
    known_tools = {definition.name for definition in runtime.tool_runtime.definitions}
    set_skill_allowed_tools(path, payload.allowed_tools, known_tools)
    runtime.refresh_catalogs()
    return build_operation_catalog()


@router.put("/operations/tools/{tool_name}")
async def update_operation_tool(tool_name: str, payload: ToolMetadataRequest) -> dict[str, Any]:
    runtime = require_runtime()
    known_tools = {definition.name for definition in runtime.tool_runtime.definitions}
    if tool_name not in known_tools:
        raise HTTPException(status_code=404, detail="Tool not found")
    tool_type = payload.tool_type if payload.tool_type in TOOL_TYPE_OPTIONS else "通用能力"
    config = _operation_config()
    overrides = config["tool_overrides"]
    overrides[tool_name] = {
        "tool_type": tool_type,
        "note": payload.note.strip(),
    }
    _save_operation_config(config)
    return build_operation_catalog()
