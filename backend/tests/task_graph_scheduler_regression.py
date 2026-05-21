from __future__ import annotations

from orchestration.runtime_loop.task_graph_scheduler import bootstrap_scheduler_state
from tasks.coordination_graph_models import TaskGraphRuntimeEdge, TaskGraphRuntimeNode, TaskGraphRuntimeSpec


def _runtime_spec() -> TaskGraphRuntimeSpec:
    return TaskGraphRuntimeSpec(
        graph_id="graph.test.scheduler",
        domain_id="domain.test",
        task_family="test",
        coordinator_agent_id="agent:0",
        nodes=(
            TaskGraphRuntimeNode(
                node_id="plan",
                title="规划",
                node_type="agent",
                role="planner",
                agent_id="agent:planner",
                phase_id="phase.plan",
                sequence_index=1,
            ),
            TaskGraphRuntimeNode(
                node_id="draft",
                title="起草",
                node_type="agent",
                role="writer",
                agent_id="agent:writer",
                phase_id="phase.write",
                sequence_index=2,
            ),
            TaskGraphRuntimeNode(
                node_id="review",
                title="审核",
                node_type="review_gate",
                role="reviewer",
                agent_id="agent:reviewer",
                phase_id="phase.write",
                sequence_index=3,
                wait_policy="wait_all_upstream_completed",
                review_gate_policy={"is_review_gate": True},
            ),
        ),
        edges=(
            TaskGraphRuntimeEdge(
                edge_id="plan_draft",
                source_node_id="plan",
                target_node_id="draft",
                mode="handoff",
                ack_required=True,
            ),
            TaskGraphRuntimeEdge(
                edge_id="draft_review",
                source_node_id="draft",
                target_node_id="review",
                mode="handoff",
                ack_required=True,
            ),
        ),
        start_node_ids=("plan",),
        terminal_node_ids=("review",),
    )


def test_scheduler_bootstrap_marks_downstream_ready_after_upstream_completed() -> None:
    state = bootstrap_scheduler_state(
        runtime_spec=_runtime_spec(),
        node_statuses={"plan": "completed", "draft": "pending", "review": "pending"},
    )

    assert state.ready_node_ids == ("draft",)
    assert state.blocked_node_ids == ("review",)
    draft = next(item for item in state.node_states if item.node_id == "draft")
    review = next(item for item in state.node_states if item.node_id == "review")
    assert draft.status == "ready"
    assert "upstream:draft" in review.blocked_reasons
    assert "sequence_wait:2" in review.blocked_reasons
    edge = next(item for item in state.edge_states if item.edge_id == "plan_draft")
    assert edge.status == "ack_waiting"


def test_scheduler_blocks_wait_handoff_ack_until_edge_acknowledged() -> None:
    spec = TaskGraphRuntimeSpec(
        graph_id="graph.test.handoff_ack",
        domain_id="domain.test",
        task_family="test",
        coordinator_agent_id="agent:0",
        nodes=(
            TaskGraphRuntimeNode(node_id="source", title="Source", node_type="agent", role="worker"),
            TaskGraphRuntimeNode(node_id="target", title="Target", node_type="agent", role="worker"),
        ),
        edges=(
            TaskGraphRuntimeEdge(
                edge_id="source_target",
                source_node_id="source",
                target_node_id="target",
                mode="handoff",
                wait_policy="wait_handoff_ack",
                ack_required=True,
            ),
        ),
        start_node_ids=("source",),
        terminal_node_ids=("target",),
    )

    missing = bootstrap_scheduler_state(
        runtime_spec=spec,
        node_statuses={"source": "completed", "target": "pending"},
    )
    target = next(item for item in missing.node_states if item.node_id == "target")

    assert "target" in missing.blocked_node_ids
    assert "handoff_ack_missing:source_target" in target.blocked_reasons

    waiting = bootstrap_scheduler_state(
        runtime_spec=spec,
        node_statuses={"source": "completed", "target": "pending"},
        edge_handoff_index={
            "source_target": {
                "handoff_id": "handoff:source_target",
                "edge_id": "source_target",
                "ack_state": "pending",
            }
        },
    )
    target = next(item for item in waiting.node_states if item.node_id == "target")

    assert "target" in waiting.blocked_node_ids
    assert "handoff_ack_waiting:source_target" in target.blocked_reasons

    acknowledged = bootstrap_scheduler_state(
        runtime_spec=spec,
        node_statuses={"source": "completed", "target": "pending"},
        edge_handoff_index={
            "source_target": {
                "handoff_id": "handoff:source_target",
                "edge_id": "source_target",
                "ack_state": "acknowledged",
            }
        },
    )

    assert acknowledged.ready_node_ids == ("target",)
    edge = next(item for item in acknowledged.edge_states if item.edge_id == "source_target")
    assert edge.status == "acknowledged"
    assert edge.diagnostics["handoff_ack_state"] == "acknowledged"


