from __future__ import annotations

from typing import Any

from task_system.environments import default_task_environment_registry
from task_system.registry.flow_models import SpecificTaskRecord, TaskExecutionPolicy

from .assembly_policy import (
    AgentSelectionPolicy,
    RequirementRefs,
    SpecificTaskAssemblyPolicy,
    ToolCapabilityRequirements,
    build_specific_task_assembly_policy_id,
)


def resolve_specific_task_assembly_policy(
    *,
    task_record: SpecificTaskRecord,
    execution_policy: TaskExecutionPolicy | None = None,
    task_selection: dict[str, Any] | None = None,
) -> SpecificTaskAssemblyPolicy:
    selection = dict(task_selection or {})
    task_policy = dict(getattr(task_record, "task_policy", {}) or {})
    metadata = dict(getattr(task_record, "metadata", {}) or {})
    execution_policy_metadata = dict(getattr(execution_policy, "metadata", {}) or {}) if execution_policy is not None else {}
    environment_id = _resolve_environment_id(
        selection.get("task_environment_id"),
        selection.get("environment_id"),
        metadata.get("task_environment_id"),
        metadata.get("environment_id"),
        task_policy.get("task_environment_id"),
        task_policy.get("environment_id"),
        getattr(task_record, "domain_id", ""),
    )
    flow_ref = _first_value(
        selection.get("flow_ref"),
        selection.get("flow_id"),
        task_policy.get("flow_ref"),
        task_policy.get("flow_id"),
        metadata.get("flow_ref"),
        metadata.get("flow_id"),
        getattr(task_record, "default_workflow_id", ""),
    )
    tool_policy = _merge_dicts(
        task_policy.get("tool_capability_requirements"),
        task_policy.get("tool_requirements"),
        metadata.get("tool_capability_requirements"),
        metadata.get("tool_requirements"),
        selection.get("tool_capability_requirements"),
        selection.get("tool_requirements"),
    )
    skill_policy = _merge_dicts(
        task_policy.get("skill_requirements"),
        metadata.get("skill_requirements"),
        selection.get("skill_requirements"),
    )
    prompt_policy = _merge_dicts(
        task_policy.get("prompt_requirements"),
        metadata.get("prompt_requirements"),
        selection.get("prompt_requirements"),
    )
    runtime_shape = _runtime_shape(
        _first_value(
            selection.get("runtime_shape"),
            task_policy.get("runtime_shape"),
            metadata.get("runtime_shape"),
            execution_policy_metadata.get("execution_chain_type"),
            "task_graph" if bool(getattr(execution_policy, "allow_worker_agent_spawn", False)) else "",
            "single_agent",
        )
    )
    agent_selection = AgentSelectionPolicy(
        default_agent_id=_first_value(
            selection.get("default_agent_id"),
            getattr(execution_policy, "default_agent_id", ""),
            metadata.get("default_agent_id"),
            "agent:0",
        ),
        agent_profile_ref=_first_value(
            selection.get("agent_profile_id"),
            selection.get("agent_profile_ref"),
            metadata.get("agent_profile_id"),
            metadata.get("agent_profile_ref"),
        ),
        worker_blueprint_id=_first_value(
            selection.get("worker_agent_blueprint_id"),
            getattr(execution_policy, "worker_agent_blueprint_id", ""),
            metadata.get("worker_agent_blueprint_id"),
        ),
        allow_worker_spawn=bool(
            selection.get("allow_worker_agent_spawn", getattr(execution_policy, "allow_worker_agent_spawn", False))
        ),
        participant_agent_refs=_tuple_from_any(
            selection.get("participant_agent_refs")
            or selection.get("participant_agent_ids")
            or metadata.get("participant_agent_refs")
            or metadata.get("participant_agent_ids")
        ),
    )
    return SpecificTaskAssemblyPolicy(
        policy_id=build_specific_task_assembly_policy_id(str(task_record.task_id), environment_id),
        task_id=str(task_record.task_id or ""),
        environment_id=environment_id,
        flow_ref=flow_ref,
        agent_selection=agent_selection,
        skill_requirements=RequirementRefs(
            required_refs=_tuple_from_any(skill_policy.get("required_refs") or skill_policy.get("required_skill_refs")),
            optional_refs=_tuple_from_any(skill_policy.get("optional_refs") or skill_policy.get("optional_skill_refs")),
            denied_refs=_tuple_from_any(skill_policy.get("denied_refs") or skill_policy.get("denied_skill_refs")),
        ),
        prompt_requirements=RequirementRefs(
            required_refs=_tuple_from_any(prompt_policy.get("required_refs") or prompt_policy.get("required_prompt_refs")),
            optional_refs=_tuple_from_any(prompt_policy.get("optional_refs") or prompt_policy.get("optional_prompt_refs")),
            denied_refs=_tuple_from_any(prompt_policy.get("denied_refs") or prompt_policy.get("denied_prompt_refs")),
        ),
        tool_capability_requirements=ToolCapabilityRequirements(
            required_operations=_tuple_from_any(tool_policy.get("required_operations")),
            optional_operations=_tuple_from_any(tool_policy.get("optional_operations")),
            denied_operations=_tuple_from_any(tool_policy.get("denied_operations")),
            required_tool_tags=_tuple_from_any(tool_policy.get("required_tool_tags")),
            preferred_tools=_tuple_from_any(tool_policy.get("preferred_tools")),
        ),
        memory_requirements=_merge_dicts(
            task_policy.get("memory_requirements"),
            metadata.get("memory_requirements"),
            selection.get("memory_requirements"),
        ),
        resource_requirements=_merge_dicts(
            task_policy.get("resource_requirements"),
            metadata.get("resource_requirements"),
            selection.get("resource_requirements"),
        ),
        output_contract_ref=_first_value(
            selection.get("output_contract_ref"),
            getattr(task_record, "output_contract_id", ""),
        ),
        acceptance_policy=_merge_dicts(
            task_policy.get("acceptance_policy"),
            metadata.get("acceptance_policy"),
            {"acceptance_profile_id": getattr(task_record, "acceptance_profile_id", "")}
            if getattr(task_record, "acceptance_profile_id", "")
            else {},
        ),
        runtime_shape=runtime_shape,
        metadata={
            "source": "task_system.tasks.assembly_policy_resolver",
            "task_record_ref": str(task_record.task_id or ""),
            "execution_policy_ref": str(getattr(execution_policy, "policy_id", "") or ""),
        },
    )


