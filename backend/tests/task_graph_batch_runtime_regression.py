from __future__ import annotations

from pathlib import Path

from runtime.unit_runtime.loop import TaskRunLoop
from runtime.execution.node_execution_request import NodeResultReadyEvent
from runtime.graph_runtime.batch_runtime import (
    bootstrap_batch_lifecycle_runtime_state,
    batch_execution_instance_for_result,
    node_has_more_batch_work,
    rewind_batch_lifecycle_for_stages,
    select_batch_for_stage,
    transition_batch_after_stage_result,
)
from runtime.graph_runtime.run_monitor import build_task_graph_run_monitor_view
from task_system.compiler.coordination_graph_compiler import compile_task_graph_definition_runtime_spec
from task_system.graphs.task_graph_models import TaskGraphDefinition, TaskGraphNodeDefinition


def _batch_graph() -> TaskGraphDefinition:
    return TaskGraphDefinition(
        graph_id="graph.test.batch_runtime",
        title="批次运行图",
        graph_kind="multi_agent",
        publish_state="published",
        entry_node_id="produce",
        output_node_id="produce",
        runtime_policy={"coordinator_agent_id": "agent:coordinator"},
        nodes=(
            TaskGraphNodeDefinition(
                node_id="produce",
                node_type="agent",
                title="批次生产",
                task_id="task.test.produce",
                agent_id="agent:producer",
                contract_bindings={
                    "unit_batch": {"unit_kind": "item", "requested_count": 5, "range_start": 1},
                    "runtime": {
                        "split_policy": {"mode": "static_batch", "batch_size": 2},
                        "batch_acceptance_policy": {"mode": "review_then_commit", "max_repair_rounds": 2},
                        "merge_policy": {"mode": "wait_all_committed"},
                    },
                },
            ),
        ),
    )


def _parallel_batch_graph() -> TaskGraphDefinition:
    return TaskGraphDefinition(
        graph_id="graph.test.parallel_batch_runtime",
        title="并行批次运行图",
        graph_kind="multi_agent",
        publish_state="published",
        entry_node_id="produce",
        output_node_id="produce",
        runtime_policy={"coordinator_agent_id": "agent:coordinator"},
        nodes=(
            TaskGraphNodeDefinition(
                node_id="produce",
                node_type="agent",
                title="并行批次生产",
                task_id="task.test.produce",
                agent_id="agent:producer",
                contract_bindings={
                    "unit_batch": {"unit_kind": "item", "requested_count": 6, "range_start": 1},
                    "runtime": {
                        "split_policy": {
                            "mode": "static_batch",
                            "batch_size": 2,
                            "child_execution_mode": "parallel",
                            "max_parallel_batches": 2,
                        },
                        "batch_acceptance_policy": {"mode": "review_then_commit", "max_repair_rounds": 1},
                        "merge_policy": {"mode": "wait_all_committed"},
                    },
                },
            ),
        ),
    )


def test_batch_runtime_state_transitions_batches_to_merge_ready() -> None:
    spec = compile_task_graph_definition_runtime_spec(graph=_batch_graph())
    state = bootstrap_batch_lifecycle_runtime_state(runtime_spec_payload=spec.to_dict())

    state, first = select_batch_for_stage(runtime_state=state, stage_id="produce", node_id="produce")
    assert first["batch_id"] == "item_1_2"
    assert state["running_batch_ids"] == ["item_1_2"]

    state = transition_batch_after_stage_result(
        runtime_state=state,
        stage_id="produce",
        node_id="produce",
        accepted=True,
        task_result_ref="taskresult:first",
    )
    assert "item_1_2" in state["committed_batch_ids"]
    assert "item_3_4" in state["ready_batch_ids"]

    state, second = select_batch_for_stage(runtime_state=state, stage_id="produce", node_id="produce")
    assert second["batch_id"] == "item_3_4"
    state = transition_batch_after_stage_result(runtime_state=state, stage_id="produce", node_id="produce", accepted=True)
    state, third = select_batch_for_stage(runtime_state=state, stage_id="produce", node_id="produce")
    assert third["batch_id"] == "item_5_5"
    state = transition_batch_after_stage_result(runtime_state=state, stage_id="produce", node_id="produce", accepted=True)

    assert state["summary"]["committed_batch_count"] == 3
    assert state["summary"]["merge_ready_count"] == 1
    assert state["merge_states"][0]["status"] == "ready"


