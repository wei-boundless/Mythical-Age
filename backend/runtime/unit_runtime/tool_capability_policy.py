from __future__ import annotations

from typing import Any

from task_system.environments import resolve_task_environment
from task_system.tasks import SpecificTaskAssemblyPolicy
from runtime.tooling import ToolCapabilityBuildRequest, ToolCapabilityTable, build_tool_capability_table


def prepare_runtime_tool_capability_table_for_turn(
    *,
    task_operation: dict[str, Any],
    file_management_policy: dict[str, Any] | None,
    execution_permit: dict[str, Any] | None,
    runtime_available_operations: tuple[str, ...] | list[str] = (),
) -> ToolCapabilityTable | None:
    """Build the system-owned tool capability table for this runtime turn."""

    file_policy = dict(file_management_policy or {})
    environment_id = str(
        file_policy.get("environment_id")
        or dict(task_operation.get("task_environment") or {}).get("environment_id")
        or dict(task_operation.get("selected_recipe") or {}).get("environment_id")
        or ""
    ).strip()
    if not environment_id:
        return None

    try:
        resolved = resolve_task_environment(environment_id)
    except KeyError:
        return None

    requirement = dict(task_operation.get("operation_requirement") or {})
    assembly_policy = _specific_task_assembly_policy_from_task_operation(task_operation)
    assembly_tool_requirements = (
        assembly_policy.tool_capability_requirements if assembly_policy is not None else None
    )
    permit = dict(execution_permit or task_operation.get("execution_permit") or {})
    return build_tool_capability_table(
        ToolCapabilityBuildRequest(
            environment=resolved.spec,
            file_access_tables=resolved.file_access_tables,
            task_required_operations=_tuple_refs(
                [
                    *list(requirement.get("required_operations") or []),
                    *list(getattr(assembly_tool_requirements, "required_operations", ()) or []),
                ]
            ),
            task_optional_operations=_tuple_refs(
                [
                    *list(requirement.get("optional_operations") or []),
                    *list(getattr(assembly_tool_requirements, "optional_operations", ()) or []),
                    *list(getattr_like(task_operation.get("resource_policy"), "requires_approval_operations") or []),
                ]
            ),
            task_denied_operations=_tuple_refs(
                [
                    *list(requirement.get("denied_operations") or []),
                    *list(getattr(assembly_tool_requirements, "denied_operations", ()) or []),
                ]
            ),
            agent_profile_allowed_operations=_tuple_refs(permit.get("allowed_operations")),
            runtime_available_operations=_tuple_refs(runtime_available_operations),
            table_id=f"tool-capability:{environment_id}:{task_operation.get('task_id') or 'turn'}",
            metadata={
                "authority": "runtime.unit_runtime.tool_capability_policy",
                "source": "task_environment+execution_permit+file_access_table",
                "specific_task_assembly_policy_ref": str(getattr(assembly_policy, "policy_id", "") or ""),
                "execution_permit_ref": str(permit.get("permit_id") or ""),
                "file_management_policy": {
                    "environment_id": str(file_policy.get("environment_id") or ""),
                    "profile_id": str(file_policy.get("profile_id") or ""),
                },
            },
        )
    )


def capability_table_to_runtime_plan_overlay(table: ToolCapabilityTable | None) -> dict[str, Any]:
    if table is None:
        return {}
    return {
        "tool_capability_table_id": table.table_id,
        "environment_id": table.environment_id,
        "visible_tools": list(table.visible_tools),
        "dispatchable_tools": list(table.dispatchable_tools),
        "visible_operations": list(table.visible_operations),
        "dispatchable_operations": list(table.dispatchable_operations),
        "filtered": [item.to_dict() for item in table.filtered],
        "authority": table.authority,
    }


