from __future__ import annotations

from typing import Any

from artifact_system.artifact_authority import artifact_ref_value, dedupe_artifact_refs, model_visible_artifact_refs

from .models import compact_text, dict_tuple, drop_empty
from .semantic_payload_classifier import merge_pending_tool_control_actions
from .todo_plan_projection import project_todo_plan


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
        current_todo_plan: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        raw_current_facts = _dedupe_by_semantic(dict_tuple(execution_projection.get("current_facts")))
        current_fact_keys = {_semantic_projection_key(item) for item in raw_current_facts if _semantic_projection_key(item)}
        current_facts = _current_fact_projection(raw_current_facts)
        authoritative_subagent_results = _authoritative_subagent_results_projection(
            execution_projection.get("authoritative_subagent_results")
        )
        latest_results = _latest_results(
            execution_projection=execution_projection,
            observation_projection=observation_projection,
            authoritative_subagent_results=authoritative_subagent_results,
            current_fact_keys=current_fact_keys,
            current_todo_plan=current_todo_plan,
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
        file_evidence_decisions = _file_evidence_decisions_projection(file_state)
        task_progress_facts = _task_progress_facts_projection(
            file_state=file_state,
            latest_results=latest_results,
            file_evidence_decisions=file_evidence_decisions,
        )
        evidence_confidence = _evidence_confidence_projection(latest_results)
        material_progress = _material_progress_projection(latest_results)
        pending_tool_control_actions = merge_pending_tool_control_actions(
            execution_projection.get("pending_tool_control_actions"),
            observation_projection.get("pending_tool_control_actions"),
            limit=12,
        )
        payload = {
            "runtime_status": str(execution_projection.get("runtime_status") or task_run_state.get("status") or ""),
            "current_step": dict(execution_projection.get("current_step") or {}),
            "pending_tool_control_actions": pending_tool_control_actions,
            "runtime_control_signals": list(dict_tuple(execution_projection.get("runtime_control_signals"))),
            "latest_runtime_control_signal": dict(execution_projection.get("latest_runtime_control_signal") or {}),
            "current_facts": current_facts,
            "authoritative_subagent_results": authoritative_subagent_results,
            "file_state": file_state,
            "file_evidence_decisions": file_evidence_decisions,
            "task_progress_facts": task_progress_facts,
            "read_resource_state": _read_resource_state_projection(
                file_state,
                file_evidence_decisions=file_evidence_decisions,
            ),
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
        ("subagent_result", dict_tuple(task_state.get("authoritative_subagent_results"))),
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
    return _bounded_replay_entries(ordered, limit=limit)


def _bounded_replay_entries(entries: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    bounded_limit = max(1, int(limit or 1))
    if len(entries) <= bounded_limit:
        return entries
    protected_limit = min(4, bounded_limit)
    protected = [entry for entry in entries if _is_protected_replay_entry(entry)]
    selected_protected = protected[-protected_limit:]
    selected_keys = {_replay_entry_key(entry) for entry in selected_protected}
    remaining = max(0, bounded_limit - len(selected_keys))
    selected_unprotected = [
        entry
        for entry in entries
        if _replay_entry_key(entry) not in selected_keys
    ][-remaining:] if remaining else []
    selected_keys.update(_replay_entry_key(entry) for entry in selected_unprotected)
    return [entry for entry in entries if _replay_entry_key(entry) in selected_keys]


def _is_protected_replay_entry(entry: dict[str, Any]) -> bool:
    entry_kind = str(entry.get("entry_kind") or "")
    if "subagent_result" in entry_kind:
        return True
    return _is_authoritative_subagent_result(entry)


def _task_state_cursor_projection(
    task_state: dict[str, Any],
    *,
    replay_entries: tuple[dict[str, Any], ...],
    result_limit: int,
    failure_limit: int,
) -> dict[str, Any]:
    cursor = dict(task_state or {})
    latest_results = dict_tuple(cursor.get("latest_tool_results"))
    subagent_results = dict_tuple(cursor.get("authoritative_subagent_results"))
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
    if subagent_results:
        cursor["authoritative_subagent_results"] = [
            _cursor_tool_result_projection(item)
            for item in subagent_results[-4:]
        ]
    else:
        cursor.pop("authoritative_subagent_results", None)
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
                "cursor_code": "append_only_replay_available",
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
            "todo_plan": project_todo_plan(dict(item.get("todo_plan") or {})),
            "subagent_result": _cursor_subagent_result_projection(dict(item.get("subagent_result") or {})),
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
            "todo_plan": project_todo_plan(dict(item.get("todo_plan") or {})),
            "code_structure": _replay_code_structure_summary(dict(item.get("code_structure") or {})),
            "content_range": _replay_content_range(dict(item.get("content_range") or {})),
            "evidence_policy": _replay_evidence_policy(dict(item.get("evidence_policy") or {})),
            "evidence_confidence": _replay_evidence_confidence(dict(item.get("evidence_confidence") or {})),
            "preview": _replay_preview(item),
            "subagent_result": _subagent_result_projection(dict(item.get("subagent_result") or {}), include_final_answer=True),
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


def _subagent_result_projection(value: dict[str, Any], *, include_final_answer: bool) -> dict[str, Any]:
    if not value:
        return {}
    final_answer = str(value.get("final_answer") or "")
    projected = drop_empty(
        {
            "kind": str(value.get("kind") or "subagent_final_result"),
            "source_tool": str(value.get("source_tool") or "collect_subagent_result"),
            "subagent_run_ref": str(value.get("subagent_run_ref") or ""),
            "result_ref": str(value.get("result_ref") or ""),
            "status": str(value.get("status") or ""),
            "result_state": str(value.get("result_state") or ""),
            "result_read_record_ref": str(value.get("result_read_record_ref") or ""),
            "final_answer": final_answer if include_final_answer else "",
            "final_answer_chars": value.get("final_answer_chars"),
            "final_answer_sha256": str(value.get("final_answer_sha256") or ""),
            "final_answer_truncated": value.get("final_answer_truncated") if isinstance(value.get("final_answer_truncated"), bool) else None,
            "max_visible_final_answer_chars": value.get("max_visible_final_answer_chars"),
            "summary": compact_text(value.get("summary") or "", limit=500),
            "artifact_refs": _replay_artifact_refs(value.get("artifact_refs")),
            "evidence_refs": [str(item) for item in list(value.get("evidence_refs") or [])[:24] if str(item).strip()],
            "observation_refs": [str(item) for item in list(value.get("observation_refs") or [])[:24] if str(item).strip()],
            "limitations": [str(item) for item in list(value.get("limitations") or [])[:24] if str(item).strip()],
            "authority": str(value.get("authority") or "orchestration.subagent_result_projection"),
        }
    )
    return projected


def _cursor_subagent_result_projection(value: dict[str, Any]) -> dict[str, Any]:
    projected = _subagent_result_projection(value, include_final_answer=False)
    if not projected:
        return {}
    if value.get("final_answer"):
        projected["final_answer_available_in_replay"] = True
    return projected


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
            "reusable_result_ref": str(value.get("reusable_result_ref") or ""),
            "exact_artifact_ref": str(value.get("exact_artifact_ref") or ""),
            "artifact_ref_status": str(value.get("artifact_ref_status") or ""),
            "returned_exact": value.get("visible_exact") if isinstance(value.get("visible_exact"), bool) else None,
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
            "policy_ref": str(value.get("policy_ref") or "file_evidence_policy_stable.tool_result_evidence"),
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
    if dict(item.get("content_range") or {}):
        return ""
    if _is_authoritative_subagent_result(item):
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
    file_evidence_decisions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    files = [_task_progress_file_fact(item) for item in list(file_state or [])]
    todos = _task_progress_todo_facts(latest_results)
    recent_tool_observations = _task_progress_tool_observations(latest_results)
    return drop_empty(
        {
            "authority": "harness.runtime.dynamic_context.task_progress_facts",
            "files": [item for item in files if item][-12:],
            "file_evidence": _task_progress_file_evidence_facts(dict(file_evidence_decisions or {})),
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
                        "reusable_result_ref": str(segment.get("reusable_result_ref") or ""),
                        "exact_artifact_ref": str(segment.get("exact_artifact_ref") or ""),
                        "returned_exact": segment.get("visible_exact") if isinstance(segment.get("visible_exact"), bool) else None,
                    }
                )
                for segment in dict_tuple(item.get("read_ranges"))[-8:]
            ],
        }
    )


