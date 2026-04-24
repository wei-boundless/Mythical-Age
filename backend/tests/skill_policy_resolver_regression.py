from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from skill_system import SkillPolicyResolver, SkillRegistry
from understanding.query_understanding import QueryUnderstanding


def main() -> None:
    resolver = SkillPolicyResolver(SkillRegistry(ROOT))

    weather = QueryUnderstanding(
        source_kind="external_web",
        task_kind="realtime_lookup",
        modality="realtime",
        route="tool",
        tool_name="get_weather",
        capability_requests=["weather"],
    )
    weather_frame = resolver.resolve(task_frame=weather)
    assert weather_frame is not None
    assert weather_frame.name == "get-weather"
    assert weather_frame.tool_scope.allowed_tools == ("get_weather",)
    assert "tool_contract_match" in weather_frame.reasons

    pdf = QueryUnderstanding(
        source_kind="document",
        task_kind="document_page",
        modality="pdf",
        route="tool",
        capability_requests=["document_analysis"],
    )
    pdf_frame = resolver.resolve(task_frame=pdf)
    assert pdf_frame is not None
    assert pdf_frame.name == "pdf-analysis"
    assert "capability_contract_match" in pdf_frame.reasons

    bounded = QueryUnderstanding(
        source_kind="knowledge_base",
        task_kind="knowledge_lookup",
        modality="general",
        route="agent",
        execution_posture="bounded_agent",
        capability_requests=["knowledge_lookup"],
    )
    assert resolver.resolve(task_frame=bounded) is None

    print("ALL PASSED (skill policy resolver)")


if __name__ == "__main__":
    main()
