from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from capability_system.skill_policy import SkillPolicyResolver
from capability_system.skill_registry import SkillRegistry
from understanding.query_understanding import QueryUnderstanding


def main() -> None:
    resolver = SkillPolicyResolver(SkillRegistry(ROOT))

    realtime = QueryUnderstanding(
        source_kind="external_web",
        task_kind="realtime_lookup",
        modality="realtime",
        route="realtime_network",
        tool_name="web_search",
        capability_requests=["weather", "latest_information"],
    )
    assert resolver.resolve(task_frame=realtime) is None

    pdf = QueryUnderstanding(
        source_kind="document",
        task_kind="document_page",
        modality="pdf",
        route="pdf",
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