def apply_tool_capability_table_to_turn_plan(
    plan: Any,
    table: ToolCapabilityTable | None,
) -> Any:
    if table is None or not hasattr(plan, "to_dict"):
        return plan
    from runtime.capabilities import CurrentTurnCapabilityPlan

    payload = plan.to_dict()
    table_visible = set(table.visible_tools)
    table_dispatchable = set(table.dispatchable_tools)
    table_operations = set(table.dispatchable_operations)
    allowed_operations = tuple(
        operation for operation in tuple(getattr(plan, "allowed_operations", ()) or ()) if operation in table_operations
    )
    operation_visible_tools = tuple(
        capability.tool_name
        for capability in table.capabilities
        if capability.operation_id in set(allowed_operations) and capability.visible
    )
    operation_dispatchable_tools = tuple(
        capability.tool_name
        for capability in table.capabilities
        if capability.operation_id in set(allowed_operations) and capability.dispatchable
    )
    return CurrentTurnCapabilityPlan(
        allowed_operations=allowed_operations,
        model_visible_tools=_dedupe_refs(
            [
                *[
                    tool
                    for tool in tuple(getattr(plan, "model_visible_tools", ()) or ())
                    if tool in table_visible
                ],
                *operation_visible_tools,
            ]
        ),
        dispatchable_tools=_dedupe_refs(
            [
                *[
                    tool
                    for tool in tuple(getattr(plan, "dispatchable_tools", ()) or ())
                    if tool in table_dispatchable
                ],
                *operation_dispatchable_tools,
            ]
        ),
        denied_operations=tuple(getattr(plan, "denied_operations", ()) or ()),
        filtered_tools=tuple(
            [
                *list(getattr(plan, "filtered_tools", ()) or ()),
                *[
                    {
                        "tool_name": item.tool_name,
                        "operation_id": item.operation_id,
                        "reason": item.reason,
                        "source": item.source,
                    }
                    for item in table.filtered
                ],
            ]
        ),
        diagnostics={
            **dict(payload.get("diagnostics") or {}),
            "tool_capability_table": capability_table_to_runtime_plan_overlay(table),
            "capability_plan_overlay_source": "runtime.tool_capability_table",
        },
    )


def getattr_like(value: Any, name: str) -> Any:
    if hasattr(value, name):
        return getattr(value, name)
    if isinstance(value, dict):
        return value.get(name)
    return None


def _specific_task_assembly_policy_from_task_operation(task_operation: dict[str, Any]) -> SpecificTaskAssemblyPolicy | None:
    payload = dict(task_operation.get("specific_task_assembly_policy") or {})
    if not payload:
        payload = dict(dict(task_operation.get("task_execution_assembly") or {}).get("metadata") or {}).get(
            "specific_task_assembly_policy"
        ) or {}
    if not isinstance(payload, dict) or not payload:
        return None
    try:
        from task_system.tasks.assembly_policy import AgentSelectionPolicy, RequirementRefs, ToolCapabilityRequirements

        return SpecificTaskAssemblyPolicy(
            policy_id=str(payload.get("policy_id") or ""),
            task_id=str(payload.get("task_id") or ""),
            environment_id=str(payload.get("environment_id") or ""),
            flow_ref=str(payload.get("flow_ref") or ""),
            agent_selection=AgentSelectionPolicy(**dict(payload.get("agent_selection") or {})),
            skill_requirements=_requirement_refs_from_payload(payload.get("skill_requirements")),
            prompt_requirements=_requirement_refs_from_payload(payload.get("prompt_requirements")),
            tool_capability_requirements=ToolCapabilityRequirements(
                required_operations=_tuple_refs(dict(payload.get("tool_capability_requirements") or {}).get("required_operations")),
                optional_operations=_tuple_refs(dict(payload.get("tool_capability_requirements") or {}).get("optional_operations")),
                denied_operations=_tuple_refs(dict(payload.get("tool_capability_requirements") or {}).get("denied_operations")),
                required_tool_tags=_tuple_refs(dict(payload.get("tool_capability_requirements") or {}).get("required_tool_tags")),
                preferred_tools=_tuple_refs(dict(payload.get("tool_capability_requirements") or {}).get("preferred_tools")),
            ),
            memory_requirements=dict(payload.get("memory_requirements") or {}),
            resource_requirements=dict(payload.get("resource_requirements") or {}),
            output_contract_ref=str(payload.get("output_contract_ref") or ""),
            acceptance_policy=dict(payload.get("acceptance_policy") or {}),
            runtime_shape=str(payload.get("runtime_shape") or "single_agent"),
            metadata=dict(payload.get("metadata") or {}),
        )
    except (TypeError, ValueError):
        return None


def _requirement_refs_from_payload(value: Any) -> Any:
    from task_system.tasks.assembly_policy import RequirementRefs

    payload = dict(value or {})
    return RequirementRefs(
        required_refs=_tuple_refs(payload.get("required_refs")),
        optional_refs=_tuple_refs(payload.get("optional_refs")),
        denied_refs=_tuple_refs(payload.get("denied_refs")),
    )


def _tuple_refs(values: Any) -> tuple[str, ...]:
    refs: list[str] = []
    seen: set[str] = set()
    for value in list(values or []):
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        refs.append(item)
    return tuple(refs)


def _dedupe_refs(values: Any) -> tuple[str, ...]:
    refs: list[str] = []
    seen: set[str] = set()
    for value in list(values or []):
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        refs.append(item)
    return tuple(refs)
