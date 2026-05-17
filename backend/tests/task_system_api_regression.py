from __future__ import annotations

import asyncio
from pathlib import Path

from api import orchestration as orchestration_api
from api import tasks as tasks_api
from soul.facade import SoulFacade
from tasks import TaskFlowRegistry, TaskWorkflowRegistry


class _RuntimeStub:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)


def test_orchestration_agents_payload_keeps_removed_legacy_groups_absent(tmp_path: Path) -> None:
    original = orchestration_api.require_runtime
    orchestration_api.require_runtime = lambda: _RuntimeStub(tmp_path)  # type: ignore[assignment]
    try:
        payload = asyncio.run(orchestration_api.orchestration_agents())
    finally:
        orchestration_api.require_runtime = original  # type: ignore[assignment]

    groups = payload["agent_groups"]

    assert payload["authority"] == "orchestration.agent_runtime_registry"
    removed_group_ids = {"group.writing.longform_novel_core"}
    assert all(item["group_id"] not in removed_group_ids for item in groups)


def test_task_system_overview_exposes_formal_task_management_layers(tmp_path: Path) -> None:
    original = tasks_api.require_runtime
    tasks_api.require_runtime = lambda: _RuntimeStub(tmp_path)  # type: ignore[assignment]
    try:
        payload = asyncio.run(tasks_api.task_system_overview())
    finally:
        tasks_api.require_runtime = original  # type: ignore[assignment]

    summary = payload["summary"]
    task_management = payload["task_management"]
    task_graph_management = payload["task_graph_management"]
    diagnostics = payload["diagnostics"]

    assert payload["authority"] == "task_system.management_console"
    assert summary["specific_task_record_count"] == len(task_management["specific_task_records"])
    assert summary["projection_binding_count"] == 0
    assert summary["derived_projection_binding_count"] == len(task_management["projection_bindings"])
    assert summary["effective_projection_binding_count"] == len(task_management["projection_bindings"])
    assert summary["flow_contract_binding_count"] == 0
    assert summary["derived_flow_contract_binding_count"] == len(task_management["flow_contract_bindings"])
    assert summary["effective_flow_contract_binding_count"] == len(task_management["flow_contract_bindings"])
    assert summary["execution_policy_count"] == 0
    assert summary["derived_execution_policy_count"] == len(task_management["execution_policies"])
    assert summary["effective_execution_policy_count"] == len(task_management["execution_policies"])
    assert summary["memory_request_profile_count"] == 0
    assert summary["derived_memory_request_profile_count"] == len(task_management["memory_request_profiles"])
    assert summary["effective_memory_request_profile_count"] == len(task_management["memory_request_profiles"])
    assert summary["communication_protocol_count"] == 0
    assert summary["contract_spec_count"] >= 5
    assert "agent_management" not in payload
    assert task_management["entry_policies"] == []
    assert all("writing" not in str(item.get("domain_id") or "") for item in task_management["task_domains"])
    assert all("writing" not in str(item.get("task_id") or "") for item in task_management["specific_task_records"])
    assert all("writing" not in str(item.get("flow_id") or "") for item in task_management["task_flow_definitions"])
    assert all("writing" not in str(item.get("task_id") or "") for item in task_management["projection_bindings"])
    assert all("writing" not in str(item.get("task_id") or "") for item in task_management["flow_contract_bindings"])
    assert all("writing" not in str(item.get("task_id") or "") for item in task_management["execution_policies"])
    assert all("writing" not in str(item.get("task_id") or "") for item in task_management["memory_request_profiles"])
    assert task_graph_management["communication_protocols"] == []
    assert payload["contract_management"]["contract_specs"]
    assert diagnostics["runtime_recipe_validation_matrix"]["authority"] == "task_system.runtime_recipe_validation"
    assert diagnostics["runtime_recipe_validation_matrix"]["template_protocol_removed"] is True
    assert diagnostics["link_permission_matrix"]["authority"] == "task_system.link_permission_matrix"
    assert diagnostics["agent_task_connections"]["authority"] == "task_system.agent_task_connections"
    assert diagnostics["agent_carrying_profiles"]["authority"] == "task_system.agent_carrying_profiles"
    assert diagnostics["connection_diagnostics"]["authority"] == "task_system.connection_diagnostics"