def test_batch_runtime_state_repairs_same_batch_before_failing() -> None:
    spec = compile_task_graph_definition_runtime_spec(graph=_batch_graph())
    state = bootstrap_batch_lifecycle_runtime_state(runtime_spec_payload=spec.to_dict())
    state, first = select_batch_for_stage(runtime_state=state, stage_id="produce", node_id="produce")

    state = transition_batch_after_stage_result(
        runtime_state=state,
        stage_id="produce",
        node_id="produce",
        accepted=False,
        task_result_ref="taskresult:revise",
    )

    assert first["batch_id"] == "item_1_2"
    assert "item_1_2" in state["ready_batch_ids"]
    repaired = next(item for item in state["batch_states"] if item["batch_id"] == "item_1_2")
    assert repaired["status"] == "repair_ready"
    assert repaired["repair_round"] == 1

    state, retry = select_batch_for_stage(runtime_state=state, stage_id="produce", node_id="produce")
    assert retry["batch_id"] == "item_1_2"
    state = transition_batch_after_stage_result(
        runtime_state=state,
        stage_id="produce",
        node_id="produce",
        accepted=False,
        task_result_ref="taskresult:revise-again",
    )
    assert "item_1_2" in state["ready_batch_ids"]

    state, final_retry = select_batch_for_stage(runtime_state=state, stage_id="produce", node_id="produce")
    assert final_retry["batch_id"] == "item_1_2"
    state = transition_batch_after_stage_result(
        runtime_state=state,
        stage_id="produce",
        node_id="produce",
        accepted=False,
        task_result_ref="taskresult:failed",
    )
    assert "item_1_2" in state["failed_batch_ids"]
    assert node_has_more_batch_work(runtime_state=state, stage_id="produce", node_id="produce") is False
    failed = next(item for item in state["batch_states"] if item["batch_id"] == "item_1_2")
    assert failed["last_verdict"] == "repair_rounds_exhausted"


def test_task_graph_run_injects_batch_range_and_continues_until_batches_done(tmp_path: Path) -> None:
    graph = _batch_graph()
    spec = compile_task_graph_definition_runtime_spec(graph=graph)
    loop = TaskRunLoop(tmp_path, backend_dir=Path("backend"))
    started = loop.start_task_graph_run(session_id="session:test", graph=graph, runtime_spec=spec)

    assert started.coordination_run is not None
    first_request = started.loop_state.diagnostics["stage_execution_request"]
    assert first_request["stage_id"] == "produce"
    assert first_request["explicit_inputs"]["unit_batch_id"] == "item_1_2"
    assert first_request["explicit_inputs"]["batch_start_index"] == 1
    assert first_request["explicit_inputs"]["batch_end_index"] == 2

    first_resume = loop.langgraph_coordination_runtime.resume_from_task_result(
        coordination_run=started.coordination_run,
        event=NodeResultReadyEvent(
            event_type="task_result_ready",
            coordination_run_id=started.coordination_run.coordination_run_id,
            task_run_id=started.task_run.task_run_id,
            stage_id="produce",
            task_ref="task.test.produce",
            task_result_ref="taskresult:first",
            accepted=True,
            request_id=first_request["request_id"],
            dispatch_event_id=first_request["dispatch_context"]["dispatch_event_id"],
        ),
        inherited_inputs=dict(first_request["explicit_inputs"]),
    )

    assert first_resume.stage_execution_request is not None
    assert first_resume.stage_execution_request.stage_id == "produce"
    assert first_resume.stage_execution_request.explicit_inputs["unit_batch_id"] == "item_3_4"
    batch_state = first_resume.state["batch_lifecycle_runtime_state"]
    assert "item_1_2" in batch_state["committed_batch_ids"]
    assert "item_3_4" in batch_state["running_batch_ids"]

    monitor = build_task_graph_run_monitor_view(
        task_run=started.task_run.to_dict(),
        coordination_run=started.coordination_run.to_dict(),
        coordination_state=first_resume.state,
    )
    assert monitor["batch_lifecycle"]["available"] is True
    assert monitor["batch_lifecycle"]["summary"]["committed_batch_count"] == 1


