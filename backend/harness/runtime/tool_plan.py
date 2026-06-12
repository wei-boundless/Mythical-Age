from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

from capability_system.mcp.local_registry import default_local_mcp_units
from permissions.operations import build_default_operation_registry
from runtime.tooling import ToolCapability, ToolCapabilityFilterIssue, ToolCapabilitySourceTrace, ToolCapabilityTable

from .tool_scheduling import (
    evaluate_environment_operation,
    operation_requests_from_authorization,
    operation_requests_from_runtime_contract,
)

_OPERATION_REGISTRY = build_default_operation_registry()
_SUBAGENT_LIFECYCLE_TOOL_NAMES = {
    "spawn_subagent",
    "send_subagent_message",
    "wait_subagent",
    "list_subagents",
    "close_subagent",
}
_TASK_RUNTIME_OWNER_SCOPES = {"task_memory"}


@dataclass(frozen=True, slots=True)
class RuntimeToolPlan:
    plan_id: str
    session_id: str
    turn_id: str
    agent_invocation_id: str
    invocation_kind: str
    model_visible_tools: tuple[dict[str, Any], ...] = ()
    dispatchable_tool_names: tuple[str, ...] = ()
    capability_table: ToolCapabilityTable | None = None
    operation_authorization: dict[str, Any] = field(default_factory=dict)
    schema_hash: str = ""
    registry_hash: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "harness.runtime.tool_plan"

    def __post_init__(self) -> None:
        if self.authority != "harness.runtime.tool_plan":
            raise ValueError("RuntimeToolPlan authority must be harness.runtime.tool_plan")
        if not self.plan_id:
            raise ValueError("RuntimeToolPlan requires plan_id")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["model_visible_tools"] = [dict(item) for item in self.model_visible_tools]
        payload["dispatchable_tool_names"] = list(self.dispatchable_tool_names)
        payload["capability_table"] = self.capability_table.to_dict() if self.capability_table is not None else {}
        payload["operation_authorization"] = dict(self.operation_authorization or {})
        payload["diagnostics"] = dict(self.diagnostics or {})
        return payload


