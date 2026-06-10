from __future__ import annotations

from typing import Any

from artifact_system.artifact_authority import artifact_ref_value, dedupe_artifact_refs, model_visible_artifact_refs

from .models import compact_text, dict_tuple, drop_empty


_PROMPT_CACHE_UNSTABLE_REPLAY_KEYS = {
    "agent_invocation_id",
    "attempt",
    "active_contract_revisions",
    "current_facts",
    "executor_status",
    "graph_run_id",
    "graph_work_order_id",
    "observations",
    "pending_user_steers",
    "runtime_assembly_id",
    "runtime_controls",
    "state_refs",
    "task_run_id",
    "turn_id",
    "work_order_id",
}


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
            dedupe_artifact_refs(
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
            "exploration_advisory": dict(execution_projection.get("exploration_advisory") or {}),
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

    def split_for_prompt_cache(
        self,
        task_state: dict[str, Any],
        *,
        replay_entry_limit: int = 12,
        cursor_result_limit: int = 2,
        cursor_failure_limit: int = 2,
    ) -> tuple[tuple[dict[str, Any], ...], dict[str, Any]]:
        state = dict(task_state or {})
        if not state:
            return (), {}
        replay_entries = tuple(
            _task_state_replay_entries(
                state,
                limit=max(1, int(replay_entry_limit or 12)),
            )
        )
        cursor = _task_state_cursor_projection(
            state,
            replay_entries=replay_entries,
            result_limit=max(1, int(cursor_result_limit or 2)),
            failure_limit=max(1, int(cursor_failure_limit or 2)),
        )
        return replay_entries, cursor


def _task_state_replay_entries(task_state: dict[str, Any], *, limit: int) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    index_by_key: dict[str, int] = {}
    order_by_key: dict[str, tuple[int, int, str]] = {}
    fallback_order = 0
    for entry_kind, items in (
        ("tool_result", dict_tuple(task_state.get("latest_tool_results"))),
        ("active_failure", dict_tuple(task_state.get("active_failures"))),
        ("historical_failure", dict_tuple(task_state.get("historical_failures"))),
    ):
        for item in items:
            fallback_order += 1
            entry = _replay_entry_projection(entry_kind, item)
            if not entry:
                continue
            key = _replay_entry_key(entry)
            order = _replay_entry_order(item, fallback_order=fallback_order)
            if key in index_by_key:
                index = index_by_key[key]
                merged = _merge_projection(entries[index], entry)
                merged["entry_kind"] = _merged_entry_kind(entries[index].get("entry_kind"), entry.get("entry_kind"))
                entries[index] = merged
                order_by_key[key] = min(order_by_key[key], order)
                continue
            index_by_key[key] = len(entries)
            order_by_key[key] = order
            entries.append(entry)
    ordered = sorted(entries, key=lambda entry: order_by_key.get(_replay_entry_key(entry), (1, 0, _replay_entry_key(entry))))
    return ordered[-limit:]


def _task_state_cursor_projection(
    task_state: dict[str, Any],
    *,
    replay_entries: tuple[dict[str, Any], ...],
    result_limit: int,
    failure_limit: int,
) -> dict[str, Any]:
    cursor = dict(task_state or {})
    latest_results = dict_tuple(cursor.get("latest_tool_results"))
    active_failures = dict_tuple(cursor.get("active_failures"))
    file_state = _cursor_file_state_projection(dict_tuple(cursor.get("file_state")))
    if file_state:
        cursor["file_state"] = file_state
    else:
        cursor.pop("file_state", None)
    if latest_results:
        cursor["latest_tool_results"] = list(latest_results[-result_limit:])
    else:
        cursor.pop("latest_tool_results", None)
    if active_failures:
        cursor["active_failures"] = list(active_failures[-failure_limit:])
    else:
        cursor.pop("active_failures", None)
    cursor.pop("historical_failures", None)
    if replay_entries:
        cursor["replay_prefix"] = drop_empty(
            {
                "entry_count": len(replay_entries),
                "latest_entry_ref": _entry_ref(replay_entries[-1]),
                "instruction": (
                    "上方 task_state_replay_entry 是本任务已发生的工具结果和失败证据。"
                    "不要重复已经失败或已经完成的同类尝试；若历史证据与当前状态冲突，以当前 task_state 为准。"
                ),
                "authority": "harness.runtime.dynamic_context.task_state_replay_cursor",
            }
        )
    return drop_empty(cursor)


def _replay_entry_projection(entry_kind: str, item: dict[str, Any]) -> dict[str, Any]:
    error = _dict_value(item.get("error")) or _dict_value(item.get("structured_error"))
    projected = drop_empty(
        {
            "entry_kind": str(entry_kind or ""),
            "observation_ref": str(item.get("observation_ref") or item.get("observation_id") or ""),
            "tool_name": _tool_name(str(item.get("tool_name") or item.get("source") or "")),
            "status": str(item.get("status") or ""),
            "path": _projection_path(item),
            "visibility": str(item.get("visibility") or ""),
            "reason": str(item.get("reason") or error.get("code") or ""),
            "summary": compact_text(item.get("summary") or error.get("message") or "", limit=300),
            "error": _replay_safe_value(error),
            "structured_error": _replay_safe_value(_dict_value(item.get("structured_error"))),
            "artifact_refs": _replay_safe_value(list(dict_tuple(item.get("artifact_refs")))),
            "replacement_ref": str(item.get("replacement_ref") or ""),
            "code_structure": _replay_safe_value(dict(item.get("code_structure") or {})),
            "content_range": _replay_safe_value(dict(item.get("content_range") or {})),
            "evidence_policy": _replay_safe_value(dict(item.get("evidence_policy") or {})),
            "preview": compact_text(item.get("preview") or "", limit=1200),
            "rehydration_plan": _replay_safe_value(dict(item.get("rehydration_plan") or {})),
            "current_runtime_fact": item.get("current_runtime_fact") if isinstance(item.get("current_runtime_fact"), bool) else None,
            "authority": "harness.runtime.dynamic_context.task_state_replay_entry",
        }
    )
    if set(projected).issubset({"entry_kind", "authority"}):
        return {}
    return projected


def _replay_entry_key(entry: dict[str, Any]) -> str:
    ref = str(entry.get("observation_ref") or "").strip()
    if ref:
        return f"observation:{ref}"
    semantic = _semantic_projection_key(entry)
    if semantic:
        return semantic
    return _ref_projection_key(entry)


def _replay_entry_order(item: dict[str, Any], *, fallback_order: int) -> tuple[int, int, str]:
    for key in ("event_offset", "observation_event_offset", "action_event_offset", "sequence", "step_index", "invocation_index"):
        value = _safe_int(item.get(key))
        if value > 0:
            return (0, value, str(item.get("observation_ref") or item.get("observation_id") or ""))
    created_at = _safe_float(item.get("created_at"))
    if created_at > 0:
        return (0, int(created_at * 1000), str(item.get("observation_ref") or item.get("observation_id") or ""))
    return (1, int(fallback_order or 0), str(item.get("observation_ref") or item.get("observation_id") or ""))


def _merged_entry_kind(first: Any, second: Any) -> str:
    kinds = [str(item or "") for item in (first, second) if str(item or "")]
    if not kinds:
        return ""
    ordered = []
    for kind in kinds:
        if kind not in ordered:
            ordered.append(kind)
    return "+".join(ordered)


def _entry_ref(entry: dict[str, Any]) -> str:
    ref = str(entry.get("observation_ref") or "").strip()
    if ref:
        return ref
    return _replay_entry_key(entry)


def _replay_safe_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _replay_safe_value(item)
            for key, item in value.items()
            if str(key) not in _PROMPT_CACHE_UNSTABLE_REPLAY_KEYS
        }
    if isinstance(value, list):
        return [_replay_safe_value(item) for item in value]
    if isinstance(value, tuple):
        return [_replay_safe_value(item) for item in value]
    return value


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
                    "code_structure": dict(item.get("code_structure") or {}),
                    "content_range": dict(item.get("content_range") or {}),
                    "evidence_policy": dict(item.get("evidence_policy") or {}),
                    "preview": _code_evidence_preview(item),
                    "rehydration_plan": dict(item.get("rehydration_plan") or {}),
                    "event_offset": item.get("event_offset"),
                    "observation_event_offset": item.get("observation_event_offset"),
                    "action_event_offset": item.get("action_event_offset"),
                    "sequence": item.get("sequence"),
                    "step_index": item.get("step_index"),
                    "invocation_index": item.get("invocation_index"),
                    "created_at": item.get("created_at"),
                }
            )
        )
    for item in dict_tuple(observation_projection.get("latest_observations")):
        results.append(_observation_result_projection(item))
    deduped = _dedupe_by_semantic([item for item in results if item])
    return [item for item in deduped if _should_keep_latest_result(item, current_fact_keys=current_fact_keys)]


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
            "code_structure": dict(item.get("code_structure") or tool_result.get("code_structure") or {}),
            "content_range": dict(item.get("content_range") or tool_result.get("content_range") or {}),
            "evidence_policy": dict(item.get("evidence_policy") or tool_result.get("evidence_policy") or {}),
            "preview": _code_evidence_preview(tool_result),
            "rehydration_plan": dict(item.get("rehydration_plan") or tool_result.get("rehydration_plan") or {}),
            "event_offset": item.get("event_offset") or tool_result.get("event_offset"),
            "observation_event_offset": item.get("observation_event_offset") or tool_result.get("observation_event_offset"),
            "action_event_offset": item.get("action_event_offset") or tool_result.get("action_event_offset"),
            "sequence": item.get("sequence") or tool_result.get("sequence"),
            "step_index": item.get("step_index") or tool_result.get("step_index"),
            "invocation_index": item.get("invocation_index") or tool_result.get("invocation_index"),
            "created_at": item.get("created_at") or tool_result.get("created_at"),
        }
    )
    if set(projected).issubset({"observation_ref", "replacement_ref"}):
        return {}
    return projected


