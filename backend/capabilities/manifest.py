from __future__ import annotations

import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

import yaml

from agents.a2a_cards import A2A_COMPATIBLE_PROTOCOL_VERSION, build_default_agent_cards
from .models import AgentCapability, CapabilityBindingEdge, CapabilityBindingGraph
from .search_policy import classify_tool_source, search_policy_labels, tool_text_set
from .validation import validate_capability_catalog


FRONTMATTER_PATTERN = re.compile(r"^---\n(.*?)\n---\n?", re.DOTALL)
MAIN_AGENT_ID = "agent:main:conversation"

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


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    match = FRONTMATTER_PATTERN.match(text)
    if not match:
        return {}, text
    data = yaml.safe_load(match.group(1)) or {}
    meta = data if isinstance(data, dict) else {}
    return meta, text[match.end() :]


def write_skill_frontmatter(path: Path, meta: dict[str, Any], body: str) -> None:
    frontmatter = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False).strip()
    path.write_text(f"---\n{frontmatter}\n---\n\n{body.lstrip()}", encoding="utf-8")


def normalize_tool_names(tool_names: list[str], known_tools: set[str]) -> list[str]:
    normalized: list[str] = []
    seen = set()
    for value in tool_names:
        name = str(value or "").strip()
        if not name or name in seen or name not in known_tools:
            continue
        seen.add(name)
        normalized.append(name)
    return normalized


def set_skill_allowed_tools(path: Path, allowed_tools: list[str], known_tools: set[str]) -> list[str]:
    text = read_text(path)
    meta, body = parse_frontmatter(text)
    metadata = meta.get("metadata") if isinstance(meta.get("metadata"), dict) else {}
    metadata["allowed_tools"] = normalize_tool_names(allowed_tools, known_tools)
    meta["metadata"] = metadata
    write_skill_frontmatter(path, meta, body)
    return list(metadata["allowed_tools"])


def default_tool_type(tool: dict[str, Any]) -> str:
    tags = tool_text_set(tool, "capability_tags", "supported_modalities")
    safety = tool_text_set(tool, "safety_tags")
    name = str(tool.get("name") or "").lower()
    source_class = classify_tool_source(tool)
    if source_class == "web":
        return "实时查询"
    if source_class in {"document", "data"} or tags & {"pdf", "document", "table", "spreadsheet", "csv", "json", "dataset"}:
        return "文档数据"
    if source_class == "rag":
        return "知识检索"
    if source_class == "local_files":
        return "本地文件"
    if source_class == "system_execution" or safety & {"shell", "destructive"} or name in {"terminal", "python_repl"}:
        return "系统执行"
    if tags & {"multimodal", "image", "preview", "indexing"}:
        return "多模态处理"
    return "通用能力"


def tool_boundary(tool: dict[str, Any]) -> str:
    source_class = classify_tool_source(tool)
    runtime_visibility = str(tool.get("runtime_visibility") or "")
    if source_class == "system_execution":
        return "系统执行"
    if source_class == "web":
        return "外部服务"
    if source_class == "local_files":
        return "本地资源"
    if source_class == "rag":
        return "知识检索"
    if source_class == "document":
        return "文档处理"
    if source_class == "data":
        return "数据分析"
    if runtime_visibility == "agent_internal":
        return "智能体内部"
    return "主运行时能力"


def tool_adapter_type(tool: dict[str, Any]) -> str:
    source_class = classify_tool_source(tool)
    name = str(tool.get("name") or "").lower()
    if name == "terminal":
        return "本地命令"
    if name == "python_repl":
        return "本地脚本"
    if source_class == "web":
        return "网络 API"
    if source_class == "rag":
        return "检索引擎"
    if source_class == "document":
        return "文档适配器"
    if source_class == "data":
        return "数据分析器"
    if source_class == "local_files":
        return "文件适配器"
    return "本地 Python"


def tool_risk_level(tool: dict[str, Any]) -> str:
    tags = tool_text_set(tool, "capability_tags", "supported_modalities", "safety_tags", "route_hints")
    if tool.get("is_destructive") or "destructive" in tags:
        return "极高"
    if "shell" in tags or not bool(tool.get("is_read_only", True)):
        return "高"
    if "network" in tags or str(tool.get("resource_exposure_policy") or "") in {"handle_only", "explicit_resource"}:
        return "中"
    return "低"


def tool_visibility_label(tool: dict[str, Any]) -> str:
    if str(tool.get("runtime_visibility") or "") == "agent_internal":
        return "智能体内部可用"
    prompt_policy = str(tool.get("prompt_exposure_policy") or "")
    if prompt_policy == "hidden":
        return "对模型隐藏"
    if prompt_policy == "debug_only":
        return "仅调试可见"
    return "模型可见结构"