def build_runtime_tool_plan(
    *,
    runtime_assembly: Any,
    invocation_kind: str,
    tool_definitions_by_name: dict[str, Any] | None = None,
) -> RuntimeToolPlan:
    assembly = runtime_assembly.to_dict() if hasattr(runtime_assembly, "to_dict") else dict(runtime_assembly or {})
    definition_by_name = dict(tool_definitions_by_name or {})
    environment_payload = dict(assembly.get("task_environment") or {})
    operation_authorization = dict(assembly.get("operation_authorization") or {})
    operation_decisions = _operation_decisions_by_id(operation_authorization)
    task_requested_operations = tuple(
        dict.fromkeys(
            [
                *operation_requests_from_authorization(operation_authorization),
                *operation_requests_from_runtime_contract(dict(assembly.get("runtime_contract") or {})),
            ]
        )
    )
    filtered_issues: list[ToolCapabilityFilterIssue] = []
    visible_tools = tuple(
        sorted(
            (
                _tool_with_authorization_metadata(
                    dict(item),
                    definition_by_name=definition_by_name,
                    operation_authorization=operation_authorization,
                    operation_decisions=operation_decisions,
                )
                for item in list(assembly.get("available_tools") or [])
                if isinstance(item, dict)
                and _tool_allowed_for_runtime_plan(
                    dict(item),
                    invocation_kind=invocation_kind,
                    definition_by_name=definition_by_name,
                    operation_decisions=operation_decisions,
                    environment_payload=environment_payload,
                    task_requested_operations=task_requested_operations,
                    filtered_issues=filtered_issues,
                )
            ),
            key=lambda item: _tool_name(item),
        )
    )
    capabilities = []
    for tool in visible_tools:
        name = _tool_name(tool)
        if not name:
            continue
        definition = definition_by_name.get(name)
        operation_id = str(tool.get("operation_id") or getattr(definition, "operation_id", "") or name)
        operation = _operation_descriptor(operation_id)
        owner_scope = _tool_owner_scope(tool, definition)
        if operation is not None:
            read_only = bool(operation.read_only)
            destructive = bool(operation.destructive)
            concurrency_safe = bool(operation.concurrency_safe)
            operation_type = str(operation.operation_type or "")
            requires_approval = bool(tool.get("requires_approval") is True)
            requires_approval_by_default = bool(operation.requires_approval_by_default)
        else:
            read_only = bool(getattr(definition, "is_read_only", False))
            destructive = bool(getattr(definition, "is_destructive", False))
            concurrency_safe = bool(getattr(definition, "is_concurrency_safe", False))
            operation_type = ""
            requires_approval = bool(tool.get("requires_approval") is True)
            requires_approval_by_default = requires_approval
        capabilities.append(
            ToolCapability(
                operation_id=operation_id,
                tool_name=name,
                visible=True,
                dispatchable=True,
                requires_approval=requires_approval,
                source_trace=(
                    ToolCapabilitySourceTrace(source="runtime_assembly", detail=name),
                    ToolCapabilitySourceTrace(source="tool_scheduling", detail=operation_id),
                ),
                metadata={
                    "read_only": read_only,
                    "destructive": destructive,
                    "concurrency_safe": concurrency_safe,
                    "operation_type": operation_type,
                    "owner_scope": owner_scope,
                    "requires_approval_by_default": requires_approval_by_default,
                    "authorization_reason": str(tool.get("authorization_reason") or ""),
                    "tool_view": dict(tool),
                },
            )
        )
    capabilities.extend(
        _local_mcp_route_capabilities(
            operation_authorization=operation_authorization,
            environment_payload=environment_payload,
            task_requested_operations=task_requested_operations,
            filtered_issues=filtered_issues,
        )
    )
    table = ToolCapabilityTable(
        table_id=f"tool-capability:{assembly.get('turn_id') or 'turn'}:{invocation_kind}",
        environment_id=str(dict(assembly.get("task_environment") or {}).get("environment_id") or ""),
        capabilities=tuple(sorted(capabilities, key=lambda item: (item.operation_id, item.tool_name))),
        filtered=tuple(filtered_issues),
        source_trace=(
            ToolCapabilitySourceTrace(source="runtime_tool_plan", detail=invocation_kind),
            ToolCapabilitySourceTrace(source="tool_scheduling", detail="environment_hard_filter"),
        ),
    )
    schema_hash = _stable_hash(visible_tools)
    registry_hash = _stable_hash(table.to_dict())
    return RuntimeToolPlan(
        plan_id=f"rttoolplan:{assembly.get('turn_id') or 'turn'}:{invocation_kind}:{schema_hash[:12]}",
        session_id=str(assembly.get("session_id") or ""),
        turn_id=str(assembly.get("turn_id") or ""),
        agent_invocation_id=str(assembly.get("agent_invocation_id") or ""),
        invocation_kind=str(invocation_kind or ""),
        model_visible_tools=visible_tools,
        dispatchable_tool_names=tuple(sorted(table.dispatchable_tools)),
        capability_table=table,
        operation_authorization=dict(assembly.get("operation_authorization") or {}),
        schema_hash=schema_hash,
        registry_hash=registry_hash,
        diagnostics={
            "visible_tool_count": len(visible_tools),
            "dispatchable_tool_count": len(table.dispatchable_tools),
            "filtered_tool_count": len(filtered_issues),
            "local_mcp_route_count": sum(1 for item in table.capabilities if dict(item.metadata).get("runtime_exposure") == "local_mcp_runtime"),
            "source": "runtime_assembly.available_tools+tool_scheduling",
        },
    )