def _task_progress_file_evidence_facts(file_evidence_decisions: dict[str, Any]) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    for item in dict_tuple(file_evidence_decisions.get("files")):
        files.append(
            drop_empty(
                {
                    "path": str(item.get("path") or ""),
                    "visible_exact_window_count": len(dict_tuple(item.get("visible_exact_windows"))),
                    "artifact_available_window_count": len(dict_tuple(item.get("artifact_available_windows"))),
                    "artifact_injection_required_window_count": len(dict_tuple(item.get("artifact_injection_required_windows"))),
                    "missing_window_count": len(dict_tuple(item.get("read_missing_windows"))),
                    "stale_window_count": len(dict_tuple(item.get("read_after_stale_windows"))),
                }
            )
        )
    return drop_empty(
        {
            "authority": str(file_evidence_decisions.get("authority") or ""),
            "files": [item for item in files if item][-8:],
        }
    )


def _file_reusable_result_ref(item: dict[str, Any]) -> str:
    for segment in reversed(dict_tuple(item.get("read_ranges"))):
        for key in ("exact_artifact_ref", "reusable_result_ref"):
            value = str(segment.get(key) or "").strip()
            if value.startswith("read_observation:"):
                return value
    return ""


def _task_progress_todo_facts(latest_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest_plan: dict[str, Any] = {}
    for item in latest_results:
        if _tool_name(str(item.get("tool_name") or "")) != "agent_todo":
            continue
        plan = project_todo_plan(dict(item.get("todo_plan") or {}))
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
                    "todo_id": todo_id,
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


def _authoritative_subagent_results_projection(value: Any) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for item in dict_tuple(value):
        subagent_result = _subagent_result_projection(dict(item.get("subagent_result") or {}), include_final_answer=True)
        if not subagent_result:
            continue
        results.append(
            drop_empty(
                {
                    "observation_ref": str(item.get("observation_ref") or item.get("observation_id") or ""),
                    "tool_name": _tool_name(str(item.get("tool_name") or "collect_subagent_result")),
                    "status": str(item.get("status") or ""),
                    "visibility": str(item.get("visibility") or ""),
                    "summary": compact_text(
                        subagent_result.get("summary") or item.get("summary") or "",
                        limit=300,
                    ),
                    "subagent_result": subagent_result,
                    "event_offset": item.get("event_offset"),
                    "observation_event_offset": item.get("observation_event_offset"),
                    "action_event_offset": item.get("action_event_offset"),
                    "sequence": item.get("sequence"),
                    "step_index": item.get("step_index"),
                    "invocation_index": item.get("invocation_index"),
                    "created_at": item.get("created_at"),
                    "authority": "harness.runtime.dynamic_context.authoritative_subagent_result",
                }
            )
        )
    return _dedupe_by_semantic(results)[-4:]


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
        "batch_edit_file",
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
    authoritative_subagent_results: list[dict[str, Any]],
    current_fact_keys: set[str],
    current_todo_plan: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for item in authoritative_subagent_results:
        results.append(dict(item))
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
                    "todo_plan": project_todo_plan(dict(item.get("todo_plan") or {})),
                    "code_structure": dict(item.get("code_structure") or {}),
                    "content_range": dict(item.get("content_range") or {}),
                    "evidence_policy": _replay_evidence_policy(dict(item.get("evidence_policy") or {})),
                    "evidence_confidence": _replay_evidence_confidence(dict(item.get("evidence_confidence") or {})),
                    "preview": _code_evidence_preview(item),
                    "subagent_result": _subagent_result_projection(dict(item.get("subagent_result") or {}), include_final_answer=True),
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
    current_todo_result = _current_todo_result_projection(dict(current_todo_plan or {}))
    if current_todo_result:
        results.append(current_todo_result)
    deduped = _dedupe_by_semantic([item for item in results if item])
    return [item for item in deduped if _should_keep_latest_result(item, current_fact_keys=current_fact_keys)]


def _current_todo_result_projection(current_todo_plan: dict[str, Any]) -> dict[str, Any]:
    plan = project_todo_plan(current_todo_plan)
    if not plan:
        return {}
    plan_id = str(plan.get("plan_id") or "").strip()
    return drop_empty(
        {
            "observation_ref": f"agent_todo_state:{plan_id}" if plan_id else "agent_todo_state:current",
            "tool_name": "agent_todo",
            "status": "ok",
            "visibility": "active",
            "summary": "Current task todo plan.",
            "todo_plan": plan,
            "current_runtime_fact": True,
            "authority": "harness.runtime.dynamic_context.current_todo_state_projection",
        }
    )


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
            "execution_control": dict(item.get("execution_control") or tool_result.get("execution_control") or {}),
            "projection_integrity_errors": list(item.get("projection_integrity_errors") or tool_result.get("projection_integrity_errors") or []),
            "structured_error": structured_error,
            "artifact_refs": list(dict_tuple(item.get("artifact_refs") or tool_result.get("artifact_refs"))),
            "todo_plan": project_todo_plan(dict(item.get("todo_plan") or tool_result.get("todo_plan") or {})),
            "code_structure": dict(item.get("code_structure") or tool_result.get("code_structure") or {}),
            "content_range": dict(item.get("content_range") or tool_result.get("content_range") or {}),
            "evidence_policy": _replay_evidence_policy(dict(item.get("evidence_policy") or tool_result.get("evidence_policy") or {})),
            "evidence_confidence": _replay_evidence_confidence(dict(item.get("evidence_confidence") or tool_result.get("evidence_confidence") or {})),
            "preview": _code_evidence_preview(tool_result),
            "subagent_result": _subagent_result_projection(dict(item.get("subagent_result") or tool_result.get("subagent_result") or {}), include_final_answer=True),
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
    if set(projected).issubset({"observation_ref"}):
        return {}
    return projected


def _should_keep_latest_result(item: dict[str, Any], *, current_fact_keys: set[str]) -> bool:
    if _is_authoritative_subagent_result(item):
        return True
    key = _semantic_projection_key(item)
    if key not in current_fact_keys:
        return True
    evidence_policy = dict(item.get("evidence_policy") or {})
    if not str(evidence_policy.get("source_kind") or "").startswith("code_"):
        return False
    return bool(item.get("preview") or item.get("code_structure"))


def _is_authoritative_subagent_result(item: dict[str, Any]) -> bool:
    if _tool_name(str(item.get("tool_name") or item.get("source") or "")) != "collect_subagent_result":
        return False
    subagent_result = dict(item.get("subagent_result") or {})
    return bool(
        str(subagent_result.get("final_answer") or "").strip()
        or str(subagent_result.get("summary") or "").strip()
        or str(subagent_result.get("result_ref") or "").strip()
    )


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
    subagent_result = dict(item.get("subagent_result") or {})
    if tool_name == "collect_subagent_result" and subagent_result:
        result_ref = str(subagent_result.get("result_ref") or "").strip()
        subagent_run_ref = str(subagent_result.get("subagent_run_ref") or "").strip()
        if result_ref or subagent_run_ref:
            return f"subagent-result:{subagent_run_ref}:{result_ref}"
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
                "exact_coverage": dict(item.get("exact_coverage") or {}),
                "total_lines": item.get("total_lines"),
                "content_sha256": str(item.get("content_sha256") or ""),
                "mtime_ns": item.get("mtime_ns"),
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
    if isinstance(segment.get("has_more"), bool):
        payload["has_more"] = segment.get("has_more")
    if segment.get("mtime_ns") not in (None, ""):
        payload["mtime_ns"] = segment.get("mtime_ns")
    if segment.get("next_start_line") not in (None, ""):
        payload["next_start_line"] = segment.get("next_start_line")
    reusable_ref = str(segment.get("reusable_result_ref") or "")
    if reusable_ref:
        payload["reusable_result_ref"] = reusable_ref
    exact_artifact_ref = str(segment.get("exact_artifact_ref") or "")
    if exact_artifact_ref:
        payload["exact_artifact_ref"] = exact_artifact_ref
    artifact_ref_status = str(segment.get("artifact_ref_status") or "")
    if artifact_ref_status:
        payload["artifact_ref_status"] = artifact_ref_status
    if isinstance(segment.get("visible_exact"), bool):
        payload["returned_exact"] = segment.get("visible_exact")
    source = str(segment.get("source") or "")
    if source:
        payload["source"] = source
    if isinstance(segment.get("truncated"), bool):
        payload["truncated"] = segment.get("truncated")
    if isinstance(segment.get("stale"), bool):
        payload["stale"] = segment.get("stale")
    return payload


def _file_evidence_decisions_projection(file_state: list[dict[str, Any]]) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    for item in list(file_state or []):
        path = str(item.get("path") or "").strip()
        if not path:
            continue
        status = str(item.get("status") or "").strip().lower()
        ranges = dict_tuple(item.get("read_ranges"))
        active_ranges = [segment for segment in ranges if not bool(segment.get("stale") is True) and status not in {"stale", "missing"}]
        exact_ranges = [segment for segment in active_ranges if _segment_exact_available(segment)]
        stale_ranges = [segment for segment in ranges if bool(segment.get("stale") is True) or status == "stale"]
        artifact_windows = [
            _inject_read_artifact_window_decision(path=path, segment=segment)
            for segment in exact_ranges
            if _segment_has_exact_artifact(segment)
        ]
        injection_required_windows = [window for window in artifact_windows if window]
        missing_windows = _read_missing_window_decisions(item, active_ranges=exact_ranges)
        stale_read_windows = [_read_after_stale_window_decision(path=path, segment=segment) for segment in stale_ranges]
        projected = drop_empty(
            {
                "path": path,
                "status": str(item.get("status") or ""),
                "content_sha256": str(item.get("content_sha256") or ""),
                "coverage": dict(item.get("coverage") or {}),
                "exact_coverage": dict(item.get("exact_coverage") or {}),
                "visible_exact_windows": [],
                "artifact_available_windows": [window for window in artifact_windows if window][-8:],
                "artifact_injection_required_windows": injection_required_windows[-8:],
                "inject_read_artifact_windows": injection_required_windows[-8:],
                "read_missing_windows": [window for window in missing_windows if window][-4:],
                "read_after_stale_windows": [window for window in stale_read_windows if window][-6:],
                "policy_ref": "file_evidence_policy_stable.read_window_admission",
                "authority": "runtime.memory.file_state_authority.evidence_decision_projection",
            }
        )
        if projected:
            files.append(projected)
    return drop_empty(
        {
            "kind": "file_evidence_decisions",
            "authority": "runtime.memory.file_state_authority.evidence_decision_projection",
            "files": files[-10:],
        }
    )


def _inject_read_artifact_window_decision(*, path: str, segment: dict[str, Any]) -> dict[str, Any]:
    artifact_ref = str(segment.get("exact_artifact_ref") or segment.get("reusable_result_ref") or "").strip()
    return drop_empty(
        {
            "decision": "inject_read_artifact",
            "path": path,
            "start_line": segment.get("start_line"),
            "end_line": segment.get("end_line"),
            "observation_ref": str(segment.get("observation_ref") or ""),
            "exact_artifact_ref": artifact_ref,
            "decision_code": "inject_exact_read_observation_artifact",
        }
    )


def _segment_has_exact_artifact(segment: dict[str, Any]) -> bool:
    artifact_ref = str(segment.get("exact_artifact_ref") or segment.get("reusable_result_ref") or "").strip()
    if not artifact_ref.startswith("read_observation:"):
        return False
    artifact_status = str(segment.get("artifact_ref_status") or "").strip()
    return artifact_status in {"", "exact"}


def _segment_exact_available(segment: dict[str, Any]) -> bool:
    if bool(segment.get("stale") is True):
        return False
    return _segment_has_exact_artifact(segment)


def _read_missing_window_decisions(item: dict[str, Any], *, active_ranges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    status = str(item.get("status") or "").strip().lower()
    if status in {"stale", "missing"}:
        return []
    path = str(item.get("path") or "")
    coverage = dict(item.get("exact_coverage") or item.get("coverage") or {})
    if coverage.get("complete") is True:
        return []
    has_explicit_missing_ranges = "missing_ranges" in coverage
    missing = [dict(segment) for segment in list(coverage.get("missing_ranges") or []) if isinstance(segment, dict)]
    if not has_explicit_missing_ranges:
        missing = _missing_ranges_from_active_windows(active_ranges, total_lines=_safe_int(item.get("total_lines")))
    windows: list[dict[str, Any]] = []
    for segment in missing[:4]:
        start_line = _safe_int(segment.get("start_line"))
        end_line = _safe_int(segment.get("end_line"))
        if start_line <= 0:
            continue
        line_count = 500
        if end_line >= start_line:
            line_count = max(1, min(500, end_line - start_line + 1))
        windows.append(
            drop_empty(
                {
                    "decision": "read_missing_window",
                    "path": path,
                    "start_line": start_line,
                    "line_count": line_count,
                    "reason": "target may be outside current read coverage",
                }
            )
        )
    if windows or active_ranges or has_explicit_missing_ranges:
        return windows
    next_read = dict(item.get("next_suggested_read") or {})
    if not next_read:
        return []
    return [
        drop_empty(
            {
                "decision": "read_missing_window",
                "path": path,
                "start_line": next_read.get("start_line"),
                "line_count": next_read.get("line_count"),
                "reason": str(next_read.get("reason") or "no active current read window"),
            }
        )
    ]


def _missing_ranges_from_active_windows(active_ranges: list[dict[str, Any]], *, total_lines: int) -> list[dict[str, int]]:
    if total_lines <= 0 or not active_ranges:
        return []
    ranges: list[tuple[int, int]] = []
    for item in active_ranges:
        start_line = _safe_int(item.get("start_line"))
        end_line = _safe_int(item.get("end_line"))
        if start_line > 0 and end_line >= start_line:
            ranges.append((start_line, end_line))
    if not ranges:
        return []
    ranges.sort()
    merged: list[tuple[int, int]] = []
    for start_line, end_line in ranges:
        if not merged or start_line > merged[-1][1] + 1:
            merged.append((start_line, end_line))
            continue
        merged[-1] = (merged[-1][0], max(merged[-1][1], end_line))
    missing: list[dict[str, int]] = []
    cursor = 1
    for start_line, end_line in merged:
        if start_line > cursor:
            missing.append({"start_line": cursor, "end_line": min(start_line - 1, total_lines)})
        cursor = max(cursor, end_line + 1)
        if cursor > total_lines:
            break
    if cursor <= total_lines:
        missing.append({"start_line": cursor, "end_line": total_lines})
    return missing


def _read_after_stale_window_decision(*, path: str, segment: dict[str, Any]) -> dict[str, Any]:
    return drop_empty(
        {
            "decision": "read_after_stale",
            "path": path,
            "start_line": segment.get("start_line"),
            "end_line": segment.get("end_line"),
            "observation_ref": str(segment.get("observation_ref") or ""),
            "reason": "A later write/edit made this read window historical; read the minimal current target window if exact current content is needed.",
        }
    )


def _read_resource_state_projection(
    file_state: list[dict[str, Any]],
    *,
    file_evidence_decisions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    active_files = [
        item
        for item in list(file_state or [])
        if _has_current_read_resource(item)
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
                "available_evidence_refs": _read_resource_evidence_refs(stale_files, include_stale=True),
                "file_evidence_decision_ref": "file_evidence_decisions",
                "state_code": "stale_after_write_or_edit",
                "authority": "harness.runtime.dynamic_context.read_resource_state",
            }
        )
    active_ranges = [segment for item in active_files for segment in _current_read_ranges(item)]
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
                        "exact_coverage": dict(item.get("exact_coverage") or {}),
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
            "exact_coverage": dict(latest.get("exact_coverage") or {}),
            "has_more": latest.get("has_more") if isinstance(latest.get("has_more"), bool) else None,
            "content_sha256": str(latest.get("content_sha256") or ""),
            "file_evidence_decision_ref": "file_evidence_decisions",
            "state_code": "current_read_resource_available",
            "authority": "harness.runtime.dynamic_context.read_resource_state",
        }
    )


