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
            artifact_ref_policy=dict(edge.get("artifact_ref_policy") or {}),
            metadata=dict(edge.get("metadata") or {}),
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


class _WorkingMemoryRegistry:
    def __init__(self) -> None:
        self.tasks = (
            SpecificTaskRecord(
                task_id="task.test.source",
                task_title="Source",
                task_family="test",
                input_contract_id="contract.user_request.basic",
                output_contract_id="contract.agent_output.markdown",
            ),
            SpecificTaskRecord(
                task_id="task.test.target",
                task_title="Target",
                task_family="test",
                input_contract_id="contract.user_request.basic",
                output_contract_id="contract.agent_output.markdown",
            ),
        )
        self.coordination = CoordinationTaskDefinition(
            graph_id="graph.test.working_memory_runtime",
            title="工作记忆运行时测试",
            coordination_mode="pipeline",
            coordinator_agent_id="agent:0",
            task_family="test",
            topology_template_id="topology.test.working_memory_runtime",
            graph_nodes=(
                {"node_id": "source", "agent_id": "agent:0", "task_id": "task.test.source", "role": "writer"},
                {"node_id": "target", "agent_id": "agent:0", "task_id": "task.test.target", "role": "writer"},
            ),
            graph_edges=({"edge_id": "source_target", "from": "source", "to": "target", "mode": "structured_handoff"},),
            metadata={
                "stage_contracts": [
                    {"stage_id": "source", "task_ref": "task.test.source", "node_id": "source"},
                    {"stage_id": "target", "task_ref": "task.test.target", "node_id": "target"},
                ],
            },
        )
        self.topology = TopologyTemplate(
            template_id="topology.test.working_memory_runtime",
            title="工作记忆运行时拓扑",
            nodes=self.coordination.graph_nodes,
            edges=self.coordination.graph_edges,
            enabled=True,
        )
        self.protocol = TaskCommunicationProtocol(
            protocol_id="protocol.test.working_memory_runtime",
            title="工作记忆 A2A 测试协议",
            message_types=("message/send",),
            payload_contracts=("contract.agent_output.markdown",),
            enabled=True,
        )

    def get_task_graph(self, graph_id: str):
        if graph_id != self.coordination.graph_id:
            return None
        return TaskGraphDefinition(
            graph_id=self.coordination.graph_id,
            title=self.coordination.title,
            task_family=self.coordination.task_family,
            graph_kind="multi_agent",
            nodes=(
                TaskGraphNodeDefinition(
                    node_id="source",
                    node_type="agent",
                    title="Source",
                    task_id="task.test.source",
                    agent_id="agent:0",
                    work_posture="writer",
                    memory_writeback_policy={
                        "writable_kinds": ["approved_world"],
                        "writable_scopes": ["graph_scope"],
                        "default_status": "accepted",
                        "default_visibility": "shared_in_graph",
                    },
                ),
                TaskGraphNodeDefinition(
                    node_id="target",
                    node_type="agent",
                    title="Target",
                    task_id="task.test.target",
                    agent_id="agent:0",
                    work_posture="writer",
                    memory_read_policy={
                        "readable_kinds": ["approved_world"],
                        "readable_scopes": ["graph_scope"],
                        "max_items": 3,
                    },
                ),
            ),
            edges=(
                TaskGraphEdgeDefinition(
                    edge_id="source_target",
                    source_node_id="source",
                    target_node_id="target",
                    edge_type="structured_handoff",
                    working_memory_handoff_policy={"carry_kinds": ["approved_world"], "carry_scopes": ["graph_scope"]},
                ),
            ),
            default_protocol_id=self.protocol.protocol_id,
            working_memory_policy={"memory_sharing_policy": "explicit_graph_scope"},
            runtime_policy={"coordinator_agent_id": self.coordination.coordinator_agent_id},
            publish_state="published",
            enabled=True,
        )

    def derive_coordination_task_view_from_graph(self, graph):
        return self.coordination if graph.graph_id == self.coordination.graph_id else None

    def get_topology_template(self, template_id: str):
        return self.topology if template_id == self.topology.template_id else None

    def get_task_communication_protocol(self, protocol_id: str):
        return self.protocol if protocol_id == self.protocol.protocol_id else None

    def list_specific_task_records(self):
        return list(self.tasks)


