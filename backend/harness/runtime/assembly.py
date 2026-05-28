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
from task_system.environments import default_task_environment_registry, resolve_task_environment


RuntimeMode = Literal["role", "standard", "professional", "custom"]


@dataclass(frozen=True, slots=True)
class RuntimeAssemblyProfile:
    mode: RuntimeMode
    interaction_mode: str
    runtime_lane: str
    prompt_pack_refs: tuple[str, ...] = ()
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
        payload["allowed_operations"] = list(self.allowed_operations)
        return payload


@dataclass(frozen=True, slots=True)
class RuntimeAssembly:
    assembly_id: str
    session_id: str
    turn_id: str
    agent_invocation_id: str
    profile: RuntimeAssemblyProfile
    agent_profile_ref: str = ""
    model_selection: dict[str, Any] = field(default_factory=dict)
    task_selection: dict[str, Any] = field(default_factory=dict)
    task_environment: dict[str, Any] = field(default_factory=dict)
    work_role_prompt: str = ""
    available_tools: tuple[dict[str, Any], ...] = ()
    tool_names: tuple[str, ...] = ()
    filtered_tools: tuple[dict[str, str], ...] = ()
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
    requested_mode = _requested_mode(selection)
    profile = build_runtime_assembly_profile(
        requested_mode,
        agent_runtime_profile=agent_runtime_profile,
        selection=selection,
        explicit_allowed_operations=_string_tuple(selection.get("allowed_operations")),
    )
    task_environment, environment_diagnostics = _resolve_runtime_task_environment(
        selection=selection,
        mode=profile.mode,
    )
    allowed_operations = set(profile.allowed_operations)
    tool_set = build_authorized_tool_set(
        tool_instances=list(tool_instances or []),
        definitions_by_name=definitions_by_name,
        allowed_operations=allowed_operations,
        runtime_lane="main_runtime",
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
    available_tools = tuple(
        _tool_view(tool_name=name, definition=definitions_by_name.get(name))
        for name in visible_tool_names
        if definitions_by_name.get(name) is not None
    )
    return RuntimeAssembly(
        assembly_id=f"rtasm:{turn_id}:{profile.mode}",
        session_id=session_id,
        turn_id=turn_id,
        agent_invocation_id=agent_invocation_id,
        profile=profile,
        agent_profile_ref=str(getattr(agent_runtime_profile, "agent_profile_id", "") or "main_interactive_agent"),
        model_selection=dict(model_selection or {}),
        task_selection=selection,
        task_environment=task_environment,
        work_role_prompt=_work_role_prompt(agent_runtime_profile),
        available_tools=available_tools,
        tool_names=visible_tool_names,
        filtered_tools=tuple([*tool_set.filtered_out, *visibility_filtered]),
        soul_role_prompt=soul_role_prompt,
        rejected_capabilities=tuple(rejected),
        diagnostics={
            "requested_mode": requested_mode,
            "resolved_mode": profile.mode,
            "agent_profile_ref": str(getattr(agent_runtime_profile, "agent_profile_id", "") or ""),
            "task_environment": environment_diagnostics,
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
    runtime_lane = str(mode_policy.get("runtime_lane") or getattr(mode_config, "runtime_lane", "") or "")
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
        runtime_lane=runtime_lane,
        prompt_pack_refs=_string_tuple(mode_policy.get("prompt_pack_refs")),
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
        selection.get("specific_task_runtime_policy"),
    )
    return _deep_merge_dicts(
        {
            "mode": mode,
            "interaction_mode": preset.get("interaction_mode") or f"{mode}_mode",
            "runtime_lane": preset.get("runtime_lane") or "",
            "default_environment_id": preset.get("default_environment_id") or "",
            "interaction_policy": dict(preset.get("interaction_policy") or {}),
            "planning_policy": dict(preset.get("planning_policy") or {}),
            "task_lifecycle_policy": dict(preset.get("task_lifecycle_policy") or {}),
            "tool_exposure_policy": dict(preset.get("tool_exposure_policy") or {}),
            "context_policy": dict(preset.get("context_policy") or {}),
            "memory_policy": dict(preset.get("memory_policy") or {}),
            "self_review_policy": dict(preset.get("self_review_policy") or {}),
            "step_summary_policy": dict(preset.get("step_summary_policy") or {}),
            "approval_policy": dict(preset.get("approval_policy") or {}),
            "artifact_policy": dict(preset.get("artifact_policy") or {}),
            "soul_prompt_policy": dict(preset.get("soul_prompt_policy") or {}),
        },
        profile_default,
        explicit_policy,
    )


def _resolve_runtime_task_environment(
    *,
    selection: dict[str, Any],
    mode: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    registry = default_task_environment_registry()
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
    resolved_id = registry.resolve_environment_id(environment_id)
    resolved = resolve_task_environment(resolved_id, registry=registry)
    return (
        {
            "environment_id": resolved.spec.environment_id,
            "requested_environment_id": environment_id,
            "group": resolved.group.to_dict() if resolved.group is not None else {},
            "environment_prompts": [item.to_dict() for item in resolved.spec.environment_prompts],
            "sandbox_policy": resolved.spec.sandbox_policy.to_dict(),
            "storage_space": dict(resolved.to_dict().get("storage_space") or {}),
            "resource_space": resolved.spec.resource_space.to_dict(),
            "file_management": resolved.spec.file_management.to_dict(),
            "file_access_tables": [table.to_dict() for table in resolved.file_access_tables],
            "artifact_policy": resolved.spec.artifact_policy.to_dict(),
            "execution_policy": resolved.spec.execution_policy.to_dict(),
            "risk_policy": resolved.spec.risk_policy.to_dict(),
            "runtime_policy": resolved.spec.runtime_policy.to_dict(),
            "authority": resolved.authority,
        },
        {
            "requested_environment_id": environment_id,
            "resolved_environment_id": resolved.spec.environment_id,
            "environment_group_id": str((resolved.group.group_id if resolved.group is not None else "") or ""),
            "source": "explicit_selection" if explicit else "mode_default",
        },
    )


def _default_environment_id_for_mode(mode: str, *, selection: dict[str, Any]) -> str:
    mode_policy = _merge_dicts(
        dict(selection.get("runtime_profile") or {}).get("runtime_mode_policy"),
        dict(selection.get("runtime_profile") or {}).get("mode_policy"),
        selection.get("runtime_mode_policy"),
        selection.get("mode_policy"),
        selection.get("specific_task_runtime_policy"),
    )
    explicit_default = str(mode_policy.get("default_environment_id") or "").strip()
    if explicit_default:
        return explicit_default
    config = runtime_mode_catalog().get(mode)
    configured_default = str(getattr(config, "default_environment_id", "") or "").strip()
    if configured_default:
        return configured_default
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


def _standard_operations(operations: tuple[str, ...]) -> tuple[str, ...]:
    blocked = {"op.python_repl"}
    return tuple(item for item in operations if item not in blocked)


def _intersect_operations(operations: tuple[str, ...], allowed: set[str]) -> tuple[str, ...]:
    return tuple(item for item in operations if item in allowed)


def _subagent_policy(*, agent_runtime_profile: Any | None, mode_policy: dict[str, Any], mode: str) -> dict[str, Any]:
    enabled_by_mode = bool(mode_policy.get("enabled", mode != ROLE_MODE))
    return {
        **dict(mode_policy or {}),
        "enabled": enabled_by_mode and bool(getattr(agent_runtime_profile, "can_delegate_to_agents", False)),
        "max_delegate_calls_per_turn": int(getattr(agent_runtime_profile, "max_delegate_calls_per_turn", 0) or 0),
        "allowed_delegate_agent_ids": list(getattr(agent_runtime_profile, "allowed_delegate_agent_ids", ()) or ()),
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


def _tool_view(*, tool_name: str, definition: Any) -> dict[str, Any]:
    contract = getattr(definition, "contract", None)
    return {
        "tool_name": tool_name,
        "operation_id": str(getattr(definition, "operation_id", "") or ""),
        "display_name": str(getattr(definition, "display_name", "") or tool_name),
        "required_inputs": list(getattr(contract, "required_inputs", []) or []),
        "optional_inputs": list(getattr(contract, "optional_inputs", []) or []),
        "owner_scope": str(getattr(contract, "owner_scope", "") or "none"),
        "read_only": bool(getattr(definition, "is_read_only", False)),
    }


def _filter_tool_names_by_profile(
    *,
    profile: RuntimeAssemblyProfile,
    tool_names: tuple[str, ...],
    definitions_by_name: dict[str, Any],
) -> tuple[tuple[str, ...], tuple[dict[str, str], ...]]:
    visible: list[str] = []
    filtered: list[dict[str, str]] = []
    read_only_only = bool(dict(profile.tool_policy or {}).get("read_only_tools_only") is True)
    for tool_name in tool_names:
        definition = definitions_by_name.get(tool_name)
        if definition is None:
            filtered.append({"tool_name": tool_name, "reason": "missing_tool_definition"})
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