def test_task_domain_upsert_persists_and_returns_formal_domain_catalog(tmp_path: Path) -> None:
    original = tasks_api.require_runtime
    tasks_api.require_runtime = lambda: _RuntimeStub(tmp_path)  # type: ignore[assignment]
    try:
        payload = asyncio.run(
            tasks_api.upsert_task_system_domain(
                "domain.research",
                tasks_api.TaskDomainUpsertRequest(
                    domain_id="domain.research",
                    task_family="research",
                    title="研究任务域",
                    description="用于实验性研究任务。",
                    enabled=True,
                    sort_order=90,
                ),
            )
        )
    finally:
        tasks_api.require_runtime = original  # type: ignore[assignment]

    domains = payload["task_management"]["task_domains"]
    research = next(item for item in domains if item["domain_id"] == "domain.research")

    assert payload["summary"]["task_domain_count"] >= 1
    assert research["task_family"] == "research"
    assert research["title"] == "研究任务域"
    assert research["description"] == "用于实验性研究任务。"


def test_task_domain_delete_cascades_specific_tasks_and_domain_catalog(tmp_path: Path) -> None:
    original = tasks_api.require_runtime
    tasks_api.require_runtime = lambda: _RuntimeStub(tmp_path)  # type: ignore[assignment]
    try:
        asyncio.run(
            tasks_api.upsert_task_system_domain(
                "domain.research",
                tasks_api.TaskDomainUpsertRequest(
                    domain_id="domain.research",
                    task_family="research",
                    title="研究任务域",
                    description="用于实验性研究任务。",
                    enabled=True,
                    sort_order=90,
                ),
            )
        )
        asyncio.run(
            tasks_api.upsert_task_system_workflow(
                "workflow.900101",
                tasks_api.TaskWorkflowUpsertRequest(
                    workflow_id="workflow.900101",
                    title="研究实验临时工作流",
                    task_mode="bounded_patch",
                    steps=[{"step_id": "run_experiment", "title": "运行实验"}],
                    output_contract_id="AssistantFinalAnswer",
                ),
            )
        )
        asyncio.run(
            tasks_api.upsert_task_system_specific_record(
                "task.research.experiment",
                tasks_api.SpecificTaskRecordUpsertRequest(
                    task_id="task.research.experiment",
                    task_title="研究实验任务",
                    task_family="research",
                    task_mode="bounded_patch",
                    description="research test",
                    default_flow_contract_id="flow.research.experiment",
                    default_workflow_id="workflow.900101",
                ),
            )
        )
        payload = asyncio.run(tasks_api.delete_task_system_domain("domain.research"))
    finally:
        tasks_api.require_runtime = original  # type: ignore[assignment]

    domains = payload["task_management"]["task_domains"]
    records = payload["task_management"]["specific_task_records"]

    assert all(item["domain_id"] != "domain.research" for item in domains)
    assert all(item["task_family"] != "research" for item in records)
    assert all(item["workflow_id"] != "workflow.900101" for item in payload["task_management"]["workflow_resources"])
    assert payload["last_deletion"]["domain_id"] == "domain.research"
    assert "task.research.experiment" in payload["last_deletion"]["deleted_task_ids"]
    assert "workflow.900101" in payload["last_deletion"]["deleted_workflow_ids"]


def test_specific_task_delete_cascades_task_assembly_objects(tmp_path: Path) -> None:
    original = tasks_api.require_runtime
    tasks_api.require_runtime = lambda: _RuntimeStub(tmp_path)  # type: ignore[assignment]
    try:
        asyncio.run(
            tasks_api.upsert_task_system_workflow(
                "workflow.900102",
                tasks_api.TaskWorkflowUpsertRequest(
                    workflow_id="workflow.900102",
                    title="研究实验补丁工作流",
                    task_mode="bounded_patch",
                    steps=[{"step_id": "patch", "title": "实施补丁"}],
                    output_contract_id="AssistantFinalAnswer",
                ),
            )
        )
        asyncio.run(
            tasks_api.upsert_task_system_specific_record(
                "task.research.experiment",
                tasks_api.SpecificTaskRecordUpsertRequest(
                    task_id="task.research.experiment",
                    task_title="研究实验任务",
                    task_family="research",
                    task_mode="bounded_patch",
                    description="research test",
                    default_flow_contract_id="flow.research.experiment",
                    default_workflow_id="workflow.900102",
                ),
            )
        )
        asyncio.run(
            tasks_api.upsert_task_system_projection_binding(
                "task.research.experiment",
                tasks_api.TaskProjectionBindingUpsertRequest(
                    task_id="task.research.experiment",
                    projection_selection_mode="task_default",
                    default_projection_id="projection.research",
                ),
            )
        )
        payload = asyncio.run(tasks_api.delete_task_system_specific_record("task.research.experiment"))
    finally:
        tasks_api.require_runtime = original  # type: ignore[assignment]

    task_management = payload["task_management"]

    assert all(item["task_id"] != "task.research.experiment" for item in task_management["specific_task_records"])
    assert all(item["task_id"] != "task.research.experiment" for item in task_management["projection_bindings"])
    assert all(item["task_id"] != "task.research.experiment" for item in task_management["flow_contract_bindings"])
    assert all(item["task_id"] != "task.research.experiment" for item in task_management["execution_policies"])
    assert all(item["task_id"] != "task.research.experiment" for item in task_management["memory_request_profiles"])
    assert all(item["workflow_id"] != "workflow.900102" for item in task_management["workflow_resources"])
    assert payload["last_deletion"]["task_id"] == "task.research.experiment"
    assert payload["last_deletion"]["deleted_workflow_ids"] == ["workflow.900102"]


