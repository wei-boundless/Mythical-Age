from __future__ import annotations

import hashlib
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .projection_templates import ProjectionTemplateRegistry


@dataclass(frozen=True, slots=True)
class ProjectionInstance:
    projection_id: str
    template_id: str
    task_id: str
    task_run_id: str
    agent_id: str
    agent_profile_id: str
    runtime_lane: str
    prompt_manifest_id: str
    resource_policy_ref: str
    context_snapshot_ref: str = ""
    created_at: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ProjectionInstanceRegistry:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)
        self.templates = ProjectionTemplateRegistry(base_dir)

    def preview_instance(
        self,
        *,
        template_id: str,
        task_id: str,
        agent_id: str,
        runtime_lane: str,
        task_run_id: str = "",
        resource_policy_ref: str = "",
        context_snapshot_ref: str = "",
    ) -> ProjectionInstance:
        return self.build_instance(
            template_id=template_id,
            task_id=task_id,
            agent_id=agent_id,
            runtime_lane=runtime_lane,
            task_run_id=task_run_id,
            resource_policy_ref=resource_policy_ref,
            context_snapshot_ref=context_snapshot_ref,
            preview_only=True,
        )

    def build_instance(
        self,
        *,
        template_id: str,
        task_id: str,
        agent_id: str,
        runtime_lane: str,
        task_run_id: str = "",
        resource_policy_ref: str = "",
        context_snapshot_ref: str = "",
        preview_only: bool = False,
    ) -> ProjectionInstance:
        template = self.templates.get_template(template_id)
        if template is None:
            raise KeyError(template_id)
        raw = f"{template_id}:{task_id}:{agent_id}:{runtime_lane}:{task_run_id}:{resource_policy_ref}"
        digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
        projection_id = f"projection:{template_id}:{digest}"
        return ProjectionInstance(
            projection_id=projection_id,
            template_id=template_id,
            task_id=task_id,
            task_run_id=task_run_id,
            agent_id=agent_id,
            agent_profile_id=template.agent_profile_id,
            runtime_lane=runtime_lane,
            prompt_manifest_id=f"prompt-manifest:{projection_id}",
            resource_policy_ref=resource_policy_ref,
            context_snapshot_ref=context_snapshot_ref,
            created_at=time.time(),
            metadata={"preview_only": preview_only, "soul_id": template.soul_id, "role_type": template.role_type},
        )
