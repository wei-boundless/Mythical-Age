from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from agent_system.profiles.runtime_mode_config import (
    CUSTOM_MODE,
    PROFESSIONAL_MODE,
    ROLE_MODE,
    STANDARD_MODE,
    runtime_mode_catalog,
)
from capability_system.tool_authorization import build_authorized_tool_set
from soul.assembly_service import SoulAssemblyService
from task_system.environments import build_task_environment_catalog, task_environment_registry_from_backend_dir

from .operation_projection import project_operation_authorization


RuntimeMode = Literal["role", "standard", "professional", "custom"]

_SUBAGENT_TOOL_NAMES = {
    "spawn_subagent",
    "send_subagent_message",
    "wait_subagent",
    "list_subagents",
    "close_subagent",
}


@dataclass(frozen=True, slots=True)
class RuntimeAssemblyProfile:
    mode: RuntimeMode
    interaction_mode: str
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
    available_tools: tuple[dict[str, Any], ...] = ()
    tool_names: tuple[str, ...] = ()
    filtered_tools: tuple[dict[str, str], ...] = ()
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
        payload["operation_authorization"] = dict(self.operation_authorization)
        payload["engagement_contract"] = dict(self.engagement_contract)
        payload["execution_strategy"] = dict(self.execution_strategy)
        payload["agent_prompt_refs"] = list(self.agent_prompt_refs)
        payload["environment_prompt_refs"] = list(self.environment_prompt_refs)
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
    requested_mode = _requested_mode(selection)
    profile = build_runtime_assembly_profile(
        requested_mode,
        agent_runtime_profile=agent_runtime_profile,
        selection=selection,
        explicit_allowed_operations=_string_tuple(selection.get("allowed_operations")),
    )
    task_environment, environment_diagnostics = _resolve_runtime_task_environment(
        backend_dir=backend_dir,
        selection=selection,
        mode=profile.mode,
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
        mode=profile.mode,
        selection=selection,
    )
    tool_instances_by_name = {
        str(getattr(tool, "name", "") or ""): tool
        for tool in list(tool_instances or [])
        if str(getattr(tool, "name", "") or "")
    }
    available_tools = tuple(
        _tool_view(
            tool_name=name,
            definition=definitions_by_name.get(name),
            tool_instance=tool_instances_by_name.get(name),
        )
        for name in visible_tool_names
        if definitions_by_name.get(name) is not None
    )
    return RuntimeAssembly(
        assembly_id=f"rtasm:{turn_id}:{profile.mode}",
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
        available_tools=available_tools,
        tool_names=visible_tool_names,
        filtered_tools=tuple(
            [
                *_operation_filtered_tools(operation_projection.to_dict(), definitions_by_name=definitions_by_name),
                *_drop_generic_operation_denials(tool_set.filtered_out),
                *visibility_filtered,
            ]
        ),
        operation_authorization=operation_projection.to_dict(),
        soul_role_prompt=soul_role_prompt,
        rejected_capabilities=tuple(rejected),
        diagnostics={
            "requested_mode": requested_mode,
            "resolved_mode": profile.mode,
            "agent_profile_ref": str(getattr(agent_runtime_profile, "agent_profile_id", "") or ""),
            "task_environment": environment_diagnostics,
            "engagement_contract_ref": str(engagement_contract.get("contract_id") or selection.get("engagement_contract_ref") or ""),
            "engagement_plan_ref": str(engagement_contract.get("plan_id") or selection.get("engagement_plan_ref") or ""),
            "operation_authorization": {
                "allowed_operation_count": len(operation_projection.allowed_operations),
                "denied_operation_count": len(operation_projection.denied_operations),
            },
        },
    )