class _FormalMemoryRegistry:
    def __init__(self) -> None:
        self.tasks = (
            SpecificTaskRecord(
                task_id="task.test.world_author",
                task_title="World Author",
                task_family="test",
                input_contract_id="contract.user_request.basic",
                output_contract_id="contract.agent_output.markdown",
            ),
            SpecificTaskRecord(
                task_id="task.test.memory_repo",
                task_title="Memory Repo",
                task_family="test",
                input_contract_id="contract.user_request.basic",
                output_contract_id="contract.agent_output.markdown",
            ),
            SpecificTaskRecord(
                task_id="task.test.world_review",
                task_title="World Review",
                task_family="test",
                input_contract_id="contract.user_request.basic",
                output_contract_id="contract.agent_output.markdown",
            ),
        )
        self.coordination = CoordinationTaskDefinition(
            graph_id="graph.test.formal_memory_runtime",
            title="正式记忆库运行时测试",
            coordination_mode="pipeline",
            coordinator_agent_id="agent:0",
            task_family="test",
            topology_template_id="topology.test.formal_memory_runtime",
            graph_nodes=(
                {"node_id": "world_author", "agent_id": "agent:0", "task_id": "task.test.world_author", "role": "writer"},
                {"node_id": "world_review", "agent_id": "agent:0", "task_id": "task.test.world_review", "role": "reviewer"},
                {
                    "node_id": "memory.world",
                    "node_type": "memory_repository",
                    "agent_id": "agent:0",
                    "task_id": "task.test.memory_repo",
                    "role": "resource",
                    "metadata": {
                        "memory_repository": {
                            "repository_id": "memory.world",
                            "collections": [
                                {"collection_id": "world", "record_kinds": ["world_bible"]},
                            ],
                        }
                    },
                },
            ),
            graph_edges=(
                {
                    "edge_id": "edge.world_author.world_review",
                    "from": "world_author",
                    "to": "world_review",
                    "mode": "structured_handoff",
                },
                {
                    "edge_id": "edge.world_author.memory.world",
                    "from": "world_author",
                    "to": "memory.world",
                    "mode": "memory_write_candidate",
                    "metadata": {
                        "collection": "world",
                        "record_key": "world_bible.current",
                        "record_kind": "world_bible",
                        "source_output_key": "world_candidate",
                    },
                },
                {
                    "edge_id": "edge.world_review.memory.world",
                    "from": "world_review",
                    "to": "memory.world",
                    "mode": "memory_commit",
                    "metadata": {
                        "collection": "world",
                        "record_key": "world_bible.current",
                        "record_kind": "world_bible",
                        "candidate_ref_key": "reviewed_candidate_ref",
                        "verdict_key": "verdict",
                        "required_verdict": "pass",
                        "receipt_policy": {"visible_after": "next_clock"},
                    },
                },
            ),
            metadata={
                "stage_contracts": [
                    {
                        "stage_id": "world_author",
                        "task_ref": "task.test.world_author",
                        "node_id": "world_author",
                    },
                    {
                        "stage_id": "world_review",
                        "task_ref": "task.test.world_review",
                        "node_id": "world_review",
                    },
                    {
                        "stage_id": "memory.world",
                        "task_ref": "task.test.memory_repo",
                        "node_id": "memory.world",
                    },
                ],
            },
        )
        self.topology = TopologyTemplate(
            template_id="topology.test.formal_memory_runtime",
            title="正式记忆库拓扑",
            nodes=self.coordination.graph_nodes,
            edges=self.coordination.graph_edges,
            enabled=True,
        )
        self.protocol = TaskCommunicationProtocol(
            protocol_id="protocol.test.formal_memory_runtime",
            title="正式记忆库 A2A 测试协议",
            message_types=("message/send",),
            payload_contracts=("contract.agent_output.markdown",),
            enabled=True,
        )

    def get_task_graph(self, graph_id: str):
        if graph_id != self.coordination.graph_id:
            return None
        return TaskGraphDefinition(
            graph_id=self.coordination.graph_id,
            title=self.coordination.title,
            task_family=self.coordination.task_family,
            graph_kind="multi_agent",
            nodes=(
                TaskGraphNodeDefinition(
                    node_id="world_author",
                    node_type="agent",
                    title="World Author",
                    task_id="task.test.world_author",
                    agent_id="agent:0",
                    work_posture="writer",
                    memory_writeback_policy={
                        "writable_kinds": ["world_bible"],
                        "writable_scopes": ["graph_scope"],
                        "default_status": "draft",
                        "default_visibility": "shared_in_graph",
                    },
                ),
                TaskGraphNodeDefinition(
                    node_id="world_review",
                    node_type="agent",
                    title="World Review",
                    task_id="task.test.world_review",
                    agent_id="agent:0",
                    work_posture="reviewer",
                    review_gate_policy={"commit_working_memory": True},
                ),
                TaskGraphNodeDefinition(
                    node_id="memory.world",
                    node_type="memory_repository",
                    title="World Memory",
                    task_id="task.test.memory_repo",
                    agent_id="agent:0",
                    work_posture="resource",
                    metadata={
                        "memory_repository": {
                            "repository_id": "memory.world",
                            "collections": [
                                {"collection_id": "world", "record_kinds": ["world_bible"]},
                            ],
                        }
                    },
                ),
            ),
            edges=(
                TaskGraphEdgeDefinition(
                    edge_id="edge.world_author.world_review",
                    source_node_id="world_author",
                    target_node_id="world_review",
                    edge_type="structured_handoff",
                ),
                TaskGraphEdgeDefinition(
                    edge_id="edge.world_author.memory.world",
                    source_node_id="world_author",
                    target_node_id="memory.world",
                    edge_type="memory_write_candidate",
                    metadata={
                        "collection": "world",
                        "record_key": "world_bible.current",
                        "record_kind": "world_bible",
                        "source_output_key": "world_candidate",
                    },
                ),
                TaskGraphEdgeDefinition(
                    edge_id="edge.world_review.memory.world",
                    source_node_id="world_review",
                    target_node_id="memory.world",
                    edge_type="memory_commit",
                    metadata={
                        "collection": "world",
                        "record_key": "world_bible.current",
                        "record_kind": "world_bible",
                        "candidate_ref_key": "reviewed_candidate_ref",
                        "verdict_key": "verdict",
                        "required_verdict": "pass",
                        "receipt_policy": {"visible_after": "next_clock"},
                    },
                ),
            ),
            default_protocol_id=self.protocol.protocol_id,
            runtime_policy={"coordinator_agent_id": self.coordination.coordinator_agent_id},
            publish_state="published",
            enabled=True,
        )

    def derive_coordination_task_view_from_graph(self, graph):
        return self.coordination if graph.graph_id == self.coordination.graph_id else None

    def get_topology_template(self, template_id: str):
        return self.topology if template_id == self.topology.template_id else None

    def get_task_communication_protocol(self, protocol_id: str):
        return self.protocol if protocol_id == self.protocol.protocol_id else None

    def list_specific_task_records(self):
        return list(self.tasks)


