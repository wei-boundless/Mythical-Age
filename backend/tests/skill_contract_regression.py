from __future__ import annotations

from capability_system.skills.contracts import SkillContract, SkillRuntimeContract


def test_skill_contract_normalizes_and_validates_runtime_fields() -> None:
    contract = SkillContract.from_runtime(
        SkillRuntimeContract(
            name="demo-skill",
            title="演示 Skill",
            description="用于验证统一契约。",
            path="agent_system/skills/builtin/demo-skill/SKILL.md",
            activation_policy="unknown",
            context_mode="bad",
            route_authority="bad",
        )
    )

    assert contract.runtime.activation_policy == "model_visible"
    assert contract.runtime.context_mode == "inline"
    assert contract.runtime.route_authority == "candidate_only"
    assert contract.validation_errors == []
    assert "技能：演示 Skill" in contract.prompt.render_block()


def test_skill_contract_accepts_historical_registry_payload() -> None:
    contract = SkillContract.from_payload(
        {
            "name": "historic-skill",
            "title": "历史 Skill",
            "description": "旧版 registry 仍可兼容。",
            "path": "agent_system/skills/builtin/historic-skill/SKILL.md",
        }
    )

    assert contract.runtime.name == "historic-skill"
    assert contract.prompt.capability == "旧版 registry 仍可兼容。"
    assert contract.to_registry_record()["schema_version"] == 3


def test_skill_contract_does_not_default_unknown_route_to_rag() -> None:
    contract = SkillContract.from_runtime(
        SkillRuntimeContract(
            name="authoring-skill",
            title="能力编写",
            description="用于能力编写。",
            path="agent_system/skills/builtin/authoring-skill/SKILL.md",
            preferred_route="",
        )
    )

    assert contract.runtime.preferred_route == ""


def test_skill_contract_requires_explicit_operation_for_known_routes() -> None:
    contract = SkillContract.from_runtime(
        SkillRuntimeContract(
            name="bad-rag",
            title="坏检索",
            description="缺少依赖声明。",
            path="agent_system/skills/builtin/bad-rag/SKILL.md",
            preferred_route="rag",
        )
    )

    assert "preferred_route rag requires explicit op.mcp_retrieval in requires_operations" in contract.validation_errors


def test_skill_contract_preserves_negative_activation_guidance() -> None:
    contract = SkillContract.from_payload(
        {
            "name": "research-skill",
            "title": "研究 Skill",
            "description": "用于验证不适用场景。",
            "path": "agent_system/skills/builtin/research-skill/SKILL.md",
            "not_for": ["只需要一条新闻时不要使用。"],
        }
    )

    assert contract.runtime.not_for == ["只需要一条新闻时不要使用。"]
    assert contract.to_registry_record()["not_for"] == ["只需要一条新闻时不要使用。"]