def test_parallel_batch_runtime_bootstraps_multiple_ready_batches_and_execution_instance(tmp_path: Path) -> None:
    graph = _parallel_batch_graph()
    spec = compile_task_graph_definition_runtime_spec(graph=graph)
    state = bootstrap_batch_lifecycle_runtime_state(runtime_spec_payload=spec.to_dict())

    assert state["execution_mode_by_plan"]
    assert set(state["ready_batch_ids"]) == {"item_1_2", "item_3_4", "item_5_6"}

    loop = TaskRunLoop(tmp_path, backend_dir=Path("backend"))
    started = loop.start_task_graph_run(session_id="session:test", graph=graph, runtime_spec=spec)

    first_request = started.loop_state.diagnostics["stage_execution_request"]
    first_inputs = first_request["explicit_inputs"]
    assert first_inputs["unit_batch_id"] == "item_1_2"
    assert first_inputs["unit_batch_execution_id"].startswith("batchrun:")
    assert first_request["dispatch_context"]["batch_execution_id"] == first_inputs["unit_batch_execution_id"]

    batch_state = started.coordination_run and loop.langgraph_coordination_runtime.checkpoints.get_state(
        thread_id=started.coordination_run.coordination_run_id
    )
    assert batch_state is not None
    runtime_state = batch_state["batch_lifecycle_runtime_state"]
    assert runtime_state["summary"]["execution_instance_count"] == 1
    assert runtime_state["summary"]["running_execution_instance_count"] == 1
    assert runtime_state["batch_execution_instances"][0]["request_id"] == first_request["request_id"]

    monitor = build_task_graph_run_monitor_view(
        task_run=started.task_run.to_dict(),
        coordination_run=started.coordination_run.to_dict() if started.coordination_run is not None else {},
        coordination_state=batch_state,
    )
    assert monitor["batch_lifecycle"]["execution_instances"][0]["execution_id"] == first_inputs["unit_batch_execution_id"]
    assert monitor["batch_dispatcher"]["available"] is True
    dispatcher_node = monitor["batch_dispatcher"]["nodes"][0]
    assert dispatcher_node["node_id"] == "produce"
    assert dispatcher_node["max_parallel_batches"] == 2
    assert dispatcher_node["available_slot_count"] == 1
    assert dispatcher_node["dispatchable_batch_ids"] == ["item_3_4"]


def test_langgraph_runtime_dispatches_ready_parallel_batch_requests(tmp_path: Path) -> None:
    graph = _parallel_batch_graph()
    spec = compile_task_graph_definition_runtime_spec(graph=graph)
    loop = TaskRunLoop(tmp_path, backend_dir=Path("backend"))
    started = loop.start_task_graph_run(session_id="session:test", graph=graph, runtime_spec=spec)
    assert started.coordination_run is not None

    result = loop.langgraph_coordination_runtime.dispatch_ready_batch_requests(
        coordination_run=started.coordination_run,
        max_requests=2,
        include_current_request=True,
    )

    requests = result.diagnostics["stage_execution_requests"]
    assert len(requests) == 2
    assert [item["explicit_inputs"]["unit_batch_id"] for item in requests] == ["item_1_2", "item_3_4"]
    assert requests[0]["request_id"] != requests[1]["request_id"]
    assert requests[0]["explicit_inputs"]["unit_batch_execution_id"] != requests[1]["explicit_inputs"]["unit_batch_execution_id"]
    state = loop.langgraph_coordination_runtime.checkpoints.get_state(
        thread_id=started.coordination_run.coordination_run_id
    )
    assert state is not None
    runtime_state = state["batch_lifecycle_runtime_state"]
    assert set(runtime_state["running_batch_ids"]) == {"item_1_2", "item_3_4"}
    assert runtime_state["summary"]["active_execution_count"] == 2
    assert result.diagnostics["batch_dispatcher"]["summary"]["available_slot_count"] == 0