class _ArtifactContextRegistry:
    def __init__(self) -> None:
        self.tasks = (
            SpecificTaskRecord(
                task_id="task.test.outline",
                task_title="Outline",
                task_family="test",
                input_contract_id="contract.user_request.basic",
                output_contract_id="contract.test.outline",
            ),
            SpecificTaskRecord(
                task_id="task.test.writer",
                task_title="Writer",
                task_family="test",
                input_contract_id="contract.test.outline",
                output_contract_id="contract.test.draft",
            ),
        )
        self.coordination = CoordinationTaskDefinition(
            graph_id="graph.test.artifact_context",
            title="产物交接测试",
            coordination_mode="pipeline",
            coordinator_agent_id="agent:0",
            task_family="test",
            topology_template_id="topology.test.artifact_context",
            graph_nodes=(
                {"node_id": "outline", "agent_id": "agent:0", "task_id": "task.test.outline", "role": "writer"},
                {
                    "node_id": "writer",
                    "agent_id": "agent:0",
                    "task_id": "task.test.writer",
                    "role": "writer",
                    "artifact_context_policy": {
                        "items": [
                            {
                                "source": "input_key",
                                "input_key": "contract.test.outline:artifact_refs",
                                "label": "当前批次细纲",
                                "max_chars": 20000,
                            }
                        ],
                        "default_max_chars": 20000,
                        "max_items": 1,
                    },
                },
            ),
            graph_edges=(
                {
                    "edge_id": "outline_writer",
                    "from": "outline",
                    "to": "writer",
                    "contract_id": "contract.test.outline",
                    "artifact_ref_policy": {
                        "target_input_key": "contract.test.outline:artifact_refs",
                        "max_chars": 20000,
                    },
                    "metadata": {"on_missing": "block"},
                },
            ),
        )
        self.topology = TopologyTemplate(
            template_id="topology.test.artifact_context",
            title="产物交接拓扑",
            nodes=self.coordination.graph_nodes,
            edges=self.coordination.graph_edges,
            enabled=True,
        )
        self.protocol = TaskCommunicationProtocol(
            protocol_id="protocol.test.artifact_context",
            title="产物交接协议",
            message_types=("message/send",),
            payload_contracts=("contract.test.outline", "contract.test.draft"),
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


def test_stage_message_expands_current_artifact_handoff(tmp_path) -> None:
    outline_path = tmp_path / "outline.md"
    outline_path.write_text("# 当前细纲\n\n第1章：主角入泽。", encoding="utf-8")
    registry = _ArtifactContextRegistry()
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
        coordination_run_id="coordrun:artifact-context",
        task_run_id="taskrun:outline",
        graph_ref="graph.test.artifact_context",
        coordinator_agent_id="agent:0",
        topology_template_id="topology.test.artifact_context",
        communication_protocol_id="protocol.test.artifact_context",
        status="running",
        diagnostics={"coordination_flow": {"current_stage_id": "outline"}},
    )
    state_index.upsert_coordination_run(coordination_run)

    result = runtime.resume_from_task_result(
        coordination_run=coordination_run,
        event=TaskResultReadyEvent(
            event_type="task_result_ready",
            coordination_run_id="coordrun:artifact-context",
            task_run_id="taskrun:outline",
            stage_id="outline",
            task_ref="task.test.outline",
            task_result_ref="taskresult:outline",
            artifact_refs=(f"artifact:{outline_path.as_posix()}",),
            accepted=True,
        ),
    )

    assert result.stage_execution_request is not None
    assert "当前批次细纲" in result.stage_execution_request.message
    assert "第1章：主角入泽" in result.stage_execution_request.message