def tool_instances_for_runtime_tool_plan(
    *,
    tool_instances: list[Any] | tuple[Any, ...] | None,
    tool_plan: RuntimeToolPlan | dict[str, Any],
) -> list[Any]:
    plan = tool_plan.to_dict() if hasattr(tool_plan, "to_dict") else dict(tool_plan or {})
    visible = {
        str(item.get("tool_name") or item.get("name") or "").strip()
        for item in list(plan.get("model_visible_tools") or [])
        if isinstance(item, dict) and str(item.get("tool_name") or item.get("name") or "").strip()
    }
    if not visible:
        visible = {
            str(item or "").strip()
            for item in list(plan.get("dispatchable_tool_names") or [])
            if str(item or "").strip()
        }
    if not visible:
        return []
    return [
        tool
        for tool in list(tool_instances or [])
        if str(getattr(tool, "name", "") or "").strip() in visible
    ]


def _stable_hash(payload: Any) -> str:
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _tool_name(tool: dict[str, Any]) -> str:
    return str(tool.get("tool_name") or tool.get("name") or "").strip()


def _tool_allowed_for_runtime_plan(
    tool: dict[str, Any],
    *,
    invocation_kind: str,
    definition_by_name: dict[str, Any],
    operation_decisions: dict[str, dict[str, Any]],
    environment_payload: dict[str, Any],
    task_requested_operations: tuple[str, ...],
    filtered_issues: list[ToolCapabilityFilterIssue],
) -> bool:
    tool_name = _tool_name(tool)
    definition = definition_by_name.get(tool_name)
    operation_id = str(tool.get("operation_id") or getattr(definition, "operation_id", "") or tool_name)
    owner_scope = _tool_owner_scope(tool, definition)
    if tool_name in _SUBAGENT_LIFECYCLE_TOOL_NAMES and invocation_kind != "task_execution":
        filtered_issues.append(
            ToolCapabilityFilterIssue(
                operation_id=operation_id,
                tool_name=tool_name,
                reason="subagent_lifecycle_requires_task_execution",
                source="invocation_kind",
                metadata={"invocation_kind": str(invocation_kind or "")},
            )
        )
        return False
    if invocation_kind == "single_agent_turn" and owner_scope in _TASK_RUNTIME_OWNER_SCOPES:
        filtered_issues.append(
            ToolCapabilityFilterIssue(
                operation_id=operation_id,
                tool_name=tool_name,
                reason="task_scoped_tool_requires_task_run",
                source="runtime_scope",
                metadata={
                    "invocation_kind": str(invocation_kind or ""),
                    "owner_scope": owner_scope,
                    "required_action": "request_task_run",
                },
            )
        )
        return False
    authorization_decision = operation_decisions.get(operation_id)
    if operation_decisions and authorization_decision is None:
        filtered_issues.append(
            ToolCapabilityFilterIssue(
                operation_id=operation_id,
                tool_name=tool_name,
                reason="operation_missing_from_authorization_projection",
                source="operation_authorization",
            )
        )
        return False
    if authorization_decision is not None and str(authorization_decision.get("final_decision") or "") not in {"allow", "requires_approval"}:
        filtered_issues.append(
            ToolCapabilityFilterIssue(
                operation_id=operation_id,
                tool_name=tool_name,
                reason=str(authorization_decision.get("reason") or "operation_denied"),
                source="operation_authorization",
                metadata=dict(authorization_decision),
            )
        )
        return False
    environment_decision = evaluate_environment_operation(
        operation_id,
        environment_payload=environment_payload,
        task_requested_operations=task_requested_operations,
    )
    if not environment_decision.allowed:
        filtered_issues.append(
            ToolCapabilityFilterIssue(
                operation_id=operation_id,
                tool_name=tool_name,
                reason=environment_decision.reason,
                source="task_environment",
                metadata=environment_decision.to_dict(),
            )
        )
        return False
    return True


