from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from harness.loop.admission import admit_model_action
from harness.loop.model_action_protocol import ModelActionRequest
from harness.runtime.compiler import RuntimeCompiler


def test_single_turn_plan_mode_is_visible_in_prompt_and_output_contract(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()

    packet = RuntimeCompiler(base_dir=backend_dir).compile_single_agent_turn_packet(
        session_id="session:plan-mode",
        turn_id="turn:plan-mode",
        agent_invocation_id="aginvoke:plan-mode",
        user_message="先写计划，不要实施。",
        history=[],
        runtime_assembly={
            "permission_mode": "plan",
            "profile": {
                "profile_ref": "main_interactive_agent",
                "planning_policy": {"plan_mode": "required", "requires_plan": True},
            },
            "task_environment": {"environment_id": "env.general.workspace"},
            "operation_authorization": {"allowed_operations": ["op.read_file", "op.write_file"]},
            "control_capabilities": {"may_call_tools": True, "may_request_task_run": True},
            "available_tools": [
                {"tool_name": "read_file", "operation_id": "op.read_file", "read_only": True},
                {"tool_name": "write_file", "operation_id": "op.write_file", "read_only": False},
            ],
        },
    ).packet

    stable_payload = _payload_after_title(packet, "Single agent turn stable boundary")
    model_input = "\n".join(str(message.get("content") or "") for message in packet.model_messages)

    assert stable_payload["planning_protocol"]["plan_mode_active"] is True
    assert stable_payload["planning_protocol"]["implementation_allowed"] is False
    assert packet.output_contract["planning_protocol"]["mode"] == "plan_only"


def test_task_execution_plan_ref_is_projected_as_task_stable_contract(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()

    packet = RuntimeCompiler(base_dir=backend_dir).compile_task_execution_packet(
        session_id="session:plan-lock",
        task_run={
            "task_run_id": "taskrun:plan-lock",
            "task_id": "task:plan-lock",
            "agent_profile_id": "main_interactive_agent",
        },
        contract={
            "task_run_goal": "按计划修改 prompt 体系",
            "completion_criteria": ["完成计划内改动"],
            "plan_ref": "plan:058",
            "implementation_lock": {
                "plan_ref": "plan:058",
                "status": "approved",
                "approved": True,
            },
        },
        observations=[],
        runtime_assembly={
            "profile": {"profile_ref": "main_interactive_agent"},
            "task_environment": {"environment_id": "env.general.workspace"},
        },
    ).packet

    payload = _payload_after_title(packet, "Task execution task contract")

    assert payload["task_contract"]["plan_ref"] == "plan:058"
    assert payload["task_contract"]["implementation_lock"]["status"] == "approved"
    assert payload["planning_protocol"]["plan_ref"] == "plan:058"
    assert payload["planning_protocol"]["implementation_allowed"] is True
    assert packet.output_contract["planning_protocol"]["plan_ref"] == "plan:058"


def test_plan_mode_admission_blocks_side_effect_tool_even_when_runtime_authorized() -> None:
    action = ModelActionRequest(
        request_id="model-action:plan:write",
        turn_id="turn:plan",
        action_type="tool_call",
        tool_call={"tool_name": "write_file", "args": {"path": "demo.txt", "content": "x"}},
    )

    decision = admit_model_action(
        action,
        packet_allowed_action_types=("tool_call",),
        definitions_by_name={
            "write_file": SimpleNamespace(is_read_only=False, operation_id="op.write_file"),
        },
        allowed_tool_names={"write_file"},
        permission_mode="plan",
        side_effect_policy="runtime_authorized",
    )

    assert decision.decision == "deny"
    assert decision.system_reason == "plan_mode_blocks_side_effect_tool"
    assert decision.resource_errors == ("plan_mode_blocks_side_effect_tool:write_file",)


def test_plan_mode_admission_allows_read_only_tool() -> None:
    action = ModelActionRequest(
        request_id="model-action:plan:read",
        turn_id="turn:plan",
        action_type="tool_call",
        tool_call={"tool_name": "read_file", "args": {"path": "demo.txt"}},
    )

    decision = admit_model_action(
        action,
        packet_allowed_action_types=("tool_call",),
        definitions_by_name={
            "read_file": SimpleNamespace(is_read_only=True, operation_id="op.read_file"),
        },
        allowed_tool_names={"read_file"},
        permission_mode="plan",
        side_effect_policy="runtime_authorized",
    )

    assert decision.decision == "allow"


def _payload_after_title(packet, title: str) -> dict:
    for message in packet.model_messages:
        content = str(message.get("content") or "")
        if content.startswith(title + "\n"):
            return json.loads(content.split("\n", 1)[1])
    raise AssertionError(f"missing message title: {title}")