def test_langgraph_coordination_runtime_injects_working_memory_context(tmp_path) -> None:
    registry = _WorkingMemoryRegistry()
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
        coordination_run_id="coordrun:wm",
        task_run_id="taskrun:wm",
        graph_ref="graph.test.working_memory_runtime",
        coordinator_agent_id="agent:0",
        topology_template_id="topology.test.working_memory_runtime",
        communication_protocol_id="protocol.test.working_memory_runtime",
        status="running",
        diagnostics={"coordination_flow": {"current_stage_id": "source"}},
    )
    state_index.upsert_coordination_run(coordination_run)

    result = runtime.resume_from_task_result(
        coordination_run=coordination_run,
        event=TaskResultReadyEvent(
            event_type="task_result_ready",
            coordination_run_id="coordrun:wm",
            task_run_id="taskrun:source",
            stage_id="source",
            task_ref="task.test.source",
            task_result_ref="taskresult:source",
            accepted=True,
            diagnostics={
                "working_memory_candidates": [
                    {
                        "title": "世界观基线",
                        "summary": "大泽少年是洪荒时代的主角。",
                        "kind": "approved_world",
                        "scope": "graph_scope",
                        "status": "accepted",
                        "visibility": "shared_in_graph",
                    }
                ]
            },
        ),
    )

    assert result.stage_execution_request is not None
    assert result.stage_execution_request.stage_id == "target"
    assert result.stage_execution_request.working_memory_refs
    assembly = result.stage_execution_request.runtime_assembly
    assert assembly["diagnostics"]["working_memory_enabled"] is True
    assert assembly["diagnostics"]["working_memory_required_count"] == 1
    section_ids = [item["section_id"] for item in assembly["context_sections"]]
    assert "working_memory.required" in section_ids
    operations = list(result.state.get("working_memory_operations") or [])
    assert operations[0]["operation"] == "memory_write"
    assert operations[0]["candidate_count"] == 1
    assert operations[1]["operation"] == "memory_handoff"
    assert operations[1]["status"] == "committed"


