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
