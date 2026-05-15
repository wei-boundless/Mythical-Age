from __future__ import annotations

import time
from typing import Any
from dataclasses import asdict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.deps import require_runtime
from capability_system import build_default_operation_registry
from orchestration import (
    AgentGroupRegistry,
    AgentRegistry,
    AgentRuntimeRegistry,
    ControlKernel,
    CoordinationRun,
    TaskContract,
    default_worker_agent_blueprints,
    build_base_unit_catalog,
)
from orchestration.runtime_loop import TaskRun
from orchestration.runtime_loop.langgraph_coordination_runtime import LangGraphCoordinationRuntimeResult
from orchestration.delegation_catalog import DelegationCatalogBuilder
from understanding import analyze_memory_intent
from tasks.coordination_graph_compiler import compile_task_graph_definition_runtime_spec
from tasks import TaskFlowRegistry, TaskWorkflowRegistry

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
    allowed_task_modes: list[str] = Field(default_factory=list)
    allowed_runtime_lanes: list[str] = Field(default_factory=list)
    allowed_operations: list[str] = Field(default_factory=list)
    blocked_operations: list[str] = Field(default_factory=list)
    allowed_memory_scopes: list[str] = Field(default_factory=list)
    allowed_context_sections: list[str] = Field(default_factory=list)
    use_shared_contract: bool = True
    output_contracts: list[str] = Field(default_factory=list)
    can_delegate_to_agents: bool = False
    allowed_delegate_agent_ids: list[str] = Field(default_factory=list)
    allowed_delegate_agent_categories: list[str] = Field(default_factory=lambda: ["worker_sub_agent"])
    max_delegate_calls_per_turn: int = Field(default=1, ge=0)
    delegate_context_policy: str = Field(default="summary_and_refs_only", max_length=120)
    approval_policy: str = Field(default="default", max_length=80)
    trace_policy: str = Field(default="runtime_event_log", max_length=120)
    lifecycle_policy: str = Field(default="orchestration_managed", max_length=120)
    metadata: dict[str, Any] = Field(default_factory=dict)


class OrchestrationAgentUpsertRequest(BaseModel):
    agent_id: str = Field(..., min_length=3, max_length=160)
    agent_name: str = Field(..., min_length=1, max_length=160)
    agent_category: str = Field(default="worker_sub_agent", max_length=80)
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
    default_topology_template_ids: list[str] = Field(default_factory=list)
    default_communication_protocol_ids: list[str] = Field(default_factory=list)
    allowed_task_graph_ids: list[str] = Field(default_factory=list)
    lifecycle_state: str = Field(default="enabled", max_length=80)
    metadata: dict[str, Any] = Field(default_factory=dict)


class OrchestrationPreviewRequest(BaseModel):
    session_id: str = Field(default="session-preview")
    turn_id: str = Field(default="turn:session-preview:1")
    task_id: str = Field(default="taskinst:turn:session-preview:1:general_response")
    user_goal: str = Field(..., min_length=1)
    source: str = Field(default="orchestration_preview")
    task_selection: dict[str, Any] = Field(default_factory=dict)


class CoordinationRunResumeRequest(BaseModel):
    resume_payload: dict[str, Any] = Field(default_factory=dict)


class TaskRunStopRequest(BaseModel):
    reason: str = Field(default="user_aborted", max_length=120)
    message: str = Field(default="", max_length=500)
    coordination_run_id: str = Field(default="", max_length=180)


class TaskGraphRunStartRequest(BaseModel):
    session_id: str = Field(default="session:task_graph_studio", max_length=180)
    task_id: str = Field(default="", max_length=180)
    initial_inputs: dict[str, Any] = Field(default_factory=dict)
    require_published: bool = True
    include_trace: bool = True
    execute_initial_stage: bool = True


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
    "op.analyze_multimodal_file": "分析多模态文件",
    "op.index_multimodal_file": "索引多模态文件",
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
    "assertions": "验收断言",
}