def test_task_system_next_ids_are_generated_with_prefixed_internal_ids_and_display_numbers(tmp_path: Path) -> None:
    original = tasks_api.require_runtime
    tasks_api.require_runtime = lambda: _RuntimeStub(tmp_path)  # type: ignore[assignment]
    try:
        payload = asyncio.run(tasks_api.task_system_next_ids())
    finally:
        tasks_api.require_runtime = original  # type: ignore[assignment]

    assert payload["authority"] == "task_system.id_registry"
    assert str(payload["task_id"]).startswith("task.")
    assert str(payload["flow_id"]).startswith("flow.")
    assert str(payload["workflow_id"]).startswith("workflow.")
    assert str(payload["graph_id"]).startswith("graph.")
    assert str(payload["topology_template_id"]).startswith("topology.")

    display_numbers = payload["display_numbers"]
    assert str(display_numbers["task"]).startswith("任务-")
    assert str(display_numbers["flow"]).startswith("流程-")
    assert str(display_numbers["workflow"]).startswith("流程-")
    assert str(display_numbers["coordination"]).startswith("协作-")
    assert str(display_numbers["topology"]).startswith("拓扑-")


def test_task_system_formal_object_upserts_persist_and_return_management_payload(tmp_path: Path) -> None:
    original = tasks_api.require_runtime
    tasks_api.require_runtime = lambda: _RuntimeStub(tmp_path)  # type: ignore[assignment]
    try:
        projection_payload = asyncio.run(
            tasks_api.upsert_task_system_projection_binding(
                "task.dev.light_web_game",
                tasks_api.TaskProjectionBindingUpsertRequest(
                    task_id="task.dev.light_web_game",
                    projection_selection_mode="allow_list",
                    allowed_projection_ids=["projection.dev.builder"],
                    default_projection_id="projection.dev.builder",
                    projection_required=True,
                    notes="test projection binding",
                ),
            )
        )
        flow_contract_payload = asyncio.run(
            tasks_api.upsert_task_system_flow_contract_binding(
                "task.dev.light_web_game",
                tasks_api.TaskFlowContractBindingUpsertRequest(
                    task_id="task.dev.light_web_game",
                    flow_contract_id="flow.dev.light_web_game",
                    override_policy="strict_task_default",
                    verification_gate_profile="gate.dev.qa",
                    fallback_policy="fail_closed",
                ),
            )
        )
        execution_payload = asyncio.run(
            tasks_api.upsert_task_system_execution_policy(
                "task.dev.light_web_game",
                tasks_api.TaskExecutionPolicyUpsertRequest(
                    task_id="task.dev.light_web_game",
                    execution_chain_type="single_agent_chain",
                    runtime_agent_selection_policy="orchestration_default",
                    default_agent_id="agent:3",
                    task_level="standard",
                    task_privilege="bounded",
                    allowed_agent_categories=["main_agent", "worker_sub_agent"],
                    allow_worker_agent_spawn=True,
                    worker_agent_blueprint_id="worker.dev.prototype",
                    worker_agent_naming_rule="game-worker-{n}",
                    notes="test adoption plan",
                ),
            )
        )
        memory_payload = asyncio.run(
            tasks_api.upsert_task_system_memory_request_profile(
                "task.dev.light_web_game",
                tasks_api.TaskMemoryRequestProfileUpsertRequest(
                    task_id="task.dev.light_web_game",
                    requested_memory_layers=["conversation", "state", "long_term"],
                    requested_topics=["project_background", "game_requirements"],
                    memory_priority="high",
                    writeback_policy="task_summary_only",
                    allow_long_term_memory=True,
                    memory_scope_hint="conversation_read_write",
                ),
            )
        )
        protocol_payload = asyncio.run(
            tasks_api.upsert_task_system_communication_protocol(
                "protocol.dev.parallel_review",
                tasks_api.TaskCommunicationProtocolUpsertRequest(
                    protocol_id="protocol.dev.parallel_review",
                    title="并行评审协议",
                    message_types=["task_claim", "draft_result", "review_feedback"],
                    payload_contracts=["DraftResult", "ReviewFeedback"],
                    signal_rules=["worker_to_coordinator", "coordinator_merge"],
                    handoff_rules=["structured_refs_only"],
                    ack_policy="explicit_ack",
                    timeout_policy="fail_closed",
                    error_signal_policy="raise_to_coordinator",
                    enabled=True,
                ),
            )
        )
    finally:
        tasks_api.require_runtime = original  # type: ignore[assignment]

    registry = TaskFlowRegistry(tmp_path)
    projection_binding = registry.get_projection_binding("task.dev.light_web_game")
    flow_binding = registry.get_flow_contract_binding("task.dev.light_web_game")
    execution_policy = registry.get_task_agent_adoption_plan("task.dev.light_web_game")
    memory_profile = registry.get_task_memory_request_profile("task.dev.light_web_game")
    protocol = registry.get_task_communication_protocol("protocol.dev.parallel_review")

    assert projection_payload["task_management"]["projection_bindings"]
    assert flow_contract_payload["task_management"]["flow_contract_bindings"]
    assert execution_payload["task_management"]["execution_policies"]
    assert memory_payload["task_management"]["memory_request_profiles"]
    assert protocol_payload["task_graph_management"]["communication_protocols"]

    assert projection_binding is not None
    assert projection_binding.projection_selection_mode == "allow_list"
    assert projection_binding.default_projection_id == "projection.dev.builder"
    assert projection_binding.projection_required is True

    assert flow_binding is not None
    assert flow_binding.override_policy == "strict_task_default"
    assert flow_binding.verification_gate_profile == "gate.dev.qa"

    assert execution_policy is not None
    assert execution_policy.to_dict()["authority"] == "task_system.task_execution_policy"
    assert execution_policy.to_dict()["execution_chain_type"] == "single_agent_chain"
    assert execution_policy.to_dict()["default_agent_id"] == "agent:3"
    assert execution_payload["task_management"]["execution_policies"][0]["default_agent_id"] == "agent:3"
    assert execution_policy.adoption_mode == "adopt_with_projection"
    assert execution_policy.allow_worker_agent_spawn is True
    assert execution_policy.worker_agent_blueprint_id == "worker.dev.prototype"

    assert memory_profile is not None
    assert "long_term" in memory_profile.requested_memory_layers
    assert memory_profile.allow_long_term_memory is True
    assert memory_profile.writeback_policy == "task_summary_only"

    assert protocol is not None
    assert protocol.enabled is True
    assert "review_feedback" in protocol.message_types


