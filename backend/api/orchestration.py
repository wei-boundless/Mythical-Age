from __future__ import annotations

import asyncio
import re
import threading
import time
from typing import Any
from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.deps import require_runtime
from capability_system import build_default_operation_registry
from capability_system import build_capability_catalog, build_orchestration_capability_items
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
from orchestration.runtime_lane_registry import DEFAULT_RUNTIME_LANE_REGISTRY, runtime_lane_option_payloads
from orchestration.runtime_loop import TaskRun
from orchestration.runtime_loop.langgraph_coordination_runtime import LangGraphCoordinationRuntimeResult
from orchestration.delegation_catalog import DelegationCatalogBuilder
from understanding import analyze_memory_intent
from tasks.coordination_graph_compiler import compile_task_graph_definition_runtime_spec
from tasks import TaskFlowRegistry
from sessions import InvalidSessionId, validate_session_id

router = APIRouter()


async def _execute_stage_request_in_background(
    *,
    runtime: Any,
    session_id: str,
    source: str,
    stage_execution_request: Any,
    current_turn_context: dict[str, Any] | None = None,
) -> None:
    continuation_payload = LangGraphCoordinationRuntimeResult(
        stage_execution_request=stage_execution_request,
    ).continuation_payload(
        session_id=session_id,
        current_turn_context=dict(current_turn_context or {}),
    )
    if not continuation_payload:
        return
    async for _event in runtime.query_runtime.task_run_loop._continue_coordination_delivery_stream(
        session_id=session_id,
        history=runtime.query_runtime.session_manager.load_session_for_agent(
            session_id,
            include_compressed_context=False,
        ),
        source=source,
        agent_runtime_chain=runtime.query_runtime.agent_runtime_chain,
        model_response_executor=runtime.query_runtime.model_response_executor,
        runtime_context_manager=runtime.query_runtime.runtime_context_manager,
        stage_projection_cycle=None,
        memory_intent=analyze_memory_intent(stage_execution_request.message),
        assistant_message_committer=lambda _payload: None,
        tool_runtime_executor=runtime.query_runtime.tool_runtime_executor,
        tool_instances=runtime.query_runtime._all_tool_instances(),
        agent_runtime_profile=runtime.query_runtime.agent_runtime_registry.get_profile(stage_execution_request.agent_id),
        continuation_payload=continuation_payload,
    ):
        pass


def _schedule_stage_execution_background(
    *,
    runtime: Any,
    session_id: str,
    source: str,
    stage_execution_request: Any,
    current_turn_context: dict[str, Any] | None = None,
) -> None:
    def runner() -> None:
        try:
            asyncio.run(
                _execute_stage_request_in_background(
                    runtime=runtime,
                    session_id=session_id,
                    source=source,
                    stage_execution_request=stage_execution_request,
                    current_turn_context=current_turn_context,
                )
            )
        except Exception as exc:
            runtime.query_runtime.task_run_loop.event_log.append(
                stage_execution_request.root_task_run_id,
                "coordination_stage_background_execution_failed",
                payload={
                    "coordination_run_id": stage_execution_request.coordination_run_id,
                    "stage_id": stage_execution_request.stage_id,
                    "task_ref": stage_execution_request.task_ref,
                    "error": str(exc),
                    "error_type": exc.__class__.__name__,
                    "source": source,
                },
                refs={
                    "coordination_run_ref": stage_execution_request.coordination_run_id,
                    "stage_id": stage_execution_request.stage_id,
                },
            )

    thread = threading.Thread(
        target=runner,
        name=f"taskgraph-node-{str(stage_execution_request.stage_id or 'unknown')}",
        daemon=True,
    )
    thread.start()