def test_parallel_batch_runtime_dispatches_multiple_active_batches_and_matches_results_by_request() -> None:
    spec = compile_task_graph_definition_runtime_spec(graph=_parallel_batch_graph())
    state = bootstrap_batch_lifecycle_runtime_state(runtime_spec_payload=spec.to_dict())

    state, first = select_batch_for_stage(runtime_state=state, stage_id="produce", node_id="produce")
    first_execution_id = first["active_execution_id"]
    state, second = select_batch_for_stage(runtime_state=state, stage_id="produce", node_id="produce")
    second_execution_id = second["active_execution_id"]
    state, third = select_batch_for_stage(runtime_state=state, stage_id="produce", node_id="produce")

    assert first["batch_id"] == "item_1_2"
    assert second["batch_id"] == "item_3_4"
    assert third == {}
    assert set(state["running_batch_ids"]) == {"item_1_2", "item_3_4"}
    assert state["summary"]["active_execution_count"] == 2

    from runtime.graph_runtime.batch_runtime import attach_batch_execution_request

    state = attach_batch_execution_request(
        runtime_state=state,
        batch_execution_id=first_execution_id,
        request_id="nodeexec:first",
        dispatch_event_id="tlevent:first",
        request_payload={"request_id": "nodeexec:first", "explicit_inputs": {"unit_batch_execution_id": first_execution_id}},
    )
    state = attach_batch_execution_request(
        runtime_state=state,
        batch_execution_id=second_execution_id,
        request_id="nodeexec:second",
        dispatch_event_id="tlevent:second",
        request_payload={"request_id": "nodeexec:second", "explicit_inputs": {"unit_batch_execution_id": second_execution_id}},
    )

    matched = batch_execution_instance_for_result(
        runtime_state=state,
        stage_id="produce",
        node_id="produce",
        request_id="nodeexec:second",
    )
    assert matched["execution_id"] == second_execution_id

    state = transition_batch_after_stage_result(
        runtime_state=state,
        stage_id="produce",
        node_id="produce",
        accepted=True,
        task_result_ref="taskresult:second",
        request_id="nodeexec:second",
    )

    assert "item_3_4" in state["committed_batch_ids"]
    assert "item_1_2" in state["running_batch_ids"]
    assert state["summary"]["active_execution_count"] == 1
    assert state["batch_execution_instances"][1]["status"] == "committed"


def test_batch_runtime_rejects_unknown_parallel_result_identity_without_touching_active_batch() -> None:
    spec = compile_task_graph_definition_runtime_spec(graph=_parallel_batch_graph())
    state = bootstrap_batch_lifecycle_runtime_state(runtime_spec_payload=spec.to_dict())
    state, first = select_batch_for_stage(runtime_state=state, stage_id="produce", node_id="produce")
    assert first["batch_id"] == "item_1_2"

    state = transition_batch_after_stage_result(
        runtime_state=state,
        stage_id="produce",
        node_id="produce",
        accepted=True,
        task_result_ref="taskresult:unknown",
        request_id="nodeexec:unknown",
    )

    assert "item_1_2" in state["running_batch_ids"]
    assert "item_1_2" not in state["committed_batch_ids"]
    assert state["diagnostics"]["last_transition_ignored"]["reason"] == "batch_execution_identity_not_found"


