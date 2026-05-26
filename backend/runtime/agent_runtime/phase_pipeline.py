from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from runtime.contracts.deliverable_validator import validate_deliverable
from runtime.contracts.obligation_validation import validate_obligations
from runtime.memory.evidence_packet import build_evidence_packet
from runtime.memory.tool_observation_ledger import (
    ToolObservationLedger,
    build_tool_observation_record,
)

from .professional.agent_plan import AgentPlanRequired, build_agent_plan_draft, empty_agent_plan_draft
from .professional.completion_judgment import build_verification_review, judge_completion
from .professional.goal_contract import _goal_contract_from_semantic_contract
from .professional.plan_coverage import review_plan_coverage


@dataclass(slots=True)
class AgentPhaseOutcome:
    terminal_reason: str = "completed"
    final_answer_metadata: dict[str, Any] = field(default_factory=dict)
    run_outcome: dict[str, Any] = field(default_factory=dict)
    final_content: str = ""


def append_pre_model_phase_events(
    *,
    runtime_host: Any,
    task_run_id: str,
    task_contract_ref: str,
    task_id: str,
    selected_recipe_payload: dict[str, Any],
    agent_runtime_config: Any,
) -> list[dict[str, Any]]:
    enabled = set(getattr(agent_runtime_config, "enabled_phases", ()) or ())
    if "planning" not in enabled:
        return []
    metadata = dict(selected_recipe_payload.get("metadata") or {})
    semantic_contract = dict(metadata.get("task_requirement_contract") or {})
    execution_obligation = dict(
        metadata.get("execution_obligation")
        or semantic_contract.get("execution_obligation")
        or {}
    )
    model_plan_draft = dict(metadata.get("agent_plan_draft") or {})
    try:
        plan = build_agent_plan_draft(
            task_id=task_id,
            semantic_contract=semantic_contract,
            execution_obligation=execution_obligation,
            model_agent_plan_draft=model_plan_draft,
        ).to_dict()
        requirement: dict[str, Any] = {}
    except AgentPlanRequired as exc:
        requirement = exc.requirement.to_dict()
        plan = empty_agent_plan_draft(
            task_id=task_id,
            semantic_contract=semantic_contract,
            requirement=requirement,
        ).to_dict()
    review = review_plan_coverage(
        task_id=task_id,
        semantic_contract=semantic_contract,
        agent_plan_draft=plan,
    ).to_dict()
    event = runtime_host.event_log.append(
        task_run_id,
        "agent_runtime_planning_phase_checked",
        payload={
            "interaction_mode": str(getattr(agent_runtime_config, "interaction_mode", "") or ""),
            "enabled_phases": list(getattr(agent_runtime_config, "enabled_phases", ()) or ()),
            "agent_plan_requirement": requirement,
            "agent_plan_draft": plan,
            "plan_coverage_review": review,
            "phase_authority": "runtime.agent_runtime.phase_pipeline",
        },
        refs={"task_contract_ref": task_contract_ref},
    )
    return [{"type": "runtime_loop_event", "event": event.to_dict()}]


