from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent_runtime.understanding import (
    build_action_permit,
    build_boundary_policy,
    build_context_candidates,
    build_request_facts,
    build_runtime_start_packet,
    main_model_owned_turn_decision,
)


@dataclass(frozen=True, slots=True)
class AgentTurnContextBuildResult:
    request_facts: dict[str, Any]
    boundary_policy: dict[str, Any]
    context_candidates: dict[str, Any]
    model_turn_decision: dict[str, Any]
    model_turn_diagnostics: dict[str, Any]
    action_permit: dict[str, Any]
    runtime_start_packet: dict[str, Any]
    runtime_context_override: dict[str, Any]

    @property
    def action_allowed(self) -> bool:
        return bool(self.action_permit.get("allowed") is True)

    @property
    def model_turn_blocked(self) -> bool:
        return str(self.model_turn_decision.get("action_intent") or "") == "block"


async def build_agent_turn_context(
    *,
    session_id: str,
    task_id: str,
    user_message: str,
    source: str,
    task_selection: dict[str, Any],
    invocation_model_context: dict[str, Any] | None = None,
    task_order_binding: dict[str, Any] | None = None,
    model_response_executor: Any | None = None,
) -> AgentTurnContextBuildResult:
    runtime_context_override = {
        **dict(invocation_model_context or {}),
        **dict(task_selection or {}),
    }
    binding = dict(task_order_binding or {})
    if binding.get("task_order_id"):
        runtime_context_override["task_order_projection"] = binding
    request_facts = build_request_facts(
        user_message=user_message,
        session_id=session_id,
        task_id=task_id,
        turn_id=str(dict(task_selection or {}).get("turn_id") or ""),
        source=source,
        explicit_selection=task_selection,
    ).to_dict()
    boundary_policy = build_boundary_policy(
        user_message=user_message,
        request_facts=request_facts,
        current_turn_context=runtime_context_override,
    ).to_dict()
    context_candidates = build_context_candidates(
        request_facts=request_facts,
        continuation_candidates=[],
        memory_runtime_view={},
        current_turn_context=runtime_context_override,
    ).to_dict()
    model_turn_decision, model_turn_diagnostics = await main_model_owned_turn_decision(
        user_message=user_message,
        request_facts=request_facts,
        task_selection=task_selection,
        model_runtime=getattr(model_response_executor, "model_runtime", None),
    )
    action_permit = build_action_permit(
        model_turn_decision=model_turn_decision,
        boundary_policy=boundary_policy,
    ).to_dict()
    runtime_start_packet = build_runtime_start_packet(
        user_request=user_message,
        request_facts=request_facts,
        boundary_policy=boundary_policy,
        context_candidates=context_candidates,
        model_turn_decision=model_turn_decision,
        action_permit=action_permit,
    ).to_dict()
    runtime_context_override.update(
        {
            "request_facts": request_facts,
            "boundary_policy": boundary_policy,
            "context_candidates": context_candidates,
            "model_turn_decision": model_turn_decision,
            "model_turn_decision_diagnostics": model_turn_diagnostics,
            "action_permit": action_permit,
            "runtime_start_packet": runtime_start_packet,
        }
    )
    return AgentTurnContextBuildResult(
        request_facts=request_facts,
        boundary_policy=boundary_policy,
        context_candidates=context_candidates,
        model_turn_decision=model_turn_decision,
        model_turn_diagnostics=dict(model_turn_diagnostics or {}),
        action_permit=action_permit,
        runtime_start_packet=runtime_start_packet,
        runtime_context_override=runtime_context_override,
    )
