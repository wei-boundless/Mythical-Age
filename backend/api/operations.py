from __future__ import annotations

import json
import re
import shutil
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.deps import require_runtime
from config import runtime_config

router = APIRouter()

SKILL_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{1,63}$")

TOOL_TYPE_OPTIONS = [
    "实时查询",
    "本地文件",
    "文档数据",
    "知识检索",
    "系统执行",
    "多模态处理",
    "通用能力",
]

TOOL_RISK_ORDER = {
    "低": 0,
    "中": 1,
    "高": 2,
    "极高": 3,
}


class CreateSkillRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=64)
    title: str = Field(..., min_length=1, max_length=80)
    description: str = Field(..., min_length=1, max_length=400)
    content: str | None = None


class SaveSkillRequest(BaseModel):
    content: str = Field(..., min_length=1)


class ToolMetadataRequest(BaseModel):
    tool_type: str = Field(default="通用能力", max_length=40)
    note: str = Field(default="", max_length=240)


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


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _default_tool_type(tool: dict[str, Any]) -> str:
    tags = {str(item).lower() for item in list(tool.get("capability_tags") or []) + list(tool.get("supported_modalities") or [])}
    safety = {str(item).lower() for item in list(tool.get("safety_tags") or [])}
    name = str(tool.get("name") or "").lower()
    if tags & {"realtime", "web", "finance", "weather"}:
        return "实时查询"
    if tags & {"pdf", "document", "table", "spreadsheet", "csv", "json", "dataset"}:
        return "文档数据"
    if tags & {"rag", "retrieval", "knowledge", "local-knowledge"}:
        return "知识检索"
    if tags & {"file", "workspace", "code"}:
        return "本地文件"
    if safety & {"shell", "destructive"} or name in {"terminal", "python_repl"}:
        return "系统执行"
    if tags & {"multimodal", "image", "preview", "indexing"}:
        return "多模态处理"
    return "通用能力"


def _tool_text_set(tool: dict[str, Any], *fields: str) -> set[str]:
    values: set[str] = set()
    for field_name in fields:
        raw = tool.get(field_name)
        if isinstance(raw, list):
            values.update(str(item).lower() for item in raw if str(item).strip())
        elif raw:
            values.add(str(raw).lower())
    return values


def _tool_boundary(tool: dict[str, Any]) -> str:
    tags = _tool_text_set(tool, "capability_tags", "supported_modalities", "safety_tags", "route_hints")
    name = str(tool.get("name") or "").lower()
    resource_policy = str(tool.get("resource_exposure_policy") or "")
    runtime_visibility = str(tool.get("runtime_visibility") or "")
    if "shell" in tags or name in {"terminal", "python_repl"}:
        return "系统执行"
    if "network" in tags or tags & {"web", "realtime", "finance", "weather"}:
        return "外部服务"
    if resource_policy == "explicit_resource" or tags & {"file", "workspace", "local", "code"}:
        return "本地资源"
    if tags & {"rag", "retrieval", "knowledge", "local-knowledge"}:
        return "知识检索"
    if runtime_visibility == "agent_internal":
        return "智能体内部"
    return "主运行时能力"


def _tool_adapter_type(tool: dict[str, Any]) -> str:
    tags = _tool_text_set(tool, "capability_tags", "supported_modalities", "safety_tags", "route_hints")
    name = str(tool.get("name") or "").lower()
    if name == "terminal":
        return "本地命令"
    if name == "python_repl":
        return "本地脚本"
    if tags & {"web", "network", "realtime", "finance", "weather"}:
        return "网络 API"
    if tags & {"rag", "retrieval", "knowledge", "local-knowledge"}:
        return "检索引擎"
    if tags & {"pdf", "document", "file", "workspace", "code"}:
        return "文件适配器"
    if tags & {"table", "spreadsheet", "csv", "json", "dataset", "analytics"}:
        return "数据分析器"
    if tags & {"multimodal", "image", "preview", "indexing"}:
        return "多模态处理器"
    return "本地 Python"


def _tool_risk_level(tool: dict[str, Any]) -> str:
    tags = _tool_text_set(tool, "capability_tags", "supported_modalities", "safety_tags", "route_hints")
    if tool.get("is_destructive") or "destructive" in tags:
        return "极高"
    if "shell" in tags or not bool(tool.get("is_read_only", True)):
        return "高"
    if "network" in tags or str(tool.get("resource_exposure_policy") or "") in {"handle_only", "explicit_resource"}:
        return "中"
    return "低"


def _tool_visibility_label(tool: dict[str, Any]) -> str:
    if str(tool.get("runtime_visibility") or "") == "agent_internal":
        return "智能体内部可用"
    prompt_policy = str(tool.get("prompt_exposure_policy") or "")
    if prompt_policy == "hidden":
        return "对模型隐藏"
    if prompt_policy == "debug_only":
        return "仅调试可见"
    return "模型可见结构"


def _tool_runtime_policy(tool: dict[str, Any]) -> str:
    if tool.get("safe_for_auto_route"):
        return "可参与自动路由"
    return "需要显式触发"


