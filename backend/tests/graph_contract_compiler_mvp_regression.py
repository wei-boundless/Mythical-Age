from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from graph_system.context_materializer import GraphContextMaterializer
from graph_system.flow_edges import build_inbound_flow_edges, build_outbound_flow_edges
from graph_system.flow_packet import build_flow_packet, edge_delivers_flow_packet
from graph_system.models import GraphLoopState, GraphTransitionInput, NodeResultEnvelope
from graph_system.runtime import _graph_runtime_scope
from graph_system.state_machine import GraphStateMachine
from graph_system.supervisor import GraphSupervisor
from graph_system.transition_processor import GraphTransitionProcessor, apply_transition_plan_to_edge_states
from task_system.compiler.executable_graph_config_publisher import build_graph_config_from_graph
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


def _edge_protocol_graph() -> TaskGraphDefinition:
    node_ids = (
        "source",
        "handoff",
        "resource_read",
        "resource_write_candidate",
        "resource_commit",
        "review_feedback",
        "conditional_route",
        "event_signal",
        "audit_observation",
        "control_dependency",
        "barrier_join",
        "human_gate",
    )
    return TaskGraphDefinition(
        graph_id="graph.edge_protocol_mvp",
        title="Edge Protocol MVP",
        graph_kind="multi_agent",
        entry_node_id="source",
        output_node_id="audit_observation",
        runtime_policy={
            "task_environment_id": "env.graph",
            "project_id": "project.alpha",
        },
        nodes=tuple(
            TaskGraphNodeDefinition(
                node_id=node_id,
                node_type="agent",
                title=node_id.replace("_", " ").title(),
                task_id=f"task.{node_id}",
                agent_id=f"agent:{node_id}",
                output_contract_id=f"contract.{node_id}.output",
            )
            for node_id in node_ids
        ),
        edges=(
            TaskGraphEdgeDefinition(
                edge_id="edge.handoff",
                source_node_id="source",
                target_node_id="handoff",
                edge_type="structured_handoff",
                payload_contract_id="contract.handoff",
            ),
            TaskGraphEdgeDefinition(
                edge_id="edge.resource_read",
                source_node_id="source",
                target_node_id="resource_read",
                edge_type="memory_read",
                payload_contract_id="contract.memory_read",
            ),
            TaskGraphEdgeDefinition(
                edge_id="edge.resource_write_candidate",
                source_node_id="source",
                target_node_id="resource_write_candidate",
                edge_type="memory_write_candidate",
                payload_contract_id="contract.memory_candidate",
            ),
            TaskGraphEdgeDefinition(
                edge_id="edge.resource_commit",
                source_node_id="source",
                target_node_id="resource_commit",
                edge_type="memory_commit",
                payload_contract_id="contract.memory_commit",
            ),
            TaskGraphEdgeDefinition(
                edge_id="edge.review_feedback",
                source_node_id="source",
                target_node_id="review_feedback",
                edge_type="review_feedback",
                payload_contract_id="contract.review_feedback",
            ),
            TaskGraphEdgeDefinition(
                edge_id="edge.conditional_route",
                source_node_id="source",
                target_node_id="conditional_route",
                edge_type="conditional_feedback",
                payload_contract_id="contract.conditional_route",
            ),
            TaskGraphEdgeDefinition(
                edge_id="edge.event_signal",
                source_node_id="source",
                target_node_id="event_signal",
                edge_type="event_emit",
                payload_contract_id="contract.event",
            ),
            TaskGraphEdgeDefinition(
                edge_id="edge.audit_observation",
                source_node_id="source",
                target_node_id="audit_observation",
                edge_type="audit_report",
                payload_contract_id="contract.audit",
            ),
            TaskGraphEdgeDefinition(
                edge_id="edge.control_dependency",
                source_node_id="source",
                target_node_id="control_dependency",
                edge_type="control",
            ),
            TaskGraphEdgeDefinition(
                edge_id="edge.barrier_join",
                source_node_id="source",
                target_node_id="barrier_join",
                edge_type="barrier",
            ),
            TaskGraphEdgeDefinition(
                edge_id="edge.human_gate",
                source_node_id="source",
                target_node_id="human_gate",
                edge_type="gate",
            ),
        ),
    )


