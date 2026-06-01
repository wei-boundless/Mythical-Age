from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from harness.loop.active_work import build_active_work_turn_context, decide_active_work_turn


TurnRouteKind = Literal[
    "plain_conversation",
    "agent_native_turn",
    "agent_action",
    "active_work_control",
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
            "conversation_only",
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


def build_turn_route(
    *,
    runtime_assembly: Any,
    active_work_decision: Any | None = None,
    active_work_context: Any | None = None,
) -> TurnRoute:
    assembly_payload = runtime_assembly.to_dict() if hasattr(runtime_assembly, "to_dict") else dict(runtime_assembly or {})
    capabilities = dict(assembly_payload.get("control_capabilities") or {})
    if active_work_decision is not None:
        action = str(getattr(active_work_decision, "action", "") or "").strip()
        if action and action not in {"normal_response", "start_new_work"}:
            return TurnRoute(
                route_kind="active_work_control",
                invocation_kind="active_work_control",
                dispatch_target="query_runtime.active_work_control",
                reason="active_work_decision_requires_control",
                control_capabilities=capabilities,
                monitor_policy={"record_task_monitor": True, "record_turn_monitor": False},
                diagnostics={
                    "active_work_action": action,
                    "active_work_task_run_id": str(getattr(active_work_context, "task_run_id", "") or ""),
                    "active_work_status": str(getattr(active_work_context, "status", "") or ""),
                },
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
    if bool(capabilities.get("conversation_only") is True):
        return TurnRoute(
            route_kind="plain_conversation",
            invocation_kind="plain_conversation",
            dispatch_target="query_runtime.plain_conversation",
            reason="conversation_only_capability",
            control_capabilities=capabilities,
            monitor_policy={"record_task_monitor": False, "record_turn_monitor": False},
            diagnostics={"explicit_contract_present": False},
        )
    if not bool(capabilities.get("requires_json_action_protocol") is True):
        if bool(capabilities.get("may_request_task_run") is True) and not bool(capabilities.get("may_use_subagents") is True):
            return TurnRoute(
                route_kind="agent_native_turn",
                invocation_kind="agent_native_turn",
                dispatch_target="query_runtime.agent_native_turn",
                reason="assistant_message_first_with_task_run_action",
                control_capabilities=capabilities,
                monitor_policy={"record_task_monitor": False, "record_turn_monitor": False},
                diagnostics={"explicit_contract_present": False},
            )
        return TurnRoute(
            route_kind="plain_conversation",
            invocation_kind="plain_conversation",
            dispatch_target="query_runtime.plain_conversation",
            reason="json_action_protocol_not_required",
            control_capabilities=capabilities,
            monitor_policy={"record_task_monitor": False, "record_turn_monitor": False},
            diagnostics={"explicit_contract_present": False},
        )
    return TurnRoute(
        route_kind="agent_action",
        invocation_kind="turn_action",
        dispatch_target="agent_harness.agent_action",
        reason="action_capable_runtime",
        control_capabilities=capabilities,
        monitor_policy={"record_task_monitor": False, "record_turn_monitor": True},
        diagnostics={"explicit_contract_present": False},
    )


async def decide_turn_route(
    *,
    runtime_host: Any,
    runtime_assembly: Any,
    session_id: str,
    user_message: str,
    model_runtime: Any,
    model_selection: dict[str, Any] | None = None,
) -> tuple[TurnRoute, Any | None, Any | None]:
    context = None
    decision = None
    if active_work_router_enabled_for_assembly(runtime_assembly):
        context = build_active_work_turn_context(
            runtime_host,
            session_id=session_id,
        )
        if context is not None:
            decision = await decide_active_work_turn(
                model_runtime=model_runtime,
                user_message=user_message,
                active_work_context=context,
                model_selection=dict(model_selection or {}),
            )
    return (
        build_turn_route(
            runtime_assembly=runtime_assembly,
            active_work_decision=decision,
            active_work_context=context,
        ),
        context,
        decision,
    )


def active_work_router_enabled_for_assembly(runtime_assembly: Any) -> bool:
    payload = runtime_assembly.to_dict() if hasattr(runtime_assembly, "to_dict") else dict(runtime_assembly or {})
    capabilities = dict(payload.get("control_capabilities") or {})
    if capabilities.get("conversation_only") is True or capabilities.get("may_control_active_work") is False:
        return False
    profile = dict(payload.get("profile") or {})
    task_lifecycle = dict(profile.get("task_lifecycle_policy") or {})
    context_policy = dict(profile.get("context_policy") or {})
    interaction_policy = dict(profile.get("interaction_policy") or {})
    if task_lifecycle.get("active_work_router") is False:
        return False
    if context_policy.get("active_work_context") is False or interaction_policy.get("active_work_router") is False:
        return False
    if task_lifecycle.get("request_task_run") is not True:
        return False
    active_work_context = str(
        context_policy.get("active_work_context")
        or context_policy.get("task_context")
        or ""
    ).strip().lower()
    if active_work_context in {"disabled", "none", "off", "false", "readonly"}:
        return False
    return True


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
