from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from capability_system.paths import CapabilitySystemPaths
from capability_system.skill_contracts import SkillContract, SkillPromptContract, SkillRuntimeContract
from capability_system.tool_contracts import SkillToolScope

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

    def allowed_tool_scope(self) -> list[str]:
        return list(self.runtime.allowed_tools)

    def tool_scope(self) -> SkillToolScope:
        return SkillToolScope(
            source="skill",
            allowed_tools=tuple(self.allowed_tool_scope()),
            capability_constraints=tuple(self.runtime.capability_tags),
            trust_level="project",
            reason="skill_runtime_contract",
            skill_name=self.runtime.name,
            activation_policy=self.runtime.activation_policy,
            context_mode=self.runtime.context_mode,
        )

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
        self.registry_path = CapabilitySystemPaths.from_base_dir(base_dir).skills_registry_path
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

    def get_for_tool(self, tool_name: str | None) -> SkillDefinition | None:
        if not tool_name:
            return None
        target = tool_name.strip().lower()
        for skill in self._skills:
            if any(tool.lower() == target for tool in skill.allowed_tools):
                return skill
        return None

    def match_for_query(
        self,
        message: str,
        route: str,
        modality: str,
        *,
        task_kind: str | None = None,
        source_kind: str | None = None,
        tool_name: str | None = None,
        candidate_tools: list[str] | None = None,
    ) -> SkillDefinition | None:
        from capability_system.skill_policy import SkillPolicyResolver

        task_frame = SimpleNamespace(
            route=route,
            modality=modality,
            task_kind=task_kind,
            source_kind=source_kind,
            tool_name=tool_name,
            candidate_tools=list(candidate_tools or []),
            capability_requests=[],
            execution_posture="",
            skill_name=None,
        )
        frame = SkillPolicyResolver(self).resolve(task_frame=task_frame)
        return frame.skill if frame is not None else None

    def format_active_skill_block(self, skill: SkillDefinition | None) -> str | None:
        if skill is None:
            return None
        return skill.render_prompt_block()

