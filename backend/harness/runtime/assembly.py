from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from agent_system.identity import normalize_agent_id_sequence
from capability_system.skills.registry import SkillRegistry
from capability_system.tools.authorization import build_authorized_tool_set
from permissions.policy import normalize_permission_mode
from core.project_layout import ProjectLayout
from harness.runtime.environment_storage import apply_session_scoped_environment_storage
from task_system.contracts.runtime_contracts import SkillRuntimeView, skill_runtime_view_from_skill_definition
from task_system.environments import build_task_environment_catalog, task_environment_registry_from_backend_dir

from .operation_projection import project_operation_authorization
from .tool_scheduling import operation_requests_from_runtime_contract
from .environment_prompt_controller import GENERAL_ENVIRONMENT_ID, build_base_prompt_mount_plan
from .personality_prompt_controller import select_personality_prompt


_SUBAGENT_TOOL_NAMES = {
    "spawn_subagent",
    "send_subagent_message",
    "wait_subagent",
    "list_subagents",
    "close_subagent",
}

_DEFAULT_TOOL_GUIDANCE_PROMPT_DEFAULTS: dict[str, str] = {
    "tool.guidance.read_file": "tool.guidance.read_file",
    "tool.guidance.read_persisted_tool_result": "tool.guidance.read_persisted_tool_result",
    "tool.guidance.edit_file": "tool.guidance.edit_file",
    "tool.guidance.batch_edit_file": "tool.guidance.batch_edit_file",
    "tool.guidance.write_file": "tool.guidance.write_file",
    "tool.guidance.terminal_powershell": "tool.guidance.terminal_powershell",
    "tool.guidance.git_read": "tool.guidance.git_read",
    "tool.guidance.git_write": "tool.guidance.git_write",
    "tool.guidance.todo": "tool.guidance.todo",
    "tool.guidance.local_search": "tool.guidance.local_search",
    "tool.guidance.subagent": "tool.guidance.subagent",
    "tool.guidance.browser": "tool.guidance.browser",
    "tool.guidance.web_fetch": "tool.guidance.web_fetch",
    "tool.guidance.attachment_extract_text": "tool.guidance.attachment_extract_text",
}

_BASE_RUNTIME_POLICY: dict[str, Any] = {
    "interaction_policy": {
        "style": "general_agent",
        "task_orientation": "agent_decides_next_action",
        "user_clarification": "allowed",
    },
    "planning_policy": {"plan_mode": "available", "specified_plan_allowed": True, "todo_required_when_task_run": True},
    "task_lifecycle_policy": {"request_task_run": True, "requires_completion_evidence": True, "artifact_evidence_required": True},
    "tool_exposure_policy": {},
    "context_policy": {
        "history_scope": "conversation_task_and_recovery",
        "task_context": "available",
        "task_run_context": "enabled",
        "active_work_context": "available",
        "system_groups": {
            "evidence_alignment": {"enabled": True},
            "reasoning_projection": {"enabled": True, "public_reasoning_default": False},
        },
    },
    "memory_policy": {"read_scope": "agent_profile", "write_scope": "candidate_with_receipt"},
    "subagent_policy": {"enabled": True},
    "self_review_policy": {
        "enabled": True,
        "checkpoints": ("before_tool", "after_tool", "before_final"),
        "failure_recovery": "replan_or_report_blocker",
    },
    "step_summary_policy": {"enabled": True, "detail": "stepwise"},
    "approval_policy": {"permission_scope": "agent_profile_ceiling"},
    "artifact_policy": {},
    "operation_authorization_projection": {},
}

_GENERAL_AGENT_PROMPT_TEMPLATE_POLICY: dict[str, Any] = {
    "prompt_policy": {
        "template_id": "prompt_template.general.agent_runtime",
        "tool_guidance_prompt_defaults": _DEFAULT_TOOL_GUIDANCE_PROMPT_DEFAULTS,
    },
    "prompt_pack_refs_by_invocation": {
        "single_agent_turn": ["runtime.pack.single_agent_turn"],
        "task_execution": ["runtime.pack.task_execution"],
        "tool_observation_followup": ["runtime.pack.observation_followup"],
        "semantic_compaction": ["runtime.pack.semantic_compaction"],
    },
}

_PROMPT_ORCHESTRATION_TEMPLATE_POLICIES: dict[str, dict[str, Any]] = {
    "prompt_template.general.agent_runtime": _GENERAL_AGENT_PROMPT_TEMPLATE_POLICY,
}

_CAPABILITY_GROUP_CATALOG: dict[str, dict[str, str]] = {
    "general_task": {
        "title": "通用任务判断",
        "use_when": "用于理解用户目标、决定是否回答、询问、启动持续任务或阻塞。",
    },
    "file_work": {
        "title": "文件与代码工作",
        "use_when": "用于列目录、按关键词查路径、按 glob 匹配路径、搜索文本、读取文件、分析代码和编辑文件。",
    },
    "web_research": {
        "title": "网络研究",
        "use_when": "用于搜索网络、读取网页、交叉验证来源和整理引用证据。",
    },
    "browser_use": {
        "title": "浏览器操作",
        "use_when": "用于打开页面、点击、输入、截图、检查本地前端或网页交互。",
    },
    "shell_execution": {
        "title": "命令执行",
        "use_when": "用于运行命令、脚本、测试、构建或解释终端输出。",
    },
    "artifact_generation": {
        "title": "产物生成",
        "use_when": "用于创建或修改文件、生成图片、写入交付物并保留证据。",
    },
    "attachment_processing": {
        "title": "附件处理",
        "use_when": "用于读取受控附件资源，并通过本地 MCP 能力提取图片文字。",
    },
    "source_control": {
        "title": "版本控制",
        "use_when": "用于查看 diff、日志、分支、暂存、提交和推送。",
    },
    "memory": {
        "title": "记忆检索",
        "use_when": "用于读取任务记忆、历史事实和可复用上下文。",
    },
    "subagent_delegation": {
        "title": "子 Agent 委派",
        "use_when": "用于把清晰子目标交给子 agent 并收回结构化结果。",
    },
    "task_planning": {
        "title": "任务计划与待办",
        "use_when": "用于维护执行待办、阶段状态和验收进度。",
    },
}

_TOOL_CAPABILITY_GROUP_BY_OPERATION: dict[str, str] = {
    "op.agent_todo": "task_planning",
    "op.subagent_spawn": "subagent_delegation",
    "op.subagent_message": "subagent_delegation",
    "op.subagent_wait": "subagent_delegation",
    "op.subagent_list": "subagent_delegation",
    "op.subagent_close": "subagent_delegation",
    "op.web_search": "web_research",
    "op.fetch_url": "web_research",
    "op.browser_control": "browser_use",
    "op.list_dir": "file_work",
    "op.stat_path": "file_work",
    "op.path_exists": "file_work",
    "op.glob_paths": "file_work",
    "op.search_files": "file_work",
    "op.search_text": "file_work",
    "op.read_file": "file_work",
    "op.read_persisted_tool_result": "file_work",
    "op.read_structured_file": "file_work",
    "op.python_code_outline": "file_work",
    "op.python_parse_check": "file_work",
    "op.python_symbol_search": "file_work",
    "op.text_metric": "file_work",
    "op.write_file": "artifact_generation",
    "op.edit_file": "artifact_generation",
    "op.image_generate": "artifact_generation",
    "op.mcp_image_ocr": "attachment_processing",
    "op.shell": "shell_execution",
    "op.python_repl": "shell_execution",
    "op.memory_read": "memory",
    "op.git_status": "source_control",
    "op.git_diff": "source_control",
    "op.git_log": "source_control",
    "op.git_show": "source_control",
    "op.git_branch_list": "source_control",
    "op.git_branch_create": "source_control",
    "op.git_stage": "source_control",
    "op.git_unstage": "source_control",
    "op.git_commit": "source_control",
    "op.git_restore": "source_control",
    "op.git_push": "source_control",
}

_CONTEXT_CAPABILITY_GROUPS = (
    "static_identity",
    "runtime_contracts",
    "action_contracts",
    "task_contracts",
    "tool_context",
    "context_memory",
    "task_state_context",
    "evidence_context",
    "evidence_alignment",
    "current_dynamic_control",
    "lifecycle_control",
    "repair_feedback",
    "active_skill",
    "memory_write",
    "reasoning_projection",
    "subagent_system",
)

_SYSTEM_GROUP_CAPABILITY_GROUPS: dict[str, tuple[str, ...]] = {
    "task_contract_intake": ("task_contracts", "runtime_contracts", "lifecycle_control", "repair_feedback"),
    "react_loop": ("action_contracts", "tool_context", "lifecycle_control", "repair_feedback", "current_dynamic_control"),
    "tool_runtime": ("tool_context", "action_contracts", "repair_feedback"),
    "skill_runtime": ("active_skill", "runtime_contracts", "tool_context"),
    "subagent_delegation": ("subagent_system", "action_contracts", "tool_context", "lifecycle_control", "repair_feedback"),
    "context_memory": ("context_memory", "task_state_context"),
    "memory_governance": ("memory_write", "context_memory", "repair_feedback"),
    "evidence_read": ("evidence_context", "tool_context", "repair_feedback"),
    "evidence_alignment": ("evidence_alignment", "evidence_context", "action_contracts", "repair_feedback"),
    "reasoning_projection": ("reasoning_projection", "runtime_contracts", "repair_feedback"),
    "lifecycle_resume_steer": ("lifecycle_control", "current_dynamic_control", "context_memory", "repair_feedback"),
    "output_projection": ("runtime_contracts", "repair_feedback"),
    "recovery_closeout": ("repair_feedback", "lifecycle_control", "context_memory"),
}

