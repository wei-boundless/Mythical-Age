from __future__ import annotations

from typing import Any

from .models import compact_text, dict_tuple, drop_empty
from .replacement_store import ReplacementStore
from .tool_result_projector import ToolResultProjector


PROJECTOR_VERSION = "observation_projector.v1"


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
        return (
            drop_empty(
                {
                    "latest_observations": latest,
                    "active_failures": active_failures[-8:],
                    "historical_failures": historical_failures[-8:],
                    "artifact_evidence": _dedupe_artifacts(artifact_evidence),
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
            _dedupe_artifacts(artifact_evidence),
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
            projection_policy=projection_policy,
        )
        structured_error = _structured_error_projection(source.get("structured_error") or observation.get("structured_error") or tool_projection.get("structured_error"))
        error = str(source.get("error") or observation.get("error") or tool_projection.get("error") or "")
        status = str(source.get("status") or source.get("result_status") or tool_projection.get("status") or ("error" if error or structured_error else "ok"))
        artifact_refs = [
            *dict_tuple(source.get("artifact_refs")),
            *dict_tuple(tool_projection.get("artifact_refs")),
        ]
        summary_source = (
            source.get("summary")
            or source.get("content")
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
                "structured_error": structured_error,
                "tool_result": _compact_tool_result(tool_projection),
                "artifact_refs": _dedupe_artifacts(artifact_refs),
                "authority": "harness.runtime.dynamic_context.observation_item_projection",
            }
        )
        projection, replacement = self.replacement_store.get_or_put(
            source_kind="observation",
            source_id=observation_id or "observation:" + str(len(str(projection))),
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


def _structured_error_projection(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return drop_empty(
        {
            "code": compact_text(value.get("code") or value.get("error_code") or "", limit=120),
            "message": compact_text(value.get("message") or value.get("detail") or "", limit=500),
            "retryable": value.get("retryable") if isinstance(value.get("retryable"), bool) else None,
            "origin": compact_text(value.get("origin") or "", limit=120),
        }
    )


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
        }
    )


def _dedupe_artifacts(refs: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ref in refs:
        item = dict(ref or {})
        key = str(item.get("path") or item.get("src") or item.get("artifact_ref") or sorted(item.items()))
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result
