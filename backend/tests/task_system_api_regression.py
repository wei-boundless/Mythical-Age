from __future__ import annotations

import asyncio
from pathlib import Path

from api import orchestration as orchestration_api
from api import tasks as tasks_api
from orchestration import AgentGroupRegistry
from tasks import TaskFlowRegistry, TaskWorkflowRegistry


class _RuntimeStub:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)


def test_orchestration_agents_payload_exposes_agent_groups(tmp_path: Path) -> None:
    original = orchestration_api.require_runtime
    orchestration_api.require_runtime = lambda: _RuntimeStub(tmp_path)  # type: ignore[assignment]
    try:
        payload = asyncio.run(orchestration_api.orchestration_agents())
    finally:
        orchestration_api.require_runtime = original  # type: ignore[assignment]

    groups = payload["agent_groups"]
    longform_group = next(item for item in groups if item["group_id"] == "group.writing.longform_novel_core")

    assert payload["authority"] == "orchestration.agent_runtime_registry"
    assert longform_group["authority"] == "orchestration.agent_group"
    assert longform_group["coordinator_agent_id"] == "agent:20"
    assert "agent:24" in longform_group["member_agent_ids"]


def test_task_system_overview_exposes_formal_task_management_layers(tmp_path: Path) -> None:
    original = tasks_api.require_runtime
    tasks_api.require_runtime = lambda: _RuntimeStub(tmp_path)  # type: ignore[assignment]
    try:
        payload = asyncio.run(tasks_api.task_system_overview())
    finally:
        tasks_api.require_runtime = original  # type: ignore[assignment]

    summary = payload["summary"]
    task_management = payload["task_management"]
    coordination_management = payload["coordination_management"]
    diagnostics = payload["diagnostics"]

    assert payload["authority"] == "task_system.management_console"
    assert summary["specific_task_record_count"] >= 1
    assert summary["projection_binding_count"] >= 1
    assert summary["flow_contract_binding_count"] >= 1
    assert summary["execution_policy_count"] >= 1
    assert summary["memory_request_profile_count"] >= 1
    assert summary["communication_protocol_count"] >= 1
    assert "agent_management" not in payload
    assert task_management["entry_policies"]
    assert task_management["task_domains"]
    assert task_management["specific_task_records"]
    assert task_management["task_flow_definitions"]
    assert task_management["projection_bindings"]
    assert task_management["flow_contract_bindings"]
    assert task_management["execution_policies"]
    assert task_management["memory_request_profiles"]
    assert coordination_management["communication_protocols"]
    assert diagnostics["template_validation_matrix"]["authority"] == "task_system.template_validation_matrix"
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

    assert payload["summary"]["task_domain_count"] >= 4
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
    assert str(payload["coordination_task_id"]).startswith("coord.")
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
    assert protocol_payload["coordination_management"]["communication_protocols"]

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
        payload = asyncio.run(
            tasks_api.upsert_task_system_coordination_task(
                "coord.writing.test_parent",
                tasks_api.CoordinationTaskUpsertRequest(
                    coordination_task_id="coord.writing.test_parent",
                    title="写作父级协调任务",
                    coordination_mode="chapter_review_loop",
                    coordinator_agent_id="agent:20",
                    task_family="writing",
                    domain_id="domain.writing",
                    agent_group_id="group.writing.longform_novel_core",
                    participant_agent_ids=["agent:23", "agent:24"],
                    topology_template_id="topology.writing.test_parent",
                    subtask_refs=["task.writing.chapter_planning", "task.writing.chapter_drafting"],
                    graph_nodes=[
                        {"node_id": "coordinator", "node_type": "coordinator", "agent_id": "agent:20", "role": "coordinator"},
                        {"node_id": "plan", "node_type": "subtask", "task_id": "task.writing.chapter_planning", "agent_id": "agent:23", "role": "participant"},
                        {"node_id": "draft", "node_type": "subtask", "task_id": "task.writing.chapter_drafting", "agent_id": "agent:24", "role": "participant"},
                    ],
                    graph_edges=[
                        {"edge_id": "e1", "from": "coordinator", "to": "plan", "mode": "draft_request"},
                        {"edge_id": "e2", "from": "plan", "to": "draft", "mode": "structured_handoff"},
                    ],
                    communication_modes=["draft_request", "structured_handoff"],
                    enabled=True,
                    metadata={"protocol_id": "protocol.writing.chapter_pipeline"},
                ),
            )
        )
    finally:
        tasks_api.require_runtime = original  # type: ignore[assignment]

    coordination = next(
        item
        for item in payload["coordination_management"]["coordination_tasks"]
        if item["coordination_task_id"] == "coord.writing.test_parent"
    )
    graph_spec = next(
        item
        for item in payload["coordination_management"]["coordination_graph_specs"]
        if item["coordination_task_id"] == "coord.writing.test_parent"
    )
    execution_policies = payload["task_management"]["execution_policies"]
    chapter_policy = next(item for item in execution_policies if item["task_id"] == "task.writing.chapter_drafting")

    assert coordination["domain_id"] == "domain.writing"
    assert coordination["task_family"] == "writing"
    assert coordination["subtask_refs"] == ["task.writing.chapter_planning", "task.writing.chapter_drafting"]
    assert {node["task_id"] for node in coordination["graph_nodes"] if node.get("task_id")} == set(coordination["subtask_refs"])
    assert graph_spec["valid"] is True
    assert graph_spec["domain_id"] == "domain.writing"
    assert graph_spec["start_node_ids"]
    assert graph_spec["terminal_node_ids"]
    assert chapter_policy["execution_chain_type"] == "coordination_chain"
    assert chapter_policy["metadata"]["coordination_task_id"] == "coord.writing.chapter_pipeline"


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
                    metadata={"template_id": "template.dev.light_web_game"},
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


