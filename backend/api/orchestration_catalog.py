from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from agent_system.groups.registry import AgentGroupRegistry
from agent_system.models.model_profile_resolver import build_provider_catalog
from agent_system.profiles.runtime_profile_registry import AgentRuntimeRegistry
from agent_system.registry.agent_registry import AgentRegistry
from agent_system.registry.worker_agent_factory import default_worker_agent_blueprints
from api.deps import require_runtime
from capability_system import build_capability_catalog, build_default_operation_registry, build_orchestration_capability_items
from orchestration import ControlKernel, TaskContract, build_base_unit_catalog
from orchestration.delegation_catalog import DelegationCatalogBuilder
from orchestration.resource_inventory import build_runtime_resource_inventory
from orchestration.runtime_lane_registry import DEFAULT_RUNTIME_LANE_REGISTRY, runtime_lane_option_payloads
from agent_system.profiles.runtime_mode_config import mode_config_catalog
from task_system import TaskFlowRegistry

router = APIRouter()


class BehaviorDryRunRequest(BaseModel):
    session_id: str
    message: str = Field(..., min_length=1)
    ephemeral_system_messages: list[str] = Field(default_factory=list)
    explicit_subtasks: list[dict[str, Any]] = Field(default_factory=list)


class OrchestrationModeRequest(BaseModel):
    mode: str = Field(default="primary")


class AgentRuntimeProfileRequest(BaseModel):
    agent_profile_id: str = Field(default="", max_length=160)
    enabled_runtime_modes: list[str] = Field(default_factory=list)
    default_runtime_mode: str = Field(default="", max_length=80)
    allowed_runtime_lanes: list[str] = Field(default_factory=list)
    allowed_operations: list[str] = Field(default_factory=list)
    blocked_operations: list[str] = Field(default_factory=list)
    allowed_memory_scopes: list[str] = Field(default_factory=list)
    allowed_context_sections: list[str] = Field(default_factory=list)
    use_shared_contract: bool = True
    can_delegate_to_agents: bool = False
    allowed_delegate_agent_ids: list[str] = Field(default_factory=list)
    max_delegate_calls_per_turn: int = Field(default=1, ge=0)
    delegate_context_policy: str = Field(default="summary_and_refs_only", max_length=120)
    approval_policy: str = Field(default="default", max_length=80)
    trace_policy: str = Field(default="runtime_event_log", max_length=120)
    lifecycle_policy: str = Field(default="orchestration_managed", max_length=120)
    model_profile: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class OrchestrationAgentUpsertRequest(BaseModel):
    agent_id: str = Field(..., min_length=3, max_length=160)
    agent_name: str = Field(..., min_length=1, max_length=160)
    agent_category: str = Field(default="custom_agent", max_length=80)
    interface_target: str = Field(default="", max_length=160)
    description: str = Field(default="", max_length=1000)
    enabled: bool = True
    editable: bool = True
    default_soul_id: str = Field(default="", max_length=160)
    default_projection_id: str = Field(default="", max_length=160)
    metadata: dict[str, Any] = Field(default_factory=dict)


class OrchestrationAgentGroupUpsertRequest(BaseModel):
    group_id: str = Field(..., min_length=3, max_length=160)
    title: str = Field(..., min_length=1, max_length=160)
    group_kind: str = Field(default="coordination_team", max_length=120)
    coordinator_agent_id: str = Field(default="", max_length=160)
    member_agent_ids: list[str] = Field(default_factory=list)
    description: str = Field(default="", max_length=1000)
    lifecycle_state: str = Field(default="enabled", max_length=80)
    metadata: dict[str, Any] = Field(default_factory=dict)


class OrchestrationPreviewRequest(BaseModel):
    session_id: str = Field(default="session-preview")
    turn_id: str = Field(default="turn:session-preview:1")
    task_id: str = Field(default="taskinst:turn:session-preview:1:general_response")
    user_goal: str = Field(..., min_length=1)
    source: str = Field(default="orchestration_preview")
    task_selection: dict[str, Any] = Field(default_factory=dict)


