from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tools.contracts import SkillToolScope

from .registry import SkillDefinition, SkillPromptView, SkillRegistry


@dataclass(frozen=True, slots=True)
class SkillPolicyFrame:
    """Runtime-only skill policy selected from structured task signals."""

    skill: SkillDefinition
    prompt_view: SkillPromptView
    tool_scope: SkillToolScope
    reasons: tuple[str, ...] = ()

    @property
    def name(self) -> str:
        return self.skill.name

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.skill.name,
            "title": self.skill.title,
            "tool_scope": self.tool_scope.to_dict(),
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True, slots=True)
class _SkillMatch:
    skill: SkillDefinition
    specificity: tuple[int, int, int, int, int]
    reasons: tuple[str, ...]


@dataclass(slots=True)
class SkillPolicyResolver:
    """Resolve skills from structural contracts, not prompt text or keywords."""

    registry: SkillRegistry

    def resolve(
        self,
        *,
        task_frame: Any,
    ) -> SkillPolicyFrame | None:
        if str(getattr(task_frame, "execution_posture", "") or "") == "bounded_agent":
            return None

        explicit_name = str(getattr(task_frame, "skill_name", "") or "").strip()
        if explicit_name:
            skill = self.registry.get_by_name(explicit_name)
            if skill is not None:
                return self._frame(skill, reasons=("explicit_skill_name",))

        skills = list(getattr(self.registry, "skills", []) or [])
        if not skills:
            return None

        candidates = [
            match
            for skill in skills
            for match in [self._match(skill, task_frame=task_frame)]
            if match is not None
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda item: item.specificity, reverse=True)
        selected = candidates[0]
        return self._frame(selected.skill, reasons=selected.reasons)

    def _match(self, skill: SkillDefinition, *, task_frame: Any) -> _SkillMatch | None:
        if self._is_forbidden(skill, task_frame):
            return None

        tool_name = str(getattr(task_frame, "tool_name", "") or "").strip()
        candidate_tools = tuple(
            str(item).strip()
            for item in list(getattr(task_frame, "candidate_tools", []) or [])
            if str(item).strip()
        )
        capabilities = tuple(
            str(item).strip()
            for item in list(getattr(task_frame, "capability_requests", []) or [])
            if str(item).strip()
        )
        task_kind = str(getattr(task_frame, "task_kind", "") or "").strip()
        source_kind = str(getattr(task_frame, "source_kind", "") or "").strip()
        modality = str(getattr(task_frame, "modality", "") or "").strip()

        reasons: list[str] = []
        direct_tool_match = int(bool(tool_name and tool_name in set(skill.allowed_tools)))
        if direct_tool_match:
            reasons.append("tool_contract_match")

        candidate_tool_match = int(bool(set(candidate_tools) & set(skill.allowed_tools)))
        if candidate_tool_match:
            reasons.append("candidate_tool_contract_match")

        capability_match = len(set(capabilities) & set(skill.capability_tags))
        if capability_match:
            reasons.append("capability_contract_match")

        task_match = int(bool(task_kind and task_kind in set(skill.supported_task_kinds)))
        if task_match:
            reasons.append("task_kind_contract_match")

        source_match = int(bool(source_kind and source_kind in set(skill.supported_source_kinds)))
        if source_match:
            reasons.append("source_kind_contract_match")

        modality_match = int(bool(modality and modality in set(skill.supported_modalities)))
        if modality_match:
            reasons.append("modality_contract_match")

        has_execution_anchor = direct_tool_match or candidate_tool_match
        has_skill_contract = capability_match and (task_match or source_match or modality_match)
        has_route_contract = task_match and source_match and modality_match
        if not (has_execution_anchor or has_skill_contract or has_route_contract):
            return None

        specificity = (
            direct_tool_match,
            candidate_tool_match,
            capability_match,
            task_match + source_match + modality_match,
            -len(skill.allowed_tools),
        )
        return _SkillMatch(
            skill=skill,
            specificity=specificity,
            reasons=tuple(reasons),
        )

    def _is_forbidden(self, skill: SkillDefinition, task_frame: Any) -> bool:
        route = str(getattr(task_frame, "route", "") or "").strip()
        return bool(route and route in set(skill.forbidden_routes))

    def _frame(self, skill: SkillDefinition, *, reasons: tuple[str, ...]) -> SkillPolicyFrame:
        return SkillPolicyFrame(
            skill=skill,
            prompt_view=skill.prompt_view,
            tool_scope=skill.tool_scope(),
            reasons=reasons,
        )