def _sanitize_replayed_writing_stage_request_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Clean stale chapter revision fields before replaying a persisted stage request."""
    if str(payload.get("stage_id") or payload.get("node_id") or "").strip() != "chapter_draft":
        return payload
    explicit_inputs = dict(payload.get("explicit_inputs") or {})
    if explicit_inputs.get("revision_required") is not True and "chapter_revision_requirements" not in explicit_inputs:
        return payload

    sanitized_inputs = _sanitize_writing_chapter_revision_inputs(explicit_inputs)
    sanitized = dict(payload)
    sanitized["explicit_inputs"] = sanitized_inputs
    sanitized["request_id"] = ""
    sanitized["idempotency_key"] = ""
    sanitized["a2a_payload"] = _replace_nested_explicit_inputs(
        dict(sanitized.get("a2a_payload") or {}),
        sanitized_inputs,
    )
    sanitized["runtime_assembly"] = _replace_nested_explicit_inputs(
        dict(sanitized.get("runtime_assembly") or {}),
        sanitized_inputs,
    )
    return sanitized


def _sanitize_writing_chapter_revision_inputs(explicit_inputs: dict[str, Any]) -> dict[str, Any]:
    inputs = dict(explicit_inputs)
    artifact_root = Path(str(inputs.get("artifact_root") or ""))
    batch_dir_name = _writing_batch_dir_name(inputs)

    latest_review_ref = _latest_artifact_ref(
        artifact_root / "reviews" / "chapters" / batch_dir_name,
        "review_round_*.md",
    )
    latest_draft_ref = _latest_artifact_ref(
        artifact_root / "chapters" / batch_dir_name,
        "draft_round_*.md",
    )
    if latest_review_ref:
        inputs["previous_chapter_review_ref"] = latest_review_ref
    if latest_draft_ref:
        inputs["previous_chapter_draft_ref"] = latest_draft_ref

    batch_start = _safe_int(inputs.get("batch_start_index") or inputs.get("chapter_index"), 1)
    batch_end = _safe_int(inputs.get("batch_end_index"), batch_start)
    chapters_per_round = _safe_int(inputs.get("chapters_per_round") or inputs.get("chapter_batch_size"), 10)
    chapter_target_words = _safe_int(inputs.get("chapter_target_words"), 2000)
    batch_chapter_numbers = list(range(batch_start, batch_end + 1))
    inputs["batch_chapter_numbers"] = batch_chapter_numbers
    inputs["batch_chapter_list"] = "、".join(f"第{i}章" for i in batch_chapter_numbers)
    review_hint = ""
    review_text = _read_artifact_text(latest_review_ref)
    if review_text:
        review_hint = "\n最新审核意见摘要：\n" + _compact_review_text(review_text, max_chars=6000)
    inputs["chapter_revision_requirements"] = (
        f"第{batch_start}章至第{batch_end}章上一轮审核未通过。"
        f"本轮必须严格依据最新审核意见重写完整批次，共{chapters_per_round}章；"
        f"每章约{chapter_target_words}字，只输出完整正文，不要输出摘要、提纲、解释、拒绝、等待补充或工作说明。"
        f"{review_hint}"
    )
    inputs["revision_required"] = True
    inputs["force_replay"] = True
    inputs["force_replay_after"] = time.time()
    inputs.pop("contract.writing.simple_novel.chapter_draft:artifact_refs", None)
    inputs.pop("previous_quality_failure_stage_id", None)
    return inputs


def _replace_nested_explicit_inputs(value: Any, explicit_inputs: dict[str, Any]) -> Any:
    if isinstance(value, dict):
        replaced: dict[str, Any] = {}
        for key, child in value.items():
            if key == "explicit_inputs" and isinstance(child, dict):
                replaced[key] = dict(explicit_inputs)
            else:
                replaced[key] = _replace_nested_explicit_inputs(child, explicit_inputs)
        return replaced
    if isinstance(value, list):
        return [_replace_nested_explicit_inputs(item, explicit_inputs) for item in value]
    return value


def _writing_batch_dir_name(inputs: dict[str, Any]) -> str:
    batch_index = _safe_int(inputs.get("batch_index"), 1)
    batch_start = _safe_int(inputs.get("batch_start_index") or inputs.get("chapter_index"), 1)
    batch_end = _safe_int(inputs.get("batch_end_index"), batch_start)
    return f"batch_{batch_index:03d}_chapters_{batch_start:03d}_{batch_end:03d}"


def _latest_artifact_ref(directory: Path, pattern: str) -> str:
    if not directory.exists() or not directory.is_dir():
        return ""
    files = [path for path in directory.glob(pattern) if path.is_file()]
    if not files:
        return ""
    latest = max(files, key=lambda path: path.stat().st_mtime)
    return f"artifact:{latest.as_posix()}"


def _read_artifact_text(artifact_ref: str, *, max_chars: int = 8000) -> str:
    path_text = str(artifact_ref or "")
    if path_text.startswith("artifact:"):
        path_text = path_text[len("artifact:") :]
    if not path_text:
        return ""
    path = Path(path_text)
    if not path.exists() or not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")[:max_chars]
    except OSError:
        return ""


def _compact_review_text(text: str, *, max_chars: int = 3000) -> str:
    raw = str(text or "").strip()
    sections = _extract_named_review_sections(
        raw,
        section_names=(
            "裁决",
            "裁决理由",
            "阻塞问题",
            "非阻塞问题",
            "下一轮修改要求",
            "canon一致性检查",
            "承接与推进检查",
            "商业阅读体验检查",
            "爽点与章末追读检查",
        ),
    )
    if sections:
        compact = "\n\n".join(sections)
    else:
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        important = [
            line
            for line in lines
            if any(
                marker in line
                for marker in (
                    "阻塞",
                    "修改",
                    "问题",
                    "必须",
                    "裁决",
                    "verdict",
                    "revise",
                    "未通过",
                    "断裂",
                    "失衡",
                    "过于简单",
                    "不允许",
                )
            )
        ]
        compact = "\n".join(important or lines)
    return compact[:max_chars]


def _extract_named_review_sections(text: str, *, section_names: tuple[str, ...]) -> list[str]:
    sections: list[tuple[str, list[str]]] = []
    current_name = ""
    current_lines: list[str] = []
    for line in str(text or "").splitlines():
        stripped = line.strip()
        matched_name = ""
        for name in section_names:
            if stripped.startswith(f"【{name}】"):
                matched_name = name
                break
        if matched_name:
            if current_name and current_lines:
                sections.append((current_name, current_lines))
            current_name = matched_name
            current_lines = [stripped]
            continue
        if current_name:
            if stripped.startswith("【") and stripped.endswith("】"):
                if current_lines:
                    sections.append((current_name, current_lines))
                current_name = ""
                current_lines = []
            else:
                current_lines.append(line)
    if current_name and current_lines:
        sections.append((current_name, current_lines))
    wanted = set(section_names)
    return ["\n".join(lines).strip() for name, lines in sections if name in wanted and "\n".join(lines).strip()]


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class BehaviorDryRunRequest(BaseModel):
    session_id: str
    message: str = Field(..., min_length=1)
    ephemeral_system_messages: list[str] = Field(default_factory=list)
    explicit_subtasks: list[dict[str, Any]] = Field(default_factory=list)


class OrchestrationModeRequest(BaseModel):
    mode: str = Field(default="primary")


class AgentRuntimeProfileRequest(BaseModel):
    agent_profile_id: str = Field(default="", max_length=160)
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


class CoordinationRunResumeRequest(BaseModel):
    resume_payload: dict[str, Any] = Field(default_factory=dict)


class CoordinationRunContinueRequest(BaseModel):
    source: str = Field(default="orchestration.coordination_run_continue_api", max_length=180)
    current_turn_context: dict[str, Any] = Field(default_factory=dict)


class TaskRunStopRequest(BaseModel):
    reason: str = Field(default="user_aborted", max_length=120)
    message: str = Field(default="", max_length=500)
    coordination_run_id: str = Field(default="", max_length=180)


class TaskGraphRunStartRequest(BaseModel):
    session_id: str = Field(default="task_graph_studio", max_length=180)
    task_id: str = Field(default="", max_length=180)
    initial_inputs: dict[str, Any] = Field(default_factory=dict)
    require_published: bool = True
    include_trace: bool = True
    execute_initial_stage: bool = True


class TaskGraphMonitorEvaluateRequest(BaseModel):
    monitor_node_id: str = Field(default="", max_length=180)
    monitor_policy: dict[str, Any] = Field(default_factory=dict)


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


def _choice_label_from_map(value: str, labels: dict[str, str]) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return "未配置"
    return str(labels.get(normalized) or _option_label(normalized, normalized)).strip()


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
    return {
        **catalog,
        "agent_groups": [item.to_dict() for item in groups],
        "options": _empty_orchestration_runtime_options(),
    }


def _empty_orchestration_runtime_options() -> dict[str, Any]:
    return {
        "operations": [],
        "task_graphs": [],
        "runtime_lanes": [],
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


@router.get("/orchestration/runtime-loop/sessions/{session_id}/live-monitor")
async def get_runtime_loop_session_live_monitor(session_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    return runtime.query_runtime.task_run_loop.get_session_live_monitor(session_id)


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


@router.get("/orchestration/runtime-loop/task-runs/{task_run_id}/live-monitor")
async def get_runtime_loop_task_run_live_monitor(task_run_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    monitor = runtime.query_runtime.task_run_loop.get_task_run_live_monitor(task_run_id)
    if monitor is None:
        raise HTTPException(status_code=404, detail="TaskRun live monitor not found")
    return monitor


@router.get("/orchestration/runtime-loop/task-runs/{task_run_id}/task-graph-monitor")
async def get_runtime_loop_task_graph_run_monitor(task_run_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    monitor = runtime.query_runtime.task_run_loop.get_task_graph_run_monitor(task_run_id)
    if monitor is None:
        raise HTTPException(status_code=404, detail="TaskGraph run monitor not found")
    return monitor


@router.post("/orchestration/runtime-loop/task-runs/{task_run_id}/task-graph-monitor/evaluate")
async def evaluate_runtime_loop_task_graph_monitor(
    task_run_id: str,
    payload: TaskGraphMonitorEvaluateRequest,
) -> dict[str, Any]:
    runtime = require_runtime()
    evaluation = runtime.query_runtime.task_run_loop.evaluate_task_graph_monitor(
        task_run_id,
        monitor_node_id=payload.monitor_node_id.strip(),
        monitor_policy=dict(payload.monitor_policy or {}),
    )
    if evaluation is None:
        raise HTTPException(status_code=404, detail="TaskGraph run monitor not found")
    return evaluation


@router.get("/orchestration/runtime-loop/task-runs/{task_run_id}/monitor-decisions")
async def list_runtime_loop_task_graph_monitor_decisions(task_run_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    return runtime.query_runtime.task_run_loop.list_task_graph_monitor_decisions(task_run_id)


@router.get("/orchestration/runtime-loop/task-runs/{task_run_id}/artifacts")
async def get_runtime_loop_task_run_artifacts(task_run_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    return runtime.query_runtime.task_run_loop.get_task_run_artifacts(task_run_id)


@router.get("/orchestration/runtime-loop/task-runs/{task_run_id}/memory-receipts")
async def get_runtime_loop_task_run_memory_receipts(task_run_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    return runtime.query_runtime.task_run_loop.get_task_run_memory_receipts(task_run_id)


@router.get("/orchestration/projects/{project_id}/runtime-status")
async def get_project_runtime_status(project_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    status = runtime.query_runtime.task_run_loop.get_project_runtime_status(project_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Project runtime status not found")
    return status


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
    session_id = payload.session_id.strip() or "task_graph_studio"
    try:
        session_id = validate_session_id(session_id or "task_graph_studio")
    except InvalidSessionId as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
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
    initial_stage_execution_background = False
    if payload.execute_initial_stage and stage_execution_request:
        from orchestration.runtime_loop.node_execution_request import NodeExecutionRequest

        request = NodeExecutionRequest.from_dict(stage_execution_request)
        try:
            _schedule_stage_execution_background(
                runtime=runtime,
                session_id=session_id,
                source="orchestration.runtime_loop.task_graph_start_api",
                stage_execution_request=request,
                current_turn_context={
                    "authority": "context.task_graph_start",
                    "task_graph_id": graph.graph_id,
                    "selected_graph_id": graph.graph_id,
                    "explicit_inputs": dict(payload.initial_inputs or {}),
                },
            )
            initial_stage_execution_background = True
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
        "initial_stage_execution_background": initial_stage_execution_background,
        "trace": (
            runtime.query_runtime.task_run_loop.get_trace(start.task_run.task_run_id)
            if payload.include_trace
            else None
        ),
        "events": [dict(item) for item in start.events],
    }


@router.get("/orchestration/coordination-runs/{coordination_run_id}/task-graph-monitor")
async def get_coordination_run_task_graph_monitor(coordination_run_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    monitor = runtime.query_runtime.task_run_loop.get_coordination_run_monitor(coordination_run_id)
    if monitor is None:
        raise HTTPException(status_code=404, detail="CoordinationRun task graph monitor not found")
    return monitor


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


@router.post("/orchestration/coordination-runs/{coordination_run_id}/continue-current-stage")
async def continue_coordination_current_stage(
    coordination_run_id: str,
    payload: CoordinationRunContinueRequest,
) -> dict[str, Any]:
    from orchestration.runtime_loop.node_execution_request import NodeExecutionRequest, NodeResultReadyEvent

    runtime = require_runtime()
    coordination_run = runtime.query_runtime.task_run_loop.state_index.get_coordination_run(coordination_run_id)
    if coordination_run is None:
        raise HTTPException(status_code=404, detail="CoordinationRun not found")
    state = runtime.query_runtime.task_run_loop.langgraph_coordination_runtime.checkpoints.get_state(
        thread_id=coordination_run_id,
    )
    if not state:
        raise HTTPException(status_code=409, detail="CoordinationRun has no LangGraph checkpoint")
    task_run = runtime.query_runtime.task_run_loop.state_index.get_task_run(coordination_run.task_run_id)
    session_id = str(getattr(task_run, "session_id", "") or "").strip()
    if not session_id:
        raise HTTPException(status_code=409, detail="CoordinationRun root TaskRun has no session_id")

    current_event = dict(state.get("current_event") or {})
    current_stage_payload = dict(state.get("stage_execution_request") or {})
    active_stage_id = str(
        state.get("active_stage_id")
        or current_stage_payload.get("stage_id")
        or ""
    ).strip()
    current_event_stage_id = str(current_event.get("stage_id") or "").strip()
    current_event_task_run_id = str(current_event.get("task_run_id") or "").strip()
    current_stage_result_task_run_id = str(
        dict(dict(state.get("stage_results") or {}).get(active_stage_id) or {}).get("task_run_id") or ""
    ).strip()
    current_event_is_active_stage_result = bool(
        str(current_event.get("event_type") or "") == "task_result_ready"
        and active_stage_id
        and current_event_stage_id == active_stage_id
        and current_event_task_run_id
        and current_event_task_run_id == current_stage_result_task_run_id
    )
    latest_unconsumed_stage_result = (
        {}
        if current_event_is_active_stage_result
        else _latest_unconsumed_stage_task_result(
            runtime=runtime,
            session_id=session_id,
            state=state,
            active_stage_id=active_stage_id,
            coordination_run_id=coordination_run_id,
        )
    )
    if latest_unconsumed_stage_result:
        resume_event = NodeResultReadyEvent(**latest_unconsumed_stage_result["event"])
        result = runtime.query_runtime.task_run_loop.langgraph_coordination_runtime.resume_from_task_result(
            coordination_run=coordination_run,
            event=resume_event,
            current_task_result=dict(latest_unconsumed_stage_result.get("task_result") or {}),
            inherited_inputs=dict(latest_unconsumed_stage_result.get("explicit_inputs") or {}),
            artifact_root=str(latest_unconsumed_stage_result.get("artifact_root") or ""),
        )
        request = result.stage_execution_request
        if request is not None:
            _schedule_stage_execution_background(
                runtime=runtime,
                session_id=session_id,
                source=payload.source or "orchestration.coordination_run_continue_api",
                stage_execution_request=request,
                current_turn_context={
                    "authority": "context.coordination_run_continue",
                    "coordination_run_id": coordination_run_id,
                    "task_graph_id": coordination_run.graph_ref,
                    "selected_graph_id": coordination_run.graph_ref,
                    **dict(payload.current_turn_context or {}),
                },
            )
        return {
            "authority": "orchestration.coordination_run_continue_current_stage",
            "coordination_run_id": coordination_run_id,
            "task_run_id": coordination_run.task_run_id,
            "session_id": session_id,
            "stage_execution_request": request.to_dict() if request is not None else None,
            "background_started": request is not None,
            "mode": "resumed_from_unconsumed_stage_task_result",
            "consumed_task_run_id": str(latest_unconsumed_stage_result.get("task_run_id") or ""),
        }
    if current_stage_payload and _stage_request_matches_active_stage(
        state=state,
        request_payload=current_stage_payload,
        active_stage_id=active_stage_id,
    ):
        request = NodeExecutionRequest.from_dict(
            _sanitize_replayed_writing_stage_request_payload(current_stage_payload)
        )
        current_turn_context = {
            "authority": "context.coordination_run_continue",
            "coordination_run_id": coordination_run_id,
            "task_graph_id": coordination_run.graph_ref,
            "selected_graph_id": coordination_run.graph_ref,
            **dict(payload.current_turn_context or {}),
        }
        _schedule_stage_execution_background(
            runtime=runtime,
            session_id=session_id,
            source=payload.source or "orchestration.coordination_run_continue_api",
            stage_execution_request=request,
            current_turn_context=current_turn_context,
        )
        return {
            "authority": "orchestration.coordination_run_continue_current_stage",
            "coordination_run_id": coordination_run_id,
            "task_run_id": coordination_run.task_run_id,
            "session_id": session_id,
            "stage_execution_request": request.to_dict(),
            "background_started": True,
            "mode": "replayed_active_stage_request",
        }
    if str(current_event.get("event_type") or "") != "task_result_ready":
        request_payload = current_stage_payload
        if not request_payload:
            raise HTTPException(status_code=409, detail="CoordinationRun has no resumable stage result or current stage execution request")
        request = NodeExecutionRequest.from_dict(
            _sanitize_replayed_writing_stage_request_payload(request_payload)
        )
        current_turn_context = {
            "authority": "context.coordination_run_continue",
            "coordination_run_id": coordination_run_id,
            "task_graph_id": coordination_run.graph_ref,
            "selected_graph_id": coordination_run.graph_ref,
            **dict(payload.current_turn_context or {}),
        }
        _schedule_stage_execution_background(
            runtime=runtime,
            session_id=session_id,
            source=payload.source or "orchestration.coordination_run_continue_api",
            stage_execution_request=request,
            current_turn_context=current_turn_context,
        )
        return {
            "authority": "orchestration.coordination_run_continue_current_stage",
            "coordination_run_id": coordination_run_id,
            "task_run_id": coordination_run.task_run_id,
            "session_id": session_id,
            "stage_execution_request": request.to_dict(),
            "background_started": True,
            "mode": "replayed_current_stage_request",
        }

    if not current_stage_payload and active_stage_id and active_stage_id != str(current_event.get("stage_id") or "").strip():
        repaired_state = dict(state)
        repaired_statuses = dict(repaired_state.get("node_statuses") or {})
        if repaired_statuses.get(active_stage_id) == "running":
            repaired_statuses[active_stage_id] = "pending"
            repaired_state["node_statuses"] = repaired_statuses
            repaired_state["terminal_status"] = ""
            repaired_state["stage_execution_request"] = {}
            repaired_state["diagnostics"] = {
                **dict(repaired_state.get("diagnostics") or {}),
                "continue_current_stage_repaired_pending_active_stage": active_stage_id,
            }
            runtime.query_runtime.task_run_loop.langgraph_coordination_runtime.checkpoints.put_state(
                thread_id=coordination_run_id,
                state=repaired_state,
                metadata={"event": "continue_current_stage_repair_pending_active_stage", "stage_id": active_stage_id},
            )

    current_task_result = dict(dict(state.get("stage_results") or {}).get(str(current_event.get("stage_id") or "")) or {})
    artifact_root = str(
        dict(payload.current_turn_context or {}).get("artifact_root")
        or dict(state.get("pending_inputs") or {}).get("artifact_root")
        or ""
    )
    resume_event = NodeResultReadyEvent(
        event_type=str(current_event.get("event_type") or "task_result_ready"),
        coordination_run_id=str(current_event.get("coordination_run_id") or coordination_run_id),
        task_run_id=str(current_event.get("task_run_id") or coordination_run.task_run_id),
        stage_id=str(current_event.get("stage_id") or ""),
        task_ref=str(current_event.get("task_ref") or ""),
        task_result_ref=str(current_event.get("task_result_ref") or ""),
        artifact_refs=tuple(str(item) for item in list(current_event.get("artifact_refs") or []) if str(item)),
        accepted=bool(current_event.get("accepted") is True),
        agent_run_result_ref=str(current_event.get("agent_run_result_ref") or ""),
        diagnostics=dict(current_event.get("diagnostics") or {}),
    )
    result = runtime.query_runtime.task_run_loop.langgraph_coordination_runtime.resume_from_task_result(
        coordination_run=coordination_run,
        event=resume_event,
        current_task_result=current_task_result,
        inherited_inputs=dict(payload.current_turn_context or {}),
        artifact_root=artifact_root,
    )
    request = result.stage_execution_request
    if request is not None:
        _schedule_stage_execution_background(
            runtime=runtime,
            session_id=session_id,
            source=payload.source or "orchestration.coordination_run_continue_api",
            stage_execution_request=request,
            current_turn_context={
                "authority": "context.coordination_run_continue",
                "coordination_run_id": coordination_run_id,
                "task_graph_id": coordination_run.graph_ref,
                "selected_graph_id": coordination_run.graph_ref,
                **dict(payload.current_turn_context or {}),
            },
        )
    return {
        "authority": "orchestration.coordination_run_continue_current_stage",
        "coordination_run_id": coordination_run_id,
        "task_run_id": coordination_run.task_run_id,
        "session_id": session_id,
        "stage_execution_request": request.to_dict() if request is not None else None,
        "background_started": request is not None,
        "mode": "resumed_from_task_result",
    }


def _stage_request_matches_active_stage(
    *,
    state: dict[str, Any],
    request_payload: dict[str, Any],
    active_stage_id: str,
) -> bool:
    request_stage_id = str(request_payload.get("stage_id") or "").strip()
    if not request_stage_id or request_stage_id != active_stage_id:
        return False
    node_status = str(dict(state.get("node_statuses") or {}).get(active_stage_id) or "")
    if node_status not in {"running", "pending"}:
        return False
    current_event_stage_id = str(dict(state.get("current_event") or {}).get("stage_id") or "").strip()
    if current_event_stage_id != active_stage_id:
        return True
    request_inputs = dict(request_payload.get("explicit_inputs") or {})
    if request_inputs.get("force_replay") is True or request_inputs.get("revision_required") is True:
        return True
    current_event = dict(state.get("current_event") or {})
    if current_event.get("accepted") is False:
        return True
    return False


def _latest_unconsumed_stage_task_result(
    *,
    runtime: Any,
    session_id: str,
    state: dict[str, Any],
    active_stage_id: str,
    coordination_run_id: str,
) -> dict[str, Any]:
    if not active_stage_id:
        return {}
    stage_results = dict(state.get("stage_results") or {})
    already_consumed_task_run_id = str(dict(stage_results.get(active_stage_id) or {}).get("task_run_id") or "")
    contracts = dict(state.get("stage_contracts") or {})
    contract = dict(contracts.get(active_stage_id) or {})
    active_task_ref = str(contract.get("task_ref") or state.get("active_task_ref") or "").strip()
    expected_task_suffix = active_stage_id
    candidates = []
    for task_run in runtime.query_runtime.task_run_loop.state_index.list_session_task_runs(session_id):
        if str(task_run.status or "") != "completed":
            continue
        if str(task_run.task_run_id or "") == already_consumed_task_run_id:
            continue
        pending_inputs = dict(state.get("pending_inputs") or {})
        force_replay_after = float(pending_inputs.get("force_replay_after") or 0.0)
        if force_replay_after and float(task_run.updated_at or task_run.created_at or 0.0) <= force_replay_after:
            continue
        task_id = str(task_run.task_id or "")
        task_contract_ref = str(task_run.task_contract_ref or "")
        exact_task_match = bool(active_task_ref and active_task_ref in {task_id, task_contract_ref})
        stage_suffix_match = bool(
            task_id.endswith(f":{expected_task_suffix}")
            or task_contract_ref.endswith(f":{expected_task_suffix}")
        )
        if not exact_task_match and not stage_suffix_match:
            continue
        diagnostics = dict(task_run.diagnostics or {})
        materialization = dict(diagnostics.get("artifact_materialization") or {})
        artifact_refs = [
            str(item)
            for item in list(materialization.get("artifact_refs") or [])
            if str(item).startswith("artifact:")
        ]
        checkpoint = runtime.query_runtime.task_run_loop.checkpoints.load_latest(task_run.task_run_id)
        task_result = dict(getattr(checkpoint, "commit_state", {}) or {}).get("task_result") if checkpoint is not None else {}
        task_result = dict(task_result or {})
        if artifact_refs:
            task_result["output_refs"] = list(dict.fromkeys([*list(task_result.get("output_refs") or []), *artifact_refs]))
        accepted = bool(str(task_run.status or "") == "completed" and (artifact_refs or not dict(contract.get("artifact_policy") or {}).get("enabled")))
        acceptance_diagnostics: dict[str, Any] = {
            "terminal_reason": str(task_run.terminal_reason or ""),
            "recovered_from_completed_stage_task_run": True,
        }
        if active_stage_id == "chapter_draft":
            artifact_text = _read_first_artifact_text(runtime=runtime, artifact_refs=artifact_refs)
            quality = _chapter_draft_recovery_quality_gate(
                artifact_text,
                explicit_inputs=pending_inputs,
            )
            accepted = bool(accepted and quality.get("accepted") is True)
            acceptance_diagnostics.update(quality)
        elif _is_review_gate_contract(contract):
            artifact_text = _read_first_artifact_text(runtime=runtime, artifact_refs=artifact_refs)
            quality = _review_gate_recovery_quality_gate(artifact_text)
            accepted = bool(accepted and quality.get("accepted") is True)
            acceptance_diagnostics.update(quality)
        candidates.append((float(task_run.updated_at or task_run.created_at or 0.0), task_run, task_result, artifact_refs, materialization, accepted, acceptance_diagnostics))
    if not candidates:
        return {}
    _updated_at, task_run, task_result, artifact_refs, materialization, accepted, acceptance_diagnostics = sorted(candidates, key=lambda item: item[0], reverse=True)[0]
    pending_inputs = dict(state.get("pending_inputs") or {})
    artifact_root = str(
        materialization.get("artifact_root")
        or pending_inputs.get("artifact_root")
        or ""
    )
    return {
        "task_run_id": task_run.task_run_id,
        "task_result": task_result,
        "explicit_inputs": pending_inputs,
        "artifact_root": artifact_root,
        "event": {
            "event_type": "task_result_ready",
            "coordination_run_id": coordination_run_id,
            "task_run_id": task_run.task_run_id,
            "stage_id": active_stage_id,
            "task_ref": active_task_ref or task_run.task_id,
            "task_result_ref": str(task_result.get("result_id") or f"taskresult:{task_run.task_run_id}"),
            "artifact_refs": tuple(artifact_refs),
            "accepted": bool(accepted),
            "agent_run_result_ref": "",
            "diagnostics": acceptance_diagnostics,
        },
    }


def _read_first_artifact_text(*, runtime: Any, artifact_refs: list[str]) -> str:
    root_dir = getattr(runtime.query_runtime.task_run_loop, "root_dir", None)
    if root_dir is None:
        return ""
    root_path = root_dir if hasattr(root_dir, "exists") else None
    candidate_roots = []
    if root_path is not None:
        candidate_roots.extend([root_path, root_path.parent, root_path.parent.parent])
    for ref in artifact_refs:
        raw = str(ref or "")
        if not raw.startswith("artifact:"):
            continue
        rel = raw[len("artifact:") :]
        paths = []
        try:
            paths.append(__import__("pathlib").Path(rel))
        except Exception:
            paths = []
        for base in candidate_roots:
            try:
                paths.append(base / rel)
            except TypeError:
                continue
        for path in paths:
            try:
                if path.exists() and path.is_file():
                    return path.read_text(encoding="utf-8")
            except OSError:
                continue
    return ""


def _is_review_gate_contract(contract: dict[str, Any]) -> bool:
    node_type = str(contract.get("node_type") or "").strip()
    gate_policy = str(contract.get("gate_policy") or "").strip()
    return node_type == "review_gate" or gate_policy == "review_gate" or bool(dict(contract.get("review_gate_policy") or {}))


def _review_gate_recovery_quality_gate(content: str) -> dict[str, Any]:
    text = str(content or "").strip()
    verdict = _extract_explicit_review_verdict(text)
    if not verdict:
        lowered = text.lower()
        if "不允许写入" in text or "不允许批次写入" in text or "必须等正文" in text:
            verdict = "revise"
        elif "允许批次写入记忆：否" in text or "是否允许批次写入记忆：否" in text:
            verdict = "revise"
        elif re.search(r"\bfail[_ -]?closed\b", lowered):
            verdict = "fail_closed"
        elif any(item in lowered for item in ("repair_world", "repair_outline", "repair_character", "human_review_required")):
            for item in ("repair_world", "repair_outline", "repair_character", "human_review_required"):
                if item in lowered:
                    verdict = item
                    break
        elif re.search(r"\b(revise|revision required)\b", lowered):
            verdict = "revise"
        elif re.search(r"\b(pass|approved|approve)\b", lowered):
            verdict = "pass"
    return {
        "accepted": verdict == "pass",
        "stage_business_acceptance": {
            "accepted": verdict == "pass",
            "policy": "review_gate_verdict_recovery",
            "verdict": verdict,
            "authority": "orchestration.stage_business_acceptance",
        },
        "review_verdict": verdict,
        "accepted_by_recovery_quality_gate": verdict == "pass",
        "recovered_from_completed_stage_task_run": True,
    }


def _extract_explicit_review_verdict(text: str) -> str:
    verdict_map = {
        "pass": "pass",
        "approved": "pass",
        "approve": "pass",
        "通过": "pass",
        "同意": "pass",
        "revise": "revise",
        "revision required": "revise",
        "修订": "revise",
        "修改": "revise",
        "返工": "revise",
        "不通过": "revise",
        "repair_world": "repair_world",
        "repair_outline": "repair_outline",
        "repair_character": "repair_character",
        "human_review_required": "human_review_required",
        "fail_closed": "fail_closed",
    }
    patterns = (
        r"^\s*[【\[]?\s*(?:裁决|结论|verdict)\s*[】\]]?\s*[:：-]?\s*([^\n\r]+)",
        r"^\s*(?:裁决|结论|verdict)\s*[:：-]\s*([^\n\r]+)",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, str(text or ""), re.IGNORECASE | re.MULTILINE):
            value = str(match.group(1) or "").strip().lower()
            for token, verdict in verdict_map.items():
                if token in value:
                    return verdict
    return ""


def _chapter_draft_recovery_quality_gate(content: str, *, explicit_inputs: dict[str, Any]) -> dict[str, Any]:
    text = str(content or "").strip()
    words = _count_longform_words(text)
    chapters_per_round = max(_safe_int(explicit_inputs.get("chapters_per_round") or explicit_inputs.get("chapter_batch_size")), 1)
    start_index = _safe_int(explicit_inputs.get("batch_start_index") or explicit_inputs.get("chapter_index"), 1)
    end_index = _safe_int(explicit_inputs.get("batch_end_index"), start_index + chapters_per_round - 1)
    expected_indexes = list(range(start_index, end_index + 1)) if end_index >= start_index else [start_index]
    found_indexes = _extract_chapter_heading_indexes(text)
    missing_indexes = [index for index in expected_indexes if index not in found_indexes]
    target_words = _safe_int(explicit_inputs.get("batch_target_words")) or ((_safe_int(explicit_inputs.get("chapter_target_words")) or 2000) * chapters_per_round)
    min_words = max(1200 * chapters_per_round, int(target_words * 0.55))
    refusal_detected = any(
        marker in text
        for marker in (
            "抱歉，我无法",
            "无法执行这个请求",
            "请先提供",
            "缺少前置资产",
            "我没有读取到",
            "当前可推进步骤",
            "不能直接产出",
        )
    )
    issues: list[str] = []
    if not text:
        issues.append("empty_content")
    if refusal_detected:
        issues.append("refusal_or_process_text_detected")
    if words < min_words:
        issues.append(f"insufficient_words:{words}<{min_words}")
    if missing_indexes:
        issues.append("missing_chapter_headings:" + ",".join(str(index) for index in missing_indexes))
    return {
        "accepted": not issues,
        "stage_business_acceptance": {
            "accepted": not issues,
            "policy": "chapter_draft_batch_quality_recovery",
            "issues": issues,
        },
        "chapter_words": words,
        "accepted_by_recovery_quality_gate": not issues,
        "recovery_quality_issues": issues,
        "expected_chapter_indexes": expected_indexes,
        "found_chapter_indexes": sorted(found_indexes),
        "missing_chapter_indexes": missing_indexes,
        "recovered_from_completed_stage_task_run": True,
    }


def _count_longform_words(content: str) -> int:
    text = str(content or "").strip()
    if not text:
        return 0
    return len(re.findall(r"[\u4e00-\u9fff]", text)) + len(re.findall(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)?", text))


def _extract_chapter_heading_indexes(content: str) -> set[int]:
    indexes: set[int] = set()
    for match in re.finditer(r"第\s*([0-9一二三四五六七八九十百零〇两]+)\s*[章节回]", str(content or "")):
        parsed = _parse_chapter_heading_number(match.group(1))
        if parsed > 0:
            indexes.add(parsed)
    return indexes


def _parse_chapter_heading_number(value: str) -> int:
    raw = str(value or "").strip()
    if not raw:
        return 0
    if raw.isdigit():
        return int(raw)
    digits = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    total = 0
    current = 0
    for char in raw:
        if char in digits:
            current = digits[char]
        elif char == "十":
            total += (current or 1) * 10
            current = 0
        elif char == "百":
            total += (current or 1) * 100
            current = 0
    return total + current


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value if value not in (None, "") else default)
    except (TypeError, ValueError):
        return default


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