def apply_post_model_phases(
    *,
    runtime_host: Any,
    task_run_id: str,
    task_id: str,
    user_message: str,
    task_contract_ref: str,
    selected_recipe_payload: dict[str, Any],
    agent_runtime_config: Any,
    final_content: str,
    final_answer_metadata: dict[str, Any],
    terminal_reason: str,
    tool_call_count: int,
    tool_observation_count: int,
) -> tuple[AgentPhaseOutcome, list[dict[str, Any]]]:
    enabled = set(getattr(agent_runtime_config, "enabled_phases", ()) or ())
    if not enabled.intersection({"evidence", "verification", "closeout"}):
        return (
            AgentPhaseOutcome(
                terminal_reason=terminal_reason,
                final_answer_metadata=dict(final_answer_metadata or {}),
                final_content=final_content,
            ),
            [],
        )

    metadata = dict(selected_recipe_payload.get("metadata") or {})
    semantic_contract = dict(metadata.get("task_requirement_contract") or {})
    execution_obligation = dict(
        metadata.get("execution_obligation")
        or semantic_contract.get("execution_obligation")
        or {}
    )
    verification_policy = dict(metadata.get("verification_policy") or {})
    strict = bool(verification_policy.get("strict") is True or "verification" in enabled)
    observations = _tool_observations_from_event_log(runtime_host.event_log.list_events(task_run_id))
    ledger = _tool_observation_ledger(
        task_run_id=task_run_id,
        observations=observations,
    )
    goal_contract = _goal_contract_from_semantic_contract(
        task_run_id=task_run_id,
        user_message=user_message,
        semantic_contract=semantic_contract,
    )
    evidence_packet = build_evidence_packet(
        task_run_id=task_run_id,
        semantic_contract=semantic_contract,
        observations=observations,
    ).to_dict()
    deliverable_validation = validate_deliverable(
        final_answer=final_content,
        semantic_contract=semantic_contract,
        evidence_packet=evidence_packet,
        strict=strict,
        required_output_paths=goal_contract.required_output_paths,
    ).to_dict()
    obligation_validation = validate_obligations(
        execution_obligation=execution_obligation,
        semantic_contract=semantic_contract,
        goal_contract=goal_contract,
        tool_observation_ledger=ledger,
        final_content=final_content,
        deliverable_validation=deliverable_validation,
        terminal_reason=terminal_reason,
        tool_execution_enabled=tool_call_count > 0 or tool_observation_count > 0,
        tool_call_count=tool_call_count,
        tool_observation_count=max(tool_observation_count, len(observations)),
        protocol_leak_detected=bool(deliverable_validation.get("protocol_leak_detected") is True),
    ).to_dict()
    verification_review = build_verification_review(
        task_run_id=task_run_id,
        semantic_contract=semantic_contract,
        evidence_packet=evidence_packet,
        deliverable_validation=deliverable_validation,
        obligation_validation=obligation_validation,
    ).to_dict()
    completion_judgment = judge_completion(
        task_run_id=task_run_id,
        semantic_contract=semantic_contract,
        evidence_packet=evidence_packet,
        verification_review=verification_review,
        terminal_reason=terminal_reason,
    ).to_dict()
    verification = {
        "interaction_mode": str(getattr(agent_runtime_config, "interaction_mode", "") or ""),
        "enabled_phases": list(getattr(agent_runtime_config, "enabled_phases", ()) or ()),
        "evidence_packet": evidence_packet,
        "tool_observation_ledger": ledger.to_dict(),
        "deliverable_validation": deliverable_validation,
        "obligation_validation": obligation_validation,
        "verification_review": verification_review,
        "completion_judgment": completion_judgment,
        "passed": bool(verification_review.get("passed") is True),
        "phase_authority": "runtime.agent_runtime.phase_pipeline",
    }
    event = runtime_host.event_log.append(
        task_run_id,
        "agent_runtime_closeout_phase_checked",
        payload={"verification": verification},
        refs={"task_contract_ref": task_contract_ref},
    )
    next_terminal_reason = terminal_reason
    if terminal_reason == "completed" and not bool(verification.get("passed") is True):
        next_terminal_reason = (
            "partial_contract_failed"
            if str(final_content or "").strip()
            else "agent_phase_validation_failed"
        )
    run_outcome = {
        "task_run_id": task_run_id,
        "task_id": task_id,
        "terminal_reason": next_terminal_reason,
        "verification": verification,
        "completion_judgment": completion_judgment,
        "authority": "runtime.agent_runtime.phase_pipeline",
    }
    metadata_out = {
        **dict(final_answer_metadata or {}),
        "verification_review": verification_review,
        "completion_judgment": completion_judgment,
        "run_outcome": run_outcome,
    }
    return (
        AgentPhaseOutcome(
            terminal_reason=next_terminal_reason,
            final_answer_metadata=metadata_out,
            run_outcome=run_outcome,
            final_content=final_content,
        ),
        [{"type": "runtime_loop_event", "event": event.to_dict()}],
    )


def _tool_observations_from_event_log(events: list[Any] | tuple[Any, ...]) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    for event in list(events or []):
        if str(getattr(event, "event_type", "") or "") != "executor_observation_received":
            continue
        payload = dict(getattr(event, "payload", {}) or {})
        observation = dict(payload.get("observation") or {})
        observation_payload = dict(observation.get("payload") or {})
        if not observation_payload:
            continue
        observations.append(
            {
                "observation_ref": str(
                    dict(getattr(event, "refs", {}) or {}).get("observation_ref")
                    or observation.get("observation_id")
                    or getattr(event, "event_id", "")
                    or ""
                ),
                "tool_name": str(observation_payload.get("tool_name") or ""),
                "tool_args": dict(observation_payload.get("tool_args") or {}),
                "result": observation_payload.get("result"),
                "result_envelope": dict(observation_payload.get("result_envelope") or {}),
                "structured_payload": dict(observation_payload.get("structured_payload") or {}),
                "observed_paths": list(observation_payload.get("observed_paths") or []),
                "matched_paths": list(observation_payload.get("matched_paths") or []),
                "artifact_refs": [
                    dict(item)
                    for item in list(observation_payload.get("artifact_refs") or [])
                    if isinstance(item, dict)
                ],
                "command_receipt": dict(observation_payload.get("command_receipt") or {}),
            }
        )
    return observations


def _tool_observation_ledger(
    *,
    task_run_id: str,
    observations: list[dict[str, Any]],
) -> ToolObservationLedger:
    ledger = ToolObservationLedger(
        ledger_id=f"tool-observation-ledger:{task_run_id}",
        task_run_id=task_run_id,
    )
    for item in observations:
        ledger = ledger.append(
            build_tool_observation_record(
                observation_ref=str(item.get("observation_ref") or ""),
                tool_name=str(item.get("tool_name") or ""),
                tool_args=dict(item.get("tool_args") or {}),
                result=item,
            )
        )
    return ledger
