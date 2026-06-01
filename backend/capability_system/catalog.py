from __future__ import annotations

from dataclasses import asdict
from typing import Any

from capability_system.capability_units import build_capability_units
from capability_system.local_mcp_registry import build_local_mcp_catalog, default_local_mcp_units
from capability_system.mcp.management_service import MCPManagementService
from capability_system.mcp_registry import build_mcp_catalog
from capability_system.operation_registry import build_default_operation_registry
from capability_system.permission_views import attach_capability_permission_views
from capability_system.skill_routes import skill_operation_ids_from_runtime
from capability_system.tool_packages import default_tool_packages
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
    "版本控制",
    "通用能力",
]

TOOL_RISK_ORDER = {
    "低": 0,
    "中": 1,
    "高": 2,
    "极高": 3,
}

CAPABILITY_OPERATION_TYPE_LABELS = {
    "agent": "子 Agent",
    "artifact": "产物",
    "filesystem": "文件系统",
    "mcp": "本地能力端点",
    "memory": "记忆",
    "model": "模型响应",
    "network": "网络",
    "session": "会话",
    "shell": "本地执行",
    "vcs": "版本控制",
}

CAPABILITY_SOURCE_CLASS_LABELS = {
    "data": "数据",
    "document": "文档",
    "local_files": "本地文件",
    "rag": "知识检索",
    "system_execution": "系统执行",
    "web": "外部网络",
}

CAPABILITY_VALUE_LABELS = {
    "builtin": "内置",
    "explicit_resource": "显式资源",
    "handle_only": "仅传递资源句柄",
    "hidden": "对模型隐藏",
    "in_process": "进程内",
    "local": "本地",
    "local-capability-endpoints": "本地能力端点",
    "main_runtime": "主运行时",
    "model_visible": "模型可见",
    "not_direct_model_tool": "不直接暴露给模型",
    "debug_only": "仅调试可见",
}

CAPABILITY_RISK_TAG_LABELS = {
    "model_response": "模型生成回答",
    "read_only": "只读访问",
    "local_read": "读取本地文件",
    "structured_config": "读取结构化配置",
    "network_open_world": "访问开放网络",
    "external_fetch": "抓取外部网页",
    "git_read": "读取版本库信息",
    "local_write": "写入本地文件",
    "shell_execution": "执行本地命令",
    "python_execution": "执行 Python 代码",
    "memory_read": "读取记忆",
    "memory_write_candidate": "提交记忆写入候选",
    "mcp_execution": "调用本地能力端点",
    "document_analysis": "分析文档内容",
    "structured_data": "分析结构化数据",
    "agent_execution": "调用子 Agent",
    "subagent_lifecycle": "启动子 Agent",
    "session_write_candidate": "提交会话消息候选",
    "artifact_write_candidate": "提交产物候选",
}


def capability_display_label(value: Any, fallback: str = "未配置") -> str:
    raw = str(value or "").strip()
    if not raw:
        return fallback
    return CAPABILITY_VALUE_LABELS.get(raw, raw)


def capability_operation_type_label(value: Any) -> str:
    raw = str(value or "").strip()
    return CAPABILITY_OPERATION_TYPE_LABELS.get(raw, raw or "运行操作")


def capability_source_class_label(value: Any) -> str:
    raw = str(value or "").strip()
    return CAPABILITY_SOURCE_CLASS_LABELS.get(raw, raw or "运行操作")


