from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from request_intent.frame_access import capability_needs, material_kinds
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

        capabilities = tuple(sorted(capability_needs(task_frame)))
        task_kind = _task_kind_from_contract(task_frame)
        source_kind = _source_kind_from_contract(task_frame, kinds=material_kinds(task_frame))
        modality = _modality_from_source_kind(source_kind)

        reasons: list[str] = []
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

        has_skill_contract = bool(
            capability_match and (task_match or source_match or modality_match)
            or source_match and modality_match
            or task_match and (source_match or modality_match)
        )
        has_route_contract = task_match and source_match and modality_match
        if not (has_skill_contract or has_route_contract):
            return None

        specificity = (
            0,
            int(has_route_contract),
            capability_match,
            task_match + source_match + modality_match,
            0,
        )
        return _SkillMatch(
            skill=skill,
            specificity=specificity,
            reasons=tuple(reasons),
        )

    def _is_forbidden(self, skill: SkillDefinition, task_frame: Any) -> bool:
        source_kind = _source_kind_from_contract(task_frame, kinds=material_kinds(task_frame))
        forbidden = set(skill.forbidden_routes)
        return bool(source_kind and source_kind in forbidden)

    def _frame(self, skill: SkillDefinition, *, reasons: tuple[str, ...]) -> SkillPolicyFrame:
        return SkillPolicyFrame(
            skill=skill,
            prompt_view=skill.prompt_view,
            reasons=reasons,
        )


def _frame_mapping(task_frame: Any) -> dict[str, Any]:
    if isinstance(task_frame, dict):
        return dict(task_frame)
    if hasattr(task_frame, "to_dict"):
        return dict(task_frame.to_dict())
    return dict(getattr(task_frame, "__dict__", {}) or {})


def _contract(task_frame: Any) -> dict[str, Any]:
    frame = _frame_mapping(task_frame)
    for key in ("task_requirement_contract", "task_contract_seed", "semantic_contract", "resource_contract"):
        value = frame.get(key)
        if isinstance(value, dict) and value:
            return dict(value)
    return {}


def _resource_contract(task_frame: Any) -> dict[str, Any]:
    frame = _frame_mapping(task_frame)
    for key in ("resource_contract", "task_contract_seed", "task_requirement_contract"):
        value = frame.get(key)
        if isinstance(value, dict):
            resource = value.get("resource_contract") if key != "resource_contract" else value
            if isinstance(resource, dict) and resource:
                return dict(resource)
    return {}


def _task_kind_from_contract(task_frame: Any) -> str:
    contract = _contract(task_frame)
    explicit = str(
        contract.get("task_kind")
        or contract.get("task_goal_type")
        or contract.get("process_kind")
        or ""
    ).strip()
    return explicit


def _source_kind_from_contract(task_frame: Any, *, kinds: set[str]) -> str:
    resource = _resource_contract(task_frame)
    contract = _contract(task_frame)
    source_kind = str(
        resource.get("source_kind")
        or contract.get("source_kind")
        or contract.get("task_domain")
        or contract.get("domain")
        or ""
    ).strip()
    if source_kind:
        return source_kind
    if "pdf" in kinds:
        return "pdf"
    if "dataset" in kinds:
        return "dataset"
    if "code" in kinds or "workspace" in kinds:
        return "workspace"
    return ""


def _modality_from_source_kind(source_kind: str) -> str:
    return {
        "external_web": "web",
        "pdf": "pdf",
        "dataset": "table",
        "workspace": "workspace",
    }.get(str(source_kind or "").strip(), "general")