def test_formal_memory_write_edge_uses_source_output_key(tmp_path) -> None:
    registry = _FormalMemoryRegistry()
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
        coordination_run_id="coordrun:formal-memory",
        task_run_id="taskrun:formal-memory",
        graph_ref="graph.test.formal_memory_runtime",
        coordinator_agent_id="agent:0",
        topology_template_id="topology.test.formal_memory_runtime",
        communication_protocol_id="protocol.test.formal_memory_runtime",
        status="running",
        diagnostics={"coordination_flow": {"current_stage_id": "world_author"}},
    )
    state_index.upsert_coordination_run(coordination_run)

    result = runtime.resume_from_task_result(
        coordination_run=coordination_run,
        event=TaskResultReadyEvent(
            event_type="task_result_ready",
            coordination_run_id="coordrun:formal-memory",
            task_run_id="taskrun:world-author",
            stage_id="world_author",
            task_ref="task.test.world_author",
            task_result_ref="taskresult:world-author",
            accepted=True,
            artifact_refs=("artifact:world_candidate.md",),
        ),
        current_task_result={
            "final_outputs": {
                "world_candidate": {
                    "canonical_text": "天地初辟，万族争道。",
                    "summary": "世界观候选正文",
                },
                "unrelated_output": {
                    "canonical_text": "这段内容不应进入世界观记忆库。",
                },
            },
            "output_refs": ["artifact:world_candidate.md"],
        },
    )

    assert result.state["stage_results"]["world_author"]["outputs"]["world_candidate"]["canonical_text"] == "天地初辟，万族争道。"
    versions, _read_log = runtime.formal_memory.store.select_versions(
        repository_id="memory.world",
        collection_id="world",
        selector={"record_key": "world_bible.current", "status_filter": ["candidate"]},
        version_selector={"mode": "all"},
        node_run_id="taskrun:formal-memory:assert",
        edge_id="assert",
    )

    assert len(versions) == 1
    assert versions[0].record_kind == "world_bible"
    assert versions[0].canonical_text == "天地初辟，万族争道。"
    assert versions[0].summary == "世界观候选正文"
    assert "unrelated_output" not in versions[0].payload


def test_formal_memory_write_edge_blocks_missing_source_output_key(tmp_path) -> None:
    registry = _FormalMemoryRegistry()
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
        coordination_run_id="coordrun:formal-memory-missing",
        task_run_id="taskrun:formal-memory-missing",
        graph_ref="graph.test.formal_memory_runtime",
        coordinator_agent_id="agent:0",
        topology_template_id="topology.test.formal_memory_runtime",
        communication_protocol_id="protocol.test.formal_memory_runtime",
        status="running",
        diagnostics={"coordination_flow": {"current_stage_id": "world_author"}},
    )
    state_index.upsert_coordination_run(coordination_run)

    result = runtime.resume_from_task_result(
        coordination_run=coordination_run,
        event=TaskResultReadyEvent(
            event_type="task_result_ready",
            coordination_run_id="coordrun:formal-memory-missing",
            task_run_id="taskrun:world-author",
            stage_id="world_author",
            task_ref="task.test.world_author",
            task_result_ref="taskresult:world-author",
            accepted=True,
            artifact_refs=("artifact:world_candidate.md",),
        ),
        current_task_result={
            "final_outputs": {
                "unrelated_output": {
                    "canonical_text": "没有 world_candidate 字段。",
                },
            },
            "output_refs": ["artifact:world_candidate.md"],
        },
    )

    operations = list(result.state.get("working_memory_operations") or [])
    write_operation = next(item for item in operations if item.get("operation") == "memory_write")
    assert write_operation["created_working_memory_refs"] == []
    assert write_operation["formal_memory_errors"][0]["error"] == "source_output_key_not_found"
    versions, _read_log = runtime.formal_memory.store.select_versions(
        repository_id="memory.world",
        collection_id="world",
        selector={"record_key": "world_bible.current", "status_filter": ["candidate"]},
        version_selector={"mode": "all"},
        node_run_id="taskrun:formal-memory-missing:assert",
        edge_id="assert",
    )
    assert versions == ()