def test_scheduler_does_not_require_ack_for_plain_completed_upstream() -> None:
    spec = TaskGraphRuntimeSpec(
        graph_id="graph.test.no_ack_gate",
        domain_id="domain.test",
        task_family="test",
        coordinator_agent_id="agent:0",
        nodes=(
            TaskGraphRuntimeNode(node_id="source", title="Source", node_type="agent", role="worker"),
            TaskGraphRuntimeNode(node_id="target", title="Target", node_type="agent", role="worker"),
        ),
        edges=(
            TaskGraphRuntimeEdge(
                edge_id="source_target",
                source_node_id="source",
                target_node_id="target",
                mode="handoff",
                ack_required=True,
            ),
        ),
        start_node_ids=("source",),
        terminal_node_ids=("target",),
    )

    state = bootstrap_scheduler_state(
        runtime_spec=spec,
        node_statuses={"source": "completed", "target": "pending"},
    )

    assert state.ready_node_ids == ("target",)
    assert "target" not in state.blocked_node_ids


def test_scheduler_blocks_completed_upstream_without_timeline_result_when_gate_enabled() -> None:
    state = bootstrap_scheduler_state(
        runtime_spec=_runtime_spec(),
        node_statuses={"plan": "completed", "draft": "pending", "review": "pending"},
        result_record_index={},
        accepted_result_records_by_scope={},
        active_scope_key="run",
    )

    assert "draft" in state.blocked_node_ids
    assert "draft" not in state.ready_node_ids
    draft = next(item for item in state.node_states if item.node_id == "draft")
    assert "timeline_result_missing:plan" in draft.blocked_reasons
    edge = next(item for item in state.edge_states if item.edge_id == "plan_draft")
    assert edge.status == "timeline_waiting"


def test_scheduler_releases_downstream_with_current_scope_timeline_result() -> None:
    state = bootstrap_scheduler_state(
        runtime_spec=_runtime_spec(),
        node_statuses={"plan": "completed", "draft": "pending", "review": "pending"},
        result_record_index={
            "tlresult:plan": {
                "result_record_id": "tlresult:plan",
                "stage_id": "plan",
                "accepted": True,
                "effective_from_clock_seq": 2,
                "produced_artifact_refs": ["artifact:plan.md"],
                "scope_key": "run/phase.plan",
                "dependency_scope_key": "run",
            }
        },
        accepted_result_records_by_scope={"run": {"plan": "tlresult:plan"}},
        active_scope_key="run",
    )

    assert state.ready_node_ids == ("draft",)
    draft = next(item for item in state.node_states if item.node_id == "draft")
    assert draft.status == "ready"
    edge = next(item for item in state.edge_states if item.edge_id == "plan_draft")
    assert edge.status == "ack_waiting"
    assert edge.diagnostics["result_record_id"] == "tlresult:plan"


