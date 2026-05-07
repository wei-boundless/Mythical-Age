from __future__ import annotations

from types import SimpleNamespace

from orchestration.runtime_loop.event_log import RuntimeEventLog
from orchestration.runtime_loop.langgraph_coordination_runtime import LangGraphCoordinationRuntime
from orchestration.runtime_loop.models import CoordinationRun, TaskRun
from orchestration.runtime_loop.stage_execution_request import TaskResultReadyEvent
from orchestration.runtime_loop.state_index import RuntimeStateIndex
from tasks.flow_models import CoordinationTaskDefinition, TaskCommunicationProtocol, TopologyTemplate


class _Trace:
    def __init__(self, traces):
        self.traces = traces

    def get_trace(self, task_run_id: str, *, include_payloads: bool = False, include_model_messages: bool = False):
        return self.traces.get(task_run_id)


class _Registry:
    def __init__(self) -> None:
        self.coordination = CoordinationTaskDefinition(
            coordination_task_id="coord.test.bootstrap",
            title="测试协调任务",
            coordination_mode="pipeline",
            coordinator_agent_id="agent:0",
            task_family="test",
            topology_template_id="topology.test.bootstrap",
            subtask_refs=("task.test.project", "task.test.novel_bible"),
            graph_nodes=(
                {"node_id": "project_scope", "agent_id": "agent:0", "task_id": "task.test.project", "role": "coordinator"},
                {"node_id": "novel_bible", "agent_id": "agent:1", "task_id": "task.test.novel_bible", "role": "writer"},
            ),
            graph_edges=({"from": "project_scope", "to": "novel_bible", "mode": "structured_handoff"},),
            metadata={
                "stage_sequence": [
                    {"stage_id": "project_scope", "task_ref": "task.test.project"},
                    {"stage_id": "novel_bible", "task_ref": "task.test.novel_bible"},
                ],
                "stage_contracts": [
                    {
                        "stage_id": "project_scope",
                        "task_ref": "task.test.project",
                        "node_id": "project_scope",
                        "output_mappings": [{"output_key": "project_spec_ref", "required": True}],
                    },
                    {
                        "stage_id": "novel_bible",
                        "task_ref": "task.test.novel_bible",
                        "node_id": "novel_bible",
                        "required_inputs": ["project_spec_ref"],
                        "input_bindings": [
                            {
                                "source": "stage_output",
                                "source_stage_id": "project_scope",
                                "output_key": "project_spec_ref",
                                "input_key": "project_spec_ref",
                                "required": True,
                            }
                        ],
                    },
                ],
            },
        )
        self.topology = TopologyTemplate(
            template_id="topology.test.bootstrap",
            title="测试拓扑",
            nodes=self.coordination.graph_nodes,
            edges=self.coordination.graph_edges,
            enabled=True,
        )
        self.protocol = TaskCommunicationProtocol(
            protocol_id="protocol.test.a2a",
            title="官方 A2A 测试协议",
            message_types=("message/send", "message/stream", "task/status", "task/artifact"),
            payload_contracts=("contract.payload.project_spec",),
            enabled=True,
            metadata={"a2a_protocol": "official", "protocol_locked": True},
        )

    def get_coordination_task(self, coordination_task_id: str):
        return self.coordination if coordination_task_id == self.coordination.coordination_task_id else None

    def get_topology_template(self, template_id: str):
        return self.topology if template_id == self.topology.template_id else None

    def get_task_communication_protocol(self, protocol_id: str):
        return self.protocol if protocol_id == self.protocol.protocol_id else None

    def list_specific_task_records(self):
        return []


def test_langgraph_coordination_runtime_advances_by_stage_contract(tmp_path) -> None:
    registry = _Registry()
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
        coordination_task_ref="coord.test.bootstrap",
        coordinator_agent_id="agent:20",
        topology_template_id="topology.test.bootstrap",
        communication_protocol_id="protocol.test.a2a",
        status="running",
        diagnostics={
            "coordination_flow": {
                "current_stage_id": "project_scope",
                "stages": [
                    {"stage_id": "project_scope", "status": "running", "task_ref": "task.test.project"},
                    {"stage_id": "novel_bible", "status": "pending", "task_ref": "task.test.novel_bible"},
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
            task_ref="task.test.project",
            task_result_ref="taskresult:project",
            artifact_refs=("ref:project_spec",),
            accepted=True,
        ),
        inherited_inputs={},
    )

    assert result.stage_execution_request is not None
    assert result.stage_execution_request.stage_id == "novel_bible"
    assert result.stage_execution_request.task_ref == "task.test.novel_bible"
    assert result.stage_execution_request.explicit_inputs["project_spec_ref"] == "ref:project_spec"
    assert result.stage_execution_request.a2a_payload["protocol_version"] == "0.3.0"
    assert result.stage_execution_request.a2a_payload["transport"] == "JSONRPC"
    assert result.stage_execution_request.a2a_payload["message"]["kind"] == "message"
    assert result.stage_execution_request.a2a_payload["message"]["metadata"]["target_stage_id"] == "novel_bible"
    continuation = result.continuation_payload(session_id="session")
    assert continuation["a2a_payload"]["message"]["metadata"]["target_task_ref"] == "task.test.novel_bible"
    assert continuation["current_turn_context"]["a2a_payload"]["message"]["metadata"]["target_stage_id"] == "novel_bible"
    updated = state_index.get_coordination_run("coordrun:test")
    assert updated is not None
    flow = dict(updated.diagnostics.get("coordination_flow") or {})
    assert flow["current_stage_id"] == "novel_bible"
