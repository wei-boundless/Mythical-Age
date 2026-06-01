from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from capability_system.skill_registry import SkillRegistry
from capability_system.tool_authorization import build_authorized_tool_set
from soul.assembly_service import SoulAssemblyService
from task_system.contracts.runtime_contracts import SkillRuntimeView, skill_runtime_view_from_skill_definition
from task_system.environments import build_task_environment_catalog, task_environment_registry_from_backend_dir

from .operation_projection import project_operation_authorization


_SUBAGENT_TOOL_NAMES = {
    "spawn_subagent",
    "send_subagent_message",
    "wait_subagent",
    "list_subagents",
    "close_subagent",
}

_DEFAULT_RUNTIME_POLICY: dict[str, Any] = {
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
    "soul_prompt_policy": {"enabled": False},
    "prompt_pack_refs_by_invocation": {},
    "operation_authorization_projection": {},
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
    permission_policy: dict[str, Any] = field(default_factory=dict)
    soul_prompt_policy: dict[str, Any] = field(default_factory=dict)
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
    task_selection: dict[str, Any] = field(default_factory=dict)
    engagement_contract: dict[str, Any] = field(default_factory=dict)
    execution_strategy: dict[str, Any] = field(default_factory=dict)
    engagement_run_ref: str = ""
    task_environment: dict[str, Any] = field(default_factory=dict)
    agent_prompt_refs: tuple[str, ...] = ()
    environment_prompt_refs: tuple[str, ...] = ()
    skill_runtime_views: tuple[dict[str, Any], ...] = ()
    selected_skill_ids: tuple[str, ...] = ()
    available_tools: tuple[dict[str, Any], ...] = ()
    tool_names: tuple[str, ...] = ()
    filtered_tools: tuple[dict[str, str], ...] = ()
    control_capabilities: dict[str, Any] = field(default_factory=dict)
    operation_authorization: dict[str, Any] = field(default_factory=dict)
    soul_role_prompt: dict[str, Any] = field(default_factory=dict)
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
        payload["environment_prompt_refs"] = list(self.environment_prompt_refs)
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
    request_task_selection: dict[str, Any],
    model_selection: dict[str, Any],
    agent_runtime_profile: Any | None,
    tool_instances: list[Any] | tuple[Any, ...] | None,
    definitions_by_name: dict[str, Any],
) -> RuntimeAssembly:
    selection = dict(request_task_selection or {})
    engagement_contract = dict(selection.get("engagement_contract") or {})
    profile = build_runtime_assembly_profile(
        agent_runtime_profile=agent_runtime_profile,
        selection=selection,
        explicit_allowed_operations=_string_tuple(selection.get("allowed_operations")),
    )
    task_environment, environment_diagnostics = _resolve_runtime_task_environment(
        backend_dir=backend_dir,
        selection=selection,
    )
    operation_projection = project_operation_authorization(
        agent_allowed_operations=profile.allowed_operations,
        agent_blocked_operations=tuple(getattr(agent_runtime_profile, "blocked_operations", ()) or ()),
        environment_payload=task_environment,
        task_requested_operations=_string_tuple(selection.get("allowed_operations")),
        definitions_by_name=definitions_by_name,
    )
    allowed_operations = set(operation_projection.allowed_operations)
    tool_set = build_authorized_tool_set(
        tool_instances=list(tool_instances or []),
        definitions_by_name=definitions_by_name,
        allowed_operations=allowed_operations,
        include_hidden=bool(profile.tool_policy.get("include_hidden_tools") is True),
    )
    visible_tool_names, visibility_filtered = _filter_tool_names_by_profile(
        profile=profile,
        tool_names=tuple(tool_set.tool_names),
        definitions_by_name=definitions_by_name,
    )
    soul_role_prompt, rejected = _assemble_soul_role_prompt(
        backend_dir=backend_dir,
        soul_prompt_policy=profile.soul_prompt_policy,
        selection=selection,
    )
    tool_instances_by_name = {
        str(getattr(tool, "name", "") or ""): tool
        for tool in list(tool_instances or [])
        if str(getattr(tool, "name", "") or "")
    }
    control_capabilities = _control_capabilities_for_runtime(
        profile=profile,
        selection=selection,
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
        selection.get("selected_skill_ids"),
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
        task_selection=selection,
        engagement_contract=engagement_contract,
        execution_strategy=dict(engagement_contract.get("execution_strategy") or selection.get("execution_strategy") or {}),
        engagement_run_ref=str(selection.get("engagement_run_ref") or ""),
        task_environment=task_environment,
        agent_prompt_refs=_agent_prompt_refs(agent_runtime_profile),
        environment_prompt_refs=_environment_prompt_refs(task_environment),
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
        soul_role_prompt=soul_role_prompt,
        rejected_capabilities=tuple(rejected),
        diagnostics={
            "agent_profile_ref": str(getattr(agent_runtime_profile, "agent_profile_id", "") or ""),
            "task_environment": environment_diagnostics,
            "engagement_contract_ref": str(engagement_contract.get("contract_id") or selection.get("engagement_contract_ref") or ""),
            "engagement_plan_ref": str(engagement_contract.get("plan_id") or selection.get("engagement_plan_ref") or ""),
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
    selection: dict[str, Any] | None = None,
    explicit_allowed_operations: tuple[str, ...] = (),
) -> RuntimeAssemblyProfile:
    selection = dict(selection or {})
    runtime_policy = _resolved_runtime_policy(
        agent_runtime_profile=agent_runtime_profile,
        selection=selection,
    )
    base_operations = _profile_operations(agent_runtime_profile)
    tool_policy = dict(runtime_policy.get("tool_exposure_policy") or {})
    explicit_tool_policy = _merge_dicts(
        selection.get("tool_exposure_policy"),
        selection.get("tool_policy"),
        dict(selection.get("runtime_profile") or {}).get("tool_exposure_policy"),
        dict(selection.get("runtime_profile") or {}).get("tool_policy"),
    )
    if explicit_tool_policy:
        tool_policy = {**tool_policy, **explicit_tool_policy}
    ceiling = _string_tuple(explicit_tool_policy.get("operation_ceiling"))
    if ceiling:
        base_operations = tuple(item for item in base_operations if item in set(ceiling))
    blocked_operations = set(_string_tuple(explicit_tool_policy.get("blocked_operations")))
    if blocked_operations:
        base_operations = tuple(item for item in base_operations if item not in blocked_operations)
    if explicit_allowed_operations:
        base_operations = tuple(item for item in base_operations if item in set(explicit_allowed_operations))
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
        permission_policy=dict(runtime_policy.get("approval_policy") or runtime_policy.get("permission_policy") or {}),
        soul_prompt_policy=dict(runtime_policy.get("soul_prompt_policy") or {}),
        step_summary_policy=dict(runtime_policy.get("step_summary_policy") or {}),
    )


