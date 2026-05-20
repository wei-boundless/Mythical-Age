from __future__ import annotations

from typing import Any

from .models import IntentDecision, IntentFrame


def build_runtime_assembly_hint(
    *,
    intent_frame: IntentFrame,
    intent_decision: IntentDecision,
) -> dict[str, Any]:
    """Expose orchestration intent while keeping assembly inside orchestration."""

    return {
        "authority": "orchestration.intent_runtime_assembly_hint",
        "execution_strategy": intent_decision.execution_strategy,
        "target_domain_hint": intent_decision.target_domain_hint,
        "runtime_mode": _runtime_mode(intent_decision.execution_strategy),
        "interaction_mode": _interaction_mode(intent_decision.execution_strategy),
        "strategy_candidates": list(intent_frame.execution_strategy_candidates),
        "task_complexity": intent_frame.task_complexity,
        "graph_coordination_allowed": intent_decision.execution_strategy == "graph_coordination_run",
        "reason": intent_decision.reason,
    }


def _runtime_mode(strategy: str) -> str:
    if strategy == "professional_task_run":
        return "professional_task"
    if strategy == "specialist_handoff":
        return "specialist_handoff"
    if strategy == "graph_coordination_run":
        return "graph_coordination"
    if strategy == "retrieval_augmented_answer":
        return "retrieval_augmented_answer"
    return "interactive_single_agent"


def _interaction_mode(strategy: str) -> str:
    if strategy == "professional_task_run":
        return "professional_mode"
    return ""
