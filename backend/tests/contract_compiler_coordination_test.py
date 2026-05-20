from __future__ import annotations

from pathlib import Path

from orchestration.agent_runtime_models import AgentRuntimeProfile
from orchestration.runtime_loop.contract_compiler import compile_coordination_contract_manifest
from tasks import TaskContractRegistry, compile_task_graph_definition_runtime_spec
from tasks.flow_models import CoordinationTaskDefinition, SpecificTaskRecord, TaskCommunicationProtocol
from tasks.task_graph_models import TaskGraphDefinition, TaskGraphEdgeDefinition, TaskGraphNodeDefinition


def _seed_coordination_contracts(registry: TaskContractRegistry) -> None:
    for contract_id, title_zh, kind in (
        ("contract.test.node_input", "测试节点输入", "node_execution"),
        ("contract.test.node_output", "测试节点输出", "node_execution"),
        ("contract.test.node_override", "测试节点覆盖契约", "node_execution"),
        ("contract.test.edge_handoff", "测试边交接", "edge_handoff"),
        ("contract.test.graph_unit.handoff", "测试图节点交接", "edge_handoff"),
        ("contract.test.graph_unit.binding_handoff", "测试图节点绑定交接", "edge_handoff"),
    ):
        registry.upsert_contract_spec(
            {
                "contract_id": contract_id,
                "title_zh": title_zh,
                "contract_kind": kind,
                "output_fields": [
                    {
                        "field_id": "payload",
                        "title_zh": "载荷",
                        "field_type": "object",
                        "required": True,
                        "source_hint": "upstream_output",
                        "visibility": "model_visible",
                    }
                ],
            }
        )


def test_coordination_contract_compiler_builds_node_and_edge_manifest(tmp_path: Path) -> None:
    contract_registry = TaskContractRegistry(tmp_path)
    _seed_coordination_contracts(contract_registry)
    task = SpecificTaskRecord(
        task_id="task.test.worker",
        task_title="测试工作节点",
        task_family="test",
        input_contract_id="contract.test.node_input",
        output_contract_id="contract.test.node_output",
    )
    coordination = CoordinationTaskDefinition(
        graph_id="graph.test.pipeline",
        title="测试协调链路",
        coordination_mode="pipeline",
        coordinator_agent_id="agent:0",
        task_family="test",
        graph_nodes=(
            {"node_id": "coordinator", "node_type": "coordinator", "agent_id": "agent:0", "role": "coordinator"},
            {
                "node_id": "worker",
                "node_type": "subtask",
                "task_id": task.task_id,
                "agent_id": "agent:test",
                "runtime_lane": "coordination_task",
                "node_contract_id": "contract.test.node_override",
                "projection_id": "projection.test.node_worker",
            },
        ),
        graph_edges=(
            {"edge_id": "coordinator_to_worker", "from": "coordinator", "to": "worker", "mode": "dispatch"},
        ),
        communication_modes=("dispatch",),
        metadata={"protocol_id": "protocol.test.dispatch"},
    )
    protocol = TaskCommunicationProtocol(
        protocol_id="protocol.test.dispatch",
        title="测试派发协议",
        message_types=("dispatch",),
        payload_contracts=("contract.test.edge_handoff",),
        enabled=True,
    )
    graph = TaskGraphDefinition(
        graph_id=coordination.graph_id,
        title=coordination.title,
        graph_kind="multi_agent",
        task_family=coordination.task_family,
        nodes=(
            TaskGraphNodeDefinition(
                node_id="coordinator",
                node_type="coordinator",
                title="协调者",
                agent_id="agent:0",
                work_posture="coordinator",
            ),
            TaskGraphNodeDefinition(
                node_id="worker",
                node_type="subtask",
                title="测试工作节点",
                task_id=task.task_id,
                agent_id="agent:test",
                runtime_lane="coordination_task",
                node_contract_id="contract.test.node_override",
                projection_id="projection.test.node_worker",
            ),
        ),
        edges=(
            TaskGraphEdgeDefinition(
                edge_id="coordinator_to_worker",
                source_node_id="coordinator",
                target_node_id="worker",
                edge_type="dispatch",
            ),
        ),
    )
    graph_spec = compile_task_graph_definition_runtime_spec(
        graph=graph,
        specific_tasks=(task,),
        communication_protocol=protocol,
    )
    profile = AgentRuntimeProfile(
        agent_profile_id="worker_test_profile",
        agent_id="agent:test",
        allowed_runtime_lanes=("coordination_task",),
    )
    coordinator_profile = AgentRuntimeProfile(
        agent_profile_id="coordinator_test_profile",
        agent_id="agent:0",
        allowed_runtime_lanes=("coordination_task",),
    )

    manifest = compile_coordination_contract_manifest(
        contract_registry=contract_registry,
        coordination_task=coordination,
        graph_spec=graph_spec,
        specific_tasks=(task,),
        communication_protocol=protocol,
        agent_profiles=(coordinator_profile, profile),
    )

    assert graph_spec.valid is True
    assert manifest.valid is True
    assert manifest.manifest_kind == "coordination"
    assert [item.node_id for item in manifest.node_contracts] == ["coordinator", "worker"]
    assert manifest.edge_handoff_contracts[0].contract_refs == ("contract.test.edge_handoff",)
    assert manifest.edge_handoff_contracts[0].message_type == "message/send"
    assert manifest.node_contracts[1].contract_refs == (
        "contract.test.node_input",
        "contract.test.node_output",
        "contract.test.node_override",
    )
    assert manifest.node_contracts[1].projection_id == "projection.test.node_worker"
    assert {item.contract_id for item in manifest.global_contracts} == {
        "contract.test.node_input",
        "contract.test.node_output",
        "contract.test.node_override",
        "contract.test.edge_handoff",
    }


