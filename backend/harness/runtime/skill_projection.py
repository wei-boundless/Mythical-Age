from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from capability_system.skill_registry import SkillRegistry
from task_system.contracts.runtime_contracts import skill_runtime_view_from_skill_definition


@dataclass(frozen=True, slots=True)
class RuntimeSkillCandidate:
    skill_id: str
    title: str
    source: str
    availability: str
    required_operations: tuple[str, ...] = ()
    missing_operations: tuple[str, ...] = ()
    method_summary: str = ""
    input_boundary: str = ""
    output_boundary: str = ""
    forbidden_uses: tuple[str, ...] = ()
    canonical_path: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "harness.runtime.skill_candidate"

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "title": self.title,
            "source": self.source,
            "availability": self.availability,
            "required_operations": list(self.required_operations),
            "missing_operations": list(self.missing_operations),
            "method_summary": self.method_summary,
            "input_boundary": self.input_boundary,
            "output_boundary": self.output_boundary,
            "forbidden_uses": list(self.forbidden_uses),
            "canonical_path": self.canonical_path,
            "diagnostics": dict(self.diagnostics),
            "authority": self.authority,
        }


def project_runtime_skill_candidates(
    *,
    skill_registry: SkillRegistry,
    environment_payload: dict[str, Any],
    task_selection: dict[str, Any] | None = None,
    agent_runtime_profile: Any | None = None,
    authorized_operations: set[str] | frozenset[str] = frozenset(),
) -> tuple[tuple[RuntimeSkillCandidate, ...], tuple[dict[str, str], ...]]:
    selection = dict(task_selection or {})
    skill_space = dict(environment_payload.get("skill_space") or {})
    denied_refs = _skill_ref_set(skill_space.get("denied_skill_refs"))
    denied_refs |= _skill_ref_set(_skill_requirements(selection).get("denied_refs"))
    denied_refs |= _skill_ref_set(_skill_requirements(selection).get("denied_skill_refs"))
    denied_refs |= _skill_ref_set(dict(getattr(agent_runtime_profile, "metadata", {}) or {}).get("blocked_skill_refs"))

    refs: list[tuple[str, str]] = []
    refs.extend((ref, "environment_default") for ref in _skill_refs(skill_space.get("default_skill_refs")))
    refs.extend((ref, "environment_optional") for ref in _skill_refs(skill_space.get("optional_skill_refs")))
    requirements = _skill_requirements(selection)
    refs.extend((ref, "task_required") for ref in _skill_refs(requirements.get("required_refs") or requirements.get("required_skill_refs")))
    refs.extend((ref, "task_optional") for ref in _skill_refs(requirements.get("optional_refs") or requirements.get("optional_skill_refs")))
    refs.extend(
        (ref, "agent_preferred")
        for ref in _skill_refs(dict(getattr(agent_runtime_profile, "metadata", {}) or {}).get("preferred_skill_refs"))
    )

    candidates: list[RuntimeSkillCandidate] = []
    filtered: list[dict[str, str]] = []
    seen: set[str] = set()
    allowed = {str(item).strip() for item in set(authorized_operations or set()) if str(item).strip()}
    for raw_ref, source in refs:
        skill_ref = _normalize_skill_ref(raw_ref)
        if not skill_ref or skill_ref in seen:
            continue
        seen.add(skill_ref)
        if skill_ref in denied_refs:
            filtered.append({"skill_ref": skill_ref, "source": source, "reason": "skill_denied_by_policy"})
            continue
        skill_name = skill_ref.removeprefix("skill.")
        skill = skill_registry.get_by_name(skill_name)
        if skill is None:
            filtered.append({"skill_ref": skill_ref, "source": source, "reason": "missing_skill_definition"})
            continue
        view = skill_runtime_view_from_skill_definition(skill, task_reason=_task_reason(source))
        required_operations = tuple(str(item).strip() for item in tuple(view.required_operations or ()) if str(item).strip())
        missing = tuple(item for item in required_operations if item not in allowed)
        if not required_operations or not missing:
            availability = "available"
        elif len(missing) == len(required_operations):
            availability = "unavailable"
        else:
            availability = "partial"
        candidates.append(
            RuntimeSkillCandidate(
                skill_id=view.skill_id,
                title=view.title,
                source=source,
                availability=availability,
                required_operations=required_operations,
                missing_operations=missing,
                method_summary=view.method_summary,
                input_boundary=view.input_boundary,
                output_boundary=view.output_boundary,
                forbidden_uses=view.forbidden_uses,
                canonical_path=view.canonical_path,
                diagnostics={"required_operation_policy": str(skill_space.get("required_operation_policy") or "declare_only")},
            )
        )
    return tuple(candidates), tuple(filtered)


def _skill_requirements(selection: dict[str, Any]) -> dict[str, Any]:
    runtime_profile = dict(selection.get("runtime_profile") or {})
    values = [
        selection.get("skill_requirements"),
        selection.get("required_skills"),
        runtime_profile.get("skill_requirements"),
        selection.get("specific_task_skill_requirements"),
    ]
    merged: dict[str, Any] = {}
    for value in values:
        if isinstance(value, dict):
            merged.update(dict(value))
    return merged


def _skill_refs(value: Any) -> tuple[str, ...]:
    return tuple(_normalize_skill_ref(item) for item in list(value or []) if _normalize_skill_ref(item))


def _skill_ref_set(value: Any) -> set[str]:
    return set(_skill_refs(value))


def _normalize_skill_ref(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return text if text.startswith("skill.") else f"skill.{text}"


def _task_reason(source: str) -> str:
    if source == "environment_default":
        return "Static skill candidate from the selected task environment."
    if source == "environment_optional":
        return "Optional skill candidate from the selected task environment."
    if source == "task_required":
        return "Required skill declared by the current task contract or selection."
    if source == "task_optional":
        return "Optional skill declared by the current task contract or selection."
    return "Skill candidate preferred by the agent profile."
