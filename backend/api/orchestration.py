from __future__ import annotations

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
    TaskContract,
    default_worker_agent_blueprints,
    build_base_unit_catalog,
)
from tasks import TaskFlowRegistry, TaskWorkflowRegistry
from tasks.definitions import default_task_definitions
from tasks.flow_registry import CONTRACT_TITLE_MAP

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
    output_contracts: list[str] = Field(default_factory=list)
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
    task_scope: list[str] = Field(default_factory=list)
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
    allowed_coordination_task_ids: list[str] = Field(default_factory=list)
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


OPTION_LABELS: dict[str, str] = {
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
    "AssistantFinalAnswer": "最终回答",
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
    definition_items = list(default_task_definitions().values())
    task_mode_labels = {
        str(item.task_mode): str(item.title)
        for item in definition_items
        if str(item.task_mode or "").strip()
    }
    task_mode_labels.update({
        str(item.task_mode): str(item.title)
        for item in workflows
        if str(item.task_mode or "").strip() and str(item.title or "").strip()
    })
    task_modes = sorted({
        *[item.task_mode for item in flow_items if item.task_mode],
        *[item.task_mode for item in workflows if item.task_mode],
        *[item.task_mode for item in definition_items if item.task_mode],
    })
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
    output_contracts = sorted(
        {
            *[item.output_contract_id for item in flow_items if item.output_contract_id],
            *[item.output_contract_id for item in workflows if item.output_contract_id],
            "AssistantFinalAnswer",
        }
    )
    contract_labels = {
        **CONTRACT_TITLE_MAP,
        **OPTION_LABELS,
    }
    contract_labels.update({
        item.contract_id: item.title
        for item in task_registry.list_contract_descriptors()
        if str(item.contract_id or "").strip()
    })
    approval_policies = ["default", "read_only_first", "manual_approval_required", "deny_destructive"]
    trace_policies = ["runtime_event_log", "full_trace", "minimal_trace"]
    return {
        **catalog,
        "agent_groups": [item.to_dict() for item in groups],
        "options": {
            "operations": [item.to_dict() for item in operations],
            "task_modes": task_modes,
            "runtime_lanes": runtime_lanes,
            "memory_scopes": memory_scopes,
            "context_sections": context_sections,
            "output_contracts": output_contracts,
            "approval_policies": approval_policies,
            "trace_policies": trace_policies,
            "operation_options": [_operation_option(item) for item in operations],
            "task_mode_options": [_option(item, label=_choice_label_from_map(item, task_mode_labels)) for item in task_modes],
            "runtime_lane_options": [_option(item, label=_choice_label_from_map(item, runtime_lane_labels)) for item in runtime_lanes],
            "memory_scope_options": [_option(item, label=_choice_label_from_map(item, memory_scope_labels)) for item in memory_scopes],
            "context_section_options": [_option(item) for item in context_sections],
            "output_contract_options": [_option(item, label=_choice_label_from_map(item, contract_labels)) for item in output_contracts],
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
            task_scope=tuple(payload.task_scope),
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
            allowed_coordination_task_ids=tuple(payload.allowed_coordination_task_ids),
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
            output_contracts=tuple(payload.output_contracts),
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


@router.put("/orchestration/plan-mode")
async def set_orchestration_plan_mode(payload: OrchestrationModeRequest) -> dict[str, Any]:
    runtime = require_runtime()
    config = runtime.settings.set_orchestration_plan_mode(payload.mode)
    return {
        "mode": str(config.get("orchestration_plan_mode", "primary") or "primary"),
        "supported_modes": ["primary"],
    }
