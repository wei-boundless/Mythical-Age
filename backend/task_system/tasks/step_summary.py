from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any

from .run_models import TaskRunLedger, TaskStepRun


@dataclass(frozen=True, slots=True)
class StepExecutionSummary:
    summary_id: str
    task_run_id: str
    step_id: str
    attempt: int
    status: str
    action_summary: str
    inputs_used: tuple[str, ...] = ()
    operations_performed: tuple[str, ...] = ()
    files_read: tuple[str, ...] = ()
    files_written: tuple[str, ...] = ()
    commands_run: tuple[str, ...] = ()
    artifacts_touched: tuple[str, ...] = ()
    observations: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()
    verification: dict[str, Any] = field(default_factory=dict)
    failure: dict[str, Any] = field(default_factory=dict)
    next_step_recommendation: str = ""
    hidden_reasoning_included: bool = False
    created_at: float = 0.0
    authority: str = "task_run.step_execution_summary"

    def __post_init__(self) -> None:
        if self.authority != "task_run.step_execution_summary":
            raise ValueError("StepExecutionSummary authority must be task_run.step_execution_summary")
        if not self.summary_id:
            raise ValueError("StepExecutionSummary requires summary_id")
        if not self.task_run_id:
            raise ValueError("StepExecutionSummary requires task_run_id")
        if not self.step_id:
            raise ValueError("StepExecutionSummary requires step_id")
        if self.hidden_reasoning_included:
            raise ValueError("StepExecutionSummary must not include hidden reasoning")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in (
            "inputs_used",
            "operations_performed",
            "files_read",
            "files_written",
            "commands_run",
            "artifacts_touched",
            "observations",
            "outputs",
        ):
            payload[key] = list(payload.get(key) or [])
        payload["verification"] = dict(self.verification or {})
        payload["failure"] = dict(self.failure or {})
        return payload


def build_step_execution_summary(
    *,
    ledger: TaskRunLedger,
    step_run: TaskStepRun,
    reason: str,
    status: str,
    refs: dict[str, Any] | None = None,
    diagnostics: dict[str, Any] | None = None,
) -> StepExecutionSummary:
    ref_payload = dict(refs or {})
    diagnostic_payload = dict(diagnostics or {})
    operation_id = str(ref_payload.get("operation_id") or diagnostic_payload.get("operation_id") or "").strip()
    observations = _dedupe([*list(step_run.observation_refs), str(ref_payload.get("observation_ref") or "")])
    outputs = _dedupe([*list(step_run.output_refs), step_run.step_result_ref])
    verification = _verification_from_payloads(
        refs=ref_payload,
        diagnostics=diagnostic_payload,
        observations=observations,
    )
    failure = {}
    if status == "failed":
        failure = {
            "reason": str(step_run.failure_reason or reason or "step_failed"),
            "recoverable": bool(diagnostic_payload.get("recoverable") is True),
            "recovery_hint": str(diagnostic_payload.get("recovery_hint") or ""),
        }
    return StepExecutionSummary(
        summary_id=f"stepsummary:{ledger.task_run_id}:{step_run.step_id}:{max(1, int(step_run.attempt_count or 1))}",
        task_run_id=ledger.task_run_id,
        step_id=step_run.step_id,
        attempt=max(1, int(step_run.attempt_count or 1)),
        status=status,
        action_summary=_action_summary(step_run=step_run, status=status, reason=reason, operation_id=operation_id),
        inputs_used=tuple(step_run.input_refs),
        operations_performed=tuple(_dedupe([operation_id, *list(step_run.required_operations)])),
        observations=tuple(observations),
        outputs=tuple(outputs),
        verification=verification,
        failure=failure,
        next_step_recommendation=str(diagnostic_payload.get("next_step_recommendation") or ""),
        hidden_reasoning_included=False,
        created_at=time.time(),
    )


def _action_summary(*, step_run: TaskStepRun, status: str, reason: str, operation_id: str) -> str:
    title = str(step_run.title or step_run.step_id or "step").strip()
    op = operation_id or str(step_run.executor_ref or step_run.executor_type or "").strip()
    if status == "completed":
        return f"Completed step '{title}'" + (f" via {op}." if op else ".")
    if status == "failed":
        return f"Step '{title}' failed: {step_run.failure_reason or reason or 'step_failed'}."
    if status == "skipped":
        return f"Skipped step '{title}'."
    return f"Recorded step '{title}' with status {status}."


def _verification_from_payloads(
    *,
    refs: dict[str, Any],
    diagnostics: dict[str, Any],
    observations: list[str],
) -> dict[str, Any]:
    command_receipt = diagnostics.get("command_receipt")
    if not isinstance(command_receipt, dict):
        command_receipt = {}
    passed = command_receipt.get("passed")
    performed = bool(command_receipt or diagnostics.get("verification_intent") or refs.get("verification_ref"))
    return {
        "performed": performed,
        "passed": bool(passed is True) if performed else False,
        "evidence_refs": list(observations),
        "limitations": [str(item) for item in list(diagnostics.get("limitations") or []) if str(item).strip()],
    }


def _dedupe(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        item = str(raw or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result