def test_scheduler_consumes_explicit_blocking_temporal_edges() -> None:
    spec = TaskGraphRuntimeSpec(
        graph_id="graph.test.temporal_dependency",
        domain_id="domain.test",
        task_family="test",
        coordinator_agent_id="agent:0",
        nodes=(
            TaskGraphRuntimeNode(node_id="research", title="Research", node_type="agent", role="worker"),
            TaskGraphRuntimeNode(node_id="draft", title="Draft", node_type="agent", role="worker"),
        ),
        start_node_ids=("research", "draft"),
        terminal_node_ids=("draft",),
        temporal_edges=(
            {
                "edge_id": "temporal:research->draft",
                "source_node_id": "research",
                "target_node_id": "draft",
                "temporal_type": "after_success",
                "blocking": True,
            },
        ),
    )

    blocked = bootstrap_scheduler_state(runtime_spec=spec)
    draft = next(item for item in blocked.node_states if item.node_id == "draft")

    assert blocked.ready_node_ids == ("research",)
    assert "upstream:research" in draft.blocked_reasons
    assert blocked.diagnostics["blocking_temporal_edge_count"] == 1

    released = bootstrap_scheduler_state(
        runtime_spec=spec,
        node_statuses={"research": "completed", "draft": "pending"},
    )

    assert released.ready_node_ids == ("draft",)


def test_scheduler_bootstrap_groups_phase_state_without_taking_over_runtime() -> None:
    state = bootstrap_scheduler_state(
        runtime_spec=_runtime_spec(),
        node_statuses={"plan": "running", "draft": "pending", "review": "pending"},
    )

    assert state.mode == "shadow"
    assert state.running_node_ids == ("plan",)
    phase_plan = next(item for item in state.phase_states if item.phase_id == "phase.plan")
    phase_write = next(item for item in state.phase_states if item.phase_id == "phase.write")
    assert phase_plan.status == "active"
    assert phase_write.status == "blocked"
    assert state.diagnostics["scheduler_phase"] == "shadow_bootstrap"


def test_scheduler_supports_wait_any_shadow_readiness() -> None:
    spec = TaskGraphRuntimeSpec(
        graph_id="graph.test.wait_any",
        domain_id="domain.test",
        task_family="test",
        coordinator_agent_id="agent:0",
        nodes=(
            TaskGraphRuntimeNode(node_id="a", title="A", node_type="agent", role="worker"),
            TaskGraphRuntimeNode(node_id="b", title="B", node_type="agent", role="worker"),
            TaskGraphRuntimeNode(node_id="merge", title="Merge", node_type="agent", role="coordinator", wait_policy="wait_any_upstream_completed"),
        ),
        edges=(
            TaskGraphRuntimeEdge(edge_id="a_merge", source_node_id="a", target_node_id="merge", mode="handoff"),
            TaskGraphRuntimeEdge(edge_id="b_merge", source_node_id="b", target_node_id="merge", mode="handoff"),
        ),
        start_node_ids=("a", "b"),
        terminal_node_ids=("merge",),
    )

    state = bootstrap_scheduler_state(
        runtime_spec=spec,
        node_statuses={"a": "completed", "b": "pending", "merge": "pending"},
    )

    assert "merge" in state.ready_node_ids


def test_scheduler_shadow_blocks_later_phase_until_current_phase_completes() -> None:
    spec = TaskGraphRuntimeSpec(
        graph_id="graph.test.phase_gate",
        domain_id="domain.test",
        task_family="test",
        coordinator_agent_id="agent:0",
        nodes=(
            TaskGraphRuntimeNode(node_id="plan", title="Plan", node_type="agent", role="planner", phase_id="phase.plan", sequence_index=1),
            TaskGraphRuntimeNode(node_id="draft", title="Draft", node_type="agent", role="writer", phase_id="phase.write", sequence_index=1),
        ),
        start_node_ids=("plan", "draft"),
        terminal_node_ids=("draft",),
    )

    state = bootstrap_scheduler_state(runtime_spec=spec)

    assert state.ready_node_ids == ("plan",)
    draft = next(item for item in state.node_states if item.node_id == "draft")
    assert draft.status == "blocked"
    assert draft.blocked_reasons == ("phase_not_active:phase.write",)
    assert state.diagnostics["active_phase_ids"] == ["phase.plan"]