def test_coordination_contract_compiler_reports_missing_edge_contract(tmp_path: Path) -> None:
    contract_registry = TaskContractRegistry(tmp_path)
    _seed_coordination_contracts(contract_registry)
    task = SpecificTaskRecord(
        task_id="task.test.worker",
        task_title="测试工作节点",
        task_family="test",
        input_contract_id="contract.test.node_input",
        output_contract_id="contract.test.node_override",
    )
    coordination = CoordinationTaskDefinition(
        graph_id="graph.test.pipeline",
        title="测试协调链路",
        coordination_mode="pipeline",
        coordinator_agent_id="agent:0",
        task_family="test",
        graph_nodes=(
            {"node_id": "coordinator", "node_type": "coordinator", "agent_id": "agent:0", "role": "coordinator"},
            {"node_id": "worker", "node_type": "subtask", "task_id": task.task_id, "agent_id": "agent:test"},
        ),
        graph_edges=(
            {"edge_id": "coordinator_to_worker", "from": "coordinator", "to": "worker", "mode": "dispatch"},
        ),
    )
    graph = TaskGraphDefinition(
        graph_id=coordination.graph_id,
        title=coordination.title,
        graph_kind="multi_agent",
        task_family=coordination.task_family,
        nodes=(
            TaskGraphNodeDefinition(
                node_id="coordinator",
                node_type="coordinator",
                title="协调者",
                agent_id="agent:0",
                work_posture="coordinator",
            ),
            TaskGraphNodeDefinition(
                node_id="worker",
                node_type="subtask",
                title="测试工作节点",
                task_id=task.task_id,
                agent_id="agent:test",
            ),
        ),
        edges=(
            TaskGraphEdgeDefinition(
                edge_id="coordinator_to_worker",
                source_node_id="coordinator",
                target_node_id="worker",
                edge_type="dispatch",
            ),
        ),
    )
    graph_spec = compile_task_graph_definition_runtime_spec(graph=graph, specific_tasks=(task,))

    manifest = compile_coordination_contract_manifest(
        contract_registry=contract_registry,
        coordination_task=coordination,
        graph_spec=graph_spec,
        specific_tasks=(task,),
        communication_protocol=None,
        agent_profiles=(
            AgentRuntimeProfile(
                agent_profile_id="worker_test_profile",
                agent_id="agent:test",
            ),
        ),
    )

    assert manifest.valid is False
    assert "edge_handoff_contract_missing" in {item.code for item in manifest.issues}