def tool_runtime_policy(tool: dict[str, Any]) -> str:
    if tool.get("safe_for_auto_route"):
        return "可参与自动路由"
    return "需要显式触发"


def tool_bound_skills(skills: list[dict[str, Any]], tool_name: str) -> list[dict[str, str]]:
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


def agent_tool_bindings(tools: list[dict[str, Any]]) -> dict[str, list[str]]:
    bindings: dict[str, list[str]] = {MAIN_AGENT_ID: []}
    known_tool_names = {str(tool.get("name") or "") for tool in tools}
    for tool in tools:
        if str(tool.get("runtime_visibility") or "") == "main_runtime":
            bindings[MAIN_AGENT_ID].append(str(tool.get("name") or ""))
    for agent in build_default_agent_cards().values():
        tool_names = []
        for item in list(agent.mcp_profile.get("tools") or []):
            if not isinstance(item, dict):
                continue
            tool_name = str(item.get("tool_name") or item.get("name") or "").strip()
            if tool_name in known_tool_names:
                tool_names.append(tool_name)
        bindings[agent.agent_id] = sorted(set(tool_names))
    return {agent_id: sorted(set(names)) for agent_id, names in bindings.items()}


def agent_binding_nodes(agent_bindings: dict[str, list[str]]) -> list[AgentCapability]:
    cards = build_default_agent_cards()
    nodes = [
        AgentCapability(
            agent_id=MAIN_AGENT_ID,
            name="主会话智能体",
            kind="main",
            description="负责理解用户意图、选择路由、收束结果；只保留主运行时可见工具。",
            bound_tools=list(agent_bindings.get(MAIN_AGENT_ID, [])),
            protocol_version=A2A_COMPATIBLE_PROTOCOL_VERSION,
        )
    ]
    for card in cards.values():
        nodes.append(
            AgentCapability(
                agent_id=card.agent_id,
                name=card.name,
                kind=str(card.extensions.get("x-langchain-agent.worker_route") or "sub_agent"),
                description=card.description,
                bound_tools=list(agent_bindings.get(card.agent_id, [])),
                protocol_version=card.protocol_version,
            )
        )
    return nodes


def tool_agent_bindings(agent_bindings: dict[str, list[str]]) -> dict[str, list[dict[str, str]]]:
    agent_names = {node.agent_id: node.name for node in agent_binding_nodes(agent_bindings)}
    bindings: dict[str, list[dict[str, str]]] = {}
    for agent_id, tool_names in agent_bindings.items():
        for tool_name in tool_names:
            bindings.setdefault(tool_name, []).append(
                {
                    "agent_id": agent_id,
                    "name": agent_names.get(agent_id, agent_id),
                }
            )
    return bindings


def tool_governance_hints(tool: dict[str, Any]) -> list[str]:
    hints = [tool_runtime_policy(tool), tool_visibility_label(tool)]
    risk = tool_risk_level(tool)
    boundary = tool_boundary(tool)
    if risk in {"高", "极高"}:
        hints.append("建议保持人工确认")
    if boundary in {"本地资源", "系统执行"}:
        hints.append("需要关注路径、权限与副作用")
    if str(tool.get("resource_exposure_policy") or "") == "handle_only":
        hints.append("只传递资源句柄，避免把原始文件暴露给模型")
    if not tool.get("is_concurrency_safe"):
        hints.append("不建议并发调用")
    return hints


def operation_tool_metadata(
    tool: dict[str, Any],
    metadata: dict[str, Any],
    skills: list[dict[str, Any]],
    bound_agents_by_tool: dict[str, list[dict[str, str]]] | None = None,
) -> dict[str, Any]:
    tool_type = str(metadata.get("tool_type") or "").strip() or default_tool_type(tool)
    if tool_type not in TOOL_TYPE_OPTIONS:
        tool_type = "通用能力"
    tool_name = str(tool.get("name") or "")
    bound_agents = list((bound_agents_by_tool or {}).get(tool_name, []))
    source_class = classify_tool_source(tool)
    return {
        "tool_type": tool_type,
        "note": str(metadata.get("note") or ""),
        "source_class": source_class,
        "search_policy": search_policy_labels(source_class),
        "tool_boundary": tool_boundary(tool),
        "adapter_type": tool_adapter_type(tool),
        "risk_level": tool_risk_level(tool),
        "risk_rank": TOOL_RISK_ORDER.get(tool_risk_level(tool), 0),
        "visibility_label": tool_visibility_label(tool),
        "runtime_policy": tool_runtime_policy(tool),
        "editable_policy": "前端可编辑类型与备注；工具注册、执行契约和安全边界由后端代码控制。",
        "bound_skills": tool_bound_skills(skills, tool_name),
        "bound_agents": bound_agents,
        "ownership_label": " / ".join(item["name"] for item in bound_agents) if bound_agents else "尚未绑定智能体",
        "governance_hints": tool_governance_hints(tool),
    }