def test_publisher_emits_contract_indexes_and_deployment_package() -> None:
    config = build_graph_config_from_graph(graph=_graph())
    contracts = dict(config.contracts or {})

    assert contracts["compile_report"]["status"] == "valid"
    compile_summary = contracts["compile_report"]["summary"]
    assert compile_summary["configuration_guidance"]["configurator_system_node_id"] == "__configurator__"
    assert compile_summary["configuration_guidance"]["configurator_write_contract_id"] == f"configurator-write:{config.graph_id}"
    node_recommendations = {
        item["node_id"]: item["prototype_id"]
        for item in compile_summary["prototype_recommendations"]["nodes"]
    }
    edge_recommendations = {
        item["edge_id"]: item["prototype_id"]
        for item in compile_summary["prototype_recommendations"]["edges"]
    }
    assert node_recommendations == {"draft": "node.agent_worker", "review": "node.agent_worker"}
    assert edge_recommendations["edge.draft.review"] == "edge.node_handoff"
    assert contracts["configurator_write_contract"]["can_apply_to"] == ["draft_graph_store"]
    assert contracts["configurator_write_contract"]["output_contract"]["required_outputs"] == [
        "graph_draft_patch",
        "prototype_selection_report",
        "compiler_validation_request",
    ]
    assert {
        item["prototype_id"]
        for item in contracts["configurator_write_contract"]["prototype_catalog"]["edge_contract_prototypes"]
    } >= {"edge.node_handoff", "edge.review_feedback", "edge.human_gate", "edge.a2a_session"}
    system_nodes = contracts["system_node_contract_index"]
    assert system_nodes["__configurator__"]["prompt_contract"]["role_prompt"] == "你是一名任务图配置代理。"
    assert "graph_draft_patch" in system_nodes["__configurator__"]["prompt_contract"]["output_requirements"][1]
    assert system_nodes["__supervisor__"]["prompt_contract"]["role_prompt"] == "你是一名任务图运行监管员。"
    assert "node_interaction_contract_index" not in contracts
    assert contracts["graph_binding_contract"]["project_id"] == "project.alpha"
    assert contracts["deployment_package"]["binding"]["binding_mode"] == "project_scoped"

    draft_contract = contracts["node_contract_index"]["draft"]
    assert draft_contract["environment_lock"]["task_environment_id"] == "env.writer"
    assert draft_contract["session_policy"]["mode"] == "per_node_run_session"

    edge_contract = contracts["edge_contract_index"]["edge.draft.review"]
    assert edge_contract["protocol"]["kind"] == "node_handoff"
    assert edge_contract["packet"]["target_input_slot"] == "review_material"
    assert edge_contract["human_control"]["enabled"] is True
    assert edge_contract["human_control"]["allowed_decisions"] == ["pass", "replace"]
    assert edge_contract["security"]["source_environment_id"] == "env.writer"
    assert edge_contract["security"]["target_environment_id"] == "env.review"


def test_compiler_emits_basic_edge_protocol_packet_policies() -> None:
    config = build_graph_config_from_graph(graph=_edge_protocol_graph())
    edge_contracts = dict(config.contracts["edge_contract_index"])
    edge_recommendations = {
        item["edge_id"]: item
        for item in config.contracts["compile_report"]["summary"]["prototype_recommendations"]["edges"]
    }
    expected_protocols = {
        "edge.handoff": ("node_handoff", True),
        "edge.resource_read": ("resource_read", True),
        "edge.resource_write_candidate": ("resource_write_candidate", True),
        "edge.resource_commit": ("resource_commit", True),
        "edge.review_feedback": ("review_feedback", True),
        "edge.conditional_route": ("conditional_route", True),
        "edge.event_signal": ("event_signal", True),
        "edge.audit_observation": ("audit_observation", True),
        "edge.control_dependency": ("control_dependency", False),
        "edge.barrier_join": ("barrier_join", False),
        "edge.human_gate": ("human_gate", False),
    }

    edges_by_id = {str(edge.get("edge_id") or ""): dict(edge) for edge in config.edges}
    outbound_flow_edge_ids = {str(edge.get("edge_id") or "") for edge in build_outbound_flow_edges(config, "source")}

    for edge_id, (protocol_kind, produces_packet) in expected_protocols.items():
        contract = dict(edge_contracts[edge_id])
        protocol = dict(contract["protocol"])
        trace = dict(contract["trace"])
        packet = dict(contract.get("packet") or {})
        recommendation = dict(edge_recommendations[edge_id])
        assert protocol["kind"] == protocol_kind
        assert protocol["produces_flow_packet"] is produces_packet
        assert bool(protocol["interaction_pattern"])
        assert recommendation["prototype_id"] == f"edge.{protocol_kind}"
        assert recommendation["interaction_pattern"] == protocol["interaction_pattern"]
        human_control = dict(contract.get("human_control") or {})
        if protocol_kind == "node_handoff":
            assert human_control["enabled"] is True
            assert human_control["allowed_decisions"] == ["pass", "replace"]
            assert recommendation["human_control"]["allowed_decisions"] == ["pass", "replace"]
        elif protocol_kind in {"review_feedback", "conditional_route"}:
            assert human_control["enabled"] is True
            assert human_control["allowed_decisions"] == ["revise"]
            assert recommendation["human_control"]["allowed_decisions"] == ["revise"]
        else:
            assert human_control.get("enabled") is False
        assert trace["persist_packet"] is produces_packet
        assert edge_delivers_flow_packet(edges_by_id[edge_id], graph_config=config) is produces_packet
        if produces_packet:
            assert packet["packet_type"] == f"flow_packet.{protocol_kind}"
            assert edge_id in outbound_flow_edge_ids
            assert build_inbound_flow_edges(config, str(edges_by_id[edge_id]["target_node_id"]))
        else:
            assert "packet_type" not in packet
            assert edge_id not in outbound_flow_edge_ids
            assert not build_inbound_flow_edges(config, str(edges_by_id[edge_id]["target_node_id"]))


