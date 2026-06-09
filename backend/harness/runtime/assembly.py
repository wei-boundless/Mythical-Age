from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from capability_system.skills.registry import SkillRegistry
from capability_system.tools.authorization import build_authorized_tool_set
from permissions.policy import normalize_permission_mode
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

_DEFAULT_LIFECYCLE_PROMPT_DEFAULTS: dict[str, str] = {
    "context_intake": "environment.general.lifecycle.context_intake",
    "request_judgment": "environment.general.lifecycle.request_judgment",
    "work_relation": "environment.general.lifecycle.work_relation",
    "environment_capability_alignment": "environment.general.lifecycle.environment_capability_alignment",
    "plan_gate": "environment.general.lifecycle.plan_gate",
    "action_selection": "environment.general.lifecycle.action_selection",
    "active_work_control": "environment.general.lifecycle.active_work_control",
    "task_run_handoff": "environment.general.lifecycle.task_run_handoff",
    "user_steer_contract_revision": "environment.general.lifecycle.user_steer_contract_revision",
    "tool_dispatch": "environment.general.lifecycle.tool_dispatch",
    "tool_observation_recovery": "environment.general.lifecycle.tool_observation_recovery",
    "subagent_delegation": "environment.general.lifecycle.subagent_delegation",
    "subagent_result_integration": "environment.general.lifecycle.subagent_result_integration",
    "verification_gate": "environment.general.lifecycle.verification_gate",
    "memory_read_context": "environment.general.lifecycle.memory_read_context",
    "memory_write_handoff": "environment.general.lifecycle.memory_write_handoff",
    "compaction_handoff": "environment.general.lifecycle.compaction_handoff",
    "finalization": "environment.general.lifecycle.finalization",
}

