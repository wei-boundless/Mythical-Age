from __future__ import annotations

from typing import Any

from artifact_system.artifact_authority import dedupe_artifact_refs, model_visible_artifact_refs

from .models import compact_text, dict_tuple, drop_empty
from .replacement_store import ReplacementStore
from .structured_error_projection import structured_error_projection
from .tool_result_projector import ToolResultProjector


PROJECTOR_VERSION = "observation_projector.v3"


class ObservationProjector:
    def __init__(self, *, replacement_store: ReplacementStore, tool_result_projector: ToolResultProjector) -> None:
        self.replacement_store = replacement_store
        self.tool_result_projector = tool_result_projector

    def project(
        self,
        observations: list[dict[str, Any]] | tuple[dict[str, Any], ...],
        *,
        task_run_id: str = "",
        projection_policy: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], list[str], list[dict[str, Any]], list[dict[str, Any]]]:
        policy = dict(projection_policy or {})
        latest: list[dict[str, Any]] = []
        active_failures: list[dict[str, Any]] = []
        historical_failures: list[dict[str, Any]] = []
        artifact_evidence: list[dict[str, Any]] = []
        refs: list[str] = []
        replacement_records: list[dict[str, Any]] = []
        for item in list(observations or []):
            if not isinstance(item, dict):
                continue
            projection, record = self._project_one(item, task_run_id=task_run_id, projection_policy=policy)
            if not projection:
                continue
            latest.append(projection)
            refs.append(str(projection.get("observation_id") or projection.get("observation_ref") or ""))
            replacement_records.append(record)
            if projection.get("artifact_refs"):
                artifact_evidence.extend(dict_tuple(projection.get("artifact_refs")))
            if str(projection.get("status") or "") in {"error", "blocked", "timeout"} or projection.get("structured_error"):
                if str(projection.get("visibility") or "active") == "historical":
                    historical_failures.append(projection)
                else:
                    active_failures.append(projection)
        latest = latest[-int(policy.get("latest_observation_limit") or 12):]
        failure_limit = int(policy.get("active_failure_limit") or 8)
        return (
            drop_empty(
                {
                    "latest_observations": latest,
                    "active_failures": active_failures[-failure_limit:],
                    "historical_failures": historical_failures[-failure_limit:],
                    "artifact_evidence": dedupe_artifact_refs(artifact_evidence),
                    "omitted_observations": {
                        "count": max(0, len(list(observations or [])) - len(latest)),
                        "reason": "latest_observation_limit",
                    }
                    if len(list(observations or [])) > len(latest)
                    else {},
                    "authority": "harness.runtime.dynamic_context.observation_projection",
                }
            ),
            [ref for ref in refs if ref],
            dedupe_artifact_refs(artifact_evidence),
            replacement_records,
        )

    def _project_one(
        self,
        observation: dict[str, Any],
        *,
        task_run_id: str,
        projection_policy: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        source = _source_observation_payload(observation)
        observation_id = str(observation.get("observation_id") or source.get("observation_id") or source.get("observation_ref") or "")
        tool_projection, tool_record = self.tool_result_projector.project_from_observation(
            source,
            task_run_id=task_run_id,
            projection_policy=_tool_projection_policy_for_observation(projection_policy, source=source),
        )
        structured_error = structured_error_projection(source.get("structured_error") or observation.get("structured_error") or tool_projection.get("structured_error"))
        error = str(source.get("error") or observation.get("error") or tool_projection.get("error") or "")
        status = str(source.get("status") or source.get("result_status") or tool_projection.get("status") or ("error" if error or structured_error else "ok"))
        artifact_refs = model_visible_artifact_refs(
            [
                *dict_tuple(source.get("artifact_refs")),
                *dict_tuple(tool_projection.get("artifact_refs")),
            ]
        )
        summary_source = (
            source.get("summary")
            or source.get("content")
            or source.get("runtime_result")
            or source.get("text")
            or observation.get("summary")
            or observation.get("content")
            or tool_projection.get("preview")
            or error
            or ""
        )
        projection = drop_empty(
            {
                "observation_id": observation_id,
                "source": str(source.get("source") or source.get("tool_name") or tool_projection.get("tool_name") or ""),
                "status": status,
                "visibility": _visibility(source),
                "summary": compact_text(summary_source, limit=int(projection_policy.get("observation_summary_chars") or 600)),
                "error": compact_text(error, limit=500),
                "event_offset": source.get("event_offset") or observation.get("event_offset"),
                "created_at": source.get("created_at") or observation.get("created_at"),
                **_active_work_control_projection(source),
                "structured_error": structured_error,
                "tool_result": _compact_tool_result(tool_projection),
                "artifact_refs": dedupe_artifact_refs(artifact_refs),
                "authority": "harness.runtime.dynamic_context.observation_item_projection",
            }
        )
        projection, replacement = self.replacement_store.get_or_put(
            source_kind="observation",
            source_id=observation_id or "observation:" + str(len(str(projection))),
            task_run_id=task_run_id,
            content=source,
            projection_policy=projection_policy,
            projector_version=PROJECTOR_VERSION,
            projection=projection,
        )
        if tool_record:
            projection = {**projection, "tool_result": _compact_tool_result(tool_projection)}
        return projection, replacement.to_dict()


def _source_observation_payload(observation: dict[str, Any]) -> dict[str, Any]:
    item = dict(observation or {})
    wrapped = dict(item.get("observation") or {})
    return wrapped if wrapped else item


def _visibility(source: dict[str, Any]) -> str:
    freshness = dict(source.get("runtime_freshness") or {})
    value = str(source.get("visibility") or freshness.get("visibility") or "")
    return value if value in {"active", "historical"} else "active"


def _active_work_control_projection(source: dict[str, Any]) -> dict[str, Any]:
    if str(source.get("observation_kind") or "") != "active_work_control":
        return {}
    control = dict(source.get("active_work_control") or {})
    return drop_empty(
        {
            "observation_kind": "active_work_control",
            "control_action": str(control.get("resolved_action") or control.get("action") or ""),
            "applied": source.get("applied") if isinstance(source.get("applied"), bool) else None,
            "terminal_reason": compact_text(source.get("terminal_reason") or "", limit=160),
            "runtime_result": compact_text(source.get("runtime_result") or "", limit=800),
            "followup_instruction": compact_text(source.get("followup_instruction") or "", limit=300),
        }
    )


def _tool_projection_policy_for_observation(projection_policy: dict[str, Any], *, source: dict[str, Any]) -> dict[str, Any]:
    policy = dict(projection_policy or {})
    summary_chars = _positive_int(policy.get("observation_summary_chars"))
    if summary_chars <= 0:
        return policy
    tool_preview_chars = _positive_int(policy.get("tool_result_preview_chars"))
    observation_limit = max(4000, summary_chars) if _is_code_observation(source) else max(1000, summary_chars)
    policy["tool_result_preview_chars"] = min(
        tool_preview_chars or observation_limit,
        observation_limit,
    )
    return policy


def _compact_tool_result(tool_projection: dict[str, Any]) -> dict[str, Any]:
    if not tool_projection:
        return {}
    return drop_empty(
        {
            "tool_result_ref": str(tool_projection.get("tool_result_ref") or ""),
            "tool_name": str(tool_projection.get("tool_name") or ""),
            "status": str(tool_projection.get("status") or ""),
            "preview": str(tool_projection.get("preview") or ""),
            "result_ref": str(tool_projection.get("result_ref") or ""),
            "structured_error": dict(tool_projection.get("structured_error") or {}),
            "artifact_refs": list(dict_tuple(tool_projection.get("artifact_refs"))),
            "replacement_ref": str(tool_projection.get("replacement_ref") or ""),
            "code_structure": dict(tool_projection.get("code_structure") or {}),
            "content_range": dict(tool_projection.get("content_range") or {}),
            "evidence_policy": dict(tool_projection.get("evidence_policy") or {}),
            "evidence_confidence": dict(tool_projection.get("evidence_confidence") or {}),
            "rehydration_plan": dict(tool_projection.get("rehydration_plan") or {}),
        }
    )


def _is_code_observation(source: dict[str, Any]) -> bool:
    payload = dict(source.get("payload") or {})
    envelope = dict(payload.get("result_envelope") or source.get("result_envelope") or {})
    tool_name = _normalized_tool_name(
        payload.get("tool_name")
        or source.get("tool_name")
        or envelope.get("tool_name")
        or source.get("source")
        or ""
    )
    if tool_name in {"read_file", "codebase_search", "search_text"}:
        return True
    structured = dict(
        payload.get("structured_payload")
        or source.get("structured_payload")
        or envelope.get("structured_payload")
        or {}
    )
    return bool(structured.get("code_structure") or dict(structured.get("tool_result") or {}).get("kind") == "text_file")


def _normalized_tool_name(value: Any) -> str:
    text = str(value or "").strip()
    return text.removeprefix("tool:").strip()


def _positive_int(value: Any) -> int:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return parsed if parsed > 0 else 0
