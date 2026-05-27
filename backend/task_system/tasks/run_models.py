from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Literal

from task_system.planning.execution_recipe_models import ExecutionRecipe
from task_system.tasks.spec_models import TaskSpec


TaskStepRunStatus = Literal["pending", "running", "completed", "failed", "skipped"]
TaskRunLedgerStatus = Literal["created", "running", "completed", "partially_completed", "blocked", "failed", "aborted"]


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
    retry_policy: dict[str, Any] = field(default_factory=dict)
    observation_refs: tuple[str, ...] = ()
    output_refs: tuple[str, ...] = ()
    entered_at: float = 0.0
    completed_at: float = 0.0
    attempt_count: int = 0
    failure_reason: str = ""
    step_result_ref: str = ""
    executor_ref: str = ""
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
    completion: dict[str, Any] = field(default_factory=dict)
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
        payload["completion"] = dict(self.completion or {})
        return payload


def build_task_run_ledger(
    *,
    task_run_id: str,
    task_contract_ref: str,
    task_spec: TaskSpec,
    selected_recipe: ExecutionRecipe,
    status: TaskRunLedgerStatus = "running",
    current_step_id: str = "",
    step_runs: tuple[TaskStepRun, ...] | None = None,
    diagnostics: dict[str, Any] | None = None,
) -> TaskRunLedger:
    initial_step_runs = step_runs or tuple(_step_run_from_blueprint(step) for step in selected_recipe.step_blueprints)
    return TaskRunLedger(
        ledger_id=f"taskrun-ledger:{task_run_id}",
        task_run_id=task_run_id,
        task_id=task_spec.task_id,
        task_spec_ref=task_spec.task_spec_ref,
        template_id=selected_recipe.recipe_id,
        status=status,
        current_step_id=current_step_id or (initial_step_runs[0].step_id if initial_step_runs else ""),
        requested_outputs=tuple(task_spec.requested_outputs),
        step_runs=initial_step_runs,
        refs={
            "task_contract_ref": task_contract_ref,
            "recipe_id": selected_recipe.recipe_id,
        },
        diagnostics=dict(diagnostics or {}),
    )


def start_task_run_step(
    ledger: TaskRunLedger,
    *,
    step_id: str | None = None,
    started_at: float | None = None,
    executor_ref: str = "",
    diagnostics: dict[str, Any] | None = None,
) -> TaskRunLedger:
    target_index = _resolve_step_index(ledger, step_id=step_id)
    if target_index < 0:
        return ledger
    current = ledger.step_runs[target_index]
    if current.status == "running":
        return ledger
    if current.status not in {"pending", "skipped"}:
        return ledger
    ts = _ts(started_at)
    updated_step = replace(
        current,
        status="running",
        entered_at=ts,
        attempt_count=max(1, int(current.attempt_count or 0) + 1),
        executor_ref=executor_ref or current.executor_ref,
        diagnostics=_merged_dict(current.diagnostics, diagnostics),
        failure_reason="",
    )
    return _replace_step_run(
        ledger,
        target_index,
        updated_step,
        current_step_id=updated_step.step_id,
        diagnostics={"current_step_id": updated_step.step_id},
    )


def complete_task_run_step(
    ledger: TaskRunLedger,
    *,
    step_id: str | None = None,
    completed_at: float | None = None,
    observation_refs: tuple[str, ...] = (),
    output_refs: tuple[str, ...] = (),
    step_result_ref: str = "",
    executor_ref: str = "",
    diagnostics: dict[str, Any] | None = None,
) -> TaskRunLedger:
    target_index = _resolve_step_index(ledger, step_id=step_id)
    if target_index < 0:
        return ledger
    current = ledger.step_runs[target_index]
    if current.status == "completed":
        return ledger
    ts = _ts(completed_at)
    updated_step = replace(
        current,
        status="completed",
        completed_at=ts,
        observation_refs=_dedupe_tuple((*current.observation_refs, *observation_refs)),
        output_refs=_dedupe_tuple((*current.output_refs, *output_refs)),
        step_result_ref=step_result_ref or current.step_result_ref,
        executor_ref=executor_ref or current.executor_ref,
        diagnostics=_merged_dict(current.diagnostics, diagnostics),
        failure_reason="",
    )
    updated_ledger = _replace_step_run(
        ledger,
        target_index,
        updated_step,
        current_step_id=_next_pending_step_id(ledger, start_index=target_index + 1),
    )
    if target_index + 1 >= len(updated_ledger.step_runs):
        return replace(updated_ledger, current_step_id="")
    return updated_ledger


