from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from api import orchestration_catalog as orchestration_api
from orchestration.resource_inventory import build_runtime_resource_inventory
from runtime.shared.resume_decision import decide_runtime_resume
from runtime.memory.tool_observation_ledger import (
    ToolObservationLedger,
    build_tool_observation_record,
)
from runtime.tool_runtime.tool_result_envelope import build_tool_result_envelope
from prompting.strategy_prototypes import strategy_prototype_for_task_goal
from task_system.goal_profiles import get_task_goal_profile, known_task_goal_types


def test_resource_inventory_keeps_domain_and_projection_non_authoritative() -> None:
    inventory = build_runtime_resource_inventory(Path("backend"))
    items = {item["resource_id"]: item for item in inventory.to_dict()["items"]}

    assert items["resource.execution_obligation"]["can_authorize_side_effects"] is True
    assert items["resource.task_domains"]["can_authorize_side_effects"] is False
    assert items["resource.soul_projection"]["authority_layer"] == "L6_projection_style"


def test_resource_inventory_api_exposes_authority_layers(tmp_path: Path) -> None:
    original = orchestration_api.require_runtime
    orchestration_api.require_runtime = lambda: SimpleNamespace(base_dir=tmp_path)  # type: ignore[assignment]
    try:
        payload = asyncio.run(orchestration_api.orchestration_resource_inventory())
    finally:
        orchestration_api.require_runtime = original  # type: ignore[assignment]

    items = {item["resource_id"]: item for item in payload["items"]}

    assert payload["authority"] == "orchestration.runtime_resource_inventory"
    assert items["resource.execution_obligation"]["can_authorize_side_effects"] is True
    assert items["resource.task_domains"]["can_authorize_side_effects"] is False
    assert str(items["resource.task_domains"]["path"]).startswith(str(tmp_path))


def test_strategy_prototype_is_soft_profile_not_obligation_source() -> None:
    prototype = strategy_prototype_for_task_goal("test_report_triage")

    assert prototype.prototype_id == "test_report_triage"
    assert prototype.prompt_profile_id == "professional.test_report_triage"
    assert prototype.authority == "runtime.strategy_prototype"


def test_task_goal_registry_contains_conversation_tool_and_delivery_families() -> None:
    known = set(known_task_goal_types())

    assert {
        "light_qa",
        "role_conversation",
        "inspection",
        "bounded_tool_task",
        "test_report_triage",
        "code_fix_execution",
        "artifact_delivery",
        "frontend_app_delivery",
        "game_vertical_slice_delivery",
    }.issubset(known)
    assert get_task_goal_profile("frontend_app_delivery").default_core_deliverables
    assert get_task_goal_profile("game_vertical_slice_delivery").required_actions


def test_strategy_prototype_reads_task_goal_registry_binding() -> None:
    assert strategy_prototype_for_task_goal("implementation").prototype_id == "code_change_execution"
    assert strategy_prototype_for_task_goal("light_qa").prototype_id == "generic_professional_task"


def test_tool_observation_ledger_classifies_write_and_verification() -> None:
    write_envelope = build_tool_result_envelope(
        tool_name="write_file",
        tool_args={"path": "output/result.md"},
        result={
            "text": "Write succeeded: output/result.md",
            "structured_payload": {
                "observed_paths": ["output/result.md"],
                "artifact_refs": [{"path": "output/result.md", "kind": "file", "source": "write_file"}],
            },
        },
    )
    terminal_envelope = build_tool_result_envelope(
        tool_name="terminal",
        tool_args={"command": "pytest -q"},
        result={
            "text": "1 passed",
            "structured_payload": {
                "command_receipt": {
                    "command": "pytest -q",
                    "exit_code": 0,
                    "passed": True,
                    "output_preview": "1 passed",
                },
                "verification_intent": {
                    "stage": "verify_output",
                    "obligation": "verify_command",
                    "authority": "harness.loop.agent_phase_pipeline",
                },
            },
        },
    )
    ledger = ToolObservationLedger(ledger_id="ledger:test", task_run_id="taskrun:test")
    ledger = ledger.append(
        build_tool_observation_record(
            observation_ref="obs:write",
            tool_name="write_file",
            tool_args={"path": "output/result.md"},
            result={"result_envelope": write_envelope.to_dict()},
        )
    )
    ledger = ledger.append(
        build_tool_observation_record(
            observation_ref="obs:test",
            tool_name="terminal",
            tool_args={"command": "pytest -q"},
            result={"result_envelope": terminal_envelope.to_dict()},
        )
    )
    summary = ledger.summary()

    assert summary["write_count"] == 1
    assert summary["verification_count"] == 1
    assert "write_output" in summary["satisfied_obligations"]
    assert "verify_command" in summary["satisfied_obligations"]
    assert ledger.records[0].side_effect_hash


def test_resume_decision_uses_checkpoint_without_overriding_current_obligation() -> None:
    checkpoint = SimpleNamespace(
        checkpoint_id="rtchk:taskrun:test:9",
        event_offset=9,
        loop_state=SimpleNamespace(status="running", terminal_reason=""),
    )
    decision = decide_runtime_resume(
        task_run_id="taskrun:test",
        checkpoint=checkpoint,
        current_obligation={"required_writes": [{"kind": "workspace_change"}]},
        resume_intent="continue",
    )

    assert decision.decision == "continue"
    assert decision.resume_from_checkpoint_ref == "rtchk:taskrun:test:9"
    assert decision.current_obligation["required_writes"]


