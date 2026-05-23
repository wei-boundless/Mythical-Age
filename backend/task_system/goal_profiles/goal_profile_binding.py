from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .task_goal_profiles import TaskGoalProfile, get_task_goal_profile


@dataclass(frozen=True, slots=True)
class TaskGoalProfileBinding:
    binding_id: str
    task_goal_type: str
    task_domain: str
    profile_id: str
    matched_by: str
    confidence: float
    inherited_capabilities: tuple[str, ...] = ()
    inherited_success_criteria: tuple[dict[str, Any], ...] = ()
    inherited_verifications: tuple[dict[str, Any], ...] = ()
    domain_plan_template_id: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_system.task_goal_profile_binding"

    def __post_init__(self) -> None:
        if self.authority != "task_system.task_goal_profile_binding":
            raise ValueError("TaskGoalProfileBinding authority must be task_system.task_goal_profile_binding")
        if not self.binding_id:
            raise ValueError("TaskGoalProfileBinding requires binding_id")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["inherited_capabilities"] = list(self.inherited_capabilities)
        payload["inherited_success_criteria"] = [dict(item) for item in self.inherited_success_criteria]
        payload["inherited_verifications"] = [dict(item) for item in self.inherited_verifications]
        return payload


def bind_task_goal_profile(
    *,
    session_id: str,
    task_id: str,
    task_goal_type: str,
    task_goal_frame: dict[str, Any] | None = None,
) -> TaskGoalProfileBinding:
    goal_frame = dict(task_goal_frame or {})
    profile = get_task_goal_profile(task_goal_type)
    if profile is None:
        return _fallback_binding(
            session_id=session_id,
            task_id=task_id,
            task_goal_type=task_goal_type,
            task_goal_frame=goal_frame,
        )
    conflicts = _explicit_constraint_conflicts(goal_frame=goal_frame, profile=profile)
    return TaskGoalProfileBinding(
        binding_id=f"task-goal-profile-binding:{session_id}:{task_id}",
        task_goal_type=profile.task_goal_type,
        task_domain=profile.task_domain,
        profile_id=profile.task_goal_type,
        matched_by="task_goal_type",
        confidence=_confidence(goal_frame, default=0.86),
        inherited_capabilities=tuple(profile.required_capabilities),
        inherited_success_criteria=_criteria(goal_frame, "success_criteria", profile.default_success_criteria),
        inherited_verifications=_criteria(goal_frame, "required_verifications", profile.default_verifications),
        domain_plan_template_id=profile.strategy_prototype_id or profile.task_goal_type,
        diagnostics={
            "profile": profile.to_dict(),
            "explicit_constraint_conflicts": conflicts,
            "authority": "task_system.goal_profile_binding",
        },
    )


def _fallback_binding(
    *,
    session_id: str,
    task_id: str,
    task_goal_type: str,
    task_goal_frame: dict[str, Any],
) -> TaskGoalProfileBinding:
    return TaskGoalProfileBinding(
        binding_id=f"task-goal-profile-binding:{session_id}:{task_id}",
        task_goal_type=str(task_goal_type or "light_qa"),
        task_domain=str(task_goal_frame.get("task_domain") or "general"),
        profile_id="fallback",
        matched_by="fallback",
        confidence=_confidence(task_goal_frame, default=0.32),
        inherited_capabilities=tuple(
            str(item).strip()
            for item in list(task_goal_frame.get("required_capabilities") or [])
            if str(item).strip()
        ),
        inherited_success_criteria=_criteria(task_goal_frame, "success_criteria", ()),
        inherited_verifications=_criteria(task_goal_frame, "required_verifications", ()),
        domain_plan_template_id="generic_professional_task",
        diagnostics={
            "fallback_reason": "unregistered_task_goal_type",
            "authority": "task_system.goal_profile_binding",
        },
    )


def _criteria(goal_frame: dict[str, Any], key: str, defaults: tuple[str, ...]) -> tuple[dict[str, Any], ...]:
    explicit = [dict(item) for item in list(goal_frame.get(key) or []) if isinstance(item, dict)]
    if explicit:
        return tuple(explicit)
    return tuple(
        {
            "criterion_id": _slug(item),
            "title": item,
            "verification_kind": "evidence",
            "required": True,
        }
        for item in defaults
        if str(item).strip()
    )


def _explicit_constraint_conflicts(*, goal_frame: dict[str, Any], profile: TaskGoalProfile) -> list[str]:
    forbidden = {
        str(item).strip()
        for item in list(goal_frame.get("forbidden_actions") or [])
        if str(item).strip()
    }
    capabilities = set(profile.required_capabilities)
    conflicts: list[str] = []
    if forbidden.intersection({"modify_code", "write_file", "edit_file"}) and "workspace_write" in capabilities:
        conflicts.append("profile_requires_workspace_write_but_user_forbids_write")
    return conflicts


def _confidence(goal_frame: dict[str, Any], *, default: float) -> float:
    try:
        value = float(goal_frame.get("confidence"))
    except (TypeError, ValueError):
        value = default
    if value <= 0:
        return default
    return max(0.0, min(value, 0.98))


def _slug(value: str) -> str:
    slug = "".join(ch if ch.isalnum() else "_" for ch in str(value or "").lower()).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug or "criterion"