class DelegationPreviewRequest(BaseModel):
    parent_agent_id: str = Field(default="")
    target_agent_id: str = Field(default="")
    delegation_kind: str = Field(default="")


OPTION_LABELS: dict[str, str] = {
    "general": "通用任务域",
    "development": "开发任务域",
    "longform_novel_writing": "长篇小说创作域",
    "writing": "写作任务域",
    "health": "健康任务域",
    "capability": "能力调用域",
    "general_task": "通用任务",
    "bounded_patch": "受限补丁",
    "light_web_game": "轻量网页小游戏",
    "arcade_game_bundle": "复合网页游戏包",
    "longform_novel_graph": "长篇小说图运行",
    "knowledge_retrieval": "知识检索",
    "information_search": "信息搜索",
    "capability_execution": "能力执行",
    "main_conversation_entry": "主会话入口",
    "issue_triage": "健康问题分诊",
    "trace_analysis": "健康链路分析",
    "case_draft": "健康用例草案",
    "fix_verification": "健康修复验证",
    "session_memory_maintenance": "会话记忆维护",
    "durable_memory_extraction": "长期记忆提取",
    "memory_candidate_review": "记忆候选审核",
    "op.model_response": "模型响应",
    "op.read_file": "读取文件",
    "op.search_files": "搜索文件",
    "op.search_text": "搜索文本",
    "op.list_dir": "列出目录",
    "op.stat_path": "读取路径信息",
    "op.path_exists": "检查路径存在",
    "op.glob_paths": "通配查找路径",
    "op.read_structured_file": "读取结构化文件",
    "op.web_search": "网页搜索",
    "op.fetch_url": "抓取网页",
    "op.git_status": "查看 Git 状态",
    "op.git_diff": "查看 Git 差异",
    "op.git_log": "查看 Git 日志",
    "op.git_show": "查看 Git 对象",
    "op.write_file": "写入文件",
    "op.edit_file": "编辑文件",
    "op.shell": "终端命令",
    "op.python_repl": "Python 执行",
    "op.memory_read": "读取记忆",
    "op.memory_write_candidate": "提交记忆候选",
    "op.mcp_retrieval": "检索 MCP",
    "op.mcp_pdf": "PDF MCP",
    "op.mcp_structured_data": "结构化数据 MCP",
    "op.delegate_to_agent": "委派子Agent",
    "op.agent_bounded": "运行受限 Agent",
    "op.session_message_candidate": "提交会话消息候选",
    "op.artifact_result_ref": "提交产物引用候选",
    "default": "默认审批",
    "read_only_first": "只读优先",
    "manual_approval_required": "需要人工审批",
    "deny_destructive": "拒绝破坏性操作",
    "runtime_event_log": "运行事件追踪",
    "full_trace": "完整追踪",
    "minimal_trace": "最小追踪",
    "conversation": "会话内容",
    "state": "当前状态",
    "task": "任务信息",
    "projection": "投影信息",
    "tool": "工具结果",
    "health_issue": "健康事项",
    "runtime_trace": "运行追踪",
    "prompt_manifest": "提示结构",
    "memory_runtime_view": "记忆视图",
    "runtime_contracts": "运行契约",
    "artifact_refs": "产物引用",
    "upstream_outputs": "上游交接",
    "working_memory": "工作记忆包",
    "task_durable_memory": "任务持久记忆",
    "coordination_task_state": "协调任务状态",
    "assertions": "验收断言",
    "conversation_readonly": "会话记忆只读",
    "state_readonly": "状态记忆只读",
    "long_term_candidate": "长期记忆候选",
    "session_memory_write_candidate": "会话记忆写入候选",
    "durable_memory_write_candidate": "长期记忆写入候选",
    "issue_local_readonly": "事项局部只读",
    "health_trace_readonly": "健康追踪只读",
    "formal_memory_read": "正式记忆读取",
    "formal_memory_write_candidate": "正式记忆写入候选",
}