def _first_value(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _resolve_environment_id(*values: Any) -> str:
    explicit = _first_value(*values)
    if explicit:
        return _require_known_environment(_normalize_environment_id(explicit))
    return "env.general_workspace"


def _normalize_environment_id(value: Any) -> str:
    text = str(value or "").strip()
    if text in {"writing", "domain.writing", "domain.writing.modular_novel", "domain.writing_modular_novel"}:
        return "env.writing"
    if text in {"research", "web_research", "domain.research", "domain.web_research"}:
        return "env.web_research"
    if text in {"coding", "development", "vibe_coding", "domain.development", "domain.custom_4"}:
        return "env.vibe_coding"
    if text.startswith("env."):
        return text
    return text


def _require_known_environment(environment_id: str) -> str:
    value = str(environment_id or "").strip()
    if not value:
        raise ValueError("SpecificTaskAssemblyPolicy requires environment_id")
    if default_task_environment_registry().get(value) is None:
        raise ValueError(f"unknown task environment: {value}")
    return value


def _tuple_from_any(value: Any) -> tuple[str, ...]:
    return tuple(str(item).strip() for item in list(value or []) if str(item).strip())


def _merge_dicts(*values: Any) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for value in values:
        if isinstance(value, dict):
            merged.update(dict(value))
    return merged


def _runtime_shape(value: str) -> str:
    normalized = str(value or "").strip()
    if normalized in {"coordination_chain", "task_graph", "graph"}:
        return "task_graph"
    if normalized in {"human_gate", "human"}:
        return "human_gate"
    if normalized in {"graph_module", "imported_graph"}:
        return "graph_module"
    return "single_agent"


