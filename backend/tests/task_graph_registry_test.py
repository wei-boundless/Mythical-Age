from __future__ import annotations

from pathlib import Path

from api.tasks import _task_system_payload
from tasks.coordination_graph_compiler import compile_task_graph_definition_runtime_spec
from tasks.flow_registry import TaskFlowRegistry
from tasks.task_graph_models import task_graph_from_dict, validate_task_graph


def test_task_graph_registry_round_trips_single_agent_graph(tmp_path: Path) -> None:
    registry = TaskFlowRegistry(tmp_path)

    graph = registry.upsert_task_graph(
        graph_id="graph.test.single_agent",
        title="测试单 Agent 图",
        graph_kind="single_agent",
        nodes=(
            {"node_id": "input", "node_type": "input", "title": "输入"},
            {"node_id": "agent", "node_type": "agent", "title": "主 Agent", "agent_id": "agent:0"},
            {"node_id": "output", "node_type": "output", "title": "输出"},
        ),
        edges=(
            {"edge_id": "edge_input_agent", "source_node_id": "input", "target_node_id": "agent"},
            {"edge_id": "edge_agent_output", "source_node_id": "agent", "target_node_id": "output", "edge_type": "finalize"},
        ),
    )

    assert graph.valid is True
    assert graph.entry_node_id == "input"
    assert graph.output_node_id == "output"

    loaded = registry.get_task_graph("graph.test.single_agent")
    assert loaded is not None
    assert loaded.graph_kind == "single_agent"
    assert len(loaded.nodes) == 3
    assert len(loaded.edges) == 2


def test_task_system_overview_exposes_task_graph_management(tmp_path: Path) -> None:
    TaskFlowRegistry(tmp_path).upsert_task_graph(
        graph_id="graph.test.single_agent",
        title="测试单 Agent 图",
        graph_kind="single_agent",
        nodes=(
            {"node_id": "input", "node_type": "input", "title": "输入"},
            {"node_id": "agent", "node_type": "agent", "title": "主 Agent", "agent_id": "agent:0"},
            {"node_id": "output", "node_type": "output", "title": "输出"},
        ),
        edges=(
            {"edge_id": "edge_input_agent", "source_node_id": "input", "target_node_id": "agent"},
            {"edge_id": "edge_agent_output", "source_node_id": "agent", "target_node_id": "output", "edge_type": "finalize"},
        ),
    )

    payload = _task_system_payload(tmp_path)

    assert payload["summary"]["task_graph_count"] == 1
    assert payload["task_graph_management"]["task_graphs"][0]["graph_id"] == "graph.test.single_agent"


def test_task_graph_round_trips_working_memory_policies(tmp_path: Path) -> None:
    registry = TaskFlowRegistry(tmp_path)

    graph = registry.upsert_task_graph(
        graph_id="graph.test.working_memory",
        title="工作记忆策略图",
        graph_kind="multi_agent",
        working_memory_policy_profile_id="wmprofile.test",
        working_memory_policy={
            "enabled": True,
            "default_scope": "graph_scope",
            "dynamic_read_default": "runloop_approved",
        },
        nodes=(
            {
                "node_id": "planner",
                "node_type": "agent",
                "title": "规划节点",
                "agent_id": "agent:planner",
                "memory_read_policy": {
                    "readable_kinds": ["task_goal", "decision_record"],
                    "readable_scopes": ["graph_scope"],
                },
                "memory_writeback_policy": {
                    "writable_kinds": ["plan_fragment"],
                    "writable_scopes": ["node_scope"],
                },
                "dynamic_memory_read_policy": {
                    "allow_dynamic_read": True,
                    "max_dynamic_reads_per_node_run": 2,
                },
            },
            {
                "node_id": "writer",
                "node_type": "agent",
                "title": "写作节点",
                "agent_id": "agent:writer",
            },
        ),
        edges=(
            {
                "edge_id": "planner_to_writer",
                "source_node_id": "planner",
                "target_node_id": "writer",
                "working_memory_handoff_policy": {
                    "carry_kinds": ["plan_fragment"],
                    "carry_scopes": ["handoff_only"],
                    "summary_only": True,
                },
            },
        ),
    )

    assert graph.valid is True
    assert graph.working_memory_policy_profile_id == "wmprofile.test"
    assert graph.runtime_policy["working_memory_profile_id"] == "wmprofile.test"

    loaded = registry.get_task_graph("graph.test.working_memory")
    assert loaded is not None
    planner = next(node for node in loaded.nodes if node.node_id == "planner")
    edge = loaded.edges[0]

    assert loaded.working_memory_policy["default_scope"] == "graph_scope"
    assert planner.memory_read_policy["readable_kinds"] == ["task_goal", "decision_record"]
    assert planner.memory_writeback_policy["writable_kinds"] == ["plan_fragment"]
    assert planner.dynamic_memory_read_policy["max_dynamic_reads_per_node_run"] == 2
    assert edge.working_memory_handoff_policy["carry_kinds"] == ["plan_fragment"]