_TOOL_CAPABILITY_SYSTEM_GROUPS: dict[str, dict[str, tuple[str, ...]]] = {
    "task_planning": {
        "capability_groups": ("action_contracts", "task_state_context", "tool_context", "repair_feedback"),
        "prompt_resources": ("tool.guidance.todo", "runtime.rule.plan_mode_boundary"),
        "context_segments": (
            "task_goal_context",
            "task_plan_context",
            "task_todo_context",
            "single_agent_turn_tool_call",
            "tool_transcript_delta",
        ),
        "feedback_channels": ("todo_update", "plan_repair"),
    },
    "file_work": {
        "capability_groups": ("tool_context", "evidence_context", "repair_feedback"),
        "prompt_resources": (
            "runtime.rule.file_management.generic",
            "tool.guidance.read_file",
            "tool.guidance.read_persisted_tool_result",
            "tool.guidance.local_search",
        ),
        "context_segments": ("tool_index_stable", "read_evidence_context", "evidence_index_cursor", "editor_context_index"),
        "feedback_channels": ("file_read_result", "file_search_result", "file_evidence_repair"),
    },
    "artifact_generation": {
        "capability_groups": ("tool_context", "action_contracts", "repair_feedback"),
        "prompt_resources": ("tool.guidance.edit_file", "tool.guidance.batch_edit_file", "tool.guidance.write_file"),
        "context_segments": ("tool_index_stable", "read_evidence_context", "tool_transcript_delta"),
        "feedback_channels": ("artifact_write_result", "artifact_write_error", "edit_recovery"),
    },
    "shell_execution": {
        "capability_groups": ("tool_context", "action_contracts", "repair_feedback"),
        "prompt_resources": ("tool.guidance.terminal_powershell",),
        "context_segments": ("tool_index_stable", "single_agent_turn_tool_call", "tool_transcript_delta"),
        "feedback_channels": ("shell_result", "shell_error", "shell_recovery"),
    },
    "source_control": {
        "capability_groups": ("tool_context", "evidence_context", "repair_feedback"),
        "prompt_resources": ("tool.guidance.git_read", "tool.guidance.git_write"),
        "context_segments": ("tool_index_stable", "read_evidence_context", "tool_transcript_delta"),
        "feedback_channels": ("git_result", "git_error", "git_recovery"),
    },
    "web_research": {
        "capability_groups": ("tool_context", "evidence_context", "repair_feedback"),
        "prompt_resources": ("tool.guidance.web_fetch",),
        "context_segments": ("tool_index_stable", "read_evidence_context"),
        "feedback_channels": ("web_fetch_result", "web_fetch_error", "source_recovery"),
    },
    "browser_use": {
        "capability_groups": ("tool_context", "evidence_context", "current_dynamic_control", "repair_feedback"),
        "prompt_resources": ("tool.guidance.browser",),
        "context_segments": ("tool_index_stable", "read_evidence_context", "dynamic_projection"),
        "feedback_channels": ("browser_observation", "browser_error", "browser_recovery"),
    },
    "attachment_processing": {
        "capability_groups": ("tool_context", "evidence_context", "repair_feedback"),
        "prompt_resources": ("tool.guidance.attachment_extract_text",),
        "context_segments": ("tool_index_stable", "attachment_context_index", "read_evidence_context"),
        "feedback_channels": ("attachment_extract_result", "attachment_extract_error", "attachment_recovery"),
    },
    "subagent_delegation": {
        "capability_groups": ("action_contracts", "tool_context", "lifecycle_control", "repair_feedback"),
        "prompt_resources": ("tool.guidance.subagent", "runtime.rule.subagent_delegation", "runtime.rule.subagent_invocation_protocol"),
        "context_segments": ("tool_index_stable", "single_agent_turn_tool_call", "tool_transcript_delta"),
        "feedback_channels": ("subagent_result", "subagent_failure", "subagent_closeout"),
    },
}


@dataclass(frozen=True, slots=True)
class RuntimeAssemblyProfile:
    profile_ref: str
    prompt_pack_refs: tuple[str, ...] = ()
    prompt_pack_refs_by_invocation: dict[str, Any] = field(default_factory=dict)
    operation_authorization_projection: dict[str, Any] = field(default_factory=dict)
    allowed_operations: tuple[str, ...] = ()
    interaction_policy: dict[str, Any] = field(default_factory=dict)
    tool_policy: dict[str, Any] = field(default_factory=dict)
    network_policy: dict[str, Any] = field(default_factory=dict)
    subagent_policy: dict[str, Any] = field(default_factory=dict)
    planning_policy: dict[str, Any] = field(default_factory=dict)
    task_lifecycle_policy: dict[str, Any] = field(default_factory=dict)
    context_policy: dict[str, Any] = field(default_factory=dict)
    memory_policy: dict[str, Any] = field(default_factory=dict)
    self_review_policy: dict[str, Any] = field(default_factory=dict)
    artifact_policy: dict[str, Any] = field(default_factory=dict)
    prompt_policy: dict[str, Any] = field(default_factory=dict)
    permission_policy: dict[str, Any] = field(default_factory=dict)
    step_summary_policy: dict[str, Any] = field(default_factory=dict)
    authority: str = "harness.runtime.assembly_profile"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["prompt_pack_refs"] = list(self.prompt_pack_refs)
        payload["prompt_pack_refs_by_invocation"] = {
            str(key): [str(item) for item in list(value or []) if str(item)]
            for key, value in dict(self.prompt_pack_refs_by_invocation or {}).items()
        }
        payload["operation_authorization_projection"] = dict(self.operation_authorization_projection or {})
        payload["allowed_operations"] = list(self.allowed_operations)
        return payload


