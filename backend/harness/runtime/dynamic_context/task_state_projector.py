from __future__ import annotations

from typing import Any

from .models import compact_text, dict_tuple, drop_empty
from .tool_result_projector import model_visible_artifact_refs


class TaskStateProjector:
    def project(
        self,
        *,
        execution_projection: dict[str, Any],
        observation_projection: dict[str, Any],
        work_history_projection: dict[str, Any],
        task_run_state: dict[str, Any],
        envelope_projection: dict[str, Any],
        include_task_run_context: bool = True,
    ) -> dict[str, Any]:
        current_facts = _dedupe_by_semantic(dict_tuple(execution_projection.get("current_facts")))
        current_fact_keys = {_semantic_projection_key(item) for item in current_facts if _semantic_projection_key(item)}
        latest_results = _latest_results(
            execution_projection=execution_projection,
            observation_projection=observation_projection,
            current_fact_keys=current_fact_keys,
        )
        artifact_evidence = model_visible_artifact_refs(
            _dedupe_artifacts(
                [
                    *dict_tuple(execution_projection.get("artifact_evidence")),
                    *dict_tuple(observation_projection.get("artifact_evidence")),
                    *dict_tuple(work_history_projection.get("active_artifacts")),
                ]
            )
        )
        positive_paths = _positive_paths(current_facts, latest_results, artifact_evidence)
        current_facts = _drop_superseded_missing_path_probes(current_facts, positive_paths=positive_paths)
        latest_results = _drop_superseded_missing_path_probes(latest_results, positive_paths=positive_paths)
        payload = {
            "runtime_status": str(execution_projection.get("runtime_status") or task_run_state.get("status") or ""),
            "current_step": dict(execution_projection.get("current_step") or {}),
            "current_facts": current_facts,
            "file_state": _file_state_projection(execution_projection.get("file_state")),
            "latest_tool_results": latest_results[-8:],
            "active_failures": _dedupe_failures(
                [
                    *dict_tuple(execution_projection.get("active_failures")),
                    *dict_tuple(observation_projection.get("active_failures")),
                ]
            )[-8:],
            "historical_failures": _dedupe_failures(
                [
                    *dict_tuple(execution_projection.get("historical_failures")),
                    *dict_tuple(observation_projection.get("historical_failures")),
                ]
            )[-4:],
            "artifact_evidence": artifact_evidence,
            "pending_user_steers": _dedupe_by_ref(dict_tuple(execution_projection.get("pending_user_steers")), ref_keys=("steer_id",)),
            "active_contract_revisions": _dedupe_by_ref(
                dict_tuple(execution_projection.get("active_contract_revisions")),
                ref_keys=("revision_id", "contract_revision_id"),
            ),
            "work_progress": _work_progress_projection(work_history_projection),
            "authority": "harness.runtime.dynamic_context.task_execution_state_projection",
        }
        if include_task_run_context:
            payload["task_run_state"] = _task_run_state_projection(task_run_state)
            payload["runtime_boundary"] = _runtime_boundary_projection(envelope_projection)
        return drop_empty(payload)