def _should_keep_latest_result(item: dict[str, Any], *, current_fact_keys: set[str]) -> bool:
    key = _semantic_projection_key(item)
    if key not in current_fact_keys:
        return True
    evidence_policy = dict(item.get("evidence_policy") or {})
    if not str(evidence_policy.get("source_kind") or "").startswith("code_"):
        return False
    return bool(item.get("preview") or item.get("code_structure"))


def _code_evidence_preview(item: dict[str, Any]) -> str:
    evidence_policy = dict(item.get("evidence_policy") or {})
    if str(evidence_policy.get("source_kind") or "") != "code_evidence":
        return ""
    preview = str(item.get("preview") or "")
    if not preview:
        return ""
    return preview[:4000].rstrip()


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
            "event_offset": item.get("event_offset"),
            "observation_event_offset": item.get("observation_event_offset"),
            "action_event_offset": item.get("action_event_offset"),
            "sequence": item.get("sequence"),
            "step_index": item.get("step_index"),
            "invocation_index": item.get("invocation_index"),
            "created_at": item.get("created_at"),
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
                for item in dict_tuple(work_history_projection.get("recent_steps"))[-1:]
            ],
        }
    )


def _cursor_file_state_projection(items: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict) or _low_value_file_state_cursor_item(item):
            continue
        result.append(dict(item))
    return result[-8:]


def _low_value_file_state_cursor_item(item: dict[str, Any]) -> bool:
    if dict_tuple(item.get("read_ranges")):
        return False
    if dict(item.get("coverage") or {}):
        return False
    if dict(item.get("next_suggested_read") or {}):
        return False
    for key in ("total_lines", "content_sha256", "has_more"):
        if item.get(key) not in (None, "", [], {}):
            return False
    status = str(item.get("status") or "").strip().lower()
    return status in {"", "missing", "absent", "not_found", "ok"}


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
        value = artifact_ref_value(ref).replace("\\", "/").strip().strip("/")
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


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


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