def test_batch_runtime_executor_failure_releases_batch_without_consuming_repair_round() -> None:
    spec = compile_task_graph_definition_runtime_spec(graph=_batch_graph())
    state = bootstrap_batch_lifecycle_runtime_state(runtime_spec_payload=spec.to_dict())
    state, first = select_batch_for_stage(runtime_state=state, stage_id="produce", node_id="produce")
    execution_id = first["active_execution_id"]

    state = transition_batch_after_stage_result(
        runtime_state=state,
        stage_id="produce",
        node_id="produce",
        accepted=False,
        task_result_ref="taskresult:provider-failed",
        batch_execution_id=execution_id,
        event_diagnostics={
            "unit_batch_execution_id": execution_id,
            "terminal_reason": "executor_failed",
            "last_error": {"code": "provider_error", "message": "Insufficient Balance"},
        },
    )

    assert "item_1_2" in state["ready_batch_ids"]
    assert state["running_batch_ids"] == []
    batch = next(item for item in state["batch_states"] if item["batch_id"] == "item_1_2")
    assert batch["repair_round"] == 0
    assert batch["last_verdict"] == "technical_retry"
    assert state["batch_execution_instances"][0]["status"] == "technical_failed"
    assert state["batch_execution_instances"][0]["verdict"] == "technical_retry"
    assert state["diagnostics"]["last_transition"]["technical_failure"] is True

    state, retry = select_batch_for_stage(runtime_state=state, stage_id="produce", node_id="produce")
    assert retry["batch_id"] == "item_1_2"
    assert retry["active_execution_id"] != execution_id


def test_batch_runtime_technical_failures_circuit_break_without_business_repair() -> None:
    spec = compile_task_graph_definition_runtime_spec(graph=_batch_graph())
    state = bootstrap_batch_lifecycle_runtime_state(runtime_spec_payload=spec.to_dict())
    selected_execution_ids: list[str] = []
    for index in range(3):
        state, selected = select_batch_for_stage(runtime_state=state, stage_id="produce", node_id="produce")
        execution_id = selected["active_execution_id"]
        selected_execution_ids.append(execution_id)
        state = transition_batch_after_stage_result(
            runtime_state=state,
            stage_id="produce",
            node_id="produce",
            accepted=False,
            task_result_ref=f"taskresult:provider-failed-{index}",
            batch_execution_id=execution_id,
            event_diagnostics={
                "unit_batch_execution_id": execution_id,
                "terminal_reason": "executor_failed",
                "last_error": {"code": "provider_error", "message": "Insufficient Balance"},
            },
        )

    batch = next(item for item in state["batch_states"] if item["batch_id"] == "item_1_2")
    assert batch["status"] == "technical_blocked"
    assert batch["repair_round"] == 0
    assert batch["last_verdict"] == "technical_blocked"
    assert state["ready_batch_ids"] == []
    assert state["running_batch_ids"] == []
    assert state["failed_batch_ids"] == []
    assert node_has_more_batch_work(runtime_state=state, stage_id="produce", node_id="produce") is False
    assert state["batch_execution_instances"][-1]["execution_id"] == selected_execution_ids[-1]
    assert state["batch_execution_instances"][-1]["status"] == "technical_blocked"
    assert state["batch_execution_instances"][-1]["verdict"] == "technical_blocked"
    assert state["diagnostics"]["last_transition"]["technical_failure_count"] == 3
    assert state["diagnostics"]["last_transition"]["technical_blocked"] is True


