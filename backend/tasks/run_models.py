from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from .spec_models import TaskSpec
from .template_models import TaskTemplate


TaskStepRunStatus = Literal["pending", "running", "completed", "failed", "skipped"]
TaskRunLedgerStatus = Literal["created", "running", "completed", "failed", "aborted"]


@dataclass(frozen=True, slots=True)
class TaskStepRun:
    step_id: str
    title: str
    step_kind: str
    executor_type: str
    status: TaskStepRunStatus = "pending"
    required_operations: tuple[str, ...] = ()
    optional_operations: tuple[str, ...] = ()
    input_refs: tuple[str, ...] = ()
    output_contract_id: str = ""
    stop_policy: str = "on_success"
    observation_refs: tuple[str, ...] = ()
    output_refs: tuple[str, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_system.task_step_run"

    def __post_init__(self) -> None:
        if self.authority != "task_system.task_step_run":
            raise ValueError("TaskStepRun authority must be task_system.task_step_run")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["required_operations"] = list(self.required_operations)
        payload["optional_operations"] = list(self.optional_operations)
        payload["input_refs"] = list(self.input_refs)
        payload["observation_refs"] = list(self.observation_refs)
        payload["output_refs"] = list(self.output_refs)
        return payload


@dataclass(frozen=True, slots=True)
class TaskRunLedger:
    ledger_id: str
    task_run_id: str
    task_id: str
    task_spec_ref: str
    template_id: str
    status: TaskRunLedgerStatus = "created"
    current_step_id: str = ""
    requested_outputs: tuple[str, ...] = ()
    step_runs: tuple[TaskStepRun, ...] = ()
    refs: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_system.task_run_ledger"

    def __post_init__(self) -> None:
        if self.authority != "task_system.task_run_ledger":
            raise ValueError("TaskRunLedger authority must be task_system.task_run_ledger")
        if not self.ledger_id:
            raise ValueError("TaskRunLedger requires ledger_id")
        if not self.task_run_id:
            raise ValueError("TaskRunLedger requires task_run_id")
        if not self.task_spec_ref:
            raise ValueError("TaskRunLedger requires task_spec_ref")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["requested_outputs"] = list(self.requested_outputs)
        payload["step_runs"] = [item.to_dict() for item in self.step_runs]
        return payload


@dataclass(frozen=True, slots=True)
class TaskResult:
    result_id: str
    task_run_id: str
    task_id: str
    task_spec_ref: str
    template_id: str
    status: str
    terminal_reason: str = ""
    requested_outputs: tuple[str, ...] = ()
    result_refs: tuple[str, ...] = ()
    output_refs: tuple[str, ...] = ()
    step_runs: tuple[TaskStepRun, ...] = ()
    final_outputs: dict[str, Any] = field(default_factory=dict)
    refs: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_system.task_result"

    def __post_init__(self) -> None:
        if self.authority != "task_system.task_result":
            raise ValueError("TaskResult authority must be task_system.task_result")
        if not self.result_id:
            raise ValueError("TaskResult requires result_id")
        if not self.task_run_id:
            raise ValueError("TaskResult requires task_run_id")
        if not self.task_spec_ref:
            raise ValueError("TaskResult requires task_spec_ref")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["requested_outputs"] = list(self.requested_outputs)
        payload["result_refs"] = list(self.result_refs)
        payload["output_refs"] = list(self.output_refs)
        payload["step_runs"] = [item.to_dict() for item in self.step_runs]
        return payload


def build_task_run_ledger(
    *,
    task_run_id: str,
    task_contract_ref: str,
    task_spec: TaskSpec,
    selected_template: TaskTemplate,
    status: TaskRunLedgerStatus = "running",
    current_step_id: str = "",
    step_runs: tuple[TaskStepRun, ...] | None = None,
    diagnostics: dict[str, Any] | None = None,
) -> TaskRunLedger:
    initial_step_runs = step_runs or tuple(
        TaskStepRun(
            step_id=step.step_id,
            title=step.title,
            step_kind=step.step_kind,
            executor_type=step.executor_type,
            status="pending",
            required_operations=tuple(step.required_operations),
            optional_operations=tuple(step.optional_operations),
            input_refs=tuple(step.input_refs),
            output_contract_id=step.output_contract_id,
            stop_policy=step.stop_policy,
            diagnostics=dict(step.retry_policy),
        )
        for step in selected_template.step_blueprints
    )
    return TaskRunLedger(
        ledger_id=f"taskrun-ledger:{task_run_id}",
        task_run_id=task_run_id,
        task_id=task_spec.task_id,
        task_spec_ref=task_spec.task_spec_ref,
        template_id=selected_template.template_id,
        status=status,
        current_step_id=current_step_id or (initial_step_runs[0].step_id if initial_step_runs else ""),
        requested_outputs=tuple(task_spec.requested_outputs),
        step_runs=initial_step_runs,
        refs={
            "task_contract_ref": task_contract_ref,
            "template_id": selected_template.template_id,
        },
        diagnostics=dict(diagnostics or {}),
    )

