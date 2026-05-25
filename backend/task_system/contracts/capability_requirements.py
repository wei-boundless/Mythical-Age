from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class OperationRequirement:
    requirement_id: str
    task_id: str
    source: str
    required_operations: tuple[str, ...] = ()
    optional_operations: tuple[str, ...] = ()
    denied_operations: tuple[str, ...] = ()
    reason: str = ""
    authority: str = "candidate_only"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_operation_requirement(
    *,
    task_id: str,
    source: str,
    required_task_operations: list[str] | tuple[str, ...] = (),
    denied_operations: list[str] | tuple[str, ...] = (),
    default_operation_requirements: list[str] | tuple[str, ...] = (),
    capability_operations: list[str] | tuple[str, ...] = (),
    approval_policy: str = "default",
    review_policy: str = "optional",
    safety_envelope: dict[str, Any] | None = None,
    extra_metadata: dict[str, Any] | None = None,
    reason: str = "",
) -> OperationRequirement:
    required = _dedupe([*default_operation_requirements, *required_task_operations])
    optional = _dedupe(capability_operations)
    denied = _dedupe(denied_operations)
    return OperationRequirement(
        requirement_id=f"opreq:{task_id}:{source}",
        task_id=task_id,
        source=source,
        required_operations=tuple(required),
        optional_operations=tuple(optional),
        denied_operations=tuple(denied),
        reason=reason,
        metadata={
            "approval_policy": approval_policy,
            "review_policy": review_policy,
            "safety_envelope": dict(safety_envelope or {}),
            **dict(extra_metadata or {}),
        },
    )


def _dedupe(values: list[str] | tuple[str, ...]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result