def test_task_graph_warns_when_temporal_expansion_has_no_limit() -> None:
    graph = task_graph_from_dict(
        {
            "graph_id": "graph.test.temporal_limit",
            "nodes": [
                {
                    "node_id": "writer",
                    "node_type": "agent",
                    "agent_id": "agent:writer",
                    "dynamic_memory_read_policy": {
                        "allow_dynamic_read": True,
                        "max_dynamic_reads_per_node_run": 2,
                        "allow_temporal_expansion": True,
                    },
                }
            ],
        }
    )

    issue_codes = {issue.code for issue in validate_task_graph(graph)}

    assert "node_temporal_expansion_limit_missing" in issue_codes


def test_task_graph_round_trips_agent_dispatch_policy(tmp_path: Path) -> None:
    registry = TaskFlowRegistry(tmp_path)

    graph = registry.upsert_task_graph(
        graph_id="graph.test.dispatch_policy",
        title="Agent 调度策略图",
        graph_kind="multi_agent",
        nodes=(
            {
                "node_id": "world",
                "node_type": "agent",
                "title": "世界观",
                "agent_id": "agent:world",
                "execution_mode": "parallel",
                "dispatch_group": "planning",
                "wait_policy": "wait_all_upstream_completed",
                "join_policy": "all_success",
            },
            {
                "node_id": "memory_curator",
                "node_type": "agent",
                "title": "记忆整理",
                "agent_id": "agent:memory",
                "execution_mode": "background",
                "background_policy": {
                    "enabled": True,
                    "blocks_downstream": False,
                    "max_runtime_seconds": 900,
                    "kill_on_parent_abort": True,
                },
                "notification_policy": {
                    "on_completed": "queued_summary",
                    "priority": "later",
                },
                "resource_lifecycle_policy": {
                    "cleanup_on_terminal": True,
                },
            },
            {
                "node_id": "join",
                "node_type": "barrier",
                "title": "规划汇合",
                "execution_mode": "barrier",
                "wait_policy": "wait_all_upstream_completed",
                "join_policy": "all_success",
            },
        ),
        edges=(
            {
                "edge_id": "world_join",
                "source_node_id": "world",
                "target_node_id": "join",
                "wait_policy": "wait_handoff_ack",
                "ack_required": True,
                "failure_propagation_policy": "coordinator_decides",
                "result_delivery_policy": "contract_payload_and_refs",
            },
            {
                "edge_id": "memory_join",
                "source_node_id": "memory_curator",
                "target_node_id": "join",
                "wait_policy": "fire_and_continue",
                "ack_required": False,
                "failure_propagation_policy": "isolate_failure",
                "result_delivery_policy": "summary_and_refs",
            },
        ),
    )

    assert graph.valid is True

    loaded = registry.get_task_graph("graph.test.dispatch_policy")

    assert loaded is not None
    world = next(node for node in loaded.nodes if node.node_id == "world")
    memory = next(node for node in loaded.nodes if node.node_id == "memory_curator")
    edge = next(edge for edge in loaded.edges if edge.edge_id == "memory_join")

    assert world.execution_mode == "parallel"
    assert world.dispatch_group == "planning"
    assert memory.execution_mode == "background"
    assert memory.background_policy["max_runtime_seconds"] == 900
    assert memory.notification_policy["on_completed"] == "queued_summary"
    assert edge.wait_policy == "fire_and_continue"
    assert edge.ack_required is False
    assert edge.failure_propagation_policy == "isolate_failure"
    assert edge.result_delivery_policy == "summary_and_refs"