def fail_task_run_step(
    ledger: TaskRunLedger,
    *,
    step_id: str | None = None,
    completed_at: float | None = None,
    failure_reason: str = "",
    observation_refs: tuple[str, ...] = (),
    output_refs: tuple[str, ...] = (),
    step_result_ref: str = "",
    executor_ref: str = "",
    diagnostics: dict[str, Any] | None = None,
) -> TaskRunLedger:
    target_index = _resolve_step_index(ledger, step_id=step_id)
    if target_index < 0:
        return ledger
    current = ledger.step_runs[target_index]
    if current.status == "failed":
        return ledger
    ts = _ts(completed_at)
    updated_step = replace(
        current,
        status="failed",
        completed_at=ts,
        observation_refs=_dedupe_tuple((*current.observation_refs, *observation_refs)),
        output_refs=_dedupe_tuple((*current.output_refs, *output_refs)),
        step_result_ref=step_result_ref or current.step_result_ref,
        executor_ref=executor_ref or current.executor_ref,
        diagnostics=_merged_dict(current.diagnostics, diagnostics),
        failure_reason=str(failure_reason or current.failure_reason or "step_failed"),
    )
    return _replace_step_run(
        ledger,
        target_index,
        updated_step,
        current_step_id=updated_step.step_id,
    )


def skip_task_run_step(
    ledger: TaskRunLedger,
    *,
    step_id: str | None = None,
    completed_at: float | None = None,
    diagnostics: dict[str, Any] | None = None,
) -> TaskRunLedger:
    target_index = _resolve_step_index(ledger, step_id=step_id)
    if target_index < 0:
        return ledger
    current = ledger.step_runs[target_index]
    if current.status == "skipped":
        return ledger
    ts = _ts(completed_at)
    updated_step = replace(
        current,
        status="skipped",
        completed_at=ts,
        diagnostics=_merged_dict(current.diagnostics, diagnostics),
    )
    updated_ledger = _replace_step_run(
        ledger,
        target_index,
        updated_step,
        current_step_id=_next_pending_step_id(ledger, start_index=target_index + 1),
    )
    if target_index + 1 >= len(updated_ledger.step_runs):
        return replace(updated_ledger, current_step_id="")
    return updated_ledger


def append_task_run_step(
    ledger: TaskRunLedger,
    step_run: TaskStepRun,
    *,
    make_current: bool = False,
    before_step_id: str = "",
    diagnostics: dict[str, Any] | None = None,
) -> TaskRunLedger:
    """Append a runtime-discovered step without introducing a separate long-run ledger."""

    step_id = str(step_run.step_id or "").strip()
    if not step_id:
        return ledger
    existing_ids = {str(item.step_id or "").strip() for item in ledger.step_runs}
    if step_id in existing_ids:
        return update_task_run_step_diagnostics(
            ledger,
            step_id=step_id,
            diagnostics=_merged_dict(step_run.diagnostics, diagnostics),
        )
    step_runs = tuple(ledger.step_runs)
    insert_at = len(step_runs)
    target_before = str(before_step_id or "").strip()
    if target_before:
        for index, item in enumerate(step_runs):
            if item.step_id == target_before:
                insert_at = index
                break
    return replace(
        ledger,
        step_runs=tuple((*step_runs[:insert_at], step_run, *step_runs[insert_at:])),
        current_step_id=step_id if make_current else ledger.current_step_id,
        diagnostics=_merged_dict(ledger.diagnostics, diagnostics),
    )