def build_runtime_assembly_profile(
    mode: str,
    *,
    agent_runtime_profile: Any | None = None,
    selection: dict[str, Any] | None = None,
    explicit_allowed_operations: tuple[str, ...] = (),
) -> RuntimeAssemblyProfile:
    normalized = _normalize_mode(mode, agent_runtime_profile=agent_runtime_profile)
    mode_config = runtime_mode_catalog().get(normalized)
    mode_policy = _resolved_mode_runtime_policy(
        normalized,
        mode_config=mode_config,
        agent_runtime_profile=agent_runtime_profile,
        selection=dict(selection or {}),
    )
    interaction_mode = str(mode_policy.get("interaction_mode") or getattr(mode_config, "interaction_mode", "") or f"{normalized}_mode")
    base_operations = _profile_operations(agent_runtime_profile)
    tool_policy = dict(mode_policy.get("tool_exposure_policy") or {})
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
        mode=normalized if normalized in {ROLE_MODE, STANDARD_MODE, PROFESSIONAL_MODE, CUSTOM_MODE} else "custom",
        interaction_mode=interaction_mode,
        prompt_pack_refs=_string_tuple(mode_policy.get("prompt_pack_refs")),
        prompt_pack_refs_by_invocation=dict(mode_policy.get("prompt_pack_refs_by_invocation") or {}),
        operation_authorization_projection=dict(mode_policy.get("operation_authorization_projection") or {}),
        allowed_operations=base_operations,
        interaction_policy=dict(mode_policy.get("interaction_policy") or {}),
        tool_policy=tool_policy,
        network_policy=dict(mode_policy.get("network_policy") or {}),
        subagent_policy=_subagent_policy(
            agent_runtime_profile=agent_runtime_profile,
            mode_policy=dict(mode_policy.get("subagent_policy") or {}),
            mode=normalized,
        ),
        planning_policy=dict(mode_policy.get("planning_policy") or {}),
        task_lifecycle_policy=dict(mode_policy.get("task_lifecycle_policy") or {}),
        context_policy=dict(mode_policy.get("context_policy") or {}),
        memory_policy=dict(mode_policy.get("memory_policy") or {}),
        self_review_policy=dict(mode_policy.get("self_review_policy") or {}),
        artifact_policy=dict(mode_policy.get("artifact_policy") or {}),
        permission_policy=dict(mode_policy.get("approval_policy") or mode_policy.get("permission_policy") or {}),
        soul_prompt_policy=_soul_prompt_policy_for_mode(normalized, mode_policy=dict(mode_policy.get("soul_prompt_policy") or {})),
        step_summary_policy=dict(mode_policy.get("step_summary_policy") or {}),
    )


def _requested_mode(selection: dict[str, Any]) -> str:
    runtime_profile = dict(selection.get("runtime_profile") or {})
    return str(
        selection.get("runtime_mode")
        or selection.get("mode")
        or runtime_profile.get("mode")
        or runtime_profile.get("runtime_mode")
        or ""
    ).strip()


