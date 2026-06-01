from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from artifact_system.artifact_repository_models import ArtifactRecord
from task_system.projects.project_library_manifest import ProjectLibraryManifest
from task_system.writing.artifact_projection_models import ArtifactProjectionRule
from task_system.writing.artifact_type_catalog import default_writing_projection_rules


@dataclass(frozen=True, slots=True)
class ArtifactProjectionDecision:
    artifact_id: str
    artifact_type: str
    projection_state: str
    rule_id: str = ""
    target_repository_id: str = ""
    target_section_id: str = ""
    reason: str = ""
    authority: str = "task_system.artifact_projection_decision"

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "artifact_type": self.artifact_type,
            "projection_state": self.projection_state,
            "rule_id": self.rule_id,
            "target_repository_id": self.target_repository_id,
            "target_section_id": self.target_section_id,
            "reason": self.reason,
            "authority": self.authority,
        }


class ArtifactProjectionService:
    """Maps recorded artifacts to project-library semantic targets.

    This service decides semantic projection only. It does not move files or
    commit candidates; lifecycle graphs perform adoption and writes.
    """

    def __init__(self, base_dir: Path, rules: tuple[ArtifactProjectionRule, ...] | None = None) -> None:
        self.base_dir = Path(base_dir)
        self.rules = tuple(rules) if rules is not None else default_writing_projection_rules()

    def decide(self, *, artifact: ArtifactRecord, manifest: ProjectLibraryManifest, project_kind: str = "") -> ArtifactProjectionDecision:
        artifact_type = str(artifact.metadata.get("artifact_type") or artifact.artifact_kind or "").strip()
        if not artifact_type:
            return ArtifactProjectionDecision(
                artifact_id=artifact.artifact_id,
                artifact_type="",
                projection_state="quarantined",
                reason="artifact_type is missing",
            )
        candidates = [
            rule
            for rule in self.rules
            if rule.enabled
            and rule.artifact_type == artifact_type
            and (not rule.source_contract_id or rule.source_contract_id == artifact.output_contract_id)
            and (not rule.environment_id or rule.environment_id == manifest.environment_id)
            and (not rule.project_kind or not project_kind or rule.project_kind == project_kind)
        ]
        if not candidates:
            return ArtifactProjectionDecision(
                artifact_id=artifact.artifact_id,
                artifact_type=artifact_type,
                projection_state="quarantined",
                reason="no projection rule matched",
            )
        rule = candidates[0]
        if manifest.repository(rule.target.repository_id) is None:
            return ArtifactProjectionDecision(
                artifact_id=artifact.artifact_id,
                artifact_type=artifact_type,
                projection_state="quarantined",
                rule_id=rule.rule_id,
                reason="projection target repository is not in project manifest",
            )
        return ArtifactProjectionDecision(
            artifact_id=artifact.artifact_id,
            artifact_type=artifact_type,
            projection_state=rule.target.state,
            rule_id=rule.rule_id,
            target_repository_id=rule.target.repository_id,
            target_section_id=rule.target.section_id,
        )
