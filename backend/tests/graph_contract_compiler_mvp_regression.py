from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from harness.graph.context_materializer import GraphContextMaterializer
from harness.graph.flow_packet import build_flow_packet
from harness.graph.models import GraphLoopState, NodeResultEnvelope
from harness.graph.runtime import _graph_runtime_scope
from harness.graph.state_machine import GraphStateMachine
from harness.graph.supervisor import GraphSupervisor
from task_system.compiler.graph_harness_config_publisher import build_graph_harness_config_from_graph
from task_system.graphs.task_graph_models import (
    TaskGraphDefinition,
    TaskGraphEdgeDefinition,
    TaskGraphNodeDefinition,
)


def _graph() -> TaskGraphDefinition:
    return TaskGraphDefinition(
        graph_id="graph.contract_mvp",
        title="Contract MVP",
        graph_kind="multi_agent",
        entry_node_id="draft",
        output_node_id="review",
        runtime_policy={
            "task_environment_id": "env.graph",
            "project_id": "project.alpha",
        },
        nodes=(
            TaskGraphNodeDefinition(
                node_id="draft",
                node_type="agent",
                title="Draft",
                task_id="task.draft",
                agent_id="agent:writer",
                output_contract_id="contract.chapter_draft",
                contract_bindings={"schema": {"output_keys": ["draft_text"]}},
                metadata={
                    "task_environment_id": "env.writer",
                    "runtime_profile": {
                        "session_policy": {"mode": "per_node_run_session"},
                    },
                },
            ),
            TaskGraphNodeDefinition(
                node_id="review",
                node_type="agent",
                title="Review",
                task_id="task.review",
                agent_id="agent:reviewer",
                input_contract_id="contract.chapter_draft",
                output_contract_id="contract.review_result",
                contract_bindings={
                    "schema": {
                        "required_inputs": ["review_material"],
                        "output_keys": ["verdict", "issues"],
                    }
                },
                metadata={"task_environment_id": "env.review"},
            ),
        ),
        edges=(
            TaskGraphEdgeDefinition(
                edge_id="edge.draft.review",
                source_node_id="draft",
                target_node_id="review",
                edge_type="handoff",
                payload_contract_id="contract.chapter_draft",
                contract_bindings={"handoff": {"target_input_slot": "review_material"}},
            ),
        ),
    )


def test_publisher_emits_contract_indexes_and_deployment_package() -> None:
    config = build_graph_harness_config_from_graph(graph=_graph())
    contracts = dict(config.contracts or {})

    assert contracts["compile_report"]["status"] == "valid"
    assert contracts["configurator_write_contract"]["can_apply_to"] == ["draft_graph_store"]
    assert "node_interaction_contract_index" not in contracts
    assert contracts["graph_binding_contract"]["project_id"] == "project.alpha"
    assert contracts["deployment_package"]["binding"]["binding_mode"] == "project_scoped"

    draft_contract = contracts["node_contract_index"]["draft"]
    assert draft_contract["environment_lock"]["task_environment_id"] == "env.writer"
    assert draft_contract["session_policy"]["mode"] == "per_node_run_session"

    edge_contract = contracts["edge_contract_index"]["edge.draft.review"]
    assert edge_contract["protocol"]["kind"] == "node_handoff"
    assert edge_contract["packet"]["target_input_slot"] == "review_material"
    assert edge_contract["security"]["source_environment_id"] == "env.writer"
    assert edge_contract["security"]["target_environment_id"] == "env.review"