def test_batch_runtime_rewind_resets_failed_batches_to_dispatchable_work() -> None:
    spec = compile_task_graph_definition_runtime_spec(graph=_batch_graph())
    state = bootstrap_batch_lifecycle_runtime_state(runtime_spec_payload=spec.to_dict())
    for _ in range(3):
        state, selected = select_batch_for_stage(runtime_state=state, stage_id="produce", node_id="produce")
        assert selected["batch_id"] == "item_1_2"
        state = transition_batch_after_stage_result(
            runtime_state=state,
            stage_id="produce",
            node_id="produce",
            accepted=False,
            task_result_ref="taskresult:revise",
        )

    assert "item_1_2" in state["failed_batch_ids"]
    assert state["summary"]["failed_batch_count"] == 1
    assert state["batch_execution_instances"]

    rewound = rewind_batch_lifecycle_for_stages(
        runtime_state=state,
        invalidated_stage_ids=["produce"],
        target_stage_id="produce",
        target_node_id="produce",
        reason="retry_after_prompt_fix",
    )

    assert rewound["ready_batch_ids"] == ["item_1_2"]
    assert rewound["failed_batch_ids"] == []
    assert rewound["summary"]["failed_batch_count"] == 0
    assert rewound["batch_execution_instances"] == []
    first = next(item for item in rewound["batch_states"] if item["batch_id"] == "item_1_2")
    assert first["attempt_index"] == 0
    assert first["repair_round"] == 0
    assert first["last_result_ref"] == ""


def test_coordination_rewind_resets_failed_batch_and_creates_new_request(tmp_path: Path) -> None:
    graph = _batch_graph()
    spec = compile_task_graph_definition_runtime_spec(graph=graph)
    loop = TaskRunLoop(tmp_path, backend_dir=Path("backend"))
    started = loop.start_task_graph_run(session_id="session:test", graph=graph, runtime_spec=spec)
    assert started.coordination_run is not None
    coordination_run = started.coordination_run
    request = started.loop_state.diagnostics["stage_execution_request"]

    for index in range(3):
        result = loop.langgraph_coordination_runtime.resume_from_task_result(
            coordination_run=coordination_run,
            event=NodeResultReadyEvent(
                event_type="task_result_ready",
                coordination_run_id=coordination_run.coordination_run_id,
                task_run_id=started.task_run.task_run_id,
                stage_id="produce",
                task_ref="task.test.produce",
                task_result_ref=f"taskresult:revise-{index}",
                accepted=False,
                request_id=request["request_id"],
                dispatch_event_id=request["dispatch_context"]["dispatch_event_id"],
                diagnostics={
                    "unit_batch_execution_id": request["explicit_inputs"]["unit_batch_execution_id"],
                },
            ),
            inherited_inputs=dict(request["explicit_inputs"]),
        )
        if index < 2:
            assert result.stage_execution_request is not None
            request = result.stage_execution_request.to_dict()

    failed_state = loop.langgraph_coordination_runtime.checkpoints.get_state(
        thread_id=coordination_run.coordination_run_id
    )
    assert failed_state is not None
    assert "item_1_2" in failed_state["batch_lifecycle_runtime_state"]["failed_batch_ids"]

    rewound = loop.langgraph_coordination_runtime.rewind_from_stage(
        coordination_run_id=coordination_run.coordination_run_id,
        stage_id="produce",
        reason="retry_after_prompt_fix",
        refresh_graph_spec=True,
    )

    assert rewound.stage_execution_request is not None
    payload = rewound.stage_execution_request.to_dict()
    assert payload["stage_id"] == "produce"
    assert payload["explicit_inputs"]["unit_batch_id"] == "item_1_2"
    assert payload["request_id"] != request["request_id"]
    batch_state = rewound.state["batch_lifecycle_runtime_state"]
    assert "item_1_2" in batch_state["running_batch_ids"]
    assert batch_state["failed_batch_ids"] == []