def test_task_graph_round_trips_timeline_review_and_artifact_policies(tmp_path: Path) -> None:
    registry = TaskFlowRegistry(tmp_path)

    registry.upsert_task_graph(
        graph_id="graph.test.timeline_artifact",
        title="时序产物图",
        graph_kind="multi_agent",
        nodes=(
            {
                "node_id": "draft",
                "node_type": "agent",
                "title": "起草",
                "agent_id": "agent:writer",
                "phase_id": "drafting",
                "sequence_index": 1,
                "timeline_group_id": "main",
                "blocks_phase_exit": True,
                "artifact_target": "chapters/chapter_001_draft.md",
                "artifact_policy": {"required": True},
            },
            {
                "node_id": "review",
                "node_type": "review_gate",
                "title": "审核",
                "agent_id": "agent:reviewer",
                "phase_id": "review",
                "sequence_index": 2,
                "review_gate_policy": {"is_review_gate": True, "on_fail": "draft", "on_pass": "publish"},
                "loop_policy": {"max_attempts": 2},
            },
        ),
        edges=(
            {
                "edge_id": "draft_review",
                "source_node_id": "draft",
                "target_node_id": "review",
            },
        ),
    )

    loaded = registry.get_task_graph("graph.test.timeline_artifact")

    assert loaded is not None
    draft = next(node for node in loaded.nodes if node.node_id == "draft")
    review = next(node for node in loaded.nodes if node.node_id == "review")
    assert draft.phase_id == "drafting"
    assert draft.sequence_index == 1
    assert draft.artifact_target == "chapters/chapter_001_draft.md"
    assert draft.artifact_policy["required"] is True
    assert review.review_gate_policy["is_review_gate"] is True
    assert review.loop_policy["max_attempts"] == 2


