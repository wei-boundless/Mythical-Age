from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from capability_system.skill_policy import SkillPolicyResolver
from capability_system.skill_contracts import SkillPromptContract, SkillRuntimeContract
from capability_system.skill_registry import SkillDefinition
from capability_system.skill_registry import SkillRegistry
from understanding.query_understanding import QueryUnderstanding


class _RegistryStub:
    def __init__(self, skills):
        self.skills = list(skills)

    def get_by_name(self, name: str | None):
        target = str(name or "").strip().lower()
        return next((skill for skill in self.skills if skill.name.lower() == target), None)


def _skill(name: str, *, activation_policy: str, task_kind: str = "knowledge_lookup") -> SkillDefinition:
    runtime = SkillRuntimeContract(
        name=name,
        title=name,
        description=f"{name} description",
        path=f"capability_system/units/skills/{name}/SKILL.md",
        supported_modalities=["general"],
        supported_task_kinds=[task_kind],
        supported_source_kinds=["knowledge_base"],
        capability_tags=["knowledge_lookup"],
        preferred_route="rag",
        activation_policy=activation_policy,
    ).normalized()
    return SkillDefinition(
        runtime=runtime,
        prompt_view=SkillPromptContract(
            name=runtime.name,
            title=runtime.title,
            capability=runtime.description,
        ),
        validation_errors=[],
    )


def test_manual_and_disabled_skills_are_not_auto_selected() -> None:
    resolver = SkillPolicyResolver(
        _RegistryStub(
            [
                _skill("disabled-rag", activation_policy="disabled"),
                _skill("manual-rag", activation_policy="manual"),
                _skill("visible-rag", activation_policy="model_visible"),
            ]
        )
    )
    task_frame = SimpleNamespace(
        source_kind="knowledge_base",
        task_kind="knowledge_lookup",
        modality="general",
        route="rag",
        capability_requests=["knowledge_lookup"],
        execution_posture="",
        skill_name="",
        preferred_skill="",
        message="知识库查询",
    )

    inspection = resolver.inspect(task_frame=task_frame)

    assert inspection.selected is not None
    assert inspection.selected.name == "visible-rag"
    filtered = {candidate.name: candidate.filter_reason for candidate in inspection.candidates if candidate.filtered}
    assert filtered["disabled-rag"] == "skill_disabled"
    assert filtered["manual-rag"] == "manual_activation_only"


def test_explicit_disabled_skill_is_rejected() -> None:
    resolver = SkillPolicyResolver(_RegistryStub([_skill("disabled-rag", activation_policy="disabled")]))
    task_frame = SimpleNamespace(
        source_kind="knowledge_base",
        task_kind="knowledge_lookup",
        modality="general",
        route="rag",
        capability_requests=["knowledge_lookup"],
        execution_posture="",
        skill_name="disabled-rag",
        preferred_skill="",
        message="知识库查询",
    )

    inspection = resolver.inspect(task_frame=task_frame)

    assert inspection.selected is None
    assert inspection.reasons == ("explicit_skill_disabled",)
    assert inspection.candidates[0].filter_reason == "skill_disabled"


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
