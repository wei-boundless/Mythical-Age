from __future__ import annotations

import sys
from dataclasses import asdict
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from intent.task_goal_interpreter import build_task_goal_frame
from task_system.contracts.semantic_task_contracts import build_semantic_task_contract
from task_system.goal_profiles import bind_task_goal_profile, get_task_goal_profile
from understanding.query_understanding import analyze_query_understanding


def test_registered_goal_profile_drives_semantic_contract_fields() -> None:
    message = "请开发一个可运行的浏览器端 2D 肉鸽游戏垂直切片，并真实启动浏览器验证。"
    query = analyze_query_understanding(message)
    goal_frame = build_task_goal_frame(message, query_understanding=asdict(query)).to_dict()

    contract = build_semantic_task_contract(
        session_id="session-domain-profile",
        task_id="task-domain-profile",
        user_goal=message,
        query_understanding=asdict(query),
        current_turn_context={"task_goal_frame": goal_frame},
    )
    payload = contract.to_dict()
    binding = dict(payload["diagnostics"]["task_goal_profile_binding"])
    profile = get_task_goal_profile("game_vertical_slice_delivery")

    assert profile is not None
    assert payload["domain"] == profile.task_domain
    assert payload["professional_profile_id"] == profile.professional_profile_id
    assert payload["deliverables"] == list(profile.default_core_deliverables)
    assert payload["required_reasoning_steps"] == list(profile.default_reasoning_steps)
    assert binding["task_domain"] == "development"
    assert binding["profile_id"] == "game_vertical_slice_delivery"
    assert binding["matched_by"] == "task_goal_type"
    assert "workspace_write" in binding["inherited_capabilities"]


def test_unregistered_goal_profile_binding_is_explicit_fallback() -> None:
    binding = bind_task_goal_profile(
        session_id="session-domain-fallback",
        task_id="task-domain-fallback",
        task_goal_type="unregistered_professional_goal",
        task_goal_frame={
            "task_domain": "custom_domain",
            "required_capabilities": ["workspace_read"],
            "confidence": 0.41,
        },
    ).to_dict()

    assert binding["task_domain"] == "custom_domain"
    assert binding["profile_id"] == "fallback"
    assert binding["matched_by"] == "fallback"
    assert binding["diagnostics"]["fallback_reason"] == "unregistered_task_goal_type"