def test_task_graph_definition_compiles_direct_runtime_spec_with_policy_diagnostics(tmp_path: Path) -> None:
    registry = TaskFlowRegistry(tmp_path)
    graph = registry.upsert_task_graph(
        graph_id="graph.test.direct_compile",
        title="直接编译图",
        domain_id="domain.story",
        task_family="story",
        graph_kind="multi_agent",
        graph_contract_id="contract.story.graph",
        default_protocol_id="protocol.story",
        runtime_policy={
            "coordinator_agent_id": "agent:coordinator",
            "agent_group_id": "group.story",
            "default_execution_mode": "parallel",
            "default_wait_policy": "wait_required_contracts",
            "participant_agent_ids": ["agent:writer", "agent:reviewer"],
        },
        context_policy={"shared_context_policy": "shared_task_context"},
        working_memory_policy_profile_id="wmprofile.story",
        working_memory_policy={"default_scope": "graph_scope"},
        metadata={
            "artifact_policy": {"enabled": True},
            "timeline_policy": {"scheduling_mode": "phase_then_sequence_index"},
        },
        nodes=(
            {
                "node_id": "draft",
                "node_type": "agent",
                "title": "起草",
                "agent_id": "agent:writer",
                "phase_id": "drafting",
                "sequence_index": 1,
                "memory_read_policy": {"readable_kinds": ["task_goal"]},
                "artifact_policy": {"required": True},
                "artifact_target": "draft.md",
            },
            {
                "node_id": "review",
                "node_type": "review_gate",
                "title": "审核",
                "agent_id": "agent:reviewer",
                "phase_id": "review",
                "sequence_index": 2,
                "review_gate_policy": {"is_review_gate": True},
            },
        ),
        edges=(
            {
                "edge_id": "draft_review",
                "source_node_id": "draft",
                "target_node_id": "review",
                "payload_contract_id": "contract.story.payload",
                "wait_policy": "wait_handoff_ack",
                "ack_required": True,
                "working_memory_handoff_policy": {"carry_kinds": ["draft_artifact"]},
            },
        ),
    )

    spec = compile_task_graph_definition_runtime_spec(graph=graph)

    assert spec.graph_id == "graph.test.direct_compile"
    assert spec.coordinator_agent_id == "agent:coordinator"
    assert spec.agent_group_id == "group.story"
    assert spec.start_node_ids == ("draft",)
    assert spec.terminal_node_ids == ("review",)
    assert spec.diagnostics["source"] == "task_system.task_graph_definition_runtime_compiler"
    assert spec.diagnostics["graph_contract_id"] == "contract.story.graph"
    assert spec.diagnostics["working_memory_policy_profile_id"] == "wmprofile.story"
    draft = next(node for node in spec.nodes if node.node_id == "draft")
    review = next(node for node in spec.nodes if node.node_id == "review")
    edge = spec.edges[0]
    assert draft.execution_mode == "parallel"
    assert draft.wait_policy == "wait_required_contracts"
    assert draft.phase_id == "drafting"
    assert draft.artifact_policy["artifact_target"] == "draft.md"
    assert review.review_gate_policy["is_review_gate"] is True
    assert edge.payload_contract_id == "contract.story.payload"
    assert edge.working_memory_handoff_policy["carry_kinds"] == ["draft_artifact"]


def test_task_graph_dispatch_policy_fails_closed_for_invalid_or_unsafe_modes() -> None:
    graph = task_graph_from_dict(
        {
            "graph_id": "graph.test.invalid_dispatch",
            "nodes": [
                {
                    "node_id": "bad_mode",
                    "node_type": "agent",
                    "agent_id": "agent:bad",
                    "execution_mode": "daemon",
                },
                {
                    "node_id": "parallel_without_group",
                    "node_type": "agent",
                    "agent_id": "agent:parallel",
                    "execution_mode": "parallel",
                },
                {
                    "node_id": "unsafe_background",
                    "node_type": "agent",
                    "agent_id": "agent:bg",
                    "execution_mode": "background",
                    "background_policy": {"enabled": True},
                },
                {
                    "node_id": "floating_barrier",
                    "node_type": "barrier",
                    "execution_mode": "barrier",
                    "wait_policy": "fire_and_continue",
                },
            ],
            "edges": [
                {
                    "edge_id": "bad_edge_policy",
                    "source_node_id": "bad_mode",
                    "target_node_id": "parallel_without_group",
                    "wait_policy": "eventually",
                    "failure_propagation_policy": "ignore_everything",
                    "result_delivery_policy": "raw_private_context",
                }
            ],
        }
    )

    issue_codes = {issue.code for issue in validate_task_graph(graph)}

    assert "node_execution_mode_invalid" in issue_codes
    assert "parallel_node_dispatch_group_missing" in issue_codes
    assert "background_node_timeout_missing" in issue_codes
    assert "background_node_notification_policy_missing" in issue_codes
    assert "barrier_node_wait_policy_invalid" in issue_codes
    assert "barrier_node_missing_upstream" in issue_codes
    assert "edge_wait_policy_invalid" in issue_codes
    assert "edge_failure_propagation_policy_invalid" in issue_codes
    assert "edge_result_delivery_policy_invalid" in issue_codes
    assert graph.valid is False