def _option_label(value: str, fallback: str = "") -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return fallback or "未配置"
    if normalized in OPTION_LABELS:
        return OPTION_LABELS[normalized]
    return fallback or normalized


def _option(value: str, *, label: str = "", description: str = "") -> dict[str, str]:
    normalized = str(value or "").strip()
    return {
        "id": normalized,
        "value": normalized,
        "label": _option_label(normalized, label),
        "description": str(description or "").strip(),
    }


def _operation_option(operation: Any) -> dict[str, str]:
    operation_id = str(getattr(operation, "operation_id", "") or "").strip()
    return {
        **_option(
            operation_id,
            label=str(getattr(operation, "title", "") or ""),
            description=str(getattr(operation, "capability_summary", "") or ""),
        ),
        "operation_type": str(getattr(operation, "operation_type", "") or ""),
    }


def _memory_scope_option(value: str) -> dict[str, str]:
    descriptions = {
        "conversation_readonly": "只读取会话连续性候选；普通主回答不直接读取 Session Memory 热摘要。",
        "state_readonly": "只读取 process_state.json 派生的状态快照和恢复候选。",
        "long_term_candidate": "读取长期记忆候选；不能直接写入长期记忆。",
        "session_memory_write_candidate": "仅记忆管理 Agent 使用：提交后维护 Session Memory。",
        "durable_memory_write_candidate": "仅记忆管理 Agent 使用：提交长期记忆写入计划并接受沙箱校验。",
        "formal_memory_read": "读取正式记忆模型。",
        "formal_memory_write_candidate": "提交正式记忆候选，不自动落盘。",
        "issue_local_readonly": "读取健康事项局部记忆。",
        "health_trace_readonly": "读取健康追踪记忆。",
    }
    normalized = str(value or "").strip()
    return _option(normalized, description=descriptions.get(normalized, ""))


def _record_field_text(record: Any, field: str) -> str:
    if isinstance(record, dict):
        value = record.get(field)
    else:
        value = getattr(record, field, "")
    return str(value or "").strip()


def _task_graph_option(value: str, *, label: str, description: str = "", source: str = "") -> dict[str, str]:
    option = _option(value, label=label, description=description)
    option["source"] = str(source or "").strip()
    return option


def _build_task_graph_options(task_registry: TaskFlowRegistry) -> tuple[list[str], list[dict[str, str]]]:
    options_by_value: dict[str, dict[str, str]] = {}

    def add(value: str, *, label: str, description: str = "", source: str = "") -> None:
        normalized = str(value or "").strip()
        if not normalized or normalized in options_by_value:
            return
        options_by_value[normalized] = _task_graph_option(
            normalized,
            label=label,
            description=description,
            source=source,
        )

    for graph in task_registry.list_task_graphs():
        if not graph.enabled and graph.publish_state == "archived":
            continue
        add(
            graph.graph_id,
            label=f"{graph.title} · 任务图",
            description=f"{graph.graph_kind} / {graph.publish_state}",
            source="task_graph",
        )

    options = sorted(options_by_value.values(), key=lambda item: (item.get("source", ""), item["label"], item["value"]))
    return [item["value"] for item in options], options


DEFAULT_ORCHESTRATION_CONTEXT_SECTIONS = (
    "conversation",
    "state",
    "task",
    "projection",
    "tool",
    "runtime_contracts",
    "artifact_refs",
    "upstream_outputs",
    "working_memory",
    "task_durable_memory",
    "health_issue",
    "runtime_trace",
    "prompt_manifest",
    "memory_runtime_view",
    "assertions",
)


DEFAULT_ORCHESTRATION_MEMORY_SCOPES = (
    "conversation_readonly",
    "state_readonly",
    "long_term_candidate",
    "session_memory_write_candidate",
    "durable_memory_write_candidate",
    "formal_memory_read",
    "formal_memory_write_candidate",
    "issue_local_readonly",
    "health_trace_readonly",
)