def skill_payload(runtime, skill) -> dict[str, Any]:
    path = runtime.base_dir / skill.runtime.path
    content = read_text(path) if path.exists() else ""
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


def build_binding_graph(
    skills: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    bindings_by_agent: dict[str, list[str]],
) -> CapabilityBindingGraph:
    tool_lookup = {str(tool.get("name") or ""): tool for tool in tools}
    skill_edges: list[CapabilityBindingEdge] = []
    for skill in skills:
        runtime = skill.get("runtime") if isinstance(skill.get("runtime"), dict) else {}
        for tool_name in list(runtime.get("allowed_tools") or []):
            if tool_name not in tool_lookup:
                continue
            skill_edges.append(
                CapabilityBindingEdge(
                    from_id=str(runtime.get("name") or ""),
                    from_label=str(runtime.get("title") or runtime.get("name") or ""),
                    to_id=tool_name,
                    to_label=tool_name,
                    relation="skill 授权调用 tool",
                )
            )

    nodes = agent_binding_nodes(bindings_by_agent)
    agent_name_by_id = {node.agent_id: node.name for node in nodes}
    agent_edges: list[CapabilityBindingEdge] = []
    for agent_id, tool_names in bindings_by_agent.items():
        for tool_name in tool_names:
            if tool_name not in tool_lookup:
                continue
            agent_edges.append(
                CapabilityBindingEdge(
                    from_id=agent_id,
                    from_label=agent_name_by_id.get(agent_id, agent_id),
                    to_id=tool_name,
                    to_label=tool_name,
                    relation="agent 持有 tool",
                )
            )

    recommendations = []
    for tool in tools:
        name = str(tool.get("name") or "")
        metadata = tool.get("operation_metadata") if isinstance(tool.get("operation_metadata"), dict) else {}
        owner_names = [item["name"] for item in list(metadata.get("bound_agents") or []) if isinstance(item, dict)]
        if classify_tool_source(tool) == "document" and "主会话智能体" in owner_names:
            recommendations.append(f"{name} 是文档能力，应从主会话下沉到文档智能体。")
        if not owner_names:
            recommendations.append(f"{name} 尚未绑定智能体，建议明确归属后再参与自动路由。")
    return CapabilityBindingGraph(
        agent_nodes=nodes,
        skill_tool_edges=skill_edges,
        agent_tool_edges=agent_edges,
        recommendations=recommendations,
    )


def build_operation_catalog(runtime, tool_overrides: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    overrides = dict(tool_overrides or {})
    skills = [skill_payload(runtime, skill) for skill in runtime.skill_registry.skills]
    raw_tools = [definition.to_registry_record() for definition in runtime.tool_runtime.definitions]
    bindings_by_agent = agent_tool_bindings(raw_tools)
    bound_agents_by_tool = tool_agent_bindings(bindings_by_agent)
    tools = []
    for record in raw_tools:
        tool_name = str(record.get("name") or "")
        metadata = dict(overrides.get(tool_name) or {})
        tools.append(
            {
                **record,
                "operation_metadata": operation_tool_metadata(record, metadata, skills, bound_agents_by_tool),
            }
        )

    risk_counts: dict[str, int] = {}
    boundary_counts: dict[str, int] = {}
    source_counts: dict[str, int] = {}
    for tool in tools:
        operation_metadata = tool["operation_metadata"]
        risk_counts[operation_metadata["risk_level"]] = risk_counts.get(operation_metadata["risk_level"], 0) + 1
        boundary_counts[operation_metadata["tool_boundary"]] = boundary_counts.get(operation_metadata["tool_boundary"], 0) + 1
        source_counts[operation_metadata["source_class"]] = source_counts.get(operation_metadata["source_class"], 0) + 1

    validation_issues = validate_capability_catalog(skills=skills, tools=tools, agent_bindings=bindings_by_agent)
    return {
        "skills": skills,
        "tools": tools,
        "binding_graph": build_binding_graph(skills, tools, bindings_by_agent).to_operation_payload(),
        "validation_issues": [issue.to_dict() for issue in validation_issues],
        "tool_type_options": TOOL_TYPE_OPTIONS,
        "summary": {
            "skill_count": len(skills),
            "tool_count": len(tools),
            "model_visible_skills": sum(1 for item in skills if item["runtime"].get("activation_policy") == "model_visible"),
            "tool_types": sorted({tool["operation_metadata"]["tool_type"] for tool in tools}),
            "tool_boundaries": dict(sorted(boundary_counts.items())),
            "tool_sources": dict(sorted(source_counts.items())),
            "tool_risks": dict(sorted(risk_counts.items(), key=lambda item: TOOL_RISK_ORDER.get(item[0], 0))),
        },
    }