def _work_role_prompt(agent_runtime_profile: Any | None) -> str:
    metadata = dict(getattr(agent_runtime_profile, "metadata", {}) or {})
    return str(
        metadata.get("work_role_prompt")
        or metadata.get("agent_work_role_prompt")
        or ""
    ).strip()


def _agent_prompt_refs(agent_runtime_profile: Any | None) -> tuple[str, ...]:
    metadata = dict(getattr(agent_runtime_profile, "metadata", {}) or {})
    explicit = _string_tuple(metadata.get("agent_prompt_refs"))
    if explicit:
        return explicit
    if _work_role_prompt(agent_runtime_profile):
        profile_id = str(getattr(agent_runtime_profile, "agent_profile_id", "") or "main_interactive_agent")
        return (_agent_work_role_prompt_id(profile_id),)
    return ()


def _environment_prompt_refs(environment_payload: dict[str, Any]) -> tuple[str, ...]:
    boundary = dict(environment_payload.get("environment_boundary") or {})
    refs = _string_tuple(boundary.get("prompt_refs"))
    if refs:
        return refs
    return tuple(
        str(item.get("prompt_id") or "").strip()
        for item in list(environment_payload.get("environment_prompts") or [])
        if isinstance(item, dict) and str(item.get("prompt_id") or "").strip()
    )


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


