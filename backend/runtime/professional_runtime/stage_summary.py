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
        latest_observations=tuple(
            _compact_stage_observation(item)
            for item in list(structured_observations or [])[-5:]
            if isinstance(item, dict)
        ),
        pending_deliverables=tuple(dict.fromkeys(pending)),
        verification_passed=tool_observation_ledger.verification_passed(),
        environment=dict(environment_snapshot or {}),
    )


def _compact_stage_observation(observation: dict[str, Any]) -> dict[str, Any]:
    item = dict(observation or {})
    envelope = dict(item.get("result_envelope") or {})
    structured = dict(item.get("structured_payload") or envelope.get("structured_payload") or {})
    command_receipt = dict(item.get("command_receipt") or envelope.get("command_receipt") or structured.get("command_receipt") or {})
    result_text = str(item.get("result") or envelope.get("text") or "")
    tool_name = str(item.get("tool_name") or envelope.get("tool_name") or "")
    observed_paths = _dedupe_strings(
        [
            *[str(path).strip() for path in list(item.get("observed_paths") or []) if str(path).strip()],
            *[str(path).strip() for path in list(envelope.get("observed_paths") or []) if str(path).strip()],
            *[str(path).strip() for path in list(structured.get("observed_paths") or []) if str(path).strip()],
        ]
    )
    matched_paths = _dedupe_strings(
        [
            *[str(path).strip() for path in list(item.get("matched_paths") or []) if str(path).strip()],
            *[str(path).strip() for path in list(envelope.get("matched_paths") or []) if str(path).strip()],
            *[str(path).strip() for path in list(structured.get("matched_paths") or []) if str(path).strip()],
        ]
    )
    artifact_refs = [
        dict(ref)
        for ref in [
            *list(item.get("artifact_refs") or []),
            *list(envelope.get("artifact_refs") or []),
            *list(structured.get("artifact_refs") or []),
        ]
        if isinstance(ref, dict)
    ][:8]
    return {
        "observation_ref": str(item.get("observation_ref") or ""),
        "tool_name": tool_name,
        "tool_args": _compact_tool_args(dict(item.get("tool_args") or envelope.get("tool_args") or {})),
        "status": str(envelope.get("status") or structured.get("status") or ""),
        "observed_paths": observed_paths,
        "matched_paths": matched_paths,
        "artifact_refs": artifact_refs,
        "command_receipt": {
            key: value
            for key, value in command_receipt.items()
            if key in {"command", "exit_code", "passed", "duration_ms", "output_preview"}
        },
        "result_preview": _safe_result_preview(
            tool_name=tool_name,
            result_text=result_text,
            structured_payload=structured,
            observed_paths=observed_paths,
            artifact_refs=artifact_refs,
            command_receipt=command_receipt,
        ),
        "result_chars": len(result_text),
    }


def _safe_result_preview(
    *,
    tool_name: str,
    result_text: str,
    structured_payload: dict[str, Any],
    observed_paths: list[str],
    artifact_refs: list[dict[str, Any]],
    command_receipt: dict[str, Any],
) -> str:
    if tool_name in {"read_file", "read_structured_file"}:
        file_meta = dict(structured_payload.get("tool_result") or {})
        size = str(file_meta.get("size_chars") or file_meta.get("size_bytes") or "").strip()
        path_text = ", ".join(observed_paths[:4])
        return f"{tool_name} observed {path_text}" + (f" ({size} chars)" if size else "")
    if tool_name in {"write_file", "edit_file"}:
        paths = [
            str(ref.get("path") or "").strip()
            for ref in artifact_refs
            if isinstance(ref, dict) and str(ref.get("path") or "").strip()
        ]
        return f"{tool_name} wrote {', '.join(paths[:4])}" if paths else f"{tool_name} completed"
    if tool_name == "terminal":
        return str(command_receipt.get("output_preview") or result_text)[:240]
    return str(result_text or "")[:240]


def _compact_tool_args(args: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key, value in dict(args or {}).items():
        if key == "content":
            text = str(value or "")
            compact[key] = f"<content_chars:{len(text)}>"
            continue
        compact[key] = value
    return compact


def _dedupe_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result