def test_state_machine_and_flow_packet_consume_edge_contract_index() -> None:
    config = build_graph_harness_config_from_graph(graph=_graph())
    edge = dict(config.edges[0])
    state = GraphLoopState(
        state_id="gstate:test",
        graph_run_id="grun:test",
        task_run_id="taskrun:test",
        session_id="session-root",
        config_id=config.config_id,
        config_hash=config.content_hash,
        graph_id=config.graph_id,
        edge_states=GraphStateMachine().initial_edge_states(config),
    )

    edge_state = state.edge_states["edge.draft.review"]
    assert edge_state["protocol_kind"] == "node_handoff"
    assert edge_state["protocol_ref"] == "edge-contract:edge.draft.review"

    result = NodeResultEnvelope(
        result_id="result:draft",
        graph_run_id=state.graph_run_id,
        task_run_id=state.task_run_id,
        node_id="draft",
        work_order_id="work:draft",
        outputs={"draft_text": "正文"},
        handoff_summary="草稿完成",
    )
    packet = build_flow_packet(
        graph_config=config,
        state=state,
        edge=edge,
        result=result,
        result_ref="rtobj:result:draft",
    )

    assert packet.packet_type == "flow_packet.node_handoff"
    assert packet.contract_id == "contract.chapter_draft"
    assert packet.target_input_slot == "review_material"
    assert packet.visibility["edge_contract_id"] == "edge-contract:edge.draft.review"


def test_materializer_uses_node_environment_and_node_session_policy() -> None:
    config = build_graph_harness_config_from_graph(graph=_graph())
    state_machine = GraphStateMachine()
    state = GraphLoopState(
        state_id="gstate:test",
        graph_run_id="grun:test",
        task_run_id="taskrun:test",
        session_id="session-root",
        config_id=config.config_id,
        config_hash=config.content_hash,
        graph_id=config.graph_id,
        node_states=state_machine.initial_node_states(config),
        edge_states=state_machine.initial_edge_states(config),
        initial_inputs={"project_id": "project.alpha"},
    )

    order = GraphContextMaterializer().build_work_order(
        graph_config=config,
        state=state,
        node=dict(config.nodes[0]),
    )

    assert order.node_session_id.startswith("gsess:")
    assert order.node_session_policy["mode"] == "per_node_run_session"
    assert order.input_package["task_environment_id"] == "env.writer"
    assert order.input_package["runtime_profile"]["task_environment_id"] == "env.writer"
    assert order.graph_slot["node_contract"]["environment_lock"]["task_environment_id"] == "env.writer"


def test_graph_runtime_scope_uses_project_binding_from_published_contract() -> None:
    config = build_graph_harness_config_from_graph(graph=_graph())

    scope = _graph_runtime_scope(
        graph_config=config,
        graph_run_id="grun:test",
        task_run_id="taskrun:test",
        initial_inputs={"project_id": "project.user.override", "runtime_scope": {"project_id": "project.runtime.override"}},
        diagnostics={"project_id": "project.diagnostic.override"},
    )

    assert scope["project_id"] == "project.alpha"
    assert scope["workspace_view"] == "project"
    assert scope["task_environment_id"] == "env.graph"
    assert scope["graph_binding_mode"] == "project_scoped"


def test_supervisor_reports_blocked_and_failed_nodes_without_mutating_contracts() -> None:
    config = build_graph_harness_config_from_graph(graph=_graph())
    state = GraphLoopState(
        state_id="gstate:test",
        graph_run_id="grun:test",
        task_run_id="taskrun:test",
        session_id="session-root",
        config_id=config.config_id,
        config_hash=config.content_hash,
        graph_id=config.graph_id,
        node_states={
            "draft": {"node_id": "draft", "status": "failed"},
            "review": {"node_id": "review", "status": "blocked"},
        },
    )

    observation = GraphSupervisor().observe(graph_config=config, state=state).to_dict()

    assert observation["status"] == "blocked"
    assert {item["code"] for item in observation["risk_alerts"]} == {"node_blocked", "node_failed"}
    failed_candidate = next(item for item in observation["maintenance_action_candidates"] if item["action"] == "requeue_failed_node")
    assert failed_candidate["requires_human_approval"] is True
    assert config.contracts["edge_contract_index"]["edge.draft.review"]["protocol"]["kind"] == "node_handoff"
