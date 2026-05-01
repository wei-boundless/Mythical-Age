from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class StageProjectionSnapshot:
    snapshot_id: str
    task_id: str
    projection_ref: str
    prompt_manifest_ref: str
    soul_runtime_view: dict[str, Any] = field(default_factory=dict)
    prompt_manifest: dict[str, Any] = field(default_factory=dict)
    projection_requirement: dict[str, Any] = field(default_factory=dict)
    visible_section_count: int = 0
    visible_tool_ids: tuple[str, ...] = ()
    visible_skill_ids: tuple[str, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "orchestration.stage_projection_snapshot"

    def __post_init__(self) -> None:
        if self.authority != "orchestration.stage_projection_snapshot":
            raise ValueError("StageProjectionSnapshot authority must be orchestration.stage_projection_snapshot")
        if not self.snapshot_id:
            raise ValueError("StageProjectionSnapshot requires snapshot_id")
        if not self.task_id:
            raise ValueError("StageProjectionSnapshot requires task_id")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["visible_tool_ids"] = list(self.visible_tool_ids)
        payload["visible_skill_ids"] = list(self.visible_skill_ids)
        return payload


class StageProjectionCycle:
    """Adapts the current SoulSystem projection into the runtime loop."""

    def build_from_task_operation(
        self,
        task_operation: dict[str, Any],
        *,
        context_snapshot_ref: str = "",
    ) -> StageProjectionSnapshot:
        task_contract = dict(task_operation.get("task_contract") or {})
        task_id = str(task_contract.get("task_id") or "task-runtime")
        raw_soul_runtime_view = dict(task_operation.get("soul_runtime_view") or {})
        raw_prompt_manifest = dict(task_operation.get("prompt_manifest") or {})
        soul_runtime_view = _runtime_safe_soul_runtime_view(raw_soul_runtime_view)
        prompt_manifest = _runtime_safe_prompt_manifest(raw_prompt_manifest, soul_runtime_view)
        projection_requirement = dict(task_operation.get("projection_requirement") or {})
        projection_ref = str(prompt_manifest.get("projection_id") or task_operation.get("projection_id") or "")
        if not projection_ref:
            projection_ref = _stable_ref("projection", task_id, soul_runtime_view)
        prompt_manifest_ref = str(prompt_manifest.get("manifest_id") or "")
        if not prompt_manifest_ref:
            prompt_manifest_ref = _stable_ref("manifest", task_id, prompt_manifest)
        sections = list(soul_runtime_view.get("sections") or ())
        visible_sections = [section for section in sections if dict(section).get("visible_to_model") is not False]
        visible_tools = tuple(str(item) for item in list(soul_runtime_view.get("visible_tool_ids") or ()))
        visible_skills = tuple(str(item) for item in list(soul_runtime_view.get("visible_skill_ids") or ()))
        snapshot_id = _stable_ref(
            "stageproj",
            task_id,
            {
                "projection_ref": projection_ref,
                "prompt_manifest_ref": prompt_manifest_ref,
                "context_snapshot_ref": context_snapshot_ref,
            },
        )
        return StageProjectionSnapshot(
            snapshot_id=snapshot_id,
            task_id=task_id,
            projection_ref=projection_ref,
            prompt_manifest_ref=prompt_manifest_ref,
            soul_runtime_view=soul_runtime_view,
            prompt_manifest=prompt_manifest,
            projection_requirement=projection_requirement,
            visible_section_count=len(visible_sections),
            visible_tool_ids=visible_tools,
            visible_skill_ids=visible_skills,
            diagnostics={
                "projection_owner": "SoulSystem",
                "cycle_owner": "TaskRunLoop",
                "context_snapshot_ref": context_snapshot_ref,
                "permission_expansion_allowed": False,
                "control_plane_sections_filtered": True,
            },
        )


def _runtime_safe_soul_runtime_view(payload: dict[str, Any]) -> dict[str, Any]:
    view = dict(payload or {})
    sections = []
    for section in list(view.get("sections") or ()):
        item = dict(section or {})
        if _is_control_plane_section(item):
            continue
        if not str(item.get("content") or "").strip():
            continue
        item["visible_to_model"] = item.get("visible_to_model") is not False
        sections.append(item)
    view["sections"] = sections
    view["visible_tool_ids"] = [
        str(item)
        for item in list(view.get("visible_tool_ids") or ())
        if str(item or "").strip()
    ]
    return view


def _runtime_safe_prompt_manifest(payload: dict[str, Any], runtime_view: dict[str, Any]) -> dict[str, Any]:
    manifest = dict(payload or {})
    allowed_ids = {
        str(dict(section or {}).get("section_id") or "")
        for section in list(runtime_view.get("sections") or ())
    }
    manifest["sections"] = [
        dict(section or {})
        for section in list(manifest.get("sections") or ())
        if str(dict(section or {}).get("section_id") or "") in allowed_ids
    ]
    manifest["total_sections"] = len(manifest["sections"])
    manifest["total_chars"] = sum(int(dict(section).get("chars") or 0) for section in manifest["sections"])
    return manifest


def _is_control_plane_section(section: dict[str, Any]) -> bool:
    section_id = str(section.get("section_id") or "").strip()
    owner_layer = str(section.get("owner_layer") or "").strip()
    source_type = str(section.get("source_type") or "").strip()
    source_id = str(section.get("source_id") or "").strip()
    source_refs = [str(item or "").strip() for item in list(section.get("source_refs") or ())]
    content = str(section.get("content") or "")
    metadata = dict(section.get("metadata") or {}) if isinstance(section.get("metadata"), dict) else {}
    if section_id in {"resource_section", "guardrail_section"}:
        return True
    if owner_layer in {"resource_policy", "control_kernel", "operation_gate", "commit_gate"}:
        return True
    if source_type in {"resource_policy", "operation_gate", "control_kernel", "commit_gate"}:
        return True
    probe = "\n".join([source_id, *source_refs, content, repr(metadata)]).lower()
    return any(
        marker in probe
        for marker in (
            ":preview",
            "denied:",
            "do not execute tools",
            "runtime_executable=false",
            "runtime_executable: false",
        )
    )


def _stable_ref(prefix: str, task_id: str, payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return f"{prefix}:{task_id}:{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:12]}"
