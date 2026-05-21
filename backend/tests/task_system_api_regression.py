from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from api import orchestration as orchestration_api
from api import tasks as tasks_api
from orchestration.runtime_loop.node_execution_request import NodeExecutionRequest
from orchestration.runtime_loop.models import AgentRun, CoordinationRun, TaskRun
from orchestration.runtime_loop.coordination_trace_adapter import CoordinationTraceAdapter
from orchestration.runtime_loop.state_index import RuntimeStateIndex
from orchestration.runtime_loop.task_run_loop import TaskRunLoop
from soul.facade import SoulFacade
from tasks import TaskFlowRegistry, TaskWorkflowRegistry
from tasks.task_graph_models import TaskGraphDefinition, TaskGraphNodeDefinition


class _RuntimeStub:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)


def _parallel_batch_api_graph() -> TaskGraphDefinition:
    return TaskGraphDefinition(
        graph_id="graph.test.parallel_batch_dispatch_api",
        title="并行批次派发 API 图",
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


def test_orchestration_agents_payload_keeps_removed_legacy_groups_absent(tmp_path: Path) -> None:
    TaskFlowRegistry(tmp_path).upsert_task_graph(
        graph_id="graph.test.runtime_lane",
        title="Runtime Lane Smoke Graph",
        nodes=(
            {
                "node_id": "node_a",
                "node_type": "agent",
                "title": "Node A",
                "runtime_lane": "coordination_task",
            },
        ),
    )
    original = orchestration_api.require_runtime
    orchestration_api.require_runtime = lambda: _RuntimeStub(tmp_path)  # type: ignore[assignment]
    try:
        payload = asyncio.run(orchestration_api.orchestration_agents())
    finally:
        orchestration_api.require_runtime = original  # type: ignore[assignment]

    groups = payload["agent_groups"]

    assert payload["authority"] == "orchestration.agent_runtime_registry"
    assert "coordination_task" in payload["options"]["runtime_lanes"]
    assert "output_contracts" not in payload["options"]
    assert "output_contract_options" not in payload["options"]
    assert "runtime_contracts" in payload["options"]["context_sections"]
    assert "artifact_refs" in payload["options"]["context_sections"]
    assert "formal_memory_read" in payload["options"]["memory_scopes"]
    removed_group_ids = {"group.writing.longform_novel_core"}
    assert all(item["group_id"] not in removed_group_ids for item in groups)


def test_coordination_rewind_api_downstream_scan_ignores_feedback_edges() -> None:
    state = {
        "stage_order": ["a", "b", "c", "d"],
        "diagnostics": {
            "coordination_graph_spec": {
                "edges": [
                    {"source_node_id": "a", "target_node_id": "b", "mode": "structured_handoff"},
                    {"source_node_id": "b", "target_node_id": "c", "mode": "structured_handoff"},
                    {"source_node_id": "c", "target_node_id": "d", "mode": "structured_handoff"},
                    {
                        "source_node_id": "d",
                        "target_node_id": "b",
                        "mode": "review_feedback",
                        "metadata": {"dependency_role": "feedback"},
                    },
                ]
            }
        },
    }

    assert orchestration_api._coordination_downstream_stage_ids(
        state=state,
        stage_id="d",
        include_downstream=True,
    ) == ["d"]


def test_dispatch_ready_batches_api_returns_multiple_standard_requests(tmp_path: Path) -> None:
    graph = _parallel_batch_api_graph()
    loop = TaskRunLoop(tmp_path, backend_dir=Path("backend"))
    runtime = SimpleNamespace(base_dir=Path("backend"), query_runtime=SimpleNamespace(task_run_loop=loop))
    start = loop.start_task_graph_run(
        session_id="session:test",
        graph=graph,
        runtime_spec=orchestration_api.compile_task_graph_definition_runtime_spec(graph=graph),
    )
    assert start.coordination_run is not None

    original = orchestration_api.require_runtime
    orchestration_api.require_runtime = lambda: runtime  # type: ignore[assignment]
    try:
        payload = asyncio.run(
            orchestration_api.dispatch_coordination_ready_batches(
                start.coordination_run.coordination_run_id,
                orchestration_api.CoordinationRunDispatchReadyBatchesRequest(
                    max_requests=2,
                    include_current_request=True,
                    execute_background=False,
                    source="test",
                ),
            )
        )
    finally:
        orchestration_api.require_runtime = original  # type: ignore[assignment]

    assert payload["authority"] == "orchestration.coordination_run_dispatch_ready_batches"
    assert payload["request_count"] == 2
    assert [item["explicit_inputs"]["unit_batch_id"] for item in payload["stage_execution_requests"]] == ["item_1_2", "item_3_4"]
    assert payload["stage_execution_requests"][0]["request_id"] != payload["stage_execution_requests"][1]["request_id"]
    assert payload["batch_dispatcher"]["summary"]["active_execution_count"] == 2


def test_coordination_rewind_invalidates_running_stage_task_runs(tmp_path: Path) -> None:
    state_index = RuntimeStateIndex(tmp_path / "runtime_state")
    root = TaskRun(
        task_run_id="taskrun:root",
        session_id="session:rewind",
        task_id="task.root",
        status="running",
    )
    stale = TaskRun(
        task_run_id="taskrun:session:turn:old:volume_plan:abc",
        session_id="session:rewind",
        task_id="taskinst:turn:old:volume_plan",
        agent_id="agent:writer",
        status="running",
    )
    other = TaskRun(
        task_run_id="taskrun:session:turn:old:chapter_outline:def",
        session_id="session:rewind",
        task_id="taskinst:turn:old:chapter_outline",
        agent_id="agent:writer",
        status="completed",
        terminal_reason="completed",
    )
    state_index.upsert_task_run(root)
    state_index.upsert_task_run(stale)
    state_index.upsert_task_run(other)
    state_index.upsert_agent_run(
        AgentRun(
            agent_run_id="agrun:stale",
            task_run_id=stale.task_run_id,
            agent_id="agent:writer",
            agent_profile_id="writer_runtime",
            status="running",
        )
    )
    coordination_run = CoordinationRun(
        coordination_run_id="coordrun:root",
        task_run_id=root.task_run_id,
        coordinator_agent_id="agent:coord",
        graph_ref="graph.test",
        status="running",
    )

    changed = orchestration_api._mark_invalidated_stage_task_runs(
        task_run_loop=type("Loop", (), {"state_index": state_index})(),
        coordination_run=coordination_run,
        stage_ids=["volume_plan", "chapter_outline"],
        reason="bad_stage_output",
    )

    assert changed == [
        {
            "task_run_id": stale.task_run_id,
            "stage_id": "volume_plan",
            "previous_status": "running",
            "status": "aborted",
        }
    ]
    invalidated = state_index.get_task_run(stale.task_run_id)
    assert invalidated is not None
    assert invalidated.status == "aborted"
    assert invalidated.terminal_reason == "user_aborted"
    assert invalidated.diagnostics["invalidated_by_coordination_rewind"]["stage_id"] == "volume_plan"
    assert state_index.get_task_run(other.task_run_id).status == "completed"  # type: ignore[union-attr]
    agent_run = state_index.list_task_agent_runs(stale.task_run_id)[0]
    assert agent_run.status == "killed"


def test_stage_execution_scheduler_skips_existing_same_source_task_run(tmp_path: Path) -> None:
    state_index = RuntimeStateIndex(tmp_path / "runtime_state")
    request = NodeExecutionRequest(
        request_id="nodeexec:draft",
        coordination_run_id="coordrun:root",
        thread_id="coordrun:root",
        root_task_run_id="taskrun:root",
        stage_id="chapter_draft",
        node_id="chapter_draft",
        task_ref="task.test.chapter_draft",
        explicit_inputs={"outline_ref": "artifact:outline.md"},
    )
    existing = TaskRun(
        task_run_id="taskrun:session:test:taskinst:turn:stable:chapter_draft:aaaa1111",
        session_id="session:test",
        task_id="taskinst:turn:stable:chapter_draft",
        status="running",
        diagnostics={
            "coordination_run_id": request.coordination_run_id,
            "stage_id": request.stage_id,
            "stage_request_id": request.request_id,
            "stage_idempotency_key": request.idempotency_key,
        },
    )
    state_index.upsert_task_run(existing)
    loop = SimpleNamespace(state_index=state_index, event_log=SimpleNamespace(append=lambda *args, **kwargs: None))

    result = orchestration_api._schedule_stage_execution_background(
        runtime=SimpleNamespace(query_runtime=SimpleNamespace(task_run_loop=loop)),
        session_id="session:test",
        source="test",
        stage_execution_request=request,
        current_turn_context={},
    )

    assert result["background_started"] is False
    assert result["reason"] == "stage_execution_already_has_effective_task_run"
    assert result["existing_task_run_id"] == existing.task_run_id


def test_stage_execution_scheduler_allows_new_idempotency_key(tmp_path: Path) -> None:
    state_index = RuntimeStateIndex(tmp_path / "runtime_state")
    first = NodeExecutionRequest(
        request_id="nodeexec:draft:first",
        coordination_run_id="coordrun:root",
        thread_id="coordrun:root",
        root_task_run_id="taskrun:root",
        stage_id="chapter_draft",
        node_id="chapter_draft",
        task_ref="task.test.chapter_draft",
        explicit_inputs={"outline_ref": "artifact:outline.md"},
        dispatch_context={"dispatch_event_id": "tlevent:first"},
    )
    retry = NodeExecutionRequest(
        request_id="nodeexec:draft:retry",
        coordination_run_id="coordrun:root",
        thread_id="coordrun:root",
        root_task_run_id="taskrun:root",
        stage_id="chapter_draft",
        node_id="chapter_draft",
        task_ref="task.test.chapter_draft",
        explicit_inputs={"outline_ref": "artifact:outline.md"},
        dispatch_context={"dispatch_event_id": "tlevent:retry"},
    )
    state_index.upsert_task_run(
        TaskRun(
            task_run_id="taskrun:session:test:taskinst:turn:first:chapter_draft:aaaa1111",
            session_id="session:test",
            task_id="taskinst:turn:first:chapter_draft",
            status="completed",
            diagnostics={
                "coordination_run_id": first.coordination_run_id,
                "stage_id": first.stage_id,
                "stage_request_id": first.request_id,
                "stage_idempotency_key": first.idempotency_key,
            },
        )
    )
    loop = SimpleNamespace(state_index=state_index)

    assert orchestration_api._matching_stage_execution_task_run(
        task_run_loop=loop,
        session_id="session:test",
        identity=orchestration_api._stage_execution_schedule_identity(retry),
    ) is None


def test_stage_execution_scheduler_ignores_rewind_invalidated_completed_run(tmp_path: Path) -> None:
    state_index = RuntimeStateIndex(tmp_path / "runtime_state")
    request = NodeExecutionRequest(
        request_id="nodeexec:draft",
        coordination_run_id="coordrun:root",
        thread_id="coordrun:root",
        root_task_run_id="taskrun:root",
        stage_id="chapter_draft",
        node_id="chapter_draft",
        task_ref="task.test.chapter_draft",
        explicit_inputs={"outline_ref": "artifact:outline.md"},
    )
    state_index.upsert_task_run(
        TaskRun(
            task_run_id="taskrun:session:test:taskinst:turn:first:chapter_draft:aaaa1111",
            session_id="session:test",
            task_id="taskinst:turn:first:chapter_draft",
            status="completed",
            diagnostics={
                "coordination_run_id": request.coordination_run_id,
                "stage_id": request.stage_id,
                "stage_request_id": request.request_id,
                "stage_idempotency_key": request.idempotency_key,
                "invalidated_by_coordination_rewind": {
                    "coordination_run_id": request.coordination_run_id,
                    "stage_id": request.stage_id,
                    "reason": "bad_stage_output",
                },
            },
        )
    )
    loop = SimpleNamespace(state_index=state_index)

    assert orchestration_api._matching_stage_execution_task_run(
        task_run_loop=loop,
        session_id="session:test",
        identity=orchestration_api._stage_execution_schedule_identity(request),
    ) is None


def test_graph_unit_stage_scheduler_starts_and_reuses_child_task_graph_run(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    runtime_dir = tmp_path / "runtime_state"
    registry = TaskFlowRegistry(backend_dir)
    registry.upsert_task_graph(
        graph_id="graph.test.graph_unit_child_run",
        title="GraphUnit 子图",
        graph_kind="multi_agent",
        nodes=(
            {
                "node_id": "child_node",
                "node_type": "agent",
                "title": "子节点",
                "task_id": "task_graph.node.graph.test.graph_unit_child_run.child_node",
                "agent_id": "agent:0",
            },
        ),
        runtime_policy={"coordinator_agent_id": "agent:0"},
        publish_state="published",
        enabled=True,
    )
    loop = TaskRunLoop(runtime_dir, backend_dir=backend_dir)
    runtime = SimpleNamespace(base_dir=backend_dir, query_runtime=SimpleNamespace(task_run_loop=loop))
    request = NodeExecutionRequest(
        request_id="nodeexec:graph-unit",
        coordination_run_id="coordrun:parent",
        thread_id="coordrun:parent",
        root_task_run_id="taskrun:parent",
        stage_id="graph_unit.block.child",
        node_id="graph_unit.block.child",
        task_ref="task_graph.node.graph.test.parent.graph_unit.block.child",
        executor_type="graph_unit",
        executor_binding={
            "selected_executor": "graph_unit",
            "graph_unit_runtime_handle": {
                "authority": "orchestration.graph_unit_runtime_handle",
                "handle_id": "graphunitrun:test",
                "parent_graph_id": "graph.test.parent",
                "parent_coordination_run_id": "coordrun:parent",
                "parent_root_task_run_id": "taskrun:parent",
                "parent_stage_id": "graph_unit.block.child",
                "parent_node_id": "graph_unit.block.child",
                "linked_graph_id": "graph.test.graph_unit_child_run",
                "nested_runtime_plan_id": "nested.block.child",
                "handoff_contract_id": "contract.test.graph_unit.handoff",
                "standard_input_package": {
                    "input_items": [
                        {
                            "input_key": "world_design",
                            "content_type": "artifact_text",
                            "metadata": {"text": "父级标准输入包只允许留在诊断中。"},
                        }
                    ]
                },
                "explicit_inputs": {
                    "user_goal": "启动子图",
                    "parent_stage_execution_request": {"artifact_refs": ["artifact:debug/should_not_be_visible.md"]},
                },
                "executor_policy": {"auto_start_child_initial_stage": False},
            },
        },
        runtime_assembly={
            "authority": "orchestration.graph_unit_runtime_assembly",
            "graph_unit_runtime_handle": {
                "authority": "orchestration.graph_unit_runtime_handle",
                "handle_id": "graphunitrun:test",
                "parent_graph_id": "graph.test.parent",
                "parent_coordination_run_id": "coordrun:parent",
                "parent_root_task_run_id": "taskrun:parent",
                "parent_stage_id": "graph_unit.block.child",
                "parent_node_id": "graph_unit.block.child",
                "linked_graph_id": "graph.test.graph_unit_child_run",
                "nested_runtime_plan_id": "nested.block.child",
                "handoff_contract_id": "contract.test.graph_unit.handoff",
                "standard_input_package": {
                    "input_items": [
                        {
                            "input_key": "world_design",
                            "content_type": "artifact_text",
                            "metadata": {"text": "父级标准输入包只允许留在诊断中。"},
                        }
                    ]
                },
                "explicit_inputs": {
                    "user_goal": "启动子图",
                    "parent_stage_execution_request": {"artifact_refs": ["artifact:debug/should_not_be_visible.md"]},
                },
                "executor_policy": {"auto_start_child_initial_stage": False},
            },
        },
        explicit_inputs={"user_goal": "启动子图"},
        dispatch_context={"dispatch_event_id": "tlevent:graph-unit:001"},
    )

    asyncio.run(
        orchestration_api._execute_stage_request_in_background(
            runtime=runtime,
            session_id="session:test",
            source="test",
            stage_execution_request=request,
            current_turn_context={},
        )
    )

    child_runs = [
        task_run
        for task_run in loop.state_index.list_session_task_runs("session:test")
        if dict(task_run.diagnostics or {}).get("graph_unit_child_run") is True
    ]
    assert len(child_runs) == 1
    child = child_runs[0]
    assert child.diagnostics["linked_graph_id"] == "graph.test.graph_unit_child_run"
    assert child.diagnostics["parent_coordination_run_id"] == "coordrun:parent"
    assert child.diagnostics["parent_stage_id"] == "graph_unit.block.child"
    assert child.diagnostics["stage_idempotency_key"] == request.idempotency_key
    assert child.diagnostics["parent_graph_unit_runtime_handle"]["linked_graph_id"] == "graph.test.graph_unit_child_run"
    assert child.diagnostics["parent_stage_execution_request"]["request_id"] == "nodeexec:graph-unit"
    assert child.diagnostics["parent_standard_input_package"]["input_items"][0]["input_key"] == "world_design"
    initial_inputs_ref = str(child.diagnostics["task_graph_initial_inputs_ref"])
    child_initial_inputs = dict(loop.runtime_objects.get_object(initial_inputs_ref)["initial_inputs"])
    assert child_initial_inputs == {"user_goal": "启动子图"}
    child_coordination_run_id = str(child.diagnostics["child_coordination_run_id"])
    child_state = loop.langgraph_coordination_runtime.checkpoints.get_state(thread_id=child_coordination_run_id)
    assert child_state["pending_inputs"]["user_goal"] == "启动子图"
    for protocol_key in (
        "parent_graph_unit_runtime_handle",
        "parent_stage_execution_request",
        "parent_standard_input_package",
        "graph_unit_runtime_handle",
    ):
        assert protocol_key not in child_state["pending_inputs"]
    assert child_state["diagnostics"]["filtered_internal_protocol_input_keys"] == []
    child_request = child_state["stage_execution_request"]
    child_explicit_inputs = dict(child_request["explicit_inputs"])
    assert child_explicit_inputs["user_goal"] == "启动子图"
    assert "parent_stage_execution_request" not in child_explicit_inputs
    assert "parent_standard_input_package" not in child_explicit_inputs
    child_input_keys = {
        item["input_key"]
        for item in child_request["standard_input_package"]["input_items"]
    }
    assert "user_goal" in child_input_keys
    assert "parent_stage_execution_request" not in child_input_keys
    assert "parent_standard_input_package" not in child_input_keys
    assert "parent_graph_unit_runtime_handle" not in child_input_keys
    assert child_request["artifact_context_packet"]["artifact_refs"] == []

    reused = orchestration_api._schedule_stage_execution_background(
        runtime=runtime,
        session_id="session:test",
        source="test",
        stage_execution_request=request,
        current_turn_context={},
    )

    assert reused["background_started"] is False
    assert reused["reason"] == "stage_execution_already_has_effective_task_run"
    assert reused["existing_task_run_id"] == child.task_run_id


def test_graph_unit_child_completion_commits_output_packet_and_releases_parent(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    runtime_dir = tmp_path / "runtime_state"
    registry = TaskFlowRegistry(backend_dir)
    registry.upsert_task_graph(
        graph_id="graph.test.child_graph_unit_commit",
        title="GraphUnit 子图提交",
        graph_kind="multi_agent",
        nodes=(
            {
                "node_id": "child_node",
                "node_type": "agent",
                "title": "子节点",
                "task_id": "task_graph.node.graph.test.child_graph_unit_commit.child_node",
                "agent_id": "agent:0",
            },
        ),
        runtime_policy={"coordinator_agent_id": "agent:0"},
        publish_state="published",
        enabled=True,
    )
    parent_graph = registry.upsert_task_graph(
        graph_id="graph.test.parent_graph_unit_commit",
        title="GraphUnit 父图提交",
        graph_kind="coordination",
        nodes=(
            {
                "node_id": "after_child",
                "node_type": "agent",
                "title": "后续节点",
                "task_id": "task_graph.node.graph.test.parent_graph_unit_commit.after_child",
                "agent_id": "agent:0",
            },
        ),
        edges=(
            {
                "edge_id": "child_to_after",
                "source_node_id": "graph_unit.block.child",
                "target_node_id": "after_child",
                "payload_contract_id": "contract.test.graph_unit.output",
                "ack_required": False,
            },
        ),
        metadata={
            "timeline_blocks": [
                {
                    "block_id": "block.child",
                    "block_type": "child_graph",
                    "title": "子图阶段",
                    "phase_id": "phase.child",
                    "linked_graph_id": "graph.test.child_graph_unit_commit",
                    "version_ref": "v1",
                    "handoff_contract_id": "contract.test.graph_unit.handoff",
                    "input_port_id": "input.child",
                    "output_port_id": "output.child",
                }
            ],
            "stage_contracts": [
                {
                    "stage_id": "graph_unit.block.child",
                    "task_ref": "task_graph.node.graph.test.parent_graph_unit_commit.graph_unit.block.child",
                    "node_id": "graph_unit.block.child",
                    "node_type": "graph_unit",
                    "title": "子图阶段",
                    "executor_policy": {
                        "default_executor": "graph_unit",
                        "allowed_executors": ["graph_unit"],
                        "subgraph_id": "graph.test.child_graph_unit_commit",
                        "auto_start_child_initial_stage": False,
                    },
                    "linked_graph_id": "graph.test.child_graph_unit_commit",
                    "nested_runtime_plan_id": "nested.block.child",
                    "handoff_contract_id": "contract.test.graph_unit.handoff",
                    "input_port_id": "input.child",
                    "output_port_id": "output.child",
                    "output_mappings": [{"output_key": "contract.test.graph_unit.output:artifact_refs", "required": True}],
                },
                {
                    "stage_id": "after_child",
                    "task_ref": "task_graph.node.graph.test.parent_graph_unit_commit.after_child",
                    "node_id": "after_child",
                    "node_type": "agent",
                    "title": "后续节点",
                    "agent_id": "agent:0",
                    "required_inputs": ["contract.test.graph_unit.output:artifact_refs"],
                    "input_bindings": [
                        {
                            "source": "stage_output",
                            "source_stage_id": "graph_unit.block.child",
                            "output_key": "contract.test.graph_unit.output:artifact_refs",
                            "input_key": "contract.test.graph_unit.output:artifact_refs",
                            "required": True,
                        }
                    ],
                },
            ],
        },
        runtime_policy={"coordinator_agent_id": "agent:0"},
        publish_state="published",
        enabled=True,
    )
    loop = TaskRunLoop(runtime_dir, backend_dir=backend_dir)
    runtime = SimpleNamespace(base_dir=backend_dir, query_runtime=SimpleNamespace(task_run_loop=loop))
    parent_start = loop.start_task_graph_run(
        session_id="session:test",
        graph=parent_graph,
        runtime_spec=orchestration_api.compile_task_graph_definition_runtime_spec(
            graph=parent_graph,
            communication_protocol=None,
        ),
        initial_inputs={"user_goal": "运行父图"},
    )
    parent_coordination_run = parent_start.coordination_run
    assert parent_coordination_run is not None
    parent_state = loop.langgraph_coordination_runtime.checkpoints.get_state(
        thread_id=parent_coordination_run.coordination_run_id,
    )
    parent_request = NodeExecutionRequest.from_dict(parent_state["stage_execution_request"])

    asyncio.run(
        orchestration_api._execute_stage_request_in_background(
            runtime=runtime,
            session_id="session:test",
            source="test",
            stage_execution_request=parent_request,
            current_turn_context={},
        )
    )
    child_run = next(
        task_run
        for task_run in loop.state_index.list_session_task_runs("session:test")
        if dict(task_run.diagnostics or {}).get("graph_unit_child_run") is True
    )
    child_coordination_run_id = str(child_run.diagnostics["child_coordination_run_id"])
    child_state = loop.langgraph_coordination_runtime.checkpoints.get_state(thread_id=child_coordination_run_id)
    child_state["terminal_status"] = "completed"
    child_state["node_statuses"] = {"child_node": "completed"}
    child_state["completed_nodes"] = ["child_node"]
    child_state["stage_results"] = {
        "child_node": {
            "task_run_id": "taskrun:child-node",
            "task_result_ref": "taskresult:child-node",
            "artifact_refs": ["artifact:child/final.md"],
            "outputs": {"summary": "子图完成", "output_refs": ["artifact:child/final.md"]},
            "accepted": True,
        }
    }
    child_state["final_result_ref"] = "taskresult:child-node"
    loop.langgraph_coordination_runtime.checkpoints.put_state(
        thread_id=child_coordination_run_id,
        state=child_state,
        metadata={"event": "test_child_completed"},
    )
    child_coordination_run = loop.state_index.get_coordination_run(child_coordination_run_id)
    assert child_coordination_run is not None
    CoordinationTraceAdapter(loop.state_index, loop.event_log).write_state(
        coordination_run=child_coordination_run,
        state=child_state,
        checkpoint_ref="coordchk:test-child-completed",
        event_task_run_id=child_run.task_run_id,
    )
    refreshed_child = loop.state_index.get_task_run(child_run.task_run_id)
    assert refreshed_child is not None
    loop.state_index.upsert_task_run(
        TaskRun(
            task_run_id=refreshed_child.task_run_id,
            session_id=refreshed_child.session_id,
            task_id=refreshed_child.task_id,
            task_contract_ref=refreshed_child.task_contract_ref,
            owner_agent_seat_id=refreshed_child.owner_agent_seat_id,
            agent_id=refreshed_child.agent_id,
            agent_profile_id=refreshed_child.agent_profile_id,
            runtime_lane=refreshed_child.runtime_lane,
            status="completed",
            created_at=refreshed_child.created_at,
            updated_at=refreshed_child.updated_at,
            latest_event_offset=refreshed_child.latest_event_offset,
            latest_checkpoint_ref=refreshed_child.latest_checkpoint_ref,
            terminal_reason="completed",
            diagnostics=refreshed_child.diagnostics,
        )
    )

    original = orchestration_api.require_runtime
    orchestration_api.require_runtime = lambda: runtime  # type: ignore[assignment]
    try:
        payload = asyncio.run(
            orchestration_api.continue_coordination_current_stage(
                parent_coordination_run.coordination_run_id,
                orchestration_api.CoordinationRunContinueRequest(source="test"),
            )
        )
        second = asyncio.run(
            orchestration_api.continue_coordination_current_stage(
                parent_coordination_run.coordination_run_id,
                orchestration_api.CoordinationRunContinueRequest(source="test"),
            )
        )
    finally:
        orchestration_api.require_runtime = original  # type: ignore[assignment]

    assert payload["mode"] == "resumed_from_graph_unit_child_output_packet"
    assert payload["consumed_task_run_id"] == child_run.task_run_id
    assert payload["packet_ref"].startswith("rtobj:graph_unit_output_packets:")
    assert payload["stage_execution_request"]["stage_id"] == "after_child"
    packet = loop.runtime_objects.get_object(payload["packet_ref"])
    assert packet["artifact_refs_by_stage"]["child_node"] == ["artifact:child/final.md"]
    assert packet["core_artifact_refs"] == ["artifact:child/final.md"]
    parent_state_after = loop.langgraph_coordination_runtime.checkpoints.get_state(
        thread_id=parent_coordination_run.coordination_run_id,
    )
    assert parent_state_after["node_statuses"]["graph_unit.block.child"] == "completed"
    assert parent_state_after["node_statuses"]["after_child"] == "running"
    stage_result = parent_state_after["stage_results"]["graph_unit.block.child"]
    assert stage_result["task_result_ref"] == payload["packet_ref"]
    assert stage_result["standard_result_package"]["authority"] == "task_graph.standard_node_result_package"
    committed_child = loop.state_index.get_task_run(child_run.task_run_id)
    assert committed_child is not None
    assert committed_child.diagnostics["graph_unit_output_packet_committed"]["packet_ref"] == payload["packet_ref"]
    assert second["mode"] in {"replayed_active_stage_request", "resumed_from_task_result"}
    assert loop.state_index.get_task_run(child_run.task_run_id).diagnostics["graph_unit_output_packet_committed"]["packet_ref"] == payload["packet_ref"]  # type: ignore[union-attr]


def test_graph_unit_core_artifact_refs_exclude_debug_reports() -> None:
    refs = orchestration_api._graph_unit_core_artifact_refs(
        artifact_refs_by_stage={
            "project_brief": [
                "artifact:run/project_brief.md",
                "artifact:run/debug/run_report_task-writing.md",
            ],
            "outline_design": ["artifact:run/outline/outline_design.md"],
            "baseline_memory_seed": ["artifact:run/memory/baseline/baseline_commit.md"],
        },
        all_artifact_refs=[],
    )

    assert refs == [
        "artifact:run/project_brief.md",
        "artifact:run/outline/outline_design.md",
        "artifact:run/memory/baseline/baseline_commit.md",
    ]


def test_graph_unit_child_result_waits_until_child_completed(tmp_path: Path) -> None:
    state_index = RuntimeStateIndex(tmp_path / "runtime_state")
    child = TaskRun(
        task_run_id="taskrun:child",
        session_id="session:test",
        task_id="task_graph.graph_unit.graph.child",
        status="running",
        diagnostics={
            "graph_unit_child_run": True,
            "parent_coordination_run_id": "coordrun:parent",
            "parent_stage_id": "graph_unit.block.child",
            "parent_stage_request_id": "nodeexec:graph-unit",
            "parent_stage_idempotency_key": "idem:graph-unit",
            "child_coordination_run_id": "coordrun:child",
            "linked_graph_id": "graph.child",
        },
    )
    state_index.upsert_task_run(child)
    loop = SimpleNamespace(
        state_index=state_index,
        runtime_objects=SimpleNamespace(put_object=lambda *args, **kwargs: "rtobj:should:not-write"),
        checkpoints=SimpleNamespace(load_latest=lambda _task_run_id: None),
        langgraph_coordination_runtime=SimpleNamespace(
            checkpoints=SimpleNamespace(get_state=lambda *, thread_id: {"terminal_status": ""})
        ),
    )
    runtime = SimpleNamespace(query_runtime=SimpleNamespace(task_run_loop=loop))
    result = orchestration_api._latest_unconsumed_graph_unit_child_result(
        runtime=runtime,
        session_id="session:test",
        state={
            "active_stage_id": "graph_unit.block.child",
            "stage_execution_request": {
                "stage_id": "graph_unit.block.child",
                "task_ref": "task_graph.node.graph.parent.graph_unit.block.child",
                "executor_type": "graph_unit",
                "request_id": "nodeexec:graph-unit",
                "idempotency_key": "idem:graph-unit",
            },
            "stage_contracts": {},
            "stage_results": {},
            "pending_inputs": {},
        },
        active_stage_id="graph_unit.block.child",
        coordination_run_id="coordrun:parent",
    )

    assert result == {}


def test_graph_unit_child_failure_commits_failure_packet_and_uses_parent_failure_policy(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    runtime_dir = tmp_path / "runtime_state"
    registry = TaskFlowRegistry(backend_dir)
    registry.upsert_task_graph(
        graph_id="graph.test.child_graph_unit_failure",
        title="GraphUnit 失败子图",
        graph_kind="multi_agent",
        nodes=(
            {
                "node_id": "child_node",
                "node_type": "agent",
                "title": "子节点",
                "task_id": "task_graph.node.graph.test.child_graph_unit_failure.child_node",
                "agent_id": "agent:0",
            },
        ),
        runtime_policy={"coordinator_agent_id": "agent:0"},
        publish_state="published",
        enabled=True,
    )
    parent_graph = registry.upsert_task_graph(
        graph_id="graph.test.parent_graph_unit_failure",
        title="GraphUnit 父图失败传播",
        graph_kind="coordination",
        nodes=(
            {
                "node_id": "after_child",
                "node_type": "agent",
                "title": "后续节点",
                "task_id": "task_graph.node.graph.test.parent_graph_unit_failure.after_child",
                "agent_id": "agent:0",
            },
        ),
        edges=(
            {
                "edge_id": "child_to_after",
                "source_node_id": "graph_unit.block.child",
                "target_node_id": "after_child",
                "payload_contract_id": "contract.test.graph_unit.output",
                "ack_required": False,
                "failure_propagation_policy": "fail_downstream",
            },
        ),
        metadata={
            "timeline_blocks": [
                {
                    "block_id": "block.child",
                    "block_type": "child_graph",
                    "title": "子图阶段",
                    "phase_id": "phase.child",
                    "linked_graph_id": "graph.test.child_graph_unit_failure",
                    "version_ref": "v1",
                    "handoff_contract_id": "contract.test.graph_unit.handoff",
                    "input_port_id": "input.child",
                    "output_port_id": "output.child",
                }
            ],
            "stage_contracts": [
                {
                    "stage_id": "graph_unit.block.child",
                    "task_ref": "task_graph.node.graph.test.parent_graph_unit_failure.graph_unit.block.child",
                    "node_id": "graph_unit.block.child",
                    "node_type": "graph_unit",
                    "title": "子图阶段",
                    "executor_policy": {
                        "default_executor": "graph_unit",
                        "allowed_executors": ["graph_unit"],
                        "subgraph_id": "graph.test.child_graph_unit_failure",
                        "auto_start_child_initial_stage": False,
                    },
                    "linked_graph_id": "graph.test.child_graph_unit_failure",
                    "nested_runtime_plan_id": "nested.block.child",
                    "handoff_contract_id": "contract.test.graph_unit.handoff",
                    "input_port_id": "input.child",
                    "output_port_id": "output.child",
                    "retry_policy": {"retry_limit": 0},
                },
                {
                    "stage_id": "after_child",
                    "task_ref": "task_graph.node.graph.test.parent_graph_unit_failure.after_child",
                    "node_id": "after_child",
                    "node_type": "agent",
                    "title": "后续节点",
                    "agent_id": "agent:0",
                },
            ],
        },
        runtime_policy={"coordinator_agent_id": "agent:0"},
        publish_state="published",
        enabled=True,
    )
    loop = TaskRunLoop(runtime_dir, backend_dir=backend_dir)
    runtime = SimpleNamespace(base_dir=backend_dir, query_runtime=SimpleNamespace(task_run_loop=loop))
    parent_start = loop.start_task_graph_run(
        session_id="session:test",
        graph=parent_graph,
        runtime_spec=orchestration_api.compile_task_graph_definition_runtime_spec(
            graph=parent_graph,
            communication_protocol=None,
        ),
        initial_inputs={"user_goal": "运行父图"},
    )
    parent_coordination_run = parent_start.coordination_run
    assert parent_coordination_run is not None
    parent_state = loop.langgraph_coordination_runtime.checkpoints.get_state(
        thread_id=parent_coordination_run.coordination_run_id,
    )
    parent_request = NodeExecutionRequest.from_dict(parent_state["stage_execution_request"])

    asyncio.run(
        orchestration_api._execute_stage_request_in_background(
            runtime=runtime,
            session_id="session:test",
            source="test",
            stage_execution_request=parent_request,
            current_turn_context={},
        )
    )
    child_run = next(
        task_run
        for task_run in loop.state_index.list_session_task_runs("session:test")
        if dict(task_run.diagnostics or {}).get("graph_unit_child_run") is True
    )
    child_coordination_run_id = str(child_run.diagnostics["child_coordination_run_id"])
    child_state = loop.langgraph_coordination_runtime.checkpoints.get_state(thread_id=child_coordination_run_id)
    child_state["terminal_status"] = "failed"
    child_state["node_statuses"] = {"child_node": "failed"}
    child_state["failed_nodes"] = ["child_node"]
    loop.langgraph_coordination_runtime.checkpoints.put_state(
        thread_id=child_coordination_run_id,
        state=child_state,
        metadata={"event": "test_child_failed"},
    )
    child_coordination_run = loop.state_index.get_coordination_run(child_coordination_run_id)
    assert child_coordination_run is not None
    CoordinationTraceAdapter(loop.state_index, loop.event_log).write_state(
        coordination_run=child_coordination_run,
        state=child_state,
        checkpoint_ref="coordchk:test-child-failed",
        event_task_run_id=child_run.task_run_id,
    )
    refreshed_child = loop.state_index.get_task_run(child_run.task_run_id)
    assert refreshed_child is not None
    loop.state_index.upsert_task_run(
        TaskRun(
            task_run_id=refreshed_child.task_run_id,
            session_id=refreshed_child.session_id,
            task_id=refreshed_child.task_id,
            task_contract_ref=refreshed_child.task_contract_ref,
            owner_agent_seat_id=refreshed_child.owner_agent_seat_id,
            agent_id=refreshed_child.agent_id,
            agent_profile_id=refreshed_child.agent_profile_id,
            runtime_lane=refreshed_child.runtime_lane,
            status="failed",
            created_at=refreshed_child.created_at,
            updated_at=refreshed_child.updated_at,
            latest_event_offset=refreshed_child.latest_event_offset,
            latest_checkpoint_ref=refreshed_child.latest_checkpoint_ref,
            terminal_reason="failed",
            diagnostics=refreshed_child.diagnostics,
        )
    )

    original = orchestration_api.require_runtime
    orchestration_api.require_runtime = lambda: runtime  # type: ignore[assignment]
    try:
        payload = asyncio.run(
            orchestration_api.continue_coordination_current_stage(
                parent_coordination_run.coordination_run_id,
                orchestration_api.CoordinationRunContinueRequest(source="test"),
            )
        )
    finally:
        orchestration_api.require_runtime = original  # type: ignore[assignment]

    assert payload["mode"] == "resumed_from_graph_unit_child_output_packet"
    assert payload["packet_ref"].startswith("rtobj:graph_unit_failure_packets:")
    assert payload["stage_execution_request"] is None
    parent_state_after = loop.langgraph_coordination_runtime.checkpoints.get_state(
        thread_id=parent_coordination_run.coordination_run_id,
    )
    assert parent_state_after["terminal_status"] == "failed"
    assert parent_state_after["node_statuses"]["graph_unit.block.child"] == "failed"
    assert parent_state_after["node_statuses"]["after_child"] == "failed"
    scheduler_state = dict(dict(parent_state_after["diagnostics"]).get("task_graph_scheduler_state") or {})
    assert scheduler_state["diagnostics"]["failure_propagated_node_ids"] == ["after_child"]
    committed_child = loop.state_index.get_task_run(child_run.task_run_id)
    assert committed_child is not None
    assert committed_child.diagnostics["graph_unit_failure_packet_committed"]["packet_ref"] == payload["packet_ref"]


def test_task_system_overview_exposes_formal_task_management_layers(tmp_path: Path) -> None:
    original = tasks_api.require_runtime
    tasks_api.require_runtime = lambda: _RuntimeStub(tmp_path)  # type: ignore[assignment]
    try:
        payload = asyncio.run(tasks_api.task_system_overview())
    finally:
        tasks_api.require_runtime = original  # type: ignore[assignment]

    summary = payload["summary"]
    task_management = payload["task_management"]
    task_graph_management = payload["task_graph_management"]
    diagnostics = payload["diagnostics"]

    assert payload["authority"] == "task_system.management_console"
    assert summary["specific_task_record_count"] == len(task_management["specific_task_records"])
    assert summary["projection_binding_count"] == 0
    assert summary["derived_projection_binding_count"] == len(task_management["projection_bindings"])
    assert summary["effective_projection_binding_count"] == len(task_management["projection_bindings"])
    assert summary["flow_contract_binding_count"] == 0
    assert summary["derived_flow_contract_binding_count"] == len(task_management["flow_contract_bindings"])
    assert summary["effective_flow_contract_binding_count"] == len(task_management["flow_contract_bindings"])
    assert summary["execution_policy_count"] == 0
    assert summary["derived_execution_policy_count"] == len(task_management["execution_policies"])
    assert summary["effective_execution_policy_count"] == len(task_management["execution_policies"])
    assert summary["communication_protocol_count"] == 0
    assert summary["contract_spec_count"] >= 5
    assert "agent_management" not in payload
    assert task_management["entry_policies"] == []
    assert all("writing" not in str(item.get("domain_id") or "") for item in task_management["task_domains"])
    assert all("writing" not in str(item.get("task_id") or "") for item in task_management["specific_task_records"])
    assert all("writing" not in str(item.get("flow_id") or "") for item in task_management["task_flow_definitions"])
    assert all("writing" not in str(item.get("task_id") or "") for item in task_management["projection_bindings"])
    assert all("writing" not in str(item.get("task_id") or "") for item in task_management["flow_contract_bindings"])
    assert all("writing" not in str(item.get("task_id") or "") for item in task_management["execution_policies"])
    assert task_graph_management["communication_protocols"] == []
    assert task_graph_management["task_graph_specs"] == []
    assert payload["contract_management"]["contract_specs"]
    assert diagnostics["runtime_recipe_validation_matrix"]["authority"] == "task_system.runtime_recipe_validation"
    assert diagnostics["runtime_recipe_validation_matrix"]["template_protocol_removed"] is True
    assert diagnostics["overview_mode"] == "lightweight"
    assert "compatibility" not in diagnostics


def test_task_domain_upsert_persists_and_returns_formal_domain_catalog(tmp_path: Path) -> None:
    original = tasks_api.require_runtime
    tasks_api.require_runtime = lambda: _RuntimeStub(tmp_path)  # type: ignore[assignment]
    try:
        payload = asyncio.run(
            tasks_api.upsert_task_system_domain(
                "domain.research",
                tasks_api.TaskDomainUpsertRequest(
                    domain_id="domain.research",
                    task_family="research",
                    title="研究任务域",
                    description="用于实验性研究任务。",
                    enabled=True,
                    sort_order=90,
                ),
            )
        )
    finally:
        tasks_api.require_runtime = original  # type: ignore[assignment]

    domains = payload["task_management"]["task_domains"]
    research = next(item for item in domains if item["domain_id"] == "domain.research")

    assert payload["summary"]["task_domain_count"] >= 1
    assert research["task_family"] == "research"
    assert research["title"] == "研究任务域"
    assert research["description"] == "用于实验性研究任务。"


def test_task_domain_delete_cascades_specific_tasks_and_domain_catalog(tmp_path: Path) -> None:
    original = tasks_api.require_runtime
    tasks_api.require_runtime = lambda: _RuntimeStub(tmp_path)  # type: ignore[assignment]
    try:
        asyncio.run(
            tasks_api.upsert_task_system_domain(
                "domain.research",
                tasks_api.TaskDomainUpsertRequest(
                    domain_id="domain.research",
                    task_family="research",
                    title="研究任务域",
                    description="用于实验性研究任务。",
                    enabled=True,
                    sort_order=90,
                ),
            )
        )
        asyncio.run(
            tasks_api.upsert_task_system_workflow(
                "workflow.900101",
                tasks_api.TaskWorkflowUpsertRequest(
                    workflow_id="workflow.900101",
                    title="研究实验临时工作流",
                    task_mode="bounded_patch",
                    steps=[{"step_id": "run_experiment", "title": "运行实验"}],
                    output_contract_id="AssistantFinalAnswer",
                ),
            )
        )
        asyncio.run(
            tasks_api.upsert_task_system_specific_record(
                "task.research.experiment",
                tasks_api.SpecificTaskRecordUpsertRequest(
                    task_id="task.research.experiment",
                    task_title="研究实验任务",
                    task_family="research",
                    task_mode="bounded_patch",
                    description="research test",
                    default_flow_contract_id="flow.research.experiment",
                    default_workflow_id="workflow.900101",
                ),
            )
        )
        payload = asyncio.run(tasks_api.delete_task_system_domain("domain.research"))
    finally:
        tasks_api.require_runtime = original  # type: ignore[assignment]

    domains = payload["task_management"]["task_domains"]
    records = payload["task_management"]["specific_task_records"]

    assert all(item["domain_id"] != "domain.research" for item in domains)
    assert all(item["task_family"] != "research" for item in records)
    assert all(item["workflow_id"] != "workflow.900101" for item in payload["task_management"]["workflow_resources"])
    assert payload["last_deletion"]["domain_id"] == "domain.research"
    assert "task.research.experiment" in payload["last_deletion"]["deleted_task_ids"]
    assert "workflow.900101" in payload["last_deletion"]["deleted_workflow_ids"]


def test_specific_task_delete_cascades_task_assembly_objects(tmp_path: Path) -> None:
    original = tasks_api.require_runtime
    tasks_api.require_runtime = lambda: _RuntimeStub(tmp_path)  # type: ignore[assignment]
    try:
        asyncio.run(
            tasks_api.upsert_task_system_workflow(
                "workflow.900102",
                tasks_api.TaskWorkflowUpsertRequest(
                    workflow_id="workflow.900102",
                    title="研究实验补丁工作流",
                    task_mode="bounded_patch",
                    steps=[{"step_id": "patch", "title": "实施补丁"}],
                    output_contract_id="AssistantFinalAnswer",
                ),
            )
        )
        asyncio.run(
            tasks_api.upsert_task_system_specific_record(
                "task.research.experiment",
                tasks_api.SpecificTaskRecordUpsertRequest(
                    task_id="task.research.experiment",
                    task_title="研究实验任务",
                    task_family="research",
                    task_mode="bounded_patch",
                    description="research test",
                    default_flow_contract_id="flow.research.experiment",
                    default_workflow_id="workflow.900102",
                ),
            )
        )
        asyncio.run(
            tasks_api.upsert_task_system_projection_binding(
                "task.research.experiment",
                tasks_api.TaskProjectionBindingUpsertRequest(
                    task_id="task.research.experiment",
                    projection_selection_mode="task_default",
                    default_projection_id="projection.research",
                ),
            )
        )
        payload = asyncio.run(tasks_api.delete_task_system_specific_record("task.research.experiment"))
    finally:
        tasks_api.require_runtime = original  # type: ignore[assignment]

    task_management = payload["task_management"]

    assert all(item["task_id"] != "task.research.experiment" for item in task_management["specific_task_records"])
    assert all(item["task_id"] != "task.research.experiment" for item in task_management["projection_bindings"])
    assert all(item["task_id"] != "task.research.experiment" for item in task_management["flow_contract_bindings"])
    assert all(item["task_id"] != "task.research.experiment" for item in task_management["execution_policies"])
    assert all(item["workflow_id"] != "workflow.900102" for item in task_management["workflow_resources"])
    assert payload["last_deletion"]["task_id"] == "task.research.experiment"
    assert payload["last_deletion"]["deleted_workflow_ids"] == ["workflow.900102"]


def test_task_system_next_ids_are_generated_with_prefixed_internal_ids_and_display_numbers(tmp_path: Path) -> None:
    original = tasks_api.require_runtime
    tasks_api.require_runtime = lambda: _RuntimeStub(tmp_path)  # type: ignore[assignment]
    try:
        payload = asyncio.run(tasks_api.task_system_next_ids())
    finally:
        tasks_api.require_runtime = original  # type: ignore[assignment]

    assert payload["authority"] == "task_system.id_registry"
    assert str(payload["task_id"]).startswith("task.")
    assert str(payload["flow_id"]).startswith("flow.")
    assert str(payload["workflow_id"]).startswith("workflow.")
    assert str(payload["graph_id"]).startswith("graph.")
    assert str(payload["topology_template_id"]).startswith("topology.")

    display_numbers = payload["display_numbers"]
    assert str(display_numbers["task"]).startswith("任务-")
    assert str(display_numbers["flow"]).startswith("流程-")
    assert str(display_numbers["workflow"]).startswith("流程-")
    assert str(display_numbers["coordination"]).startswith("协作-")
    assert str(display_numbers["topology"]).startswith("拓扑-")


def test_task_graph_execution_package_combines_runtime_contracts_and_scheduler(tmp_path: Path) -> None:
    registry = TaskFlowRegistry(tmp_path)
    registry.upsert_task_graph(
        graph_id="graph.test.execution_package",
        title="执行包验证图",
        graph_kind="multi_agent",
        nodes=(
            {
                "node_id": "start",
                "node_type": "agent",
                "title": "开始节点",
                "agent_id": "agent:0",
            },
            {
                "node_id": "finish",
                "node_type": "agent",
                "title": "结束节点",
                "agent_id": "agent:0",
            },
        ),
        edges=(
            {
                "edge_id": "start_finish",
                "source_node_id": "start",
                "target_node_id": "finish",
                "payload_contract_id": "contract.agent_output.markdown",
                "wait_policy": "wait_handoff_ack",
                "ack_required": True,
            },
        ),
        contract_bindings={"schema": {"graph_contract_id": "contract.user_request.basic"}},
        publish_state="published",
        enabled=True,
    )
    original = tasks_api.require_runtime
    tasks_api.require_runtime = lambda: _RuntimeStub(tmp_path)  # type: ignore[assignment]
    try:
        payload = asyncio.run(tasks_api.build_task_system_task_graph_execution_package("graph.test.execution_package"))
    finally:
        tasks_api.require_runtime = original  # type: ignore[assignment]

    assert payload["authority"] == "task_system.task_graph_execution_package"
    assert payload["graph_id"] == "graph.test.execution_package"
    assert payload["runtime_spec"]["graph_id"] == "graph.test.execution_package"
    assert payload["contract_manifest"]["graph_contract_bindings"]["schema"]["graph_contract_id"] == "contract.user_request.basic"
    assert payload["scheduler_state"]["authority"] == "task_system.task_graph_scheduler_state"
    assert payload["summary"]["node_count"] == 2
    assert payload["summary"]["edge_count"] == 1
    assert payload["summary"]["assembly_count"] == 2
    assert payload["summary"]["object_trace_count"] == 4
    assert payload["node_runtime_assemblies"][0]["authority"] == "orchestration.node_runtime_assembly"
    trace_by_type = {
        (item["object_type"], item["object_id"]): item
        for item in payload["object_trace_index"]
    }
    assert trace_by_type[("graph", "graph.test.execution_package")]["manifest_ref"]["manifest_id"] == "contract-manifest:coordination:graph.test.execution_package"
    assert trace_by_type[("node", "start")]["assembly_ref"]["assembly_id"].startswith("runtime-assembly:node:")
    assert trace_by_type[("edge", "start_finish")]["manifest_ref"]["contract_refs"] == ["contract.agent_output.markdown"]


def test_task_graph_execution_package_expands_graph_unit_child_plan(tmp_path: Path) -> None:
    registry = TaskFlowRegistry(tmp_path)
    registry.upsert_task_graph(
        graph_id="graph.test.child_execution_plan",
        title="子图执行计划",
        graph_kind="multi_agent",
        nodes=(
            {
                "node_id": "child_start",
                "node_type": "agent",
                "title": "子图开始",
                "agent_id": "agent:0",
            },
            {
                "node_id": "child_finish",
                "node_type": "agent",
                "title": "子图结束",
                "agent_id": "agent:0",
            },
        ),
        edges=(
            {
                "edge_id": "child_start_finish",
                "source_node_id": "child_start",
                "target_node_id": "child_finish",
                "payload_contract_id": "contract.agent_output.markdown",
            },
        ),
        publish_state="published",
        enabled=True,
    )
    registry.upsert_task_graph(
        graph_id="graph.test.parent_execution_plan",
        title="父图执行计划",
        graph_kind="coordination",
        metadata={
            "timeline_blocks": [
                {
                    "block_id": "block.child",
                    "block_type": "child_graph",
                    "title": "子图阶段",
                    "phase_id": "phase.child",
                    "linked_graph_id": "graph.test.child_execution_plan",
                    "version_ref": "v1",
                    "handoff_contract_id": "contract.agent_output.markdown",
                    "input_port_id": "input.child",
                    "output_port_id": "output.child",
                }
            ],
        },
        publish_state="published",
        enabled=True,
    )
    original = tasks_api.require_runtime
    tasks_api.require_runtime = lambda: _RuntimeStub(tmp_path)  # type: ignore[assignment]
    try:
        payload = asyncio.run(tasks_api.build_task_system_task_graph_execution_package("graph.test.parent_execution_plan"))
    finally:
        tasks_api.require_runtime = original  # type: ignore[assignment]

    plans = payload["graph_unit_execution_plans"]
    assert payload["summary"]["graph_unit_count"] == 1
    assert payload["summary"]["graph_unit_handoff_contract_count"] == 1
    assert payload["summary"]["graph_unit_execution_plan_count"] == 1
    assert payload["summary"]["graph_unit_execution_plan_issue_count"] == 0
    assert plans[0]["authority"] == "task_system.graph_unit_execution_plan"
    assert plans[0]["valid"] is True
    assert plans[0]["linked_graph_id"] == "graph.test.child_execution_plan"
    assert plans[0]["child_graph"]["title"] == "子图执行计划"
    assert plans[0]["child_runtime_spec_summary"]["node_count"] == 2
    assert plans[0]["child_contract_manifest_summary"]["edge_handoff_contract_count"] == 1
    assert plans[0]["child_scheduler_summary"]["authority"] == "task_system.task_graph_scheduler_state"
    assert plans[0]["child_node_runtime_assembly_summary"]["assembly_count"] == 2
    graph_unit_contracts = payload["contract_manifest"]["graph_unit_handoff_contracts"]
    assert graph_unit_contracts[0]["runtime_node_id"] == "graph_unit.block.child"
    assert graph_unit_contracts[0]["handoff_contract_id"] == "contract.agent_output.markdown"
    graph_unit_trace = next(item for item in payload["object_trace_index"] if item["object_type"] == "graph_unit")
    assert graph_unit_trace["runtime_ref"]["plan_id"] == "nested.block.child"
    assert graph_unit_trace["manifest_ref"]["handoff_contract_id"] == "contract.agent_output.markdown"
    assert graph_unit_trace["child_plan_ref"]["valid"] is True


def test_task_graph_execution_package_reports_missing_graph_unit_child(tmp_path: Path) -> None:
    TaskFlowRegistry(tmp_path).upsert_task_graph(
        graph_id="graph.test.parent_missing_child",
        title="父图缺失子图",
        graph_kind="coordination",
        metadata={
            "timeline_blocks": [
                {
                    "block_id": "block.missing",
                    "block_type": "child_graph",
                    "title": "缺失子图阶段",
                    "phase_id": "phase.child",
                    "linked_graph_id": "graph.test.missing_child",
                    "version_ref": "v1",
                    "handoff_contract_id": "contract.agent_output.markdown",
                }
            ],
        },
        publish_state="published",
        enabled=True,
    )
    original = tasks_api.require_runtime
    tasks_api.require_runtime = lambda: _RuntimeStub(tmp_path)  # type: ignore[assignment]
    try:
        payload = asyncio.run(tasks_api.build_task_system_task_graph_execution_package("graph.test.parent_missing_child"))
    finally:
        tasks_api.require_runtime = original  # type: ignore[assignment]

    assert payload["valid"] is False
    assert payload["graph_unit_execution_plans"][0]["valid"] is False
    assert payload["summary"]["graph_unit_execution_plan_issue_count"] == 1
    assert any(issue["code"] == "graph_unit_linked_graph_not_found" for issue in payload["issues"])


def test_task_system_formal_object_upserts_persist_and_return_management_payload(tmp_path: Path) -> None:
    original = tasks_api.require_runtime
    tasks_api.require_runtime = lambda: _RuntimeStub(tmp_path)  # type: ignore[assignment]
    try:
        projection_payload = asyncio.run(
            tasks_api.upsert_task_system_projection_binding(
                "task.dev.light_web_game",
                tasks_api.TaskProjectionBindingUpsertRequest(
                    task_id="task.dev.light_web_game",
                    projection_selection_mode="allow_list",
                    allowed_projection_ids=["projection.dev.builder"],
                    default_projection_id="projection.dev.builder",
                    projection_required=True,
                    notes="test projection binding",
                ),
            )
        )
        flow_contract_payload = asyncio.run(
            tasks_api.upsert_task_system_flow_contract_binding(
                "task.dev.light_web_game",
                tasks_api.TaskFlowContractBindingUpsertRequest(
                    task_id="task.dev.light_web_game",
                    flow_contract_id="flow.dev.light_web_game",
                    override_policy="strict_task_default",
                    verification_gate_profile="gate.dev.qa",
                    fallback_policy="fail_closed",
                ),
            )
        )
        execution_payload = asyncio.run(
            tasks_api.upsert_task_system_execution_policy(
                "task.dev.light_web_game",
                tasks_api.TaskExecutionPolicyUpsertRequest(
                    task_id="task.dev.light_web_game",
                    execution_chain_type="single_agent_chain",
                    runtime_agent_selection_policy="orchestration_default",
                    default_agent_id="agent:3",
                    task_level="standard",
                    task_privilege="bounded",
                    allow_worker_agent_spawn=True,
                    worker_agent_blueprint_id="worker.dev.prototype",
                    worker_agent_naming_rule="game-worker-{n}",
                    notes="test adoption plan",
                ),
            )
        )
        protocol_payload = asyncio.run(
            tasks_api.upsert_task_system_communication_protocol(
                "protocol.dev.parallel_review",
                tasks_api.TaskCommunicationProtocolUpsertRequest(
                    protocol_id="protocol.dev.parallel_review",
                    title="并行评审协议",
                    message_types=["task_claim", "draft_result", "review_feedback"],
                    payload_contracts=["DraftResult", "ReviewFeedback"],
                    signal_rules=["worker_to_coordinator", "coordinator_merge"],
                    handoff_rules=["structured_refs_only"],
                    ack_policy="explicit_ack",
                    timeout_policy="fail_closed",
                    error_signal_policy="raise_to_coordinator",
                    enabled=True,
                ),
            )
        )
    finally:
        tasks_api.require_runtime = original  # type: ignore[assignment]

    registry = TaskFlowRegistry(tmp_path)
    projection_binding = registry.get_projection_binding("task.dev.light_web_game")
    flow_binding = registry.get_flow_contract_binding("task.dev.light_web_game")
    execution_policy = registry.get_task_agent_adoption_plan("task.dev.light_web_game")
    protocol = registry.get_task_communication_protocol("protocol.dev.parallel_review")

    assert projection_payload["task_management"]["projection_bindings"]
    assert flow_contract_payload["task_management"]["flow_contract_bindings"]
    assert execution_payload["task_management"]["execution_policies"]
    assert protocol_payload["task_graph_management"]["communication_protocols"]

    assert projection_binding is not None
    assert projection_binding.projection_selection_mode == "allow_list"
    assert projection_binding.default_projection_id == "projection.dev.builder"
    assert projection_binding.projection_required is True

    assert flow_binding is not None
    assert flow_binding.override_policy == "strict_task_default"
    assert flow_binding.verification_gate_profile == "gate.dev.qa"

    assert execution_policy is not None
    assert execution_policy.to_dict()["authority"] == "task_system.task_execution_policy"
    assert execution_policy.to_dict()["execution_chain_type"] == "single_agent_chain"
    assert execution_policy.to_dict()["default_agent_id"] == "agent:3"
    assert execution_payload["task_management"]["execution_policies"][0]["default_agent_id"] == "agent:3"
    assert execution_policy.adoption_mode == "adopt_with_projection"
    assert execution_policy.allow_worker_agent_spawn is True
    assert execution_policy.worker_agent_blueprint_id == "worker.dev.prototype"

    assert protocol is not None
    assert protocol.enabled is True
    assert "review_feedback" in protocol.message_types


def test_task_execution_policy_normalizes_legacy_worker_spawn_mode(tmp_path: Path) -> None:
    registry = TaskFlowRegistry(tmp_path)

    registry.upsert_task_agent_adoption_plan(
        task_id="task.dev.light_web_game",
        adoption_mode="spawn_worker_allowed",
        default_agent_id="agent:0",
        allow_worker_agent_spawn=True,
        worker_agent_blueprint_id="worker.dev.prototype",
    )

    policy = registry.get_task_agent_adoption_plan("task.dev.light_web_game")

    assert policy is not None
    assert policy.adoption_mode == "adopt_with_projection"


def test_coordination_task_is_domain_parent_with_specific_subtask_refs(tmp_path: Path) -> None:
    original = tasks_api.require_runtime
    tasks_api.require_runtime = lambda: _RuntimeStub(tmp_path)  # type: ignore[assignment]
    try:
        asyncio.run(
            tasks_api.upsert_task_system_specific_record(
                "task.research.plan",
                tasks_api.SpecificTaskRecordUpsertRequest(
                    task_id="task.research.plan",
                    task_title="研究规划",
                    task_family="research",
                    task_mode="analysis_plan",
                    description="测试用规划子任务。",
                ),
            )
        )
        asyncio.run(
            tasks_api.upsert_task_system_specific_record(
                "task.research.report",
                tasks_api.SpecificTaskRecordUpsertRequest(
                    task_id="task.research.report",
                    task_title="研究报告",
                    task_family="research",
                    task_mode="analysis_report",
                    description="测试用报告子任务。",
                ),
            )
        )
        payload = asyncio.run(
            tasks_api.upsert_task_system_task_graph_bundle(
                "graph.research.test_parent",
                tasks_api.CoordinationTaskUpsertRequest(
                    graph_id="graph.research.test_parent",
                    title="研究父级协调任务",
                    coordination_mode="review_merge",
                    coordinator_agent_id="agent:20",
                    task_family="research",
                    domain_id="domain.research",
                    agent_group_id="group.research.test_parent",
                    participant_agent_ids=["agent:23", "agent:24"],
                    topology_template_id="topology.research.test_parent",
                    subtask_refs=["task.research.plan", "task.research.report"],
                    graph_nodes=[
                        {"node_id": "coordinator", "node_type": "coordinator", "agent_id": "agent:20", "role": "coordinator"},
                        {"node_id": "plan", "node_type": "subtask", "task_id": "task.research.plan", "agent_id": "agent:23", "role": "participant"},
                        {"node_id": "report", "node_type": "subtask", "task_id": "task.research.report", "agent_id": "agent:24", "role": "participant"},
                    ],
                    graph_edges=[
                        {"edge_id": "e1", "from": "coordinator", "to": "plan", "mode": "draft_request"},
                        {"edge_id": "e2", "from": "plan", "to": "report", "mode": "structured_handoff"},
                    ],
                    communication_modes=["draft_request", "structured_handoff"],
                    enabled=True,
                    metadata={"protocol_id": "protocol.research.review_pipeline"},
                ),
            )
        )
        graph_spec = asyncio.run(tasks_api.compile_task_system_task_graph_runtime_spec("graph.research.test_parent"))
        coordination_detail = asyncio.run(tasks_api.get_task_system_task_graph("graph.research.test_parent"))
    finally:
        tasks_api.require_runtime = original  # type: ignore[assignment]

    coordination = next(
        item
        for item in payload["task_graph_management"]["task_graphs"]
        if item["graph_id"] == "graph.research.test_parent"
    )
    assert coordination["domain_id"] == "domain.research"
    assert coordination["task_family"] == "research"
    assert coordination["overview_mode"] == "summary"
    assert coordination["node_count"] == 3
    assert coordination_detail["subtask_refs"] == ["task.research.plan", "task.research.report"]
    assert {node["task_id"] for node in coordination_detail["graph_nodes"] if node.get("task_id")} == set(coordination_detail["subtask_refs"])
    assert graph_spec["valid"] is True
    assert graph_spec["domain_id"] == "domain.research"
    assert graph_spec["start_node_ids"]
    assert graph_spec["terminal_node_ids"]


def test_task_system_specific_record_is_canonical_and_assignment_becomes_compat_view(tmp_path: Path) -> None:
    original = tasks_api.require_runtime
    tasks_api.require_runtime = lambda: _RuntimeStub(tmp_path)  # type: ignore[assignment]
    try:
        record_payload = asyncio.run(
            tasks_api.upsert_task_system_specific_record(
                "task.dev.light_web_game",
                tasks_api.SpecificTaskRecordUpsertRequest(
                    task_id="task.dev.light_web_game",
                    task_title="轻量网页小游戏开发",
                    task_family="development",
                    task_mode="light_web_game",
                    description="canonical specific task record",
                    input_contract_id="LightWebGameTaskInput",
                    output_contract_id="LightWebGameResult",
                    acceptance_profile_id="accept.game.delivery",
                    default_flow_contract_id="flow.dev.light_web_game",
                    default_workflow_id="workflow.dev.light_web_game",
                    default_projection_policy="workflow_compatible_or_task_default",
                    task_policy={
                        "safety_policy": {"verification_mode": "qa_required"},
                        "task_structure": {"memory_scope_hint": "conversation_readonly"},
                    },
                    enabled=True,
                    metadata={"runtime_recipe_id": "runtime.recipe.light_web_game"},
                ),
            )
        )
    finally:
        tasks_api.require_runtime = original  # type: ignore[assignment]

    registry = TaskFlowRegistry(tmp_path)
    specific_record = registry.get_specific_task_record("task.dev.light_web_game")
    compat_assignment = registry.get_task_assignment("task.dev.light_web_game")

    assert record_payload["task_management"]["specific_task_records"]
    assert specific_record is not None
    assert specific_record.description == "canonical specific task record"
    assert specific_record.acceptance_profile_id == "accept.game.delivery"
    assert specific_record.default_flow_contract_id == "flow.dev.light_web_game"

    assert compat_assignment is not None
    assert compat_assignment.task_id == specific_record.task_id
    assert compat_assignment.task_title == specific_record.task_title
    assert compat_assignment.workflow_id == specific_record.default_workflow_id
    assert compat_assignment.input_contract_id == specific_record.input_contract_id


def test_task_system_no_longer_seeds_concrete_writing_task_objects(tmp_path: Path) -> None:
    registry = TaskFlowRegistry(tmp_path)

    removed_refs = {
        "flows": [
            "flow.writing.short_story",
            "flow.writing.longform_novel_project",
        ],
        "records": [
            "task.writing.short_story",
            "task.writing.longform_novel_project",
        ],
        "protocols": [
            "protocol.writing.short_story_pipeline",
            "protocol.writing.longform_project_bootstrap",
        ],
        "coordination_tasks": [
            "graph.writing.short_story_pipeline",
            "graph.writing.longform_project_bootstrap",
        ],
        "adoption_plans": [
            "task.writing.longform_novel_project",
        ],
    }

    for flow_id in removed_refs["flows"]:
        assert registry.get_flow(flow_id) is None
    for task_id in removed_refs["records"]:
        assert registry.get_specific_task_record(task_id) is None
        assert registry.get_task_assignment(task_id) is None
    for protocol_id in removed_refs["protocols"]:
        assert registry.get_task_communication_protocol(protocol_id) is None
    for graph_id in removed_refs["coordination_tasks"]:
        assert registry.get_task_graph(graph_id) is None
    for task_id in removed_refs["adoption_plans"]:
        assert registry.get_task_agent_adoption_plan(task_id) is None


def test_task_graph_api_persists_working_memory_strategy_fields(tmp_path: Path) -> None:
    original = tasks_api.require_runtime
    tasks_api.require_runtime = lambda: _RuntimeStub(tmp_path)  # type: ignore[assignment]
    try:
        payload = asyncio.run(
            tasks_api.upsert_task_system_task_graph(
                "graph.test.working_memory",
                tasks_api.TaskGraphUpsertRequest(
                    graph_id="graph.test.working_memory",
                    title="工作记忆策略图",
                    graph_kind="multi_agent",
                    nodes=[
                        {
                            "node_id": "planner",
                            "node_type": "agent",
                            "title": "规划节点",
                            "agent_id": "agent:planner",
                            "memory_read_policy": {
                                "readable_kinds": ["task_goal", "decision_record"],
                                "readable_scopes": ["graph_scope"],
                            },
                            "memory_writeback_policy": {
                                "writable_kinds": ["plan_fragment"],
                                "writable_scopes": ["node_scope"],
                            },
                            "dynamic_memory_read_policy": {
                                "allow_dynamic_read": True,
                                "max_dynamic_reads_per_node_run": 2,
                            },
                        },
                        {
                            "node_id": "writer",
                            "node_type": "agent",
                            "title": "写作节点",
                            "agent_id": "agent:writer",
                        },
                    ],
                    edges=[
                        {
                            "edge_id": "planner_to_writer",
                            "source_node_id": "planner",
                            "target_node_id": "writer",
                            "working_memory_handoff_policy": {
                                "carry_kinds": ["plan_fragment"],
                                "carry_scopes": ["handoff_only"],
                            },
                        }
                    ],
                    working_memory_policy_profile_id="wmprofile.test",
                    working_memory_policy={
                        "enabled": True,
                        "default_scope": "graph_scope",
                    },
                    runtime_policy={
                        "working_memory_profile_id": "wmprofile.test",
                    },
                ),
            )
        )
        graph_detail = asyncio.run(tasks_api.get_task_system_task_graph("graph.test.working_memory"))
    finally:
        tasks_api.require_runtime = original  # type: ignore[assignment]

    graph = next(
        item
        for item in payload["task_graph_management"]["task_graphs"]
        if item["graph_id"] == "graph.test.working_memory"
    )
    assert graph["working_memory_policy_profile_id"] == "wmprofile.test"
    assert graph["working_memory_policy"]["default_scope"] == "graph_scope"
    assert graph["runtime_policy"]["working_memory_profile_id"] == "wmprofile.test"
    assert graph["overview_mode"] == "summary"
    assert graph["node_count"] == 2
    planner = next(item for item in graph_detail["nodes"] if item["node_id"] == "planner")
    edge = graph_detail["edges"][0]
    assert planner["memory_read_policy"]["readable_kinds"] == ["task_goal", "decision_record"]
    assert planner["dynamic_memory_read_policy"]["max_dynamic_reads_per_node_run"] == 2
    assert edge["working_memory_handoff_policy"]["carry_kinds"] == ["plan_fragment"]


def test_task_graph_api_migrates_legacy_prompt_metadata_to_projection(tmp_path: Path) -> None:
    original = tasks_api.require_runtime
    tasks_api.require_runtime = lambda: _RuntimeStub(tmp_path)  # type: ignore[assignment]
    try:
        payload = asyncio.run(
            tasks_api.upsert_task_system_task_graph(
                "graph.test.prompt_migration",
                tasks_api.TaskGraphUpsertRequest(
                    graph_id="graph.test.prompt_migration",
                    title="Prompt 迁移图",
                    task_family="story",
                    graph_kind="multi_agent",
                    nodes=[
                        {
                            "node_id": "world_review",
                            "node_type": "agent",
                            "title": "世界观审核",
                            "agent_id": "agent:reviewer",
                            "metadata": {
                                "role_prompt": "你是一名世界观审核员。你只负责评审一致性。你不负责扩写剧情。",
                                "role_identity": "你是一名世界观审核员。",
                            },
                        }
                    ],
                ),
            )
        )
        graph_detail = asyncio.run(tasks_api.get_task_system_task_graph("graph.test.prompt_migration"))
    finally:
        tasks_api.require_runtime = original  # type: ignore[assignment]

    graph = next(
        item
        for item in payload["task_graph_management"]["task_graphs"]
        if item["graph_id"] == "graph.test.prompt_migration"
    )
    assert graph["overview_mode"] == "summary"
    node = graph_detail["nodes"][0]
    metadata = node["metadata"]

    assert node["projection_id"] == "projection.taskgraph.graph.test.prompt.migration.world.review"
    assert "role_prompt" not in metadata
    assert "role_identity" not in metadata
    assert metadata["legacy_prompt_migration"]["migration_status"] == "migrated"
    assert metadata["legacy_prompt_migration"]["projection_id"] == node["projection_id"]

    projection_cards = SoulFacade(tmp_path).list_projection_cards()["cards"]
    projection = next(item for item in projection_cards if item["projection_id"] == node["projection_id"])
    assert projection["owner_system"] == "task_system"
    assert projection["projection_kind"] == "task_graph_node"
    assert projection["source_task_graph_refs"] == ["graph.test.prompt_migration"]
    assert "你是一名世界观审核员" in projection["projection_prompt"]


def test_task_graph_api_exposes_direct_runtime_spec_in_overview(tmp_path: Path) -> None:
    original = tasks_api.require_runtime
    tasks_api.require_runtime = lambda: _RuntimeStub(tmp_path)  # type: ignore[assignment]
    try:
        asyncio.run(
            tasks_api.upsert_task_system_task_graph(
                "graph.test.direct_spec",
                tasks_api.TaskGraphUpsertRequest(
                    graph_id="graph.test.direct_spec",
                    title="直接运行规范图",
                    domain_id="domain.story",
                    task_family="story",
                    graph_kind="multi_agent",
                    graph_contract_id="contract.story.graph",
                    runtime_policy={
                        "coordinator_agent_id": "agent:coordinator",
                        "default_execution_mode": "parallel",
                    },
                    nodes=[
                        {
                            "node_id": "draft",
                            "node_type": "agent",
                            "title": "起草",
                            "agent_id": "agent:writer",
                            "phase_id": "drafting",
                        },
                        {
                            "node_id": "review",
                            "node_type": "review_gate",
                            "title": "审核",
                            "agent_id": "agent:reviewer",
                            "review_gate_policy": {"is_review_gate": True},
                        },
                    ],
                    edges=[
                        {
                            "edge_id": "draft_review",
                            "source_node_id": "draft",
                            "target_node_id": "review",
                            "payload_contract_id": "contract.story.payload",
                        }
                    ],
                ),
            )
        )
        payload = asyncio.run(tasks_api.task_system_overview())
        runtime_spec = asyncio.run(tasks_api.compile_task_system_task_graph_runtime_spec("graph.test.direct_spec"))
    finally:
        tasks_api.require_runtime = original  # type: ignore[assignment]

    assert payload["task_graph_management"]["task_graph_specs"] == []
    spec = runtime_spec
    draft = next(item for item in spec["nodes"] if item["node_id"] == "draft")
    edge = spec["edges"][0]

    assert spec["diagnostics"]["source"] == "task_system.task_graph_definition_runtime_compiler"
    assert spec["diagnostics"]["graph_contract_id"] == "contract.story.graph"
    assert draft["execution_mode"] == "parallel"
    assert draft["phase_id"] == "drafting"
    assert edge["payload_contract_id"] == "contract.story.payload"
    assert runtime_spec["graph_id"] == "graph.test.direct_spec"
    assert runtime_spec["coordinator_agent_id"] == "agent:coordinator"
