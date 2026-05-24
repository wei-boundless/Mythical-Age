from __future__ import annotations

from task_system.tasks.run_models import (
    advance_task_run_ledger,
    build_task_run_ledger,
    complete_task_run_step,
    current_task_step_run,
    project_task_result_from_ledger,
    start_task_run_step,
)
from task_system.planning.execution_recipe_models import ExecutionRecipe
from task_system.tasks.spec_models import TaskSpec
from task_system.tasks.step_models import TaskStepBlueprint
from runtime.unit_runtime.loop import _finalize_runtime_task_run_ledger


def _recipe(*steps: TaskStepBlueprint) -> ExecutionRecipe:
    return ExecutionRecipe(
        recipe_id="recipe.test.state_machine",
        title="State Machine Test",
        description="",
        execution_kind="single_agent",
        task_mode="test",
        source_kind="runtime",
        input_schema={"message": "string"},
        output_schema={"final_answer": "string"},
        required_operations=("op.model_response",),
        step_blueprints=tuple(steps),
    )


def _task_spec() -> TaskSpec:
    return TaskSpec(
        task_id="task-state-machine",
        task_spec_ref="taskspec:test",
        recipe_id="recipe.test.state_machine",
        session_id="session-test",
        user_goal="test",
        requested_outputs=("final_answer",),
    )


def test_task_result_is_projected_from_runtime_ledger() -> None:
    recipe = _recipe(
        TaskStepBlueprint(
            step_id="step.read",
            title="Read",
            step_kind="read",
            executor_type="tool",
            required_operations=("op.read_file",),
        ),
        TaskStepBlueprint(
            step_id="step.finalize",
            title="Finalize",
            step_kind="finalize",
            executor_type="model",
            required_operations=("op.model_response",),
        ),
    )
    ledger = build_task_run_ledger(
        task_run_id="taskrun:test",
        task_contract_ref="task:test",
        task_spec=_task_spec(),
        selected_recipe=recipe,
        status="running",
    )
    ledger = start_task_run_step(ledger, step_id="step.read", started_at=1.0)
    ledger = advance_task_run_ledger(
        _finalize_runtime_task_run_ledger(
            ledger=ledger,
            terminal_reason="completed",
            final_content="done",
            output_refs=("out:answer",),
        )[0]
    )
    result = project_task_result_from_ledger(
        ledger,
        result_id="taskresult:test",
        status="completed",
        terminal_reason="completed",
        result_refs=("obs:1",),
        output_refs=("out:answer",),
        final_outputs={"final_answer": "done"},
    )

    assert result.step_runs == ledger.step_runs
    assert result.task_spec_ref == ledger.task_spec_ref
    assert result.template_id == ledger.template_id


def test_terminal_finalize_skips_optional_verify_step() -> None:
    recipe = _recipe(
        TaskStepBlueprint(
            step_id="step.write",
            title="Write",
            step_kind="write",
            executor_type="tool",
            required_operations=("op.edit_file",),
        ),
        TaskStepBlueprint(
            step_id="step.verify",
            title="Verify",
            step_kind="verify",
            executor_type="mcp",
            optional_operations=("op.shell",),
            stop_policy="allow_unverified_completion",
        ),
        TaskStepBlueprint(
            step_id="step.finalize",
            title="Finalize",
            step_kind="finalize",
            executor_type="model",
            required_operations=("op.model_response",),
        ),
    )
    ledger = build_task_run_ledger(
        task_run_id="taskrun:test-verify",
        task_contract_ref="task:test-verify",
        task_spec=_task_spec(),
        selected_recipe=recipe,
        status="running",
    )
    ledger = start_task_run_step(ledger, step_id="step.write", started_at=1.0)
    ledger = complete_task_run_step(ledger, step_id="step.write", completed_at=2.0, output_refs=("obs:write",))
    ledger = advance_task_run_ledger(ledger, started_at=3.0)

    finalized, transitions = _finalize_runtime_task_run_ledger(
        ledger=ledger,
        terminal_reason="completed",
        final_content="done",
        output_refs=("out:answer",),
    )

    assert finalized is not None
    assert finalized.status == "completed"
    assert finalized.current_step_id == ""
    assert [item["event_type"] for item in transitions] == [
        "step_skipped",
        "step_entered",
        "step_completed",
    ]
    statuses = {step.step_id: step.status for step in finalized.step_runs}
    assert statuses["step.verify"] == "skipped"
    assert statuses["step.finalize"] == "completed"


def test_failure_marks_running_step_failed() -> None:
    recipe = _recipe(
        TaskStepBlueprint(
            step_id="step.answer",
            title="Answer",
            step_kind="finalize",
            executor_type="model",
            required_operations=("op.model_response",),
        )
    )
    ledger = build_task_run_ledger(
        task_run_id="taskrun:test-fail",
        task_contract_ref="task:test-fail",
        task_spec=_task_spec(),
        selected_recipe=recipe,
        status="running",
    )
    ledger = start_task_run_step(ledger, started_at=1.0)

    finalized, transitions = _finalize_runtime_task_run_ledger(
        ledger=ledger,
        terminal_reason="executor_failed",
        final_content="",
        output_refs=(),
    )

    assert finalized is not None
    assert finalized.status == "failed"
    assert current_task_step_run(finalized).status == "failed"
    assert transitions and transitions[0]["event_type"] == "step_failed"