def test_task_execution_policy_normalizes_legacy_worker_spawn_mode(tmp_path: Path) -> None:
    registry = TaskFlowRegistry(tmp_path)

    registry.upsert_task_agent_adoption_plan(
        task_id="task.dev.light_web_game",
        adoption_mode="spawn_worker_allowed",
        default_agent_id="agent:0",
        allowed_agent_categories=("main_agent", "worker_sub_agent"),
        allow_worker_agent_spawn=True,
        worker_agent_blueprint_id="worker.dev.prototype",
    )

    policy = registry.get_task_agent_adoption_plan("task.dev.light_web_game")

    assert policy is not None
    assert policy.adoption_mode == "adopt_with_projection"


def test_coordination_task_is_domain_parent_with_specific_subtask_refs(tmp_path: Path) -> None:
    original = tasks_api.require_runtime
    tasks_api.require_runtime = lambda: _RuntimeStub(tmp_path)  # type: ignore[assignment]
    try:
        asyncio.run(
            tasks_api.upsert_task_system_specific_record(
                "task.research.plan",
                tasks_api.SpecificTaskRecordUpsertRequest(
                    task_id="task.research.plan",
                    task_title="研究规划",
                    task_family="research",
                    task_mode="analysis_plan",
                    description="测试用规划子任务。",
                ),
            )
        )
        asyncio.run(
            tasks_api.upsert_task_system_specific_record(
                "task.research.report",
                tasks_api.SpecificTaskRecordUpsertRequest(
                    task_id="task.research.report",
                    task_title="研究报告",
                    task_family="research",
                    task_mode="analysis_report",
                    description="测试用报告子任务。",
                ),
            )
        )
        payload = asyncio.run(
            tasks_api.upsert_task_system_task_graph_bundle(
                "graph.research.test_parent",
                tasks_api.CoordinationTaskUpsertRequest(
                    graph_id="graph.research.test_parent",
                    title="研究父级协调任务",
                    coordination_mode="review_merge",
                    coordinator_agent_id="agent:20",
                    task_family="research",
                    domain_id="domain.research",
                    agent_group_id="group.research.test_parent",
                    participant_agent_ids=["agent:23", "agent:24"],
                    topology_template_id="topology.research.test_parent",
                    subtask_refs=["task.research.plan", "task.research.report"],
                    graph_nodes=[
                        {"node_id": "coordinator", "node_type": "coordinator", "agent_id": "agent:20", "role": "coordinator"},
                        {"node_id": "plan", "node_type": "subtask", "task_id": "task.research.plan", "agent_id": "agent:23", "role": "participant"},
                        {"node_id": "report", "node_type": "subtask", "task_id": "task.research.report", "agent_id": "agent:24", "role": "participant"},
                    ],
                    graph_edges=[
                        {"edge_id": "e1", "from": "coordinator", "to": "plan", "mode": "draft_request"},
                        {"edge_id": "e2", "from": "plan", "to": "report", "mode": "structured_handoff"},
                    ],
                    communication_modes=["draft_request", "structured_handoff"],
                    enabled=True,
                    metadata={"protocol_id": "protocol.research.review_pipeline"},
                ),
            )
        )
    finally:
        tasks_api.require_runtime = original  # type: ignore[assignment]

    coordination = next(
        item
        for item in payload["task_graph_management"]["task_graphs"]
        if item["graph_id"] == "graph.research.test_parent"
    )
    graph_spec = next(
        item
        for item in payload["task_graph_management"]["task_graph_specs"]
        if item["graph_id"] == "graph.research.test_parent"
    )
    assert coordination["domain_id"] == "domain.research"
    assert coordination["task_family"] == "research"
    assert coordination["subtask_refs"] == ["task.research.plan", "task.research.report"]
    assert {node["task_id"] for node in coordination["graph_nodes"] if node.get("task_id")} == set(coordination["subtask_refs"])
    assert graph_spec["valid"] is True
    assert graph_spec["domain_id"] == "domain.research"
    assert graph_spec["start_node_ids"]
    assert graph_spec["terminal_node_ids"]


