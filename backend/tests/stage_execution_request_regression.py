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
