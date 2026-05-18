from __future__ import annotations

from orchestration.runtime_loop.langgraph_coordination_runtime import LangGraphCoordinationRuntimeResult
from orchestration.runtime_loop.node_execution_request import NodeExecutionRequest


def test_node_execution_request_builds_stable_boundary_payload() -> None:
    request = NodeExecutionRequest(
        request_id="",
        coordination_run_id="coordrun:test",
        thread_id="",
        root_task_run_id="taskrun:root",
        stage_id="volume_planning",
        node_id="volume_planning",
        task_ref="task.writing.volume_planning",
        executor_type="human",
        executor_binding={"selected_executor": "human"},
        explicit_inputs={"novel_bible_ref": "ref:bible"},
        standard_input_package={"package_id": "nodeinput:test", "node_id": "volume_planning"},
        human_work_packet={"work_packet_id": "humanwork:test", "package_id": "nodeinput:test"},
    )
    same = NodeExecutionRequest(
        request_id="",
        coordination_run_id="coordrun:test",
        thread_id="",
        root_task_run_id="taskrun:root",
        stage_id="volume_planning",
        node_id="volume_planning",
        task_ref="task.writing.volume_planning",
        explicit_inputs={"novel_bible_ref": "ref:bible"},
    )

    assert request.thread_id == "coordrun:test"
    assert request.idempotency_key == same.idempotency_key
    assert request.message == "继续执行任务图节点：volume_planning。"
    assert "长篇小说持续交付" not in request.message
    assert request.to_dict()["authority"] == "task_graph.node_execution_request"
    assert request.to_dict()["explicit_inputs"]["novel_bible_ref"] == "ref:bible"
    assert request.to_dict()["executor_type"] == "human"
    assert request.to_dict()["standard_input_package"]["package_id"] == "nodeinput:test"
    assert request.to_dict()["human_work_packet"]["work_packet_id"] == "humanwork:test"


def test_node_execution_request_uses_dispatch_context_for_retry_safe_identity() -> None:
    first = NodeExecutionRequest(
        request_id="",
        coordination_run_id="coordrun:test",
        thread_id="",
        root_task_run_id="taskrun:root",
        stage_id="review_target",
        node_id="review_target",
        task_ref="task.test.review_target",
        explicit_inputs={"candidate_ref": "artifact:a.md"},
        dispatch_context={"dispatch_event_id": "tlevent:test:001", "clock_seq": 1, "scope_path": ["run", "phase.review"]},
        artifact_context_packet={"packet_id": "artctx:001", "artifact_refs": ["artifact:a.md"]},
    )
    second = NodeExecutionRequest(
        request_id="",
        coordination_run_id="coordrun:test",
        thread_id="",
        root_task_run_id="taskrun:root",
        stage_id="review_target",
        node_id="review_target",
        task_ref="task.test.review_target",
        explicit_inputs={"candidate_ref": "artifact:a.md"},
        dispatch_context={"dispatch_event_id": "tlevent:test:002", "clock_seq": 2, "scope_path": ["run", "phase.review", "retry[1]"]},
        artifact_context_packet={"packet_id": "artctx:002", "artifact_refs": ["artifact:a_v002.md"]},
    )

    assert first.idempotency_key != second.idempotency_key
    restored = NodeExecutionRequest.from_dict(first.to_dict())
    assert restored.dispatch_context["dispatch_event_id"] == "tlevent:test:001"
    assert restored.artifact_context_packet["artifact_refs"] == ["artifact:a.md"]


def test_human_executor_continuation_payload_does_not_dispatch_agent() -> None:
    request = NodeExecutionRequest(
        request_id="nodeexec:human",
        coordination_run_id="coordrun:test",
        thread_id="coordrun:test",
        root_task_run_id="taskrun:root",
        stage_id="world_review",
        node_id="world_review",
        task_ref="task.test.world_review",
        agent_id="agent:reviewer",
        executor_type="human",
        executor_binding={"selected_executor": "human"},
        explicit_inputs={"world_candidate_ref": "artifact:world.md"},
        human_work_packet={"work_packet_id": "humanwork:test", "title": "代替节点执行：世界观审核"},
    )

    payload = LangGraphCoordinationRuntimeResult(stage_execution_request=request).continuation_payload(session_id="session:test")

    assert payload["requires_human_executor"] is True
    assert payload["human_work_packet"]["work_packet_id"] == "humanwork:test"
    assert "next_task_ref" not in payload
    assert "message" not in payload
