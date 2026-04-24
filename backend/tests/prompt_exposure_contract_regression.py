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


FORBIDDEN_PROMPT_POLICY_TOKENS = (
    "allowed_tools",
    "route_authority",
    "reference_paths",
    "ToolScope",
    "SkillToolScope",
    "PermissionDecision",
    "trust_level",
)


def main() -> None:
    frame = QueryUnderstanding(
        source_kind="knowledge_base",
        task_kind="faq_explanation",
        modality="general",
        route="rag",
        capability_requests=["faq"],
        candidate_tools=["search_knowledge"],
    )
    skill_frame = SkillPolicyResolver(SkillRegistry(ROOT)).resolve(task_frame=frame)
    assert skill_frame is not None

    dispatch = CapabilityDispatchScheduler().resolve(
        task_frame=frame,
        active_skill=skill_frame.skill,
        tool_registry=ToolRegistry(ROOT),
    )
    prompt_payload = dispatch.prompt_exposure.to_dict()
    prompt_text = str(prompt_payload)

    assert prompt_payload["exposure_policy"] == "model_visible_only"
    assert prompt_payload["active_skill_name"] == "rag-skill"
    assert "Skill: 知识库问答" in prompt_payload["skill_prompt_block"]
    for forbidden in FORBIDDEN_PROMPT_POLICY_TOKENS:
        assert forbidden not in prompt_text

    dispatch_payload = dispatch.to_dict()
    assert dispatch_payload["effective_tool_scope"]["allowed_tools"] == ("search_knowledge",)
    assert "effective_tool_scope" not in prompt_payload

    print("ALL PASSED (prompt exposure contract)")


if __name__ == "__main__":
    main()
