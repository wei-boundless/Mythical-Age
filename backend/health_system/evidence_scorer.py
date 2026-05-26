from __future__ import annotations

from typing import Any

from .evidence_models import EvidenceScore


def score_runtime_event(event: dict[str, Any], *, total_events: int = 0, index: int = 0) -> EvidenceScore:
    event_type = str(event.get("event_type") or "")
    payload = dict(event.get("payload") or {})
    base = _temporal_weight(index=index, total_events=total_events)

    if event_type == "loop_error":
        return EvidenceScore(
            causal_score=1.4,
            temporal_score=base,
            decision_score=0.5,
            recovery_score=0.9,
            reproduction_score=0.4,
            semantic_score=0.8,
            novelty_score=0.2,
        )
    if event_type == "loop_terminal":
        return EvidenceScore(
            causal_score=1.0,
            temporal_score=base,
            decision_score=0.5,
            recovery_score=0.7,
            reproduction_score=0.3,
            semantic_score=0.6,
            novelty_score=0.2,
        )
    if event_type == "operation_gate_checked":
        gate = dict(payload.get("gate") or {})
        return EvidenceScore(
            causal_score=0.9,
            temporal_score=base,
            decision_score=1.2,
            recovery_score=0.5,
            reproduction_score=0.4,
            semantic_score=0.5,
            novelty_score=0.1,
            negative_score=0.4 if gate.get("allowed") is False else 0.0,
        )
    if event_type == "commit_gate_checked":
        return EvidenceScore(
            causal_score=0.7,
            temporal_score=base,
            decision_score=1.0,
            recovery_score=0.8,
            reproduction_score=0.3,
            semantic_score=0.4,
            novelty_score=0.1,
        )
    if event_type == "checkpoint_written":
        return EvidenceScore(
            causal_score=0.6,
            temporal_score=base,
            decision_score=0.4,
            recovery_score=1.5,
            reproduction_score=0.6,
            semantic_score=0.4,
            novelty_score=0.3,
        )
    if event_type == "agent_delegation_requested":
        return EvidenceScore(
            causal_score=0.8,
            temporal_score=base,
            decision_score=1.1,
            recovery_score=0.6,
            reproduction_score=0.7,
            semantic_score=0.5,
            novelty_score=0.2,
        )
    if event_type == "agent_delegation_result_created":
        return EvidenceScore(
            causal_score=0.9,
            temporal_score=base,
            decision_score=0.7,
            recovery_score=0.6,
            reproduction_score=0.4,
            semantic_score=0.5,
            novelty_score=0.2,
        )
    if event_type == "tool_call_requested":
        tool_name = _tool_name(event)
        return EvidenceScore(
            causal_score=0.6,
            temporal_score=base,
            decision_score=0.9,
            recovery_score=0.4,
            reproduction_score=0.8,
            semantic_score=0.4,
            novelty_score=0.1,
            negative_score=0.5 if tool_name == "delegate_to_agent" else 0.0,
        )
    if event_type == "tool_result_received":
        return EvidenceScore(
            causal_score=0.8,
            temporal_score=base,
            decision_score=0.3,
            recovery_score=0.6,
            reproduction_score=0.5,
            semantic_score=0.4,
            novelty_score=0.1,
        )
    if event_type in {"task_run_ledger_updated", "step_completed", "step_entered", "step_failed", "step_skipped"}:
        return EvidenceScore(
            causal_score=0.5,
            temporal_score=base,
            decision_score=0.4,
            recovery_score=0.6,
            reproduction_score=0.3,
            semantic_score=0.3,
            novelty_score=0.1,
        )
    if event_type in {"coordination_flow_registered", "coordination_flow_finalized", "coordination_stage_updated"}:
        return EvidenceScore(
            causal_score=0.7,
            temporal_score=base,
            decision_score=0.9,
            recovery_score=0.7,
            reproduction_score=0.5,
            semantic_score=0.6,
            novelty_score=0.2,
        )
    if event_type in {"scheduler_evaluated", "coordination_merge_result_created", "handoff_envelope_created"}:
        return EvidenceScore(
            causal_score=0.8,
            temporal_score=base,
            decision_score=0.8,
            recovery_score=0.8,
            reproduction_score=0.5,
            semantic_score=0.5,
            novelty_score=0.2,
        )
    if event_type in {"task_contract_built", "context_snapshot_built", "memory_runtime_view_built"}:
        return EvidenceScore(
            causal_score=0.4,
            temporal_score=base,
            decision_score=0.5,
            recovery_score=0.4,
            reproduction_score=0.9,
            semantic_score=0.4,
            novelty_score=0.1,
        )
    return EvidenceScore(
        causal_score=0.2,
        temporal_score=base,
        decision_score=0.2,
        recovery_score=0.2,
        reproduction_score=0.2,
        semantic_score=0.2,
        novelty_score=0.1,
    )


def score_negative_observation(*, weight: float = 0.8) -> EvidenceScore:
    return EvidenceScore(
        causal_score=0.4,
        temporal_score=0.4,
        decision_score=0.3,
        recovery_score=0.4,
        reproduction_score=0.8,
        semantic_score=0.6,
        novelty_score=0.2,
        negative_score=weight,
    )


def _temporal_weight(*, index: int, total_events: int) -> float:
    if total_events <= 0:
        return 0.5
    ratio = max(1, min(index, total_events)) / float(total_events)
    return round(0.25 + ratio * 0.75, 4)


def _tool_name(event: dict[str, Any]) -> str:
    action_request = dict(event.get("payload") or {}).get("action_request") or {}
    action_payload = dict(action_request.get("payload") or {})
    return str(action_payload.get("tool_name") or "")
