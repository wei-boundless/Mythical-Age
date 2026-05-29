from __future__ import annotations

from typing import Any


_INTERNAL_LEAK_MARKERS = (
    "workflow_id",
    "operation_id",
    "manifest_id",
    "resource_id",
)


def build_prompt_manifest_validation(
    *,
    interaction_mode: str,
    sections: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    normalized_mode = _normalize_interaction_mode(interaction_mode)
    visible_sections = [dict(item) for item in list(sections or []) if isinstance(item, dict)]
    section_ids = [str(item.get("section_id") or "").strip() for item in visible_sections if str(item.get("section_id") or "").strip()]
    issues: list[str] = []

    if normalized_mode != "role_mode":
        forbidden = {"role_prompt_section"}
        leaked = [section_id for section_id in section_ids if section_id in forbidden]
        if leaked:
            issues.append("forbidden_role_prompt_sections_outside_role_mode:" + ",".join(leaked))

    if normalized_mode == "professional_mode":
        required = {"semantic_task_section", "output_section"}
        missing = [section_id for section_id in sorted(required) if section_id not in section_ids]
        if missing:
            issues.append("missing_required_professional_sections:" + ",".join(missing))

    leaked_markers = _detect_internal_marker_leaks(visible_sections)
    if leaked_markers:
        issues.append("internal_marker_leak:" + ",".join(leaked_markers))

    return {
        "authority": "prompt_library.manifest_validation",
        "interaction_mode": normalized_mode,
        "passed": not issues,
        "issues": issues,
        "section_ids": section_ids,
        "visible_section_count": len(section_ids),
    }


def _normalize_interaction_mode(value: str) -> str:
    normalized = str(value or "").strip() or "standard_mode"
    return normalized


def _detect_internal_marker_leaks(sections: list[dict[str, Any]]) -> list[str]:
    leaked: list[str] = []
    for marker in _INTERNAL_LEAK_MARKERS:
        if any(marker in str(item.get("content") or "") for item in sections):
            leaked.append(marker)
    return leaked