def capability_risk_tag_label(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    return CAPABILITY_RISK_TAG_LABELS.get(raw, raw)

def default_tool_type(tool: dict[str, Any]) -> str:
    tags = tool_text_set(tool, "capability_tags", "supported_modalities")
    safety = tool_text_set(tool, "safety_tags")
    name = str(tool.get("name") or "").lower()
    source_class = classify_tool_source(tool)
    if tags & {"git", "vcs"} or str(tool.get("operation_id") or "").startswith("op.git_"):
        return "版本控制"
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
            relation="本地能力端点由编排系统调度",
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
    skill_registry = getattr(runtime, "skill_registry", None)
    tool_runtime = getattr(runtime, "tool_runtime", None)
    skills = [skill_payload(runtime, skill) for skill in getattr(skill_registry, "skills", ())] if skill_registry is not None else []
    if tool_runtime is None:
        tool_descriptions: dict[str, str] = {}
        raw_tools: list[dict[str, Any]] = []
    else:
        tool_descriptions = {
            str(getattr(instance, "name", "") or ""): str(getattr(instance, "description", "") or "")
            for instance in getattr(tool_runtime, "instances", ())
        }
        raw_tools = [
            {
                **definition.to_registry_record(),
                "description": tool_descriptions.get(definition.name, ""),
            }
            for definition in tool_runtime.definitions
        ]
    operation_registry = build_default_operation_registry()
    operations = [operation.to_dict() for operation in operation_registry.list_operations()]
    mcps = build_mcp_catalog(operation_registry)
    local_mcp_units = build_local_mcp_catalog()
    unified_mcp = MCPManagementService(runtime.base_dir, include_external=True).build_catalog()
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
    operation_ids_in_packages = {
        operation_id
        for package in default_tool_packages()
        for operation_id in package.operation_ids
    }
    default_library = [
        {
            "tool_name": str(tool.get("name") or ""),
            "operation_id": str(tool.get("operation_id") or ""),
            "tool_type": str(dict(tool.get("operation_metadata") or {}).get("tool_type") or ""),
        }
        for tool in tools
        if str(tool.get("operation_id") or "") not in operation_ids_in_packages
    ]

    catalog_payload = {
        "skills": skills,
        "tools": tools,
        "mcps": mcps,
        "local_mcp_units": local_mcp_units,
        "mcp_management": unified_mcp,
        "capability_endpoints": capability_endpoints,
        "operations": operations,
        "tool_packages": [package.to_dict() for package in default_tool_packages()],
        "default_library": default_library,
    }
    capability_units = attach_capability_permission_views(build_capability_units(catalog_payload))

    validation_issues = validate_capability_catalog(
        skills=skills,
        tools=tools,
        agent_bindings=bindings_by_agent,
        mcps=mcps,
        capability_endpoints=capability_endpoints,
        capability_units=capability_units,
        operations=operations,
    )
    return {
        "skills": skills,
        "tools": tools,
        "mcps": mcps,
        "local_mcp_units": local_mcp_units,
        "mcp_management": unified_mcp,
        "capability_units": capability_units,
        "capability_endpoints": capability_endpoints,
        "operations": operations,
        "tool_packages": [package.to_dict() for package in default_tool_packages()],
        "default_library": default_library,
        "binding_graph": build_binding_graph(skills, tools, bindings_by_agent, mcps).to_operation_payload(),
        "validation_issues": [issue.to_dict() for issue in validation_issues],
        "tool_type_options": TOOL_TYPE_OPTIONS,
        "summary": {
            "skill_count": len(skills),
            "tool_count": len(tools),
            "mcp_count": len(mcps),
            "mcp_management_server_count": unified_mcp["summary"]["server_count"],
            "local_mcp_unit_count": len(local_mcp_units),
            "local_mcp_endpoint_count": len(mcps),
            "capability_endpoint_count": len(capability_endpoints),
            "capability_unit_count": len(capability_units),
            "model_visible_skills": sum(1 for item in skills if item["runtime"].get("activation_policy") == "model_visible"),
            "tool_types": sorted({tool["operation_metadata"]["tool_type"] for tool in tools}),
            "tool_package_count": len(default_tool_packages()),
            "default_library_tool_count": len(default_library),
            "tool_boundaries": dict(sorted(boundary_counts.items())),
            "tool_sources": dict(sorted(source_counts.items())),
            "tool_risks": dict(sorted(risk_counts.items(), key=lambda item: TOOL_RISK_ORDER.get(item[0], 0))),
            "operation_count": len(operations),
            "validation_issue_count": len(validation_issues),
            "validation_error_count": sum(1 for issue in validation_issues if issue.severity == "error"),
        },
    }


def _capability_risk_from_operation(operation: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(operation, dict):
        return {
            "risk_label": "注册信息不足",
            "risk_tone": "warn",
            "risk_items": ["缺少 operation 描述"],
        }
    items = _dedupe_texts([
        *[capability_risk_tag_label(tag) for tag in list(operation.get("risk_tags") or []) if str(tag).strip()],
        "只读" if bool(operation.get("read_only")) else "",
        "破坏性操作" if bool(operation.get("destructive")) else "",
        "默认需要审批" if bool(operation.get("requires_approval_by_default")) else "",
        "可并发" if bool(operation.get("concurrency_safe")) else "",
    ])
    risk_tags = [str(tag) for tag in list(operation.get("risk_tags") or []) if str(tag).strip()]
    if bool(operation.get("destructive")):
        return {"risk_label": "高风险", "risk_tone": "danger", "risk_items": items}
    if bool(operation.get("requires_approval_by_default")) or any(
        any(marker in tag for marker in ("write", "execution", "network"))
        for tag in risk_tags
    ):
        return {"risk_label": "需审慎授权", "risk_tone": "warn", "risk_items": items}
    if bool(operation.get("read_only")):
        return {"risk_label": "低风险只读", "risk_tone": "ok", "risk_items": items}
    return {"risk_label": "中性风险", "risk_tone": "neutral", "risk_items": items}


def build_orchestration_capability_items(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    operations = [item for item in list(catalog.get("operations") or []) if isinstance(item, dict)]
    operation_by_id = {
        str(item.get("operation_id") or "").strip(): item
        for item in operations
        if str(item.get("operation_id") or "").strip()
    }
    items: list[dict[str, Any]] = []
    used_tool_operation_ids: set[str] = set()
    mcp_operation_ids: set[str] = set()

    for skill in [item for item in list(catalog.get("skills") or []) if isinstance(item, dict)]:
        runtime = skill.get("runtime") if isinstance(skill.get("runtime"), dict) else {}
        prompt_view = skill.get("prompt_view") if isinstance(skill.get("prompt_view"), dict) else {}
        route = str(runtime.get("preferred_route") or "").strip()
        operation_ids = skill_operation_ids_from_runtime(runtime)
        primary_operation_id = operation_ids[0] if operation_ids else ""
        operation = operation_by_id.get(primary_operation_id)
        risk = _capability_risk_from_operation(operation)
        items.append({
            "capability_id": f"skill:{str(runtime.get('name') or '').strip()}",
            "capability_kind": "skill",
            "title": str(prompt_view.get("title") or runtime.get("title") or runtime.get("name") or "").strip(),
            "subtitle": f"依赖 {', '.join(operation_ids)}" if operation_ids else "未声明运行依赖",
            "description": str(prompt_view.get("capability") or runtime.get("description") or "未注册说明").strip(),
            "operation_ids": operation_ids,
            "source_label": "任务能力 · 模型可见入口",
            "source_detail": f"调用路线：{capability_display_label(route)}；授权落到依赖的运行操作。",
            "risk_label": risk["risk_label"],
            "risk_tone": risk["risk_tone"],
            "risk_items": risk["risk_items"],
            "tags": [str(tag) for tag in [*list(runtime.get("capability_tags") or []), *list(runtime.get("supported_modalities") or [])] if str(tag).strip()][:8],
            "metadata": [
                {"label": "使用时机", "value": str(prompt_view.get("use_when") or "未注册 use_when").strip() or "未注册 use_when"},
                {"label": "输出规则", "value": str(prompt_view.get("output_rule") or "未注册 output_rule").strip() or "未注册 output_rule"},
                {"label": "上下文", "value": str(runtime.get("context_mode") or "未配置").strip() or "未配置"},
                {"label": "依赖能力", "value": ", ".join(str(item) for item in list(runtime.get("requires_capabilities") or [])) or "未声明"},
            ],
        })

    for tool in [item for item in list(catalog.get("tools") or []) if isinstance(item, dict)]:
        operation_id = str(tool.get("operation_id") or "").strip()
        operation = operation_by_id.get(operation_id)
        metadata = tool.get("operation_metadata") if isinstance(tool.get("operation_metadata"), dict) else {}
        risk = _capability_risk_from_operation(operation)
        if operation_id:
            used_tool_operation_ids.add(operation_id)
        items.append({
            "capability_id": f"tool:{str(tool.get('name') or '').strip()}",
            "capability_kind": "tool",
            "title": str((operation or {}).get("title") or tool.get("name") or "").strip(),
            "subtitle": f"{str(tool.get('name') or '').strip()} · {operation_id}".strip(" ·"),
            "description": str((operation or {}).get("capability_summary") or metadata.get("note") or " / ".join(str(tag) for tag in list(tool.get("capability_tags") or []))).strip() or "未注册说明",
            "operation_ids": [operation_id] if operation_id else [],
            "source_label": f"本地工具 · {capability_source_class_label(metadata.get('source_class') or (operation or {}).get('operation_type'))}",
            "source_detail": f"{str(metadata.get('tool_boundary') or '未标注边界').strip()} · {str(metadata.get('adapter_type') or tool.get('module') or '本地适配器').strip()}",
            "risk_label": str(metadata.get("risk_level") or risk["risk_label"]).strip() or risk["risk_label"],
            "risk_tone": risk["risk_tone"],
            "risk_items": _dedupe_texts([
                *risk["risk_items"],
                *[capability_risk_tag_label(tag) for tag in list(tool.get("safety_tags") or []) if str(tag).strip()],
                "可自动路由" if bool(tool.get("safe_for_auto_route")) else "需要显式触发",
                str(metadata.get("runtime_policy") or "").strip(),
            ])[:10],
            "tags": [str(tag) for tag in [*list(tool.get("capability_tags") or []), *list(tool.get("supported_modalities") or [])] if str(tag).strip()][:8],
            "metadata": [
                {"label": "运行可见性", "value": capability_display_label(tool.get("runtime_visibility"))},
                {"label": "提示词暴露", "value": capability_display_label(tool.get("prompt_exposure_policy"))},
                {"label": "资源暴露", "value": capability_display_label(tool.get("resource_exposure_policy"))},
            ],
        })

    for operation in operations:
        operation_id = str(operation.get("operation_id") or "").strip()
        if not operation_id or operation.get("operation_type") == "mcp" or operation_id in used_tool_operation_ids:
            continue
        risk = _capability_risk_from_operation(operation)
        items.append({
            "capability_id": f"operation:{operation_id}",
            "capability_kind": "operation",
            "title": str(operation.get("title") or operation_id).strip(),
            "subtitle": f"{capability_operation_type_label(operation.get('operation_type'))} · {operation_id}",
            "description": str(operation.get("capability_summary") or "未注册说明").strip() or "未注册说明",
            "operation_ids": [operation_id],
            "source_label": "运行操作注册表",
            "source_detail": f"{capability_operation_type_label(operation.get('operation_type'))}，由运行时授权列表直接控制。",
            "risk_label": risk["risk_label"],
            "risk_tone": risk["risk_tone"],
            "risk_items": risk["risk_items"],
            "tags": [str(tag) for tag in list(operation.get("risk_tags") or []) if str(tag).strip()][:8],
            "metadata": [
                {"label": "提供方", "value": capability_display_label(operation.get("provider") or "builtin")},
                {"label": "审批", "value": "默认需要审批" if bool(operation.get("requires_approval_by_default")) else "默认不要求审批"},
                {"label": "中断行为", "value": str(operation.get("interrupt_behavior") or "未配置").strip() or "未配置"},
            ],
        })

    mcp_entries = [item for item in list(catalog.get("mcps") or []) if isinstance(item, dict)]
    if not mcp_entries:
        binding_graph = catalog.get("binding_graph") if isinstance(catalog.get("binding_graph"), dict) else {}
        mcp_entries = [item for item in list(binding_graph.get("mcp_nodes") or []) if isinstance(item, dict)]
    for mcp in mcp_entries:
        operation_id = str(mcp.get("operation_id") or "").strip()
        operation = operation_by_id.get(operation_id)
        risk = _capability_risk_from_operation(operation)
        if operation_id:
            mcp_operation_ids.add(operation_id)
        items.append({
            "capability_id": f"mcp:{str(mcp.get('mcp_id') or operation_id).strip()}",
            "capability_kind": "mcp",
            "title": str(mcp.get("name") or (operation or {}).get("title") or operation_id).strip(),
            "subtitle": f"{str(mcp.get('route') or mcp.get('unit_id') or 'local').strip()} · {operation_id}".strip(" ·"),
            "description": str(mcp.get("description") or (operation or {}).get("capability_summary") or "未注册说明").strip() or "未注册说明",
            "operation_ids": [operation_id] if operation_id else [],
            "source_label": "本地能力端点",
            "source_detail": f"{capability_display_label(mcp.get('transport') or 'in_process')} · {capability_display_label(mcp.get('model_visibility') or 'not_direct_model_tool')}",
            "risk_label": risk["risk_label"],
            "risk_tone": risk["risk_tone"],
            "risk_items": _dedupe_texts([
                *risk["risk_items"],
                *[f"输入 {str(item).strip()}" for item in list(mcp.get("input_modes") or []) if str(item).strip()],
                *[f"输出 {str(item).strip()}" for item in list(mcp.get("output_modes") or []) if str(item).strip()],
            ])[:10],
            "tags": [str(tag) for tag in list(mcp.get("tags") or []) if str(tag).strip()][:8],
            "metadata": [
                {"label": "端点标识", "value": str(mcp.get("mcp_id") or "未配置").strip() or "未配置"},
                {"label": "能力单元", "value": str(mcp.get("unit_id") or "未配置").strip() or "未配置"},
                {"label": "服务", "value": capability_display_label(mcp.get("server_name") or "local-capability-endpoints")},
            ],
        })

    for operation in operations:
        operation_id = str(operation.get("operation_id") or "").strip()
        if operation.get("operation_type") != "mcp" or not operation_id or operation_id in mcp_operation_ids:
            continue
        risk = _capability_risk_from_operation(operation)
        items.append({
            "capability_id": f"mcp-operation:{operation_id}",
            "capability_kind": "mcp",
            "title": str(operation.get("title") or operation_id).strip(),
            "subtitle": operation_id,
            "description": str(operation.get("capability_summary") or "未注册说明").strip() or "未注册说明",
            "operation_ids": [operation_id],
            "source_label": "本地能力端点 · 运行操作后备",
            "source_detail": "能力系统未返回本地能力端点明细，当前使用运行操作注册信息展示。",
            "risk_label": risk["risk_label"],
            "risk_tone": risk["risk_tone"],
            "risk_items": risk["risk_items"],
            "tags": [str(tag) for tag in list(operation.get("risk_tags") or []) if str(tag).strip()][:8],
            "metadata": [{"label": "注册状态", "value": "缺少本地能力端点明细"}],
        })

    return items


def _dedupe_texts(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


