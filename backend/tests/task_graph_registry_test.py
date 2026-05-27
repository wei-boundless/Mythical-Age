from __future__ import annotations

from pathlib import Path

import pytest

from api.task_system import _task_system_payload
from task_system.compiler.coordination_graph_compiler import compile_task_graph_definition_runtime_spec
from task_system.registry.flow_registry import TaskFlowRegistry
from task_system.graphs.task_graph_models import task_graph_from_dict, validate_task_graph
from runtime.contracts.continuation_policy import derive_stage_contracts_from_graph
from harness.loop.graph_coordination.payloads import _runtime_spec_from_payload
from runtime.graph_runtime.scheduler import bootstrap_scheduler_state


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


def test_task_graph_contract_bindings_are_canonical_over_legacy_fields() -> None:
    graph = task_graph_from_dict(
        {
            "graph_id": "graph.test.contract_binding_authority",
            "graph_contract_id": "contract.legacy.graph",
            "contract_bindings": {"schema": {"graph_contract_id": "contract.binding.graph"}},
            "nodes": [
                {
                    "node_id": "worker",
                    "node_type": "agent",
                    "agent_id": "agent:worker",
                    "input_contract_id": "contract.legacy.input",
                    "output_contract_id": "contract.legacy.output",
                    "node_contract_id": "contract.legacy.node",
                    "contract_bindings": {
                        "schema": {
                            "input_contract_id": "contract.binding.input",
                            "output_contract_id": "contract.binding.output",
                        },
                        "execution": {"node_contract_id": "contract.binding.node"},
                    },
                }
            ],
            "edges": [
                {
                    "edge_id": "edge.worker.worker",
                    "source_node_id": "worker",
                    "target_node_id": "worker",
                    "payload_contract_id": "contract.legacy.payload",
                    "contract_bindings": {"schema": {"payload_contract_id": "contract.binding.payload"}},
                }
            ],
        }
    )

    node = graph.nodes[0]
    edge = graph.edges[0]
    issue_codes = [issue.code for issue in validate_task_graph(graph)]

    assert graph.graph_contract_id == "contract.binding.graph"
    assert node.input_contract_id == "contract.binding.input"
    assert node.output_contract_id == "contract.binding.output"
    assert node.node_contract_id == "contract.binding.node"
    assert edge.payload_contract_id == "contract.binding.payload"
    assert issue_codes.count("contract_binding_conflict") == 5


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
    scheduler_support = spec.diagnostics["scheduler_support"]
    assert scheduler_support["authority"] == "task_system.scheduler_support_report"
    assert scheduler_support["partial_count"] > 0
    assert any(item["field"] == "phase_id" for item in scheduler_support["partial"])
    assert any(item["field"] == "sequence_index" for item in scheduler_support["partial"])
    assert not any(item["field"] == "sequence_index" for item in scheduler_support["supported"])
    assert any(issue.code == "scheduler_policy_partial" for issue in spec.issues)
    layered = spec.diagnostics["layered_graph"]
    assert layered["authority"] == "task_system.layered_graph_normalizer"
    assert layered["summary"]["memory_edge_count"] == 1


def test_task_graph_runtime_spec_does_not_derive_temporal_edges_from_sequence_index(tmp_path: Path) -> None:
    registry = TaskFlowRegistry(tmp_path)
    graph = registry.upsert_task_graph(
        graph_id="graph.test.no_sequence_temporal",
        title="顺序坐标不派生阻塞边",
        graph_kind="multi_agent",
        nodes=(
            {"node_id": "a", "node_type": "agent", "agent_id": "agent:a", "phase_id": "phase.work", "sequence_index": 1},
            {"node_id": "b", "node_type": "agent", "agent_id": "agent:b", "phase_id": "phase.work", "sequence_index": 2},
        ),
        edges=(),
    )

    spec = compile_task_graph_definition_runtime_spec(graph=graph)
    layered = spec.diagnostics["layered_graph"]

    assert spec.temporal_edges == ()
    assert layered["summary"]["temporal_edge_count"] == 0