def test_formal_memory_commit_edge_uses_candidate_ref_and_verdict(tmp_path) -> None:
    registry = _FormalMemoryRegistry()
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
        coordination_run_id="coordrun:formal-memory-commit",
        task_run_id="taskrun:formal-memory-commit",
        graph_ref="graph.test.formal_memory_runtime",
        coordinator_agent_id="agent:0",
        topology_template_id="topology.test.formal_memory_runtime",
        communication_protocol_id="protocol.test.formal_memory_runtime",
        status="running",
        diagnostics={"coordination_flow": {"current_stage_id": "world_author"}},
    )
    state_index.upsert_coordination_run(coordination_run)

    source_result = runtime.resume_from_task_result(
        coordination_run=coordination_run,
        event=TaskResultReadyEvent(
            event_type="task_result_ready",
            coordination_run_id="coordrun:formal-memory-commit",
            task_run_id="taskrun:world-author",
            stage_id="world_author",
            task_ref="task.test.world_author",
            task_result_ref="taskresult:world-author",
            accepted=True,
            artifact_refs=("artifact:world_candidate.md",),
        ),
        current_task_result={
            "final_outputs": {
                "world_candidate": {
                    "canonical_text": "洪荒世界观候选。",
                    "summary": "待审核世界观",
                }
            },
            "output_refs": ["artifact:world_candidate.md"],
        },
    )
    candidate_ref = source_result.state["stage_results"]["world_author"]["working_memory_refs"][0]
    assert source_result.stage_execution_request is not None
    assert source_result.stage_execution_request.stage_id == "world_review"

    review_result = runtime.resume_from_task_result(
        coordination_run=coordination_run,
        event=TaskResultReadyEvent(
            event_type="task_result_ready",
            coordination_run_id="coordrun:formal-memory-commit",
            task_run_id="taskrun:world-review",
            stage_id="world_review",
            task_ref="task.test.world_review",
            task_result_ref="taskresult:world-review",
            accepted=True,
        ),
        current_task_result={
            "final_outputs": {
                "reviewed_candidate_ref": candidate_ref,
                "verdict": "pass",
            }
        },
    )

    operations = list(review_result.state.get("working_memory_operations") or [])
    commit_operation = [item for item in operations if item.get("operation") == "memory_commit"][-1]
    assert commit_operation["formal_memory_receipts"][0]["status"] == "committed"
    versions, _read_log = runtime.formal_memory.store.select_versions(
        repository_id="memory.world",
        collection_id="world",
        selector={"record_key": "world_bible.current", "status_filter": ["committed"]},
        version_selector={"mode": "latest_committed_before_clock"},
        clock_seq=999,
        node_run_id="taskrun:formal-memory-commit:assert",
        edge_id="assert",
    )
    assert len(versions) == 1
    assert versions[0].canonical_text == "洪荒世界观候选。"


def test_formal_memory_read_edge_does_not_fallback_to_working_memory(tmp_path) -> None:
    registry = _FormalMemoryRegistry()
    state_index = RuntimeStateIndex(tmp_path)
    event_log = RuntimeEventLog(tmp_path)
    runtime = LangGraphCoordinationRuntime(
        root_dir=tmp_path,
        state_index=state_index,
        event_log=event_log,
        task_flow_registry=registry,
        trace_reader=_Trace({}),
    )
    graph_spec = {
        "graph_id": "graph.test.formal_memory_read",
        "graph_ref": "graph.test.formal_memory_read",
        "nodes": [
            {
                "node_id": "memory.world",
                "node_type": "memory_repository",
                "metadata": {
                    "memory_repository": {
                        "repository_id": "memory.world",
                        "collections": [{"collection_id": "world", "record_kinds": ["world_bible"]}],
                    }
                },
            },
            {"node_id": "chapter_writer", "node_type": "agent"},
        ],
        "edges": [
            {
                "edge_id": "edge.memory.chapter.world",
                "source_node_id": "memory.world",
                "target_node_id": "chapter_writer",
                "mode": "memory_read",
                "metadata": {
                    "collection": "world",
                    "selector": {
                        "collection": "world",
                        "record_key": "world_bible.current",
                        "record_kind": "world_bible",
                        "status_filter": ["committed"],
                    },
                    "version_selector": {"mode": "latest_committed_before_clock"},
                    "on_missing": "block",
                },
            }
        ],
    }
    runtime.formal_memory.sync_graph_spec(graph_id="graph.test.formal_memory_read", graph_spec=graph_spec)
    candidate, _write_txn = runtime.formal_memory.write_candidate_from_edge(
        edge={
            "edge_id": "edge.world_author.memory.world",
            "repository": "memory.world",
            "collection": "world",
            "record_key": "world_bible.current",
            "record_kind": "world_bible",
        },
        candidate={
            "kind": "world_bible",
            "summary": "正式世界观",
            "payload": {"canonical_text": "正式仓库中的世界观。"},
        },
        task_run_id="taskrun:formal-read",
        node_run_id="taskrun:formal-read:world_author",
        source_node_id="world_author",
        source_clock_seq=0,
    )
    runtime.formal_memory.commit_from_edge(
        edge={
            "edge_id": "edge.world_review.memory.world",
            "repository": "memory.world",
            "collection": "world",
            "record_key": "world_bible.current",
            "record_kind": "world_bible",
            "receipt_policy": {"visible_after": "same_clock"},
        },
        candidate_version_id=candidate.version_id,
        node_run_id="taskrun:formal-read:world_review",
        source_clock_seq=0,
    )
    legacy_item = runtime.working_memory.create_item(
        task_run_id="taskrun:formal-read",
        graph_id="graph.test.formal_memory_read",
        owner_node_id="legacy_seed",
        node_run_id="taskrun:formal-read:legacy_seed",
        kind="world_bible",
        scope="graph_scope",
        status="accepted",
        visibility="shared_in_graph",
        title="旧工作记忆世界观",
        summary="这条旧工作记忆不应该通过正式 memory_read 边进入上下文。",
        metadata={
            "formal_memory": {
                "repository_id": "memory.world",
                "collection_id": "world",
                "record_key": "world_bible.current",
                "record_kind": "world_bible",
                "commit_state": "committed",
            }
        },
    )

    context = runtime._select_stage_working_memory_context(
        state={
            "coordination_run_id": "coordrun:formal-read",
            "root_task_run_id": "taskrun:formal-read",
            "diagnostics": {"coordination_graph_spec": graph_spec},
            "retry_counts": {},
        },
        stage_id="chapter_writer",
        node_id="chapter_writer",
        contract={"stage_id": "chapter_writer", "node_id": "chapter_writer", "agent_id": "agent:writer"},
    )

    assert context["diagnostics"]["formal_memory_primary"] is True
    assert context["diagnostics"]["working_memory_legacy_read_enabled"] is False
    assert dict(context["working_memory.required"])["item_count"] == 0
    assert legacy_item.work_memory_id not in context.get("required_refs", [])
    assert context["formal_memory.required_records"][0]["canonical_text"] == "正式仓库中的世界观。"
    assert context["formal_memory.required_records"][0]["version_id"] == candidate.version_id