def test_task_system_specific_record_is_canonical_and_assignment_becomes_compat_view(tmp_path: Path) -> None:
    original = tasks_api.require_runtime
    tasks_api.require_runtime = lambda: _RuntimeStub(tmp_path)  # type: ignore[assignment]
    try:
        record_payload = asyncio.run(
            tasks_api.upsert_task_system_specific_record(
                "task.dev.light_web_game",
                tasks_api.SpecificTaskRecordUpsertRequest(
                    task_id="task.dev.light_web_game",
                    task_title="轻量网页小游戏开发",
                    task_family="development",
                    task_mode="light_web_game",
                    description="canonical specific task record",
                    input_contract_id="LightWebGameTaskInput",
                    output_contract_id="LightWebGameResult",
                    acceptance_profile_id="accept.game.delivery",
                    default_flow_contract_id="flow.dev.light_web_game",
                    default_workflow_id="workflow.dev.light_web_game",
                    default_projection_policy="workflow_compatible_or_task_default",
                    task_policy={
                        "safety_policy": {"verification_mode": "qa_required"},
                        "task_structure": {"memory_scope_hint": "conversation_read_write"},
                    },
                    enabled=True,
                    metadata={"runtime_recipe_id": "runtime.recipe.light_web_game"},
                ),
            )
        )
    finally:
        tasks_api.require_runtime = original  # type: ignore[assignment]

    registry = TaskFlowRegistry(tmp_path)
    specific_record = registry.get_specific_task_record("task.dev.light_web_game")
    compat_assignment = registry.get_task_assignment("task.dev.light_web_game")

    assert record_payload["task_management"]["specific_task_records"]
    assert specific_record is not None
    assert specific_record.description == "canonical specific task record"
    assert specific_record.acceptance_profile_id == "accept.game.delivery"
    assert specific_record.default_flow_contract_id == "flow.dev.light_web_game"

    assert compat_assignment is not None
    assert compat_assignment.task_id == specific_record.task_id
    assert compat_assignment.task_title == specific_record.task_title
    assert compat_assignment.workflow_id == specific_record.default_workflow_id
    assert compat_assignment.input_contract_id == specific_record.input_contract_id