def test_task_graph_runtime_spec_reports_unsupported_scheduler_policy(tmp_path: Path) -> None:
    registry = TaskFlowRegistry(tmp_path)
    graph = registry.upsert_task_graph(
        graph_id="graph.test.scheduler_support",
        title="调度支持矩阵图",
        graph_kind="multi_agent",
        nodes=(
            {
                "node_id": "a",
                "node_type": "agent",
                "agent_id": "agent:a",
                "execution_mode": "sync",
            },
            {
                "node_id": "b",
                "node_type": "agent",
                "agent_id": "agent:b",
                "wait_policy": "wait_any_upstream_completed",
                "join_policy": "quorum",
            },
        ),
        edges=(
            {
                "edge_id": "a_b",
                "source_node_id": "a",
                "target_node_id": "b",
                "failure_propagation_policy": "isolate_failure",
            },
        ),
    )

    spec = compile_task_graph_definition_runtime_spec(graph=graph)
    scheduler_support = spec.diagnostics["scheduler_support"]

    unsupported_fields = {item["field"] for item in scheduler_support["unsupported"]}
    assert "join_policy" in unsupported_fields
    supported_fields = {item["field"] for item in scheduler_support["supported"]}
    assert "wait_policy" in supported_fields
    assert "failure_propagation_policy" in supported_fields
    unsupported_values = {(item["field"], item["value"]) for item in scheduler_support["unsupported"]}
    assert ("failure_propagation_policy", "isolate_failure") not in unsupported_values
    assert any(issue.code == "scheduler_policy_unsupported" and issue.severity == "warning" for issue in spec.issues)


def test_task_graph_runtime_spec_reports_edge_temporal_support_matrix(tmp_path: Path) -> None:
    registry = TaskFlowRegistry(tmp_path)
    graph = registry.upsert_task_graph(
        graph_id="graph.test.edge_temporal_support",
        title="边时序支持矩阵图",
        graph_kind="multi_agent",
        nodes=(
            {"node_id": "a", "node_type": "agent", "agent_id": "agent:a"},
            {"node_id": "b", "node_type": "agent", "agent_id": "agent:b"},
        ),
        edges=(
            {
                "edge_id": "a_b",
                "source_node_id": "a",
                "target_node_id": "b",
                "wait_policy": "wait_handoff_ack",
                "ack_required": True,
                "ack_policy": "explicit_ack",
                "metadata": {
                    "temporal_semantics": {
                        "trigger_timing": "after_source_success",
                        "visibility_timing": "same_clock",
                        "acknowledgement_timing": "ack_before_phase_exit",
                        "propagation_timing": "manual_release",
                    }
                },
            },
        ),
    )

    spec = compile_task_graph_definition_runtime_spec(graph=graph)
    scheduler_support = spec.diagnostics["scheduler_support"]
    supported = {(item["field"], item["value"]) for item in scheduler_support["supported"]}
    partial = {(item["field"], item["value"]) for item in scheduler_support["partial"]}
    unsupported = {(item["field"], item["value"]) for item in scheduler_support["unsupported"]}

    assert ("wait_policy", "wait_handoff_ack") in supported
    assert ("ack_policy", "explicit_ack") in supported
    assert ("temporal.trigger_timing", "after_source_success") in supported
    assert ("temporal.visibility_timing", "same_clock") in partial
    assert ("temporal.acknowledgement_timing", "ack_before_phase_exit") in partial
    assert ("temporal.propagation_timing", "manual_release") in partial
    assert ("temporal.trigger_timing", "after_source_success") not in unsupported
    assert any(issue.code == "scheduler_policy_partial" and issue.edge_id == "a_b" for issue in spec.issues)