def test_coordination_contract_compiler_uses_categorized_contract_bindings(tmp_path: Path) -> None:
    contract_registry = TaskContractRegistry(tmp_path)
    _seed_coordination_contracts(contract_registry)
    task = SpecificTaskRecord(
        task_id="task.test.worker",
        task_title="测试工作节点",
        task_family="test",
        input_contract_id="contract.test.node_input",
        output_contract_id="contract.test.node_output",
    )
    coordination = CoordinationTaskDefinition(
        graph_id="graph.test.bindings",
        title="契约绑定图",
        coordination_mode="pipeline",
        coordinator_agent_id="agent:0",
        task_family="test",
        graph_nodes=(),
        graph_edges=(),
    )
    graph = TaskGraphDefinition(
        graph_id=coordination.graph_id,
        title=coordination.title,
        graph_kind="multi_agent",
        task_family=coordination.task_family,
        contract_bindings={
            "schema": {"graph_contract_id": "contract.test.node_output"},
            "unit_batch": {"unit_label": "项", "unit_batch_size_key": "items_per_round"},
        },
        nodes=(
            TaskGraphNodeDefinition(
                node_id="worker",
                node_type="subtask",
                title="测试工作节点",
                task_id=task.task_id,
                agent_id="agent:test",
                runtime_lane="coordination_task",
                contract_bindings={
                    "schema": {
                        "input_contract_id": "contract.test.node_input",
                        "output_contract_id": "contract.test.node_output",
                    },
                    "execution": {
                        "node_contract_id": "contract.test.node_override",
                        "tool_bindings": [{"tool_id": "tool.counter"}],
                    },
                    "artifact": {"artifact_policy": {"target": "artifact.md"}},
                    "memory": {"memory_read_policy": {"readable_scopes": ["baseline"]}},
                    "acceptance": {"acceptance_policies": [{"policy_id": "quality.basic"}]},
                    "runtime": {"model_profile_overrides": {"max_output_tokens": 65536}},
                },
            ),
        ),
        edges=(
            TaskGraphEdgeDefinition(
                edge_id="edge.input.worker",
                source_node_id="worker",
                target_node_id="worker",
                edge_type="handoff",
                contract_bindings={
                    "schema": {"payload_contract_id": "contract.test.edge_handoff"},
                    "handoff": {"required_refs": ["worker.output"], "ack_required": True},
                    "temporal": {"visibility_timing": "after_commit"},
                },
            ),
        ),
    )

    graph_spec = compile_task_graph_definition_runtime_spec(graph=graph, specific_tasks=(task,))
    manifest = compile_coordination_contract_manifest(
        contract_registry=contract_registry,
        coordination_task=coordination,
        graph_spec=graph_spec,
        specific_tasks=(task,),
        agent_profiles=(
            AgentRuntimeProfile(
                agent_profile_id="worker_test_profile",
                agent_id="agent:test",
                allowed_runtime_lanes=("coordination_task",),
            ),
        ),
    )

    assert manifest.valid is True
    assert manifest.graph_contract_bindings["unit_batch"]["unit_label"] == "项"
    node_contract = manifest.node_contracts[0]
    assert node_contract.schema_bindings["input_contract_id"] == "contract.test.node_input"
    assert node_contract.execution_bindings["node_contract_id"] == "contract.test.node_override"
    assert node_contract.artifact_bindings["artifact_policy"]["target"] == "artifact.md"
    assert node_contract.memory_bindings["memory_read_policy"]["readable_scopes"] == ["baseline"]
    assert node_contract.acceptance_bindings["acceptance_policies"][0]["policy_id"] == "quality.basic"
    assert node_contract.runtime_bindings["model_profile_overrides"]["max_output_tokens"] == 65536
    edge_contract = manifest.edge_handoff_contracts[0]
    assert edge_contract.contract_refs == ("contract.test.edge_handoff",)
    assert edge_contract.schema_bindings["payload_contract_id"] == "contract.test.edge_handoff"
    assert edge_contract.temporal_bindings["visibility_timing"] == "after_commit"


