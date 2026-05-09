from __future__ import annotations

from dataclasses import asdict
from typing import Any

from capability_system.local_mcp_registry import build_local_mcp_catalog, default_local_mcp_units
from capability_system.mcp_registry import build_mcp_catalog
from capability_system.operation_registry import build_default_operation_registry
from .endpoints import build_capability_endpoints
from .models import AgentCapability, CapabilityBindingEdge, CapabilityBindingGraph, MCPCapability
from .search_policy import classify_tool_source, search_policy_labels, tool_text_set
from .skill_authoring import read_text
from .validation import validate_capability_catalog


MAIN_AGENT_ID = "agent:0"

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


def agent_tool_bindings(tools: list[dict[str, Any]]) -> dict[str, list[str]]:
    bindings: dict[str, list[str]] = {MAIN_AGENT_ID: []}
    for tool in tools:
        if str(tool.get("runtime_visibility") or "") == "main_runtime":
            bindings[MAIN_AGENT_ID].append(str(tool.get("name") or ""))
    return {agent_id: sorted(set(names)) for agent_id, names in bindings.items()}


def agent_binding_nodes(agent_bindings: dict[str, list[str]]) -> list[AgentCapability]:
    nodes = [
        AgentCapability(
            agent_id=MAIN_AGENT_ID,
            name="主会话智能体",
            kind="main",
            description="负责理解用户意图、选择路由、收束结果；只保留主运行时可见工具。",
            bound_tools=list(agent_bindings.get(MAIN_AGENT_ID, [])),
            protocol_version="0.3.0",
        )
    ]
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
    bound_agents_by_tool: dict[str, list[dict[str, str]]] | None = None,
) -> dict[str, Any]:
    tool_type = str(metadata.get("tool_type") or "").strip() or default_tool_type(tool)
    if tool_type not in TOOL_TYPE_OPTIONS:
        tool_type = "通用能力"
    tool_name = str(tool.get("name") or "")
    llm_description = str(metadata.get("llm_description") or tool.get("description") or "").strip()
    bound_agents = list((bound_agents_by_tool or {}).get(tool_name, []))
    source_class = classify_tool_source(tool)
    return {
        "tool_type": tool_type,
        "note": str(metadata.get("note") or ""),
        "llm_description": llm_description,
        "source_class": source_class,
        "search_policy": search_policy_labels(source_class),
        "tool_boundary": tool_boundary(tool),
        "adapter_type": tool_adapter_type(tool),
        "risk_level": tool_risk_level(tool),
        "risk_rank": TOOL_RISK_ORDER.get(tool_risk_level(tool), 0),
        "visibility_label": tool_visibility_label(tool),
        "runtime_policy": tool_runtime_policy(tool),
        "editable_policy": "前端可编辑类型与备注；工具注册、执行契约和安全边界由后端代码控制。",
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
    mcps: list[dict[str, Any]] | None = None,
) -> CapabilityBindingGraph:
    tool_lookup = {str(tool.get("name") or ""): tool for tool in tools}
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

    mcp_nodes = [
        MCPCapability(
            mcp_id=str(mcp.get("mcp_id") or ""),
            unit_id=str(mcp.get("unit_id") or ""),
            route=str(mcp.get("route") or ""),
            name=str(mcp.get("name") or ""),
            description=str(mcp.get("description") or ""),
            operation_id=str(mcp.get("operation_id") or ""),
            transport=str(mcp.get("transport") or ""),
            model_visibility=str(mcp.get("model_visibility") or ""),
            tags=[str(tag) for tag in list(mcp.get("tags") or [])],
        )
        for mcp in list(mcps or [])
    ]
    mcp_edges = [
        CapabilityBindingEdge(
            from_id=str(mcp.get("mcp_id") or ""),
            from_label=str(mcp.get("name") or mcp.get("route") or ""),
            to_id=str(mcp.get("operation_id") or ""),
            to_label=str(mcp.get("operation_id") or ""),
            relation="mcp capability 由 orchestration/internal endpoint 调度",
        )
        for mcp in list(mcps or [])
        if str(mcp.get("operation_id") or "").strip()
    ]

    recommendations = []
    for tool in tools:
        name = str(tool.get("name") or "")
        metadata = tool.get("operation_metadata") if isinstance(tool.get("operation_metadata"), dict) else {}
        owner_names = [item["name"] for item in list(metadata.get("bound_agents") or []) if isinstance(item, dict)]
        if classify_tool_source(tool) == "document" and "主会话智能体" in owner_names:
            recommendations.append(f"{name} 是文档能力，建议继续保持在编排内部端点侧执行。")
        if not owner_names:
            recommendations.append(f"{name} 当前没有主会话绑定，建议确认是否需要暴露给主运行时。")
    return CapabilityBindingGraph(
        agent_nodes=nodes,
        mcp_nodes=mcp_nodes,
        agent_tool_edges=agent_edges,
        mcp_operation_edges=mcp_edges,
        recommendations=recommendations,
    )