def test_task_system_no_longer_seeds_concrete_writing_task_objects(tmp_path: Path) -> None:
    registry = TaskFlowRegistry(tmp_path)

    removed_refs = {
        "flows": [
            "flow.writing.short_story",
            "flow.writing.longform_novel_project",
        ],
        "records": [
            "task.writing.short_story",
            "task.writing.longform_novel_project",
        ],
        "protocols": [
            "protocol.writing.short_story_pipeline",
            "protocol.writing.longform_project_bootstrap",
        ],
        "coordination_tasks": [
            "graph.writing.short_story_pipeline",
            "graph.writing.longform_project_bootstrap",
        ],
        "adoption_plans": [
            "task.writing.longform_novel_project",
        ],
    }

    for flow_id in removed_refs["flows"]:
        assert registry.get_flow(flow_id) is None
    for task_id in removed_refs["records"]:
        assert registry.get_specific_task_record(task_id) is None
        assert registry.get_task_assignment(task_id) is None
    for protocol_id in removed_refs["protocols"]:
        assert registry.get_task_communication_protocol(protocol_id) is None
    for graph_id in removed_refs["coordination_tasks"]:
        assert registry.get_task_graph(graph_id) is None
    for task_id in removed_refs["adoption_plans"]:
        assert registry.get_task_agent_adoption_plan(task_id) is None


def test_task_graph_api_persists_working_memory_strategy_fields(tmp_path: Path) -> None:
    original = tasks_api.require_runtime
    tasks_api.require_runtime = lambda: _RuntimeStub(tmp_path)  # type: ignore[assignment]
    try:
        payload = asyncio.run(
            tasks_api.upsert_task_system_task_graph(
                "graph.test.working_memory",
                tasks_api.TaskGraphUpsertRequest(
                    graph_id="graph.test.working_memory",
                    title="工作记忆策略图",
                    graph_kind="multi_agent",
                    nodes=[
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
                    ],
                    edges=[
                        {
                            "edge_id": "planner_to_writer",
                            "source_node_id": "planner",
                            "target_node_id": "writer",
                            "working_memory_handoff_policy": {
                                "carry_kinds": ["plan_fragment"],
                                "carry_scopes": ["handoff_only"],
                            },
                        }
                    ],
                    working_memory_policy_profile_id="wmprofile.test",
                    working_memory_policy={
                        "enabled": True,
                        "default_scope": "graph_scope",
                    },
                    runtime_policy={
                        "working_memory_profile_id": "wmprofile.test",
                    },
                ),
            )
        )
    finally:
        tasks_api.require_runtime = original  # type: ignore[assignment]

    graph = next(
        item
        for item in payload["task_graph_management"]["task_graphs"]
        if item["graph_id"] == "graph.test.working_memory"
    )
    planner = next(item for item in graph["nodes"] if item["node_id"] == "planner")
    edge = graph["edges"][0]

    assert graph["working_memory_policy_profile_id"] == "wmprofile.test"
    assert graph["working_memory_policy"]["default_scope"] == "graph_scope"
    assert graph["runtime_policy"]["working_memory_profile_id"] == "wmprofile.test"
    assert planner["memory_read_policy"]["readable_kinds"] == ["task_goal", "decision_record"]
    assert planner["dynamic_memory_read_policy"]["max_dynamic_reads_per_node_run"] == 2
    assert edge["working_memory_handoff_policy"]["carry_kinds"] == ["plan_fragment"]