def _work_role_prompt(agent_runtime_profile: Any | None) -> str:
    metadata = dict(getattr(agent_runtime_profile, "metadata", {}) or {})
    return str(
        metadata.get("work_role_prompt")
        or metadata.get("professional_role_prompt")
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


def _agent_work_role_prompt_id(agent_profile_id: str) -> str:
    normalized = ".".join(part for part in str(agent_profile_id or "agent").replace(":", ".").split(".") if part)
    return f"agent.{normalized}.work_role.v1"


def _resolved_mode_runtime_policy(
    mode: str,
    *,
    mode_config: Any | None,
    agent_runtime_profile: Any | None,
    selection: dict[str, Any],
) -> dict[str, Any]:
    preset = mode_config.to_dict() if hasattr(mode_config, "to_dict") else {}
    profile_metadata = dict(getattr(agent_runtime_profile, "metadata", {}) or {})
    custom_modes = dict(profile_metadata.get("runtime_mode_policies") or profile_metadata.get("custom_runtime_mode_policies") or {})
    profile_default = dict(custom_modes.get(mode) or {})
    runtime_profile = dict(selection.get("runtime_profile") or {})
    explicit_policy = _merge_dicts(
        runtime_profile.get("runtime_mode_policy"),
        runtime_profile.get("mode_policy"),
        selection.get("runtime_mode_policy"),
        selection.get("mode_policy"),
    )
    return _deep_merge_dicts(
        {
            "mode": mode,
            "interaction_mode": preset.get("interaction_mode") or f"{mode}_mode",
            "interaction_policy": dict(preset.get("interaction_policy") or {}),
            "planning_policy": dict(preset.get("planning_policy") or {}),
            "task_lifecycle_policy": dict(preset.get("task_lifecycle_policy") or {}),
            "tool_exposure_policy": dict(preset.get("tool_exposure_policy") or {}),
            "context_policy": dict(preset.get("context_policy") or {}),
            "memory_policy": dict(preset.get("memory_policy") or {}),
            "subagent_policy": dict(preset.get("subagent_policy") or {}),
            "self_review_policy": dict(preset.get("self_review_policy") or {}),
            "step_summary_policy": dict(preset.get("step_summary_policy") or {}),
            "approval_policy": dict(preset.get("approval_policy") or {}),
            "artifact_policy": dict(preset.get("artifact_policy") or {}),
            "soul_prompt_policy": dict(preset.get("soul_prompt_policy") or {}),
            "prompt_pack_refs_by_invocation": dict(preset.get("prompt_pack_refs_by_invocation") or {}),
            "operation_authorization_projection": dict(preset.get("operation_authorization_projection") or {}),
        },
        profile_default,
        explicit_policy,
    )


def _resolve_runtime_task_environment(
    *,
    backend_dir: Path,
    selection: dict[str, Any],
    mode: str,
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
    environment_id = explicit or _default_environment_id_for_mode(mode, selection=selection)
    registry.require(environment_id)
    environment_payload = build_task_environment_catalog(registry=registry).runtime_environment_payload(environment_id)
    source = "explicit_selection" if explicit else ("policy_default" if environment_id != "env.general.workspace" else "fallback_default")
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


def _default_environment_id_for_mode(mode: str, *, selection: dict[str, Any]) -> str:
    mode_policy = _merge_dicts(
        dict(selection.get("runtime_profile") or {}).get("runtime_mode_policy"),
        dict(selection.get("runtime_profile") or {}).get("mode_policy"),
        selection.get("runtime_mode_policy"),
        selection.get("mode_policy"),
    )
    explicit_default = str(mode_policy.get("default_environment_id") or "").strip()
    if explicit_default:
        return explicit_default
    return "env.general.workspace"


def _normalize_mode(mode: str, *, agent_runtime_profile: Any | None) -> str:
    raw = str(mode or "").strip().lower()
    aliases = {
        "role_mode": ROLE_MODE,
        "standard_mode": STANDARD_MODE,
        "professional_mode": PROFESSIONAL_MODE,
    }
    raw = aliases.get(raw, raw)
    enabled = tuple(str(item) for item in tuple(getattr(agent_runtime_profile, "enabled_runtime_modes", ()) or ()))
    default_mode = str(getattr(agent_runtime_profile, "default_runtime_mode", "") or STANDARD_MODE)
    if raw in {ROLE_MODE, STANDARD_MODE, PROFESSIONAL_MODE, CUSTOM_MODE} and (not enabled or raw in enabled):
        return raw
    if default_mode in {ROLE_MODE, STANDARD_MODE, PROFESSIONAL_MODE, CUSTOM_MODE}:
        return default_mode
    return STANDARD_MODE


def _profile_operations(agent_runtime_profile: Any | None) -> tuple[str, ...]:
    operations = tuple(
        str(item).strip()
        for item in tuple(getattr(agent_runtime_profile, "allowed_operations", ()) or ())
        if str(item).strip()
    )
    if operations:
        return operations
    return ("op.model_response",)


def _subagent_policy(*, agent_runtime_profile: Any | None, mode_policy: dict[str, Any], mode: str) -> dict[str, Any]:
    profile_policy = getattr(agent_runtime_profile, "subagent_policy", None)
    profile_payload = profile_policy.to_dict() if hasattr(profile_policy, "to_dict") else dict(profile_policy or {})
    allowed_ids = _string_tuple(profile_payload.get("allowed_subagent_ids"))
    mode_enabled = mode_policy.get("enabled")
    profile_enabled = bool(profile_payload.get("enabled") is True)
    enabled = profile_enabled if mode_enabled is None else bool(mode_enabled is True and profile_enabled)
    if mode == ROLE_MODE:
        enabled = False
    return {
        **profile_payload,
        **dict(mode_policy or {}),
        "enabled": enabled and bool(allowed_ids),
        "allowed_subagent_ids": list(allowed_ids),
        "max_subagent_runs_per_task": max(0, int(profile_payload.get("max_subagent_runs_per_task") or 0)),
        "max_active_subagents": max(0, int(profile_payload.get("max_active_subagents") or 0)),
        "context_policy": str(profile_payload.get("context_policy") or "summary_and_refs_only"),
        "result_policy": str(profile_payload.get("result_policy") or "observation_refs_only"),
        "allow_nested_subagents": bool(profile_payload.get("allow_nested_subagents") is True),
        **({"disabled_reason": "role_mode_disallows_subagents"} if mode == ROLE_MODE else {}),
    }


def _soul_prompt_policy_for_mode(mode: str, *, mode_policy: dict[str, Any]) -> dict[str, Any]:
    if mode == ROLE_MODE:
        return {
            "enabled": True,
            "allowed_prompt_kinds": ["role_persona"],
            "forbidden_effects": [
                "tool_permission_change",
                "task_lifecycle_change",
                "output_contract_change",
                "system_boundary_override",
            ],
            **dict(mode_policy or {}),
        }
    return {"enabled": False, **dict(mode_policy or {})}


def _assemble_soul_role_prompt(
    *,
    backend_dir: Path,
    mode: str,
    selection: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    soul_id = str(
        selection.get("soul_id")
        or dict(selection.get("runtime_profile") or {}).get("soul_id")
        or ""
    ).strip().lower()
    if not soul_id:
        return {}, []
    if mode != ROLE_MODE:
        return {}, [{"capability": "soul_role_prompt", "reason": "soul_prompt_only_allowed_in_role_mode"}]
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
