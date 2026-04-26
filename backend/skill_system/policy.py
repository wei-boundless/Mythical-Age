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
class SkillPolicyCandidate:
    name: str
    title: str
    selected: bool = False
    filtered: bool = False
    filter_reason: str = ""
    specificity: tuple[int, int, int, int, int] = (0, 0, 0, 0, 0)
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "selected": self.selected,
            "filtered": self.filtered,
            "filter_reason": self.filter_reason,
            "specificity": list(self.specificity),
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True, slots=True)
class SkillPolicyInspection:
    selected: SkillPolicyFrame | None = None
    candidates: tuple[SkillPolicyCandidate, ...] = ()
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected": self.selected.to_dict() if self.selected is not None else None,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
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
        return self.inspect(task_frame=task_frame).selected

    def inspect(
        self,
        *,
        task_frame: Any,
    ) -> SkillPolicyInspection:
        if str(getattr(task_frame, "execution_posture", "") or "") == "bounded_agent":
            return SkillPolicyInspection(reasons=("bounded_agent_skips_skill_policy",))

        explicit_name = str(getattr(task_frame, "skill_name", "") or "").strip()
        if explicit_name:
            skill = self.registry.get_by_name(explicit_name)
            if skill is not None:
                frame = self._frame(skill, reasons=("explicit_skill_name",))
                return SkillPolicyInspection(
                    selected=frame,
                    candidates=(
                        SkillPolicyCandidate(
                            name=skill.name,
                            title=skill.title,
                            selected=True,
                            specificity=(1, 1, 1, 1, 0),
                            reasons=("explicit_skill_name",),
                        ),
                    ),
                    reasons=("explicit_skill_name",),
                )

        skills = list(getattr(self.registry, "skills", []) or [])
        if not skills:
            return SkillPolicyInspection(reasons=("empty_skill_registry",))

        matches: list[_SkillMatch] = []
        candidate_views: list[SkillPolicyCandidate] = []
        for skill in skills:
            if self._is_forbidden(skill, task_frame):
                candidate_views.append(
                    SkillPolicyCandidate(
                        name=skill.name,
                        title=skill.title,
                        filtered=True,
                        filter_reason="forbidden_route",
                    )
                )
                continue
            match = self._match(skill, task_frame=task_frame)
            if match is None:
                candidate_views.append(
                    SkillPolicyCandidate(
                        name=skill.name,
                        title=skill.title,
                        filtered=True,
                        filter_reason="no_structural_contract_match",
                    )
                )
                continue
            matches.append(match)

        if not matches:
            return SkillPolicyInspection(
                candidates=tuple(candidate_views),
                reasons=("no_skill_contract_match",),
            )
        matches.sort(key=lambda item: item.specificity, reverse=True)
        selected = matches[0]
        selected_frame = self._frame(selected.skill, reasons=selected.reasons)
        matched_views = [
            SkillPolicyCandidate(
                name=match.skill.name,
                title=match.skill.title,
                selected=match.skill.name == selected.skill.name,
                specificity=match.specificity,
                reasons=match.reasons,
            )
            for match in matches
        ]
        return SkillPolicyInspection(
            selected=selected_frame,
            candidates=tuple([*matched_views, *candidate_views]),
            reasons=("skill_policy_inspected",),
        )

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
