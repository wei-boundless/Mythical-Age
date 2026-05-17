from __future__ import annotations

from orchestration.runtime_loop.stage_execution_request import StageExecutionRequest


def test_stage_execution_request_builds_stable_boundary_payload() -> None:
    request = StageExecutionRequest(
        request_id="",
        coordination_run_id="coordrun:test",
        thread_id="",
        root_task_run_id="taskrun:root",
        stage_id="volume_planning",
        node_id="volume_planning",
        task_ref="task.writing.volume_planning",
        explicit_inputs={"novel_bible_ref": "ref:bible"},
    )
    same = StageExecutionRequest(
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
    assert request.message == "继续执行协调任务阶段：volume_planning。"
    assert "长篇小说持续交付" not in request.message
    assert request.to_dict()["explicit_inputs"]["novel_bible_ref"] == "ref:bible"


def test_stage_execution_request_uses_dispatch_context_for_retry_safe_identity() -> None:
    first = StageExecutionRequest(
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
    second = StageExecutionRequest(
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
    restored = StageExecutionRequest.from_dict(first.to_dict())
    assert restored.dispatch_context["dispatch_event_id"] == "tlevent:test:001"
    assert restored.artifact_context_packet["artifact_refs"] == ["artifact:a.md"]
