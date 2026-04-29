from __future__ import annotations

import pytest

from orchestration import (
    AgentAssignmentCandidate,
    AgentResultCandidate,
    AgentSeatPlanPreview,
    AdoptedResourcePolicy,
    CommitGatePreview,
    ControlKernel,
    ControlKernelPreviewContext,
    ExecutionTopologyPreview,
    RuntimeDirective,
    TaskContract,
    build_single_agent_topology_preview,
)
from tasks import build_task_runtime_contract_preview


def test_control_kernel_preview_context_records_refs_without_directives() -> None:
    task = TaskContract(
        task_id="task-kernel-preview",
        user_goal="读取 docs 并总结",
        session_id="session-kernel",
    )
    context = ControlKernelPreviewContext(
        task_prompt_contract_ref="task-prompt:task-kernel-preview:preview",
        resource_policy_ref="policy:task-kernel-preview:preview",
        prompt_manifest_ref="manifest-task-kernel-preview-preview",
        operation_requirement_ref="opreq:task-kernel-preview:task_binding_preview",
        denied_operations=("op.shell",),
        requires_approval_operations=("op.edit_file",),
    )

    result = ControlKernel().collect(task=task, preview_context=context)
    graph = result.execution_graph

    assert result.status == "blocked"
    assert result.reason == "preview_only"
    assert result.directives == ()
    assert graph is not None
    assert graph.nodes == ()
    assert graph.edges == ()
    assert graph.refs["state"] == "preview_only"
    assert graph.refs["blocked_reason"] == "preview_only"
    assert graph.refs["resource_policy_ref"] == "policy:task-kernel-preview:preview"
    assert graph.refs["resource_policy_adopted"] is False
    assert graph.refs["runtime_directive_enabled"] is False
    assert graph.refs["runtime_executable"] is False
    assert result.diagnostics["fail_closed"] is True
    assert result.diagnostics["preview_only"] is True
    assert result.diagnostics["resource_policy_state"] == "preview"
    assert result.diagnostics["resource_policy_adopted"] is False
    assert result.diagnostics["runtime_directive_enabled"] is False
    assert result.diagnostics["runtime_executable"] is False
    assert result.diagnostics["operation_gate_required_before_execution"] is True
    assert result.diagnostics["directive_count"] == 0
    assert result.diagnostics["execution_node_count"] == 0
    assert result.diagnostics["denied_operations"] == ["op.shell"]
    assert result.diagnostics["requires_approval_operations"] == ["op.edit_file"]


def test_control_kernel_preview_context_rejects_runtime_authority() -> None:
    with pytest.raises(ValueError, match="adopted policy"):
        ControlKernelPreviewContext(resource_policy_adopted=True)

    with pytest.raises(ValueError, match="runtime directives"):
        ControlKernelPreviewContext(runtime_directive_enabled=True)

    with pytest.raises(ValueError, match="runtime executable"):
        ControlKernelPreviewContext(runtime_executable=True)


def test_single_agent_topology_preview_prepares_agent_interfaces_without_execution() -> None:
    topology, policy = build_single_agent_topology_preview(task_id="task-topology-preview")

    assert topology.mode == "single_agent"
    assert topology.preview_only is True
    assert topology.adopted is False
    assert topology.runtime_executable is False
    assert topology.coordination_policy_ref == policy.policy_id
    assert policy.max_agents == 1
    assert policy.max_parallelism == 1
    assert policy.preview_only is True
    assert policy.runtime_executable is False

    seat = AgentSeatPlanPreview(
        seat_id="seat:future:reviewer",
        role="reviewer",
        stage_ref="stage:future",
        task_contract_ref="task:future",
        resource_policy_ref="respol:future:preview",
        memory_policy_ref="mempol:future:preview",
    )
    assignment = AgentAssignmentCandidate(
        assignment_id="assignment:future:reviewer",
        seat_ref=seat.seat_id,
        agent_profile_ref="agent:general-purpose",
        reason="future multi-agent interface only",
        confidence=0.5,
    )
    result = AgentResultCandidate(
        result_id="agent-result:future:reviewer",
        seat_ref=seat.seat_id,
        agent_instance_ref="agent-instance:future",
        summary="future result candidate",
    )

    assert seat.runtime_executable is False
    assert assignment.authority == "candidate_only"
    assert result.final_answer is False

    with pytest.raises(ValueError, match="runtime executable"):
        ExecutionTopologyPreview(
            topology_id="topology:bad",
            task_id="task-bad",
            runtime_executable=True,
        )

    with pytest.raises(ValueError, match="final answer"):
        AgentResultCandidate(
            result_id="agent-result:bad",
            seat_ref="seat:bad",
            agent_instance_ref="agent-instance:bad",
            final_answer=True,
        )


