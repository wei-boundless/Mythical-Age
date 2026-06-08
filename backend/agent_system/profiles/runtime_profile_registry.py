from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from project_layout import ProjectLayout
from prompt_ref_migrations import migrate_runtime_profile_prompt_metadata

from ..registry.agent_registry import AgentRegistry
from ..identity import agent_id_aliases, normalize_agent_id, normalize_agent_id_sequence
from .runtime_profile_models import AgentRuntimeProfile, SubagentPolicy
from permissions.operation_packages import (
    ToolPackageSelection,
    default_enabled_package_selections,
    parse_tool_package_selection,
    resolve_tool_package_operations,
)
from ..models.model_profile_models import contains_raw_secret, parse_agent_model_profile


def _storage_root(base_dir: Path) -> Path:
    return ProjectLayout.from_backend_dir(base_dir).orchestration_dir


def _profiles_path(base_dir: Path) -> Path:
    return _storage_root(base_dir) / "agent_runtime_profiles.json"


def _read_json(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return fallback
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback
    return loaded if isinstance(loaded, dict) else fallback


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _is_removed_health_runtime_profile(payload: dict[str, Any]) -> bool:
    metadata = dict(payload.get("metadata") or {})
    profile_id = str(payload.get("agent_profile_id") or "").strip()
    agent_id = normalize_agent_id(str(payload.get("agent_id") or ""))
    return (
        agent_id == "agent:3"
        and (
            profile_id == "health_maintainer_agent"
            or str(metadata.get("runtime_template_id") or "").strip() == "builtin.system.health_manager"
        )
    )


def _runtime_profile(**payload: Any) -> AgentRuntimeProfile:
    if "allowed_operations" in payload:
        raise ValueError("default runtime profiles must declare allowed_tool_packages or extra_allowed_operations")
    allowed_tool_packages = tuple(payload.pop("allowed_tool_packages", ()) or ())
    extra_allowed_operations = tuple(str(item).strip() for item in list(payload.pop("extra_allowed_operations", ()) or ()) if str(item).strip())
    blocked_operations = tuple(str(item).strip() for item in list(payload.pop("blocked_operations", ()) or ()) if str(item).strip())
    allowed_operations = resolve_tool_package_operations(
        allowed_tool_packages,
        extra_allowed_operations=extra_allowed_operations,
        blocked_operations=blocked_operations,
    )
    return AgentRuntimeProfile(
        **payload,
        allowed_tool_packages=allowed_tool_packages,
        extra_allowed_operations=extra_allowed_operations,
        allowed_operations=allowed_operations,
        blocked_operations=_without_allowed_operations(blocked_operations, allowed_operations=allowed_operations),
    )


def default_agent_runtime_profiles() -> tuple[AgentRuntimeProfile, ...]:
    main_packages = (*default_enabled_package_selections(), ToolPackageSelection(package_id="pkg.subagent.lifecycle"))
    profiles = (
        _runtime_profile(
            agent_profile_id="main_interactive_agent",
            agent_id="agent:0",
            allowed_tool_packages=main_packages,
            extra_allowed_operations=("op.model_response", "op.shell"),
            blocked_operations=("op.python_repl", "op.memory_write_candidate", "op.git_push"),
            allowed_memory_scopes=("conversation_readonly", "state_readonly", "long_term_candidate"),
            allowed_context_sections=("conversation", "state", "task", "projection", "tool", "runtime_contracts"),
            subagent_policy=SubagentPolicy(
                enabled=True,
                allowed_subagent_ids=(
                    "agent:knowledge_searcher",
                    "agent:codebase_searcher",
                    "agent:memory_searcher",
                    "agent:pdf_reader",
                    "agent:table_analyst",
                    "agent:web_researcher",
                    "agent:verifier",
                ),
                max_subagent_runs_per_task=4,
                max_active_subagents=2,
                context_policy="summary_and_refs_only",
                result_policy="observation_refs_only",
                allow_nested_subagents=False,
            ),
            lifecycle_policy="system_builtin",
            metadata={
                "runtime_template_id": "builtin.main.default",
                "agent_prompt_refs_by_invocation": {
                    "single_agent_turn": ["agent.main_interactive_agent.single_agent_turn.work_role"],
                    "tool_observation_followup": ["agent.main_interactive_agent.tool_observation_followup.work_role"],
                    "task_execution": ["agent.main_interactive_agent.task_execution.work_role"],
                },
            },
        ),
        _runtime_profile(
            agent_profile_id="memory_system_agent",
            agent_id="agent:1",
            extra_allowed_operations=("op.model_response", "op.memory_read", "op.memory_write_candidate"),
            blocked_operations=("op.write_file", "op.edit_file", "op.shell", "op.python_repl", "op.agent_bounded", "op.web_search"),
            allowed_memory_scopes=("conversation_readonly", "state_readonly", "long_term_candidate", "session_memory_write_candidate", "durable_memory_write_candidate"),
            allowed_context_sections=("task", "runtime_trace", "memory_runtime_view", "prompt_manifest", "runtime_contracts"),
            approval_policy="read_only_first",
            lifecycle_policy="system_builtin",
            metadata={
                "system_key": "memory_system",
                "manager_kind": "memory",
                "runtime_template_id": "builtin.system.memory_manager",
                "agent_prompt_refs_by_invocation": {
                    "memory_maintenance": ["agent.memory_system_agent.memory_maintenance.work_role"],
                },
            },
        ),
        _runtime_profile(
            agent_profile_id="config_system_agent",
            agent_id="agent:2",
            extra_allowed_operations=("op.model_response", "op.read_file", "op.search_text"),
            blocked_operations=("op.write_file", "op.edit_file", "op.shell", "op.python_repl", "op.memory_write_candidate", "op.agent_bounded"),
            allowed_memory_scopes=("state_readonly",),
            allowed_context_sections=("task", "runtime_trace", "runtime_contracts"),
            approval_policy="read_only_first",
            lifecycle_policy="system_builtin",
            metadata={"system_key": "config_system", "manager_kind": "config", "runtime_template_id": "builtin.system.config_manager"},
        ),
        _runtime_profile(
            agent_profile_id="health_management_agent",
            agent_id="agent:3",
            extra_allowed_operations=(
                "op.model_response",
                "op.read_file",
                "op.search_files",
                "op.search_text",
                "op.git_status",
                "op.git_diff",
                "op.memory_read",
            ),
            blocked_operations=(
                "op.write_file",
                "op.edit_file",
                "op.shell",
                "op.python_repl",
                "op.memory_write_candidate",
                "op.agent_bounded",
                "op.git_commit",
                "op.git_push",
            ),
            allowed_memory_scopes=("conversation_readonly", "state_readonly", "issue_local_readonly", "health_trace_readonly"),
            allowed_context_sections=("task", "health_issue", "runtime_trace", "prompt_manifest", "assertions", "runtime_contracts", "artifact_refs"),
            approval_policy="read_only_first",
            trace_policy="runtime_event_log",
            lifecycle_policy="system_builtin",
            metadata={
                "system_key": "health_system",
                "manager_kind": "health",
                "runtime_template_id": "builtin.system.health_manager",
                "worker_kind": "health_diagnostics",
                "subagent_task_kind": "health_diagnostics",
                "when_to_use": "用于读取运行 trace、prompt manifest、断言证据和监控状态，并按健康/诊断标准给出 fail-closed 判定。",
                "runtime_config": {
                    "template_id": "runtime.template.health_diagnostics",
                    "runtime_kind": "health_diagnostics_agent",
                    "max_iterations": 2,
                    "max_tool_calls": 8,
                    "max_sources": 16,
                    "evidence_packet_required": True,
                    "stop_policy": "verdict_with_evidence_or_fail_closed",
                },
            },
        ),
        _runtime_profile(
            agent_profile_id="task_management_agent",
            agent_id="agent:4",
            extra_allowed_operations=("op.model_response", "op.read_file", "op.search_text"),
            blocked_operations=("op.write_file", "op.edit_file", "op.shell", "op.python_repl", "op.memory_write_candidate", "op.agent_bounded"),
            allowed_memory_scopes=("state_readonly",),
            allowed_context_sections=("task", "runtime_trace", "runtime_contracts"),
            approval_policy="read_only_first",
            lifecycle_policy="system_builtin",
            metadata={"system_key": "task_management_system", "manager_kind": "task", "runtime_template_id": "builtin.system.task_manager"},
        ),
        _runtime_profile(
            agent_profile_id="capability_system_agent",
            agent_id="agent:5",
            extra_allowed_operations=("op.model_response", "op.read_file", "op.search_text"),
            blocked_operations=("op.write_file", "op.edit_file", "op.shell", "op.python_repl", "op.memory_write_candidate", "op.agent_bounded"),
            allowed_memory_scopes=("state_readonly",),
            allowed_context_sections=("task", "runtime_trace", "runtime_contracts"),
            approval_policy="read_only_first",
            lifecycle_policy="system_builtin",
            metadata={"system_key": "capability_system", "manager_kind": "capability", "runtime_template_id": "builtin.system.capability_manager"},
        ),
        _runtime_profile(
            agent_profile_id="context_compactor_agent",
            agent_id="agent:context_compactor",
            extra_allowed_operations=("op.model_response",),
            blocked_operations=(
                "op.web_search",
                "op.fetch_url",
                "op.read_file",
                "op.write_file",
                "op.edit_file",
                "op.shell",
                "op.python_repl",
                "op.memory_write_candidate",
            ),
            allowed_memory_scopes=("conversation_readonly", "state_readonly"),
            allowed_context_sections=("task", "runtime_trace", "memory_runtime_view", "prompt_manifest", "runtime_contracts", "artifact_refs"),
            approval_policy="read_only_first",
            trace_policy="runtime_event_log",
            lifecycle_policy="system_builtin",
            model_profile=parse_agent_model_profile(
                {
                    "profile_id": "model.profile.context_compactor.semantic_compaction",
                    "display_name": "Context compactor semantic JSON profile",
                    "max_output_tokens": 4096,
                    "timeout_seconds": 45,
                    "long_output_timeout_seconds": 45,
                    "max_retries": 1,
                    "temperature": 0,
                    "thinking_mode": "disabled",
                    "reasoning_effort": "auto",
                    "stream_policy": {"enabled": False, "source": "context_compactor_agent.model_profile"},
                    "response_format": {"type": "json_object"},
                }
            ),
            metadata={
                "system_key": "context_management",
                "manager_kind": "context_compaction",
                "runtime_template_id": "builtin.system.context_compactor",
                "agent_prompt_refs_by_invocation": {
                    "semantic_compaction": ["agent.context_compactor_agent.semantic_compaction.work_role"],
                },
                "worker_kind": "semantic_compaction",
                "subagent_task_kind": "semantic_compaction",
                "input_contract": {
                    "request": "context_system.semantic_compaction_request",
                    "forbidden_inputs": ("external_web", "cross_namespace_memory", "raw_filesystem_scan"),
                },
                "output_contract": {
                    "required_fields": ("context_recovery_package",),
                    "optional_fields": ("summary_content", "diagnostics"),
                    "forbidden_actions": ("tool_call", "file_write", "memory_write", "delegation"),
                },
                "runtime_config": {
                    "template_id": "runtime.template.context_compactor",
                    "runtime_kind": "context_compactor",
                    "max_iterations": 1,
                    "max_tool_calls": 0,
                    "max_sources": 0,
                    "evidence_packet_required": False,
                    "stop_policy": "recovery_point_ready_or_blocked",
                    "context_compaction": {
                        "output_contract": "context_recovery_point",
                        "unavailable_summary_policy": "block_compaction",
                        "keep_last_messages": 6,
                        "max_summary_chars": 4000,
                        "trigger_pressure_levels": ("high", "critical"),
                        "actual_context_bytes_threshold": 120000,
                    },
                },
            },
        ),
        _runtime_profile(
            agent_profile_id="knowledge_search_agent",
            agent_id="agent:knowledge_searcher",
            extra_allowed_operations=("op.model_response", "op.mcp_retrieval"),
            blocked_operations=(
                "op.web_search",
                "op.fetch_url",
                "op.search_files",
                "op.search_text",
                "op.read_file",
                "op.memory_read",
                "op.write_file",
                "op.edit_file",
                "op.shell",
                "op.python_repl",
                "op.memory_write_candidate",
            ),
            allowed_memory_scopes=(),
            allowed_context_sections=("task", "projection", "tool", "runtime_contracts", "artifact_refs"),
            approval_policy="read_only_first",
            lifecycle_policy="system_builtin",
            metadata={
                "worker_kind": "knowledge_search",
                "subagent_task_kind": "knowledge_search",
                "subagent_task_kinds": ("knowledge_search", "knowledge_retrieval", "evidence_lookup", "retrieval"),
                "runtime_template_id": "runtime.template.knowledge_search",
                "worker_prompt_ref": "worker.prompt.knowledge_search",
                "agent_prompt_refs_by_invocation": {
                    "task_execution": ["worker.prompt.knowledge_search"],
                },
            },
        ),
        _runtime_profile(
            agent_profile_id="pdf_analysis_agent",
            agent_id="agent:pdf_reader",
            extra_allowed_operations=("op.model_response", "op.mcp_pdf", "op.read_file"),
            blocked_operations=("op.write_file", "op.edit_file", "op.shell", "op.python_repl", "op.memory_write_candidate"),
            allowed_memory_scopes=("conversation_readonly", "state_readonly"),
            allowed_context_sections=("task", "projection", "tool", "runtime_contracts", "artifact_refs"),
            approval_policy="read_only_first",
            lifecycle_policy="system_builtin",
            metadata={
                "worker_kind": "pdf_analysis",
                "subagent_task_kind": "pdf_reading",
                "runtime_template_id": "builtin.specialist.pdf_reader",
                "worker_prompt_ref": "worker.prompt.pdf_analysis",
                "agent_prompt_refs_by_invocation": {
                    "task_execution": ["worker.prompt.pdf_analysis"],
                },
            },
        ),
        _runtime_profile(
            agent_profile_id="structured_data_analysis_agent",
            agent_id="agent:table_analyst",
            extra_allowed_operations=("op.model_response", "op.mcp_structured_data", "op.read_structured_file", "op.read_file"),
            blocked_operations=("op.write_file", "op.edit_file", "op.shell", "op.python_repl", "op.memory_write_candidate"),
            allowed_memory_scopes=("conversation_readonly", "state_readonly"),
            allowed_context_sections=("task", "projection", "tool", "runtime_contracts", "artifact_refs"),
            approval_policy="read_only_first",
            lifecycle_policy="system_builtin",
            metadata={
                "worker_kind": "structured_data_analysis",
                "subagent_task_kind": "table_analysis",
                "runtime_template_id": "builtin.specialist.table_analyst",
                "worker_prompt_ref": "worker.prompt.structured_data_analysis",
                "agent_prompt_refs_by_invocation": {
                    "task_execution": ["worker.prompt.structured_data_analysis"],
                },
            },
        ),
        _runtime_profile(
            agent_profile_id="web_research_agent",
            agent_id="agent:web_researcher",
            extra_allowed_operations=(
                "op.model_response",
                "op.search_agent",
                "op.web_search",
                "op.fetch_url",
            ),
            blocked_operations=(
                "op.search_files",
                "op.search_text",
                "op.read_file",
                "op.mcp_retrieval",
                "op.memory_read",
                "op.write_file",
                "op.edit_file",
                "op.shell",
                "op.python_repl",
                "op.memory_write_candidate",
            ),
            allowed_memory_scopes=(),
            allowed_context_sections=("task", "projection", "tool", "runtime_contracts", "artifact_refs"),
            approval_policy="read_only_first",
            lifecycle_policy="system_builtin",
            metadata={
                "worker_kind": "web_research",
                "subagent_task_kind": "web_research",
                "subagent_task_kinds": (
                    "web_research",
                    "external_web_lookup",
                    "current_information_lookup",
                    "official_source_lookup",
                ),
                "when_to_use": "用于外部 Web 研究、当前信息、官方来源、第三方文档、版本日期、价格政策和需要 URL 证据的问题；不用于本地代码、RAG 或 memory 搜索。",
                "input_contract": {
                    "goal": "一句话说明要核实的外部问题。",
                    "instructions": "说明背景、时间新鲜度、是否偏好官方/主来源、排除项、输出长度和失败处理。",
                    "context_refs": "只传必要的父任务引用；不要假设子 agent 继承父会话全文。",
                    "expected_outputs": ("answer_candidate", "evidence_refs", "source_urls", "limitations"),
                },
                "output_contract": {
                    "required_fields": ("answer_candidate", "evidence_refs", "limitations"),
                    "recommended_fields": ("source_matrix", "source_urls", "open_questions", "source_strength", "recommended_parent_action"),
                    "source_policy": "无 source URL 或 evidence packet 时不得完成为成功答案。",
                    "result_policy": "summary_and_refs_only",
                },
                "context_policy": "fresh_specialist_summary_and_refs_only",
                "runtime_template_id": "builtin.specialist.web_researcher",
                "worker_prompt_ref": "worker.prompt.web_research",
                "agent_prompt_refs_by_invocation": {
                    "task_execution": ["worker.prompt.web_research"],
                },
                "runtime_config": {
                    "template_id": "runtime.template.deepsearch",
                    "runtime_kind": "search_agent",
                    "max_iterations": 4,
                    "max_tool_calls": 18,
                    "max_sources": 12,
                    "evidence_packet_required": True,
                    "stop_policy": "enough_evidence_or_budget_exhausted",
                    "search": {
                        "search_strategy": "deepsearch",
                        "search_sources": ("web",),
                        "web_provider": "tavily",
                        "allow_fetch_url": True,
                        "max_iterations": 4,
                        "max_queries": 6,
                        "max_fetches": 8,
                        "max_sources": 12,
                        "search_depth": "advanced",
                        "include_raw_content": False,
                        "prefer_primary_sources": True,
                        "freshness_required_by_default": False,
                        "evidence_packet_required": True,
                        "stop_policy": "enough_evidence_or_budget_exhausted",
                    },
                },
            },
        ),
        _runtime_profile(
            agent_profile_id="codebase_search_agent",
            agent_id="agent:codebase_searcher",
            extra_allowed_operations=(
                "op.model_response",
                "op.codebase_search",
                "op.search_files",
                "op.search_text",
                "op.read_file",
                "op.glob_paths",
                "op.git_status",
                "op.git_log",
                "op.git_show",
            ),
            blocked_operations=(
                "op.web_search",
                "op.fetch_url",
                "op.mcp_retrieval",
                "op.memory_read",
                "op.write_file",
                "op.edit_file",
                "op.shell",
                "op.python_repl",
                "op.memory_write_candidate",
            ),
            allowed_memory_scopes=(),
            allowed_context_sections=("task", "projection", "tool", "runtime_contracts", "artifact_refs"),
            approval_policy="read_only_first",
            lifecycle_policy="system_builtin",
            metadata={
                "worker_kind": "codebase_search",
                "subagent_task_kind": "codebase_search",
                "subagent_task_kinds": ("codebase_search", "local_search", "workspace_search", "file_search"),
                "when_to_use": "用于本地代码库只读搜索、符号定位、调用链追踪、跨文件结构理解和测试/实现证据查找；不用于 Web、RAG、memory 或文件修改。",
                "input_contract": {
                    "goal": "一句话说明要定位的代码事实或结构问题。",
                    "instructions": "包含已知符号、路径、模块、调用关系、排除项、是否需要测试文件和期望 file:line 证据。",
                    "context_refs": "只传必要的父任务引用；不要让子 agent 猜测父会话隐含背景。",
                    "expected_outputs": ("findings", "files_read", "evidence_refs", "limitations"),
                },
                "output_contract": {
                    "required_fields": ("findings", "evidence_refs", "limitations"),
                    "source_policy": "优先返回 file:line 和片段；无命中时返回 limitation，不伪造证据。",
                    "result_policy": "summary_and_refs_only",
                },
                "context_policy": "fresh_specialist_summary_and_refs_only",
                "runtime_template_id": "runtime.template.codebase_search",
                "worker_prompt_ref": "worker.prompt.codebase_search",
                "agent_prompt_refs_by_invocation": {
                    "task_execution": ["worker.prompt.codebase_search"],
                },
                "runtime_config": {
                    "template_id": "runtime.template.codebase_search",
                    "runtime_kind": "codebase_search_agent",
                    "max_iterations": 3,
                    "max_tool_calls": 18,
                    "max_sources": 16,
                    "evidence_packet_required": True,
                    "stop_policy": "enough_code_evidence_or_budget_exhausted",
                    "codebase_search": {
                        "max_queries": 12,
                        "max_file_slices": 16,
                        "max_slice_lines": 120,
                        "include_git_history": True,
                        "include_tests": True,
                    },
                },
            },
        ),
        _runtime_profile(
            agent_profile_id="memory_search_agent",
            agent_id="agent:memory_searcher",
            extra_allowed_operations=("op.model_response", "op.memory_read"),
            blocked_operations=(
                "op.web_search",
                "op.fetch_url",
                "op.search_files",
                "op.search_text",
                "op.read_file",
                "op.mcp_retrieval",
                "op.write_file",
                "op.edit_file",
                "op.shell",
                "op.python_repl",
                "op.memory_write_candidate",
            ),
            allowed_memory_scopes=("conversation_readonly", "state_readonly"),
            allowed_context_sections=("task", "projection", "tool", "runtime_contracts", "artifact_refs", "memory_runtime_view"),
            approval_policy="read_only_first",
            lifecycle_policy="system_builtin",
            metadata={
                "worker_kind": "memory_search",
                "subagent_task_kind": "memory_search",
                "subagent_task_kinds": ("memory_search", "memory_lookup", "memory_recall"),
                "runtime_template_id": "runtime.template.memory_search",
                "worker_prompt_ref": "worker.prompt.memory_search",
                "agent_prompt_refs_by_invocation": {
                    "task_execution": ["worker.prompt.memory_search"],
                },
                "runtime_config": {
                    "template_id": "runtime.template.memory_search",
                    "runtime_kind": "memory_search_agent",
                    "max_iterations": 2,
                    "max_tool_calls": 6,
                    "max_sources": 12,
                    "evidence_packet_required": True,
                    "stop_policy": "enough_memory_evidence_or_budget_exhausted",
                },
            },
        ),
        _runtime_profile(
            agent_profile_id="completion_verifier_agent",
            agent_id="agent:verifier",
            extra_allowed_operations=("op.model_response", "op.read_file", "op.search_files", "op.search_text", "op.git_diff", "op.git_status", "op.shell"),
            blocked_operations=("op.write_file", "op.edit_file", "op.python_repl", "op.memory_write_candidate"),
            allowed_memory_scopes=("conversation_readonly", "state_readonly"),
            allowed_context_sections=("task", "projection", "runtime_trace", "assertions", "runtime_contracts", "artifact_refs"),
            approval_policy="read_only_first",
            trace_policy="runtime_event_log",
            lifecycle_policy="system_builtin",
            metadata={
                "worker_kind": "completion_verification",
                "subagent_task_kind": "completion_verification",
                "subagent_task_kinds": (
                    "completion_verification",
                    "semantic_verification",
                    "deliverable_review",
                    "artifact_review",
                    "quality_review",
                    "plan_review",
                ),
                "when_to_use": "当主 Agent 已有候选回答、产物或执行证据，但需要独立检查是否满足用户目标、是否缺少证据、是否需要返工时使用。",
                "runtime_template_id": "builtin.specialist.verifier",
                "worker_prompt_ref": "worker.prompt.verification",
                "agent_prompt_refs_by_invocation": {
                    "task_execution": ["worker.prompt.verification"],
                },
                "output_contract": {
                    "required_fields": ("verdict", "checks", "risks"),
                    "verdict_values": ("PASS", "FAIL", "PARTIAL"),
                    "evidence_required": True,
                    "forbidden_actions": ("file_write", "edit", "fix_implementation"),
                },
                "child_execution_mode": "bounded_verification",
            },
        ),
    )
    return profiles

def _profile_from_dict(payload: dict[str, Any]) -> AgentRuntimeProfile:
    normalized_agent_id = normalize_agent_id(str(payload.get("agent_id") or ""))
    metadata = dict(payload.get("metadata") or {})
    raw_blocked_operations = tuple(str(item) for item in list(payload.get("blocked_operations") or []) if str(item))
    package_selections = _package_selections_from_payload(payload)
    extra_allowed_operations = tuple(str(item) for item in list(payload.get("extra_allowed_operations") or []) if str(item))
    allowed_operations = resolve_tool_package_operations(
        package_selections,
        extra_allowed_operations=extra_allowed_operations,
        blocked_operations=raw_blocked_operations,
    )
    blocked_operations = _without_allowed_operations(raw_blocked_operations, allowed_operations=allowed_operations)
    return AgentRuntimeProfile(
        agent_profile_id=str(payload.get("agent_profile_id") or ""),
        agent_id=normalized_agent_id,
        allowed_tool_packages=package_selections,
        extra_allowed_operations=extra_allowed_operations,
        allowed_operations=allowed_operations,
        blocked_operations=blocked_operations,
        allowed_memory_scopes=tuple(_normalize_memory_scopes(normalized_agent_id, payload.get("allowed_memory_scopes"))),
        allowed_context_sections=tuple(str(item) for item in list(payload.get("allowed_context_sections") or []) if str(item)),
        subagent_policy=_subagent_policy_from_payload(payload),
        approval_policy=str(payload.get("approval_policy") or "default"),
        trace_policy=str(payload.get("trace_policy") or "runtime_event_log"),
        lifecycle_policy=str(payload.get("lifecycle_policy") or "orchestration_managed"),
        model_profile=parse_agent_model_profile(payload.get("model_profile")),
        metadata=metadata,
    )


def _package_selections_from_payload(payload: dict[str, Any]) -> tuple[ToolPackageSelection, ...]:
    return tuple(
        item
        for item in (
            parse_tool_package_selection(raw)
            for raw in list(payload.get("allowed_tool_packages") or [])
        )
        if item is not None
    )


def _subagent_policy_from_payload(payload: dict[str, Any]) -> SubagentPolicy:
    raw = dict(payload.get("subagent_policy") or {})
    allowed_ids = normalize_agent_id_sequence(
        str(item) for item in list(raw.get("allowed_subagent_ids") or []) if str(item)
    )
    enabled = bool(raw.get("enabled", False))
    max_runs = int(raw.get("max_subagent_runs_per_task", 0) or 0)
    max_active = int(raw.get("max_active_subagents", min(max_runs, 2) if max_runs else 0) or 0)
    return SubagentPolicy(
        enabled=enabled and bool(allowed_ids),
        allowed_subagent_ids=allowed_ids,
        max_subagent_runs_per_task=max(0, max_runs),
        max_active_subagents=max(0, max_active),
        context_policy=str(raw.get("context_policy") or "summary_and_refs_only"),
        result_policy=str(raw.get("result_policy") or "observation_refs_only"),
        allow_nested_subagents=bool(raw.get("allow_nested_subagents", False)),
    )


def _coerce_subagent_policy_for_upsert(value: SubagentPolicy | dict[str, Any] | None) -> SubagentPolicy:
    if isinstance(value, SubagentPolicy):
        return value
    payload = {"subagent_policy": dict(value or {})}
    return _subagent_policy_from_payload(payload)


def _infer_runtime_template_id(agent_id: str, payload: dict[str, Any]) -> str:
    metadata = dict(payload.get("metadata") or {})
    explicit = str(metadata.get("runtime_template_id") or payload.get("runtime_template_id") or "").strip()
    if explicit:
        return explicit
    source_refs = [str(item).strip() for item in list(metadata.get("source_task_graph_refs") or []) if str(item).strip()]
    return ""


class AgentRuntimeRegistry:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)
        self.agent_registry = AgentRegistry(self.base_dir)
        self.path = _profiles_path(self.base_dir)

    def list_profiles(self) -> list[AgentRuntimeProfile]:
        default_payload = [item.to_dict() for item in default_agent_runtime_profiles()]
        default_by_agent = {str(item.get("agent_id") or ""): item for item in default_payload}
        payload = _read_json(
            self.path,
            {"profiles": default_payload},
        )
        stored_profiles = [
            _migrate_profile_payload(item)
            for item in list(payload.get("profiles") or [])
            if isinstance(item, dict) and not _is_removed_health_runtime_profile(item)
        ]
        default_agent_ids = set(default_by_agent)
        live_agent_ids = {agent.agent_id for agent in self.agent_registry.list_agents()}
        merged_payload = (
            default_payload
            if not self.path.exists()
            else _merge_items_by_key(
                default_payload,
                [
                    item
                    for item in stored_profiles
                    if str(item.get("agent_id") or "").strip() in live_agent_ids
                    or str(item.get("agent_id") or "").strip() in default_agent_ids
                ],
                key="agent_id",
            )
        )
        profiles = [
            _profile_from_dict(_enforce_system_builtin_profile_payload(item, default_by_agent=default_by_agent))
            for item in merged_payload
        ]
        normalized = [item.to_dict() for item in profiles]
        if payload.get("profiles") != normalized:
            _write_json(self.path, {"profiles": normalized})
        return profiles

    def get_profile(self, agent_id: str) -> AgentRuntimeProfile | None:
        target = normalize_agent_id(agent_id)
        aliases = set(agent_id_aliases(target))
        return next((item for item in self.list_profiles() if item.agent_id in aliases), None)

    def get_profile_by_profile_id(self, agent_profile_id: str) -> AgentRuntimeProfile | None:
        target = str(agent_profile_id or "").strip()
        if not target:
            return None
        return next((item for item in self.list_profiles() if item.agent_profile_id == target), None)

    def upsert_profile(
        self,
        *,
        agent_id: str,
        agent_profile_id: str = "",
        allowed_tool_packages: tuple[ToolPackageSelection, ...] | None = None,
        allowed_operations: tuple[str, ...] | None = None,
        extra_allowed_operations: tuple[str, ...] | None = None,
        blocked_operations: tuple[str, ...] = (),
        allowed_memory_scopes: tuple[str, ...] = (),
        allowed_context_sections: tuple[str, ...] = (),
        subagent_policy: SubagentPolicy | dict[str, Any] | None = None,
        approval_policy: str = "default",
        trace_policy: str = "runtime_event_log",
        lifecycle_policy: str = "orchestration_managed",
        model_profile: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AgentRuntimeProfile:
        target = normalize_agent_id(agent_id)
        if not target.startswith("agent:"):
            raise ValueError("agent_id must start with agent:")
        if self.agent_registry.get_agent(target) is None:
            raise ValueError("unknown agent")
        if contains_raw_secret(model_profile):
            raise ValueError("model_profile must use credential_ref instead of raw secrets")
        current = self.get_profile(target)
        metadata_payload = migrate_runtime_profile_prompt_metadata(dict(metadata or {}))
        requested_packages = current.allowed_tool_packages if allowed_tool_packages is None and current else (allowed_tool_packages or ())
        requested_extra_operations = (
            tuple(str(item).strip() for item in allowed_operations if str(item).strip())
            if allowed_operations is not None
            else current.extra_allowed_operations if extra_allowed_operations is None and current else (extra_allowed_operations or ())
        )
        raw_blocked_operations = tuple(str(item).strip() for item in blocked_operations if str(item).strip())
        resolved_allowed_operations = resolve_tool_package_operations(
            requested_packages,
            extra_allowed_operations=requested_extra_operations,
            blocked_operations=raw_blocked_operations,
        )
        profile = AgentRuntimeProfile(
            agent_profile_id=str(agent_profile_id or (current.agent_profile_id if current else f"{target.removeprefix('agent:').replace(':', '_')}_runtime")).strip(),
            agent_id=target,
            allowed_tool_packages=tuple(requested_packages),
            extra_allowed_operations=tuple(str(item).strip() for item in requested_extra_operations if str(item).strip()),
            allowed_operations=resolved_allowed_operations,
            blocked_operations=tuple(str(item).strip() for item in raw_blocked_operations if str(item).strip()),
            allowed_memory_scopes=tuple(_normalize_memory_scopes(target, allowed_memory_scopes)),
            allowed_context_sections=tuple(str(item).strip() for item in allowed_context_sections if str(item).strip()),
            subagent_policy=_coerce_subagent_policy_for_upsert(
                subagent_policy if subagent_policy is not None else (current.subagent_policy if current else None)
            ),
            approval_policy=str(approval_policy or "default").strip() or "default",
            trace_policy=str(trace_policy or "runtime_event_log").strip() or "runtime_event_log",
            lifecycle_policy=str(lifecycle_policy or "orchestration_managed").strip() or "orchestration_managed",
            model_profile=parse_agent_model_profile(model_profile if model_profile is not None else (current.model_profile.to_dict() if current else {})),
            metadata=metadata_payload,
        )
        profiles = [item for item in self.list_profiles() if item.agent_id != target]
        profiles.append(profile)
        _write_json(self.path, {"profiles": [item.to_dict() for item in profiles]})
        return profile

    def delete_profile(self, agent_id: str) -> None:
        target = str(agent_id or "").strip()
        if not target:
            return
        profiles = [item for item in self.list_profiles() if item.agent_id != target]
        _write_json(self.path, {"profiles": [item.to_dict() for item in profiles]})

    def build_catalog(self) -> dict[str, Any]:
        agents = self.agent_registry.list_agents()
        profiles = self.list_profiles()
        profile_by_agent = {item.agent_id: item for item in profiles}
        runtime_templates: dict[str, dict[str, Any]] = {}
        for profile in profiles:
            template_id = profile.runtime_template_id
            if not template_id:
                continue
            bucket = runtime_templates.setdefault(
                template_id,
                {
                    "runtime_template_id": template_id,
                    "agent_ids": [],
                    "profile_ids": [],
                    "lifecycle_policies": set(),
                },
            )
            bucket["agent_ids"].append(profile.agent_id)
            bucket["profile_ids"].append(profile.agent_profile_id)
            bucket["lifecycle_policies"].add(profile.lifecycle_policy)
        return {
            "authority": "orchestration.agent_runtime_registry",
            "agents": [
                {
                    **agent.to_dict(),
                    "runtime_profile": profile_by_agent.get(agent.agent_id).to_dict() if profile_by_agent.get(agent.agent_id) else {},
                }
                for agent in agents
            ],
            "profiles": [item.to_dict() for item in profiles],
            "runtime_templates": [
                {
                    "runtime_template_id": template_id,
                    "agent_ids": sorted(list(dict.fromkeys(bucket["agent_ids"]))),
                    "profile_ids": sorted(list(dict.fromkeys(bucket["profile_ids"]))),
                    "lifecycle_policies": sorted(bucket["lifecycle_policies"]),
                    "agent_count": len(set(bucket["agent_ids"])),
                }
                for template_id, bucket in sorted(runtime_templates.items())
            ],
            "summary": {
                "agent_count": len(agents),
                "runtime_profile_count": len(profiles),
                "profile_missing_count": sum(1 for agent in agents if agent.agent_id not in profile_by_agent),
                "main_agent_count": sum(1 for item in agents if item.profile_type == "main_agent"),
                "builtin_agent_count": sum(1 for item in agents if item.profile_type == "builtin_agent"),
                "custom_agent_count": sum(1 for item in agents if item.profile_type == "custom_agent"),
                "system_manager_agent_count": sum(1 for item in agents if item.builtin_kind == "system_manager"),
                "subagent_enabled_agent_count": sum(1 for item in agents if item.subagent_enabled),
                "runtime_template_count": len(runtime_templates),
            },
        }


def _merge_items_by_key(
    default_items: list[dict[str, Any]],
    stored_items: list[dict[str, Any]],
    *,
    key: str,
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for item in default_items:
        item_key = str(item.get(key) or "").strip()
        if item_key:
            merged[item_key] = dict(item)
    for item in stored_items:
        item_key = str(item.get(key) or "").strip()
        if item_key:
            merged[item_key] = dict(item)
    return list(merged.values())


def _migrate_profile_payload(payload: dict[str, Any]) -> dict[str, Any]:
    next_payload = dict(payload)
    next_payload["agent_id"] = normalize_agent_id(str(payload.get("agent_id") or ""))
    next_payload["subagent_policy"] = _subagent_policy_from_payload(payload).to_dict()
    next_payload["allowed_memory_scopes"] = _normalize_memory_scopes(
        next_payload["agent_id"],
        payload.get("allowed_memory_scopes"),
    )
    metadata = migrate_runtime_profile_prompt_metadata(dict(payload.get("metadata") or {}))
    metadata.pop("legacy_agent_id", None)
    metadata.pop("allowed_task_modes", None)
    runtime_template_id = _infer_runtime_template_id(next_payload["agent_id"], {**next_payload, "metadata": metadata})
    if runtime_template_id:
        metadata["runtime_template_id"] = runtime_template_id
    next_payload["metadata"] = metadata
    next_payload["model_profile"] = parse_agent_model_profile(
        payload.get("model_profile") or metadata.pop("model_profile", {})
    ).to_dict()
    next_payload.pop("output_contracts", None)
    return next_payload


def _enforce_system_builtin_profile_payload(
    payload: dict[str, Any],
    *,
    default_by_agent: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    agent_id = str(payload.get("agent_id") or "").strip()
    default_payload = default_by_agent.get(agent_id)
    if not default_payload:
        return payload
    strict_default_agent_ids = {
        "agent:web_researcher",
        "agent:codebase_searcher",
        "agent:knowledge_searcher",
        "agent:memory_searcher",
    }
    if agent_id in strict_default_agent_ids:
        enforced = dict(default_payload)
        enforced["agent_id"] = agent_id
        return enforced
    enforced = dict(default_payload)
    enforced.update(payload)
    enforced["agent_id"] = agent_id
    for key in (
        "extra_allowed_operations",
        "blocked_operations",
        "allowed_memory_scopes",
        "allowed_context_sections",
    ):
        enforced[key] = _merge_sequence_field(
            default_payload.get(key),
            payload.get(key),
        )
    enforced["subagent_policy"] = _merge_subagent_policy_payloads(
        default_payload.get("subagent_policy"),
        payload.get("subagent_policy"),
    )
    default_model_profile = dict(default_payload.get("model_profile") or {})
    if (
        str(payload.get("agent_profile_id") or "") == str(default_payload.get("agent_profile_id") or "")
        and _model_profile_has_default_authority(default_model_profile)
    ):
        enforced["model_profile"] = default_model_profile
    enforced["allowed_memory_scopes"] = _normalize_memory_scopes(
        agent_id,
        enforced.get("allowed_memory_scopes"),
    )
    enforced_allowed_operations = resolve_tool_package_operations(
        _package_selections_from_payload(enforced),
        extra_allowed_operations=tuple(str(item) for item in list(enforced.get("extra_allowed_operations") or []) if str(item)),
        blocked_operations=tuple(str(item) for item in list(enforced.get("blocked_operations") or []) if str(item)),
    )
    enforced["blocked_operations"] = _without_allowed_operations(
        enforced.get("blocked_operations"),
        allowed_operations=enforced_allowed_operations,
    )
    default_metadata_keys: set[str] = set()
    if str(payload.get("agent_profile_id") or "") == str(default_payload.get("agent_profile_id") or ""):
        default_metadata_keys.update(
            {
                "system_key",
                "manager_kind",
                "runtime_template_id",
                "agent_prompt_refs_by_invocation",
                "worker_kind",
                "subagent_task_kind",
                "input_contract",
                "output_contract",
            }
        )
    payload_metadata = dict(payload.get("metadata") or {})
    if default_metadata_keys:
        payload_metadata.pop("work_role_prompt", None)
        payload_metadata.pop("agent_work_role_prompt", None)
        payload_metadata.pop("work_role_prompt_by_invocation", None)
        payload_metadata.pop("agent_work_role_prompt_by_invocation", None)
        payload_metadata.pop("work_role_prompt_refs_by_invocation", None)
    enforced["metadata"] = {
        **payload_metadata,
        **{
            key: value
            for key, value in dict(default_payload.get("metadata") or {}).items()
            if key in default_metadata_keys
        },
    }
    return enforced


def _model_profile_has_default_authority(payload: dict[str, Any]) -> bool:
    if not payload:
        return False
    return any(
        payload.get(key) not in (None, "", [], {})
        for key in (
            "profile_id",
            "provider",
            "model",
            "max_output_tokens",
            "timeout_seconds",
            "temperature",
            "thinking_mode",
            "reasoning_effort",
            "stream_policy",
            "response_format",
        )
    )


def _merge_subagent_policy_payloads(default_value: Any, payload_value: Any) -> dict[str, Any]:
    default_policy = _subagent_policy_from_payload({"subagent_policy": dict(default_value or {})}).to_dict()
    payload_policy = _subagent_policy_from_payload({"subagent_policy": dict(payload_value or {})}).to_dict()
    allowed = _merge_sequence_field(default_policy.get("allowed_subagent_ids"), payload_policy.get("allowed_subagent_ids"))
    return {
        **default_policy,
        **payload_policy,
        "enabled": bool(default_policy.get("enabled") or payload_policy.get("enabled")) and bool(allowed),
        "allowed_subagent_ids": allowed,
        "max_subagent_runs_per_task": max(
            int(default_policy.get("max_subagent_runs_per_task") or 0),
            int(payload_policy.get("max_subagent_runs_per_task") or 0),
        ),
        "max_active_subagents": max(
            int(default_policy.get("max_active_subagents") or 0),
            int(payload_policy.get("max_active_subagents") or 0),
        ),
    }


def _merge_sequence_field(default_value: Any, payload_value: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for source in (default_value, payload_value):
        for item in list(source or []):
            normalized = str(item or "").strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            result.append(normalized)
    return result


def _dedupe_sequence(values: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in list(values or []):
        normalized = str(item or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _normalize_memory_scopes(agent_id: str, scopes: Any) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for item in list(scopes or []):
        value = str(item or "").strip()
        if value in {"conversation_read_write", "state_read_write"}:
            continue
        if not value or value in seen:
            continue
        if agent_id != "agent:1" and value in {"session_memory_write_candidate", "durable_memory_write_candidate"}:
            continue
        seen.add(value)
        normalized.append(value)
    return normalized


def _without_allowed_operations(blocked_operations: Any, *, allowed_operations: Any) -> tuple[str, ...]:
    allowed = {str(item or "").strip() for item in list(allowed_operations or []) if str(item or "").strip()}
    result: list[str] = []
    seen: set[str] = set()
    for item in list(blocked_operations or []):
        value = str(item or "").strip()
        if not value or value in allowed or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return tuple(result)


