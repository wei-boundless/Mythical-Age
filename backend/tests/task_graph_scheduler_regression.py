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
            TaskGraphRuntimeEdge(edge_id="b_merge", source_node_id="b", target_node_id="merge", mode="handoff"),
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
            TaskGraphRuntimeEdge(edge_id="b_merge", source_node_id="b", target_node_id="merge", mode="handoff"),
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