def append_plan_item_step(
    ledger: TaskRunLedger,
    *,
    plan_item: dict[str, Any],
    make_current: bool = False,
    before_step_id: str = "",
    diagnostics: dict[str, Any] | None = None,
) -> TaskRunLedger:
    plan = dict(plan_item or {})
    plan_item_id = str(plan.get("plan_item_id") or plan.get("step_id") or "").strip()
    if not plan_item_id:
        return ledger
    required_operations = tuple(
        str(item).strip()
        for item in list(plan.get("required_operations") or [])
        if str(item).strip()
    )
    optional_operations = tuple(
        str(item).strip()
        for item in list(plan.get("optional_operations") or [])
        if str(item).strip()
    )
    step_run = TaskStepRun(
        step_id=plan_item_id,
        title=str(plan.get("title") or plan_item_id),
        step_kind=str(plan.get("step_kind") or "plan_item"),
        executor_type=str(plan.get("executor_type") or plan.get("action_kind") or "main_agent"),
        required_operations=required_operations,
        optional_operations=optional_operations,
        input_refs=tuple(str(item).strip() for item in list(plan.get("input_refs") or []) if str(item).strip()),
        output_contract_id=str(plan.get("output_contract_id") or ""),
        stop_policy=str(plan.get("stop_policy") or "on_success"),
        retry_policy=dict(plan.get("retry_policy") or {}),
        diagnostics={"plan_item": plan},
    )
    return append_task_run_step(
        ledger,
        step_run,
        make_current=make_current,
        before_step_id=before_step_id,
        diagnostics=diagnostics,
    )


def update_task_run_step_diagnostics(
    ledger: TaskRunLedger,
    *,
    step_id: str,
    diagnostics: dict[str, Any] | None = None,
) -> TaskRunLedger:
    target_index = _resolve_step_index(ledger, step_id=step_id)
    if target_index < 0:
        return ledger
    current = ledger.step_runs[target_index]
    updated_step = replace(
        current,
        diagnostics=_merged_dict(current.diagnostics, diagnostics),
    )
    return _replace_step_run(
        ledger,
        target_index,
        updated_step,
        current_step_id=ledger.current_step_id,
    )


def advance_task_run_ledger(
    ledger: TaskRunLedger,
    *,
    started_at: float | None = None,
    executor_ref: str = "",
    diagnostics: dict[str, Any] | None = None,
) -> TaskRunLedger:
    next_step_id = _next_pending_step_id(ledger)
    if not next_step_id:
        return replace(ledger, current_step_id="")
    return start_task_run_step(
        ledger,
        step_id=next_step_id,
        started_at=started_at,
        executor_ref=executor_ref,
        diagnostics=diagnostics,
    )


def terminalize_task_run_ledger(
    ledger: TaskRunLedger,
    *,
    status: TaskRunLedgerStatus,
    current_step_id: str | None = None,
    diagnostics: dict[str, Any] | None = None,
) -> TaskRunLedger:
    next_current_step_id = ledger.current_step_id if current_step_id is None else current_step_id
    return replace(
        ledger,
        status=status,
        current_step_id=next_current_step_id,
        diagnostics=_merged_dict(ledger.diagnostics, diagnostics),
    )


def project_task_result_from_ledger(
    ledger: TaskRunLedger,
    *,
    result_id: str,
    status: str,
    terminal_reason: str,
    result_refs: tuple[str, ...] = (),
    output_refs: tuple[str, ...] = (),
    final_outputs: dict[str, Any] | None = None,
    completion: dict[str, Any] | None = None,
    refs: dict[str, Any] | None = None,
    diagnostics: dict[str, Any] | None = None,
) -> TaskResult:
    return TaskResult(
        result_id=result_id,
        task_run_id=ledger.task_run_id,
        task_id=ledger.task_id,
        task_spec_ref=ledger.task_spec_ref,
        template_id=ledger.template_id,
        status=status,
        terminal_reason=terminal_reason,
        requested_outputs=tuple(ledger.requested_outputs),
        result_refs=_dedupe_tuple(result_refs),
        output_refs=_dedupe_tuple(output_refs),
        step_runs=tuple(ledger.step_runs),
        final_outputs=dict(final_outputs or {}),
        completion=dict(completion or {}),
        refs={
            "task_spec_ref": ledger.task_spec_ref,
            "template_id": ledger.template_id,
            **dict(refs or {}),
        },
        diagnostics={
            "ledger_id": ledger.ledger_id,
            **dict(diagnostics or {}),
        },
    )