def test_task_runtime_contract_preview_uses_control_kernel_preview_result() -> None:
    preview = build_task_runtime_contract_preview(
        session_id="session-kernel-bridge",
        task_id="task-kernel-bridge",
        user_goal="修改任务系统文档，然后检查有没有前后矛盾",
    )
    result = preview["control_kernel_result"]
    graph = result["execution_graph"]
    diagnostics = preview["control_kernel_diagnostics"]
    topology = preview["execution_topology_preview"]
    coordination_policy = preview["coordination_policy_preview"]
    candidate_set = preview["candidate_set_preview"]
    orchestration_plan = preview["orchestration_plan_preview"]
    plan_validation = preview["plan_validation"]
    graph_preview = preview["execution_graph_preview"]
    adoption = preview["adoption_candidate_preview"]
    adoption_block = preview["adoption_block"]
    directive_candidates = preview["runtime_directive_candidates"]
    runtime_directive_block = preview["runtime_directive_block"]
    operation_gate_preflight = preview["operation_gate_preflight"]
    directive_only_executor = preview["directive_only_executor_preview"]
    commit_gate = preview["commit_gate_preview"]
    understanding_candidates = preview["understanding_candidate_preview"]

    assert result["status"] == "blocked"
    assert result["reason"] == "preview_only"
    assert result["directives"] == []
    assert len(result["candidates"]) == len(candidate_set)
    assert len(candidate_set) >= 11
    assert len(understanding_candidates) == 5
    assert all(candidate["authority"] == "candidate_only" for candidate in understanding_candidates)
    assert graph["nodes"] == []
    assert graph["edges"] == []
    assert graph["refs"]["state"] == "preview_only"
    assert graph["refs"]["resource_policy_ref"] == preview["resource_policy"]["policy_id"]
    assert graph["refs"]["execution_topology_ref"] == topology["topology_id"]
    assert graph["refs"]["execution_topology_mode"] == "single_agent"
    assert graph["refs"]["coordination_policy_ref"] == coordination_policy["policy_id"]
    assert graph["refs"]["multi_agent_enabled"] is False
    assert graph["refs"]["agent_seat_count"] == 0
    assert graph["refs"]["orchestration_plan_ref"] == orchestration_plan["plan_id"]
    assert graph["refs"]["plan_validation_ref"] == plan_validation["validation_id"]
    assert graph["refs"]["execution_graph_preview_ref"] == graph_preview["graph_preview_id"]
    assert graph["refs"]["adoption_candidate_ref"] == adoption["candidate_id"]
    assert graph["refs"]["adoption_block_ref"] == adoption_block["block_id"]
    assert graph["refs"]["runtime_directive_candidate_count"] == len(directive_candidates)
    assert graph["refs"]["runtime_directive_block_ref"] == runtime_directive_block["block_id"]
    assert graph["refs"]["operation_gate_preflight_ref"] == operation_gate_preflight["preflight_id"]
    assert graph["refs"]["operation_gate_passed"] is False
    assert graph["refs"]["directive_only_executor_ref"] == directive_only_executor["preview_id"]
    assert graph["refs"]["executor_dispatch_enabled"] is False
    assert graph["refs"]["commit_gate_ref"] == commit_gate["gate_id"]
    assert graph["refs"]["commit_gate_status"] == "blocked"
    assert graph["refs"]["commit_allowed"] is False
    assert graph["refs"]["task_prompt_contract_ref"] == preview["task_prompt_contract"]["contract_id"]
    assert graph["refs"]["prompt_manifest_ref"] == preview["prompt_manifest_preview"]["manifest_id"]
    assert graph["refs"]["operation_requirement_ref"] == preview["operation_requirement"]["requirement_id"]
    assert orchestration_plan["topology_mode"] == "single_agent"
    assert orchestration_plan["preview_only"] is True
    assert orchestration_plan["adopted"] is False
    assert orchestration_plan["runtime_executable"] is False
    assert orchestration_plan["stages"][0]["stage_type"] == "main_agent_response"
    assert plan_validation["status"] == "blocked"
    assert plan_validation["runtime_executable"] is False
    assert plan_validation["can_build_runtime_directive"] is False
    assert graph_preview["runtime_executable"] is False
    assert graph_preview["node_previews"][0]["executable"] is False
    assert graph_preview["node_previews"][0]["authority"] == "preview_only"
    assert adoption["status"] == "blocked"
    assert adoption["can_adopt_plan"] is False
    assert adoption["can_adopt_resource_policy"] is False
    assert adoption["runtime_executable"] is False
    assert adoption_block["blocked"] is True
    assert adoption_block["diagnostics"]["adopted_resource_policy_available"] is False
    assert len(directive_candidates) == 1
    assert directive_candidates[0]["authority"] == "candidate_only"
    assert directive_candidates[0]["runtime_executable"] is False
    assert runtime_directive_block["blocked"] is True
    assert runtime_directive_block["diagnostics"]["runtime_directive_available"] is False
    assert operation_gate_preflight["status"] == "blocked"
    assert operation_gate_preflight["operation_gate_required"] is True
    assert operation_gate_preflight["operation_gate_passed"] is False
    assert operation_gate_preflight["runtime_executable"] is False
    assert operation_gate_preflight["checks"]
    assert all(check["decision"] == "deny" for check in operation_gate_preflight["checks"])
    assert all(check["required_input_type"] == "RuntimeDirective" for check in operation_gate_preflight["checks"])
    assert all(check["received_input_type"] == "RuntimeDirectiveCandidate" for check in operation_gate_preflight["checks"])
    assert directive_only_executor["status"] == "blocked"
    assert directive_only_executor["accepted_input_type"] == "RuntimeDirective"
    assert "RuntimeDirectiveCandidate" in directive_only_executor["rejected_input_types"]
    assert "QueryExecutionPlan" in directive_only_executor["rejected_input_types"]
    assert directive_only_executor["operation_gate_passed"] is False
    assert directive_only_executor["will_dispatch"] is False
    assert directive_only_executor["runtime_executable"] is False
    assert commit_gate["status"] == "blocked"
    assert commit_gate["commit_allowed"] is False
    assert commit_gate["runtime_executable"] is False
    assert {candidate["commit_type"] for candidate in commit_gate["commit_candidates"]} == {
        "session_message",
        "session_memory",
        "durable_memory",
        "task_result",
        "artifact_graph",
        "title",
    }
    assert all(candidate["allowed"] is False for candidate in commit_gate["commit_candidates"])
    assert topology["mode"] == "single_agent"
    assert topology["preview_only"] is True
    assert topology["adopted"] is False
    assert topology["runtime_executable"] is False
    assert coordination_policy["max_agents"] == 1
    assert coordination_policy["max_parallelism"] == 1
    assert preview["agent_seat_plan_previews"] == []
    assert preview["agent_assignment_candidates"] == []
    assert diagnostics["resource_policy_ref"] == preview["resource_policy"]["policy_id"]
    assert diagnostics["resource_policy_state"] == "preview"
    assert diagnostics["resource_policy_adopted"] is False
    assert diagnostics["preview_only"] is True
    assert diagnostics["runtime_directive_enabled"] is False
    assert diagnostics["runtime_executable"] is False
    assert diagnostics["execution_topology_mode"] == "single_agent"
    assert diagnostics["single_agent_main_chain_first"] is True
    assert diagnostics["multi_agent_enabled"] is False
    assert diagnostics["agent_architecture_prepared"] is True
    assert diagnostics["candidate_count"] == len(candidate_set)
    assert diagnostics["orchestration_plan_ref"] == orchestration_plan["plan_id"]
    assert diagnostics["plan_validation_status"] == "blocked"
    assert diagnostics["execution_graph_preview_node_count"] == 1
    assert diagnostics["adoption_candidate_status"] == "blocked"
    assert diagnostics["adopted_resource_policy_available"] is False
    assert diagnostics["runtime_directive_candidate_count"] == 1
    assert diagnostics["runtime_directive_available"] is False
    assert diagnostics["operation_gate_passed"] is False
    assert diagnostics["operation_gate_check_count"] == len(operation_gate_preflight["checks"])
    assert diagnostics["executor_dispatch_enabled"] is False
    assert diagnostics["executor_accepts_only"] == "RuntimeDirective"
    assert diagnostics["legacy_query_execution_rejected"] is True
    assert diagnostics["commit_gate_status"] == "blocked"
    assert diagnostics["commit_allowed"] is False
    assert diagnostics["commit_candidate_count"] == len(commit_gate["commit_candidates"])
    assert diagnostics["operation_gate_required_before_execution"] is True
    assert "op.edit_file" in diagnostics["requires_approval_operations"]


