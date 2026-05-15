from __future__ import annotations

from types import SimpleNamespace

from orchestration.runtime_loop.event_log import RuntimeEventLog
from orchestration.runtime_loop.langgraph_coordination_runtime import LangGraphCoordinationRuntime
from orchestration.runtime_loop.models import CoordinationRun, TaskRun
from orchestration.runtime_loop.stage_execution_request import TaskResultReadyEvent
from orchestration.runtime_loop.state_index import RuntimeStateIndex
from tasks import TaskContractRegistry
from tasks.flow_models import CoordinationTaskDefinition, SpecificTaskRecord, TaskCommunicationProtocol, TopologyTemplate
from tasks.task_graph_models import TaskGraphDefinition, TaskGraphEdgeDefinition, TaskGraphNodeDefinition
from orchestration.runtime_loop.continuation_policy import parse_stage_contracts


class _Trace:
    def __init__(self, traces):
        self.traces = traces

    def get_trace(self, task_run_id: str, *, include_payloads: bool = False, include_model_messages: bool = False):
        return self.traces.get(task_run_id)


def _task_graph_from_coordination(coordination: CoordinationTaskDefinition, *, protocol_id: str = "") -> TaskGraphDefinition:
    nodes = tuple(
        TaskGraphNodeDefinition(
            node_id=str(node.get("node_id") or ""),
            node_type=str(node.get("node_type") or "agent"),
            title=str(node.get("title") or node.get("node_id") or ""),
            task_id=str(node.get("task_id") or ""),
            agent_id=str(node.get("agent_id") or ""),
            runtime_lane=str(node.get("runtime_lane") or node.get("lane") or ""),
            work_posture=str(node.get("role") or ""),
            phase_id=str(node.get("phase_id") or ""),
            sequence_index=int(node.get("sequence_index") or 0),
            metadata={key: value for key, value in dict(node).items() if key not in {"node_id", "node_type", "title", "task_id", "agent_id", "runtime_lane", "lane", "role", "phase_id", "sequence_index"}},
        )
        for node in coordination.graph_nodes
    )
    edges = tuple(
        TaskGraphEdgeDefinition(
            edge_id=str(edge.get("edge_id") or edge.get("id") or ""),
            source_node_id=str(edge.get("source_node_id") or edge.get("from") or edge.get("source") or ""),
            target_node_id=str(edge.get("target_node_id") or edge.get("to") or edge.get("target") or ""),
            edge_type=str(edge.get("edge_type") or edge.get("mode") or "handoff"),
            payload_contract_id=str(edge.get("payload_contract_id") or edge.get("contract_id") or ""),
        )
        for edge in coordination.graph_edges
    )
    return TaskGraphDefinition(
        graph_id=coordination.graph_id,
        title=coordination.title,
        task_family=coordination.task_family,
        graph_kind="multi_agent",
        nodes=nodes,
        edges=edges,
        default_protocol_id=protocol_id,
        runtime_policy={"coordinator_agent_id": coordination.coordinator_agent_id},
        metadata=dict(coordination.metadata or {}),
        publish_state="published",
        enabled=True,
    )