def test_task_system_includes_formal_short_story_task_objects(tmp_path: Path) -> None:
    registry = TaskFlowRegistry(tmp_path)

    flow = registry.get_flow("flow.writing.short_story")
    record = registry.get_specific_task_record("task.writing.short_story")
    assignment = registry.get_task_assignment("task.writing.short_story")
    memory_profile = registry.get_task_memory_request_profile("task.writing.short_story")
    protocol = registry.get_task_communication_protocol("protocol.writing.short_story_pipeline")
    coordination = registry.get_coordination_task("coord.writing.short_story_pipeline")

    assert flow is not None
    assert flow.task_family == "writing"
    assert flow.default_workflow_id == "workflow.writing.short_story"
    assert flow.metadata.get("template_id") == "template.writing.short_story"

    assert record is not None
    assert record.task_mode == "short_story"
    assert record.default_flow_contract_id == "flow.writing.short_story"

    assert assignment is not None
    assert assignment.task_family == "writing"
    assert assignment.workflow_id == "workflow.writing.short_story"

    assert memory_profile is not None
    assert "long_term" in memory_profile.requested_memory_layers
    assert memory_profile.allow_long_term_memory is True

    assert protocol is not None
    assert protocol.enabled is True

    assert coordination is not None
    assert coordination.enabled is True


def test_task_system_includes_longform_novel_coordination_stack_and_agent_group(tmp_path: Path) -> None:
    registry = TaskFlowRegistry(tmp_path)
    group_registry = AgentGroupRegistry(tmp_path)

    flow = registry.get_flow("flow.writing.chapter_drafting")
    record = registry.get_specific_task_record("task.writing.chapter_drafting")
    protocol = registry.get_task_communication_protocol("protocol.writing.chapter_pipeline")
    coordination = registry.get_coordination_task("coord.writing.chapter_pipeline")
    memory_profile = registry.get_task_memory_request_profile("task.writing.chapter_drafting")
    adoption_plan = registry.get_task_agent_adoption_plan("task.writing.chapter_drafting")
    agent_group = group_registry.get_group("group.writing.longform_novel_core")

    assert flow is not None
    assert flow.default_agent_id == "agent:24"
    assert flow.metadata.get("coordination_task_id") == "coord.writing.chapter_pipeline"

    assert record is not None
    assert record.task_mode == "chapter_drafting"

    assert protocol is not None
    assert protocol.enabled is True
    assert "chapter_draft" in protocol.message_types

    assert coordination is not None
    assert coordination.enabled is True
    assert coordination.agent_group_id == "group.writing.longform_novel_core"
    assert "task.writing.chapter_planning" in coordination.subtask_refs
    assert "task.writing.chapter_drafting" in coordination.subtask_refs
    assert "task.writing.chapter_revision" in coordination.subtask_refs
    assert "agent:24" in coordination.participant_agent_ids
    assert "agent:25" in coordination.participant_agent_ids
    assert "agent:26" in coordination.participant_agent_ids

    assert memory_profile is not None
    assert "novel_bible" in memory_profile.requested_topics

    assert adoption_plan is not None
    assert adoption_plan.to_dict()["execution_chain_type"] == "coordination_chain"

    assert agent_group is not None
    assert agent_group.coordinator_agent_id == "agent:20"
    assert "agent:24" in agent_group.member_agent_ids