def test_coordination_executor_failure_requeues_batch_without_business_repair(tmp_path: Path) -> None:
    graph = _batch_graph()
    spec = compile_task_graph_definition_runtime_spec(graph=graph)
    loop = TaskRunLoop(tmp_path, backend_dir=Path("backend"))
    started = loop.start_task_graph_run(session_id="session:test", graph=graph, runtime_spec=spec)
    assert started.coordination_run is not None
    coordination_run = started.coordination_run
    request = started.loop_state.diagnostics["stage_execution_request"]
    first_execution_id = request["explicit_inputs"]["unit_batch_execution_id"]

    result = loop.langgraph_coordination_runtime.resume_from_task_result(
        coordination_run=coordination_run,
        event=NodeResultReadyEvent(
            event_type="task_result_ready",
            coordination_run_id=coordination_run.coordination_run_id,
            task_run_id=started.task_run.task_run_id,
            stage_id="produce",
            task_ref="task.test.produce",
            task_result_ref="taskresult:provider-failed",
            accepted=False,
            request_id=request["request_id"],
            dispatch_event_id=request["dispatch_context"]["dispatch_event_id"],
            diagnostics={
                "unit_batch_execution_id": first_execution_id,
                "terminal_reason": "executor_failed",
                "last_error": {"code": "provider_error", "message": "Insufficient Balance"},
            },
        ),
        inherited_inputs=dict(request["explicit_inputs"]),
    )

    assert result.stage_execution_request is not None
    next_payload = result.stage_execution_request.to_dict()
    assert next_payload["stage_id"] == "produce"
    assert next_payload["explicit_inputs"]["unit_batch_id"] == "item_1_2"
    assert next_payload["explicit_inputs"]["unit_batch_execution_id"] != first_execution_id
    assert result.state["retry_counts"].get("produce") in {None, 0}
    assert result.state["contract_status"]["node_status"]["produce"]["diagnostics"]["reason"] == "technical_retry"
    batch_state = result.state["batch_lifecycle_runtime_state"]
    batch = next(item for item in batch_state["batch_states"] if item["batch_id"] == "item_1_2")
    assert batch["repair_round"] == 0
    assert batch_state["batch_execution_instances"][0]["status"] == "technical_failed"
    assert batch_state["diagnostics"]["last_transition"]["technical_failure"] is True


def test_coordination_technical_failure_circuit_breaks_to_blocked_checkpoint(tmp_path: Path) -> None:
    graph = _batch_graph()
    spec = compile_task_graph_definition_runtime_spec(graph=graph)
    loop = TaskRunLoop(tmp_path, backend_dir=Path("backend"))
    started = loop.start_task_graph_run(session_id="session:test", graph=graph, runtime_spec=spec)
    assert started.coordination_run is not None
    coordination_run = started.coordination_run
    request = started.loop_state.diagnostics["stage_execution_request"]

    result = None
    for index in range(3):
        execution_id = request["explicit_inputs"]["unit_batch_execution_id"]
        result = loop.langgraph_coordination_runtime.resume_from_task_result(
            coordination_run=coordination_run,
            event=NodeResultReadyEvent(
                event_type="task_result_ready",
                coordination_run_id=coordination_run.coordination_run_id,
                task_run_id=started.task_run.task_run_id,
                stage_id="produce",
                task_ref="task.test.produce",
                task_result_ref=f"taskresult:provider-failed-{index}",
                accepted=False,
                request_id=request["request_id"],
                dispatch_event_id=request["dispatch_context"]["dispatch_event_id"],
                diagnostics={
                    "unit_batch_execution_id": execution_id,
                    "terminal_reason": "executor_failed",
                    "last_error": {"code": "provider_error", "message": "Insufficient Balance"},
                },
            ),
            inherited_inputs=dict(request["explicit_inputs"]),
        )
        if index < 2:
            assert result.stage_execution_request is not None
            request = result.stage_execution_request.to_dict()

    assert result is not None
    assert result.stage_execution_request is None
    assert result.state["terminal_status"] == "blocked"
    assert result.state["node_statuses"]["produce"] == "blocked"
    assert result.state["diagnostics"]["batch_node_blocked_reason"] == "technical_retry_exhausted"
    assert result.state["retry_counts"].get("produce") in {None, 0}
    batch_state = result.state["batch_lifecycle_runtime_state"]
    batch = next(item for item in batch_state["batch_states"] if item["batch_id"] == "item_1_2")
    assert batch["status"] == "technical_blocked"
    assert batch["repair_round"] == 0
    assert batch_state["failed_batch_ids"] == []
