from __future__ import annotations

from skill_system.contracts import SkillContract, SkillRuntimeContract


def test_skill_contract_normalizes_and_validates_runtime_fields() -> None:
    contract = SkillContract.from_runtime(
        SkillRuntimeContract(
            name="demo-skill",
            title="演示 Skill",
            description="用于验证统一契约。",
            path="skills/demo-skill/SKILL.md",
            allowed_tools=["web_search", ""],
            activation_policy="unknown",
            context_mode="bad",
            route_authority="bad",
        )
    )

    assert contract.runtime.activation_policy == "model_visible"
    assert contract.runtime.context_mode == "inline"
    assert contract.runtime.route_authority == "candidate_only"
    assert contract.runtime.allowed_tools == ["web_search"]
    assert contract.validation_errors == []
    assert "Skill: 演示 Skill" in contract.prompt.render_block()


def test_skill_contract_accepts_legacy_registry_payload() -> None:
    contract = SkillContract.from_payload(
        {
            "name": "legacy-skill",
            "title": "旧版 Skill",
            "description": "旧版 registry 仍可兼容。",
            "path": "skills/legacy-skill/SKILL.md",
            "allowed_tools": ["search_knowledge"],
        }
    )

    assert contract.runtime.name == "legacy-skill"
    assert contract.prompt.capability == "旧版 registry 仍可兼容。"
    assert contract.to_registry_record()["schema_version"] == 3
