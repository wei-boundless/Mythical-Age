from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from ..memory.tool_observation_ledger import ToolObservationLedger
from .deliverable_progress import DeliverableProgress


@dataclass(frozen=True, slots=True)
class ProfessionalStageSummary:
    task_run_id: str
    turn_count: int
    tool_call_count: int
    tool_observation_count: int
    written_paths: tuple[str, ...] = ()
    artifact_refs: tuple[dict[str, Any], ...] = ()
    latest_observations: tuple[dict[str, Any], ...] = ()
    pending_deliverables: tuple[str, ...] = ()
    verification_passed: bool = False
    environment: dict[str, Any] = field(default_factory=dict)
    authority: str = "professional_runtime.stage_summary"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["written_paths"] = list(self.written_paths)
        payload["artifact_refs"] = [dict(item) for item in self.artifact_refs]
        payload["latest_observations"] = [dict(item) for item in self.latest_observations]
        payload["pending_deliverables"] = list(self.pending_deliverables)
        payload["environment"] = dict(self.environment)
        payload["summary"] = self.summary_text()
        return payload

    def summary_text(self) -> str:
        lines = ["阶段总结："]
        lines.append("已写入：" + ("、".join(self.written_paths[-8:]) if self.written_paths else "暂无真实写入产物"))
        lines.append("待完成：" + ("、".join(self.pending_deliverables[:8]) if self.pending_deliverables else "无明确缺失交付物"))
        lines.append("验证：" + ("已通过" if self.verification_passed else "尚未通过或尚未运行"))
        if self.latest_observations:
            latest = self.latest_observations[-1]
            lines.append(
                "最新观察："
                + str(latest.get("tool_name") or "tool")
                + " "
                + str(latest.get("result") or latest.get("text") or "")[:180]
            )
        return "\n".join(lines)


def build_stage_summary(
    *,
    task_run_id: str,
    turn_count: int,
    tool_call_count: int,
    tool_observation_count: int,
    tool_observation_ledger: ToolObservationLedger,
    deliverable_progress: DeliverableProgress,
    structured_observations: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    environment_snapshot: dict[str, Any] | None = None,
) -> ProfessionalStageSummary:
    written_paths: list[str] = []
    artifact_refs: list[dict[str, Any]] = []
    for record in tool_observation_ledger.records:
        if "write_output" not in record.satisfies:
            continue
        written_paths.extend(str(path).strip() for path in list(record.observed_paths or ()) if str(path).strip())
        artifact_refs.extend(dict(item) for item in list(record.artifact_refs or ()) if isinstance(item, dict))
    pending = [
        str(item).strip()
        for item in deliverable_progress.missing_obligations()
        if str(item).strip()
    ]
    return ProfessionalStageSummary(
        task_run_id=task_run_id,
        turn_count=int(turn_count or 0),
        tool_call_count=int(tool_call_count or 0),
        tool_observation_count=int(tool_observation_count or 0),
        written_paths=tuple(dict.fromkeys(written_paths)),
        artifact_refs=tuple(artifact_refs),
        latest_observations=tuple(dict(item) for item in list(structured_observations or [])[-5:] if isinstance(item, dict)),
        pending_deliverables=tuple(dict.fromkeys(pending)),
        verification_passed=tool_observation_ledger.verification_passed(),
        environment=dict(environment_snapshot or {}),
    )