def _build_runtime_profile_option_values(
    profiles: list[Any],
    *,
    field: str,
    defaults: tuple[str, ...],
) -> list[str]:
    values = {
        str(item).strip()
        for profile in profiles
        for item in tuple(getattr(profile, field, ()) or ())
        if str(item).strip()
    }
    values.update(defaults)
    values.discard("")
    values.discard("conversation_read_write")
    values.discard("state_read_write")
    return sorted(values)


@router.post("/orchestration/dry-run")
async def orchestration_dry_run(payload: BehaviorDryRunRequest) -> dict[str, Any]:
    runtime = require_runtime()
    try:
        task = TaskContract(
            task_id=f"dry-run:{payload.session_id}",
            session_id=payload.session_id,
            user_goal=payload.message,
            inputs={
                "ephemeral_system_message_count": len(payload.ephemeral_system_messages),
                "explicit_subtask_count": len(payload.explicit_subtasks),
            },
        )
        control = ControlKernel().collect(task=task)
        return {
            "state": "wiring_cleared",
            "control": control.to_dict(),
            "unit_catalog": build_base_unit_catalog().to_list(),
            "runtime_available": runtime is not None,
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/orchestration/catalog")
async def orchestration_catalog() -> dict[str, Any]:
    runtime = require_runtime()
    skills = []
    for skill in runtime.skill_registry.skills:
        skills.append(
            {
                "runtime": asdict(skill.runtime),
                "prompt_view": skill.prompt_view.to_dict() if hasattr(skill.prompt_view, "to_dict") else {
                    "name": skill.prompt_view.name,
                    "title": skill.prompt_view.title,
                    "capability": skill.prompt_view.capability,
                    "use_when": skill.prompt_view.use_when,
                    "output_rule": skill.prompt_view.output_rule,
                },
            }
        )
    tools = [tool.to_registry_record() for tool in runtime.tool_runtime.definitions]
    return {
        "permission_mode": runtime.permission_service.current_mode(),
        "supported_permission_modes": runtime.permission_service.supported_modes(),
        "tool_invocation_validation_mode": runtime.query_runtime.tool_invocation_validation_mode,
        "orchestration_plan_mode": runtime.settings.get_orchestration_plan_mode(),
        "orchestration_state": "wiring_cleared",
        "supported_orchestration_plan_modes": ["primary"],
        "unit_catalog": build_base_unit_catalog().to_list(),
        "skills": skills,
        "tools": tools,
    }


@router.get("/orchestration/agents")
async def orchestration_agents() -> dict[str, Any]:
    runtime = require_runtime()
    registry = AgentRuntimeRegistry(runtime.base_dir)
    catalog = registry.build_catalog()
    groups = AgentGroupRegistry(runtime.base_dir).list_groups()
    options_payload = await orchestration_runtime_options()
    return {
        **catalog,
        "agent_groups": [item.to_dict() for item in groups],
        "options": dict(options_payload.get("options") or _empty_orchestration_runtime_options()),
    }


def _empty_orchestration_runtime_options() -> dict[str, Any]:
    return {
        "operations": [],
        "task_graphs": [],
        "runtime_lanes": [],
        "runtime_modes": [],
        "runtime_lane_registry": {},
        "runtime_lane_diagnostics": {"authority": "orchestration.runtime_lane_registry"},
        "memory_scopes": [],
        "context_sections": [],
        "approval_policies": [],
        "trace_policies": [],
        "operation_options": [],
        "task_graph_options": [],
        "runtime_lane_options": [],
        "memory_scope_options": [],
        "context_section_options": [],
        "approval_policy_options": [],
        "trace_policy_options": [],
        "worker_blueprints": [],
        "capability_items": [],
    }


@router.get("/orchestration/runtime-options")
async def orchestration_runtime_options() -> dict[str, Any]:
    runtime = require_runtime()
    registry = AgentRuntimeRegistry(runtime.base_dir)
    task_registry = TaskFlowRegistry(runtime.base_dir)
    profiles = registry.list_profiles()
    operations = build_default_operation_registry().list_operations()
    task_graph_refs, task_graph_options = _build_task_graph_options(task_registry)
    profile_runtime_lanes = {
        lane
        for profile in profiles
        for lane in profile.allowed_runtime_lanes
        if lane
    }
    task_graph_runtime_lanes = {
        lane
        for graph in task_registry.list_task_graphs()
        for node in graph.nodes
        for lane in [_record_field_text(node, "runtime_lane")]
        if lane
    }
    registered_runtime_lanes = {item.lane_id for item in DEFAULT_RUNTIME_LANE_REGISTRY.list_lanes()}
    runtime_lanes = [item["value"] for item in runtime_lane_option_payloads(include_non_requestable=False)]
    runtime_lane_diagnostics = {
        "authority": "orchestration.runtime_lane_registry",
        "profile_unregistered_lanes": sorted(profile_runtime_lanes - registered_runtime_lanes),
        "task_graph_unregistered_lanes": sorted(task_graph_runtime_lanes - registered_runtime_lanes),
        "task_graph_non_requestable_lanes": sorted(
            lane
            for lane in task_graph_runtime_lanes
            if (descriptor := DEFAULT_RUNTIME_LANE_REGISTRY.get(lane)) is not None and not descriptor.requestable
        ),
    }
    memory_scopes = _build_runtime_profile_option_values(
        profiles,
        field="allowed_memory_scopes",
        defaults=DEFAULT_ORCHESTRATION_MEMORY_SCOPES,
    )
    context_sections = _build_runtime_profile_option_values(
        profiles,
        field="allowed_context_sections",
        defaults=DEFAULT_ORCHESTRATION_CONTEXT_SECTIONS,
    )
    approval_policies = ["default", "read_only_first", "manual_approval_required", "deny_destructive"]
    trace_policies = ["runtime_event_log", "full_trace", "minimal_trace"]
    return {
        "authority": "orchestration.runtime_options",
        "options": {
            "operations": [item.to_dict() for item in operations],
            "task_graphs": task_graph_refs,
            "runtime_lanes": runtime_lanes,
            "runtime_modes": mode_config_catalog(),
            "runtime_lane_registry": DEFAULT_RUNTIME_LANE_REGISTRY.catalog_payload(),
            "runtime_lane_diagnostics": runtime_lane_diagnostics,
            "memory_scopes": memory_scopes,
            "context_sections": context_sections,
            "approval_policies": approval_policies,
            "trace_policies": trace_policies,
            "operation_options": [_operation_option(item) for item in operations],
            "task_graph_options": task_graph_options,
            "runtime_lane_options": runtime_lane_option_payloads(include_non_requestable=False),
            "memory_scope_options": [_memory_scope_option(item) for item in memory_scopes],
            "context_section_options": [_option(item) for item in context_sections],
            "approval_policy_options": [_option(item) for item in approval_policies],
            "trace_policy_options": [_option(item) for item in trace_policies],
            "worker_blueprints": [item.to_dict() for item in default_worker_agent_blueprints()],
            "capability_items": [],
            "model_provider_catalog": build_provider_catalog(getattr(runtime, "settings", None)),
        },
    }


@router.get("/orchestration/capability-items")
async def orchestration_capability_items() -> dict[str, Any]:
    runtime = require_runtime()
    capability_catalog = build_capability_catalog(runtime, {})
    return {
        "authority": "orchestration.capability_items",
        "capability_items": build_orchestration_capability_items(capability_catalog),
    }


@router.get("/orchestration/resource-inventory")
async def orchestration_resource_inventory() -> dict[str, Any]:
    runtime = require_runtime()
    return build_runtime_resource_inventory(runtime.base_dir).to_dict()


@router.get("/orchestration/agents/next-worker-id")
async def next_orchestration_worker_agent_id() -> dict[str, str]:
    runtime = require_runtime()
    return {
        "authority": "orchestration.agent_registry",
        "agent_id": AgentRegistry(runtime.base_dir).next_worker_agent_id(),
    }


@router.put("/orchestration/agents/{agent_id}")
async def upsert_orchestration_agent(
    agent_id: str,
    payload: OrchestrationAgentUpsertRequest,
) -> dict[str, Any]:
    runtime = require_runtime()
    if payload.agent_id != agent_id:
        payload = payload.model_copy(update={"agent_id": agent_id})
    try:
        AgentRegistry(runtime.base_dir).upsert_agent(
            agent_id=payload.agent_id,
            agent_name=payload.agent_name,
            agent_category=payload.agent_category,
            interface_target=payload.interface_target,
            description=payload.description,
            enabled=payload.enabled,
            editable=payload.editable,
            default_soul_id=payload.default_soul_id,
            default_projection_id=payload.default_projection_id,
            metadata={**payload.metadata, "managed_by": "orchestration_console"},
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await orchestration_agents()


@router.delete("/orchestration/agents/{agent_id}")
async def delete_orchestration_agent(agent_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    try:
        AgentRegistry(runtime.base_dir).delete_agent(agent_id)
        AgentRuntimeRegistry(runtime.base_dir).delete_profile(agent_id)
        AgentGroupRegistry(runtime.base_dir).remove_agent_refs(agent_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Agent not found") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await orchestration_agents()


@router.put("/orchestration/agent-groups/{group_id}")
async def upsert_orchestration_agent_group(
    group_id: str,
    payload: OrchestrationAgentGroupUpsertRequest,
) -> dict[str, Any]:
    runtime = require_runtime()
    if payload.group_id != group_id:
        payload = payload.model_copy(update={"group_id": group_id})
    try:
        AgentGroupRegistry(runtime.base_dir).upsert_group(
            group_id=payload.group_id,
            title=payload.title,
            group_kind=payload.group_kind,
            coordinator_agent_id=payload.coordinator_agent_id,
            member_agent_ids=tuple(payload.member_agent_ids),
            description=payload.description,
            lifecycle_state=payload.lifecycle_state,
            metadata={**payload.metadata, "managed_by": "orchestration_console"},
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await orchestration_agents()


@router.delete("/orchestration/agent-groups/{group_id}")
async def delete_orchestration_agent_group(group_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    try:
        AgentGroupRegistry(runtime.base_dir).delete_group(group_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Agent group not found") from exc
    return await orchestration_agents()


@router.post("/orchestration/body-preview")
async def orchestration_body_preview(payload: OrchestrationPreviewRequest) -> dict[str, Any]:
    runtime = require_runtime()
    agent_profile = runtime.query_runtime.agent_runtime_registry.get_profile("agent:0")
    chain = runtime.query_runtime.agent_runtime_chain.build_runtime(
        session_id=payload.session_id,
        task_id=payload.task_id,
        turn_id=payload.turn_id,
        message=payload.user_goal,
        source=payload.source,
        task_selection={"turn_id": payload.turn_id, **dict(payload.task_selection or {})},
        agent_runtime_profile=agent_profile,
    )
    task_operation = dict(chain.get("task_operation") or {})
    return {
        "authority": "orchestration.body_preview",
        "task_execution_assembly": dict(chain.get("task_execution_assembly") or task_operation.get("task_execution_assembly") or {}),
        "task_body_orchestration": dict(chain.get("task_body_orchestration") or task_operation.get("task_body_orchestration") or {}),
        "agent_body_profile": dict(task_operation.get("agent_body_profile") or {}),
        "prompt_structure_profile": dict(task_operation.get("prompt_structure_profile") or {}),
        "memory_scope_profile": dict(task_operation.get("memory_scope_profile") or {}),
        "runtime_lane_profile": dict(task_operation.get("runtime_lane_profile") or {}),
        "output_boundary_profile": dict(task_operation.get("output_boundary_profile") or {}),
        "memory_runtime_view": dict(chain.get("memory_runtime_view") or {}),
        "context_policy_result": dict(chain.get("context_policy_result") or {}),
    }


@router.post("/orchestration/runtime-spec-preview")
async def orchestration_runtime_spec_preview(payload: OrchestrationPreviewRequest) -> dict[str, Any]:
    runtime = require_runtime()
    agent_profile = runtime.query_runtime.agent_runtime_registry.get_profile("agent:0")
    chain = runtime.query_runtime.agent_runtime_chain.build_runtime(
        session_id=payload.session_id,
        task_id=payload.task_id,
        turn_id=payload.turn_id,
        message=payload.user_goal,
        source=payload.source,
        task_selection={"turn_id": payload.turn_id, **dict(payload.task_selection or {})},
        agent_runtime_profile=agent_profile,
    )
    task_operation = dict(chain.get("task_operation") or {})
    return {
        "authority": "orchestration.runtime_spec_preview",
        "task_execution_assembly": dict(chain.get("task_execution_assembly") or task_operation.get("task_execution_assembly") or {}),
        "task_body_orchestration": dict(chain.get("task_body_orchestration") or task_operation.get("task_body_orchestration") or {}),
        "agent_runtime_spec": dict(chain.get("agent_runtime_spec") or task_operation.get("agent_runtime_spec") or {}),
        "memory_runtime_view": dict(chain.get("memory_runtime_view") or {}),
        "context_policy_result": dict(chain.get("context_policy_result") or {}),
    }


@router.put("/orchestration/agents/{agent_id}/runtime-profile")
async def upsert_orchestration_agent_runtime_profile(
    agent_id: str,
    payload: AgentRuntimeProfileRequest,
) -> dict[str, Any]:
    runtime = require_runtime()
    try:
        AgentRuntimeRegistry(runtime.base_dir).upsert_profile(
            agent_id=agent_id,
            agent_profile_id=payload.agent_profile_id,
            enabled_runtime_modes=tuple(payload.enabled_runtime_modes),
            default_runtime_mode=payload.default_runtime_mode,
            allowed_runtime_lanes=tuple(payload.allowed_runtime_lanes),
            allowed_operations=tuple(payload.allowed_operations),
            blocked_operations=tuple(payload.blocked_operations),
            allowed_memory_scopes=tuple(payload.allowed_memory_scopes),
            allowed_context_sections=tuple(payload.allowed_context_sections),
            use_shared_contract=payload.use_shared_contract,
            can_delegate_to_agents=payload.can_delegate_to_agents,
            allowed_delegate_agent_ids=tuple(payload.allowed_delegate_agent_ids),
            max_delegate_calls_per_turn=payload.max_delegate_calls_per_turn,
            delegate_context_policy=payload.delegate_context_policy,
            approval_policy=payload.approval_policy,
            trace_policy=payload.trace_policy,
            lifecycle_policy=payload.lifecycle_policy,
            model_profile=payload.model_profile,
            metadata=payload.metadata,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await orchestration_agents()


@router.post("/orchestration/catalog/refresh")
async def refresh_orchestration_catalog() -> dict[str, Any]:
    runtime = require_runtime()
    runtime.refresh_catalogs()
    return await orchestration_catalog()


@router.get("/orchestration/delegation-catalog")
async def orchestration_delegation_catalog(parent_agent_id: str = "") -> dict[str, Any]:
    runtime = require_runtime()
    return DelegationCatalogBuilder(runtime.base_dir).build(parent_agent_id=parent_agent_id)


@router.post("/orchestration/delegation-catalog/preview")
async def orchestration_delegation_preview(payload: DelegationPreviewRequest) -> dict[str, Any]:
    runtime = require_runtime()
    return DelegationCatalogBuilder(runtime.base_dir).preview(
        parent_agent_id=payload.parent_agent_id,
        target_agent_id=payload.target_agent_id,
        delegation_kind=payload.delegation_kind,
    )


@router.put("/orchestration/plan-mode")
async def set_orchestration_plan_mode(payload: OrchestrationModeRequest) -> dict[str, Any]:
    runtime = require_runtime()
    config = runtime.settings.set_orchestration_plan_mode(payload.mode)
    return {
        "mode": str(config.get("orchestration_plan_mode", "primary") or "primary"),
        "supported_modes": ["primary"],
    }