def _has_current_read_resource(item: dict[str, Any]) -> bool:
    status = str(item.get("status") or "").strip()
    if status in {"stale", "missing"}:
        return False
    if _current_read_ranges(item):
        return True
    coverage = dict(item.get("exact_coverage") or item.get("coverage") or {})
    return coverage.get("complete") is True and _safe_int(coverage.get("total_lines")) == 0


def _current_read_ranges(item: dict[str, Any]) -> list[dict[str, Any]]:
    ranges: list[dict[str, Any]] = []
    for segment in dict_tuple(item.get("read_ranges")):
        if segment.get("stale") is True:
            continue
        start = _safe_int(segment.get("start_line"))
        end = _safe_int(segment.get("end_line"))
        if start >= 1 and end >= start and _segment_exact_available(segment):
            ranges.append(segment)
    return ranges


def _read_resource_evidence_refs(file_state: list[dict[str, Any]], *, include_stale: bool = False) -> list[str]:
    refs: list[str] = []
    for item in list(file_state or []):
        if include_stale:
            for ref in list(item.get("evidence_refs") or []):
                text = str(ref or "").strip()
                if text and text not in refs:
                    refs.append(text)
        segments = dict_tuple(item.get("read_ranges")) if include_stale else _current_read_ranges(item)
        for segment in segments:
            for raw in (segment.get("exact_artifact_ref"), segment.get("observation_ref")):
                text = str(raw or "").strip()
                if text and text not in refs:
                    refs.append(text)
        coverage = dict(item.get("coverage") or {})
        if (
            not include_stale
            and not segments
            and coverage.get("complete") is True
            and _safe_int(coverage.get("total_lines")) == 0
        ):
            text = str(item.get("last_observation_ref") or "").strip()
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
            "open": value.get("open") if isinstance(value.get("open"), bool) else None,
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
                or tool_name in {"write_file", "edit_file", "batch_edit_file", "read_file", "search_text", "stat_path"}
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
