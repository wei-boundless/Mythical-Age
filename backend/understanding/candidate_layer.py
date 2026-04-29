from __future__ import annotations

from typing import Any

from orchestration.candidates import CandidateEnvelope

from .memory_intent import analyze_memory_intent
from .query_understanding import analyze_query_understanding
from .task_understanding import analyze_task_understanding


def build_understanding_candidates(
    *,
    task_id: str,
    message: str,
) -> tuple[CandidateEnvelope, ...]:
    """Convert legacy understanding signals into non-authoritative candidates."""

    memory_intent = analyze_memory_intent(message)
    task_understanding = analyze_task_understanding(message, memory_intent)
    query_understanding = analyze_query_understanding(message, memory_intent)

    base_ref = {"understanding_authority": "candidate_only"}
    return (
        CandidateEnvelope(
            candidate_id=f"candidate:{task_id}:understanding:intent-frame",
            producer="understanding.candidate_layer",
            candidate_type="intent_frame_candidate",
            payload={
                "intent": query_understanding.intent,
                "source_kind": query_understanding.source_kind,
                "task_kind": query_understanding.task_kind,
                "modality": query_understanding.modality,
                "confidence": query_understanding.confidence,
            },
            confidence=_bounded_confidence(query_understanding.confidence),
            reasons=tuple(query_understanding.reasons),
            refs=base_ref,
        ),
        CandidateEnvelope(
            candidate_id=f"candidate:{task_id}:understanding:route",
            producer="understanding.candidate_layer",
            candidate_type="route_candidate",
            payload={
                "route": query_understanding.route,
                "execution_posture": query_understanding.execution_posture,
                "direct_route_reason": query_understanding.direct_route_reason,
                "should_skip_rag": query_understanding.should_skip_rag,
            },
            confidence=_bounded_confidence(query_understanding.confidence),
            reasons=("route is suggested by understanding only", *tuple(query_understanding.reasons)),
            refs=base_ref,
        ),
        CandidateEnvelope(
            candidate_id=f"candidate:{task_id}:understanding:task-family",
            producer="understanding.candidate_layer",
            candidate_type="task_family_candidate",
            payload={
                "intent": task_understanding.intent,
                "source_kind": task_understanding.source_kind,
                "task_kind": task_understanding.task_kind,
                "modality": task_understanding.modality,
                "preferred_skill": task_understanding.preferred_skill,
            },
            confidence=_bounded_confidence(task_understanding.confidence),
            reasons=tuple(task_understanding.reasons),
            refs=base_ref,
        ),
        CandidateEnvelope(
            candidate_id=f"candidate:{task_id}:understanding:capability-need",
            producer="understanding.candidate_layer",
            candidate_type="capability_need_candidate",
            payload={
                "capability_requests": list(query_understanding.capability_requests),
                "candidate_tools": list(query_understanding.candidate_tools),
                "tool_name_hint": query_understanding.tool_name,
                "skill_name_hint": query_understanding.skill_name,
            },
            confidence=_bounded_confidence(query_understanding.confidence),
            reasons=("capability need is not permission",),
            refs=base_ref,
        ),
        CandidateEnvelope(
            candidate_id=f"candidate:{task_id}:understanding:memory-intent",
            producer="understanding.candidate_layer",
            candidate_type="memory_intent_candidate",
            payload=_memory_intent_payload(memory_intent),
            confidence=0.9 if memory_intent.intent != "general" else 0.3,
            reasons=("memory intent is a candidate; MemorySystem decides policy later",),
            refs=base_ref,
        ),
    )


def _memory_intent_payload(memory_intent: Any) -> dict[str, Any]:
    return {
        "intent": str(getattr(memory_intent, "intent", "") or "general"),
        "memory_read_mode": str(getattr(memory_intent, "memory_read_mode", "") or "none"),
        "memory_write_mode": str(getattr(memory_intent, "memory_write_mode", "") or "none"),
        "should_skip_rag": bool(getattr(memory_intent, "should_skip_rag", False)),
        "explicit_read_inventory": bool(getattr(memory_intent, "explicit_read_inventory", False)),
        "explicit_write_request": bool(getattr(memory_intent, "explicit_write_request", False)),
        "explicit_forget_request": bool(getattr(memory_intent, "explicit_forget_request", False)),
        "ignore_memory": bool(getattr(memory_intent, "ignore_memory", False)),
        "preferred_types": list(getattr(memory_intent, "preferred_types", []) or []),
        "preferred_memory_classes": list(getattr(memory_intent, "preferred_memory_classes", []) or []),
    }


def _bounded_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.0
    if confidence < 0.0:
        return 0.0
    if confidence > 1.0:
        return 1.0
    return confidence