def test_task_graph_api_migrates_legacy_prompt_metadata_to_projection(tmp_path: Path) -> None:
    original = tasks_api.require_runtime
    tasks_api.require_runtime = lambda: _RuntimeStub(tmp_path)  # type: ignore[assignment]
    try:
        payload = asyncio.run(
            tasks_api.upsert_task_system_task_graph(
                "graph.test.prompt_migration",
                tasks_api.TaskGraphUpsertRequest(
                    graph_id="graph.test.prompt_migration",
                    title="Prompt 迁移图",
                    task_family="story",
                    graph_kind="multi_agent",
                    nodes=[
                        {
                            "node_id": "world_review",
                            "node_type": "agent",
                            "title": "世界观审核",
                            "agent_id": "agent:reviewer",
                            "metadata": {
                                "role_prompt": "你是一名世界观审核员。你只负责评审一致性。你不负责扩写剧情。",
                                "role_identity": "你是一名世界观审核员。",
                            },
                        }
                    ],
                ),
            )
        )
    finally:
        tasks_api.require_runtime = original  # type: ignore[assignment]

    graph = next(
        item
        for item in payload["task_graph_management"]["task_graphs"]
        if item["graph_id"] == "graph.test.prompt_migration"
    )
    node = graph["nodes"][0]
    metadata = node["metadata"]

    assert node["projection_id"] == "projection.taskgraph.graph.test.prompt.migration.world.review"
    assert "role_prompt" not in metadata
    assert "role_identity" not in metadata
    assert metadata["legacy_prompt_migration"]["migration_status"] == "migrated"
    assert metadata["legacy_prompt_migration"]["projection_id"] == node["projection_id"]

    projection_cards = SoulFacade(tmp_path).list_projection_cards()["cards"]
    projection = next(item for item in projection_cards if item["projection_id"] == node["projection_id"])
    assert projection["owner_system"] == "task_system"
    assert projection["projection_kind"] == "task_graph_node"
    assert projection["source_task_graph_refs"] == ["graph.test.prompt_migration"]
    assert "你是一名世界观审核员" in projection["projection_prompt"]


def test_task_graph_api_exposes_direct_runtime_spec_in_overview(tmp_path: Path) -> None:
    original = tasks_api.require_runtime
    tasks_api.require_runtime = lambda: _RuntimeStub(tmp_path)  # type: ignore[assignment]
    try:
        asyncio.run(
            tasks_api.upsert_task_system_task_graph(
                "graph.test.direct_spec",
                tasks_api.TaskGraphUpsertRequest(
                    graph_id="graph.test.direct_spec",
                    title="直接运行规范图",
                    domain_id="domain.story",
                    task_family="story",
                    graph_kind="multi_agent",
                    graph_contract_id="contract.story.graph",
                    runtime_policy={
                        "coordinator_agent_id": "agent:coordinator",
                        "default_execution_mode": "parallel",
                    },
                    nodes=[
                        {
                            "node_id": "draft",
                            "node_type": "agent",
                            "title": "起草",
                            "agent_id": "agent:writer",
                            "phase_id": "drafting",
                        },
                        {
                            "node_id": "review",
                            "node_type": "review_gate",
                            "title": "审核",
                            "agent_id": "agent:reviewer",
                            "review_gate_policy": {"is_review_gate": True},
                        },
                    ],
                    edges=[
                        {
                            "edge_id": "draft_review",
                            "source_node_id": "draft",
                            "target_node_id": "review",
                            "payload_contract_id": "contract.story.payload",
                        }
                    ],
                ),
            )
        )
        payload = asyncio.run(tasks_api.task_system_overview())
        runtime_spec = asyncio.run(tasks_api.compile_task_system_task_graph_runtime_spec("graph.test.direct_spec"))
    finally:
        tasks_api.require_runtime = original  # type: ignore[assignment]

    graph_specs = payload["task_graph_management"]["task_graph_specs"]
    spec = next(item for item in graph_specs if item["graph_id"] == "graph.test.direct_spec")
    draft = next(item for item in spec["nodes"] if item["node_id"] == "draft")
    edge = spec["edges"][0]

    assert spec["diagnostics"]["source"] == "task_system.task_graph_definition_runtime_compiler"
    assert spec["diagnostics"]["graph_contract_id"] == "contract.story.graph"
    assert draft["execution_mode"] == "parallel"
    assert draft["phase_id"] == "drafting"
    assert edge["payload_contract_id"] == "contract.story.payload"
    assert runtime_spec["graph_id"] == "graph.test.direct_spec"
    assert runtime_spec["coordinator_agent_id"] == "agent:coordinator"
