from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


TurnRouteKind = Literal[
    "single_agent_turn",
    "explicit_contract_task",
    "blocked_runtime",
]


@dataclass(frozen=True, slots=True)
class TurnRoute:
    route_kind: TurnRouteKind
    invocation_kind: str
    dispatch_target: str
    reason: str
    control_capabilities: dict[str, Any] = field(default_factory=dict)
    monitor_policy: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "harness.routing.turn_route"

    def __post_init__(self) -> None:
        if self.authority != "harness.routing.turn_route":
            raise ValueError("TurnRoute authority must be harness.routing.turn_route")
        if not self.route_kind:
            raise ValueError("TurnRoute requires route_kind")
        allowed_capabilities = {
            "authority",
            "may_emit_assistant_message",
            "may_call_tools",
            "may_request_task_run",
            "may_control_active_work",
            "may_use_subagents",
            "requires_json_action_protocol",
            "has_explicit_contract",
            "visible_tool_count",
        }
        unknown = set(self.control_capabilities).difference(allowed_capabilities)
        if unknown:
            raise ValueError(f"TurnRoute received unknown control capability fields: {sorted(unknown)}")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["control_capabilities"] = dict(self.control_capabilities)
        payload["monitor_policy"] = dict(self.monitor_policy)
        payload["diagnostics"] = dict(self.diagnostics)
        return payload


def build_turn_route(*, runtime_assembly: Any) -> TurnRoute:
    assembly_payload = runtime_assembly.to_dict() if hasattr(runtime_assembly, "to_dict") else dict(runtime_assembly or {})
    capabilities = dict(assembly_payload.get("control_capabilities") or {})
    if _runtime_blocked(assembly_payload):
        return TurnRoute(
            route_kind="blocked_runtime",
            invocation_kind="blocked_runtime",
            dispatch_target="query_runtime.blocked_runtime",
            reason="runtime_assembly_blocked",
            control_capabilities=capabilities,
            monitor_policy={"record_task_monitor": False, "record_turn_monitor": False},
            diagnostics={"runtime_status": str(assembly_payload.get("status") or "")},
        )
    if _has_explicit_contract(assembly_payload):
        return TurnRoute(
            route_kind="explicit_contract_task",
            invocation_kind="task_execution_start",
            dispatch_target="query_runtime.explicit_contract_task",
            reason="explicit_contract_present",
            control_capabilities=capabilities,
            monitor_policy={"record_task_monitor": True, "record_turn_monitor": False},
            diagnostics={"explicit_contract_present": True},
        )
    return TurnRoute(
        route_kind="single_agent_turn",
        invocation_kind="single_agent_turn",
        dispatch_target="query_runtime.single_agent_turn",
        reason="default_agent_runtime_turn",
        control_capabilities=capabilities,
        monitor_policy={"record_task_monitor": False, "record_turn_monitor": False},
        diagnostics={"explicit_contract_present": False},
    )


def _runtime_blocked(assembly_payload: dict[str, Any]) -> bool:
    status = str(assembly_payload.get("status") or "").strip().lower()
    if status in {"blocked", "failed", "invalid"}:
        return True
    diagnostics = dict(assembly_payload.get("diagnostics") or {})
    return bool(diagnostics.get("blocked_runtime") is True or diagnostics.get("runtime_blocked") is True)


def _has_explicit_contract(assembly_payload: dict[str, Any]) -> bool:
    engagement_contract = dict(assembly_payload.get("engagement_contract") or {})
    task_selection = dict(assembly_payload.get("task_selection") or {})
    return bool(
        engagement_contract
        or task_selection.get("task_contract")
        or task_selection.get("task_contract_seed")
        or task_selection.get("engagement_contract")
        or task_selection.get("engagement_contract_ref")
    )