def current_task_step_run(ledger: TaskRunLedger | None) -> TaskStepRun | None:
    if ledger is None:
        return None
    step_id = str(ledger.current_step_id or "").strip()
    if not step_id:
        return next((item for item in ledger.step_runs if item.status == "running"), None)
    return next((item for item in ledger.step_runs if item.step_id == step_id), None)


def find_task_step_run(ledger: TaskRunLedger | None, step_id: str) -> TaskStepRun | None:
    if ledger is None:
        return None
    target = str(step_id or "").strip()
    if not target:
        return None
    return next((item for item in ledger.step_runs if item.step_id == target), None)


def task_run_step_count(ledger: TaskRunLedger | None) -> int:
    if ledger is None:
        return 0
    return sum(1 for item in ledger.step_runs if item.status in {"completed", "failed", "skipped"})


def task_run_terminal_status(terminal_reason: str) -> TaskRunLedgerStatus:
    reason = str(terminal_reason or "").strip()
    if reason == "completed":
        return "completed"
    if reason == "agent_plan_required":
        return "blocked"
    if reason in {
        "partially_completed",
        "partial_contract_failed",
        "tool_loop_budget_exceeded",
        "model_response_timeout_after_partial_output",
    }:
        return "partially_completed"
    return "failed"


def step_supports_operation(step_run: TaskStepRun | None, operation_id: str) -> bool:
    if step_run is None:
        return False
    target = str(operation_id or "").strip()
    if not target:
        return False
    return target in set(step_run.required_operations) or target in set(step_run.optional_operations)


def next_pending_step_run(ledger: TaskRunLedger | None, *, start_after_step_id: str = "") -> TaskStepRun | None:
    if ledger is None:
        return None
    start_index = 0
    if start_after_step_id:
        for index, item in enumerate(ledger.step_runs):
            if item.step_id == start_after_step_id:
                start_index = index + 1
                break
    for item in ledger.step_runs[start_index:]:
        if item.status == "pending":
            return item
    return None


def _step_run_from_blueprint(step: Any) -> TaskStepRun:
    return TaskStepRun(
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
        retry_policy=dict(step.retry_policy),
    )


def _replace_step_run(
    ledger: TaskRunLedger,
    target_index: int,
    updated_step: TaskStepRun,
    *,
    current_step_id: str,
    diagnostics: dict[str, Any] | None = None,
) -> TaskRunLedger:
    step_runs = list(ledger.step_runs)
    step_runs[target_index] = updated_step
    return replace(
        ledger,
        step_runs=tuple(step_runs),
        current_step_id=current_step_id,
        diagnostics=_merged_dict(ledger.diagnostics, diagnostics),
    )


def _resolve_step_index(ledger: TaskRunLedger, *, step_id: str | None = None) -> int:
    target = str(step_id or ledger.current_step_id or "").strip()
    if target:
        for index, step_run in enumerate(ledger.step_runs):
            if step_run.step_id == target:
                return index
    for index, step_run in enumerate(ledger.step_runs):
        if step_run.status == "running":
            return index
    return -1


def _next_pending_step_id(ledger: TaskRunLedger, *, start_index: int = 0) -> str:
    for step_run in ledger.step_runs[start_index:]:
        if step_run.status == "pending":
            return step_run.step_id
    return ""


def _merged_dict(base: dict[str, Any] | None, extra: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(base or {})
    payload.update(dict(extra or {}))
    return payload


def _dedupe_tuple(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return tuple(result)


def _ts(value: float | None) -> float:
    return float(value if value is not None else time.time())


