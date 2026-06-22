from __future__ import annotations

import json
from pathlib import Path

from harness.runtime.compiler import RuntimeCompiler
from harness.runtime.task_contract_manifest import build_task_contract_manifest
from task_system.contracts.execution_obligation import build_execution_obligation
from task_system.contracts.task_requirement_contracts import build_task_requirement_contract
from task_system.tasks.definitions import select_runtime_task_definitions


def _backend_dir() -> Path:
    return Path(__file__).resolve().parents[1]


def _contract() -> dict[str, object]:
    return {
        "contract_id": "contract:task-contract-manifest",
        "task_run_goal": "Validate task contract manifest",
        "completion_criteria": ["manifest attached"],
        "required_artifacts": [{"artifact_kind": "markdown_document", "path": "report.md"}],
        "plan_contract": {
            "plan_id": "plan:task-contract-manifest",
            "plan_status": "agent_managed",
            "major_steps": ["Attach manifest", "Verify acceptance"],
        },
    }


def _planning_protocol() -> dict[str, object]:
    return {
        "authority": "harness.runtime.planning_protocol",
        "todo_required": True,
    }


def _payload_after_title(content: str, title: str) -> dict[str, object]:
    text = str(content or "")
    assert text.startswith(title + "\n")
    return json.loads(text.split("\n", 1)[1])


def _message_payload_with_title(packet, title: str) -> dict[str, object]:
    for message in packet.model_messages:
        content = str(dict(message).get("content") or "")
        if content.startswith(title + "\n"):
            return _payload_after_title(content, title)
    raise AssertionError(f"missing model message title: {title}")


def test_task_contract_manifest_renders_task_execution_model_visible_payload() -> None:
    model_visible_contract = {
        "task_run_goal": "Validate task contract manifest",
        "completion_criteria": ["manifest attached"],
        "authority": "harness.runtime.task_contract.model_visible",
    }
    manifest = build_task_contract_manifest(
        invocation_kind="task_execution",
        model_visible_contract=model_visible_contract,
        planning_protocol=_planning_protocol(),
        source_ref="contract:task-contract-manifest",
    )

    assert manifest.source_ref == "contract:task-contract-manifest"
    assert manifest.contract_hash.startswith("sha256:")
    assert manifest.planning_protocol_hash.startswith("sha256:")
    assert manifest.contract_kind == "task_contract"
    assert manifest.completion_criteria_count == 1
    assert manifest.to_model_visible_payload() == {
        "task_contract": model_visible_contract,
        "planning_protocol": _planning_protocol(),
    }


def test_task_execution_packet_attaches_task_contract_manifest_without_prompt_drift() -> None:
    result = RuntimeCompiler(base_dir=_backend_dir()).compile_task_execution_packet(
        session_id="session:task-contract-manifest",
        task_run={"task_run_id": "taskrun:task-contract-manifest", "diagnostics": {"executor_status": "running"}},
        contract=_contract(),
        observations=[],
        runtime_assembly={
            "profile": {"profile_ref": "main_interactive_agent"},
            "task_environment": {"environment_id": "env.general.workspace"},
        },
    )

    packet = result.packet
    contract_payload = _message_payload_with_title(packet, "Task execution task contract")
    contract_segment = next(
        segment
        for segment in list(packet.segment_plan.get("segments") or [])
        if dict(segment).get("kind") == "task_contract_stable"
    )
    prompt_manifest = dict(packet.diagnostics["prompt_manifest"])

    assert contract_payload == {
        "task_contract": packet.task_contract_manifest["model_visible_contract"],
        "planning_protocol": packet.task_contract_manifest["planning_protocol"],
    }
    assert contract_payload["task_contract"] == packet.task_contract_manifest["model_visible_contract"]
    assert contract_payload["planning_protocol"] == packet.task_contract_manifest["planning_protocol"]
    assert contract_segment["source_ref"] == packet.task_contract_manifest["source_ref"]
    assert prompt_manifest["task_contract_manifest"] == packet.task_contract_manifest
    assert packet.diagnostics["task_contract_manifest"] == packet.task_contract_manifest
    assert packet.task_contract_manifest["source_ref"] == "contract:task-contract-manifest"
    assert contract_payload["task_contract"]["goal_contract"]["task_run_goal"] == "Validate task contract manifest"
    assert contract_payload["task_contract"]["plan_contract"]["plan_id"] == "plan:task-contract-manifest"
    assert contract_payload["task_contract"]["acceptance_contract"]["completion_criteria"] == ["manifest attached"]
    assert contract_payload["task_contract"]["acceptance_contract"]["required_artifacts"][0]["artifact_kind"] == "markdown_document"


