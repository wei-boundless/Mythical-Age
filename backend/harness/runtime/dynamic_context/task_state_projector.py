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
        raw_current_facts = _dedupe_by_semantic(dict_tuple(execution_projection.get("current_facts")))
        current_fact_keys = {_semantic_projection_key(item) for item in raw_current_facts if _semantic_projection_key(item)}
        current_facts = _current_fact_projection(raw_current_facts)
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
        file_state = _file_state_projection(execution_projection.get("file_state"))
        task_progress_facts = _task_progress_facts_projection(file_state=file_state, latest_results=latest_results)
        evidence_confidence = _evidence_confidence_projection(latest_results)
        material_progress = _material_progress_projection(latest_results)
        payload = {
            "runtime_status": str(execution_projection.get("runtime_status") or task_run_state.get("status") or ""),
            "current_step": dict(execution_projection.get("current_step") or {}),
            "current_facts": current_facts,
            "file_state": file_state,
            "task_progress_facts": task_progress_facts,
            "read_resource_state": _read_resource_state_projection(file_state),
            "file_state_source": str(execution_projection.get("file_state_source") or ""),
            "latest_tool_results": latest_results,
            "evidence_confidence": evidence_confidence,
            "material_progress": material_progress,
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
            "exploration_advisory": _exploration_advisory_projection(
                dict(execution_projection.get("exploration_advisory") or {})
            ),
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
        latest_cursor_results = list(latest_results[-result_limit:])
        cursor["latest_tool_results"] = (
            [_cursor_tool_result_projection(item) for item in latest_cursor_results]
            if replay_entries
            else latest_cursor_results
        )
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


def _cursor_tool_result_projection(item: dict[str, Any]) -> dict[str, Any]:
    error = _dict_value(item.get("error")) or _dict_value(item.get("structured_error"))
    projected = drop_empty(
        {
            "observation_ref": str(item.get("observation_ref") or item.get("observation_id") or ""),
            "tool_name": _tool_name(str(item.get("tool_name") or item.get("source") or "")),
            "tool_call_id": str(item.get("tool_call_id") or ""),
            "status": str(item.get("status") or ""),
            "path": _projection_path(item),
            "visibility": str(item.get("visibility") or ""),
            "reason": str(item.get("reason") or error.get("code") or ""),
            "summary": compact_text(item.get("summary") or error.get("message") or "", limit=160),
            "error": _replay_safe_value(error),
            "structured_error": _replay_safe_value(_dict_value(item.get("structured_error"))),
            "code_structure": _replay_code_structure_summary(dict(item.get("code_structure") or {})),
            "content_range": _replay_content_range(dict(item.get("content_range") or {})),
            "evidence_policy": _replay_evidence_policy(dict(item.get("evidence_policy") or {})),
            "evidence_confidence": _replay_evidence_confidence(dict(item.get("evidence_confidence") or {})),
            "replacement_ref": str(item.get("replacement_ref") or ""),
            "todo_plan": _todo_plan_projection(dict(item.get("todo_plan") or {})),
            "rehydration_plan": _replay_rehydration_plan(dict(item.get("rehydration_plan") or {})),
            "current_runtime_fact": item.get("current_runtime_fact") if isinstance(item.get("current_runtime_fact"), bool) else None,
        }
    )
    return projected


def _replay_entry_projection(entry_kind: str, item: dict[str, Any]) -> dict[str, Any]:
    error = _dict_value(item.get("error")) or _dict_value(item.get("structured_error"))
    projected = drop_empty(
        {
            "entry_kind": str(entry_kind or ""),
            "observation_ref": str(item.get("observation_ref") or item.get("observation_id") or ""),
            "tool_name": _tool_name(str(item.get("tool_name") or item.get("source") or "")),
            "tool_call_id": str(item.get("tool_call_id") or ""),
            "status": str(item.get("status") or ""),
            "path": _projection_path(item),
            "visibility": str(item.get("visibility") or ""),
            "reason": str(item.get("reason") or error.get("code") or ""),
            "summary": compact_text(item.get("summary") or error.get("message") or "", limit=180),
            "error": _replay_safe_value(error),
            "structured_error": _replay_safe_value(_dict_value(item.get("structured_error"))),
            "artifact_refs": _replay_artifact_refs(item.get("artifact_refs")),
            "replacement_ref": str(item.get("replacement_ref") or ""),
            "todo_plan": _todo_plan_projection(dict(item.get("todo_plan") or {})),
            "code_structure": _replay_code_structure_summary(dict(item.get("code_structure") or {})),
            "content_range": _replay_content_range(dict(item.get("content_range") or {})),
            "evidence_policy": _replay_evidence_policy(dict(item.get("evidence_policy") or {})),
            "evidence_confidence": _replay_evidence_confidence(dict(item.get("evidence_confidence") or {})),
            "preview": _replay_preview(item),
            "rehydration_plan": _replay_rehydration_plan(dict(item.get("rehydration_plan") or {})),
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


def _replay_artifact_refs(value: Any) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for item in dict_tuple(value)[-4:]:
        refs.append(
            drop_empty(
                {
                    "artifact_ref": str(item.get("artifact_ref") or item.get("ref") or item.get("artifact_id") or ""),
                    "path": _projection_path(item),
                    "kind": str(item.get("kind") or item.get("artifact_kind") or ""),
                }
            )
        )
    return [item for item in refs if item]


def _replay_code_structure_summary(value: dict[str, Any]) -> dict[str, Any]:
    if not value:
        return {}
    files: list[dict[str, Any]] = []
    for item in dict_tuple(value.get("files"))[:6]:
        slices: list[dict[str, Any]] = []
        for segment in dict_tuple(item.get("slices"))[:4]:
            slices.append(
                drop_empty(
                    {
                        "evidence_ref": str(segment.get("evidence_ref") or ""),
                        "symbol": str(segment.get("symbol") or ""),
                        "matched_line": segment.get("matched_line"),
                        "start_line": segment.get("start_line"),
                        "end_line": segment.get("end_line"),
                        "read_request": _replay_read_request(dict(segment.get("read_request") or {})),
                    }
                )
            )
        files.append(
            drop_empty(
                {
                    "path": _projection_path(item),
                    "candidate_only": item.get("candidate_only") if isinstance(item.get("candidate_only"), bool) else None,
                    "must_read_source_before_edit": item.get("must_read_source_before_edit")
                    if isinstance(item.get("must_read_source_before_edit"), bool)
                    else None,
                    "slices": [segment for segment in slices if segment],
                }
            )
        )
    return drop_empty(
        {
            "source_kind": str(value.get("source_kind") or ""),
            "source_authority": str(value.get("source_authority") or ""),
            "candidate_only": value.get("candidate_only") if isinstance(value.get("candidate_only"), bool) else None,
            "files": [item for item in files if item],
            "limitations": [str(item) for item in list(value.get("limitations") or [])[:3] if str(item)],
            "projection": "locator_refs_only",
        }
    )


def _replay_read_request(value: dict[str, Any]) -> dict[str, Any]:
    args = dict(value.get("args") or {})
    return drop_empty(
        {
            "tool_name": _tool_name(str(value.get("tool_name") or "")),
            "args": drop_empty(
                {
                    "path": _projection_path(args),
                    "start_line": args.get("start_line"),
                    "line_count": args.get("line_count"),
                }
            ),
        }
    )


def _replay_content_range(value: dict[str, Any]) -> dict[str, Any]:
    return drop_empty(
        {
            "path": _projection_path(value),
            "start_line": value.get("start_line"),
            "end_line": value.get("end_line"),
            "next_start_line": value.get("next_start_line"),
            "has_more": value.get("has_more") if isinstance(value.get("has_more"), bool) else None,
            "content_sha256": str(value.get("content_sha256") or ""),
            "file_unchanged": value.get("file_unchanged") if isinstance(value.get("file_unchanged"), bool) else None,
            "content_omitted": value.get("content_omitted") if isinstance(value.get("content_omitted"), bool) else None,
            "previous_observation_ref": str(value.get("previous_observation_ref") or ""),
            "reusable_result_ref": str(value.get("reusable_result_ref") or value.get("previous_observation_ref") or ""),
        }
    )


def _replay_evidence_policy(value: dict[str, Any]) -> dict[str, Any]:
    return drop_empty(
        {
            "source_kind": str(value.get("source_kind") or ""),
            "source_authority": str(value.get("source_authority") or ""),
            "visible_content_authority": str(value.get("visible_content_authority") or ""),
            "must_read_source_before_edit": value.get("must_read_source_before_edit")
            if isinstance(value.get("must_read_source_before_edit"), bool)
            else None,
            "candidate_only": value.get("candidate_only") if isinstance(value.get("candidate_only"), bool) else None,
            "fresh_read_conditions": [str(item) for item in list(value.get("fresh_read_conditions") or []) if str(item).strip()],
            "usable_as_evidence_for": [str(item) for item in list(value.get("usable_as_evidence_for") or []) if str(item).strip()],
            "rehydration_preference": str(value.get("rehydration_preference") or ""),
            "instruction": compact_text(value.get("instruction") or "", limit=160),
        }
    )


def _replay_evidence_confidence(value: dict[str, Any]) -> dict[str, Any]:
    files = []
    for item in dict_tuple(value.get("files"))[:8]:
        files.append(
            drop_empty(
                {
                    "path": _projection_path(item),
                    "start_line": item.get("start_line"),
                    "end_line": item.get("end_line"),
                    "content_sha256": str(item.get("content_sha256") or ""),
                    "fresh_read_conditions": [str(entry) for entry in list(item.get("fresh_read_conditions") or []) if str(entry).strip()],
                    "usable_as_evidence_for": [str(entry) for entry in list(item.get("usable_as_evidence_for") or []) if str(entry).strip()],
                }
            )
        )
    return drop_empty(
        {
            "authority": str(value.get("authority") or "harness.runtime.dynamic_context.evidence_confidence"),
            "source_kind": str(value.get("source_kind") or ""),
            "tool_name": _tool_name(str(value.get("tool_name") or "")),
            "confidence": str(value.get("confidence") or ""),
            "fresh_read_conditions": [str(item) for item in list(value.get("fresh_read_conditions") or []) if str(item).strip()],
            "usable_as_evidence_for": [str(item) for item in list(value.get("usable_as_evidence_for") or []) if str(item).strip()],
            "files": [item for item in files if item],
        }
    )


def _replay_preview(item: dict[str, Any]) -> str:
    if item.get("replacement_ref") or dict(item.get("content_range") or {}):
        return ""
    return compact_text(item.get("preview") or "", limit=180)


def _replay_rehydration_plan(value: dict[str, Any]) -> dict[str, Any]:
    if not value:
        return {}
    capabilities: list[dict[str, Any]] = []
    for item in dict_tuple(value.get("capabilities"))[:2]:
        capabilities.append(
            drop_empty(
                {
                    "capability": str(item.get("capability") or ""),
                    "tool_name": _tool_name(str(item.get("tool_name") or "")),
                    "args": _rehydration_args_ref(dict(item.get("args") or {})),
                    "content_range": _replay_content_range(dict(item.get("content_range") or {})),
                    "next_request": _rehydration_next_request(dict(item.get("next_request") or {})),
                }
            )
        )
    return drop_empty(
        {
            "prompt_status": str(value.get("prompt_status") or ""),
            "replacement_ref": str(value.get("replacement_ref") or ""),
            "content_hash": str(value.get("content_hash") or ""),
            "capabilities": [item for item in capabilities if item],
            "authority": str(value.get("authority") or "harness.runtime.dynamic_context.rehydration_plan"),
        }
    )


def _rehydration_args_ref(value: dict[str, Any]) -> dict[str, Any]:
    return drop_empty(
        {
            "replacement_id": _tool_result_replacement_id(value.get("replacement_id")),
            "path": _projection_path(value),
            "task_run_id": str(value.get("task_run_id") or ""),
            "start_line": value.get("start_line"),
            "line_count": value.get("line_count"),
        }
    )


def _rehydration_next_request(value: dict[str, Any]) -> dict[str, Any]:
    return drop_empty(
        {
            "tool_name": _tool_name(str(value.get("tool_name") or "")),
            "args": _rehydration_args_ref(dict(value.get("args") or {})),
        }
    )


def _tool_result_replacement_id(value: Any) -> str:
    candidate = str(value or "").strip()
    return candidate if candidate.startswith("tool_result:") else ""


def _evidence_confidence_projection(latest_results: list[dict[str, Any]]) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    locator_count = 0
    for item in latest_results:
        confidence = _replay_evidence_confidence(dict(item.get("evidence_confidence") or {}))
        if not confidence:
            continue
        if str(confidence.get("source_kind") or "") == "code_locator":
            locator_count += 1
        files.extend(dict_tuple(confidence.get("files")))
    deduped_files = _dedupe_evidence_files(files)
    if not deduped_files and not locator_count:
        return {}
    return drop_empty(
        {
            "authority": "harness.runtime.dynamic_context.evidence_confidence",
            "files": deduped_files,
            "locator_result_count": locator_count,
        }
    )


def _task_progress_facts_projection(
    *,
    file_state: list[dict[str, Any]],
    latest_results: list[dict[str, Any]],
) -> dict[str, Any]:
    files = [_task_progress_file_fact(item) for item in list(file_state or [])]
    todos = _task_progress_todo_facts(latest_results)
    recent_tool_observations = _task_progress_tool_observations(latest_results)
    return drop_empty(
        {
            "authority": "harness.runtime.dynamic_context.task_progress_facts",
            "files": [item for item in files if item][-12:],
            "todos": todos,
            "recent_tool_observations": recent_tool_observations,
        }
    )


def _task_progress_file_fact(item: dict[str, Any]) -> dict[str, Any]:
    coverage = dict(item.get("coverage") or {})
    reusable_ref = _file_reusable_result_ref(item)
    next_missing_ranges = list(coverage.get("missing_ranges") or [])
    return drop_empty(
        {
            "path": _projection_path(item),
            "status": str(item.get("status") or ""),
            "coverage": coverage,
            "total_lines": item.get("total_lines"),
            "content_sha256": str(item.get("content_sha256") or ""),
            "stale": str(item.get("status") or "") == "stale",
            "has_more": item.get("has_more") if isinstance(item.get("has_more"), bool) else None,
            "last_observation_ref": str(item.get("last_observation_ref") or ""),
            "reusable_result_ref": reusable_ref,
            "next_missing_ranges": next_missing_ranges,
            "next_suggested_read": dict(item.get("next_suggested_read") or {}),
            "read_windows_available": [
                drop_empty(
                    {
                        "start_line": segment.get("start_line"),
                        "end_line": segment.get("end_line"),
                        "observation_ref": str(segment.get("observation_ref") or ""),
                        "reusable_result_ref": str(
                            segment.get("reusable_result_ref") or segment.get("previous_observation_ref") or ""
                        ),
                        "file_unchanged": segment.get("file_unchanged")
                        if isinstance(segment.get("file_unchanged"), bool)
                        else None,
                    }
                )
                for segment in dict_tuple(item.get("read_ranges"))[-8:]
            ],
        }
    )


def _file_reusable_result_ref(item: dict[str, Any]) -> str:
    for segment in reversed(dict_tuple(item.get("read_ranges"))):
        for key in ("reusable_result_ref", "previous_observation_ref", "observation_ref"):
            value = str(segment.get(key) or "").strip()
            if value:
                return value
    return str(item.get("last_observation_ref") or "").strip()


def _task_progress_todo_facts(latest_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest_plan: dict[str, Any] = {}
    for item in latest_results:
        if _tool_name(str(item.get("tool_name") or "")) != "agent_todo":
            continue
        plan = _todo_plan_projection(dict(item.get("todo_plan") or {}))
        if plan:
            latest_plan = plan
    if not latest_plan:
        return []
    allowed_operations = list(latest_plan.get("allowed_operations") or [])
    result: list[dict[str, Any]] = []
    for item in dict_tuple(latest_plan.get("items")):
        todo_id = str(item.get("todo_id") or "").strip()
        if not todo_id:
            continue
        result.append(
            drop_empty(
                {
                    "id": todo_id,
                    "title": compact_text(item.get("content") or "", limit=180),
                    "active_form": compact_text(item.get("active_form") or "", limit=120),
                    "status": str(item.get("status") or ""),
                    "notes": compact_text(item.get("notes") or "", limit=180),
                    "allowed_operations": allowed_operations,
                    "evidence_refs": [
                        str(value)
                        for value in [
                            *list(item.get("contract_refs") or []),
                            *list(item.get("evidence_expectations") or []),
                        ]
                        if str(value).strip()
                    ][-6:],
                    "plan_id": str(latest_plan.get("plan_id") or ""),
                }
            )
        )
    return result[-20:]


def _todo_plan_projection(value: dict[str, Any]) -> dict[str, Any]:
    if not value:
        return {}
    items: list[dict[str, Any]] = []
    for item in dict_tuple(value.get("items"))[:40]:
        todo_id = str(item.get("todo_id") or item.get("id") or "").strip()
        if not todo_id:
            continue
        items.append(
            drop_empty(
                {
                    "todo_id": todo_id,
                    "content": compact_text(item.get("content") or item.get("title") or "", limit=180),
                    "active_form": compact_text(item.get("active_form") or "", limit=120),
                    "status": str(item.get("status") or ""),
                    "notes": compact_text(item.get("notes") or "", limit=180),
                    "evidence_expectations": [
                        str(entry) for entry in list(item.get("evidence_expectations") or []) if str(entry).strip()
                    ],
                    "contract_refs": [str(entry) for entry in list(item.get("contract_refs") or []) if str(entry).strip()],
                }
            )
        )
    return drop_empty(
        {
            "plan_id": str(value.get("plan_id") or ""),
            "active_item_id": str(value.get("active_item_id") or ""),
            "completion_ready": value.get("completion_ready") if isinstance(value.get("completion_ready"), bool) else None,
            "items": items,
            "allowed_operations": list(value.get("allowed_operations") or ["replace", "append", "start", "complete", "update_status", "remove", "clear", "view"]),
            "authority": str(value.get("authority") or "agent.todo_plan"),
        }
    )


def _task_progress_tool_observations(latest_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    for item in latest_results[-12:]:
        tool_name = _tool_name(str(item.get("tool_name") or ""))
        if not tool_name:
            continue
        observations.append(
            drop_empty(
                {
                    "tool_call_id": str(item.get("tool_call_id") or ""),
                    "tool_name": tool_name,
                    "outcome": str(item.get("status") or ""),
                    "observation_ref": str(item.get("observation_ref") or item.get("tool_result_ref") or ""),
                    "path": _projection_path(item),
                    "trace_only": _is_context_only_tool(tool_name),
                    "reason": str(item.get("reason") or ""),
                    "event_offset": item.get("event_offset"),
                }
            )
        )
    return observations


def _dedupe_evidence_files(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    for item in files:
        path = _projection_path(item)
        if not path:
            continue
        key = "|".join(
            [
                path,
                str(item.get("start_line") or ""),
                str(item.get("end_line") or ""),
                str(item.get("content_sha256") or ""),
            ]
        )
        by_key[key] = dict(item)
    return list(by_key.values())[-12:]


def _material_progress_projection(latest_results: list[dict[str, Any]]) -> dict[str, Any]:
    material_actions: list[dict[str, Any]] = []
    context_streak = 0
    material_since_context = False
    for item in latest_results:
        tool_name = _tool_name(str(item.get("tool_name") or ""))
        if not tool_name:
            continue
        if _is_material_progress_tool(tool_name) and _result_succeeded(item):
            material_since_context = True
            context_streak = 0
            material_actions.append(
                drop_empty(
                    {
                        "tool_name": tool_name,
                        "path": _projection_path(item),
                        "summary": compact_text(item.get("summary") or "", limit=180),
                        "event_offset": item.get("event_offset"),
                        "created_at": item.get("created_at"),
                    }
                )
            )
            continue
        if _is_context_only_tool(tool_name):
            context_streak += 1
    return drop_empty(
        {
            "authority": "harness.runtime.dynamic_context.material_progress",
            "material_event_count": len(material_actions),
            "material_actions": material_actions[-8:],
            "context_action_streak": context_streak,
            "material_progress_since_last_context_action": material_since_context and context_streak == 0,
        }
    )


def _is_material_progress_tool(tool_name: str) -> bool:
    return tool_name in {
        "write_file",
        "edit_file",
        "apply_patch",
        "terminal",
        "shell_command",
        "run_command",
        "execute_command",
        "save_file",
        "create_file",
        "delete_file",
        "move_file",
    }


def _is_context_only_tool(tool_name: str) -> bool:
    return tool_name in {
        "read_file",
        "read_resource_state",
        "read_persisted_tool_result",
        "search_text",
        "search_files",
        "codebase_search",
        "stat_path",
        "agent_todo",
    }


def _result_succeeded(item: dict[str, Any]) -> bool:
    status = str(item.get("status") or "").strip().lower()
    if status in {"failed", "error", "blocked", "timeout", "denied", "canceled", "cancelled", "aborted"}:
        return False
    return not bool(item.get("error") or item.get("structured_error"))


def _current_fact_projection(items: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        projected = drop_empty(
            {
                "observation_ref": str(item.get("observation_ref") or item.get("observation_id") or ""),
                "tool_name": _tool_name(str(item.get("tool_name") or item.get("source") or "")),
                "status": str(item.get("status") or ""),
                "path": _projection_path(item),
                "visibility": str(item.get("visibility") or ""),
                "reason": str(item.get("reason") or ""),
                "summary": compact_text(item.get("summary") or "", limit=140),
                "content_range": _replay_content_range(dict(item.get("content_range") or {})),
                "replacement_ref": str(item.get("replacement_ref") or ""),
            }
        )
        if projected:
            facts.append(projected)
    return facts[-8:]


def _exploration_advisory_projection(value: dict[str, Any]) -> dict[str, Any]:
    if not value:
        return {}
    recent_tools: list[dict[str, Any]] = []
    for item in dict_tuple(value.get("recent_tools"))[-4:]:
        recent_tools.append(
            drop_empty(
                {
                    "observation_ref": str(item.get("observation_ref") or item.get("observation_id") or ""),
                    "tool_name": _tool_name(str(item.get("tool_name") or item.get("source") or "")),
                    "status": str(item.get("status") or ""),
                    "path": _projection_path(item),
                    "summary": compact_text(item.get("summary") or "", limit=100),
                }
            )
        )
    return drop_empty(
        {
            "triggered": value.get("triggered") if isinstance(value.get("triggered"), bool) else None,
            "kind": str(value.get("kind") or ""),
            "authority_boundary": str(value.get("authority_boundary") or ""),
            "consecutive_exploration_tool_calls": value.get("consecutive_exploration_tool_calls"),
            "threshold": value.get("threshold"),
            "non_blocking": value.get("non_blocking") if isinstance(value.get("non_blocking"), bool) else None,
            "decision_questions": [
                compact_text(item, limit=80)
                for item in list(value.get("decision_questions") or [])[:2]
                if str(item)
            ],
            "recent_tools": [item for item in recent_tools if item],
            "authority": str(value.get("authority") or "harness.task_observation_projection.exploration_advisory"),
        }
    )


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
                    "tool_call_id": str(item.get("tool_call_id") or ""),
                    "status": str(item.get("status") or ""),
                    "path": _projection_path(item),
                    "visibility": str(item.get("visibility") or ""),
                    "summary": compact_text(item.get("summary") or "", limit=300),
                    "todo_plan": _todo_plan_projection(dict(item.get("todo_plan") or {})),
                    "code_structure": dict(item.get("code_structure") or {}),
            "content_range": dict(item.get("content_range") or {}),
            "evidence_policy": _replay_evidence_policy(dict(item.get("evidence_policy") or {})),
            "evidence_confidence": _replay_evidence_confidence(dict(item.get("evidence_confidence") or {})),
            "preview": _code_evidence_preview(item),
                    "rehydration_plan": _replay_rehydration_plan(dict(item.get("rehydration_plan") or {})),
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
            "tool_call_id": str(item.get("tool_call_id") or tool_result.get("tool_call_id") or ""),
            "status": str(item.get("status") or tool_result.get("status") or ""),
            "path": _projection_path(item) or _projection_path(tool_result),
            "visibility": str(item.get("visibility") or ""),
            "summary": compact_text(item.get("summary") or tool_result.get("preview") or "", limit=300),
            "structured_error": structured_error,
            "artifact_refs": list(dict_tuple(item.get("artifact_refs") or tool_result.get("artifact_refs"))),
            "replacement_ref": str(tool_result.get("replacement_ref") or ""),
            "todo_plan": _todo_plan_projection(dict(item.get("todo_plan") or tool_result.get("todo_plan") or {})),
            "code_structure": dict(item.get("code_structure") or tool_result.get("code_structure") or {}),
            "content_range": dict(item.get("content_range") or tool_result.get("content_range") or {}),
            "evidence_policy": _replay_evidence_policy(dict(item.get("evidence_policy") or tool_result.get("evidence_policy") or {})),
            "evidence_confidence": _replay_evidence_confidence(dict(item.get("evidence_confidence") or tool_result.get("evidence_confidence") or {})),
            "preview": _code_evidence_preview(tool_result),
            "rehydration_plan": _replay_rehydration_plan(dict(item.get("rehydration_plan") or tool_result.get("rehydration_plan") or {})),
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
    return preview[:1200].rstrip()


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
    return result[-5:]


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
            _file_state_read_range_projection(segment)
            for segment in dict_tuple(item.get("read_ranges"))
            if segment.get("start_line") not in (None, "") and segment.get("end_line") not in (None, "")
        ]
        editor_state = _editor_file_state_projection(dict(item.get("editor_state") or {}))
        projected = drop_empty(
            {
                "path": path,
                "read_ranges": ranges[-6:],
                "coverage": dict(item.get("coverage") or {}),
                "total_lines": item.get("total_lines"),
                "content_sha256": str(item.get("content_sha256") or ""),
                "last_observation_ref": str(item.get("last_observation_ref") or ""),
                "has_more": item.get("has_more") if isinstance(item.get("has_more"), bool) else None,
                "status": str(item.get("status") or ""),
                "stale_reason": compact_text(item.get("stale_reason") or "", limit=180),
                "editor_state": editor_state,
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
                        ][-3:],
                    ]
                    if ref
                ][-4:],
            }
        )
        if projected:
            result.append(projected)
    return result[-10:]


def _file_state_read_range_projection(segment: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "start_line": segment.get("start_line"),
        "end_line": segment.get("end_line"),
        "observation_ref": str(segment.get("observation_ref") or ""),
    }
    read_intent = str(segment.get("read_intent") or "")
    if read_intent:
        payload["read_intent"] = read_intent
    if isinstance(segment.get("file_unchanged"), bool):
        payload["file_unchanged"] = segment.get("file_unchanged")
    if isinstance(segment.get("content_omitted"), bool):
        payload["content_omitted"] = segment.get("content_omitted")
    if isinstance(segment.get("has_more"), bool):
        payload["has_more"] = segment.get("has_more")
    if segment.get("next_start_line") not in (None, ""):
        payload["next_start_line"] = segment.get("next_start_line")
    previous_ref = str(segment.get("previous_observation_ref") or "")
    if previous_ref:
        payload["previous_observation_ref"] = previous_ref
    reusable_ref = str(segment.get("reusable_result_ref") or previous_ref)
    if reusable_ref:
        payload["reusable_result_ref"] = reusable_ref
    source = str(segment.get("source") or "")
    if source:
        payload["source"] = source
    if isinstance(segment.get("truncated"), bool):
        payload["truncated"] = segment.get("truncated")
    return payload


def _read_resource_state_projection(file_state: list[dict[str, Any]]) -> dict[str, Any]:
    active_files = [
        item
        for item in list(file_state or [])
        if dict_tuple(item.get("read_ranges")) and str(item.get("status") or "") not in {"stale", "missing"}
    ]
    stale_files = [item for item in list(file_state or []) if str(item.get("status") or "") == "stale"]
    if not active_files and not stale_files:
        return {}
    latest = active_files[-1] if active_files else stale_files[-1]
    path = str(latest.get("path") or "")
    if stale_files and not active_files:
        return drop_empty(
            {
                "kind": "read_resource_state",
                "authority_boundary": "resource_state_only",
                "status": "stale",
                "path": path,
                "stale": True,
                "stale_range_count": sum(len(dict_tuple(item.get("read_ranges"))) for item in stale_files),
                "available_evidence_refs": _read_resource_evidence_refs(stale_files),
                "reliability_note": "Previously read ranges are stale after a write or edit event; use them only as history, not as current file content.",
                "authority": "harness.runtime.dynamic_context.read_resource_state",
            }
        )
    active_ranges = [segment for item in active_files for segment in dict_tuple(item.get("read_ranges"))]
    return drop_empty(
        {
            "kind": "read_resource_state",
            "authority_boundary": "resource_state_only",
            "status": "available",
            "path": path,
            "files": [
                drop_empty(
                    {
                        "path": str(item.get("path") or ""),
                        "status": str(item.get("status") or ""),
                        "coverage": dict(item.get("coverage") or {}),
                        "has_more": item.get("has_more") if isinstance(item.get("has_more"), bool) else None,
                        "content_sha256": str(item.get("content_sha256") or ""),
                        "last_observation_ref": str(item.get("last_observation_ref") or ""),
                        "next_suggested_read": dict(item.get("next_suggested_read") or {}),
                    }
                )
                for item in active_files[-8:]
            ],
            "available_range_count": len(active_ranges),
            "available_evidence_refs": _read_resource_evidence_refs(active_files),
            "coverage": dict(latest.get("coverage") or {}),
            "has_more": latest.get("has_more") if isinstance(latest.get("has_more"), bool) else None,
            "content_sha256": str(latest.get("content_sha256") or ""),
            "reliability_note": "These are resource facts about previously returned read windows. The model remains responsible for deciding whether more context is needed.",
            "authority": "harness.runtime.dynamic_context.read_resource_state",
        }
    )


def _read_resource_evidence_refs(file_state: list[dict[str, Any]]) -> list[str]:
    refs: list[str] = []
    for item in list(file_state or []):
        for ref in list(item.get("evidence_refs") or []):
            text = str(ref or "").strip()
            if text and text not in refs:
                refs.append(text)
        for segment in dict_tuple(item.get("read_ranges")):
            text = str(segment.get("observation_ref") or "").strip()
            if text and text not in refs:
                refs.append(text)
    return refs[-6:]


def _editor_file_state_projection(value: dict[str, Any]) -> dict[str, Any]:
    if not value:
        return {}
    preview = dict(value.get("content_preview") or {})
    selection = dict(value.get("selection") or {})
    return drop_empty(
        {
            "source": str(value.get("source") or ""),
            "active": value.get("active") if isinstance(value.get("active"), bool) else None,
            "visible": value.get("visible") if isinstance(value.get("visible"), bool) else None,
            "dirty": value.get("dirty") if isinstance(value.get("dirty"), bool) else None,
            "language_id": str(value.get("language_id") or ""),
            "content_preview": drop_empty(
                {
                    "source": str(preview.get("source") or ""),
                    "chars": preview.get("chars"),
                    "truncated": preview.get("truncated") if isinstance(preview.get("truncated"), bool) else None,
                    "content_sha256": str(preview.get("content_sha256") or ""),
                }
            ),
            "selection": drop_empty(
                {
                    "start_line": selection.get("start_line"),
                    "end_line": selection.get("end_line"),
                    "chars": selection.get("chars"),
                    "truncated": selection.get("truncated") if isinstance(selection.get("truncated"), bool) else None,
                }
            ),
        }
    )


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
