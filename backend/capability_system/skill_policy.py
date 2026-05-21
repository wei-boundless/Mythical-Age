from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from capability_system.skill_registry import SkillDefinition, SkillPromptView, SkillRegistry


@dataclass(frozen=True, slots=True)
class SkillPolicyFrame:
    skill: SkillDefinition
    prompt_view: SkillPromptView
    reasons: tuple[str, ...] = ()

    @property
    def name(self) -> str:
        return self.skill.name

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.skill.name,
            "title": self.skill.title,
            "skill_contract": {
                "supported_modalities": list(self.skill.supported_modalities),
                "supported_task_kinds": list(self.skill.supported_task_kinds),
                "supported_source_kinds": list(self.skill.supported_source_kinds),
                "capability_tags": list(self.skill.capability_tags),
                "preferred_route": self.skill.preferred_route,
                "activation_policy": self.skill.activation_policy,
                "context_mode": self.skill.context_mode,
                "route_authority": self.skill.route_authority,
                "requires_operations": list(self.skill.requires_operations),
                "requires_capabilities": list(self.skill.requires_capabilities),
            },
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
                if skill.activation_policy == "disabled":
                    return SkillPolicyInspection(
                        candidates=(
                            SkillPolicyCandidate(
                                name=skill.name,
                                title=skill.title,
                                filtered=True,
                                filter_reason="skill_disabled",
                                reasons=("explicit_skill_name", "skill_disabled"),
                            ),
                        ),
                        reasons=("explicit_skill_disabled",),
                    )
                frame = self._frame(skill, reasons=("explicit_skill_name",))
                return SkillPolicyInspection(
                    selected=frame,
                    candidates=(
                        SkillPolicyCandidate(
                            name=skill.name,
                            title=skill.title,
                            selected=True,
                            specificity=(1, 1, 1, 1, 1),
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
            if skill.activation_policy == "disabled":
                candidate_views.append(
                    SkillPolicyCandidate(
                        name=skill.name,
                        title=skill.title,
                        filtered=True,
                        filter_reason="skill_disabled",
                    )
                )
                continue
            if skill.activation_policy == "manual":
                candidate_views.append(
                    SkillPolicyCandidate(
                        name=skill.name,
                        title=skill.title,
                        filtered=True,
                        filter_reason="manual_activation_only",
                    )
                )
                continue
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

        capabilities = tuple(
            str(item).strip()
            for item in list(getattr(task_frame, "capability_requests", []) or [])
            if str(item).strip()
        )
        task_kind = str(getattr(task_frame, "task_kind", "") or "").strip()
        source_kind = str(getattr(task_frame, "source_kind", "") or "").strip()
        modality = str(getattr(task_frame, "modality", "") or "").strip()
        preferred_skill = str(getattr(task_frame, "preferred_skill", "") or getattr(task_frame, "skill_name", "") or "").strip()
        message = str(getattr(task_frame, "message", "") or getattr(task_frame, "query", "") or "").lower()

        reasons: list[str] = []
        preferred_skill_match = int(bool(preferred_skill and preferred_skill == skill.name))
        if preferred_skill_match:
            reasons.append("preferred_skill_match")

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

        hint_match = int(bool(message and _text_matches(skill.routing_hints, message)))
        if hint_match:
            reasons.append("routing_hint_match")

        example_match = int(bool(message and _text_matches(skill.examples, message)))
        if example_match:
            reasons.append("example_match")

        has_skill_contract = capability_match and (task_match or source_match or modality_match)
        has_route_contract = task_match and source_match and modality_match
        if not (preferred_skill_match or has_skill_contract or has_route_contract or example_match):
            return None

        specificity = (
            preferred_skill_match,
            int(has_route_contract),
            capability_match,
            task_match + source_match + modality_match,
            hint_match + example_match,
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
            reasons=reasons,
        )


def _text_matches(patterns: list[str] | tuple[str, ...], text: str) -> bool:
    normalized_text = text.lower()
    for pattern in patterns:
        normalized = str(pattern or "").strip().lower()
        if normalized and normalized in normalized_text:
            return True
    return False