def test_state_machine_and_flow_packet_consume_edge_contract_index() -> None:
    config = build_graph_config_from_graph(graph=_graph())
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


def test_loop_edge_states_persist_packets_only_for_packet_protocols() -> None:
    config = build_graph_config_from_graph(graph=_edge_protocol_graph())
    state_machine = GraphStateMachine()
    state = GraphLoopState(
        state_id="gstate:test",
        graph_run_id="grun:test",
        task_run_id="taskrun:test",
        session_id="session-root",
        config_id=config.config_id,
        config_hash=config.content_hash,
        graph_id=config.graph_id,
        edge_states=state_machine.initial_edge_states(config),
    )
    result = NodeResultEnvelope(
        result_id="result:source",
        graph_run_id=state.graph_run_id,
        task_run_id=state.task_run_id,
        node_id="source",
        work_order_id="work:source",
        outputs={"payload": "ok"},
        artifact_refs=("artifact://draft",),
        memory_commit_receipts=(
            {
                "receipt_id": "memrec:1",
                "status": "committed",
                "repository_id": "memory.repo",
                "record_key": "chapter:1",
            },
        ),
        handoff_summary="source completed",
    )

    plan = GraphTransitionProcessor().plan(
        graph_config=config,
        state=state,
        trigger=GraphTransitionInput(
            trigger_type="node_result",
            graph_run_id=state.graph_run_id,
            config_id=state.config_id,
            config_hash=state.config_hash,
            payload={
                "result": result.to_dict(),
                "result_ref": "rtobj:result:source",
            },
        ),
    )
    next_edges = apply_transition_plan_to_edge_states(edge_states=state.edge_states, plan=plan)

    packet_edge_ids = {
        "edge.handoff",
        "edge.resource_read",
        "edge.resource_write_candidate",
        "edge.resource_commit",
        "edge.review_feedback",
        "edge.conditional_route",
        "edge.event_signal",
        "edge.audit_observation",
    }
    state_only_edge_ids = {"edge.control_dependency", "edge.barrier_join", "edge.human_gate"}
    for edge_id in packet_edge_ids:
        edge_state = next_edges[edge_id]
        assert edge_state["status"] == "ready"
        assert edge_state["packet_persisted"] is True
        assert edge_state["latest_packet"]["packet_type"].startswith("flow_packet.")
        assert edge_state["latest_packet_id"]
    for edge_id in state_only_edge_ids:
        edge_state = next_edges[edge_id]
        assert edge_state["status"] == "ready"
        assert edge_state["packet_persisted"] is False
        assert "latest_packet" not in edge_state
        assert "latest_packet_id" not in edge_state


def test_materializer_uses_node_environment_and_node_session_policy() -> None:
    config = build_graph_config_from_graph(graph=_graph())
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

    assert order.node_session_id.startswith("gsess-")
    assert ":" not in order.node_session_id
    assert "/" not in order.node_session_id
    assert "\\" not in order.node_session_id
    assert order.node_session_policy["mode"] == "per_node_run_session"
    assert order.input_package["task_environment_id"] == "env.writer"
    assert "runtime_profile" not in order.input_package
    assert "task_environment" not in order.input_package
    assert order.memory_view_request == {}
    assert order.file_view_request == {}
    assert order.graph_slot["node_contract"]["environment_lock"]["task_environment_id"] == "env.writer"


def test_graph_runtime_scope_uses_project_binding_from_published_contract() -> None:
    config = build_graph_config_from_graph(graph=_graph())

    scope = _graph_runtime_scope(
        graph_config=config,
        graph_run_id="grun:test",
        task_run_id="taskrun:test",
        initial_inputs={"project_id": "project.user.override", "runtime_scope": {"project_id": "project.runtime.override"}},
        diagnostics={"project_id": "project.diagnostic.override"},
    )

    assert scope["project_id"] == "project.alpha"
    assert scope["workspace_view"] == "graph_task"
    assert "task_environment_id" not in scope
    assert scope["graph_binding_mode"] == "project_scoped"


def test_supervisor_reports_blocked_and_failed_nodes_without_mutating_contracts() -> None:
    config = build_graph_config_from_graph(graph=_graph())
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