def test_langgraph_coordination_runtime_commits_working_memory_decisions(tmp_path) -> None:
    registry = _WorkingMemoryRegistry()
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
        coordination_run_id="coordrun:wm-commit",
        task_run_id="taskrun:wm-commit",
        graph_ref="graph.test.working_memory_runtime",
        coordinator_agent_id="agent:0",
        topology_template_id="topology.test.working_memory_runtime",
        communication_protocol_id="protocol.test.working_memory_runtime",
        status="running",
        diagnostics={"coordination_flow": {"current_stage_id": "source"}},
    )
    state_index.upsert_coordination_run(coordination_run)
    item = runtime.working_memory.create_item(
        task_run_id="taskrun:wm-commit",
        graph_id="graph.test.working_memory_runtime",
        owner_node_id="source",
        node_run_id="taskrun:wm-commit:source",
        kind="approved_world",
        scope="graph_scope",
        status="proposed",
        visibility="shared_in_graph",
        title="候选设定",
        summary="候选设定等待审核。",
    )

    result = runtime.resume_from_task_result(
        coordination_run=coordination_run,
        event=TaskResultReadyEvent(
            event_type="task_result_ready",
            coordination_run_id="coordrun:wm-commit",
            task_run_id="taskrun:source",
            stage_id="source",
            task_ref="task.test.source",
            task_result_ref="taskresult:source",
            accepted=True,
            diagnostics={"working_memory_commit": {"accepted_working_memory_refs": [item.work_memory_id]}},
        ),
    )

    committed = runtime.working_memory.get_item(item.work_memory_id)
    assert committed is not None
    assert committed.status == "accepted"
    operations = list(result.state.get("working_memory_operations") or [])
    commit_operations = [item for item in operations if item.get("operation") == "memory_commit"]
    assert commit_operations
    assert commit_operations[-1]["accepted_working_memory_refs"] == [item.work_memory_id]
    sequence_indexes = [int(item.get("sequence_index") or 0) for item in operations if isinstance(item, dict)]
    assert sequence_indexes == sorted(sequence_indexes)


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
    assert result.stage_execution_request.dispatch_context["dispatch_event_id"].startswith("tlevent:")
    assert result.stage_execution_request.dispatch_context["clock_seq"] > 0
    assert result.stage_execution_request.artifact_context_packet["artifact_refs"] == ["ref:project_spec"]
    assert result.state["timeline"]["current_clock_seq"] >= result.stage_execution_request.dispatch_context["clock_seq"]
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
    assert "langgraph_runtime_state" not in updated.diagnostics
    runtime_state = runtime.checkpoints.get_state(thread_id="coordrun:test")
    assert dict(runtime_state["diagnostics"])["contract_manifest_ref"].startswith("contract-manifest:coordination:")
    assert "project_scope" in runtime_state["completed_nodes"]


