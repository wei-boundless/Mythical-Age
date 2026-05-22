from __future__ import annotations

from pathlib import Path

from runtime.shared.models import RuntimeLoopState
from runtime.unit_runtime.loop import TaskRunLoop
from task_system.planning.execution_recipe_models import ExecutionRecipe
from task_system.tasks.run_models import build_task_run_ledger, current_task_step_run, start_task_run_step
from task_system.tasks.spec_models import TaskSpec
from task_system.tasks.step_models import TaskStepBlueprint


def test_tool_result_step_transition_ignores_unmatched_current_step(tmp_path: Path) -> None:
    loop = TaskRunLoop(tmp_path)
    ledger = build_task_run_ledger(
        task_run_id="taskrun:test-unmatched-tool-result",
        task_contract_ref="task:test",
        task_spec=TaskSpec(
            task_id="task:test",
            task_spec_ref="taskspec:test",
            recipe_id="recipe:test",
            session_id="session:test",
            user_goal="test",
        ),
        selected_recipe=ExecutionRecipe(
            recipe_id="recipe:test",
            title="test",
            description="",
            execution_kind="single_agent",
            task_family="test",
            task_mode="test",
            step_blueprints=(
                TaskStepBlueprint(
                    step_id="step.answer",
                    title="Answer",
                    step_kind="finalize",
                    executor_type="model",
                    required_operations=("op.model_response",),
                ),
            ),
        ),
        status="running",
    )
    ledger = start_task_run_step(ledger, step_id="step.answer", started_at=1.0)
    state = RuntimeLoopState(
        task_run_id="taskrun:test-unmatched-tool-result",
        status="running",
        current_step_id="step.answer",
    )
    next_state, next_ledger, events = loop._apply_tool_result_step_transition(
        state=state,
        runtime_task_ledger=ledger,
        result_refs=["obs:tool"],
        operation_id="op.read_file",
        observation_ref="obs:tool",
        observation_payload={"tool_name": "read_file", "result": "ok"},
        reason="tool_result_received",
    )

    assert next_state is state
    assert next_ledger is ledger
    assert events == []
    assert current_task_step_run(next_ledger).status == "running"


def test_tool_result_step_transition_advances_matching_tool_step(tmp_path: Path) -> None:
    loop = TaskRunLoop(tmp_path)
    ledger = build_task_run_ledger(
        task_run_id="taskrun:test-matched-tool-result",
        task_contract_ref="task:test",
        task_spec=TaskSpec(
            task_id="task:test",
            task_spec_ref="taskspec:test",
            recipe_id="recipe:test",
            session_id="session:test",
            user_goal="test",
        ),
        selected_recipe=ExecutionRecipe(
            recipe_id="recipe:test",
            title="test",
            description="",
            execution_kind="single_agent",
            task_family="test",
            task_mode="test",
            step_blueprints=(
                TaskStepBlueprint(
                    step_id="step.read",
                    title="Read",
                    step_kind="read",
                    executor_type="tool",
                    required_operations=("op.read_file",),
                ),
            ),
        ),
        status="running",
    )
    ledger = start_task_run_step(ledger, step_id="step.read", started_at=1.0)
    state = RuntimeLoopState(
        task_run_id="taskrun:test-matched-tool-result",
        status="running",
        current_step_id="step.read",
    )
    next_state, next_ledger, events = loop._apply_tool_result_step_transition(
        state=state,
        runtime_task_ledger=ledger,
        result_refs=["obs:tool"],
        operation_id="op.read_file",
        observation_ref="obs:tool",
        observation_payload={"tool_name": "read_file", "result": "ok"},
        reason="tool_result_received",
    )

    assert next_ledger is not None
    assert next_ledger.step_runs[0].status == "completed"
    assert next_state.diagnostics["last_step_transition"] == "tool_result_received"
    assert [event.event_type for event in events] == [
        "step_completed",
        "task_run_ledger_updated",
        "checkpoint_written",
    ]