def test_scheduler_shadow_allows_same_sequence_parallel_group() -> None:
    spec = TaskGraphRuntimeSpec(
        graph_id="graph.test.sequence_group",
        domain_id="domain.test",
        task_family="test",
        coordinator_agent_id="agent:0",
        nodes=(
            TaskGraphRuntimeNode(node_id="a", title="A", node_type="agent", role="worker", phase_id="phase.work", sequence_index=1, timeline_group_id="reviewers"),
            TaskGraphRuntimeNode(node_id="b", title="B", node_type="agent", role="worker", phase_id="phase.work", sequence_index=1, timeline_group_id="reviewers"),
            TaskGraphRuntimeNode(node_id="merge", title="Merge", node_type="barrier", role="coordinator", phase_id="phase.work", sequence_index=2),
        ),
        start_node_ids=("a", "b"),
        terminal_node_ids=("merge",),
    )

    state = bootstrap_scheduler_state(runtime_spec=spec)

    assert state.ready_node_ids == ("a", "b")
    merge = next(item for item in state.node_states if item.node_id == "merge")
    assert merge.status == "blocked"
    assert merge.blocked_reasons == ("sequence_wait:1",)
    assert state.diagnostics["active_sequence_by_phase"] == {"phase.work": 1}


def test_scheduler_allows_partial_join_after_upstreams_reach_terminal_state() -> None:
    spec = TaskGraphRuntimeSpec(
        graph_id="graph.test.partial_join",
        domain_id="domain.test",
        task_family="test",
        coordinator_agent_id="agent:0",
        nodes=(
            TaskGraphRuntimeNode(node_id="a", title="A", node_type="agent", role="participant"),
            TaskGraphRuntimeNode(node_id="b", title="B", node_type="agent", role="participant"),
            TaskGraphRuntimeNode(
                node_id="merge",
                title="Merge",
                node_type="agent",
                role="coordinator",
                join_policy="allow_partial_with_issues",
            ),
        ),
        edges=(
            TaskGraphRuntimeEdge(edge_id="a_merge", source_node_id="a", target_node_id="merge", mode="handoff"),
            TaskGraphRuntimeEdge(
                edge_id="b_merge",
                source_node_id="b",
                target_node_id="merge",
                mode="handoff",
                failure_propagation_policy="allow_partial",
            ),
        ),
        terminal_node_ids=("merge",),
    )

    state = bootstrap_scheduler_state(
        runtime_spec=spec,
        node_statuses={"a": "completed", "b": "failed", "merge": "pending"},
    )

    assert state.ready_node_ids == ("merge",)
    assert "merge" not in state.blocked_node_ids


def test_scheduler_blocks_partial_join_until_all_upstreams_are_terminal() -> None:
    spec = TaskGraphRuntimeSpec(
        graph_id="graph.test.partial_join_pending",
        domain_id="domain.test",
        task_family="test",
        coordinator_agent_id="agent:0",
        nodes=(
            TaskGraphRuntimeNode(node_id="a", title="A", node_type="agent", role="participant"),
            TaskGraphRuntimeNode(node_id="b", title="B", node_type="agent", role="participant"),
            TaskGraphRuntimeNode(
                node_id="merge",
                title="Merge",
                node_type="agent",
                role="coordinator",
                join_policy="allow_partial_with_issues",
            ),
        ),
        edges=(
            TaskGraphRuntimeEdge(edge_id="a_merge", source_node_id="a", target_node_id="merge", mode="handoff"),
            TaskGraphRuntimeEdge(
                edge_id="b_merge",
                source_node_id="b",
                target_node_id="merge",
                mode="handoff",
                failure_propagation_policy="allow_partial",
            ),
        ),
        terminal_node_ids=("merge",),
    )

    state = bootstrap_scheduler_state(
        runtime_spec=spec,
        node_statuses={"a": "completed", "b": "pending", "merge": "pending"},
    )

    assert "merge" in state.blocked_node_ids
    merge = next(item for item in state.node_states if item.node_id == "merge")
    assert "upstream:b" in merge.blocked_reasons