def test_task_graph_runtime_spec_exposes_layered_graph_diagnostics(tmp_path: Path) -> None:
    registry = TaskFlowRegistry(tmp_path)
    graph = registry.upsert_task_graph(
        graph_id="graph.test.layered",
        title="分层图编译验证",
        graph_kind="coordination",
        nodes=(
            {
                "node_id": "memory.requirements",
                "node_type": "memory_repository",
                "title": "需求记忆库",
                "resource_lifecycle_policy": {
                    "versioning": "append_version",
                    "mutable": True,
                    "write_owner_node_ids": ["commit"],
                },
                "metadata": {"collections": ["accepted_requirements"]},
            },
            {
                "node_id": "draft",
                "node_type": "agent",
                "title": "起草",
                "agent_id": "agent:writer",
                "phase_id": "phase.write",
                "sequence_index": 1,
            },
            {
                "node_id": "review",
                "node_type": "review_gate",
                "title": "审核",
                "agent_id": "agent:reviewer",
                "phase_id": "phase.write",
                "sequence_index": 2,
                "review_gate_policy": {"is_review_gate": True},
            },
            {
                "node_id": "commit",
                "node_type": "agent",
                "title": "提交",
                "agent_id": "agent:memory",
                "phase_id": "phase.commit",
                "sequence_index": 1,
            },
        ),
        edges=(
            {
                "edge_id": "memory.read.draft",
                "source_node_id": "memory.requirements",
                "target_node_id": "draft",
                "edge_type": "memory_read",
                "metadata": {
                    "repository": "memory.requirements",
                    "collection": "accepted_requirements",
                    "version_selector": "latest_committed_before_stage_start",
                },
            },
            {
                "edge_id": "draft.review.artifact",
                "source_node_id": "draft",
                "target_node_id": "review",
                "edge_type": "artifact_context",
                "artifact_ref_policy": {
                    "source_output_key": "draft:artifact_refs",
                    "target_input_key": "candidate_ref",
                    "max_chars": 12000,
                },
                "metadata": {"context_mode": "expand_text_for_model"},
            },
            {
                "edge_id": "review.draft.revision",
                "source_node_id": "review",
                "target_node_id": "draft",
                "edge_type": "revision_request",
                "metadata": {
                    "trigger": {"verdict": "revise"},
                    "carry": [
                        {"source": "current_output", "target_input_key": "previous_review_ref"},
                        {"source": "inherited_input", "target_input_key": "previous_candidate_ref"},
                    ],
                },
            },
            {
                "edge_id": "commit.memory.write",
                "source_node_id": "commit",
                "target_node_id": "memory.requirements",
                "edge_type": "memory_write",
                "metadata": {
                    "repository": "memory.requirements",
                    "collection": "accepted_requirements",
                    "effective_from": "next_stage",
                },
            },
        ),
    )

    spec = compile_task_graph_definition_runtime_spec(graph=graph)
    layered = spec.diagnostics["layered_graph"]

    assert layered["authority"] == "task_system.layered_graph_normalizer"
    assert layered["summary"]["resource_node_count"] == 1
    assert layered["summary"]["memory_edge_count"] == 2
    assert layered["summary"]["artifact_context_edge_count"] == 1
    assert layered["summary"]["revision_edge_count"] == 1
    assert layered["resource_nodes"][0]["node_id"] == "memory.requirements"
    assert layered["resource_nodes"][0]["collections"] == ["accepted_requirements"]
    assert layered["memory_edges"][0]["memory_edge_type"] == "read"
    assert layered["artifact_context_edges"][0]["context_mode"] == "expand_text_for_model"
    assert layered["revision_edges"][0]["carry"]
    assert spec.resource_nodes[0]["node_id"] == "memory.requirements"
    assert spec.memory_edges[0]["memory_edge_type"] == "read"
    assert spec.artifact_context_edges[0]["context_mode"] == "expand_text_for_model"
    assert spec.revision_edges[0]["edge_id"] == "review.draft.revision"
    assert spec.memory_matrix["authority"] == "task_system.timeline_memory_matrix"
    restored = _runtime_spec_from_payload(spec.to_dict())
    assert restored is not None
    assert restored.resource_nodes == spec.resource_nodes
    assert restored.memory_edges == spec.memory_edges
    assert restored.artifact_context_edges == spec.artifact_context_edges
    assert restored.revision_edges == spec.revision_edges
    assert any(
        cell["phase_id"] == "phase.write"
        and cell["resource_node_id"] == "memory.requirements"
        and "read" in cell["operations"]
        for cell in layered["memory_matrix"]["cells"]
    )
    assert not any(issue.code.startswith("layered_graph_") and issue.severity == "error" for issue in spec.issues)