def build_capability_catalog(runtime, tool_overrides: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    overrides = dict(tool_overrides or {})
    skills = [skill_payload(runtime, skill) for skill in runtime.skill_registry.skills]
    tool_descriptions = {
        str(getattr(instance, "name", "") or ""): str(getattr(instance, "description", "") or "")
        for instance in runtime.tool_runtime.instances
    }
    raw_tools = [
        {
            **definition.to_registry_record(),
            "description": tool_descriptions.get(definition.name, ""),
        }
        for definition in runtime.tool_runtime.definitions
    ]
    operation_registry = build_default_operation_registry()
    operations = [operation.to_dict() for operation in operation_registry.list_operations()]
    mcps = build_mcp_catalog(operation_registry)
    local_mcp_units = build_local_mcp_catalog()
    bindings_by_agent = agent_tool_bindings(raw_tools)
    bound_agents_by_tool = tool_agent_bindings(bindings_by_agent)
    tools = []
    for record in raw_tools:
        tool_name = str(record.get("name") or "")
        metadata = dict(overrides.get(tool_name) or {})
        tools.append(
            {
                **record,
                "operation_metadata": operation_tool_metadata(record, metadata, bound_agents_by_tool),
            }
        )
    capability_endpoints = build_capability_endpoints(
        mcps=mcps,
    )

    risk_counts: dict[str, int] = {}
    boundary_counts: dict[str, int] = {}
    source_counts: dict[str, int] = {}
    for tool in tools:
        operation_metadata = tool["operation_metadata"]
        risk_counts[operation_metadata["risk_level"]] = risk_counts.get(operation_metadata["risk_level"], 0) + 1
        boundary_counts[operation_metadata["tool_boundary"]] = boundary_counts.get(operation_metadata["tool_boundary"], 0) + 1
        source_counts[operation_metadata["source_class"]] = source_counts.get(operation_metadata["source_class"], 0) + 1

    validation_issues = validate_capability_catalog(
        skills=skills,
        tools=tools,
        agent_bindings=bindings_by_agent,
        mcps=mcps,
        capability_endpoints=capability_endpoints,
        operations=operations,
    )
    return {
        "skills": skills,
        "tools": tools,
        "mcps": mcps,
        "local_mcp_units": local_mcp_units,
        "capability_endpoints": capability_endpoints,
        "operations": operations,
        "binding_graph": build_binding_graph(skills, tools, bindings_by_agent, mcps).to_operation_payload(),
        "validation_issues": [issue.to_dict() for issue in validation_issues],
        "tool_type_options": TOOL_TYPE_OPTIONS,
        "summary": {
            "skill_count": len(skills),
            "tool_count": len(tools),
            "mcp_count": len(mcps),
            "local_mcp_unit_count": len(local_mcp_units),
            "local_mcp_endpoint_count": len(mcps),
            "capability_endpoint_count": len(capability_endpoints),
            "model_visible_skills": sum(1 for item in skills if item["runtime"].get("activation_policy") == "model_visible"),
            "tool_types": sorted({tool["operation_metadata"]["tool_type"] for tool in tools}),
            "tool_boundaries": dict(sorted(boundary_counts.items())),
            "tool_sources": dict(sorted(source_counts.items())),
            "tool_risks": dict(sorted(risk_counts.items(), key=lambda item: TOOL_RISK_ORDER.get(item[0], 0))),
            "operation_count": len(operations),
            "validation_issue_count": len(validation_issues),
            "validation_error_count": sum(1 for issue in validation_issues if issue.severity == "error"),
        },
    }
