from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from capability_system.skills.contracts import SkillContract, SkillPromptContract, SkillRuntimeContract
from capability_system.skills.paths import CapabilitySkillPaths

SkillPromptView = SkillPromptContract


@dataclass(slots=True)
class SkillDefinition:
    runtime: SkillRuntimeContract
    prompt_view: SkillPromptContract
    validation_errors: list[str]

    def __getattr__(self, attr: str):
        return getattr(self.runtime, attr)

    def render_prompt_block(self) -> str:
        return self.prompt_view.render_block()

    @classmethod
    def from_payload(cls, item: dict[str, object]) -> "SkillDefinition":
        contract = SkillContract.from_payload(item)
        return cls(
            runtime=contract.runtime,
            prompt_view=contract.prompt,
            validation_errors=list(contract.validation_errors),
        )


class SkillRegistry:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.registry_path = CapabilitySkillPaths.from_base_dir(base_dir).skills_registry_path
        self._skills: list[SkillDefinition] = []
        self.reload()

    def reload(self) -> None:
        if not self.registry_path.exists():
            self._skills = []
            return
        try:
            payload = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except Exception:
            self._skills = []
            return
        skills: list[SkillDefinition] = []
        for item in payload.get("skills", []):
            if not isinstance(item, dict):
                continue
            skills.append(SkillDefinition.from_payload(item))
        self._skills = skills

    @property
    def skills(self) -> list[SkillDefinition]:
        return list(self._skills)

    def get_by_name(self, name: str | None) -> SkillDefinition | None:
        if not name:
            return None
        target = name.strip().lower()
        for skill in self._skills:
            if skill.name.lower() == target:
                return skill
        return None