def _tool_with_authorization_metadata(
    tool: dict[str, Any],
    *,
    definition_by_name: dict[str, Any],
    operation_authorization: dict[str, Any],
    operation_decisions: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    payload = dict(tool or {})
    tool_name = _tool_name(payload)
    definition = definition_by_name.get(tool_name)
    operation_id = str(payload.get("operation_id") or getattr(definition, "operation_id", "") or tool_name)
    operation = _operation_descriptor(operation_id)
    decision = operation_decisions.get(operation_id)
    requires_operations = {
        str(item or "").strip()
        for item in list(operation_authorization.get("requires_approval_operations") or [])
        if str(item or "").strip()
    }
    decision_kind = str(dict(decision or {}).get("final_decision") or dict(decision or {}).get("decision") or "")
    requires_approval = (
        bool(payload.get("requires_approval") is True)
        or operation_id in requires_operations
        or decision_kind == "requires_approval"
        or bool(getattr(operation, "requires_approval_by_default", False))
    )
    return {
        **payload,
        "requires_approval": requires_approval,
        "authorization_reason": str(dict(decision or {}).get("reason") or payload.get("authorization_reason") or ""),
    }


def _tool_owner_scope(tool: dict[str, Any], definition: Any | None) -> str:
    contract = getattr(definition, "contract", None)
    return str(tool.get("owner_scope") or getattr(contract, "owner_scope", "") or "none").strip()


def _local_mcp_route_capabilities(
    *,
    operation_authorization: dict[str, Any],
    environment_payload: dict[str, Any],
    task_requested_operations: tuple[str, ...],
    filtered_issues: list[ToolCapabilityFilterIssue],
) -> list[ToolCapability]:
    allowed_operations = {
        str(item or "").strip()
        for item in list(operation_authorization.get("allowed_operations") or [])
        if str(item or "").strip()
    }
    denied_reasons = {
        str(item.get("operation_id") or ""): str(item.get("reason") or "operation_denied")
        for item in list(operation_authorization.get("decisions") or [])
        if isinstance(item, dict) and str(item.get("final_decision") or "") != "allow"
    }
    capabilities: list[ToolCapability] = []
    for unit in default_local_mcp_units():
        operation_id = str(unit.operation_id or "").strip()
        tool_name = f"mcp__langchain_agent__{unit.route}"
        if not operation_id:
            continue
        environment_decision = evaluate_environment_operation(
            operation_id,
            environment_payload=environment_payload,
            task_requested_operations=task_requested_operations,
        )
        if operation_id in allowed_operations and environment_decision.allowed:
            capabilities.append(
                ToolCapability(
                    operation_id=operation_id,
                    tool_name=tool_name,
                    visible=False,
                    dispatchable=False,
                    requires_approval=False,
                    source_trace=(
                        ToolCapabilitySourceTrace(source="operation_authorization", detail=operation_id),
                        ToolCapabilitySourceTrace(source="local_mcp_registry", detail=unit.unit_id),
                        ToolCapabilitySourceTrace(source="tool_scheduling", detail="deferred_capability_route"),
                    ),
                    metadata={
                        "runtime_exposure": "local_mcp_runtime",
                        "route": unit.route,
                        "unit_id": unit.unit_id,
                        "title": unit.title,
                        "category": unit.category,
                        "deferred_tool": True,
                        "model_visibility": "runtime_bound_only",
                    },
                )
            )
            continue
        if operation_id in allowed_operations and not environment_decision.allowed:
            filtered_issues.append(
                ToolCapabilityFilterIssue(
                    operation_id=operation_id,
                    tool_name=tool_name,
                    reason=environment_decision.reason,
                    source="task_environment",
                    metadata=environment_decision.to_dict(),
                )
            )
            continue
        reason = denied_reasons.get(operation_id)
        if reason:
            filtered_issues.append(
                ToolCapabilityFilterIssue(
                    operation_id=operation_id,
                    tool_name=tool_name,
                    reason=reason,
                    source="operation_authorization",
                    metadata=environment_decision.to_dict(),
                )
            )
    return capabilities


def _operation_decisions_by_id(operation_authorization: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("operation_id") or ""): dict(item)
        for item in list(operation_authorization.get("decisions") or [])
        if isinstance(item, dict) and str(item.get("operation_id") or "").strip()
    }


def _operation_descriptor(operation_id: str) -> Any | None:
    return _OPERATION_REGISTRY.get_operation(str(operation_id or "").strip())