class _Registry:
    def __init__(self) -> None:
        self.coordination = CoordinationTaskDefinition(
            graph_id="graph.test.bootstrap",
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

    def get_task_graph(self, graph_id: str):
        if graph_id != self.coordination.graph_id:
            return None
        return _task_graph_from_coordination(self.coordination, protocol_id=self.protocol.protocol_id)

    def derive_coordination_task_view_from_graph(self, graph):
        return self.coordination if graph.graph_id == self.coordination.graph_id else None

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
            task_contract_ref="task.dev.light_web_game",
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
        graph_ref="graph.test.bootstrap",
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
    assert result.stage_execution_request.runtime_assembly["authority"] == "orchestration.node_runtime_assembly"
    assert result.stage_execution_request.a2a_payload["message"]["metadata"]["runtime_assembly_ref"]
    scheduler_state = dict(dict(result.state["diagnostics"]).get("task_graph_scheduler_state") or {})
    assert scheduler_state["authority"] == "task_system.task_graph_scheduler_state"
    assert scheduler_state["mode"] == "active"
    updated = state_index.get_coordination_run("coordrun:test")
    assert updated is not None
    flow = dict(updated.diagnostics.get("coordination_flow") or {})
    assert flow["current_stage_id"] == "novel_bible"
    runtime_state = dict(updated.diagnostics.get("langgraph_runtime_state") or {})
    assert runtime_state["contract_manifest_ref"].startswith("contract-manifest:coordination:")
    assert "project_scope" in runtime_state["completed_nodes"]


class _DiamondRegistry:
    def __init__(self) -> None:
        self.tasks = (
            SpecificTaskRecord(
                task_id="task.test.a",
                task_title="A",
                task_family="test",
                task_mode="task_execution",
                input_contract_id="contract.user_request.basic",
                output_contract_id="contract.artifact_refs.bundle",
            ),
            SpecificTaskRecord(
                task_id="task.test.b",
                task_title="B",
                task_family="test",
                task_mode="task_execution",
                input_contract_id="contract.user_request.basic",
                output_contract_id="contract.artifact_refs.bundle",
            ),
            SpecificTaskRecord(
                task_id="task.test.c",
                task_title="C",
                task_family="test",
                task_mode="task_execution",
                input_contract_id="contract.user_request.basic",
                output_contract_id="contract.artifact_refs.bundle",
            ),
            SpecificTaskRecord(
                task_id="task.test.d",
                task_title="D",
                task_family="test",
                task_mode="task_execution",
                input_contract_id="contract.user_request.basic",
                output_contract_id="contract.agent_output.markdown",
            ),
        )
        self.coordination = CoordinationTaskDefinition(
            graph_id="graph.test.diamond",
            title="测试汇聚拓扑",
            coordination_mode="pipeline",
            coordinator_agent_id="agent:0",
            task_family="test",
            topology_template_id="topology.test.diamond",
            graph_nodes=(
                {"node_id": "a", "agent_id": "agent:0", "task_id": "task.test.a", "role": "coordinator", "runtime_lane": "task_dispatch"},
                {"node_id": "b", "agent_id": "agent:0", "task_id": "task.test.b", "role": "participant", "runtime_lane": "task_dispatch"},
                {"node_id": "c", "agent_id": "agent:0", "task_id": "task.test.c", "role": "participant", "runtime_lane": "task_dispatch"},
                {"node_id": "d", "agent_id": "agent:0", "task_id": "task.test.d", "role": "acceptance", "runtime_lane": "final_integration"},
            ),
            graph_edges=(
                {"edge_id": "a_b", "from": "a", "to": "b", "contract_id": "contract.artifact_refs.bundle"},
                {"edge_id": "a_c", "from": "a", "to": "c", "contract_id": "contract.artifact_refs.bundle"},
                {"edge_id": "b_d", "from": "b", "to": "d", "contract_id": "contract.artifact_refs.bundle"},
                {"edge_id": "c_d", "from": "c", "to": "d", "contract_id": "contract.artifact_refs.bundle"},
            ),
            metadata={
                "stage_contracts": [
                    {
                        "stage_id": "a",
                        "task_ref": "task.test.a",
                        "node_id": "a",
                        "output_mappings": [{"output_key": "a_ref", "required": True}],
                        "on_failure": "retry_once",
                        "retry_policy": {"retry_limit": 1},
                    },
                    {
                        "stage_id": "b",
                        "task_ref": "task.test.b",
                        "node_id": "b",
                        "required_inputs": ["a_ref"],
                        "input_bindings": [{"source": "stage_output", "output_key": "a_ref", "input_key": "a_ref", "required": True}],
                        "output_mappings": [{"output_key": "b_ref", "required": True}],
                    },
                    {
                        "stage_id": "c",
                        "task_ref": "task.test.c",
                        "node_id": "c",
                        "required_inputs": ["a_ref"],
                        "input_bindings": [{"source": "stage_output", "output_key": "a_ref", "input_key": "a_ref", "required": True}],
                        "output_mappings": [{"output_key": "c_ref", "required": True}],
                    },
                    {
                        "stage_id": "d",
                        "task_ref": "task.test.d",
                        "node_id": "d",
                        "required_inputs": ["b_ref", "c_ref"],
                        "input_bindings": [
                            {"source": "stage_output", "output_key": "b_ref", "input_key": "b_ref", "required": True},
                            {"source": "stage_output", "output_key": "c_ref", "input_key": "c_ref", "required": True},
                        ],
                    },
                ],
            },
        )
        self.topology = TopologyTemplate(
            template_id="topology.test.diamond",
            title="测试汇聚拓扑",
            nodes=self.coordination.graph_nodes,
            edges=self.coordination.graph_edges,
            enabled=True,
        )
        self.protocol = TaskCommunicationProtocol(
            protocol_id="protocol.test.diamond",
            title="官方 A2A 汇聚测试协议",
            message_types=("message/send", "message/stream", "task/status", "task/artifact"),
            payload_contracts=("contract.artifact_refs.bundle",),
            enabled=True,
        )

    def get_task_graph(self, graph_id: str):
        if graph_id != self.coordination.graph_id:
            return None
        return _task_graph_from_coordination(self.coordination, protocol_id=self.protocol.protocol_id)

    def derive_coordination_task_view_from_graph(self, graph):
        return self.coordination if graph.graph_id == self.coordination.graph_id else None

    def get_topology_template(self, template_id: str):
        return self.topology if template_id == self.topology.template_id else None

    def get_task_communication_protocol(self, protocol_id: str):
        return self.protocol if protocol_id == self.protocol.protocol_id else None

    def list_specific_task_records(self):
        return list(self.tasks)


def _diamond_runtime(tmp_path):
    registry = _DiamondRegistry()
    state_index = RuntimeStateIndex(tmp_path)
    event_log = RuntimeEventLog(tmp_path)
    runtime = LangGraphCoordinationRuntime(
        root_dir=tmp_path,
        state_index=state_index,
        event_log=event_log,
        task_flow_registry=registry,
        trace_reader=_Trace({}),
    )
    coordination_run = CoordinationRun(
        coordination_run_id="coordrun:diamond",
        task_run_id="taskrun:a",
        graph_ref="graph.test.diamond",
        coordinator_agent_id="agent:0",
        topology_template_id="topology.test.diamond",
        communication_protocol_id="protocol.test.diamond",
        status="running",
        diagnostics={"coordination_flow": {"current_stage_id": "a"}},
    )
    state_index.upsert_coordination_run(coordination_run)
    TaskContractRegistry(tmp_path)
    return runtime, state_index, coordination_run


def test_langgraph_coordination_runtime_routes_ready_nodes_before_join(tmp_path) -> None:
    runtime, state_index, coordination_run = _diamond_runtime(tmp_path)

    result_a = runtime.resume_from_task_result(
        coordination_run=coordination_run,
        event=TaskResultReadyEvent(
            event_type="task_result_ready",
            coordination_run_id="coordrun:diamond",
            task_run_id="taskrun:a",
            stage_id="a",
            task_ref="task.test.a",
            task_result_ref="taskresult:a",
            artifact_refs=("ref:a",),
            accepted=True,
        ),
    )
    assert result_a.stage_execution_request is not None
    assert result_a.stage_execution_request.stage_id == "b"
    assert result_a.state["running_nodes"] == ["b"]
    assert result_a.state["ready_nodes"] == ["c"]
    assert result_a.state["blocked_nodes"] == ["d"]

    result_b = runtime.resume_from_task_result(
        coordination_run=coordination_run,
        event=TaskResultReadyEvent(
            event_type="task_result_ready",
            coordination_run_id="coordrun:diamond",
            task_run_id="taskrun:b",
            stage_id="b",
            task_ref="task.test.b",
            task_result_ref="taskresult:b",
            artifact_refs=("ref:b",),
            accepted=True,
        ),
    )
    assert result_b.stage_execution_request is not None
    assert result_b.stage_execution_request.stage_id == "c"
    assert "d" in result_b.state["blocked_nodes"]

    result_c = runtime.resume_from_task_result(
        coordination_run=coordination_run,
        event=TaskResultReadyEvent(
            event_type="task_result_ready",
            coordination_run_id="coordrun:diamond",
            task_run_id="taskrun:c",
            stage_id="c",
            task_ref="task.test.c",
            task_result_ref="taskresult:c",
            artifact_refs=("ref:c",),
            accepted=True,
        ),
    )
    assert result_c.stage_execution_request is not None
    assert result_c.stage_execution_request.stage_id == "d"
    assert result_c.stage_execution_request.runtime_assembly["node_id"] == "d"
    assert result_c.stage_execution_request.a2a_payload["message"]["metadata"]["contract_manifest_ref"]
    assert len(result_c.stage_execution_request.a2a_payload["message"]["parts"][-1]["data"]["handoff_packets"]) == 2

    updated = state_index.get_coordination_run("coordrun:diamond")
    assert updated is not None
    runtime_state = dict(updated.diagnostics.get("langgraph_runtime_state") or {})
    assert runtime_state["completed_nodes"] == ["a", "b", "c"]
    assert runtime_state["running_nodes"] == ["d"]


class _SequencedRegistry:
    def __init__(self) -> None:
        self.tasks = (
            SpecificTaskRecord(task_id="task.test.a", task_title="A", task_family="test", task_mode="task_execution"),
            SpecificTaskRecord(task_id="task.test.b", task_title="B", task_family="test", task_mode="task_execution"),
            SpecificTaskRecord(task_id="task.test.c", task_title="C", task_family="test", task_mode="task_execution"),
        )
        self.coordination = CoordinationTaskDefinition(
            graph_id="graph.test.sequence",
            title="测试显式时序",
            coordination_mode="pipeline",
            coordinator_agent_id="agent:0",
            task_family="test",
            topology_template_id="topology.test.sequence",
            graph_nodes=(
                {"node_id": "a", "agent_id": "agent:0", "task_id": "task.test.a", "role": "coordinator", "phase_id": "phase.write", "sequence_index": 1},
                {"node_id": "b", "agent_id": "agent:0", "task_id": "task.test.b", "role": "participant", "phase_id": "phase.write", "sequence_index": 2},
                {"node_id": "c", "agent_id": "agent:0", "task_id": "task.test.c", "role": "participant", "phase_id": "phase.write", "sequence_index": 3},
            ),
            graph_edges=(),
            metadata={
                "stage_contracts": [
                    {"stage_id": "a", "task_ref": "task.test.a", "node_id": "a"},
                    {"stage_id": "b", "task_ref": "task.test.b", "node_id": "b"},
                    {"stage_id": "c", "task_ref": "task.test.c", "node_id": "c"},
                ],
            },
        )
        self.topology = TopologyTemplate(
            template_id="topology.test.sequence",
            title="测试显式时序",
            nodes=self.coordination.graph_nodes,
            edges=self.coordination.graph_edges,
            enabled=True,
        )
        self.protocol = TaskCommunicationProtocol(
            protocol_id="protocol.test.sequence",
            title="官方 A2A 时序测试协议",
            message_types=("message/send",),
            enabled=True,
        )

    def get_task_graph(self, graph_id: str):
        if graph_id != self.coordination.graph_id:
            return None
        return _task_graph_from_coordination(self.coordination, protocol_id=self.protocol.protocol_id)

    def derive_coordination_task_view_from_graph(self, graph):
        return self.coordination if graph.graph_id == self.coordination.graph_id else None

    def get_topology_template(self, template_id: str):
        return self.topology if template_id == self.topology.template_id else None

    def get_task_communication_protocol(self, protocol_id: str):
        return self.protocol if protocol_id == self.protocol.protocol_id else None

    def list_specific_task_records(self):
        return list(self.tasks)


def test_langgraph_coordination_runtime_uses_scheduler_sequence_gate(tmp_path) -> None:
    registry = _SequencedRegistry()
    state_index = RuntimeStateIndex(tmp_path)
    event_log = RuntimeEventLog(tmp_path)
    runtime = LangGraphCoordinationRuntime(
        root_dir=tmp_path,
        state_index=state_index,
        event_log=event_log,
        task_flow_registry=registry,
        trace_reader=_Trace({}),
    )
    coordination_run = CoordinationRun(
        coordination_run_id="coordrun:sequence",
        task_run_id="taskrun:sequence",
        graph_ref="graph.test.sequence",
        coordinator_agent_id="agent:0",
        topology_template_id="topology.test.sequence",
        communication_protocol_id="protocol.test.sequence",
        status="running",
        diagnostics={"coordination_flow": {"current_stage_id": "a"}},
    )
    state_index.upsert_coordination_run(coordination_run)

    result = runtime.resume_from_task_result(
        coordination_run=coordination_run,
        event=TaskResultReadyEvent(
            event_type="task_result_ready",
            coordination_run_id="coordrun:sequence",
            task_run_id="taskrun:a",
            stage_id="a",
            task_ref="task.test.a",
            task_result_ref="taskresult:a",
            accepted=True,
        ),
    )

    assert result.stage_execution_request is not None
    assert result.stage_execution_request.stage_id == "b"
    assert result.state["running_nodes"] == ["b"]
    assert result.state["ready_nodes"] == []
    assert result.state["blocked_nodes"] == ["c"]
    scheduler_state = dict(dict(result.state["diagnostics"]).get("task_graph_scheduler_state") or {})
    c_state = next(item for item in scheduler_state["node_states"] if item["node_id"] == "c")
    assert "sequence_wait:2" in c_state["blocked_reasons"]


def test_langgraph_coordination_runtime_blocks_when_required_input_missing(tmp_path) -> None:
    runtime, _, coordination_run = _diamond_runtime(tmp_path)

    result = runtime.resume_from_task_result(
        coordination_run=coordination_run,
        event=TaskResultReadyEvent(
            event_type="task_result_ready",
            coordination_run_id="coordrun:diamond",
            task_run_id="taskrun:a",
            stage_id="a",
            task_ref="task.test.a",
            task_result_ref="taskresult:a",
            artifact_refs=(),
            accepted=True,
        ),
    )

    assert result.stage_execution_request is None
    assert result.state["terminal_status"] == "blocked"
    assert result.state["missing_required_inputs"] == ["a_ref"]
    assert result.state["contract_status"]["node_status"]["b"]["missing_required_inputs"] == ["a_ref"]


def test_langgraph_coordination_runtime_retries_failed_stage_when_policy_allows(tmp_path) -> None:
    runtime, _, coordination_run = _diamond_runtime(tmp_path)

    result = runtime.resume_from_task_result(
        coordination_run=coordination_run,
        event=TaskResultReadyEvent(
            event_type="task_result_ready",
            coordination_run_id="coordrun:diamond",
            task_run_id="taskrun:a",
            stage_id="a",
            task_ref="task.test.a",
            task_result_ref="taskresult:a",
            accepted=False,
        ),
    )

    assert result.stage_execution_request is not None
    assert result.stage_execution_request.stage_id == "a"
    assert result.state["retry_counts"]["a"] == 1
    assert result.state["running_nodes"] == ["a"]


def test_langgraph_coordination_runtime_enters_human_gate_when_policy_requires(tmp_path) -> None:
    runtime, state_index, coordination_run = _diamond_runtime(tmp_path)
    stage_contracts = runtime.task_flow_registry.coordination.metadata["stage_contracts"]
    stage_contracts[0]["on_failure"] = "human_gate"
    stage_contracts[0]["retry_policy"] = {"retry_limit": 0}

    result = runtime.resume_from_task_result(
        coordination_run=coordination_run,
        event=TaskResultReadyEvent(
            event_type="task_result_ready",
            coordination_run_id="coordrun:diamond",
            task_run_id="taskrun:a",
            stage_id="a",
            task_ref="task.test.a",
            task_result_ref="taskresult:a",
            accepted=False,
        ),
    )

    assert result.stage_execution_request is None
    assert result.state["terminal_status"] == "waiting_for_human"
    assert result.state["waiting_nodes"] == ["a"]
    assert result.state["contract_status"]["node_status"]["a"]["status"] == "human_gate"
    updated = state_index.get_coordination_run("coordrun:diamond")
    assert updated is not None
    runtime_state = dict(updated.diagnostics.get("langgraph_runtime_state") or {})
    assert runtime_state["human_gate"]["status"] == "waiting"


def test_langgraph_coordination_runtime_human_gate_approve_routes_next(tmp_path) -> None:
    runtime, _, coordination_run = _diamond_runtime(tmp_path)
    stage_contracts = runtime.task_flow_registry.coordination.metadata["stage_contracts"]
    stage_contracts[0]["on_failure"] = "human_gate"
    stage_contracts[0]["retry_policy"] = {"retry_limit": 0}
    runtime.resume_from_task_result(
        coordination_run=coordination_run,
        event=TaskResultReadyEvent(
            event_type="task_result_ready",
            coordination_run_id="coordrun:diamond",
            task_run_id="taskrun:a",
            stage_id="a",
            task_ref="task.test.a",
            task_result_ref="taskresult:a",
            artifact_refs=("ref:a",),
            accepted=False,
        ),
    )

    result = runtime.resume_human_gate(
        coordination_run_id="coordrun:diamond",
        resume_payload={"decision": "approve", "task_result_ref": "taskresult:a:approved", "artifact_refs": ["ref:a"]},
    )

    assert result.stage_execution_request is not None
    assert result.stage_execution_request.stage_id in {"b", "c"}
    assert result.state["contract_status"]["node_status"]["a"]["status"] == "satisfied"
    assert result.state["completed_nodes"] == ["a"]


def test_langgraph_coordination_runtime_human_gate_retry_routes_same_stage(tmp_path) -> None:
    runtime, _, coordination_run = _diamond_runtime(tmp_path)
    stage_contracts = runtime.task_flow_registry.coordination.metadata["stage_contracts"]
    stage_contracts[0]["on_failure"] = "human_gate"
    stage_contracts[0]["retry_policy"] = {"retry_limit": 0}
    runtime.resume_from_task_result(
        coordination_run=coordination_run,
        event=TaskResultReadyEvent(
            event_type="task_result_ready",
            coordination_run_id="coordrun:diamond",
            task_run_id="taskrun:a",
            stage_id="a",
            task_ref="task.test.a",
            task_result_ref="taskresult:a",
            accepted=False,
        ),
    )

    result = runtime.resume_human_gate(
        coordination_run_id="coordrun:diamond",
        resume_payload={"decision": "retry"},
    )

    assert result.stage_execution_request is not None
    assert result.stage_execution_request.stage_id == "a"
    assert result.state["retry_counts"]["a"] == 1
    assert result.state["contract_status"]["node_status"]["a"]["status"] == "pending_retry"


def test_langgraph_coordination_runtime_human_gate_reject_fails_closed(tmp_path) -> None:
    runtime, _, coordination_run = _diamond_runtime(tmp_path)
    stage_contracts = runtime.task_flow_registry.coordination.metadata["stage_contracts"]
    stage_contracts[0]["on_failure"] = "human_gate"
    stage_contracts[0]["retry_policy"] = {"retry_limit": 0}
    runtime.resume_from_task_result(
        coordination_run=coordination_run,
        event=TaskResultReadyEvent(
            event_type="task_result_ready",
            coordination_run_id="coordrun:diamond",
            task_run_id="taskrun:a",
            stage_id="a",
            task_ref="task.test.a",
            task_result_ref="taskresult:a",
            accepted=False,
        ),
    )

    result = runtime.resume_human_gate(
        coordination_run_id="coordrun:diamond",
        resume_payload={"decision": "reject"},
    )

    assert result.stage_execution_request is None
    assert result.state["terminal_status"] == "failed"
    assert result.state["failed_nodes"] == ["a"]
    assert result.state["contract_status"]["node_status"]["a"]["status"] == "failed"


def test_parse_stage_contracts_derives_from_graph_nodes_when_metadata_is_missing() -> None:
    coordination_task = CoordinationTaskDefinition(
        graph_id="graph.test.derived_contracts",
        title="测试派生契约",
        coordination_mode="pipeline",
        coordinator_agent_id="agent:0",
        task_family="test",
        topology_template_id="topology.test.derived_contracts",
        graph_nodes=(
            {
                "node_id": "a",
                "agent_id": "agent:a",
                "task_id": "task.test.a",
                "output_contract_id": "contract.test.a",
            },
            {
                "node_id": "b",
                "agent_id": "agent:b",
                "task_id": "task.test.b",
                "input_contract_id": "contract.test.a",
                "output_contract_id": "contract.test.b",
            },
        ),
        graph_edges=(
            {
                "edge_id": "a_b",
                "from": "a",
                "to": "b",
                "payload_contract_id": "contract.test.a",
            },
        ),
    )

    contracts = parse_stage_contracts(coordination_task=coordination_task, topology_nodes=list(coordination_task.graph_nodes), topology_edges=list(coordination_task.graph_edges))

    assert [contract.stage_id for contract in contracts] == ["a", "b"]
    assert contracts[1].required_inputs == ("contract.test.a:artifact_refs",)
    assert contracts[1].input_bindings[0]["source_stage_id"] == "a"
    assert contracts[1].output_mappings[0]["output_key"] == "contract.test.b:artifact_refs"