def test_scheduler_fail_downstream_propagates_failure_chain() -> None:
    spec = TaskGraphRuntimeSpec(
        graph_id="graph.test.fail_downstream",
        domain_id="domain.test",
        task_family="test",
        coordinator_agent_id="agent:0",
        nodes=(
            TaskGraphRuntimeNode(node_id="source", title="Source", node_type="agent", role="worker"),
            TaskGraphRuntimeNode(node_id="middle", title="Middle", node_type="agent", role="worker"),
            TaskGraphRuntimeNode(node_id="final", title="Final", node_type="agent", role="worker"),
        ),
        edges=(
            TaskGraphRuntimeEdge(
                edge_id="source_middle",
                source_node_id="source",
                target_node_id="middle",
                mode="handoff",
                failure_propagation_policy="fail_downstream",
            ),
            TaskGraphRuntimeEdge(
                edge_id="middle_final",
                source_node_id="middle",
                target_node_id="final",
                mode="handoff",
                failure_propagation_policy="fail_downstream",
            ),
        ),
        start_node_ids=("source",),
        terminal_node_ids=("final",),
    )

    state = bootstrap_scheduler_state(
        runtime_spec=spec,
        node_statuses={"source": "failed", "middle": "pending", "final": "pending"},
    )

    assert state.failed_node_ids == ("source", "middle", "final")
    assert state.ready_node_ids == ()
    assert state.terminal_status == "failed"
    assert state.diagnostics["failure_propagated_node_ids"] == ["final", "middle"]
    middle = next(item for item in state.node_states if item.node_id == "middle")
    final = next(item for item in state.node_states if item.node_id == "final")
    assert middle.diagnostics["failure_propagated"] is True
    assert final.diagnostics["failure_propagated"] is True


def test_scheduler_isolates_failure_without_releasing_downstream() -> None:
    spec = TaskGraphRuntimeSpec(
        graph_id="graph.test.isolate_failure",
        domain_id="domain.test",
        task_family="test",
        coordinator_agent_id="agent:0",
        nodes=(
            TaskGraphRuntimeNode(node_id="source", title="Source", node_type="agent", role="worker"),
            TaskGraphRuntimeNode(node_id="target", title="Target", node_type="agent", role="worker"),
        ),
        edges=(
            TaskGraphRuntimeEdge(
                edge_id="source_target",
                source_node_id="source",
                target_node_id="target",
                mode="handoff",
                failure_propagation_policy="isolate_failure",
            ),
        ),
        start_node_ids=("source",),
        terminal_node_ids=("target",),
    )

    state = bootstrap_scheduler_state(
        runtime_spec=spec,
        node_statuses={"source": "failed", "target": "pending"},
    )

    assert state.failed_node_ids == ("source",)
    assert "target" in state.blocked_node_ids
    assert "target" not in state.ready_node_ids
    target = next(item for item in state.node_states if item.node_id == "target")
    assert "upstream_failed:source" in target.blocked_reasons
    assert target.diagnostics["failure_propagated"] is False
    edge = next(item for item in state.edge_states if item.edge_id == "source_target")
    assert edge.status == "failure_isolated"


def test_scheduler_allow_partial_requires_target_partial_join() -> None:
    spec = TaskGraphRuntimeSpec(
        graph_id="graph.test.allow_partial_requires_join",
        domain_id="domain.test",
        task_family="test",
        coordinator_agent_id="agent:0",
        nodes=(
            TaskGraphRuntimeNode(node_id="a", title="A", node_type="agent", role="worker"),
            TaskGraphRuntimeNode(node_id="b", title="B", node_type="agent", role="worker"),
            TaskGraphRuntimeNode(node_id="merge", title="Merge", node_type="agent", role="coordinator", join_policy="all_success"),
        ),
        edges=(
            TaskGraphRuntimeEdge(edge_id="a_merge", source_node_id="a", target_node_id="merge", mode="handoff"),
            TaskGraphRuntimeEdge(
                edge_id="b_merge",
                source_node_id="b",
                target_node_id="merge",
                mode="handoff",
                failure_propagation_policy="allow_partial",
            ),
        ),
        terminal_node_ids=("merge",),
    )

    state = bootstrap_scheduler_state(
        runtime_spec=spec,
        node_statuses={"a": "completed", "b": "failed", "merge": "pending"},
    )

    assert state.ready_node_ids == ()
    assert "merge" in state.blocked_node_ids
    merge = next(item for item in state.node_states if item.node_id == "merge")
    assert "upstream_failed:b" in merge.blocked_reasons
    edge = next(item for item in state.edge_states if item.edge_id == "b_merge")
    assert edge.status == "partial_failure_allowed"


