from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

from capability_system.mcp.local_registry import default_local_mcp_units
from permissions.operations import build_default_operation_registry
from harness.runtime.capability_surface import ToolCapability, ToolCapabilityFilterIssue, ToolCapabilitySourceTrace, ToolCapabilityTable

_OPERATION_REGISTRY = build_default_operation_registry()
_SUBAGENT_LIFECYCLE_TOOL_NAMES = {"subagent"}
_TASK_RUNTIME_OWNER_SCOPES = {"task_memory"}
_TASK_RUNTIME_TOOL_NAMES = {"agent_state"}
_TASK_RUNTIME_OPERATION_IDS = {"op.agent_todo"}


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
        owner_scope = _tool_owner_scope(tool, definition)
        for operation_id in _authorized_operation_ids_for_tool(tool, definition=definition, operation_decisions=operation_decisions):
            operation = _operation_descriptor(operation_id)
            if operation is not None:
                read_only = bool(operation.read_only)
                destructive = bool(operation.destructive)
                concurrency_safe = bool(operation.concurrency_safe)
                operation_type = str(operation.operation_type or "")
                requires_approval_by_default = bool(operation.requires_approval_by_default)
            else:
                read_only = bool(getattr(definition, "is_read_only", False))
                destructive = bool(getattr(definition, "is_destructive", False))
                concurrency_safe = bool(getattr(definition, "is_concurrency_safe", False))
                operation_type = ""
                requires_approval_by_default = bool(tool.get("requires_approval") is True)
            action_decision = dict(dict(tool.get("action_authorization") or {}).get(operation_id) or {})
            requires_approval = bool(
                tool.get("requires_approval") is True
                or action_decision.get("requires_approval") is True
                or requires_approval_by_default
            )
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
                        "authorization_reason": str(action_decision.get("reason") or tool.get("authorization_reason") or ""),
                        "tool_view": dict(tool),
                    },
                )
            )
    capabilities.extend(
        _local_mcp_route_capabilities(
            operation_authorization=operation_authorization,
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
            ToolCapabilitySourceTrace(source="tool_scheduling", detail="operation_authorization_filter"),
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
    filtered_issues: list[ToolCapabilityFilterIssue],
) -> bool:
    tool_name = _tool_name(tool)
    definition = definition_by_name.get(tool_name)
    operation_ids = _definition_operation_ids(definition, fallback=tool_name)
    operation_id = operation_ids[0] if operation_ids else tool_name
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
    if invocation_kind == "single_agent_turn" and (
        owner_scope in _TASK_RUNTIME_OWNER_SCOPES
        or tool_name in _TASK_RUNTIME_TOOL_NAMES
        or any(operation in _TASK_RUNTIME_OPERATION_IDS for operation in operation_ids)
    ):
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
    authorization_decisions = {
        operation: dict(operation_decisions.get(operation) or {})
        for operation in operation_ids
        if operation_decisions.get(operation) is not None
    }
    allowed_operation_ids = tuple(
        operation
        for operation, decision in authorization_decisions.items()
        if str(decision.get("final_decision") or "") in {"allow", "requires_approval"}
    )
    if operation_decisions and not authorization_decisions:
        filtered_issues.append(
            ToolCapabilityFilterIssue(
                operation_id=operation_id,
                tool_name=tool_name,
                reason="operation_missing_from_authorization_projection",
                source="operation_authorization",
                metadata={"operation_ids": list(operation_ids)},
            )
        )
        return False
    if operation_decisions and not allowed_operation_ids:
        first_decision = next(iter(authorization_decisions.values()), {})
        filtered_issues.append(
            ToolCapabilityFilterIssue(
                operation_id=operation_id,
                tool_name=tool_name,
                reason=str(first_decision.get("reason") or "operation_denied"),
                source="operation_authorization",
                metadata={"operation_ids": list(operation_ids), "decisions": list(authorization_decisions.values())},
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
    operation_ids = _definition_operation_ids(definition, fallback=tool_name)
    requires_operations = {
        str(item or "").strip()
        for item in list(operation_authorization.get("requires_approval_operations") or [])
        if str(item or "").strip()
    }
    action_authorization: dict[str, dict[str, Any]] = {}
    requires_approval = bool(payload.get("requires_approval") is True)
    authorization_reasons: list[str] = []
    allowed_operation_ids: list[str] = []
    for operation_id in operation_ids:
        operation = _operation_descriptor(operation_id)
        decision = operation_decisions.get(operation_id)
        decision_kind = str(dict(decision or {}).get("final_decision") or dict(decision or {}).get("decision") or "")
        action_requires_approval = bool(
            operation_id in requires_operations
            or decision_kind == "requires_approval"
            or bool(getattr(operation, "requires_approval_by_default", False))
        )
        if action_requires_approval:
            requires_approval = True
        if not operation_decisions or decision_kind in {"allow", "requires_approval"}:
            allowed_operation_ids.append(operation_id)
        reason = str(dict(decision or {}).get("reason") or "")
        if reason:
            authorization_reasons.append(reason)
        action_authorization[operation_id] = {
            "operation_id": operation_id,
            "decision": decision_kind or ("allow" if not operation_decisions else "unknown"),
            "requires_approval": action_requires_approval,
            "reason": reason,
        }
    return {
        **payload,
        "authorized_operation_ids": allowed_operation_ids,
        "action_authorization": action_authorization,
        "requires_approval": requires_approval,
        "authorization_reason": str(payload.get("authorization_reason") or ", ".join(dict.fromkeys(authorization_reasons)) or ""),
    }


def _tool_owner_scope(tool: dict[str, Any], definition: Any | None) -> str:
    contract = getattr(definition, "contract", None)
    return str(tool.get("owner_scope") or getattr(contract, "owner_scope", "") or "none").strip()


def _local_mcp_route_capabilities(
    *,
    operation_authorization: dict[str, Any],
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
        if operation_id in allowed_operations:
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
        reason = denied_reasons.get(operation_id)
        if reason:
            filtered_issues.append(
                ToolCapabilityFilterIssue(
                    operation_id=operation_id,
                    tool_name=tool_name,
                    reason=reason,
                    source="operation_authorization",
                    metadata={"operation_id": operation_id, "authority": "harness.runtime.operation_authorization"},
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


def _definition_operation_ids(definition: Any | None, *, fallback: str = "") -> tuple[str, ...]:
    operation_ids: list[str] = []
    primary = str(getattr(definition, "operation_id", "") or "").strip()
    if primary:
        operation_ids.append(primary)
    for operation_id in dict(getattr(definition, "action_operation_ids", {}) or {}).values():
        value = str(operation_id or "").strip()
        if value:
            operation_ids.append(value)
    if not operation_ids and fallback:
        operation_ids.append(str(fallback).strip())
    result: list[str] = []
    seen: set[str] = set()
    for operation_id in operation_ids:
        if not operation_id or operation_id in seen:
            continue
        seen.add(operation_id)
        result.append(operation_id)
    return tuple(result)


def _authorized_operation_ids_for_tool(
    tool: dict[str, Any],
    *,
    definition: Any | None,
    operation_decisions: dict[str, dict[str, Any]],
) -> tuple[str, ...]:
    explicit = tuple(
        str(item or "").strip()
        for item in list(tool.get("authorized_operation_ids") or [])
        if str(item or "").strip()
    )
    if explicit:
        return explicit
    operation_ids = _definition_operation_ids(definition, fallback=_tool_name(tool))
    if not operation_decisions:
        return operation_ids
    return tuple(
        operation_id
        for operation_id in operation_ids
        if str(dict(operation_decisions.get(operation_id) or {}).get("final_decision") or "") in {"allow", "requires_approval"}
    )
