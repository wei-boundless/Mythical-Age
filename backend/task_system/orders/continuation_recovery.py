from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from .models import TaskOrder, TaskOrderRun


_CONTINUATION_MARKERS = (
    "继续",
    "接着",
    "恢复",
    "续上",
    "延续",
    "刚才",
    "上次",
    "之前",
    "继续做",
    "继续推进",
    "continue",
    "resume",
    "go on",
    "keep going",
)

_NEW_OBJECTIVE_MARKERS = (
    "新任务",
    "另一个",
    "换成",
    "从头",
    "重新开始",
    "restart",
    "start over",
)

_EXECUTABLE_RUN_STATUSES = {"created"}
_TERMINAL_RUN_STATUSES = {"completed", "failed", "cancelled"}


@dataclass(frozen=True, slots=True)
class TaskContinuationCandidate:
    candidate_id: str
    order_id: str
    order_run_id: str
    task_id: str
    order_kind: str
    objective: str
    run_status: str
    order_status: str
    score: float
    compatible: bool
    reason: str
    created_at: float = 0.0
    updated_at: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_system.task_order_continuation_candidate"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TaskContinuationRecoveryDecision:
    decision_kind: str = "none"
    reason: str = ""
    selected_order_id: str = ""
    selected_order_run_id: str = ""
    confidence: float = 0.0
    candidates: tuple[TaskContinuationCandidate, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_system.task_order_continuation_recovery"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["candidates"] = [item.to_dict() for item in self.candidates]
        return payload


def recover_task_order_continuation(
    *,
    message: str,
    session_orders: list[TaskOrder],
    session_runs: list[TaskOrderRun],
) -> TaskContinuationRecoveryDecision:
    text = str(message or "").strip()
    if not _looks_like_continuation(text):
        return TaskContinuationRecoveryDecision(
            decision_kind="none",
            reason="message_does_not_request_task_continuation",
            diagnostics={"continuation_intent": False},
        )

    order_by_id = {order.order_id: order for order in session_orders}
    candidates = tuple(
        _build_candidates(
            message=text,
            order_by_id=order_by_id,
            session_runs=session_runs,
        )
    )
    executable = [candidate for candidate in candidates if candidate.compatible]
    diagnostics = {
        "continuation_intent": True,
        "candidate_count": len(candidates),
        "executable_candidate_count": len(executable),
        "new_objective_marker": _looks_like_new_objective(text),
    }

    if len(executable) == 1:
        selected = executable[0]
        return TaskContinuationRecoveryDecision(
            decision_kind="selected",
            reason="single_executable_same_session_task_order_run",
            selected_order_id=selected.order_id,
            selected_order_run_id=selected.order_run_id,
            confidence=min(max(selected.score / 100.0, 0.5), 0.96),
            candidates=candidates,
            diagnostics=diagnostics,
        )
    if len(executable) > 1:
        return TaskContinuationRecoveryDecision(
            decision_kind="clarify",
            reason="multiple_executable_task_order_runs_match_continuation",
            candidates=candidates,
            diagnostics=diagnostics,
        )
    if _continuation_only(text):
        return TaskContinuationRecoveryDecision(
            decision_kind="clarify",
            reason="continuation_requested_but_no_executable_task_order_run_found",
            candidates=candidates,
            diagnostics=diagnostics,
        )
    return TaskContinuationRecoveryDecision(
        decision_kind="none",
        reason="continuation_wording_with_new_or_specific_objective",
        candidates=candidates,
        diagnostics=diagnostics,
    )


def _build_candidates(
    *,
    message: str,
    order_by_id: dict[str, TaskOrder],
    session_runs: list[TaskOrderRun],
) -> list[TaskContinuationCandidate]:
    candidates: list[TaskContinuationCandidate] = []
    ordered_runs = sorted(
        session_runs,
        key=lambda run: float(run.updated_at or run.created_at or 0.0),
        reverse=True,
    )
    for index, run in enumerate(ordered_runs[:8]):
        order = order_by_id.get(run.order_id)
        if order is None:
            continue
        run_status = str(run.status or "").strip()
        order_status = str(order.status or "").strip()
        executable = run_status in _EXECUTABLE_RUN_STATUSES and not str(run.task_run_id or "").strip()
        score = 70.0 - (index * 6.0)
        if executable:
            score += 18.0
        elif run_status in _TERMINAL_RUN_STATUSES:
            score -= 40.0
        else:
            score -= 24.0
        marker_hits = _objective_marker_hits(message, str(order.objective or ""))
        score += marker_hits * 4.0
        compatible = executable and score >= 60.0
        reason = "executable_created_run" if executable else f"run_status_not_executable:{run_status or 'unknown'}"
        candidates.append(
            TaskContinuationCandidate(
                candidate_id=f"task-continuation:{run.run_id}",
                order_id=order.order_id,
                order_run_id=run.run_id,
                task_id=str(order.task_id or ""),
                order_kind=str(order.order_kind or ""),
                objective=str(order.objective or ""),
                run_status=run_status,
                order_status=order_status,
                score=score,
                compatible=compatible,
                reason=reason,
                created_at=float(run.created_at or order.created_at or 0.0),
                updated_at=float(run.updated_at or run.created_at or order.updated_at or order.created_at or 0.0),
                metadata={
                    "order_source": str(order.source or ""),
                    "order_source_ref": str(order.source_ref or ""),
                    "task_definition_ref": str(order.task_definition_ref or ""),
                    "task_run_id": str(run.task_run_id or ""),
                },
            )
        )
    return candidates


def _looks_like_continuation(message: str) -> bool:
    lowered = str(message or "").lower()
    return any(marker in lowered for marker in _CONTINUATION_MARKERS)


def _looks_like_new_objective(message: str) -> bool:
    lowered = str(message or "").lower()
    return any(marker in lowered for marker in _NEW_OBJECTIVE_MARKERS)


def _continuation_only(message: str) -> bool:
    text = re.sub(r"[\s，。,.!！?？；;:：]+", "", str(message or "").strip().lower())
    if not text:
        return False
    compact_markers = [re.sub(r"\s+", "", marker.lower()) for marker in _CONTINUATION_MARKERS]
    if text in set(compact_markers):
        return True
    return len(text) <= 12 and any(marker in text for marker in compact_markers)


def _objective_marker_hits(message: str, objective: str) -> int:
    text = str(message or "").lower()
    objective_text = str(objective or "").lower()
    words = [
        item
        for item in re.split(r"[\s，。,.!！?？；;:：/\\]+", objective_text)
        if len(item) >= 2
    ]
    return sum(1 for word in words[:12] if word and word in text)