def _agent_work_role_prompt_id(agent_profile_id: str) -> str:
    normalized = ".".join(part for part in str(agent_profile_id or "agent").replace(":", ".").split(".") if part)
    return f"agent.{normalized}.work_role.v1"


def _resolved_runtime_policy(
    *,
    agent_runtime_profile: Any | None,
    selection: dict[str, Any],
) -> dict[str, Any]:
    profile_metadata = dict(getattr(agent_runtime_profile, "metadata", {}) or {})
    runtime_profile = dict(selection.get("runtime_profile") or {})
    explicit_policy = _merge_dicts(
        profile_metadata.get("runtime_policy"),
        profile_metadata.get("execution_policy"),
        runtime_profile.get("runtime_policy"),
        runtime_profile.get("execution_policy"),
        selection.get("runtime_policy"),
        selection.get("execution_policy"),
    )
    return _deep_merge_dicts(
        _DEFAULT_RUNTIME_POLICY,
        explicit_policy,
    )


def _resolve_runtime_task_environment(
    *,
    backend_dir: Path,
    selection: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    registry = task_environment_registry_from_backend_dir(backend_dir)
    explicit = _first_string(
        selection.get("task_environment_id"),
        selection.get("environment_id"),
        dict(selection.get("task_environment") or {}).get("environment_id")
        if isinstance(selection.get("task_environment"), dict)
        else selection.get("task_environment"),
        dict(selection.get("runtime_profile") or {}).get("task_environment_id"),
        dict(selection.get("runtime_profile") or {}).get("environment_id"),
    )
    environment_id = explicit or "env.general.workspace"
    registry.require(environment_id)
    environment_payload = build_task_environment_catalog(registry=registry).runtime_environment_payload(environment_id)
    source = "explicit_selection" if explicit else "fallback_default"
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
    selection: dict[str, Any],
    visible_tool_names: tuple[str, ...],
    engagement_contract: dict[str, Any],
) -> dict[str, Any]:
    explicit = _merge_dicts(
        selection.get("control_capabilities"),
        dict(selection.get("runtime_profile") or {}).get("control_capabilities"),
        dict(selection.get("runtime_profile") or {}).get("runtime_control_capabilities"),
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
    has_explicit_contract = bool(engagement_contract or selection.get("task_contract") or selection.get("task_contract_seed"))
    requires_json_action_protocol = bool(
        explicit.get("requires_json_action_protocol")
        if "requires_json_action_protocol" in explicit
        else (may_call_tools or may_use_subagents or has_explicit_contract)
    )
    return {
        "authority": "harness.runtime.control_capabilities",
        "may_emit_assistant_message": may_emit_assistant_message,
        "may_call_tools": may_call_tools,
        "may_request_task_run": may_request_task_run,
        "may_control_active_work": may_control_active_work,
        "may_use_subagents": may_use_subagents,
        "requires_json_action_protocol": requires_json_action_protocol,
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


def _assemble_soul_role_prompt(
    *,
    backend_dir: Path,
    soul_prompt_policy: dict[str, Any],
    selection: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    soul_id = str(
        selection.get("soul_id")
        or dict(selection.get("runtime_profile") or {}).get("soul_id")
        or ""
    ).strip().lower()
    if not soul_id:
        return {}, []
    if not bool(dict(soul_prompt_policy or {}).get("enabled") is True):
        return {}, [{"capability": "soul_role_prompt", "reason": "soul_prompt_disabled_by_agent_profile"}]
    try:
        return SoulAssemblyService(backend_dir).build_role_prompt(soul_id=soul_id), []
    except KeyError:
        return {}, [{"capability": "soul_role_prompt", "reason": "soul_not_found"}]


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
    }
    description = str(getattr(tool_instance, "description", "") or "").strip()
    if description:
        payload["description"] = description
    input_schema = _tool_input_schema(tool_instance)
    if input_schema:
        payload["input_schema"] = input_schema
    return payload


def _tool_input_schema(tool_instance: Any | None) -> dict[str, Any]:
    args_schema = getattr(tool_instance, "args_schema", None)
    if args_schema is None:
        return {}
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