def test_task_graph_feedback_edge_does_not_block_initial_forward_stage(tmp_path: Path) -> None:
    registry = TaskFlowRegistry(tmp_path)
    graph = registry.upsert_task_graph(
        graph_id="graph.test.feedback_loop",
        title="反馈返修图",
        graph_kind="coordination",
        entry_node_id="plan",
        nodes=(
            {
                "node_id": "plan",
                "node_type": "agent",
                "title": "规划",
                "task_id": "task.test.plan",
                "agent_id": "agent:planner",
                "phase_id": "phase.plan",
                "sequence_index": 1,
            },
            {
                "node_id": "draft",
                "node_type": "agent",
                "title": "起草",
                "task_id": "task.test.draft",
                "agent_id": "agent:writer",
                "phase_id": "phase.draft",
                "sequence_index": 1,
            },
            {
                "node_id": "quality",
                "node_type": "review_gate",
                "title": "质量门",
                "task_id": "task.test.quality",
                "agent_id": "agent:reviewer",
                "phase_id": "phase.review",
                "sequence_index": 1,
            },
        ),
        edges=(
            {
                "edge_id": "edge.plan.draft",
                "source_node_id": "plan",
                "target_node_id": "draft",
                "payload_contract_id": "contract.plan",
            },
            {
                "edge_id": "edge.draft.quality",
                "source_node_id": "draft",
                "target_node_id": "quality",
                "payload_contract_id": "contract.draft",
            },
            {
                "edge_id": "edge.quality.plan",
                "source_node_id": "quality",
                "target_node_id": "plan",
                "edge_type": "review_feedback",
                "payload_contract_id": "contract.quality",
                "metadata": {"dependency_role": "conditional_feedback", "loop_role": "repair"},
            },
        ),
    )
    spec = compile_task_graph_definition_runtime_spec(graph=graph)

    scheduler = bootstrap_scheduler_state(runtime_spec=spec, mode="active")
    contracts = derive_stage_contracts_from_graph(coordination_task=graph, topology_nodes=[node.to_dict() for node in spec.nodes], topology_edges=[edge.to_dict() for edge in spec.edges])
    plan_contract = next(contract for contract in contracts if contract.stage_id == "plan")

    assert scheduler.ready_node_ids == ("plan",)
    assert plan_contract.required_inputs == ()


def test_task_graph_backward_repair_edge_does_not_block_first_judge_pass(tmp_path: Path) -> None:
    registry = TaskFlowRegistry(tmp_path)
    graph = registry.upsert_task_graph(
        graph_id="graph.test.backward_repair",
        title="返修回裁判图",
        graph_kind="coordination",
        nodes=(
            {
                "node_id": "proposal_a",
                "node_type": "agent",
                "title": "方案 A",
                "task_id": "task.test.proposal_a",
                "agent_id": "agent:a",
            },
            {
                "node_id": "proposal_b",
                "node_type": "agent",
                "title": "方案 B",
                "task_id": "task.test.proposal_b",
                "agent_id": "agent:b",
            },
            {
                "node_id": "judge",
                "node_type": "review_gate",
                "title": "裁判",
                "task_id": "task.test.judge",
                "agent_id": "agent:judge",
            },
            {
                "node_id": "repair_a",
                "node_type": "agent",
                "title": "返修 A",
                "task_id": "task.test.repair_a",
                "agent_id": "agent:a",
            },
            {
                "node_id": "repair_b",
                "node_type": "agent",
                "title": "返修 B",
                "task_id": "task.test.repair_b",
                "agent_id": "agent:b",
            },
        ),
        edges=(
            {
                "edge_id": "edge.a.judge",
                "source_node_id": "proposal_a",
                "target_node_id": "judge",
                "payload_contract_id": "contract.proposal_a",
            },
            {
                "edge_id": "edge.b.judge",
                "source_node_id": "proposal_b",
                "target_node_id": "judge",
                "payload_contract_id": "contract.proposal_b",
            },
            {
                "edge_id": "edge.judge.repair_a",
                "source_node_id": "judge",
                "target_node_id": "repair_a",
                "edge_type": "review_feedback",
                "payload_contract_id": "contract.judge",
            },
            {
                "edge_id": "edge.judge.repair_b",
                "source_node_id": "judge",
                "target_node_id": "repair_b",
                "edge_type": "review_feedback",
                "payload_contract_id": "contract.judge",
            },
            {
                "edge_id": "edge.repair_a.judge",
                "source_node_id": "repair_a",
                "target_node_id": "judge",
                "payload_contract_id": "contract.repair_a",
            },
            {
                "edge_id": "edge.repair_b.judge",
                "source_node_id": "repair_b",
                "target_node_id": "judge",
                "payload_contract_id": "contract.repair_b",
            },
        ),
    )
    spec = compile_task_graph_definition_runtime_spec(graph=graph)

    scheduler = bootstrap_scheduler_state(
        runtime_spec=spec,
        node_statuses={"proposal_a": "completed", "proposal_b": "completed"},
        mode="active",
    )
    contracts = derive_stage_contracts_from_graph(
        coordination_task=graph,
        topology_nodes=[node.to_dict() for node in spec.nodes],
        topology_edges=[edge.to_dict() for edge in spec.edges],
    )
    judge_contract = next(contract for contract in contracts if contract.stage_id == "judge")

    assert "judge" in scheduler.ready_node_ids
    assert judge_contract.required_inputs == (
        "contract.proposal_a:artifact_refs",
        "contract.proposal_b:artifact_refs",
    )

    after_judge = bootstrap_scheduler_state(
        runtime_spec=spec,
        node_statuses={
            "proposal_a": "completed",
            "proposal_b": "completed",
            "judge": "completed",
        },
        mode="active",
    )

    assert "repair_a" not in after_judge.ready_node_ids
    assert "repair_b" not in after_judge.ready_node_ids


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