def test_single_agent_turn_does_not_attach_task_contract_manifest() -> None:
    result = RuntimeCompiler(base_dir=_backend_dir()).compile_single_agent_turn_packet(
        session_id="session:task-contract-single",
        turn_id="turn:task-contract-single",
        agent_invocation_id="aginvoke:task-contract-single",
        user_message="Answer briefly.",
        history=[],
        runtime_assembly={
            "profile": {"profile_ref": "main_interactive_agent"},
            "task_environment": {"environment_id": "env.general.workspace"},
        },
    )

    packet = result.packet
    prompt_manifest = dict(packet.diagnostics["prompt_manifest"])

    assert packet.task_contract_manifest == {}
    assert "task_contract_manifest" not in prompt_manifest
    assert "task_contract_manifest" not in packet.diagnostics


def test_task_requirement_contract_ignores_legacy_goal_fields_for_single_agent_authority() -> None:
    legacy_only = build_task_requirement_contract(
        session_id="session:contract-authority",
        task_id="task:legacy-only",
        user_goal="请分析当前问题。",
        current_turn_context={
            "task_goal_spec": {"task_goal_type": "frontend_app_delivery"},
            "goal_frame": {"task_goal_type": "code_fix_execution"},
            "semantic_task_type": "material_synthesis",
        },
    )
    canonical = build_task_requirement_contract(
        session_id="session:contract-authority",
        task_id="task:canonical",
        user_goal="请修复代码并验证。",
        current_turn_context={
            "task_contract_seed": {
                "task_goal_type": "code_fix_execution",
                "working_scope": {"target_objects": ["backend/example.py"]},
                "capability_intent": {"needed_capability_groups": ["file_work"]},
                "observation_contract": {"evidence_policy": "verification_required"},
            },
            "task_goal_spec": {"task_goal_type": "frontend_app_delivery"},
            "semantic_task_type": "material_synthesis",
        },
    )

    assert legacy_only.task_goal_type == "general"
    assert legacy_only.diagnostics["legacy_goal_fields"]["fields"]["task_goal_spec"]["runtime_authority"] == "ignored"
    assert canonical.task_goal_type == "code_fix_execution"
    assert canonical.diagnostics["canonical_task_contract_seed"]["task_goal_type"] == "code_fix_execution"
    assert canonical.diagnostics["legacy_goal_fields"]["fields"]["semantic_task_type"]["runtime_authority"] == "ignored"


def test_execution_obligation_ignores_legacy_goal_fields_for_single_agent_authority() -> None:
    legacy_only = build_execution_obligation(
        session_id="session:obligation-authority",
        task_id="task:legacy-only",
        user_goal="请分析当前问题。",
        current_turn_context={
            "task_goal_spec": {
                "task_goal_type": "code_fix_execution",
                "forbidden_actions": ["modify_code"],
            },
            "goal_frame": {"explicit_constraints": ["不要修改源项目"]},
        },
    ).to_dict()
    canonical = build_execution_obligation(
        session_id="session:obligation-authority",
        task_id="task:canonical",
        user_goal="请分析当前问题。",
        current_turn_context={
            "task_contract_seed": {"forbidden_actions": ["modify_code"]},
            "task_goal_spec": {"forbidden_actions": []},
        },
    ).to_dict()

    assert legacy_only["forbidden_actions"] == []
    assert legacy_only["extraction_evidence"]["legacy_goal_fields"]["fields"]["task_goal_spec"]["runtime_authority"] == "ignored"
    assert set(canonical["forbidden_actions"]) == {"modify_code", "write_file", "edit_file"}


def test_runtime_task_definition_selection_ignores_legacy_task_goal_spec() -> None:
    legacy_only = select_runtime_task_definitions(
        "请分析这份材料。",
        query_understanding={"task_goal_spec": {"task_goal_type": "external_research"}},
    )
    canonical = select_runtime_task_definitions(
        "请实现并验证。",
        query_understanding={
            "agent_turn_action_request": {
                "action_type": "request_task_run",
                "task_contract_seed": {
                    "task_goal_type": "frontend_app_delivery",
                    "capability_intent": {"needed_capability_groups": ["artifact_generation"]},
                },
            },
            "task_goal_spec": {"task_goal_type": "inspection"},
        },
    )

    assert [item.definition_id for item in legacy_only] == [
        "task.task_execution",
        "task.inspection_and_correction",
    ]
    assert [item.definition_id for item in canonical] == [
        "task.task_execution",
        "task.inspection_and_correction",
    ]