_DEFAULT_TOOL_GUIDANCE_PROMPT_DEFAULTS: dict[str, str] = {
    "tool.guidance.read_file": "tool.guidance.read_file",
    "tool.guidance.read_persisted_tool_result": "tool.guidance.read_persisted_tool_result",
    "tool.guidance.edit_file": "tool.guidance.edit_file",
    "tool.guidance.write_file": "tool.guidance.write_file",
    "tool.guidance.terminal_powershell": "tool.guidance.terminal_powershell",
    "tool.guidance.git_read": "tool.guidance.git_read",
    "tool.guidance.git_write": "tool.guidance.git_write",
    "tool.guidance.todo": "tool.guidance.todo",
    "tool.guidance.subagent": "tool.guidance.subagent",
    "tool.guidance.browser": "tool.guidance.browser",
    "tool.guidance.web_fetch": "tool.guidance.web_fetch",
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
        "lifecycle_prompt_defaults": _DEFAULT_LIFECYCLE_PROMPT_DEFAULTS,
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
    skill_runtime_views: tuple[dict[str, Any], ...] = ()
    selected_skill_ids: tuple[str, ...] = ()
    available_tools: tuple[dict[str, Any], ...] = ()
    tool_names: tuple[str, ...] = ()
    filtered_tools: tuple[dict[str, str], ...] = ()
    control_capabilities: dict[str, Any] = field(default_factory=dict)
    operation_authorization: dict[str, Any] = field(default_factory=dict)
    rejected_capabilities: tuple[dict[str, str], ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "harness.runtime.assembly"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["profile"] = self.profile.to_dict()
        payload["available_tools"] = [dict(item) for item in self.available_tools]
        payload["tool_names"] = list(self.tool_names)
        payload["filtered_tools"] = [dict(item) for item in self.filtered_tools]
        payload["control_capabilities"] = dict(self.control_capabilities)
        payload["operation_authorization"] = dict(self.operation_authorization)
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
        payload["skill_runtime_views"] = [dict(item) for item in self.skill_runtime_views]
        payload["selected_skill_ids"] = list(self.selected_skill_ids)
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
        environment_payload=task_environment,
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
    skill_runtime_views = _skill_runtime_views_for_profile(
        backend_dir=backend_dir,
        allowed_operations=tuple(sorted(allowed_operations)),
    )
    selected_skill_ids = _visible_selected_skill_ids(
        runtime_contract_payload.get("selected_skill_ids"),
        visible_skill_ids=tuple(str(item.get("skill_id") or "") for item in skill_runtime_views),
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
        skill_runtime_views=skill_runtime_views,
        selected_skill_ids=selected_skill_ids,
        available_tools=available_tools,
        tool_names=visible_tool_names,
        filtered_tools=tuple(
            [
                *_operation_filtered_tools(operation_projection.to_dict(), definitions_by_name=definitions_by_name),
                *_drop_generic_operation_denials(tool_set.filtered_out),
                *visibility_filtered,
            ]
        ),
        control_capabilities=control_capabilities,
        operation_authorization=operation_projection.to_dict(),
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
            "skill_runtime": {
                "candidate_count": len(skill_runtime_views),
                "selected_skill_ids": list(selected_skill_ids),
            },
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


def _visible_selected_skill_ids(value: Any, *, visible_skill_ids: tuple[str, ...]) -> tuple[str, ...]:
    visible = {str(item or "").strip() for item in visible_skill_ids if str(item or "").strip()}
    selected: list[str] = []
    seen: set[str] = set()
    raw_values = value if isinstance(value, (list, tuple)) else ([value] if value else [])
    for raw in raw_values:
        item = str(raw or "").strip()
        if not item:
            continue
        normalized = item if item.startswith("skill.") else f"skill.{item}"
        if normalized not in visible or normalized in seen:
            continue
        seen.add(normalized)
        selected.append(normalized)
    return tuple(selected)


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
    environment_id = explicit or "env.general.workspace"
    registry.require(environment_id)
    environment_payload = build_task_environment_catalog(registry=registry).runtime_environment_payload(environment_id)
    source = "environment_binding" if explicit_binding else "runtime_contract" if explicit else "fallback_default"
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
    active_work_context = str(
        context_policy.get("active_work_context")
        or context_policy.get("task_run_context")
        or context_policy.get("task_context")
        or ""
    ).strip().lower()
    active_work_disabled = active_work_context in {"disabled", "none", "off", "false", "0", "readonly"}
    task_run_allowed = task_lifecycle.get("request_task_run") is not False
    subagent_enabled = bool(subagent.get("enabled") is True)
    may_emit_assistant_message = bool(explicit.get("may_emit_assistant_message", True) is not False)
    may_call_tools = bool(
        explicit.get("may_call_tools")
        if "may_call_tools" in explicit
        else bool(visible_tool_names)
    )
    may_request_task_run = bool(
        explicit.get("may_request_task_run")
        if "may_request_task_run" in explicit
        else task_run_allowed
    )
    may_control_active_work = bool(
        explicit.get("may_control_active_work")
        if "may_control_active_work" in explicit
        else not active_work_disabled
    )
    may_use_subagents = bool(
        explicit.get("may_use_subagents")
        if "may_use_subagents" in explicit
        else subagent_enabled
    )
    has_explicit_contract = bool(engagement_contract or runtime_contract.get("task_contract") or runtime_contract.get("task_contract_seed"))
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


def _subagent_policy(*, agent_runtime_profile: Any | None, policy: dict[str, Any]) -> dict[str, Any]:
    profile_policy = getattr(agent_runtime_profile, "subagent_policy", None)
    profile_payload = profile_policy.to_dict() if hasattr(profile_policy, "to_dict") else dict(profile_policy or {})
    allowed_ids = _string_tuple(profile_payload.get("allowed_subagent_ids"))
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
        "prompt_exposure_policy": str(getattr(definition, "prompt_exposure_policy", "") or "schema_only"),
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
    if name in {"start_line", "line_count", "max_results", "max_entries", "max_symbols", "max_bytes", "start_byte"}:
        return {"type": "integer"}
    if name in {"allow_overwrite", "dry_run"}:
        return {"type": "boolean"}
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