def test_task_graph_node_rejects_raw_model_secret_in_contract_binding() -> None:
    with pytest.raises(ValueError, match="credential_ref"):
        task_graph_from_dict(
            {
                "graph_id": "graph.test.model_requirement_secret",
                "nodes": [
                    {
                        "node_id": "writer",
                        "node_type": "agent",
                        "agent_id": "agent:0",
                        "contract_bindings": {
                            "runtime": {
                                "model_requirement": {
                                    "profile_ref": "writer_long",
                                    "api_key": "must_fail_closed",
                                }
                            }
                        },
                    }
                ],
            }
        )


def test_task_graph_node_model_requirement_is_contract_binding_only() -> None:
    graph = task_graph_from_dict(
        {
            "graph_id": "graph.test.model_requirement",
            "nodes": [
                {
                    "node_id": "writer",
                    "node_type": "agent",
                    "agent_id": "agent:0",
                    "contract_bindings": {
                        "runtime": {
                            "model_requirement": {
                                "profile_ref": "writer_long",
                                "preferred_output_tokens": 65536,
                                "provider": "should_be_pruned",
                            }
                        }
                    },
                }
            ],
        }
    )

    requirement = graph.nodes[0].contract_bindings["runtime"]["model_requirement"]

    assert requirement["profile_ref"] == "writer_long"
    assert requirement["preferred_output_tokens"] == 65536
    assert "provider" not in requirement


def test_task_graph_runtime_spec_includes_model_resolution_summary() -> None:
    graph = task_graph_from_dict(
        {
            "graph_id": "graph.test.model_resolution",
            "nodes": [
                {
                    "node_id": "writer",
                    "node_type": "agent",
                    "agent_id": "agent:0",
                    "contract_bindings": {
                        "runtime": {
                            "model_requirement": {
                                "profile_ref": "main",
                                "preferred_output_tokens": 65536,
                                "thinking_mode": "disabled",
                            }
                        }
                    },
                }
            ],
        }
    )

    spec = compile_task_graph_definition_runtime_spec(graph=graph)
    node = spec.nodes[0]
    resolution = node.metadata["model_resolution"]

    assert node.metadata["model_requirement"]["preferred_output_tokens"] == 65536
    assert resolution["provider"]
    assert resolution["credential_configured"] in {True, False}
    assert "api_key" not in str(resolution).lower()