@dataclass(frozen=True, slots=True)
class RuntimeAssembly:
    assembly_id: str
    session_id: str
    turn_id: str
    agent_invocation_id: str
    profile: RuntimeAssemblyProfile
    backend_dir: str = ""
    agent_profile_ref: str = ""
    model_selection: dict[str, Any] = field(default_factory=dict)
    runtime_contract: dict[str, Any] = field(default_factory=dict)
    runtime_storage_ref: dict[str, Any] = field(default_factory=dict)
    engagement_contract: dict[str, Any] = field(default_factory=dict)
    execution_strategy: dict[str, Any] = field(default_factory=dict)
    engagement_run_ref: str = ""
    task_environment: dict[str, Any] = field(default_factory=dict)
    permission_mode: str = "default"
    agent_prompt_refs: tuple[str, ...] = ()
    agent_prompt_refs_by_invocation: dict[str, Any] = field(default_factory=dict)
    personality_prompt_refs: tuple[str, ...] = ()
    personality_prompt_selection: dict[str, Any] = field(default_factory=dict)
    environment_prompt_refs: tuple[str, ...] = ()
    prompt_mount_plan: dict[str, Any] = field(default_factory=dict)
    capability_directory: dict[str, Any] = field(default_factory=dict)
    skill_runtime_views: tuple[dict[str, Any], ...] = ()
    skill_activation: dict[str, Any] = field(default_factory=dict)
    available_tools: tuple[dict[str, Any], ...] = ()
    tool_names: tuple[str, ...] = ()
    filtered_tools: tuple[dict[str, str], ...] = ()
    tool_transport_policy: dict[str, Any] = field(default_factory=dict)
    control_capabilities: dict[str, Any] = field(default_factory=dict)
    operation_authorization: dict[str, Any] = field(default_factory=dict)
    system_wiring_manifest: dict[str, Any] = field(default_factory=dict)
    rejected_capabilities: tuple[dict[str, str], ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "harness.runtime.assembly"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["profile"] = self.profile.to_dict()
        payload["available_tools"] = [dict(item) for item in self.available_tools]
        payload["tool_names"] = list(self.tool_names)
        payload["filtered_tools"] = [dict(item) for item in self.filtered_tools]
        payload["tool_transport_policy"] = dict(self.tool_transport_policy)
        payload["control_capabilities"] = dict(self.control_capabilities)
        payload["operation_authorization"] = dict(self.operation_authorization)
        payload["system_wiring_manifest"] = dict(self.system_wiring_manifest)
        payload["engagement_contract"] = dict(self.engagement_contract)
        payload["execution_strategy"] = dict(self.execution_strategy)
        payload["agent_prompt_refs"] = list(self.agent_prompt_refs)
        payload["agent_prompt_refs_by_invocation"] = {
            str(key): [str(item) for item in list(value or []) if str(item)]
            for key, value in dict(self.agent_prompt_refs_by_invocation or {}).items()
        }
        payload["personality_prompt_refs"] = list(self.personality_prompt_refs)
        payload["personality_prompt_selection"] = dict(self.personality_prompt_selection)
        payload["environment_prompt_refs"] = list(self.environment_prompt_refs)
        payload["prompt_mount_plan"] = dict(self.prompt_mount_plan)
        payload["capability_directory"] = dict(self.capability_directory)
        payload["skill_runtime_views"] = [dict(item) for item in self.skill_runtime_views]
        payload["skill_activation"] = dict(self.skill_activation)
        payload["rejected_capabilities"] = [dict(item) for item in self.rejected_capabilities]
        return payload


def assemble_runtime(
    *,
    backend_dir: Path,
    session_id: str,
    turn_id: str,
    agent_invocation_id: str,
    runtime_contract: dict[str, Any],
    model_selection: dict[str, Any],
    agent_runtime_profile: Any | None,
    tool_instances: list[Any] | tuple[Any, ...] | None,
    definitions_by_name: dict[str, Any],
    environment_binding: dict[str, Any] | None = None,
    permission_mode: str = "default",
    workspace_root: str | Path | None = None,
) -> RuntimeAssembly:
    runtime_contract_payload = dict(runtime_contract or {})
    normalized_permission_mode = normalize_permission_mode(permission_mode)
    bound_workspace_root = _normalize_workspace_root(workspace_root)
    engagement_contract = dict(runtime_contract_payload.get("engagement_contract") or {})
    explicit_operation_ceiling = _explicit_operation_ceiling_from_runtime_contract(runtime_contract_payload)
    profile = build_runtime_assembly_profile(
        agent_runtime_profile=agent_runtime_profile,
        runtime_contract=runtime_contract_payload,
        explicit_operation_ceiling=explicit_operation_ceiling,
    )
    task_environment, environment_diagnostics = _resolve_runtime_task_environment(
        backend_dir=backend_dir,
        environment_binding=environment_binding,
        agent_runtime_profile=agent_runtime_profile,
        runtime_contract=runtime_contract_payload,
    )
    task_environment = apply_session_scoped_environment_storage(task_environment, session_id=session_id)
    task_environment = _apply_bound_workspace_root(task_environment, bound_workspace_root)
    personality_selection = select_personality_prompt(
        runtime_contract=runtime_contract_payload,
        agent_runtime_profile=agent_runtime_profile,
    )
    prompt_mount_plan = build_base_prompt_mount_plan(
        selected_environment=task_environment,
        personality_prompt_refs=personality_selection.personality_prompt_refs,
        personality_diagnostics=personality_selection.to_dict(),
        prompt_policy=profile.prompt_policy,
    )
    task_requested_operations = operation_requests_from_runtime_contract(runtime_contract_payload)
    operation_projection = project_operation_authorization(
        agent_allowed_operations=profile.allowed_operations,
        agent_blocked_operations=tuple(getattr(agent_runtime_profile, "blocked_operations", ()) or ()),
        task_requested_operations=task_requested_operations,
        definitions_by_name=definitions_by_name,
        permission_mode=normalized_permission_mode,
        operation_ceiling=explicit_operation_ceiling,
    )
    allowed_operations = set(operation_projection.allowed_operations)
    tool_set = build_authorized_tool_set(
        tool_instances=list(tool_instances or []),
        definitions_by_name=definitions_by_name,
        allowed_operations=allowed_operations,
        include_hidden=False,
    )
    visible_tool_names, visibility_filtered = _filter_tool_names_by_profile(
        profile=profile,
        tool_names=tuple(tool_set.tool_names),
        definitions_by_name=definitions_by_name,
    )
    tool_instances_by_name = {
        str(getattr(tool, "name", "") or ""): tool
        for tool in list(tool_instances or [])
        if str(getattr(tool, "name", "") or "")
    }
    control_capabilities = _control_capabilities_for_runtime(
        profile=profile,
        runtime_contract=runtime_contract_payload,
        environment_payload=task_environment,
        visible_tool_names=visible_tool_names,
        engagement_contract=engagement_contract,
    )
    available_tools = tuple(
        _tool_view(
            tool_name=name,
            definition=definitions_by_name.get(name),
            tool_instance=tool_instances_by_name.get(name),
        )
        for name in visible_tool_names
        if definitions_by_name.get(name) is not None
    )
    tool_transport_policy = _tool_transport_policy_for_runtime(
        profile=profile,
        runtime_contract=runtime_contract_payload,
        model_selection=dict(model_selection or {}),
        visible_tool_names=visible_tool_names,
    )
    skill_runtime_views = _skill_runtime_views_for_profile(
        backend_dir=backend_dir,
        allowed_operations=tuple(sorted(allowed_operations)),
    )
    skill_activation = _visible_skill_activation(
        runtime_contract_payload.get("skill_activation"),
        visible_skill_ids=tuple(str(item.get("skill_id") or "") for item in skill_runtime_views),
    )
    capability_directory = _capability_directory_view(
        runtime_contract=runtime_contract_payload,
        available_tools=available_tools,
        skill_runtime_views=skill_runtime_views,
        filtered_tools=tuple(
            [
                *_operation_filtered_tools(operation_projection.to_dict(), definitions_by_name=definitions_by_name),
                *_drop_generic_operation_denials(tool_set.filtered_out),
                *visibility_filtered,
            ]
        ),
    )
    system_wiring_manifest = _build_system_wiring_manifest(
        agent_runtime_profile=agent_runtime_profile,
        profile=profile,
        prompt_mount_plan=prompt_mount_plan,
        runtime_contract=runtime_contract_payload,
        task_environment=task_environment,
        operation_authorization=operation_projection.to_dict(),
        visible_tool_names=visible_tool_names,
        available_tools=available_tools,
        filtered_tools=tuple(
            [
                *_operation_filtered_tools(operation_projection.to_dict(), definitions_by_name=definitions_by_name),
                *_drop_generic_operation_denials(tool_set.filtered_out),
                *visibility_filtered,
            ]
        ),
        skill_runtime_views=skill_runtime_views,
        skill_activation=skill_activation,
        control_capabilities=control_capabilities,
    )
    return RuntimeAssembly(
        assembly_id=f"rtasm:{turn_id}:{profile.profile_ref or 'agent_profile'}",
        session_id=session_id,
        turn_id=turn_id,
        agent_invocation_id=agent_invocation_id,
        profile=profile,
        backend_dir=str(Path(backend_dir).resolve()),
        agent_profile_ref=str(getattr(agent_runtime_profile, "agent_profile_id", "") or "main_interactive_agent"),
        model_selection=dict(model_selection or {}),
        runtime_contract=runtime_contract_payload,
        runtime_storage_ref=_runtime_storage_ref(backend_dir),
        engagement_contract=engagement_contract,
        execution_strategy=dict(engagement_contract.get("execution_strategy") or runtime_contract_payload.get("execution_strategy") or {}),
        engagement_run_ref=str(runtime_contract_payload.get("engagement_run_ref") or ""),
        task_environment=task_environment,
        permission_mode=normalized_permission_mode,
        agent_prompt_refs=_agent_prompt_refs(agent_runtime_profile),
        agent_prompt_refs_by_invocation=_agent_prompt_refs_by_invocation(agent_runtime_profile),
        personality_prompt_refs=personality_selection.personality_prompt_refs,
        personality_prompt_selection=personality_selection.to_dict(),
        environment_prompt_refs=prompt_mount_plan.environment_prompt_refs,
        prompt_mount_plan=prompt_mount_plan.to_dict(),
        capability_directory=capability_directory,
        skill_runtime_views=skill_runtime_views,
        skill_activation=skill_activation,
        available_tools=available_tools,
        tool_names=visible_tool_names,
        filtered_tools=tuple(
            [
                *_operation_filtered_tools(operation_projection.to_dict(), definitions_by_name=definitions_by_name),
                *_drop_generic_operation_denials(tool_set.filtered_out),
                *visibility_filtered,
            ]
        ),
        tool_transport_policy=tool_transport_policy,
        control_capabilities=control_capabilities,
        operation_authorization=operation_projection.to_dict(),
        system_wiring_manifest=system_wiring_manifest,
        rejected_capabilities=(),
        diagnostics={
            "agent_profile_ref": str(getattr(agent_runtime_profile, "agent_profile_id", "") or ""),
            "task_environment": environment_diagnostics,
            "prompt_mount_plan": prompt_mount_plan.to_dict(),
            "personality_prompt_selection": personality_selection.to_dict(),
            "workspace_root": bound_workspace_root,
            "permission_mode": normalized_permission_mode,
            "engagement_contract_ref": str(engagement_contract.get("contract_id") or runtime_contract_payload.get("engagement_contract_ref") or ""),
            "engagement_plan_ref": str(engagement_contract.get("plan_id") or runtime_contract_payload.get("engagement_plan_ref") or ""),
            "operation_authorization": {
                "allowed_operation_count": len(operation_projection.allowed_operations),
                "denied_operation_count": len(operation_projection.denied_operations),
            },
            "control_capabilities": dict(control_capabilities),
            "tool_transport_policy": dict(tool_transport_policy),
            "skill_runtime": {
                "candidate_count": len(skill_runtime_views),
                "skill_activation": dict(skill_activation),
            },
            "system_wiring_manifest": system_wiring_manifest,
        },
    )


def build_runtime_assembly_profile(
    *,
    agent_runtime_profile: Any | None = None,
    runtime_contract: dict[str, Any] | None = None,
    explicit_operation_ceiling: tuple[str, ...] | None = None,
) -> RuntimeAssemblyProfile:
    runtime_contract = dict(runtime_contract or {})
    runtime_policy = _resolved_runtime_policy(
        agent_runtime_profile=agent_runtime_profile,
        runtime_contract=runtime_contract,
    )
    base_operations = _profile_operations(agent_runtime_profile)
    tool_policy = dict(runtime_policy.get("tool_exposure_policy") or {})
    explicit_tool_policy = _merge_dicts(
        runtime_contract.get("tool_exposure_policy"),
        runtime_contract.get("tool_policy"),
        dict(runtime_contract.get("runtime_profile") or {}).get("tool_exposure_policy"),
        dict(runtime_contract.get("runtime_profile") or {}).get("tool_policy"),
    )
    if explicit_tool_policy:
        tool_policy = {**tool_policy, **explicit_tool_policy}
    ceiling = _string_tuple(explicit_tool_policy.get("operation_ceiling"))
    if ceiling:
        base_operations = tuple(item for item in base_operations if item in set(ceiling))
    blocked_operations = set(_string_tuple(explicit_tool_policy.get("blocked_operations")))
    if blocked_operations:
        base_operations = tuple(item for item in base_operations if item not in blocked_operations)
    if explicit_operation_ceiling is not None:
        base_operations = tuple(item for item in base_operations if item in set(explicit_operation_ceiling))
    return RuntimeAssemblyProfile(
        profile_ref=str(getattr(agent_runtime_profile, "agent_profile_id", "") or "main_interactive_agent"),
        prompt_pack_refs=_string_tuple(runtime_policy.get("prompt_pack_refs")),
        prompt_pack_refs_by_invocation=dict(runtime_policy.get("prompt_pack_refs_by_invocation") or {}),
        operation_authorization_projection=dict(runtime_policy.get("operation_authorization_projection") or {}),
        allowed_operations=base_operations,
        interaction_policy=dict(runtime_policy.get("interaction_policy") or {}),
        tool_policy=tool_policy,
        network_policy=dict(runtime_policy.get("network_policy") or {}),
        subagent_policy=_subagent_policy(
            agent_runtime_profile=agent_runtime_profile,
            policy=dict(runtime_policy.get("subagent_policy") or {}),
        ),
        planning_policy=dict(runtime_policy.get("planning_policy") or {}),
        task_lifecycle_policy=dict(runtime_policy.get("task_lifecycle_policy") or {}),
        context_policy=dict(runtime_policy.get("context_policy") or {}),
        memory_policy=dict(runtime_policy.get("memory_policy") or {}),
        self_review_policy=dict(runtime_policy.get("self_review_policy") or {}),
        artifact_policy=dict(runtime_policy.get("artifact_policy") or {}),
        prompt_policy=dict(runtime_policy.get("prompt_policy") or {}),
        permission_policy=dict(runtime_policy.get("approval_policy") or runtime_policy.get("permission_policy") or {}),
        step_summary_policy=dict(runtime_policy.get("step_summary_policy") or {}),
    )


def _normalize_workspace_root(value: str | Path | None) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return str(Path(text).resolve())


def _runtime_storage_ref(backend_dir: str | Path) -> dict[str, Any]:
    layout = ProjectLayout.from_backend_dir(backend_dir)
    return {
        "runtime_state_root": str(layout.runtime_state_dir),
        "authority": "harness.runtime.assembly.runtime_storage_ref",
    }


def _apply_bound_workspace_root(environment: dict[str, Any], workspace_root: str) -> dict[str, Any]:
    if not workspace_root:
        return dict(environment or {})
    payload = dict(environment or {})
    storage = dict(payload.get("storage_space") or {})
    sandbox = dict(payload.get("sandbox_policy") or {})
    storage["workspace_root"] = workspace_root
    sandbox["workspace_root"] = workspace_root
    payload["storage_space"] = storage
    payload["sandbox_policy"] = sandbox
    payload["project_binding"] = {
        "workspace_root": workspace_root,
        "authority": "harness.runtime.session_project_binding",
    }
    return payload


def _explicit_operation_ceiling_from_runtime_contract(runtime_contract: dict[str, Any]) -> tuple[str, ...] | None:
    payload = dict(runtime_contract or {})
    scopes: list[tuple[str, ...]] = []
    runtime_profile = dict(payload.get("runtime_profile") or {})
    execution_permit = dict(payload.get("execution_permit") or {})
    runtime_execution_permit = dict(runtime_profile.get("execution_permit") or {})
    tool_policy = _merge_dicts(
        payload.get("tool_exposure_policy"),
        payload.get("tool_policy"),
        runtime_profile.get("tool_exposure_policy"),
        runtime_profile.get("tool_policy"),
    )

    for value in (
        payload.get("operation_ceiling"),
        execution_permit.get("operation_ceiling"),
        runtime_profile.get("operation_ceiling"),
        runtime_execution_permit.get("operation_ceiling"),
        tool_policy.get("operation_ceiling"),
    ):
        operations = _string_tuple(value)
        if operations:
            scopes.append(operations)

    if not scopes:
        return None
    allowed = set(scopes[0])
    for scope in scopes[1:]:
        allowed.intersection_update(scope)
    return tuple(operation for operation in scopes[0] if operation in allowed)


def _agent_prompt_refs(agent_runtime_profile: Any | None) -> tuple[str, ...]:
    metadata = dict(getattr(agent_runtime_profile, "metadata", {}) or {})
    explicit = _string_tuple(metadata.get("agent_prompt_refs"))
    if explicit:
        return explicit
    by_invocation = _agent_prompt_refs_by_invocation(agent_runtime_profile)
    if by_invocation:
        refs: list[str] = []
        seen: set[str] = set()
        for value in by_invocation.values():
            for item in _string_tuple(value):
                if item not in seen:
                    seen.add(item)
                    refs.append(item)
        return tuple(refs)
    return ()


def _agent_prompt_refs_by_invocation(agent_runtime_profile: Any | None) -> dict[str, tuple[str, ...]]:
    metadata = dict(getattr(agent_runtime_profile, "metadata", {}) or {})
    raw = metadata.get("agent_prompt_refs_by_invocation")
    result: dict[str, tuple[str, ...]] = {
        str(key): _string_tuple(value)
        for key, value in dict(raw or {}).items()
        if str(key).strip() and _string_tuple(value)
    }
    if result:
        return result
    return {}


def _skill_runtime_views_for_profile(
    *,
    backend_dir: Path,
    allowed_operations: tuple[str, ...],
) -> tuple[dict[str, Any], ...]:
    allowed = {str(item or "").strip() for item in allowed_operations if str(item or "").strip()}
    if not allowed:
        return ()
    registry = SkillRegistry(Path(backend_dir).resolve())
    views: list[SkillRuntimeView] = []
    for skill in registry.skills:
        if str(skill.runtime.activation_policy or "") != "model_visible":
            continue
        required = {
            str(item or "").strip()
            for item in tuple(skill.runtime.requires_operations or ())
            if str(item or "").strip()
        }
        if required and not required.issubset(allowed):
            continue
        views.append(skill_runtime_view_from_skill_definition(skill))
    return tuple(view.to_dict() for view in views)


def _visible_skill_activation(value: Any, *, visible_skill_ids: tuple[str, ...]) -> dict[str, Any]:
    raw = dict(value or {}) if isinstance(value, dict) else {}
    visible = {str(item or "").strip() for item in visible_skill_ids if str(item or "").strip()}
    selected: list[str] = []
    rejected: list[str] = []
    seen: set[str] = set()
    raw_values = raw.get("selected_skill_ids")
    raw_values = raw_values if isinstance(raw_values, (list, tuple)) else ([raw_values] if raw_values else [])
    for raw_item in raw_values:
        item = str(raw_item or "").strip()
        if not item:
            continue
        normalized = item if item.startswith("skill.") else f"skill.{item}"
        if normalized in seen:
            continue
        seen.add(normalized)
        if normalized not in visible:
            rejected.append(normalized)
            continue
        selected.append(normalized)
    return {
        "selected_skill_ids": selected,
        "selection_source": str(raw.get("selection_source") or "").strip(),
        "selection_reason": str(raw.get("selection_reason") or "").strip(),
        "expanded_skill_refs": list(_string_tuple(raw.get("expanded_skill_refs"))),
        "rejected_skill_ids": [*list(_string_tuple(raw.get("rejected_skill_ids"))), *rejected],
        "authority": str(raw.get("authority") or "harness.runtime.skill_activation"),
    }


def _capability_directory_view(
    *,
    runtime_contract: dict[str, Any],
    available_tools: tuple[dict[str, Any], ...],
    skill_runtime_views: tuple[dict[str, Any], ...],
    filtered_tools: tuple[dict[str, str], ...],
) -> dict[str, Any]:
    capability_intent = dict(runtime_contract.get("capability_intent") or {})
    requested_groups = set(_string_tuple(capability_intent.get("needed_capability_groups") or capability_intent.get("capability_groups")))
    preferred_namespaces = set(_string_tuple(capability_intent.get("preferred_tool_namespaces") or capability_intent.get("tool_namespaces")))
    tools_by_group: dict[str, list[dict[str, Any]]] = {}
    for tool in available_tools:
        payload = dict(tool or {})
        group_id = _capability_group_for_tool(payload)
        tools_by_group.setdefault(group_id, []).append(
            {
                "tool_name": str(payload.get("tool_name") or "").strip(),
                "operation_id": str(payload.get("operation_id") or "").strip(),
                "read_only": bool(payload.get("read_only") is True),
            }
        )
    skills_by_group: dict[str, list[dict[str, str]]] = {}
    for skill in skill_runtime_views:
        payload = dict(skill or {})
        group_id = str(payload.get("preferred_capability_group") or "").strip() or "general_task"
        skill_id = str(payload.get("skill_id") or "").strip()
        if not skill_id:
            continue
        skills_by_group.setdefault(group_id, []).append(
            {
                "skill_id": skill_id,
                "title": str(payload.get("title") or skill_id).strip(),
            }
        )
    group_ids = _dedupe_strings(
        [
            "general_task",
            *sorted(requested_groups),
            *sorted(tools_by_group.keys()),
            *sorted(skills_by_group.keys()),
        ]
    )
    groups: list[dict[str, Any]] = []
    for group_id in group_ids:
        meta = dict(_CAPABILITY_GROUP_CATALOG.get(group_id) or {})
        candidate_tools = tuple(dict(item) for item in tools_by_group.get(group_id, []))
        candidate_skills = tuple(dict(item) for item in skills_by_group.get(group_id, []))
        loading_mode = "visible" if candidate_tools else "deferred"
        if group_id in {"web_research", "browser_use"} and not candidate_tools:
            loading_mode = "search"
        groups.append(
            {
                "group_id": group_id,
                "title": str(meta.get("title") or group_id).strip(),
                "use_when": str(meta.get("use_when") or "").strip(),
                "tool_namespaces": list(_dedupe_strings([group_id, *([group_id] if group_id in preferred_namespaces else [])])),
                "candidate_tools": list(candidate_tools),
                "candidate_skills": list(candidate_skills),
                "loading_mode": loading_mode,
                "contract_requested": group_id in requested_groups,
            }
        )
    return {
        "capability_groups": groups,
        "requested_capability_groups": [group for group in group_ids if group in requested_groups],
        "preferred_tool_namespaces": sorted(preferred_namespaces),
        "tool_search_available": bool(filtered_tools or preferred_namespaces),
        "skill_selection_available": bool(skill_runtime_views),
        "authority": "harness.runtime.capability_directory",
    }


def _build_system_wiring_manifest(
    *,
    agent_runtime_profile: Any | None,
    profile: RuntimeAssemblyProfile,
    prompt_mount_plan: Any,
    runtime_contract: dict[str, Any],
    task_environment: dict[str, Any],
    operation_authorization: dict[str, Any],
    visible_tool_names: tuple[str, ...],
    available_tools: tuple[dict[str, Any], ...],
    filtered_tools: tuple[dict[str, str], ...],
    skill_runtime_views: tuple[dict[str, Any], ...],
    skill_activation: dict[str, Any],
    control_capabilities: dict[str, Any],
) -> dict[str, Any]:
    """Compile existing runtime profile/environment/task policy into wiring diagnostics.

    This is not a new configuration authority. It is a structured projection of
    the already-resolved runtime assembly, used by prompt/context gates.
    """

    profile_payload = profile.to_dict()
    prompt_mount_payload = (
        prompt_mount_plan.to_dict()
        if hasattr(prompt_mount_plan, "to_dict")
        else dict(prompt_mount_plan or {})
        if isinstance(prompt_mount_plan, dict)
        else {}
    )
    agent_profile_payload = (
        agent_runtime_profile.to_dict()
        if hasattr(agent_runtime_profile, "to_dict")
        else dict(agent_runtime_profile or {})
        if isinstance(agent_runtime_profile, dict)
        else {}
    )
    allowed_operations = tuple(
        str(item).strip()
        for item in list(operation_authorization.get("allowed_operations") or profile_payload.get("allowed_operations") or [])
        if str(item).strip()
    )
    allowed_memory_scopes = tuple(
        str(item).strip()
        for item in list(agent_profile_payload.get("allowed_memory_scopes") or [])
        if str(item).strip()
    )
    allowed_context_sections = tuple(
        str(item).strip()
        for item in list(agent_profile_payload.get("allowed_context_sections") or [])
        if str(item).strip()
    )
    memory_policy = dict(profile.memory_policy or {})
    context_policy = dict(profile.context_policy or {})
    task_lifecycle_policy = dict(profile.task_lifecycle_policy or {})
    subagent_policy = dict(profile.subagent_policy or {})
    environment_lifecycle = dict(task_environment.get("lifecycle_policy") or {})
    environment_memory_space = dict(task_environment.get("memory_space") or {})
    control = dict(control_capabilities or {})
    selected_skill_ids = tuple(
        str(item).strip()
        for item in list(dict(skill_activation or {}).get("selected_skill_ids") or [])
        if str(item).strip()
    )
    tools_by_capability_group = _tools_by_capability_group(available_tools)

    may_call_tools = bool(control.get("may_call_tools") is True and visible_tool_names)
    may_request_task_run = bool(control.get("may_request_task_run") is True)
    may_control_active_work = bool(control.get("may_control_active_work") is True)
    may_use_subagents = bool(control.get("may_use_subagents") is True)

    def system_group_allowed(group_id: str) -> bool:
        return _system_group_enabled(context_policy, group_id, default=True)

    memory_read_enabled = _system_memory_read_enabled(
        memory_policy=memory_policy,
        allowed_memory_scopes=allowed_memory_scopes,
        environment_memory_space=environment_memory_space,
    )
    memory_write_candidate_enabled = _system_memory_write_candidate_enabled(
        memory_policy=memory_policy,
        allowed_operations=allowed_operations,
        allowed_memory_scopes=allowed_memory_scopes,
    )
    allow_long_term_memory = _system_long_term_memory_allowed(
        memory_policy=memory_policy,
        allowed_memory_scopes=allowed_memory_scopes,
    )
    exact_evidence_available = bool(
        may_call_tools
        and any(
            str(tool.get("operation_id") or "").strip()
            in {"op.read_file", "op.search_files", "op.search_text", "op.read_persisted_tool_result"}
            for tool in tuple(available_tools or ())
        )
    )
    task_contract_intake_enabled = bool(may_request_task_run and system_group_allowed("task_contract_intake"))
    react_loop_enabled = bool(
        (may_call_tools or may_use_subagents or may_control_active_work)
        and system_group_allowed("react_loop")
    )
    tool_runtime_enabled = bool(may_call_tools and system_group_allowed("tool_runtime"))
    skill_runtime_enabled = bool(skill_runtime_views and system_group_allowed("skill_runtime"))
    subagent_delegation_enabled = bool(may_use_subagents and system_group_allowed("subagent_delegation"))
    context_memory_enabled = bool(memory_read_enabled and system_group_allowed("context_memory"))
    memory_governance_enabled = bool(
        (memory_read_enabled or memory_write_candidate_enabled)
        and system_group_allowed("memory_governance")
    )
    evidence_read_enabled = bool(exact_evidence_available and system_group_allowed("evidence_read"))
    evidence_alignment_enabled = bool(
        (may_call_tools or may_use_subagents)
        and system_group_allowed("evidence_alignment")
    )
    reasoning_projection_enabled = system_group_allowed("reasoning_projection")
    lifecycle_resume_steer_enabled = bool(
        (may_control_active_work or may_request_task_run or bool(environment_lifecycle))
        and system_group_allowed("lifecycle_resume_steer")
    )
    output_projection_enabled = system_group_allowed("output_projection")
    recovery_closeout_enabled = system_group_allowed("recovery_closeout")

    system_groups = {
        "task_contract_intake": _system_group_manifest(
            enabled=task_contract_intake_enabled,
            capability_groups=_SYSTEM_GROUP_CAPABILITY_GROUPS["task_contract_intake"],
            config={
                "accept_task_contract": True,
                "request_task_run_enabled": may_request_task_run,
                "contract_strictness": "canonical_task_run_contract_seed",
                "task_lifecycle_policy": task_lifecycle_policy,
            },
            prompt_resources=(
                "runtime.rule.turn_decision_alignment",
                *_lifecycle_prompt_refs(prompt_mount_payload, "task_run_handoff"),
            ),
            context_segments=("task_run_contract_stable", "task_prompt_contract"),
            feedback_channels=("contract_gap_repair", "task_run_handoff_repair"),
        ),
        "react_loop": _system_group_manifest(
            enabled=react_loop_enabled,
            capability_groups=_SYSTEM_GROUP_CAPABILITY_GROUPS["react_loop"],
            config={
                "mode": "tool_calling" if may_call_tools else "no_tool_action_control",
                "supports_json_action_protocol": bool(control.get("supports_json_action_protocol") is True),
                "requires_json_action_protocol": bool(control.get("requires_json_action_protocol") is True),
            },
            prompt_resources=("runtime.rule.tool_use", "runtime.rule.multi_tool_scheduling"),
            context_segments=("single_agent_turn_tool_call", "tool_transcript_delta", "single_agent_turn_followup_action_contract"),
            feedback_channels=("tool_result", "tool_error", "tool_permission_denial", "followup_prompt_payload"),
        ),
        "tool_runtime": _system_group_manifest(
            enabled=tool_runtime_enabled,
            capability_groups=_SYSTEM_GROUP_CAPABILITY_GROUPS["tool_runtime"],
            config={
                "visible_tool_names": list(visible_tool_names),
                "tool_count": len(visible_tool_names),
                "filtered_tool_count": len(filtered_tools),
            },
            prompt_resources=("tool.guidance.read_file", "tool.guidance.read_persisted_tool_result", "tool.guidance.edit_file", "tool.guidance.write_file", "tool.guidance.terminal_powershell"),
            context_segments=("tool_index_stable", "tool_transcript_delta"),
            feedback_channels=("tool_result", "tool_error", "tool_permission_denial"),
        ),
        "skill_runtime": _system_group_manifest(
            enabled=skill_runtime_enabled,
            capability_groups=_SYSTEM_GROUP_CAPABILITY_GROUPS["skill_runtime"],
            config={
                "visible_skill_count": len(skill_runtime_views),
                "selected_skill_ids": list(selected_skill_ids),
                "selection_source": str(dict(skill_activation or {}).get("selection_source") or ""),
            },
            prompt_resources=tuple(str(item.get("prompt_ref") or item.get("skill_id") or "") for item in tuple(skill_runtime_views or ())),
            context_segments=("active_skills",),
            feedback_channels=("skill_output_rule", "skill_failure_repair"),
        ),
        "subagent_delegation": _system_group_manifest(
            enabled=subagent_delegation_enabled,
            capability_groups=_SYSTEM_GROUP_CAPABILITY_GROUPS["subagent_delegation"],
            config={
                "allowed_subagent_ids": list(subagent_policy.get("allowed_subagent_ids") or []),
                "max_subagent_runs_per_task": int(subagent_policy.get("max_subagent_runs_per_task") or 0),
                "max_active_subagents": int(subagent_policy.get("max_active_subagents") or 0),
                "context_policy": str(subagent_policy.get("context_policy") or "summary_and_refs_only"),
                "result_policy": str(subagent_policy.get("result_policy") or "observation_refs_only"),
                "allow_nested_subagents": bool(subagent_policy.get("allow_nested_subagents") is True),
            },
            prompt_resources=(
                "tool.guidance.subagent",
                *_lifecycle_prompt_refs(prompt_mount_payload, "subagent_delegation", "subagent_result_integration"),
            ),
            context_segments=("single_agent_turn_tool_call", "tool_transcript_delta"),
            feedback_channels=("subagent_result", "subagent_failure", "subagent_closeout"),
        ),
        "context_memory": _system_group_manifest(
            enabled=context_memory_enabled,
            capability_groups=_SYSTEM_GROUP_CAPABILITY_GROUPS["context_memory"],
            config={
                "allowed_memory_scopes": list(allowed_memory_scopes),
                "allowed_context_sections": list(allowed_context_sections),
                "history_scope": str(context_policy.get("history_scope") or ""),
                "provider_visible_replay": True,
            },
            prompt_resources=_lifecycle_prompt_refs(prompt_mount_payload, "memory_read_context"),
            context_segments=("context_memory_prefix", "context_append", "runtime_memory_context", "session_history", "task_state_replay_entry"),
            feedback_channels=("memory_read_recovery", "provider_visible_ledger_recovery"),
        ),
        "memory_governance": _system_group_manifest(
            enabled=memory_governance_enabled,
            capability_groups=_SYSTEM_GROUP_CAPABILITY_GROUPS["memory_governance"],
            config={
                "read_enabled": memory_read_enabled,
                "write_candidate_enabled": memory_write_candidate_enabled,
                "allow_long_term_memory": allow_long_term_memory,
                "write_scope": str(memory_policy.get("write_scope") or ""),
                "writeback_policy": str(memory_policy.get("writeback_policy") or memory_policy.get("write_scope") or ""),
            },
            prompt_resources=_lifecycle_prompt_refs(prompt_mount_payload, "memory_write_handoff"),
            context_segments=("runtime_memory_context", "session_pinned_facts_context"),
            feedback_channels=("memory_write_candidate", "memory_write_rejected", "memory_conflict"),
        ),
        "evidence_read": _system_group_manifest(
            enabled=evidence_read_enabled,
            capability_groups=_SYSTEM_GROUP_CAPABILITY_GROUPS["evidence_read"],
            config={"exact_read_evidence": evidence_read_enabled},
            prompt_resources=("tool.guidance.read_file", *_lifecycle_prompt_refs(prompt_mount_payload, "verification_gate")),
            context_segments=("read_evidence_context", "evidence_index_cursor", "attachment_context_index", "editor_context_index"),
            feedback_channels=("evidence_missing", "evidence_recovery"),
        ),
        "evidence_alignment": _system_group_manifest(
            enabled=evidence_alignment_enabled,
            capability_groups=_SYSTEM_GROUP_CAPABILITY_GROUPS["evidence_alignment"],
            config={
                "evidence_delta_summary": evidence_alignment_enabled,
                "exact_read_evidence": evidence_read_enabled,
                "answer_contract": "answer_evidence_alignment_contract",
                "source_authority": "runtime.memory.evidence_delta_summary",
            },
            prompt_resources=("runtime.rule.answer_evidence_alignment",),
            context_segments=(
                "evidence_delta_summary",
                "evidence_semantic_summary",
                "read_coverage_projection",
                "execution_action_evidence",
                "answer_evidence_alignment_contract",
            ),
            feedback_channels=("evidence_boundary", "answer_evidence_alignment", "answer_alignment_feedback"),
        ),
        "reasoning_projection": _system_group_manifest(
            enabled=reasoning_projection_enabled,
            capability_groups=_SYSTEM_GROUP_CAPABILITY_GROUPS["reasoning_projection"],
            config={
                "provider_protocol_reasoning_replay": True,
                "public_reasoning_default": False,
                "reasoning_full_text_requires_explicit_opt_in": True,
            },
            prompt_resources=(),
            context_segments=("reasoning_trace_projection", "provider_reasoning_projection"),
            feedback_channels=("reasoning_trace_status", "reasoning_projection_state"),
        ),
        "lifecycle_resume_steer": _system_group_manifest(
            enabled=lifecycle_resume_steer_enabled,
            capability_groups=_SYSTEM_GROUP_CAPABILITY_GROUPS["lifecycle_resume_steer"],
            config={
                "may_control_active_work": may_control_active_work,
                "steer_append_only": True,
                "resume_replay_required": True,
            },
            prompt_resources=_lifecycle_prompt_refs(prompt_mount_payload, "active_work_control", "user_steer_contract_revision"),
            context_segments=("single_agent_turn_user_steer_context", "user_steering_context_append", "runtime_control_signal_tail"),
            feedback_channels=("resume_recovery", "user_steer_repair", "closeout_control"),
        ),
        "output_projection": _system_group_manifest(
            enabled=output_projection_enabled,
            capability_groups=_SYSTEM_GROUP_CAPABILITY_GROUPS["output_projection"],
            config={"final_commit_required": True, "activity_archive": True},
            prompt_resources=_lifecycle_prompt_refs(prompt_mount_payload, "finalization"),
            context_segments=("dynamic_projection",),
            feedback_channels=("final_answer_boundary", "projection_closeout"),
        ),
        "recovery_closeout": _system_group_manifest(
            enabled=recovery_closeout_enabled,
            capability_groups=_SYSTEM_GROUP_CAPABILITY_GROUPS["recovery_closeout"],
            config={"structured_failure_required": True, "recovery_package_allowed": True},
            prompt_resources=_lifecycle_prompt_refs(prompt_mount_payload, "tool_observation_recovery", "compaction_handoff"),
            context_segments=("provider_visible_ledger_recovery_checkpoint", "recovery_context_package", "recent_work_outcome"),
            feedback_channels=("structured_failure", "recovery_package", "closeout_control"),
        ),
    }
    system_groups.update(
        _tool_capability_system_group_manifests(
            tools_by_capability_group=tools_by_capability_group,
            may_call_tools=tool_runtime_enabled,
            prompt_mount_plan=prompt_mount_payload,
        )
    )
    context_capability_groups = _compiled_context_capability_groups(system_groups)
    disabled_context_capability_groups = [
        group for group in _CONTEXT_CAPABILITY_GROUPS if not context_capability_groups.get(group)
    ]
    seed = {
        "profile_ref": profile.profile_ref,
        "environment_id": str(task_environment.get("environment_id") or task_environment.get("requested_environment_id") or ""),
        "system_groups": {
            key: {
                "enabled": bool(value.get("enabled") is True),
                "config": dict(value.get("config") or {}),
            }
            for key, value in system_groups.items()
        },
        "allowed_operations": list(allowed_operations),
        "visible_tool_names": list(visible_tool_names),
        "selected_skill_ids": list(selected_skill_ids),
        "tool_capability_groups": sorted(tools_by_capability_group),
    }
    manifest_id = "syswire:" + _stable_payload_hash(seed)[:16]
    return {
        "manifest_id": manifest_id,
        "authority": "harness.runtime.system_wiring_manifest",
        "source_profile_ref": profile.profile_ref,
        "agent_profile_ref": str(agent_profile_payload.get("agent_profile_id") or ""),
        "environment_ref": str(task_environment.get("environment_id") or task_environment.get("requested_environment_id") or ""),
        "provider_physical_model": "",
        "system_groups": system_groups,
        "compiled": {
            "context_capability_groups": context_capability_groups,
            "context_capability_profile": {
                "profile_id": "ctxcap:syswire:" + _stable_payload_hash(
                    {
                        "manifest_seed": seed,
                        "enabled_groups": [group for group in _CONTEXT_CAPABILITY_GROUPS if context_capability_groups.get(group)],
                        "disabled_groups": disabled_context_capability_groups,
                    }
                )[:16],
                "enabled_groups": [group for group in _CONTEXT_CAPABILITY_GROUPS if context_capability_groups.get(group)],
                "disabled_groups": disabled_context_capability_groups,
                "provider_physical_model": "",
                "authority": "harness.runtime.system_wiring_manifest.context_capability_profile",
            },
            "prompt_resource_gates": _compiled_prompt_resource_gates(system_groups),
            "context_segment_gates": _compiled_context_segment_gates(system_groups),
            "tool_operation_gates": {
                "allowed_operations": list(allowed_operations),
                "visible_tool_names": list(visible_tool_names),
                "tool_capability_groups": sorted(tools_by_capability_group),
                "filtered_tools": [dict(item) for item in filtered_tools],
            },
            "skill_gates": {
                "visible_skill_ids": [
                    str(item.get("skill_id") or "").strip()
                    for item in tuple(skill_runtime_views or ())
                    if str(item.get("skill_id") or "").strip()
                ],
                "selected_skill_ids": list(selected_skill_ids),
                "rejected_skill_ids": list(dict(skill_activation or {}).get("rejected_skill_ids") or []),
            },
            "feedback_channels": _compiled_feedback_channels(system_groups),
        },
        "source_refs": {
            "agent_runtime_profile": str(agent_profile_payload.get("agent_profile_id") or profile.profile_ref),
            "runtime_assembly_profile": profile.profile_ref,
            "task_environment": str(task_environment.get("environment_id") or task_environment.get("requested_environment_id") or ""),
            "operation_authorization": str(operation_authorization.get("authority") or "harness.runtime.operation_authorization"),
        },
    }


def _system_group_manifest(
    *,
    enabled: bool,
    capability_groups: tuple[str, ...],
    config: dict[str, Any],
    prompt_resources: tuple[str, ...],
    context_segments: tuple[str, ...],
    feedback_channels: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "enabled": bool(enabled),
        "config": dict(config or {}),
        "capability_groups": [str(item) for item in tuple(capability_groups or ()) if str(item)],
        "prompt_resources": [str(item) for item in tuple(prompt_resources or ()) if str(item)],
        "context_segments": [str(item) for item in tuple(context_segments or ()) if str(item)],
        "feedback_channels": [str(item) for item in tuple(feedback_channels or ()) if str(item)],
    }


def _tools_by_capability_group(available_tools: tuple[dict[str, Any], ...]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for raw_tool in tuple(available_tools or ()):
        if not isinstance(raw_tool, dict):
            continue
        tool = dict(raw_tool)
        group_id = _capability_group_for_tool(tool)
        if group_id not in _CAPABILITY_GROUP_CATALOG:
            continue
        result.setdefault(group_id, []).append(
            {
                "tool_name": str(tool.get("tool_name") or tool.get("name") or "").strip(),
                "operation_id": str(tool.get("operation_id") or "").strip(),
            }
        )
    return {key: value for key, value in result.items() if value}


def _tool_capability_system_group_manifests(
    *,
    tools_by_capability_group: dict[str, list[dict[str, Any]]],
    may_call_tools: bool,
    prompt_mount_plan: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for capability_group, config in _TOOL_CAPABILITY_SYSTEM_GROUPS.items():
        tools = [dict(item) for item in list(tools_by_capability_group.get(capability_group) or []) if isinstance(item, dict)]
        group_id = f"tool_{capability_group}"
        prompt_resources = tuple(config.get("prompt_resources") or ())
        if capability_group == "task_planning":
            prompt_resources = (*prompt_resources, *_lifecycle_prompt_refs(prompt_mount_plan, "plan_gate"))
        result[group_id] = _system_group_manifest(
            enabled=bool(may_call_tools and tools),
            capability_groups=tuple(config.get("capability_groups") or ()),
            config={
                "capability_group": capability_group,
                "tool_count": len(tools),
                "tool_names": [str(item.get("tool_name") or "") for item in tools if str(item.get("tool_name") or "")],
                "operation_ids": [str(item.get("operation_id") or "") for item in tools if str(item.get("operation_id") or "")],
            },
            prompt_resources=prompt_resources,
            context_segments=tuple(config.get("context_segments") or ()),
            feedback_channels=tuple(config.get("feedback_channels") or ()),
        )
    return result


def _lifecycle_prompt_refs(prompt_mount_plan: dict[str, Any], *slots: str) -> tuple[str, ...]:
    defaults = dict(dict(prompt_mount_plan or {}).get("lifecycle_prompt_defaults") or {})
    overrides = dict(dict(prompt_mount_plan or {}).get("lifecycle_prompt_overrides") or {})
    refs: list[str] = []
    for slot in slots:
        key = str(slot or "").strip()
        ref = str(overrides.get(key) or defaults.get(key) or "").strip()
        if ref:
            refs.append(ref)
    return _dedupe_strings(tuple(refs))


def _compiled_context_capability_groups(system_groups: dict[str, dict[str, Any]]) -> dict[str, bool]:
    enabled: set[str] = {"static_identity", "runtime_contracts"}
    for group_payload in system_groups.values():
        if not bool(dict(group_payload or {}).get("enabled") is True):
            continue
        enabled.update(
            str(item)
            for item in list(dict(group_payload or {}).get("capability_groups") or [])
            if str(item)
        )
    return {group: group in enabled for group in _CONTEXT_CAPABILITY_GROUPS}


def _system_group_enabled(context_policy: dict[str, Any], group_id: str, *, default: bool) -> bool:
    group = str(group_id or "").strip()
    if not group:
        return default
    policy = dict(context_policy or {})
    for container_key in ("system_groups", "system_group_policy", "capability_systems"):
        container = policy.get(container_key)
        if not isinstance(container, dict):
            continue
        if group in container:
            return _policy_switch_enabled(container.get(group), default=default)
    for key in (group, f"{group}_enabled", f"include_{group}"):
        if key in policy:
            return _policy_switch_enabled(policy.get(key), default=default)
    return default


def _policy_switch_enabled(value: Any, *, default: bool) -> bool:
    if isinstance(value, dict):
        if "enabled" in value:
            return _policy_switch_enabled(value.get("enabled"), default=default)
        if "mode" in value:
            return _policy_switch_enabled(value.get("mode"), default=default)
        return default
    if isinstance(value, bool):
        return value
    normalized = str(value or "").strip().lower()
    if not normalized or normalized in {"default", "inherit"}:
        return default
    if normalized in {"disabled", "disable", "off", "false", "0", "none", "omit", "omitted", "hidden"}:
        return False
    if normalized in {"enabled", "enable", "on", "true", "1", "yes", "include", "included", "visible"}:
        return True
    return default


def _compiled_prompt_resource_gates(system_groups: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for system_group, group_payload in system_groups.items():
        enabled = bool(dict(group_payload or {}).get("enabled") is True)
        for prompt_ref in list(dict(group_payload or {}).get("prompt_resources") or []):
            ref = str(prompt_ref or "").strip()
            if not ref:
                continue
            gate = result.setdefault(
                ref,
                {
                    "enabled": False,
                    "system_groups": [],
                    "disabled_system_groups": [],
                },
            )
            if enabled:
                gate["enabled"] = True
                gate["system_groups"] = _dedupe_strings([*list(gate.get("system_groups") or []), system_group])
            else:
                gate["disabled_system_groups"] = _dedupe_strings(
                    [*list(gate.get("disabled_system_groups") or []), system_group]
                )
    return result


def _compiled_context_segment_gates(system_groups: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for system_group, group_payload in system_groups.items():
        enabled = bool(dict(group_payload or {}).get("enabled") is True)
        for segment in list(dict(group_payload or {}).get("context_segments") or []):
            key = str(segment or "").strip()
            if not key:
                continue
            gate = result.setdefault(
                key,
                {
                    "enabled": False,
                    "system_groups": [],
                    "disabled_system_groups": [],
                },
            )
            if enabled:
                gate["enabled"] = True
                gate["system_groups"] = _dedupe_strings([*list(gate.get("system_groups") or []), system_group])
            else:
                gate["disabled_system_groups"] = _dedupe_strings(
                    [*list(gate.get("disabled_system_groups") or []), system_group]
                )
    return result


def _compiled_feedback_channels(system_groups: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for system_group, group_payload in system_groups.items():
        enabled = bool(dict(group_payload or {}).get("enabled") is True)
        for channel in list(dict(group_payload or {}).get("feedback_channels") or []):
            key = str(channel or "").strip()
            if not key:
                continue
            gate = result.setdefault(
                key,
                {
                    "enabled": False,
                    "system_groups": [],
                    "disabled_system_groups": [],
                },
            )
            if enabled:
                gate["enabled"] = True
                gate["system_groups"] = _dedupe_strings([*list(gate.get("system_groups") or []), system_group])
            else:
                gate["disabled_system_groups"] = _dedupe_strings(
                    [*list(gate.get("disabled_system_groups") or []), system_group]
                )
    return result


def _system_memory_read_enabled(
    *,
    memory_policy: dict[str, Any],
    allowed_memory_scopes: tuple[str, ...],
    environment_memory_space: dict[str, Any],
) -> bool:
    read_scope = str(memory_policy.get("read_scope") or memory_policy.get("enabled") or "").strip().lower()
    if read_scope in {"disabled", "disable", "off", "false", "0", "none"}:
        return False
    return bool(
        allowed_memory_scopes
        or read_scope
        or environment_memory_space.get("retrieval_index_refs")
        or environment_memory_space.get("memory_refs")
    )


def _system_memory_write_candidate_enabled(
    *,
    memory_policy: dict[str, Any],
    allowed_operations: tuple[str, ...],
    allowed_memory_scopes: tuple[str, ...],
) -> bool:
    write_scope = str(memory_policy.get("write_scope") or memory_policy.get("write_enabled") or "").strip().lower()
    if write_scope in {"disabled", "disable", "off", "false", "0", "none"}:
        return False
    return bool(
        "op.memory_write_candidate" in set(allowed_operations)
        or any(scope.endswith("_write_candidate") for scope in allowed_memory_scopes)
    )


def _system_long_term_memory_allowed(
    *,
    memory_policy: dict[str, Any],
    allowed_memory_scopes: tuple[str, ...],
) -> bool:
    if bool(memory_policy.get("allow_long_term_memory") is True):
        return True
    long_term_scopes = {
        "long_term_candidate",
        "durable_memory_write_candidate",
        "formal_memory_write_candidate",
        "formal_memory_read",
    }
    return bool(long_term_scopes.intersection(set(allowed_memory_scopes)))


def _capability_group_for_tool(tool: dict[str, Any]) -> str:
    operation_id = str(tool.get("operation_id") or "").strip()
    if operation_id in _TOOL_CAPABILITY_GROUP_BY_OPERATION:
        return _TOOL_CAPABILITY_GROUP_BY_OPERATION[operation_id]
    tool_name = str(tool.get("tool_name") or "").strip()
    if "browser" in tool_name:
        return "browser_use"
    if "web" in tool_name or "fetch" in tool_name:
        return "web_research"
    if "git" in tool_name:
        return "source_control"
    if "write" in tool_name or "image" in tool_name:
        return "artifact_generation"
    if "shell" in tool_name or "python_repl" in tool_name:
        return "shell_execution"
    return "general_task"


def _stable_payload_hash(value: Any) -> str:
    payload = json.dumps(_json_stable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()


def _json_stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_stable(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_json_stable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def _dedupe_strings(values: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return tuple(result)


def _resolved_runtime_policy(
    *,
    agent_runtime_profile: Any | None,
    runtime_contract: dict[str, Any],
) -> dict[str, Any]:
    profile_metadata = dict(getattr(agent_runtime_profile, "metadata", {}) or {})
    runtime_profile = dict(runtime_contract.get("runtime_profile") or {})
    explicit_policy = _merge_dicts(
        profile_metadata.get("runtime_policy"),
        profile_metadata.get("execution_policy"),
        runtime_profile.get("runtime_policy"),
        runtime_profile.get("execution_policy"),
        runtime_contract.get("runtime_policy"),
        runtime_contract.get("execution_policy"),
    )
    template_policy = _prompt_orchestration_template_policy(
        agent_runtime_profile=agent_runtime_profile,
        runtime_contract=runtime_contract,
        explicit_policy=explicit_policy,
    )
    return _deep_merge_dicts(
        _BASE_RUNTIME_POLICY,
        template_policy,
        explicit_policy,
    )


def _prompt_orchestration_template_policy(
    *,
    agent_runtime_profile: Any | None,
    runtime_contract: dict[str, Any],
    explicit_policy: dict[str, Any],
) -> dict[str, Any]:
    profile_metadata = dict(getattr(agent_runtime_profile, "metadata", {}) or {})
    runtime_profile = dict(runtime_contract.get("runtime_profile") or {})
    runtime_profile_policy = dict(runtime_profile.get("runtime_policy") or runtime_profile.get("execution_policy") or {})
    prompt_policy = dict(explicit_policy.get("prompt_policy") or {})
    runtime_profile_prompt_policy = dict(runtime_profile.get("prompt_policy") or {})
    runtime_contract_prompt_policy = dict(runtime_contract.get("prompt_policy") or runtime_contract.get("runtime_prompt_policy") or {})
    template_id = _first_string(
        runtime_contract.get("prompt_template_id"),
        runtime_profile.get("prompt_template_id"),
        runtime_contract_prompt_policy.get("template_id"),
        runtime_profile_prompt_policy.get("template_id"),
        explicit_policy.get("prompt_template_id"),
        prompt_policy.get("template_id"),
        profile_metadata.get("prompt_template_id"),
    )
    if not template_id:
        return {}
    template = _PROMPT_ORCHESTRATION_TEMPLATE_POLICIES.get(template_id)
    if not template:
        return {}
    policy = _deep_merge_dicts(template)
    resolved_prompt_policy = dict(policy.get("prompt_policy") or {})
    resolved_prompt_policy.setdefault("template_id", template_id)
    resolved_prompt_policy.setdefault("template_selection_source", _prompt_template_selection_source(
        template_id=template_id,
        runtime_contract=runtime_contract,
        runtime_profile=runtime_profile,
        runtime_profile_policy=runtime_profile_policy,
        runtime_contract_prompt_policy=runtime_contract_prompt_policy,
        runtime_profile_prompt_policy=runtime_profile_prompt_policy,
        prompt_policy=prompt_policy,
        profile_metadata=profile_metadata,
    ))
    policy["prompt_policy"] = resolved_prompt_policy
    return policy


def _prompt_template_selection_source(
    *,
    template_id: str,
    runtime_contract: dict[str, Any],
    runtime_profile: dict[str, Any],
    runtime_profile_policy: dict[str, Any],
    runtime_contract_prompt_policy: dict[str, Any],
    runtime_profile_prompt_policy: dict[str, Any],
    prompt_policy: dict[str, Any],
    profile_metadata: dict[str, Any],
) -> str:
    if str(runtime_contract.get("prompt_template_id") or "").strip() == template_id:
        return "runtime_contract.prompt_template_id"
    if str(runtime_profile.get("prompt_template_id") or "").strip() == template_id:
        return "runtime_contract.runtime_profile.prompt_template_id"
    if str(runtime_contract_prompt_policy.get("template_id") or "").strip() == template_id:
        return "runtime_contract.prompt_policy.template_id"
    if str(runtime_profile_prompt_policy.get("template_id") or "").strip() == template_id:
        return "runtime_contract.runtime_profile.prompt_policy.template_id"
    if str(runtime_profile_policy.get("prompt_template_id") or "").strip() == template_id:
        return "runtime_policy.prompt_template_id"
    if str(prompt_policy.get("template_id") or "").strip() == template_id:
        return "runtime_policy.prompt_policy.template_id"
    if str(profile_metadata.get("prompt_template_id") or "").strip() == template_id:
        return "agent_runtime_profile.metadata.prompt_template_id"
    return "prompt_orchestration_template"


def _resolve_runtime_task_environment(
    *,
    backend_dir: Path,
    environment_binding: dict[str, Any] | None = None,
    agent_runtime_profile: Any | None = None,
    runtime_contract: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    registry = task_environment_registry_from_backend_dir(backend_dir)
    binding = dict(environment_binding or {})
    explicit_binding = _first_string(
        binding.get("task_environment_id"),
        binding.get("environment_id"),
        dict(binding.get("task_environment") or {}).get("environment_id")
        if isinstance(binding.get("task_environment"), dict)
        else binding.get("task_environment"),
    )
    explicit = _first_string(
        explicit_binding,
        runtime_contract.get("task_environment_id"),
        runtime_contract.get("environment_id"),
        dict(runtime_contract.get("task_environment") or {}).get("environment_id")
        if isinstance(runtime_contract.get("task_environment"), dict)
        else runtime_contract.get("task_environment"),
        dict(runtime_contract.get("runtime_profile") or {}).get("task_environment_id"),
        dict(runtime_contract.get("runtime_profile") or {}).get("environment_id"),
    )
    agent_default = _agent_profile_default_environment_id(agent_runtime_profile)
    environment_id = explicit or agent_default or "env.general.workspace"
    registry.require(environment_id)
    environment_payload = build_task_environment_catalog(registry=registry).runtime_environment_payload(environment_id)
    source = (
        "environment_binding"
        if explicit_binding
        else "runtime_contract"
        if explicit
        else "agent_runtime_profile"
        if agent_default
        else "fallback_default"
    )
    return (
        {
            **environment_payload,
            "requested_environment_id": environment_id,
        },
        {
            "requested_environment_id": environment_id,
            "resolved_environment_id": str(environment_payload.get("environment_id") or ""),
            "environment_group_id": str(dict(environment_payload.get("group") or {}).get("group_id") or ""),
            "source": source,
        },
    )


def _agent_profile_default_environment_id(agent_runtime_profile: Any | None) -> str:
    metadata = dict(getattr(agent_runtime_profile, "metadata", {}) or {})
    runtime_policy = dict(metadata.get("runtime_policy") or metadata.get("execution_policy") or {})
    context_policy = dict(runtime_policy.get("context_policy") or {})
    return _first_string(
        metadata.get("default_task_environment_id"),
        metadata.get("task_environment_id"),
        runtime_policy.get("default_task_environment_id"),
        runtime_policy.get("task_environment_id"),
        context_policy.get("default_task_environment_id"),
    )


def _profile_operations(agent_runtime_profile: Any | None) -> tuple[str, ...]:
    operations = tuple(
        str(item).strip()
        for item in tuple(getattr(agent_runtime_profile, "allowed_operations", ()) or ())
        if str(item).strip()
    )
    if operations:
        return operations
    return ("op.model_response",)


def _control_capabilities_for_runtime(
    *,
    profile: RuntimeAssemblyProfile,
    runtime_contract: dict[str, Any],
    environment_payload: dict[str, Any],
    visible_tool_names: tuple[str, ...],
    engagement_contract: dict[str, Any],
) -> dict[str, Any]:
    explicit = _merge_dicts(
        runtime_contract.get("control_capabilities"),
        dict(runtime_contract.get("runtime_profile") or {}).get("control_capabilities"),
        dict(runtime_contract.get("runtime_profile") or {}).get("runtime_control_capabilities"),
    )
    task_lifecycle = dict(profile.task_lifecycle_policy or {})
    context_policy = dict(profile.context_policy or {})
    subagent = dict(profile.subagent_policy or {})
    environment_kind = str(environment_payload.get("environment_kind") or "").strip()
    lifecycle_policy = dict(environment_payload.get("lifecycle_policy") or {})
    active_work_context = str(
        context_policy.get("active_work_context")
        or context_policy.get("task_run_context")
        or context_policy.get("task_context")
        or ""
    ).strip().lower()
    active_work_disabled = active_work_context in {"disabled", "none", "off", "false", "0", "readonly"}
    environment_disables_tasks = (
        environment_kind == "chat"
        or lifecycle_policy.get("request_task_run") is False
        or str(lifecycle_policy.get("task_lifecycle_prompts") or "").strip().lower() == "disabled"
    )
    environment_disables_active_work = (
        environment_kind == "chat"
        or lifecycle_policy.get("active_work_control") is False
    )
    task_run_allowed = task_lifecycle.get("request_task_run") is not False
    subagent_enabled = bool(subagent.get("enabled") is True)
    may_emit_assistant_message = bool(explicit.get("may_emit_assistant_message", True) is not False)
    may_call_tools = bool(
        explicit.get("may_call_tools")
        if "may_call_tools" in explicit
        else bool(visible_tool_names)
    )
    may_request_task_run = bool(
        (
            explicit.get("may_request_task_run")
            if "may_request_task_run" in explicit
            else task_run_allowed
        )
        and not environment_disables_tasks
    )
    may_control_active_work = bool(
        (
            explicit.get("may_control_active_work")
            if "may_control_active_work" in explicit
            else not active_work_disabled
        )
        and not environment_disables_active_work
    )
    may_use_subagents = bool(
        (
            explicit.get("may_use_subagents")
            if "may_use_subagents" in explicit
            else subagent_enabled
        )
    )
    has_explicit_contract = bool(
        engagement_contract
        or runtime_contract.get("task_run_contract")
        or runtime_contract.get("task_run_contract_seed")
        or runtime_contract.get("engagement_contract")
    )
    requires_json_action_protocol_explicit = "requires_json_action_protocol" in explicit
    supports_json_action_protocol = bool(
        may_call_tools
        or may_request_task_run
        or may_control_active_work
        or may_use_subagents
        or has_explicit_contract
    )
    requires_json_action_protocol = bool(
        explicit.get("requires_json_action_protocol")
        if requires_json_action_protocol_explicit
        else False
    )
    return {
        "authority": "harness.runtime.control_capabilities",
        "may_emit_assistant_message": may_emit_assistant_message,
        "may_call_tools": may_call_tools,
        "may_request_task_run": may_request_task_run,
        "may_control_active_work": may_control_active_work,
        "may_use_subagents": may_use_subagents,
        "supports_json_action_protocol": supports_json_action_protocol,
        "requires_json_action_protocol": requires_json_action_protocol,
        "requires_json_action_protocol_explicit": requires_json_action_protocol_explicit,
        "has_explicit_contract": has_explicit_contract,
        "visible_tool_count": len(visible_tool_names),
    }


def _tool_transport_policy_for_runtime(
    *,
    profile: RuntimeAssemblyProfile,
    runtime_contract: dict[str, Any],
    model_selection: dict[str, Any],
    visible_tool_names: tuple[str, ...],
) -> dict[str, Any]:
    runtime_profile = dict(runtime_contract.get("runtime_profile") or {})
    explicit = _merge_dicts(
        dict(profile.tool_policy or {}).get("tool_transport_policy"),
        dict(profile.tool_policy or {}).get("transport_policy"),
        runtime_contract.get("tool_transport_policy"),
        runtime_contract.get("tool_transport"),
        runtime_profile.get("tool_transport_policy"),
        runtime_profile.get("tool_transport"),
        dict(model_selection or {}).get("tool_transport_policy"),
        dict(model_selection or {}).get("tool_transport"),
    )
    requested_mode = _normalize_tool_transport_mode(
        _first_string(
            explicit.get("transport_mode"),
            explicit.get("mode"),
            explicit.get("tool_call_transport"),
            explicit.get("ordinary_tool_transport"),
        )
    )
    provider_native_explicit = (
        "provider_native_tools_enabled" in explicit
        or "native_tools_enabled" in explicit
        or "provider_tools_enabled" in explicit
    )
    provider_native_requested = bool(
        explicit.get("provider_native_tools_enabled")
        or explicit.get("native_tools_enabled")
        or explicit.get("provider_tools_enabled")
    )
    if requested_mode == "provider_native" or (not requested_mode and provider_native_explicit and provider_native_requested):
        transport_mode = "provider_native"
    else:
        transport_mode = "json_action"
    if provider_native_explicit and not provider_native_requested:
        transport_mode = "json_action"
    provider_native_enabled = bool(transport_mode == "provider_native" and visible_tool_names)
    return {
        "authority": "harness.runtime.tool_transport_policy",
        "transport_contract_family": "tool_call_action",
        "agent_visible_semantics": "tool_call_action",
        "supported_transport_modes": ["json_action", "provider_native"],
        "selected_transport_mode": transport_mode,
        "transport_mode": transport_mode,
        "provider_native_tools_enabled": provider_native_enabled,
        "json_action_tool_call_enabled": bool(visible_tool_names),
        "control_action_transport": "json_action",
        "provider_native_control_actions_enabled": False,
        "transport_sidecar_visibility": "runtime_private",
        "transport_sidecar_scope": "current_provider_request",
        "cache_contract": {
            "message_prefix_component": False,
            "context_memory_component": False,
            "sidecar_cache_role": "never_replay_as_context",
        },
        "visible_tool_count": len(visible_tool_names),
    }


def _normalize_tool_transport_mode(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_")
    if text in {"provider_native", "native", "native_tools", "provider_tools", "tools_sidecar"}:
        return "provider_native"
    if text in {"json_action", "json", "structured_json", "tool_call_action", "assistant_message"}:
        return "json_action"
    return ""


def _subagent_policy(*, agent_runtime_profile: Any | None, policy: dict[str, Any]) -> dict[str, Any]:
    profile_policy = getattr(agent_runtime_profile, "subagent_policy", None)
    profile_payload = profile_policy.to_dict() if hasattr(profile_policy, "to_dict") else dict(profile_policy or {})
    allowed_ids = normalize_agent_id_sequence(_string_tuple(profile_payload.get("allowed_subagent_ids")))
    policy_enabled = policy.get("enabled")
    profile_enabled = bool(profile_payload.get("enabled") is True)
    enabled = profile_enabled if policy_enabled is None else bool(policy_enabled is True and profile_enabled)
    return {
        **profile_payload,
        **dict(policy or {}),
        "enabled": enabled and bool(allowed_ids),
        "allowed_subagent_ids": list(allowed_ids),
        "max_subagent_runs_per_task": max(0, int(profile_payload.get("max_subagent_runs_per_task") or 0)),
        "max_active_subagents": max(0, int(profile_payload.get("max_active_subagents") or 0)),
        "context_policy": str(profile_payload.get("context_policy") or "summary_and_refs_only"),
        "result_policy": str(profile_payload.get("result_policy") or "observation_refs_only"),
        "allow_nested_subagents": bool(profile_payload.get("allow_nested_subagents") is True),
    }


def _tool_view(*, tool_name: str, definition: Any, tool_instance: Any | None = None) -> dict[str, Any]:
    contract = getattr(definition, "contract", None)
    payload = {
        "tool_name": tool_name,
        "operation_id": str(getattr(definition, "operation_id", "") or ""),
        "display_name": str(getattr(definition, "display_name", "") or tool_name),
        "required_inputs": list(getattr(contract, "required_inputs", []) or []),
        "optional_inputs": list(getattr(contract, "optional_inputs", []) or []),
        "owner_scope": str(getattr(contract, "owner_scope", "") or "none"),
        "read_only": bool(getattr(definition, "is_read_only", False)),
        "concurrency_safe": bool(getattr(definition, "is_concurrency_safe", False)),
        "prompt_exposure_policy": str(getattr(definition, "prompt_exposure_policy", "") or "schema_only"),
    }
    output_contract = getattr(definition, "output_contract", None)
    if output_contract is not None and hasattr(output_contract, "to_dict"):
        payload["output_contract"] = output_contract.to_dict()
    resolution_contract = getattr(definition, "resolution_contract", None)
    path_field = str(getattr(resolution_contract, "path_field", "") or "").strip()
    path_kind = str(getattr(resolution_contract, "path_kind", "") or "").strip()
    if path_field or path_kind:
        payload["path_policy"] = {
            "path_field": path_field,
            "path_kind": path_kind,
        }
    description = str(getattr(tool_instance, "description", "") or "").strip()
    if description:
        payload["description"] = description
    input_schema = _tool_input_schema(tool_instance, definition=definition)
    if input_schema:
        payload["input_schema"] = input_schema
    return payload


def _tool_input_schema(tool_instance: Any | None, *, definition: Any | None = None) -> dict[str, Any]:
    args_schema = getattr(tool_instance, "args_schema", None)
    if args_schema is None:
        return _contract_input_schema(definition)
    try:
        if hasattr(args_schema, "model_json_schema"):
            schema = args_schema.model_json_schema()
        elif hasattr(args_schema, "schema"):
            schema = args_schema.schema()
        else:
            return {}
    except Exception:
        return {}
    if not isinstance(schema, dict):
        return {}
    return dict(schema)


def _contract_input_schema(definition: Any | None) -> dict[str, Any]:
    contract = getattr(definition, "contract", None)
    if contract is None:
        return {}
    field_names = [
        *list(getattr(contract, "required_inputs", []) or []),
        *list(getattr(contract, "optional_inputs", []) or []),
    ]
    properties: dict[str, Any] = {}
    for field_name in field_names:
        name = str(field_name or "").strip()
        if not name:
            continue
        properties[name] = _contract_field_schema(name)
    if not properties:
        return {}
    return {
        "type": "object",
        "properties": properties,
        "required": [
            str(item or "").strip()
            for item in list(getattr(contract, "required_inputs", []) or [])
            if str(item or "").strip()
        ],
        "additionalProperties": False,
    }


def _contract_field_schema(field_name: str) -> dict[str, Any]:
    name = str(field_name or "").strip()
    if name in {"start_line", "line_count", "max_results", "max_entries", "max_symbols", "max_bytes", "max_text_chars", "start_byte", "base_mtime_ns"}:
        return {"type": "integer"}
    if name in {"allow_overwrite", "dry_run"}:
        return {"type": "boolean"}
    if name == "read_intent":
        return {
            "type": "string",
            "enum": [
                "edit_target",
                "verify_behavior",
                "understand_api",
                "locate_symbol",
                "inspect_dependency",
                "recover_failure",
            ],
        }
    if name == "edits":
        return {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "old_text": {"type": "string"},
                    "new_text": {"type": "string"},
                },
                "required": ["old_text", "new_text"],
                "additionalProperties": False,
            },
        }
    if name in {"roots", "paths", "items", "context_refs", "expected_outputs"}:
        return {"type": "array"}
    if name in {"args", "diagnostics", "metadata"}:
        return {"type": "object"}
    return {"type": "string"}


def _filter_tool_names_by_profile(
    *,
    profile: RuntimeAssemblyProfile,
    tool_names: tuple[str, ...],
    definitions_by_name: dict[str, Any],
) -> tuple[tuple[str, ...], tuple[dict[str, str], ...]]:
    visible: list[str] = []
    filtered: list[dict[str, str]] = []
    read_only_only = bool(dict(profile.tool_policy or {}).get("read_only_tools_only") is True)
    subagent_enabled = bool(dict(profile.subagent_policy or {}).get("enabled") is True)
    for tool_name in tool_names:
        definition = definitions_by_name.get(tool_name)
        if definition is None:
            filtered.append({"tool_name": tool_name, "reason": "missing_tool_definition"})
            continue
        if tool_name in _SUBAGENT_TOOL_NAMES and not subagent_enabled:
            filtered.append(
                {
                    "tool_name": tool_name,
                    "operation_id": str(getattr(definition, "operation_id", "") or ""),
                    "reason": "subagent_lifecycle_disabled_by_profile",
                }
            )
            continue
        if read_only_only and not bool(getattr(definition, "is_read_only", False)):
            filtered.append(
                {
                    "tool_name": tool_name,
                    "operation_id": str(getattr(definition, "operation_id", "") or ""),
                    "reason": "profile_requires_read_only_tools",
                }
            )
            continue
        visible.append(tool_name)
    return tuple(visible), tuple(filtered)


def _operation_filtered_tools(
    operation_authorization: dict[str, Any],
    *,
    definitions_by_name: dict[str, Any],
) -> tuple[dict[str, str], ...]:
    denied_reasons = {
        str(item.get("operation_id") or ""): str(item.get("reason") or "operation_denied")
        for item in list(operation_authorization.get("decisions") or [])
        if str(item.get("final_decision") or "") != "allow"
    }
    filtered: list[dict[str, str]] = []
    for tool_name, definition in definitions_by_name.items():
        operation_id = str(getattr(definition, "operation_id", "") or "").strip()
        reason = denied_reasons.get(operation_id)
        if reason:
            filtered.append({"tool_name": str(tool_name), "operation_id": operation_id, "reason": reason})
    return tuple(filtered)


def _drop_generic_operation_denials(filtered_tools: tuple[dict[str, str], ...]) -> tuple[dict[str, str], ...]:
    return tuple(
        dict(item)
        for item in tuple(filtered_tools or ())
        if str(dict(item).get("reason") or "") != "operation_not_allowed"
    )


def _string_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        text = value.strip()
        return (text,) if text else ()
    return tuple(str(item).strip() for item in list(value or []) if str(item).strip())


def _first_string(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _merge_dicts(*values: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for value in values:
        if isinstance(value, dict):
            result.update(dict(value))
    return result


def _deep_merge_dicts(*values: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for value in values:
        if not isinstance(value, dict):
            continue
        for key, item in value.items():
            if isinstance(result.get(key), dict) and isinstance(item, dict):
                result[key] = _deep_merge_dicts(result[key], item)
            else:
                result[key] = item
    return result