def test_commit_gate_preview_rejects_commit_authority() -> None:
    with pytest.raises(ValueError, match="cannot allow commits"):
        CommitGatePreview(
            gate_id="commit-gate:bad",
            task_id="task-bad",
            plan_ref="plan:bad",
            execution_graph_preview_ref="graph-preview:bad",
            adoption_candidate_ref="adoption:bad",
            commit_allowed=True,
        )


def test_runtime_adoption_contracts_reject_preview_or_unadopted_authority() -> None:
    with pytest.raises(ValueError, match="cannot grant execution"):
        AdoptedResourcePolicy(
            policy_id="adopted:bad",
            task_id="task-bad",
            source_policy_ref="respol:bad:preview",
            runtime_executable=True,
        )

    with pytest.raises(ValueError, match="adopted resource policy"):
        RuntimeDirective(
            directive_id="directive:bad",
            task_id="task-bad",
            plan_ref="orchplan:bad",
            stage_ref="orchstage:bad",
            executor_type="model",
            adopted_resource_policy_ref="",
        )

    with pytest.raises(ValueError, match="preview plan"):
        RuntimeDirective(
            directive_id="directive:bad-preview",
            task_id="task-bad",
            plan_ref="orchplan:bad:preview",
            stage_ref="orchstage:bad",
            executor_type="model",
            adopted_resource_policy_ref="adopted:policy",
        )
