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
    """Adapts current SoulSystem preview projection into the runtime loop."""

    def build_from_task_operation_preview(
        self,
        task_operation_preview: dict[str, Any],
        *,
        context_snapshot_ref: str = "",
    ) -> StageProjectionSnapshot:
        task_contract = dict(task_operation_preview.get("task_contract") or {})
        task_id = str(task_contract.get("task_id") or "task-runtime")
        soul_runtime_view = dict(task_operation_preview.get("soul_runtime_view") or {})
        prompt_manifest = dict(task_operation_preview.get("prompt_manifest_preview") or {})
        projection_requirement = dict(task_operation_preview.get("projection_requirement") or {})
        projection_ref = str(prompt_manifest.get("projection_id") or task_operation_preview.get("projection_id") or "")
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
            },
        )


def _stable_ref(prefix: str, task_id: str, payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return f"{prefix}:{task_id}:{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:12]}"

