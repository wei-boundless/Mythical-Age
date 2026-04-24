from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from query.capability_dispatch import CapabilityDispatchScheduler
from skill_system import SkillPolicyResolver, SkillRegistry
from tools.tool_registry import ToolRegistry
from understanding.query_understanding import QueryUnderstanding


def main() -> None:
    skill_registry = SkillRegistry(ROOT)
    skill_resolver = SkillPolicyResolver(skill_registry)
    tool_registry = ToolRegistry(ROOT)
    scheduler = CapabilityDispatchScheduler()

    frame = QueryUnderstanding(
        source_kind="external_web",
        task_kind="realtime_lookup",
        modality="realtime",
        route="tool",
        tool_name="get_weather",
        capability_requests=["weather"],
        candidate_tools=["get_weather"],
        tool_input={"query": "北京天气"},
    )
    skill_frame = skill_resolver.resolve(task_frame=frame)
    assert skill_frame is not None
    plan = scheduler.resolve(
        task_frame=frame,
        active_skill=skill_frame.skill,
        tool_registry=tool_registry,
    )

    assert plan.skill_policy is not None
    assert plan.skill_policy.name == "get-weather"
    assert plan.effective_tool_scope.source == "skill"
    assert plan.effective_tool_scope.allowed_tools == ("get_weather",)
    assert [candidate.name for candidate in plan.tool_candidates] == ["get_weather"]
    assert plan.selected_tool_request is not None
    assert plan.selected_tool_request.tool_name == "get_weather"

    exposure = plan.prompt_exposure.to_dict()
    assert exposure["active_skill_name"] == "get-weather"
    assert "Skill: 天气查询" in exposure["skill_prompt_block"]
    assert "allowed_tools" not in exposure
    assert "tool_scope" not in exposure
    assert "PermissionDecision" not in str(exposure)

    print("ALL PASSED (capability dispatch)")


if __name__ == "__main__":
    main()
