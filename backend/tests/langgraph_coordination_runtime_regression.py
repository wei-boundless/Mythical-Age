from __future__ import annotations

from types import SimpleNamespace

from orchestration.runtime_loop.event_log import RuntimeEventLog
from orchestration.runtime_loop.langgraph_coordination_runtime import LangGraphCoordinationRuntime
from orchestration.runtime_loop.models import CoordinationRun, TaskRun
from orchestration.runtime_loop.stage_execution_request import TaskResultReadyEvent
from orchestration.runtime_loop.state_index import RuntimeStateIndex
from tasks.flow_registry import TaskFlowRegistry


class _Trace:
    def __init__(self, traces):
        self.traces = traces

    def get_trace(self, task_run_id: str, *, include_payloads: bool = False, include_model_messages: bool = False):
        return self.traces.get(task_run_id)


def test_langgraph_coordination_runtime_advances_by_stage_contract(tmp_path) -> None:
    registry = TaskFlowRegistry(tmp_path / "backend")
    state_index = RuntimeStateIndex(tmp_path)
    event_log = RuntimeEventLog(tmp_path)
    state_index.upsert_task_run(
        TaskRun(
            task_run_id="taskrun:project",
            session_id="session",
            task_id="taskinst:project",
            task_contract_ref="task.writing.longform_novel_project",
            status="completed",
            updated_at=10,
        )
    )
    trace = _Trace({"taskrun:project": {"task_result": {"output_refs": ["ref:project_spec"]}}})
    runtime = LangGraphCoordinationRuntime(
        root_dir=tmp_path,
        state_index=state_index,
        event_log=event_log,
        task_flow_registry=registry,
        trace_reader=trace,
    )
    coordination_run = CoordinationRun(
        coordination_run_id="coordrun:test",
        task_run_id="taskrun:project",
        coordination_task_ref="coord.writing.longform_project_bootstrap",
        coordinator_agent_id="agent:20",
        topology_template_id="topology.writing.longform_project_bootstrap",
        communication_protocol_id="protocol.writing.longform_project_bootstrap",
        status="running",
        diagnostics={
            "coordination_flow": {
                "current_stage_id": "project_scope",
                "stages": [
                    {"stage_id": "project_scope", "status": "running", "task_ref": "task.writing.longform_novel_project"},
                    {"stage_id": "novel_bible", "status": "pending", "task_ref": "task.writing.novel_bible_build"},
                ],
            }
        },
    )
    state_index.upsert_coordination_run(coordination_run)

    result = runtime.resume_from_task_result(
        coordination_run=coordination_run,
        event=TaskResultReadyEvent(
            event_type="task_result_ready",
            coordination_run_id="coordrun:test",
            task_run_id="taskrun:project",
            stage_id="project_scope",
            task_ref="task.writing.longform_novel_project",
            task_result_ref="taskresult:project",
            artifact_refs=("ref:project_spec",),
            accepted=True,
        ),
        inherited_inputs={},
    )

    assert result.stage_execution_request is not None
    assert result.stage_execution_request.stage_id == "novel_bible"
    assert result.stage_execution_request.task_ref == "task.writing.novel_bible_build"
    assert result.stage_execution_request.explicit_inputs["project_spec_ref"] == "ref:project_spec"
    updated = state_index.get_coordination_run("coordrun:test")
    assert updated is not None
    flow = dict(updated.diagnostics.get("coordination_flow") or {})
    assert flow["current_stage_id"] == "novel_bible"
