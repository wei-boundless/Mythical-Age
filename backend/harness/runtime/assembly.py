from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from agent_system.profiles.runtime_mode_config import (
    PROFESSIONAL_MODE,
    ROLE_MODE,
    STANDARD_MODE,
    runtime_mode_catalog,
)
from capability_system.tool_authorization import build_authorized_tool_set
from soul.assembly_service import SoulAssemblyService


RuntimeMode = Literal["role", "standard", "professional", "custom"]


@dataclass(frozen=True, slots=True)
class RuntimeAssemblyProfile:
    mode: RuntimeMode
    interaction_mode: str
    runtime_lane: str
    prompt_pack_refs: tuple[str, ...] = ()
    allowed_operations: tuple[str, ...] = ()
    tool_policy: dict[str, Any] = field(default_factory=dict)
    network_policy: dict[str, Any] = field(default_factory=dict)
    subagent_policy: dict[str, Any] = field(default_factory=dict)
    planning_policy: dict[str, Any] = field(default_factory=dict)
    task_lifecycle_policy: dict[str, Any] = field(default_factory=dict)
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
        explicit_allowed_operations=_string_tuple(selection.get("allowed_operations")),
    )
    allowed_operations = set(profile.allowed_operations)
    tool_set = build_authorized_tool_set(
        tool_instances=list(tool_instances or []),
        definitions_by_name=definitions_by_name,
        allowed_operations=allowed_operations,
        runtime_lane="main_runtime",
        include_hidden=bool(profile.tool_policy.get("include_hidden_tools") is True),
    )
    soul_role_prompt, rejected = _assemble_soul_role_prompt(
        backend_dir=backend_dir,
        mode=profile.mode,
        selection=selection,
    )
    available_tools = tuple(
        _tool_view(tool_name=name, definition=definitions_by_name.get(name))
        for name in tool_set.tool_names
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
        available_tools=available_tools,
        tool_names=tuple(tool_set.tool_names),
        filtered_tools=tuple(tool_set.filtered_out),
        soul_role_prompt=soul_role_prompt,
        rejected_capabilities=tuple(rejected),
        diagnostics={
            "requested_mode": requested_mode,
            "resolved_mode": profile.mode,
            "agent_profile_ref": str(getattr(agent_runtime_profile, "agent_profile_id", "") or ""),
        },
    )


def build_runtime_assembly_profile(
    mode: str,
    *,
    agent_runtime_profile: Any | None = None,
    explicit_allowed_operations: tuple[str, ...] = (),
) -> RuntimeAssemblyProfile:
    normalized = _normalize_mode(mode, agent_runtime_profile=agent_runtime_profile)
    mode_config = runtime_mode_catalog().get(normalized)
    interaction_mode = str(getattr(mode_config, "interaction_mode", "") or f"{normalized}_mode")
    runtime_lane = str(getattr(mode_config, "runtime_lane", "") or "")
    base_operations = _profile_operations(agent_runtime_profile)
    if explicit_allowed_operations:
        base_operations = tuple(item for item in base_operations if item in set(explicit_allowed_operations))
    if normalized == ROLE_MODE:
        allowed_operations = _intersect_operations(
            base_operations,
            {
                "op.model_response",
                "op.web_search",
                "op.fetch_url",
                "op.memory_read",
            },
        )
        return RuntimeAssemblyProfile(
            mode="role",
            interaction_mode=interaction_mode,
            runtime_lane=runtime_lane,
            prompt_pack_refs=("runtime.prompt.mode.role.v1",),
            allowed_operations=allowed_operations,
            tool_policy={"read_only_tools_only": True, "write_tools_allowed": False},
            network_policy={"web_search": True, "fetch_url": True},
            subagent_policy={"enabled": False, "max_delegate_calls_per_turn": 0},
            planning_policy={"plan_mode": "disabled"},
            task_lifecycle_policy={"request_task_run": False},
            artifact_policy={"required": False},
            permission_policy={"scope": "role_conversation_readonly"},
            soul_prompt_policy={
                "enabled": True,
                "allowed_prompt_kinds": ["role_persona"],
                "forbidden_effects": [
                    "tool_permission_change",
                    "task_lifecycle_change",
                    "output_contract_change",
                    "system_boundary_override",
                ],
            },
            step_summary_policy={"enabled": True, "detail": "compact"},
        )
    if normalized == PROFESSIONAL_MODE:
        allowed_operations = base_operations
        return RuntimeAssemblyProfile(
            mode="professional",
            interaction_mode=interaction_mode,
            runtime_lane=runtime_lane,
            prompt_pack_refs=("runtime.prompt.mode.professional.v1",),
            allowed_operations=allowed_operations,
            tool_policy={"read_only_tools_only": False, "write_tools_allowed": True},
            network_policy={"web_search": True, "fetch_url": True},
            subagent_policy={
                "enabled": bool(getattr(agent_runtime_profile, "can_delegate_to_agents", False)),
                "max_delegate_calls_per_turn": int(getattr(agent_runtime_profile, "max_delegate_calls_per_turn", 0) or 0),
                "allowed_delegate_agent_ids": list(getattr(agent_runtime_profile, "allowed_delegate_agent_ids", ()) or ()),
            },
            planning_policy={"plan_mode": "available", "specified_plan_allowed": True},
            task_lifecycle_policy={"request_task_run": True, "requires_completion_evidence": True},
            artifact_policy={"required_for_long_task": True, "verify_before_final": True},
            permission_policy={"scope": "professional_high_authority_with_gate"},
            soul_prompt_policy={"enabled": False},
            step_summary_policy={"enabled": True, "detail": "stepwise"},
        )
    allowed_operations = _standard_operations(base_operations)
    return RuntimeAssemblyProfile(
        mode="standard",
        interaction_mode=interaction_mode,
        runtime_lane=runtime_lane or "standard_task",
        prompt_pack_refs=("runtime.prompt.mode.standard.v1",),
        allowed_operations=allowed_operations,
        tool_policy={"read_only_tools_only": False, "write_tools_allowed": True},
        network_policy={"web_search": True, "fetch_url": True},
        subagent_policy={
            "enabled": bool(getattr(agent_runtime_profile, "can_delegate_to_agents", False)),
            "max_delegate_calls_per_turn": int(getattr(agent_runtime_profile, "max_delegate_calls_per_turn", 0) or 0),
            "allowed_delegate_agent_ids": list(getattr(agent_runtime_profile, "allowed_delegate_agent_ids", ()) or ()),
        },
        planning_policy={"plan_mode": "disabled"},
        task_lifecycle_policy={"request_task_run": True, "requires_completion_evidence": True},
        artifact_policy={"required_for_long_task": True},
        permission_policy={"scope": "standard_tools_with_gate"},
        soul_prompt_policy={"enabled": False},
        step_summary_policy={"enabled": True, "detail": "compact"},
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
    if raw in {ROLE_MODE, STANDARD_MODE, PROFESSIONAL_MODE} and (not enabled or raw in enabled):
        return raw
    if default_mode in {ROLE_MODE, STANDARD_MODE, PROFESSIONAL_MODE}:
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


def _string_tuple(value: Any) -> tuple[str, ...]:
    return tuple(str(item).strip() for item in list(value or []) if str(item).strip())
