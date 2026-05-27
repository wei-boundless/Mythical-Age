from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from agent_system.profiles.runtime_profile_models import AgentRuntimeProfile
from runtime.agent_assembly import DirectWorkOrder, build_agent_invocation
from harness.runtime import build_agent_runtime_config, resolve_agent_execution_permit
from harness.runtime.policies import (
    ControlPolicy,
    ModePolicy,
    PlanningPolicy,
)


def test_professional_mode_is_config_preset_not_runtime_kind() -> None:
    config = build_agent_runtime_config(
        selected_recipe_payload={
            "task_mode": "professional_mode",
            "metadata": {
                "interaction_mode": "professional_mode",
            },
        },
        task_operation={},
        agent_runtime_spec={"agent_id": "agent:0", "agent_profile_id": "main_interactive_agent"},
    )

    payload = config.to_dict()
    assert config.interaction_mode == "professional_mode"
    assert payload["control_policy"]["planning_required"] is True
    assert payload["evidence_policy"]["required"] is True
    assert payload["verification_policy"]["required"] is True
    assert payload["closeout_policy"]["required"] is True
    assert payload["enabled_phases"] == [
        "planning",
        "model_turn",
        "tool_followup",
        "evidence",
        "verification",
        "closeout",
    ]
    assert payload["authority"] == "harness.runtime.agent_config"


def test_standard_and_role_modes_keep_lightweight_phase_policy() -> None:
    for mode in ("standard_mode", "role_mode"):
        config = build_agent_runtime_config(
            selected_recipe_payload={
                "task_mode": mode,
                "metadata": {
                    "interaction_mode": mode,
                    "mode_policy": {"interaction_mode": mode},
                },
            },
            task_operation={},
        )

        payload = config.to_dict()
        assert config.interaction_mode == mode
        assert payload["control_policy"]["planning_required"] is False
        assert payload["enabled_phases"] == ["model_turn", "tool_followup"]


def test_unknown_mode_defaults_to_standard_policy() -> None:
    config = build_agent_runtime_config(
        selected_recipe_payload={"task_mode": "unknown"},
        task_operation={"current_turn_context": {"interaction_mode": "unknown"}},
    )

    assert config.interaction_mode == "standard_mode"
    assert config.control_policy.planning_required is False
    assert config.control_policy.followup_allowed is True


def test_mode_policy_does_not_own_runtime_control_policy() -> None:
    assert hasattr(ModePolicy(), "interaction_mode")
    assert not hasattr(ModePolicy(), "planning_required")
    assert ControlPolicy(planning_required=True).planning_required is True
    assert PlanningPolicy(required=True).required is True


def test_professional_mode_policy_lives_under_agent_runtime_config() -> None:
    config = build_agent_runtime_config(
        selected_recipe_payload={
            "task_mode": "professional_mode",
            "metadata": {
                "interaction_mode": "professional_mode",
                "mode_policy": {
                    "interaction_mode": "professional_mode",
                    "tool_policy": {"enabled": True, "allowed_tool_names": ["read_file"]},
                },
                "task_requirement_contract": {
                    "execution_obligation": {"requires_evidence": True},
                },
            },
        },
        task_operation={},
    )

    payload = config.to_dict()
    assert config.interaction_mode == "professional_mode"
    assert payload["tool_policy"]["allowed_tool_names"] == ["read_file"]
    assert payload["control_policy"]["evidence_required"] is True
    assert payload["enabled_phases"][-3:] == ["evidence", "verification", "closeout"]


def test_execution_permit_uses_agent_runtime_config_not_mode_specific_runner_flag() -> None:
    profile = AgentRuntimeProfile(
        agent_profile_id="main_interactive_agent",
        agent_id="agent:0",
        allowed_operations=("op.model_response",),
    )
    invocation = build_agent_invocation(
        DirectWorkOrder(
            work_order_id="",
            task_ref="task.test.agent-runtime-permit",
            agent_id="agent:0",
            agent_profile_id="main_interactive_agent",
            runtime_lane="professional_task",
        ),
        base_dir=BACKEND_DIR,
        agent_runtime_profile=profile,
    )
    selected_recipe = {
        "task_mode": "professional_mode",
        "metadata": {
            "interaction_mode": "professional_mode",
            "tool_execution_policy": {
                "allowed_operation_refs": ["op.read_file"],
                "allowed_tool_names": ["read_file"],
            },
        },
    }
    config = build_agent_runtime_config(
        selected_recipe_payload=selected_recipe,
        task_operation={"selected_recipe": selected_recipe},
        agent_runtime_spec={"agent_id": "agent:0", "agent_profile_id": "main_interactive_agent"},
    )

    permit = resolve_agent_execution_permit(
        invocation.assembly_contract,
        task_operation={"selected_recipe": selected_recipe},
        task_id="task.test.agent-runtime-permit",
        agent_id="agent:0",
        agent_profile_id="main_interactive_agent",
        agent_runtime_config=config,
    )

    diagnostics = dict(permit.get("diagnostics") or {})
    assert "op.read_file" in set(permit["allowed_operations"])
    assert "read_file" in set(permit["visible_tools"])
    assert diagnostics["agent_runtime_tool_policy_adopted"] is True
    assert diagnostics["agent_runtime_enabled_phases"] == [
        "planning",
        "model_turn",
        "tool_followup",
        "evidence",
        "verification",
        "closeout",
    ]
