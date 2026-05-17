from __future__ import annotations

from dataclasses import dataclass, field

from understanding.capability_resolution_view import capability_resolution_view
from .process_state import DialogueState
from .turn_understanding import TurnUnderstandingSnapshot


@dataclass(slots=True)
class ReconciliationDecision:
    action: str = "accept"
    conflict_type: str = ""
    slots_to_clear: list[str] = field(default_factory=list)
    facts_to_block: list[str] = field(default_factory=list)
    confidence_override: float | None = None
    preserve_previous_flow: bool = False
    preserve_previous_goal: bool = False
    restore_goal_hint: str = ""
    restore_flow_hint: str = ""
    needs_clarification: bool = False
    reason: str = ""
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ReconciledTurnUnderstanding:
    snapshot: TurnUnderstandingSnapshot
    decision: ReconciliationDecision


class UnderstandingReconciler:
    """Correction and conflict gate between turn understanding and process commit."""

    def review(
        self,
        snapshot: TurnUnderstandingSnapshot,
        previous_state: DialogueState,
    ) -> ReconciledTurnUnderstanding:
        decision = ReconciliationDecision()
        last_user_turn = next((turn for turn in reversed(snapshot.turn_trace) if turn.role == "user"), None)
        confidence = getattr(snapshot.active_understanding.understanding, "confidence", 0.0)

        if last_user_turn is not None and last_user_turn.turn_type == "correction_feedback":
            repair_flow = self._resolve_repair_flow(snapshot, previous_state)
            decision = ReconciliationDecision(
                action="repair_state",
                conflict_type="user_correction",
                slots_to_clear=self._slots_to_clear_for_flow(repair_flow),
                facts_to_block=["latest_assistant_result", "latest_assistant_decision"],
                preserve_previous_goal=True,
                restore_goal_hint=previous_state.active_goal,
                restore_flow_hint=repair_flow,
                reason="latest_user_turn_is_correction_feedback",
                notes=[
                    "User correction detected before process-state commit.",
                    "Latest assistant result/decision should not be promoted into working state.",
                ],
            )
        elif last_user_turn is not None and last_user_turn.turn_type == "task_switch":
            decision = ReconciliationDecision(
                action="accept",
                conflict_type="explicit_task_switch",
                reason="explicit_task_switch_detected",
                notes=["Explicit task switch detected; prior flow should only survive as warm context."],
            )
        elif self._is_low_confidence_flow_switch(snapshot, previous_state, confidence, last_user_turn):
            decision = ReconciliationDecision(
                action="accept_with_downgrade",
                conflict_type="low_confidence_flow_switch",
                confidence_override=max(0.45, min(confidence, 0.54)),
                preserve_previous_flow=True,
                restore_goal_hint=previous_state.active_goal,
                restore_flow_hint=previous_state.flow_state.flow_type,
                needs_clarification=confidence < 0.45,
                reason="low_confidence_understanding_on_existing_flow",
                notes=[
                    "Understanding confidence is low; keep the prior flow as a restore hint while preserving the current-turn goal.",
                    "Ask for clarification before committing a major flow switch if ambiguity persists.",
                ],
            )

        return ReconciledTurnUnderstanding(snapshot=snapshot, decision=decision)

    def _resolve_repair_flow(
        self,
        snapshot: TurnUnderstandingSnapshot,
        previous_state: DialogueState,
    ) -> str:
        previous_flow = previous_state.flow_state.flow_type
        if previous_flow and previous_flow != "general_problem_solving_flow":
            return previous_flow

        for turn in reversed(snapshot.turn_trace):
            if turn.role != "user":
                continue
            if turn.turn_type in {"goal_request", "followup_request", "task_switch"} and turn.flow_hint:
                return turn.flow_hint

        understanding = snapshot.active_understanding.understanding
        if understanding.modality == "pdf":
            return "pdf_document_flow"
        if understanding.modality == "table":
            return "structured_data_flow"
        if understanding.modality in {"realtime", "web"}:
            return "external_lookup_flow"
        if capability_resolution_view(understanding).route == "rag":
            return "knowledge_lookup_flow"
        return "general_problem_solving_flow"

    def _slots_to_clear_for_flow(self, flow_type: str) -> list[str]:
        if flow_type == "pdf_document_flow":
            return ["active_pdf", "active_entity"]
        if flow_type == "structured_data_flow":
            return ["active_dataset", "active_entity"]
        if flow_type in {"coding_change_flow", "architecture_design_flow", "knowledge_lookup_flow"}:
            return ["active_entity"]
        return []

    def _is_low_confidence_flow_switch(
        self,
        snapshot: TurnUnderstandingSnapshot,
        previous_state: DialogueState,
        confidence: float,
        last_user_turn,
    ) -> bool:
        if confidence >= 0.55:
            return False
        if not snapshot.active_goal.strip():
            return False
        if previous_state.flow_state.flow_type == "general_problem_solving_flow":
            return False
        if last_user_turn is None or last_user_turn.turn_type != "goal_request":
            return False
        proposed_flow_hint = str(last_user_turn.flow_hint or "").strip()
        if not proposed_flow_hint:
            return False
        return proposed_flow_hint != previous_state.flow_state.flow_type