LEGACY_ORCHESTRATION_TASK_MODES = {
    "issue_triage",
    "trace_analysis",
    "case_draft",
    "fix_verification",
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


def _choice_label_from_map(value: str, labels: dict[str, str]) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return "未配置"
    return str(labels.get(normalized) or _option_label(normalized, normalized)).strip()


def _task_scope_option(value: str, *, label: str, description: str = "", source: str = "") -> dict[str, str]:
    option = _option(value, label=label, description=description)
    option["source"] = str(source or "").strip()
    return option


def _build_task_scope_options(task_registry: TaskFlowRegistry, workflows: list[Any]) -> tuple[list[str], list[dict[str, str]]]:
    options_by_value: dict[str, dict[str, str]] = {}

    def add(value: str, *, label: str, description: str = "", source: str = "") -> None:
        normalized = str(value or "").strip()
        if not normalized or normalized in options_by_value or normalized in LEGACY_ORCHESTRATION_TASK_MODES:
            return
        options_by_value[normalized] = _task_scope_option(
            normalized,
            label=label,
            description=description,
            source=source,
        )

    for domain in task_registry.list_task_domains():
        if not domain.enabled:
            continue
        add(
            domain.task_family,
            label=f"{_option_label(domain.task_family, domain.title)} · 任务域",
            description=domain.description or domain.domain_id,
            source="task_domain",
        )

    for record in task_registry.list_specific_task_records():
        if not record.enabled:
            continue
        add(
            record.task_mode,
            label=f"{_option_label(record.task_mode, record.task_title)} · 具体任务",
            description=record.task_id,
            source="specific_task",
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

    for workflow in workflows:
        if not getattr(workflow, "enabled", True):
            continue
        task_mode = str(getattr(workflow, "task_mode", "") or "").strip()
        if not task_mode:
            continue
        add(
            task_mode,
            label=f"{_option_label(task_mode, str(getattr(workflow, 'title', task_mode) or task_mode))} · 工作流",
            description=str(getattr(workflow, "workflow_id", "") or ""),
            source="workflow",
        )

    options = sorted(options_by_value.values(), key=lambda item: (item.get("source", ""), item["label"], item["value"]))
    return [item["value"] for item in options], options


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
        "tool_contract_mode": runtime.query_runtime.tool_contract_gate.mode,
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
    task_registry = TaskFlowRegistry(runtime.base_dir)
    operations = build_default_operation_registry().list_operations()
    workflows = TaskWorkflowRegistry(runtime.base_dir).list_workflows()
    flow_items = task_registry.list_flows()
    task_scopes, task_scope_options = _build_task_scope_options(task_registry, workflows)
    runtime_lane_labels = {
        "main_conversation": "主会话通道",
        "general_task": "通用任务通道",
        "workspace_task": "工作区任务通道",
        "coordination_task": "协调任务通道",
        "health_task": "健康任务通道",
    }
    runtime_lanes = sorted({item.default_runtime_lane for item in flow_items if item.default_runtime_lane})
    memory_scope_labels = {
        "session_read": "会话只读记忆",
        "session_working_set": "会话工作记忆",
        "workspace_context": "工作区上下文",
        "health_case_memory": "健康案例记忆",
    }
    memory_scopes = sorted({item.default_memory_scope for item in flow_items if item.default_memory_scope})
    context_sections = [
        "conversation",
        "state",
        "task",
        "projection",
        "tool",
        "health_issue",
        "runtime_trace",
        "prompt_manifest",
        "memory_runtime_view",
        "assertions",
    ]
    approval_policies = ["default", "read_only_first", "manual_approval_required", "deny_destructive"]
    trace_policies = ["runtime_event_log", "full_trace", "minimal_trace"]
    return {
        **catalog,
        "agent_groups": [item.to_dict() for item in groups],
        "options": {
            "operations": [item.to_dict() for item in operations],
            "task_modes": task_scopes,
            "runtime_lanes": runtime_lanes,
            "memory_scopes": memory_scopes,
            "context_sections": context_sections,
            "approval_policies": approval_policies,
            "trace_policies": trace_policies,
            "operation_options": [_operation_option(item) for item in operations],
            "task_mode_options": task_scope_options,
            "runtime_lane_options": [_option(item, label=_choice_label_from_map(item, runtime_lane_labels)) for item in runtime_lanes],
            "memory_scope_options": [_option(item, label=_choice_label_from_map(item, memory_scope_labels)) for item in memory_scopes],
            "context_section_options": [_option(item) for item in context_sections],
            "approval_policy_options": [_option(item) for item in approval_policies],
            "trace_policy_options": [_option(item) for item in trace_policies],
            "worker_blueprints": [item.to_dict() for item in default_worker_agent_blueprints()],
        },
    }


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
            default_topology_template_ids=tuple(payload.default_topology_template_ids),
            default_communication_protocol_ids=tuple(payload.default_communication_protocol_ids),
            allowed_task_graph_ids=tuple(payload.allowed_task_graph_ids),
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
            allowed_task_modes=tuple(payload.allowed_task_modes),
            allowed_runtime_lanes=tuple(payload.allowed_runtime_lanes),
            allowed_operations=tuple(payload.allowed_operations),
            blocked_operations=tuple(payload.blocked_operations),
            allowed_memory_scopes=tuple(payload.allowed_memory_scopes),
            allowed_context_sections=tuple(payload.allowed_context_sections),
            use_shared_contract=payload.use_shared_contract,
            output_contracts=tuple(payload.output_contracts),
            can_delegate_to_agents=payload.can_delegate_to_agents,
            allowed_delegate_agent_ids=tuple(payload.allowed_delegate_agent_ids),
            allowed_delegate_agent_categories=tuple(payload.allowed_delegate_agent_categories),
            max_delegate_calls_per_turn=payload.max_delegate_calls_per_turn,
            delegate_context_policy=payload.delegate_context_policy,
            approval_policy=payload.approval_policy,
            trace_policy=payload.trace_policy,
            lifecycle_policy=payload.lifecycle_policy,
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


@router.get("/orchestration/runtime-loop/sessions/{session_id}/task-runs")
async def list_runtime_loop_task_runs(session_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    return runtime.query_runtime.task_run_loop.list_session_traces(session_id)


@router.get("/orchestration/runtime-loop/task-runs/{task_run_id}")
async def get_runtime_loop_trace(
    task_run_id: str,
    include_payloads: bool = False,
    include_model_messages: bool = False,
) -> dict[str, Any]:
    runtime = require_runtime()
    trace = runtime.query_runtime.task_run_loop.get_trace(
        task_run_id,
        include_payloads=include_payloads,
        include_model_messages=include_model_messages,
    )
    if trace is None:
        raise HTTPException(status_code=404, detail="TaskRun trace not found")
    return trace


@router.post("/orchestration/runtime-loop/task-graphs/{graph_id}/start")
async def start_task_graph_runtime_loop_run(
    graph_id: str,
    payload: TaskGraphRunStartRequest,
) -> dict[str, Any]:
    runtime = require_runtime()
    registry = TaskFlowRegistry(runtime.base_dir)
    graph = registry.get_task_graph(graph_id)
    if graph is None:
        raise HTTPException(status_code=404, detail="TaskGraph not found")
    if payload.require_published and graph.publish_state != "published":
        raise HTTPException(status_code=409, detail="TaskGraph must be published before run start")
    protocol = registry.get_task_communication_protocol(
        str(graph.default_protocol_id or dict(graph.metadata or {}).get("protocol_id") or "")
    )
    runtime_spec = compile_task_graph_definition_runtime_spec(
        graph=graph,
        specific_tasks=tuple(registry.list_specific_task_records()),
        communication_protocol=protocol,
    )
    blocking_issues = [issue.to_dict() for issue in runtime_spec.issues if issue.severity == "error"]
    if blocking_issues:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "TaskGraph runtime spec has blocking issues",
                "issues": blocking_issues,
            },
        )
    session_id = payload.session_id.strip() or "session:task_graph_studio"
    start = runtime.query_runtime.task_run_loop.start_task_graph_run(
        session_id=session_id,
        task_id=payload.task_id.strip(),
        graph=graph,
        runtime_spec=runtime_spec,
        initial_inputs=dict(payload.initial_inputs or {}),
        diagnostics={
            "source": "orchestration.runtime_loop.task_graph_start_api",
            "require_published": payload.require_published,
        },
    )
    stage_execution_request = dict(start.loop_state.diagnostics.get("stage_execution_request") or {})
    initial_stage_execution_events: list[dict[str, Any]] = []
    initial_stage_execution_error: dict[str, Any] | None = None
    if payload.execute_initial_stage and stage_execution_request:
        from orchestration.runtime_loop.stage_execution_request import StageExecutionRequest

        request = StageExecutionRequest.from_dict(stage_execution_request)
        continuation_payload = LangGraphCoordinationRuntimeResult(
            stage_execution_request=request,
        ).continuation_payload(
            session_id=session_id,
            current_turn_context={
                "authority": "context.task_graph_start",
                "task_graph_id": graph.graph_id,
                "selected_graph_id": graph.graph_id,
                "explicit_inputs": dict(payload.initial_inputs or {}),
            },
        )
        try:
            async for event in runtime.query_runtime.task_run_loop._continue_coordination_delivery_stream(
                session_id=session_id,
                history=runtime.query_runtime.session_manager.load_session_for_agent(
                    session_id,
                    include_compressed_context=False,
                ),
                source="orchestration.runtime_loop.task_graph_start_api",
                agent_runtime_chain=runtime.query_runtime.agent_runtime_chain,
                model_response_executor=runtime.query_runtime.model_response_executor,
                runtime_context_manager=runtime.query_runtime.runtime_context_manager,
                stage_projection_cycle=None,
                memory_intent=analyze_memory_intent(request.message),
                assistant_message_committer=lambda _payload: None,
                tool_runtime_executor=runtime.query_runtime.tool_runtime_executor,
                tool_instances=runtime.query_runtime._all_tool_instances(),
                agent_runtime_profile=runtime.query_runtime.agent_runtime_registry.get_profile(request.agent_id),
                continuation_payload=continuation_payload,
            ):
                initial_stage_execution_events.append(dict(event))
        except Exception as exc:
            initial_stage_execution_error = {
                "error": str(exc),
                "type": exc.__class__.__name__,
            }
    return {
        "authority": "orchestration.task_graph_run_start",
        "graph_id": graph.graph_id,
        "task_run_id": start.task_run.task_run_id,
        "coordination_run_id": start.coordination_run.coordination_run_id if start.coordination_run is not None else "",
        "task_run": start.task_run.to_dict(),
        "coordination_run": start.coordination_run.to_dict() if start.coordination_run is not None else None,
        "checkpoint": start.checkpoint.to_dict(),
        "runtime_spec": runtime_spec.to_dict(),
        "stage_execution_request": stage_execution_request or None,
        "initial_stage_execution_events": initial_stage_execution_events,
        "initial_stage_execution_event_count": len(initial_stage_execution_events),
        "initial_stage_execution_error": initial_stage_execution_error,
        "trace": (
            runtime.query_runtime.task_run_loop.get_trace(start.task_run.task_run_id)
            if payload.include_trace
            else None
        ),
        "events": [dict(item) for item in start.events],
    }


@router.post("/orchestration/coordination-runs/{coordination_run_id}/resume")
async def resume_coordination_run(
    coordination_run_id: str,
    payload: CoordinationRunResumeRequest,
) -> dict[str, Any]:
    runtime = require_runtime()
    result = runtime.query_runtime.task_run_loop.langgraph_coordination_runtime.resume_human_gate(
        coordination_run_id=coordination_run_id,
        resume_payload=dict(payload.resume_payload or {}),
    )
    if result.diagnostics.get("reason") == "missing_coordination_run":
        raise HTTPException(status_code=404, detail="CoordinationRun not found")
    if result.diagnostics.get("reason") == "missing_checkpoint":
        raise HTTPException(status_code=409, detail="CoordinationRun has no LangGraph checkpoint")
    return {
        "authority": "orchestration.coordination_run_resume",
        "coordination_run_id": coordination_run_id,
        "checkpoint_ref": result.checkpoint_ref,
        "diagnostics": dict(result.diagnostics),
        "stage_execution_request": (
            result.stage_execution_request.to_dict()
            if result.stage_execution_request is not None
            else None
        ),
        "events": [
            event.to_dict() if hasattr(event, "to_dict") else dict(event)
            for event in result.events
        ],
    }


@router.post("/orchestration/runtime-loop/task-runs/{task_run_id}/stop")
async def stop_task_run(
    task_run_id: str,
    payload: TaskRunStopRequest,
) -> dict[str, Any]:
    try:
        runtime = require_runtime()
        task_run_loop = runtime.query_runtime.task_run_loop
        state_index = task_run_loop.state_index
        task_run = state_index.get_task_run(task_run_id)
        if task_run is None:
            raise HTTPException(status_code=404, detail="TaskRun not found")
        coordination_run_id = payload.coordination_run_id.strip()
        coordination_run = (
            state_index.get_coordination_run(coordination_run_id)
            if coordination_run_id
            else None
        )
        checkpoint = task_run_loop.checkpoints.load_latest(task_run_id)
        if checkpoint is None:
            raise HTTPException(status_code=409, detail="TaskRun has no checkpoint to stop from")
        terminal_reason = "user_aborted" if payload.reason.strip() == "user_aborted" else payload.reason.strip() or "user_aborted"
        loop_state = checkpoint.loop_state.with_status(
            "aborted",
            transition="stop_after_final_output",
            terminal_reason=terminal_reason,
            diagnostics={
                **dict(checkpoint.loop_state.diagnostics),
                "stop_request": {
                    "reason": terminal_reason,
                    "message": payload.message.strip(),
                    "stopped_at": time.time(),
                },
            },
        )
        checkpoint_event = task_run_loop._write_checkpoint_event(loop_state, event_offset=checkpoint.event_offset)
        task_run_event = task_run_loop.event_log.append(
            task_run_id,
            "task_run_stopped",
            payload={
                "task_run_id": task_run_id,
                "reason": terminal_reason,
                "message": payload.message.strip(),
                "coordination_run_id": coordination_run.coordination_run_id if coordination_run is not None else "",
                "checkpoint_ref": checkpoint_event.refs.get("checkpoint_ref") or checkpoint.checkpoint_id,
            },
            refs={
                "task_run_ref": task_run_id,
                "checkpoint_ref": checkpoint_event.refs.get("checkpoint_ref") or checkpoint.checkpoint_id,
                "coordination_run_ref": coordination_run.coordination_run_id if coordination_run is not None else "",
            },
        )
        state_index.upsert_task_run(
            TaskRun(
                task_run_id=task_run.task_run_id,
                session_id=task_run.session_id,
                task_id=task_run.task_id,
                task_contract_ref=task_run.task_contract_ref,
                owner_agent_seat_id=task_run.owner_agent_seat_id,
                agent_id=task_run.agent_id,
                agent_profile_id=task_run.agent_profile_id,
                runtime_lane=task_run.runtime_lane,
                status="aborted",
                created_at=task_run.created_at,
                updated_at=time.time(),
                latest_event_offset=checkpoint_event.offset,
                latest_checkpoint_ref=str(checkpoint_event.refs.get("checkpoint_ref") or checkpoint.checkpoint_id),
                terminal_reason=terminal_reason,  # type: ignore[arg-type]
                diagnostics={
                    **dict(task_run.diagnostics),
                    "stop_request": {"reason": terminal_reason, "message": payload.message.strip()},
                },
            )
        )
        if coordination_run is not None:
            state_index.upsert_coordination_run(
                CoordinationRun(
                    coordination_run_id=coordination_run.coordination_run_id,
                    task_run_id=coordination_run.task_run_id,
                    graph_ref=coordination_run.graph_ref,
                    coordinator_agent_id=coordination_run.coordinator_agent_id,
                    topology_template_id=coordination_run.topology_template_id,
                    communication_protocol_id=coordination_run.communication_protocol_id,
                    handoff_policy=coordination_run.handoff_policy,
                    failure_policy=coordination_run.failure_policy,
                    merge_policy=coordination_run.merge_policy,
                    status="aborted",
                    latest_checkpoint_ref=str(checkpoint_event.refs.get("checkpoint_ref") or checkpoint.checkpoint_id),
                    latest_merge_result_ref=coordination_run.latest_merge_result_ref,
                    created_at=coordination_run.created_at,
                    updated_at=time.time(),
                    diagnostics={
                        **dict(coordination_run.diagnostics),
                        "stop_request": {"reason": terminal_reason, "message": payload.message.strip()},
                    },
                )
            )
        return {
            "authority": "orchestration.task_run_stop",
            "task_run_id": task_run_id,
            "reason": terminal_reason,
            "checkpoint_ref": str(checkpoint_event.refs.get("checkpoint_ref") or checkpoint.checkpoint_id),
            "event_ref": task_run_event.event_id,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"task_run_stop_failed: {exc}") from exc


@router.put("/orchestration/plan-mode")
async def set_orchestration_plan_mode(payload: OrchestrationModeRequest) -> dict[str, Any]:
    runtime = require_runtime()
    config = runtime.settings.set_orchestration_plan_mode(payload.mode)
    return {
        "mode": str(config.get("orchestration_plan_mode", "primary") or "primary"),
        "supported_modes": ["primary"],
    }