def test_scheduler_does_not_schedule_conditional_repair_or_failure_routes_by_default() -> None:
    spec = TaskGraphRuntimeSpec(
        graph_id="graph.test.conditional_routes",
        domain_id="domain.test",
        task_family="test",
        coordinator_agent_id="agent:0",
        nodes=(
            TaskGraphRuntimeNode(node_id="review", title="Review", node_type="review_gate", role="reviewer"),
            TaskGraphRuntimeNode(node_id="commit", title="Commit", node_type="agent", role="memory"),
            TaskGraphRuntimeNode(node_id="repair", title="Repair", node_type="agent", role="writer"),
            TaskGraphRuntimeNode(node_id="fail_closed", title="Fail", node_type="agent", role="memory"),
        ),
        edges=(
            TaskGraphRuntimeEdge(
                edge_id="review_commit",
                source_node_id="review",
                target_node_id="commit",
                mode="structured_handoff",
            ),
            TaskGraphRuntimeEdge(
                edge_id="review_repair",
                source_node_id="review",
                target_node_id="repair",
                mode="repair_route",
                metadata={"verdict": "repair_world"},
            ),
            TaskGraphRuntimeEdge(
                edge_id="review_fail",
                source_node_id="review",
                target_node_id="fail_closed",
                mode="fail_closed",
                metadata={"verdict": "fail_closed"},
            ),
        ),
        start_node_ids=("review",),
        terminal_node_ids=("commit", "fail_closed"),
    )

    state = bootstrap_scheduler_state(
        runtime_spec=spec,
        node_statuses={
            "review": "completed",
            "commit": "pending",
            "repair": "pending",
            "fail_closed": "pending",
        },
    )

    assert state.ready_node_ids == ("commit",)
    assert "repair" not in state.ready_node_ids
    assert "fail_closed" not in state.ready_node_ids
    repair = next(item for item in state.node_states if item.node_id == "repair")
    failure = next(item for item in state.node_states if item.node_id == "fail_closed")
    assert repair.upstream_node_ids == ()
    assert failure.upstream_node_ids == ()
    assert "repair" in state.diagnostics["optional_node_ids"]
    assert "fail_closed" in state.diagnostics["optional_node_ids"]


def test_scheduler_excludes_resource_nodes_from_execution_queue() -> None:
    spec = TaskGraphRuntimeSpec(
        graph_id="graph.test.resource_nodes",
        domain_id="domain.test",
        task_family="test",
        coordinator_agent_id="agent:0",
        nodes=(
            TaskGraphRuntimeNode(node_id="draft", title="Draft", node_type="agent", role="writer"),
            TaskGraphRuntimeNode(node_id="memory.writing.mutable", title="Mutable Memory", node_type="memory_repository", role="resource"),
        ),
        edges=(
            TaskGraphRuntimeEdge(
                edge_id="edge.memory_commit.draft.mutable",
                source_node_id="draft",
                target_node_id="memory.writing.mutable",
                mode="memory_commit",
            ),
        ),
        start_node_ids=("draft",),
        terminal_node_ids=("draft",),
    )

    state = bootstrap_scheduler_state(
        runtime_spec=spec,
        node_statuses={"draft": "completed", "memory.writing.mutable": "pending"},
    )

    assert state.ready_node_ids == ()
    assert "memory.writing.mutable" not in state.blocked_node_ids
    assert state.diagnostics["resource_node_ids_excluded_from_schedule"] == ["memory.writing.mutable"]