class _DiamondRegistry:
    def __init__(self) -> None:
        self.tasks = (
            SpecificTaskRecord(
                task_id="task.test.a",
                task_title="A",
                task_family="test",
                input_contract_id="contract.user_request.basic",
                output_contract_id="contract.artifact_refs.bundle",
            ),
            SpecificTaskRecord(
                task_id="task.test.b",
                task_title="B",
                task_family="test",
                input_contract_id="contract.user_request.basic",
                output_contract_id="contract.artifact_refs.bundle",
            ),
            SpecificTaskRecord(
                task_id="task.test.c",
                task_title="C",
                task_family="test",
                input_contract_id="contract.user_request.basic",
                output_contract_id="contract.artifact_refs.bundle",
            ),
            SpecificTaskRecord(
                task_id="task.test.d",
                task_title="D",
                task_family="test",
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


def test_langgraph_coordination_runtime_ignores_stale_dispatch_result(tmp_path) -> None:
    runtime, state_index, coordination_run = _diamond_runtime(tmp_path)
    first = runtime.resume_from_task_result(
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
    assert first.stage_execution_request is not None
    active_request_id = first.stage_execution_request.request_id

    stale = runtime.resume_from_task_result(
        coordination_run=coordination_run,
        event=TaskResultReadyEvent(
            event_type="task_result_ready",
            coordination_run_id="coordrun:diamond",
            task_run_id="taskrun:b:old",
            stage_id="b",
            task_ref="task.test.b",
            task_result_ref="taskresult:b:old",
            artifact_refs=("ref:b:old",),
            accepted=True,
            request_id="stageexec:stale",
            dispatch_event_id="tlevent:stale",
        ),
    )

    assert stale.state["stage_execution_request"]["request_id"] == active_request_id
    assert "b" not in stale.state.get("stage_results", {})
    assert stale.state["stale_stage_results"]
    assert stale.state["diagnostics"]["last_stale_result_reason"] == "request_id_does_not_match_active_request"

    updated = state_index.get_coordination_run("coordrun:diamond")
    assert updated is not None
    assert "langgraph_runtime_state" not in updated.diagnostics
    runtime_state = runtime.checkpoints.get_state(thread_id="coordrun:diamond")
    assert runtime_state["completed_nodes"] == ["a"]
    assert runtime_state["running_nodes"] == ["b"]
    assert runtime_state["ready_nodes"] == ["c"]


class _SequencedRegistry:
    def __init__(self) -> None:
        self.tasks = (
            SpecificTaskRecord(task_id="task.test.a", task_title="A", task_family="test"),
            SpecificTaskRecord(task_id="task.test.b", task_title="B", task_family="test"),
            SpecificTaskRecord(task_id="task.test.c", task_title="C", task_family="test"),
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
    assert "langgraph_runtime_state" not in updated.diagnostics
    runtime_state = runtime.checkpoints.get_state(thread_id="coordrun:diamond")
    assert runtime_state["human_gate"]["status"] == "waiting"


def test_langgraph_coordination_runtime_does_not_block_human_gate_when_auto_continue(tmp_path) -> None:
    runtime, _, coordination_run = _diamond_runtime(tmp_path)
    runtime.task_flow_registry.coordination.metadata["continuation_policy"] = {"human_gate_mode": "auto_continue"}
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
    assert result.state["terminal_status"] == "failed"
    assert result.state["failed_nodes"] == ["a"]
    assert result.state["human_gate"] == {}


def test_langgraph_coordination_runtime_preserves_node_human_gate_policy_in_contract(tmp_path) -> None:
    runtime, _, coordination_run = _diamond_runtime(tmp_path)
    node = runtime.task_flow_registry.coordination.graph_nodes[0]
    node["human_gate_policy"] = {"enabled": True, "mode": "non_blocking", "trigger_verdict": "human_review_required"}
    contracts = runtime._contracts_for_run(
        coordination_run=coordination_run,
        coordination_task=runtime.task_flow_registry.coordination,
    )

    assert contracts[0].human_gate_policy == {
        "enabled": True,
        "mode": "non_blocking",
        "trigger_verdict": "human_review_required",
    }


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