def _latest_results(
    *,
    execution_projection: dict[str, Any],
    observation_projection: dict[str, Any],
    current_fact_keys: set[str],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for item in dict_tuple(execution_projection.get("last_action_receipts")):
        results.append(
            drop_empty(
                {
                    "observation_ref": str(item.get("observation_ref") or ""),
                    "tool_name": str(item.get("tool_name") or ""),
                    "status": str(item.get("status") or ""),
                    "path": _projection_path(item),
                    "visibility": str(item.get("visibility") or ""),
                    "summary": compact_text(item.get("summary") or "", limit=300),
                    "content_range": dict(item.get("content_range") or {}),
                    "tool_guidance": compact_text(item.get("tool_guidance") or "", limit=500),
                }
            )
        )
    for item in dict_tuple(observation_projection.get("latest_observations")):
        results.append(_observation_result_projection(item))
    deduped = _dedupe_by_semantic([item for item in results if item])
    return [
        item
        for item in deduped
        if _semantic_projection_key(item) not in current_fact_keys
    ]


def _observation_result_projection(item: dict[str, Any]) -> dict[str, Any]:
    tool_result = dict(item.get("tool_result") or {})
    structured_error = dict(item.get("structured_error") or tool_result.get("structured_error") or {})
    projected = drop_empty(
        {
            "observation_ref": str(item.get("observation_id") or item.get("observation_ref") or ""),
            "tool_name": _tool_name(str(item.get("source") or tool_result.get("tool_name") or "")),
            "status": str(item.get("status") or tool_result.get("status") or ""),
            "path": _projection_path(item) or _projection_path(tool_result),
            "visibility": str(item.get("visibility") or ""),
            "summary": compact_text(item.get("summary") or tool_result.get("preview") or "", limit=300),
            "structured_error": structured_error,
            "artifact_refs": list(dict_tuple(item.get("artifact_refs") or tool_result.get("artifact_refs"))),
            "replacement_ref": str(tool_result.get("replacement_ref") or ""),
            "content_range": dict(item.get("content_range") or tool_result.get("content_range") or {}),
            "tool_guidance": compact_text(item.get("tool_guidance") or tool_result.get("tool_guidance") or "", limit=500),
        }
    )
    if set(projected).issubset({"observation_ref", "replacement_ref"}):
        return {}
    return projected


def _dedupe_failures(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for item in items:
        status = str(item.get("status") or "")
        if status and status not in {"error", "failed", "blocked", "timeout", "denied", "canceled"}:
            continue
        projected = _failure_projection(item)
        if projected:
            failures.append(projected)
    return _dedupe_by_semantic(failures)


def _failure_projection(item: dict[str, Any]) -> dict[str, Any]:
    error = _dict_value(item.get("error")) or _dict_value(item.get("structured_error"))
    tool_result = dict(item.get("tool_result") or {})
    if not error:
        error = _dict_value(tool_result.get("structured_error"))
    error_text = item.get("error") if isinstance(item.get("error"), str) else ""
    return drop_empty(
        {
            "observation_ref": str(item.get("observation_ref") or item.get("observation_id") or ""),
            "tool_name": _tool_name(str(item.get("tool_name") or item.get("source") or tool_result.get("tool_name") or "")),
            "status": str(item.get("status") or tool_result.get("status") or "error"),
            "visibility": str(item.get("visibility") or ""),
            "reason": str(item.get("reason") or error.get("code") or ""),
            "summary": compact_text(item.get("summary") or error_text or error.get("message") or "", limit=300),
            "error": error,
            "current_runtime_fact": item.get("current_runtime_fact") if isinstance(item.get("current_runtime_fact"), bool) else None,
        }
    )


def _work_progress_projection(work_history_projection: dict[str, Any]) -> dict[str, Any]:
    return drop_empty(
        {
            "latest_progress": compact_text(work_history_projection.get("latest_progress") or "", limit=300),
            "latest_step_title": compact_text(work_history_projection.get("latest_step_title") or "", limit=120),
            "active_facts": [compact_text(item, limit=180) for item in list(work_history_projection.get("active_facts") or []) if str(item)],
            "historical_work_summary": dict(work_history_projection.get("historical_work_summary") or {}),
            "recent_steps": [
                drop_empty(
                    {
                        "type": str(item.get("type") or ""),
                        "title": compact_text(item.get("title") or "", limit=120),
                        "status": str(item.get("status") or ""),
                        "summary": compact_text(item.get("summary") or "", limit=240),
                    }
                )
                for item in dict_tuple(work_history_projection.get("recent_steps"))[-4:]
            ],
        }
    )


def _task_run_state_projection(task_run_state: dict[str, Any]) -> dict[str, Any]:
    return drop_empty(
        {
            "status": str(task_run_state.get("status") or ""),
            "terminal_reason": str(task_run_state.get("terminal_reason") or ""),
            "current_step_index": task_run_state.get("current_step_index"),
            "diagnostics": dict(task_run_state.get("diagnostics") or {}),
        }
    )


def _runtime_boundary_projection(envelope_projection: dict[str, Any]) -> dict[str, Any]:
    return drop_empty(
        {
            "artifact_root": str(envelope_projection.get("artifact_root") or ""),
            "permission_scope": str(envelope_projection.get("permission_scope") or ""),
            "output_format": str(envelope_projection.get("output_format") or ""),
        }
    )


def _dedupe_by_ref(items: list[dict[str, Any]] | tuple[dict[str, Any], ...], *, ref_keys: tuple[str, ...] = ("observation_ref", "observation_id")) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    index_by_key: dict[str, int] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        key = ""
        for ref_key in ref_keys:
            key = str(item.get(ref_key) or "").strip()
            if key:
                break
        if not key:
            key = repr(sorted((str(k), repr(v)) for k, v in item.items()))
        if key in index_by_key:
            index = index_by_key[key]
            result[index] = _merge_projection(result[index], dict(item))
            continue
        index_by_key[key] = len(result)
        result.append(dict(item))
    return result


def _dedupe_by_semantic(items: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    index_by_key: dict[str, int] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        projected = drop_empty(dict(item))
        if not projected:
            continue
        key = _semantic_projection_key(projected)
        if not key:
            key = _ref_projection_key(projected)
        if key in index_by_key:
            index = index_by_key[key]
            result[index] = _merge_projection(result[index], projected)
            continue
        index_by_key[key] = len(result)
        result.append(projected)
    return result


def _semantic_projection_key(item: dict[str, Any]) -> str:
    tool_name = _tool_name(str(item.get("tool_name") or item.get("source") or ""))
    status = str(item.get("status") or item.get("result") or "").strip().lower()
    path = _projection_path(item)
    range_key = _content_range_key(item)
    error = dict(item.get("structured_error") or item.get("error") or {})
    error_code = str(error.get("code") or item.get("reason") or "").strip()
    if tool_name and path and range_key:
        return f"tool-path-range:{tool_name}:{path}:{range_key}:{status or error_code}"
    if tool_name and path:
        return f"tool-path:{tool_name}:{path}:{status or error_code}"
    if tool_name and error_code:
        return f"tool-error:{tool_name}:{error_code}"
    summary = compact_text(item.get("summary") or "", limit=160)
    if tool_name and summary:
        return f"tool-summary:{tool_name}:{status}:{summary}"
    return ""


def _content_range_key(item: dict[str, Any]) -> str:
    content_range = dict(item.get("content_range") or {})
    if not content_range:
        return ""
    start_line = content_range.get("start_line")
    end_line = content_range.get("end_line")
    if start_line in (None, "") and end_line in (None, ""):
        return ""
    return f"{start_line}:{end_line}"


def _file_state_projection(value: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in dict_tuple(value):
        path = _projection_path(item) or str(item.get("path") or "").replace("\\", "/").strip().strip("/")
        if not path:
            continue
        ranges = [
            {
                "start_line": segment.get("start_line"),
                "end_line": segment.get("end_line"),
                "observation_ref": str(segment.get("observation_ref") or ""),
            }
            for segment in dict_tuple(item.get("read_ranges"))
            if segment.get("start_line") not in (None, "") and segment.get("end_line") not in (None, "")
        ]
        projected = drop_empty(
            {
                "path": path,
                "read_ranges": ranges[-12:],
                "coverage": dict(item.get("coverage") or {}),
                "total_lines": item.get("total_lines"),
                "content_sha256": str(item.get("content_sha256") or ""),
                "last_observation_ref": str(item.get("last_observation_ref") or ""),
                "has_more": item.get("has_more") if isinstance(item.get("has_more"), bool) else None,
                "status": str(item.get("status") or ""),
                "search_hit_count": len(dict_tuple(item.get("search_hits"))),
                "write_event_count": len(dict_tuple(item.get("write_events"))),
                "next_suggested_read": dict(item.get("next_suggested_read") or {}),
                "evidence_refs": [
                    ref
                    for ref in [
                        str(item.get("last_observation_ref") or ""),
                        *[
                            str(segment.get("observation_ref") or "")
                            for segment in dict_tuple(item.get("read_ranges"))
                            if str(segment.get("observation_ref") or "")
                        ][-4:],
                    ]
                    if ref
                ][-5:],
            }
        )
        if projected:
            result.append(projected)
    return result[-20:]


def _projection_path(item: dict[str, Any]) -> str:
    for key in ("path", "target_path", "artifact_path", "output_path"):
        value = str(item.get(key) or "").replace("\\", "/").strip().strip("/")
        if value:
            return value
    args = dict(item.get("args") or item.get("tool_args") or {})
    for key in ("path", "target_path", "artifact_path", "output_path"):
        value = str(args.get(key) or "").replace("\\", "/").strip().strip("/")
        if value:
            return value
    artifact_refs = [dict(ref) for ref in list(item.get("artifact_refs") or []) if isinstance(ref, dict)]
    for ref in artifact_refs:
        value = str(ref.get("path") or ref.get("src") or ref.get("artifact_ref") or "").replace("\\", "/").strip().strip("/")
        if value:
            return value
    return ""


def _ref_projection_key(item: dict[str, Any]) -> str:
    for key in ("observation_ref", "observation_id"):
        value = str(item.get(key) or "").strip()
        if value:
            return f"ref:{value}"
    return repr(sorted((str(k), repr(v)) for k, v in item.items()))


def _merge_projection(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    merged = dict(first)
    for key, value in second.items():
        if value in ("", None, [], {}):
            continue
        if key == "error" and isinstance(value, dict):
            merged[key] = {**dict(merged.get(key) or {}), **value}
        elif key == "structured_error" and isinstance(value, dict):
            merged[key] = {**dict(merged.get(key) or {}), **value}
        elif not merged.get(key):
            merged[key] = value
    return drop_empty(merged)


def _dedupe_artifacts(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        path = str(item.get("path") or item.get("artifact_ref") or item.get("src") or "").strip()
        if not path or path in seen:
            continue
        seen.add(path)
        result.append(dict(item))
    return result[-20:]


def _positive_paths(*groups: Any) -> set[str]:
    paths: set[str] = set()
    for group in groups:
        for item in dict_tuple(group):
            path = _projection_path(item)
            if not path:
                continue
            if _is_missing_path_probe(item):
                continue
            status = str(item.get("status") or "").strip().lower()
            tool_name = _tool_name(str(item.get("tool_name") or item.get("source") or ""))
            if (
                status == "ok"
                or tool_name in {"write_file", "edit_file", "read_file", "search_text", "stat_path"}
                or item.get("kind")
                or item.get("artifact_ref")
            ):
                paths.add(path)
    return paths


def _drop_superseded_missing_path_probes(items: list[dict[str, Any]], *, positive_paths: set[str]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in items:
        if _is_missing_path_probe(item) and _projection_path(item) in positive_paths:
            continue
        result.append(item)
    return result


def _is_missing_path_probe(item: dict[str, Any]) -> bool:
    if _tool_name(str(item.get("tool_name") or item.get("source") or "")) != "path_exists":
        return False
    summary = str(item.get("summary") or "").strip().lower()
    if summary in {"false", "0", "no", "not found", "missing"}:
        return True
    return any(marker in summary for marker in ("不存在", "not exist", "does not exist", "not_found", "not found"))


def _dict_value(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _tool_name(value: str) -> str:
    text = str(value or "")
    return text.split(":", 1)[1] if text.startswith("tool:") else text