def test_coordination_contract_compiler_reports_contract_binding_conflict(tmp_path: Path) -> None:
    contract_registry = TaskContractRegistry(tmp_path)
    _seed_coordination_contracts(contract_registry)
    task = SpecificTaskRecord(
        task_id="task.test.worker",
        task_title="测试工作节点",
        task_family="test",
        input_contract_id="contract.test.node_input",
        output_contract_id="contract.test.node_output",
    )
    coordination = CoordinationTaskDefinition(
        graph_id="graph.test.binding_conflict",
        title="契约冲突图",
        coordination_mode="pipeline",
        coordinator_agent_id="agent:0",
        task_family="test",
        graph_nodes=(),
        graph_edges=(),
    )
    graph = TaskGraphDefinition(
        graph_id=coordination.graph_id,
        title=coordination.title,
        graph_kind="multi_agent",
        task_family=coordination.task_family,
        nodes=(
            TaskGraphNodeDefinition(
                node_id="worker",
                node_type="subtask",
                title="测试工作节点",
                task_id=task.task_id,
                agent_id="agent:test",
                input_contract_id="contract.test.node_input",
                contract_bindings={"schema": {"input_contract_id": "contract.test.node_output"}},
            ),
        ),
        edges=(
            TaskGraphEdgeDefinition(
                edge_id="edge.worker.worker",
                source_node_id="worker",
                target_node_id="worker",
                payload_contract_id="contract.test.edge_handoff",
            ),
        ),
    )

    graph_spec = compile_task_graph_definition_runtime_spec(graph=graph, specific_tasks=(task,))
    manifest = compile_coordination_contract_manifest(
        contract_registry=contract_registry,
        coordination_task=coordination,
        graph_spec=graph_spec,
        specific_tasks=(task,),
    )

    assert manifest.valid is False
    assert "contract_binding_conflict" in {item.code for item in manifest.issues}


def test_coordination_contract_compiler_does_not_collect_conflicting_legacy_contract_refs(tmp_path: Path) -> None:
    contract_registry = TaskContractRegistry(tmp_path)
    _seed_coordination_contracts(contract_registry)
    task = SpecificTaskRecord(
        task_id="task.test.worker",
        task_title="测试工作节点",
        task_family="test",
        input_contract_id="contract.test.node_input",
        output_contract_id="contract.test.node_override",
    )
    coordination = CoordinationTaskDefinition(
        graph_id="graph.test.binding_authority",
        title="契约权威图",
        coordination_mode="pipeline",
        coordinator_agent_id="agent:0",
        task_family="test",
        graph_nodes=(),
        graph_edges=(),
    )
    graph = TaskGraphDefinition(
        graph_id=coordination.graph_id,
        title=coordination.title,
        graph_kind="multi_agent",
        task_family=coordination.task_family,
        nodes=(
            TaskGraphNodeDefinition(
                node_id="worker",
                node_type="subtask",
                title="测试工作节点",
                task_id=task.task_id,
                agent_id="agent:test",
                input_contract_id="contract.test.node_input",
                contract_bindings={"schema": {"input_contract_id": "contract.test.node_output"}},
                metadata={"legacy_contract_fields": {"input_contract_id": "contract.test.node_input"}},
            ),
        ),
        edges=(
            TaskGraphEdgeDefinition(
                edge_id="edge.worker.worker",
                source_node_id="worker",
                target_node_id="worker",
                payload_contract_id="contract.test.edge_handoff",
                contract_bindings={"schema": {"payload_contract_id": "contract.test.node_output"}},
                metadata={"legacy_contract_fields": {"payload_contract_id": "contract.test.edge_handoff"}},
            ),
        ),
    )

    graph_spec = compile_task_graph_definition_runtime_spec(graph=graph, specific_tasks=(task,))
    manifest = compile_coordination_contract_manifest(
        contract_registry=contract_registry,
        coordination_task=coordination,
        graph_spec=graph_spec,
        specific_tasks=(task,),
    )

    node_contract = manifest.node_contracts[0]
    edge_contract = manifest.edge_handoff_contracts[0]
    issue_codes = {item.code for item in manifest.issues}

    assert "contract_binding_conflict" in issue_codes
    assert node_contract.input_contract_id == "contract.test.node_output"
    assert node_contract.contract_refs == ("contract.test.node_output", "contract.test.node_override")
    assert edge_contract.contract_refs == ("contract.test.node_output",)