def _tool_bound_skills(skills: list[dict[str, Any]], tool_name: str) -> list[dict[str, str]]:
    bindings = []
    for skill in skills:
        runtime = skill.get("runtime") if isinstance(skill.get("runtime"), dict) else {}
        allowed_tools = runtime.get("allowed_tools") if isinstance(runtime, dict) else []
        if not isinstance(allowed_tools, list) or tool_name not in allowed_tools:
            continue
        bindings.append(
            {
                "name": str(runtime.get("name") or ""),
                "title": str(runtime.get("title") or runtime.get("name") or ""),
                "activation_policy": str(runtime.get("activation_policy") or ""),
                "context_mode": str(runtime.get("context_mode") or ""),
            }
        )
    return bindings


def _tool_governance_hints(tool: dict[str, Any]) -> list[str]:
    hints = [_tool_runtime_policy(tool), _tool_visibility_label(tool)]
    risk = _tool_risk_level(tool)
    boundary = _tool_boundary(tool)
    if risk in {"高", "极高"}:
        hints.append("建议保持人工确认")
    if boundary in {"本地资源", "系统执行"}:
        hints.append("需要关注路径、权限与副作用")
    if str(tool.get("resource_exposure_policy") or "") == "handle_only":
        hints.append("只传递资源句柄，避免把原始文件暴露给模型")
    if not tool.get("is_concurrency_safe"):
        hints.append("不建议并发调用")
    return hints


def _operation_tool_metadata(tool: dict[str, Any], metadata: dict[str, Any], skills: list[dict[str, Any]]) -> dict[str, Any]:
    tool_type = str(metadata.get("tool_type") or "").strip() or _default_tool_type(tool)
    if tool_type not in TOOL_TYPE_OPTIONS:
        tool_type = "通用能力"
    return {
        "tool_type": tool_type,
        "note": str(metadata.get("note") or ""),
        "tool_boundary": _tool_boundary(tool),
        "adapter_type": _tool_adapter_type(tool),
        "risk_level": _tool_risk_level(tool),
        "risk_rank": TOOL_RISK_ORDER.get(_tool_risk_level(tool), 0),
        "visibility_label": _tool_visibility_label(tool),
        "runtime_policy": _tool_runtime_policy(tool),
        "editable_policy": "前端可编辑类型与备注；工具注册、执行契约和安全边界由后端代码控制。",
        "bound_skills": _tool_bound_skills(skills, str(tool.get("name") or "")),
        "governance_hints": _tool_governance_hints(tool),
    }


def _skill_payload(runtime, skill) -> dict[str, Any]:
    path = runtime.base_dir / skill.runtime.path
    content = _read_text(path) if path.exists() else ""
    return {
        "runtime": asdict(skill.runtime),
        "prompt_view": skill.prompt_view.to_dict() if hasattr(skill.prompt_view, "to_dict") else {
            "name": skill.prompt_view.name,
            "title": skill.prompt_view.title,
            "capability": skill.prompt_view.capability,
            "use_when": skill.prompt_view.use_when,
            "output_rule": skill.prompt_view.output_rule,
        },
        "prompt_block": skill.render_prompt_block(),
        "content": content,
        "validation_errors": list(getattr(skill, "validation_errors", []) or []),
    }


def build_operation_catalog() -> dict[str, Any]:
    runtime = require_runtime()
    config = _operation_config()
    overrides = config["tool_overrides"]
    skills = [_skill_payload(runtime, skill) for skill in runtime.skill_registry.skills]
    tools = []
    for definition in runtime.tool_runtime.definitions:
        record = definition.to_registry_record()
        metadata = dict(overrides.get(definition.name) or {})
        tools.append(
            {
                **record,
                "operation_metadata": _operation_tool_metadata(record, metadata, skills),
            }
        )
    risk_counts: dict[str, int] = {}
    boundary_counts: dict[str, int] = {}
    for tool in tools:
        operation_metadata = tool["operation_metadata"]
        risk_counts[operation_metadata["risk_level"]] = risk_counts.get(operation_metadata["risk_level"], 0) + 1
        boundary_counts[operation_metadata["tool_boundary"]] = boundary_counts.get(operation_metadata["tool_boundary"], 0) + 1
    return {
        "skills": skills,
        "tools": tools,
        "tool_type_options": TOOL_TYPE_OPTIONS,
        "summary": {
            "skill_count": len(skills),
            "tool_count": len(tools),
            "model_visible_skills": sum(1 for item in skills if item["runtime"].get("activation_policy") == "model_visible"),
            "tool_types": sorted({tool["operation_metadata"]["tool_type"] for tool in tools}),
            "tool_boundaries": dict(sorted(boundary_counts.items())),
            "tool_risks": dict(sorted(risk_counts.items(), key=lambda item: TOOL_RISK_ORDER.get(item[0], 0))),
        },
    }


def _default_skill_content(name: str, title: str, description: str) -> str:
    quoted_description = json_string(description)
    quoted_title = json_string(title)
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


def json_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


@router.get("/operations/catalog")
async def operation_catalog() -> dict[str, Any]:
    return build_operation_catalog()


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
