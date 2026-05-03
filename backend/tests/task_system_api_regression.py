from __future__ import annotations

import asyncio
from pathlib import Path

from api import tasks as tasks_api
from tasks import TaskFlowRegistry


class _RuntimeStub:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)


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
    assert summary["adoption_plan_count"] >= 1
    assert summary["memory_request_profile_count"] >= 1
    assert summary["communication_protocol_count"] >= 1
    assert task_management["specific_task_records"]
    assert task_management["task_flow_definitions"]
    assert task_management["projection_bindings"]
    assert task_management["flow_contract_bindings"]
    assert task_management["agent_adoption_plans"]
    assert task_management["memory_request_profiles"]
    assert coordination_management["communication_protocols"]
    assert diagnostics["template_validation_matrix"]["authority"] == "task_system.template_validation_matrix"
    assert diagnostics["link_permission_matrix"]["authority"] == "task_system.link_permission_matrix"
    assert diagnostics["agent_task_connections"]["authority"] == "task_system.agent_task_connections"
    assert diagnostics["agent_carrying_profiles"]["authority"] == "task_system.agent_carrying_profiles"
    assert diagnostics["connection_diagnostics"]["authority"] == "task_system.connection_diagnostics"


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
        adoption_payload = asyncio.run(
            tasks_api.upsert_task_system_agent_adoption_plan(
                "task.dev.light_web_game",
                tasks_api.TaskAgentAdoptionPlanUpsertRequest(
                    task_id="task.dev.light_web_game",
                    adoption_mode="adopt_with_projection",
                    default_agent_id="agent:0",
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
    adoption_plan = registry.get_task_agent_adoption_plan("task.dev.light_web_game")
    memory_profile = registry.get_task_memory_request_profile("task.dev.light_web_game")
    protocol = registry.get_task_communication_protocol("protocol.dev.parallel_review")

    assert projection_payload["task_management"]["projection_bindings"]
    assert flow_contract_payload["task_management"]["flow_contract_bindings"]
    assert adoption_payload["task_management"]["agent_adoption_plans"]
    assert memory_payload["task_management"]["memory_request_profiles"]
    assert protocol_payload["coordination_management"]["communication_protocols"]

    assert projection_binding is not None
    assert projection_binding.projection_selection_mode == "allow_list"
    assert projection_binding.default_projection_id == "projection.dev.builder"
    assert projection_binding.projection_required is True

    assert flow_binding is not None
    assert flow_binding.override_policy == "strict_task_default"
    assert flow_binding.verification_gate_profile == "gate.dev.qa"

    assert adoption_plan is not None
    assert adoption_plan.adoption_mode == "adopt_with_projection"
    assert adoption_plan.allow_worker_agent_spawn is True
    assert adoption_plan.worker_agent_blueprint_id == "worker.dev.prototype"

    assert memory_profile is not None
    assert "long_term" in memory_profile.requested_memory_layers
    assert memory_profile.allow_long_term_memory is True
    assert memory_profile.writeback_policy == "task_summary_only"

    assert protocol is not None
    assert protocol.enabled is True
    assert "review_feedback" in protocol.message_types


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