def test_coordination_contract_compiler_compiles_graph_unit_handoff_contracts(tmp_path: Path) -> None:
    contract_registry = TaskContractRegistry(tmp_path)
    _seed_coordination_contracts(contract_registry)
    coordination = CoordinationTaskDefinition(
        graph_id="graph.test.graph_unit_manifest",
        title="图节点契约清单",
        coordination_mode="pipeline",
        coordinator_agent_id="agent:0",
        task_family="test",
        graph_nodes=(),
        graph_edges=(),
    )
    graph = TaskGraphDefinition(
        graph_id=coordination.graph_id,
        title=coordination.title,
        graph_kind="coordination",
        task_family=coordination.task_family,
        metadata={
            "timeline_blocks": [
                {
                    "block_id": "block.child",
                    "block_type": "child_graph",
                    "title": "子图阶段",
                    "phase_id": "phase.child",
                    "linked_graph_id": "graph.test.child",
                    "version_ref": "v1",
                    "handoff_contract_id": "contract.test.graph_unit.handoff",
                    "contract_bindings": {
                        "handoff": {"handoff_contract_id": "contract.test.graph_unit.binding_handoff"},
                        "runtime": {"resume_policy": "resume_from_checkpoint"},
                    },
                }
            ],
        },
    )

    graph_spec = compile_task_graph_definition_runtime_spec(graph=graph)
    manifest = compile_coordination_contract_manifest(
        contract_registry=contract_registry,
        coordination_task=coordination,
        graph_spec=graph_spec,
    )

    assert manifest.valid is False
    assert "contract_binding_conflict" in {item.code for item in manifest.issues}
    graph_unit_contract = manifest.graph_unit_handoff_contracts[0]
    assert graph_unit_contract.plan_id == "nested.block.child"
    assert graph_unit_contract.runtime_node_id == "graph_unit.block.child"
    assert graph_unit_contract.linked_graph_id == "graph.test.child"
    assert graph_unit_contract.handoff_contract_id == "contract.test.graph_unit.binding_handoff"
    assert graph_unit_contract.contract_refs == ("contract.test.graph_unit.binding_handoff",)
    assert graph_unit_contract.handoff_bindings["handoff_contract_id"] == "contract.test.graph_unit.binding_handoff"
    assert "contract.test.graph_unit.binding_handoff" in {item.contract_id for item in manifest.global_contracts}


def test_coordination_contract_compiler_reports_missing_graph_unit_handoff_contract(tmp_path: Path) -> None:
    contract_registry = TaskContractRegistry(tmp_path)
    _seed_coordination_contracts(contract_registry)
    coordination = CoordinationTaskDefinition(
        graph_id="graph.test.graph_unit_missing_handoff",
        title="图节点缺失交接契约",
        coordination_mode="pipeline",
        coordinator_agent_id="agent:0",
        task_family="test",
        graph_nodes=(),
        graph_edges=(),
    )
    graph = TaskGraphDefinition(
        graph_id=coordination.graph_id,
        title=coordination.title,
        graph_kind="coordination",
        task_family=coordination.task_family,
        metadata={
            "timeline_blocks": [
                {
                    "block_id": "block.child",
                    "block_type": "child_graph",
                    "linked_graph_id": "graph.test.child",
                    "version_ref": "v1",
                }
            ],
        },
    )

    graph_spec = compile_task_graph_definition_runtime_spec(graph=graph)
    manifest = compile_coordination_contract_manifest(
        contract_registry=contract_registry,
        coordination_task=coordination,
        graph_spec=graph_spec,
    )

    assert manifest.graph_unit_handoff_contracts[0].contract_refs == ()
    assert "graph_unit_handoff_contract_missing" in {item.code for item in manifest.issues}
