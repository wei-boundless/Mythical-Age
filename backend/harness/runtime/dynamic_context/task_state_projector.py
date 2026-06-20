from __future__ import annotations

import hashlib
import json
from typing import Any

from artifact_system.artifact_authority import artifact_ref_value, dedupe_artifact_refs, model_visible_artifact_refs
from runtime.shared.file_observation_policy import recommended_window_for_gap

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
    entries_by_key: dict[str, dict[str, Any]] = {}
    order_by_key: dict[str, tuple[int, int, str]] = {}
    fallback_order = 0
    for entry_kind, items in (
        ("subagent_result", dict_tuple(task_state.get("authoritative_subagent_results"))),
        ("tool_result", dict_tuple(task_state.get("latest_tool_results"))),
    ):
        for item in items:
            fallback_order += 1
            if _is_runtime_control_observation(item):
                continue
            entry = _replay_entry_projection(entry_kind, item)
            if not entry:
                continue
            key = _replay_entry_key(entry)
            order = _replay_entry_order(item, fallback_order=fallback_order)
            if key in entries_by_key:
                merged = _merge_projection(entries_by_key[key], entry)
                merged["entry_kind"] = _merged_entry_kind(entries_by_key[key].get("entry_kind"), entry.get("entry_kind"))
                entries_by_key[key] = merged
                order_by_key[key] = min(order_by_key[key], order)
                continue
            entries_by_key[key] = entry
            order_by_key[key] = order
    ordered_keys = sorted(
        entries_by_key,
        key=lambda key: order_by_key.get(key, (1, 0, key)),
    )
    entries = [entries_by_key[key] for key in ordered_keys]
    return _bounded_replay_entries(entries, limit=limit)


def _bounded_replay_entries(entries: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    bounded_limit = max(1, int(limit or 1))
    if len(entries) <= bounded_limit:
        return entries
    if bounded_limit == 1:
        return [_replay_summary_entry(entries, retained_prefix_entry_count=0, total_entry_count=len(entries))]
    retained = entries[: bounded_limit - 1]
    overflow = entries[bounded_limit - 1 :]
    return [
        *retained,
        _replay_summary_entry(
            overflow,
            retained_prefix_entry_count=len(retained),
            total_entry_count=len(entries),
        ),
    ]


def _replay_summary_entry(
    entries: list[dict[str, Any]],
    *,
    retained_prefix_entry_count: int,
    total_entry_count: int,
) -> dict[str, Any]:
    refs = [_entry_ref(entry) for entry in entries if _entry_ref(entry)]
    tool_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    for entry in entries:
        tool_name = str(entry.get("tool_name") or "").strip()
        status = str(entry.get("status") or "").strip()
        if tool_name:
            tool_counts[tool_name] = tool_counts.get(tool_name, 0) + 1
        if status:
            status_counts[status] = status_counts.get(status, 0) + 1
    seed = {
        "refs": refs,
        "tool_counts": tool_counts,
        "status_counts": status_counts,
        "retained_prefix_entry_count": retained_prefix_entry_count,
        "total_entry_count": total_entry_count,
    }
    digest = hashlib.sha256(
        json.dumps(seed, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    return drop_empty(
        {
            "entry_kind": "task_state_replay_summary",
            "entry_ref": f"task_state_replay_summary:{digest}",
            "summary_ref": f"task_state_replay_summary:{digest}",
            "retained_prefix_entry_count": retained_prefix_entry_count,
            "summarized_entry_count": len(entries),
            "total_entry_count": total_entry_count,
            "summarized_refs": refs[-24:],
            "tool_counts": tool_counts,
            "status_counts": status_counts,
            "replay_summary_policy": "prefix_preserved_summary_replacement",
            "rehydration": "older exact replay entries are summarized; use evidence refs or tools when exact detail is needed",
            "authority": "harness.runtime.dynamic_context.task_state_replay_summary",
        }
    )


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
    current_facts = dict_tuple(cursor.get("current_facts"))
    file_state = _cursor_file_state_projection(dict_tuple(cursor.get("file_state")))
    if file_state:
        cursor["file_state"] = file_state
    else:
        cursor.pop("file_state", None)
    if latest_results:
        latest_cursor_results = list(latest_results[-result_limit:])
        if replay_entries:
            cursor["latest_tool_results"] = _cursor_latest_tool_result_refs(latest_cursor_results)
        else:
            cursor["latest_tool_results"] = latest_cursor_results
    else:
        cursor.pop("latest_tool_results", None)
    cursor["current_facts"] = _cursor_current_facts_projection(
        current_facts,
        replay_entries=replay_entries,
    )
    if subagent_results:
        cursor["authoritative_subagent_results"] = [
            _cursor_tool_result_projection(item)
            for item in subagent_results[-4:]
        ]
    else:
        cursor.pop("authoritative_subagent_results", None)
    if active_failures:
        cursor["active_failures"] = [
            _cursor_failure_projection(item)
            for item in active_failures[-failure_limit:]
        ]
    else:
        cursor.pop("active_failures", None)
    cursor.pop("historical_failures", None)
    cursor.pop("pending_user_steers", None)
    cursor.pop("runtime_control_signals", None)
    cursor.pop("runtime_boundary", None)
    cursor["file_evidence_decisions"] = _cursor_file_evidence_decisions_projection(
        dict(cursor.get("file_evidence_decisions") or {})
    )
    cursor["task_progress_facts"] = _cursor_task_progress_facts_projection(
        dict(cursor.get("task_progress_facts") or {})
    )
    cursor["read_resource_state"] = _cursor_read_resource_state_projection(
        dict(cursor.get("read_resource_state") or {})
    )
    cursor["work_progress"] = _cursor_work_progress_projection(dict(cursor.get("work_progress") or {}))
    cursor["evidence_confidence"] = _cursor_evidence_confidence_projection(
        dict(cursor.get("evidence_confidence") or {})
    )
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


def _cursor_latest_tool_result_refs(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if not _result_succeeded(item):
            refs.append(_cursor_tool_result_projection(item))
            continue
        observation_ref = str(item.get("observation_ref") or item.get("observation_id") or "")
        refs.append(
            drop_empty(
                {
                    "observation_ref": observation_ref,
                    "tool_name": _tool_name(str(item.get("tool_name") or item.get("source") or "")),
                    "status": str(item.get("status") or ""),
                    "path": _projection_path(item),
                    "replay_ref": f"task_state_replay:{observation_ref}" if observation_ref else _semantic_projection_key(item),
                    "cursor_code": "details_available_in_task_state_replay",
                }
            )
        )
    return [item for item in refs if item]


def _cursor_current_facts_projection(
    items: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    replay_entries: tuple[dict[str, Any], ...],
) -> list[dict[str, Any]]:
    if not items:
        return []
    replay_observation_refs = {
        str(entry.get("observation_ref") or "").strip()
        for entry in replay_entries
        if str(entry.get("observation_ref") or "").strip()
    }
    replay_semantic_keys = {_semantic_projection_key(entry) for entry in replay_entries if _semantic_projection_key(entry)}
    projected: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        observation_ref = str(item.get("observation_ref") or item.get("observation_id") or "").strip()
        semantic_key = _semantic_projection_key(item)
        if observation_ref and observation_ref in replay_observation_refs:
            continue
        if semantic_key and semantic_key in replay_semantic_keys:
            continue
        fallback = _current_fact_projection([item])
        projected.append(fallback[0] if fallback else {})
    return [item for item in projected if item][-6:]


def _cursor_tool_result_projection(item: dict[str, Any]) -> dict[str, Any]:
    error = _dict_value(item.get("error")) or _dict_value(item.get("structured_error"))
    content_range = _replay_content_range(dict(item.get("content_range") or {}))
    summary_limit = 80 if content_range else 140
    summary = "" if content_range else compact_text(item.get("summary") or error.get("message") or "", limit=summary_limit)
    projected = drop_empty(
        {
            "observation_ref": str(item.get("observation_ref") or item.get("observation_id") or ""),
            "tool_name": _tool_name(str(item.get("tool_name") or item.get("source") or "")),
            "tool_call_id": str(item.get("tool_call_id") or ""),
            "status": str(item.get("status") or ""),
            "path": _projection_path(item),
            "reason": str(item.get("reason") or error.get("code") or ""),
            "summary": summary,
            "error": _cursor_error_projection(error),
            "structured_error": _cursor_error_projection(_dict_value(item.get("structured_error"))),
            "code_structure": _replay_code_structure_summary(dict(item.get("code_structure") or {})),
            "content_range": content_range,
            "evidence_policy": {}
            if content_range
            else _cursor_evidence_policy_projection(
                dict(item.get("evidence_policy") or {}),
                content_range=bool(content_range),
            ),
            "evidence_confidence": {}
            if content_range
            else _replay_evidence_confidence(dict(item.get("evidence_confidence") or {})),
            "subagent_result": _cursor_subagent_result_projection(dict(item.get("subagent_result") or {})),
            "rehydration_plan": {} if content_range else _replay_rehydration_plan(dict(item.get("rehydration_plan") or {})),
            "rehydration_action": "read_file_range_if_exact_needed" if content_range else "",
            "current_runtime_fact": item.get("current_runtime_fact") if isinstance(item.get("current_runtime_fact"), bool) else None,
        }
    )
    return projected


def _cursor_failure_projection(item: dict[str, Any]) -> dict[str, Any]:
    error = _dict_value(item.get("error")) or _dict_value(item.get("structured_error"))
    return drop_empty(
        {
            "observation_ref": str(item.get("observation_ref") or item.get("observation_id") or ""),
            "tool_name": _tool_name(str(item.get("tool_name") or item.get("source") or "")),
            "status": str(item.get("status") or "error"),
            "visibility": str(item.get("visibility") or ""),
            "reason": str(item.get("reason") or error.get("code") or ""),
            "summary": compact_text(item.get("summary") or error.get("message") or "", limit=180),
            "error": _cursor_error_projection(error),
            "current_runtime_fact": item.get("current_runtime_fact") if isinstance(item.get("current_runtime_fact"), bool) else None,
        }
    )


def _cursor_error_projection(error: dict[str, Any]) -> dict[str, Any]:
    if not error:
        return {}
    repair_instruction = str(error.get("repair_instruction") or "")
    return drop_empty(
        {
            "code": str(error.get("code") or ""),
            "origin": str(error.get("origin") or ""),
            "retryable": error.get("retryable") if isinstance(error.get("retryable"), bool) else None,
            "message": compact_text(error.get("message") or "", limit=220),
            "repair_instruction_summary": compact_text(repair_instruction, limit=260),
            "repair_instruction_available": True if repair_instruction else None,
        }
    )


def _cursor_evidence_policy_projection(value: dict[str, Any], *, content_range: bool) -> dict[str, Any]:
    if not value:
        return {}
    if content_range:
        return drop_empty(
            {
                "policy_ref": str(value.get("policy_ref") or "file_evidence_policy_stable.tool_result_evidence"),
                "source_kind": str(value.get("source_kind") or ""),
                "visible_content_authority": str(value.get("visible_content_authority") or ""),
            }
        )
    return _replay_evidence_policy(value)


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
            "code_structure": _replay_code_structure_summary(dict(item.get("code_structure") or {})),
            "content_range": _replay_content_range(dict(item.get("content_range") or {})),
            "evidence_policy": {}
            if _replay_content_range(dict(item.get("content_range") or {}))
            else _replay_evidence_policy(dict(item.get("evidence_policy") or {})),
            "evidence_confidence": {}
            if _replay_content_range(dict(item.get("content_range") or {}))
            else _replay_evidence_confidence(dict(item.get("evidence_confidence") or {})),
            "preview": _replay_preview(item),
            "subagent_result": _subagent_result_projection(dict(item.get("subagent_result") or {}), include_final_answer=True),
            "rehydration_plan": {}
            if _replay_content_range(dict(item.get("content_range") or {}))
            else _replay_rehydration_plan(dict(item.get("rehydration_plan") or {})),
            "rehydration_action": "read_file_range_if_exact_needed"
            if _replay_content_range(dict(item.get("content_range") or {}))
            else "",
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


def _is_runtime_control_observation(item: dict[str, Any]) -> bool:
    ref = str(item.get("observation_ref") or item.get("observation_id") or "").strip()
    if ref.startswith(("rtobs:", "runtime-control:")):
        return True
    if item.get("current_runtime_fact") is True:
        return True
    tool_name = _tool_name(str(item.get("tool_name") or item.get("source") or ""))
    if tool_name in {"runtime_control", "model_action_protocol", "action_protocol"}:
        return True
    error = _dict_value(item.get("error")) or _dict_value(item.get("structured_error"))
    code = str(error.get("code") or item.get("reason") or "").strip()
    origin = str(error.get("origin") or "").strip()
    return origin == "model_protocol" or code.startswith("model_action_")


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
    ref = str(entry.get("observation_ref") or entry.get("entry_ref") or "").strip()
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
    if not value:
        return {}
    payload = drop_empty(
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
    if set(payload) <= {"policy_ref"}:
        return {}
    return payload


def _replay_evidence_confidence(value: dict[str, Any]) -> dict[str, Any]:
    if not value:
        return {}
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
    payload = drop_empty(
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
    if set(payload) <= {"authority"}:
        return {}
    return payload


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
    recent_tool_observations = _task_progress_tool_observations(latest_results)
    return drop_empty(
        {
            "authority": "harness.runtime.dynamic_context.task_progress_facts",
            "files": [item for item in files if item][-8:],
            "file_evidence": _task_progress_file_evidence_facts(dict(file_evidence_decisions or {})),
            "recent_tool_observations": recent_tool_observations[-8:],
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
            "coverage": _thin_coverage_projection(coverage),
            "total_lines": item.get("total_lines"),
            "content_sha256": str(item.get("content_sha256") or ""),
            "stale": str(item.get("status") or "") == "stale",
            "has_more": item.get("has_more") if isinstance(item.get("has_more"), bool) else None,
            "last_observation_ref": str(item.get("last_observation_ref") or ""),
            "reusable_result_ref": reusable_ref,
            "next_missing_ranges": [_range_ref(segment) for segment in next_missing_ranges[:4]],
            "next_suggested_read": dict(item.get("next_suggested_read") or {}),
            "read_windows_available": [
                _file_state_cursor_read_window(segment)
                for segment in dict_tuple(item.get("read_ranges"))[-4:]
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
                    "reusable_evidence_count": len(dict_tuple(item.get("reusable_evidence"))),
                    "candidate_read_window_count": len(dict_tuple(item.get("candidate_read_windows"))),
                    "required_read_window_count": len(dict_tuple(item.get("required_read_windows"))),
                    "caution_count": len(dict_tuple(item.get("cautions"))),
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
        "list_dir",
        "path_exists",
        "glob_paths",
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
        content_range = _replay_content_range(dict(item.get("content_range") or {}))
        projected = drop_empty(
            {
                "observation_ref": str(item.get("observation_ref") or item.get("observation_id") or ""),
                "tool_name": _tool_name(str(item.get("tool_name") or item.get("source") or "")),
                "status": str(item.get("status") or ""),
                "path": _projection_path(item),
                "visibility": str(item.get("visibility") or ""),
                "reason": str(item.get("reason") or ""),
                "summary": "" if content_range else compact_text(item.get("summary") or "", limit=120),
                "content_range": content_range,
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
            "latest_progress": compact_text(work_history_projection.get("latest_progress") or "", limit=180),
            "latest_step_title": compact_text(work_history_projection.get("latest_step_title") or "", limit=120),
            "active_facts": [
                compact_text(item, limit=120)
                for item in list(work_history_projection.get("active_facts") or [])[-3:]
                if str(item)
            ],
            "historical_work_summary": _cursor_historical_work_summary(
                dict(work_history_projection.get("historical_work_summary") or {})
            ),
            "recent_steps": [
                drop_empty(
                    {
                        "type": str(item.get("type") or ""),
                        "title": compact_text(item.get("title") or "", limit=120),
                        "status": str(item.get("status") or ""),
                        "summary": compact_text(item.get("summary") or "", limit=140),
                    }
                )
                for item in dict_tuple(work_history_projection.get("recent_steps"))[-1:]
            ],
        }
    )


def _cursor_historical_work_summary(value: dict[str, Any]) -> dict[str, Any]:
    return drop_empty(
        {
            "status": str(value.get("status") or ""),
            "public_result_summary": compact_text(value.get("public_result_summary") or "", limit=160),
            "usable_artifact_refs": _replay_artifact_refs(value.get("usable_artifact_refs")),
            "non_control_context": value.get("non_control_context") if isinstance(value.get("non_control_context"), bool) else None,
        }
    )


def _cursor_work_progress_projection(value: dict[str, Any]) -> dict[str, Any]:
    if not value:
        return {}
    return drop_empty(
        {
            "latest_progress": compact_text(value.get("latest_progress") or "", limit=140),
            "latest_step_title": compact_text(value.get("latest_step_title") or "", limit=100),
            "active_facts": [
                compact_text(item, limit=100)
                for item in list(value.get("active_facts") or [])[-2:]
                if str(item).strip()
            ],
            "historical_work_summary": _cursor_historical_work_summary(
                dict(value.get("historical_work_summary") or {})
            ),
            "recent_steps": [
                drop_empty(
                    {
                        "type": str(item.get("type") or ""),
                        "title": compact_text(item.get("title") or "", limit=100),
                        "status": str(item.get("status") or ""),
                        "summary": compact_text(item.get("summary") or "", limit=120),
                    }
                )
                for item in dict_tuple(value.get("recent_steps"))[-1:]
            ],
        }
    )


def _cursor_file_evidence_decisions_projection(value: dict[str, Any]) -> dict[str, Any]:
    if not value:
        return {}
    files: list[dict[str, Any]] = []
    for item in dict_tuple(value.get("files"))[-8:]:
        files.append(
            drop_empty(
                {
                    "path": str(item.get("path") or ""),
                    "status": str(item.get("status") or ""),
                    "facts": _cursor_file_evidence_facts(dict(item.get("facts") or {})),
                    "reusable_evidence_count": len(dict_tuple(item.get("reusable_evidence"))),
                    "reusable_evidence": _cursor_evidence_windows(item.get("reusable_evidence")),
                    "candidate_read_window_count": len(dict_tuple(item.get("candidate_read_windows"))),
                    "candidate_read_windows": _cursor_decision_windows(item.get("candidate_read_windows")),
                    "required_read_window_count": len(dict_tuple(item.get("required_read_windows"))),
                    "required_read_windows": _cursor_decision_windows(item.get("required_read_windows")),
                    "caution_count": len(dict_tuple(item.get("cautions"))),
                    "cautions": _cursor_caution_windows(item.get("cautions")),
                    "policy_ref": str(item.get("policy_ref") or ""),
                }
            )
        )
    return drop_empty(
        {
            "kind": str(value.get("kind") or "file_evidence_contract"),
            "contract_version": str(value.get("contract_version") or ""),
            "authority_boundary": str(value.get("authority_boundary") or ""),
            "authority": str(value.get("authority") or "runtime.memory.file_state_authority.evidence_decision_projection"),
            "files": [item for item in files if item],
        }
    )


def _cursor_file_evidence_facts(value: dict[str, Any]) -> dict[str, Any]:
    return drop_empty(
        {
            "coverage": _thin_coverage_projection(dict(value.get("coverage") or {})),
            "exact_coverage": _thin_coverage_projection(dict(value.get("exact_coverage") or {})),
            "current_exact_window_available": (
                value.get("current_exact_window_available")
                if isinstance(value.get("current_exact_window_available"), bool)
                else None
            ),
            "stale_window_available": (
                value.get("stale_window_available")
                if isinstance(value.get("stale_window_available"), bool)
                else None
            ),
        }
    )


def _cursor_evidence_windows(value: Any) -> list[dict[str, Any]]:
    windows: list[dict[str, Any]] = []
    for item in dict_tuple(value)[-3:]:
        windows.append(
            drop_empty(
                {
                    "evidence_kind": str(item.get("evidence_kind") or ""),
                    "path": str(item.get("path") or ""),
                    "start_line": item.get("start_line"),
                    "end_line": item.get("end_line"),
                    "observation_ref": str(item.get("observation_ref") or ""),
                    "exact_artifact_ref": str(item.get("exact_artifact_ref") or ""),
                    "usage_condition": compact_text(item.get("usage_condition") or "", limit=120),
                }
            )
        )
    return [item for item in windows if item]


def _cursor_decision_windows(value: Any) -> list[dict[str, Any]]:
    windows: list[dict[str, Any]] = []
    for item in dict_tuple(value)[-3:]:
        windows.append(
            drop_empty(
                {
                    "candidate_kind": str(item.get("candidate_kind") or ""),
                    "requirement_kind": str(item.get("requirement_kind") or ""),
                    "decision": str(item.get("decision") or ""),
                    "path": str(item.get("path") or ""),
                    "start_line": item.get("start_line"),
                    "end_line": item.get("end_line"),
                    "line_count": item.get("line_count"),
                    "match_line": item.get("match_line"),
                    "query": compact_text(item.get("query") or "", limit=80),
                    "observation_ref": str(item.get("observation_ref") or ""),
                    "source_observation_ref": str(item.get("source_observation_ref") or ""),
                    "exact_artifact_ref": str(item.get("exact_artifact_ref") or ""),
                    "read_condition": compact_text(item.get("read_condition") or "", limit=120),
                    "reason": compact_text(item.get("reason") or "", limit=120),
                }
            )
        )
    return [item for item in windows if item]


def _cursor_caution_windows(value: Any) -> list[dict[str, Any]]:
    cautions: list[dict[str, Any]] = []
    for item in dict_tuple(value)[-3:]:
        cautions.append(
            drop_empty(
                {
                    "caution_kind": str(item.get("caution_kind") or ""),
                    "path": str(item.get("path") or ""),
                    "start_line": item.get("start_line"),
                    "end_line": item.get("end_line"),
                    "read_condition": compact_text(item.get("read_condition") or "", limit=120),
                    "reason": compact_text(item.get("reason") or "", limit=120),
                }
            )
        )
    return [item for item in cautions if item]


def _cursor_task_progress_facts_projection(value: dict[str, Any]) -> dict[str, Any]:
    if not value:
        return {}
    raw_observations = dict_tuple(value.get("recent_tool_observations"))
    context_observations = [
        item
        for item in raw_observations
        if isinstance(item, dict) and item.get("trace_only") is True
    ]
    observations = [
        drop_empty(
            {
                "tool_name": str(item.get("tool_name") or ""),
                "outcome": str(item.get("outcome") or ""),
                "observation_ref": str(item.get("observation_ref") or ""),
                "trace_only": item.get("trace_only") if isinstance(item.get("trace_only"), bool) else None,
                "reason": str(item.get("reason") or ""),
            }
        )
        for item in raw_observations[-6:]
        if item.get("trace_only") is not True
    ]
    observations = [item for item in observations if item]
    latest_context_observation = context_observations[-1] if context_observations else {}
    return drop_empty(
        {
            "authority": str(value.get("authority") or "harness.runtime.dynamic_context.task_progress_facts"),
            "file_evidence": dict(value.get("file_evidence") or {}),
            "recent_tool_observation_refs": observations,
            "context_observation_count": len(context_observations) or None,
            "latest_context_observation_ref": str(latest_context_observation.get("observation_ref") or ""),
        }
    )


def _cursor_read_resource_state_projection(value: dict[str, Any]) -> dict[str, Any]:
    if not value:
        return {}
    return drop_empty(
        {
            "kind": str(value.get("kind") or "read_resource_state"),
            "authority_boundary": str(value.get("authority_boundary") or ""),
            "status": str(value.get("status") or ""),
            "path": str(value.get("path") or ""),
            "active_file_count": value.get("active_file_count"),
            "available_range_count": value.get("available_range_count"),
            "available_evidence_refs": [
                str(item)
                for item in list(value.get("available_evidence_refs") or [])[-10:]
                if str(item).strip()
            ],
            "content_sha256": str(value.get("content_sha256") or ""),
            "file_evidence_decision_ref": str(value.get("file_evidence_decision_ref") or ""),
            "state_code": str(value.get("state_code") or ""),
            "reuse_feedback": dict(value.get("reuse_feedback") or {}),
            "collection_feedback": dict(value.get("collection_feedback") or {}),
            "action_conditions": [
                compact_text(item, limit=120)
                for item in list(value.get("action_conditions") or [])[-4:]
                if str(item).strip()
            ],
            "candidate_read_windows": _cursor_decision_windows(value.get("candidate_read_windows")),
            "authority": str(value.get("authority") or "harness.runtime.dynamic_context.read_resource_state"),
        }
    )


def _cursor_evidence_confidence_projection(value: dict[str, Any]) -> dict[str, Any]:
    if not value:
        return {}
    return drop_empty(
        {
            "authority": str(value.get("authority") or "harness.runtime.dynamic_context.evidence_confidence"),
            "files": [
                drop_empty(
                    {
                        "path": str(item.get("path") or ""),
                        "start_line": item.get("start_line"),
                        "end_line": item.get("end_line"),
                        "content_sha256": str(item.get("content_sha256") or ""),
                    }
                )
                for item in dict_tuple(value.get("files"))[-8:]
            ],
            "locator_result_count": value.get("locator_result_count"),
        }
    )


def _cursor_file_state_projection(items: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict) or _low_value_file_state_cursor_item(item):
            continue
        result.append(_file_state_cursor_item_projection(item))
    return result[-5:]


def _low_value_file_state_cursor_item(item: dict[str, Any]) -> bool:
    if dict_tuple(item.get("read_ranges")):
        return False
    if dict_tuple(item.get("read_recommendations")) or dict_tuple(item.get("recommended_read_windows")):
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


def _file_state_cursor_item_projection(item: dict[str, Any]) -> dict[str, Any]:
    coverage = dict(item.get("coverage") or {})
    ranges = [
        _file_state_cursor_read_window(segment)
        for segment in dict_tuple(item.get("read_ranges"))
        if segment.get("start_line") not in (None, "") and segment.get("end_line") not in (None, "")
    ]
    return drop_empty(
        {
            "path": _projection_path(item) or str(item.get("path") or ""),
            "status": str(item.get("status") or ""),
            "coverage": _file_state_coverage_summary(coverage),
            "total_lines": item.get("total_lines"),
            "content_sha256": str(item.get("content_sha256") or ""),
            "has_more": item.get("has_more") if isinstance(item.get("has_more"), bool) else None,
            "last_observation_ref": str(item.get("last_observation_ref") or ""),
            "next_suggested_read": _read_request_ref(dict(item.get("next_suggested_read") or {})),
            "recommended_read_windows": _cursor_decision_windows(item.get("recommended_read_windows")),
            "read_recommendation_count": len(dict_tuple(item.get("read_recommendations"))),
            "read_window_refs": ranges[-4:],
            "evidence_refs": _dedupe_strings(
                str(ref)
                for ref in list(item.get("evidence_refs") or [])
                if str(ref or "").strip()
            )[-4:],
        }
    )


def _file_state_cursor_read_window(segment: dict[str, Any]) -> dict[str, Any]:
    return drop_empty(
        {
            "start_line": segment.get("start_line"),
            "end_line": segment.get("end_line"),
            "observation_ref": str(segment.get("observation_ref") or ""),
            "reusable_result_ref": str(segment.get("reusable_result_ref") or ""),
            "exact_artifact_ref": str(segment.get("exact_artifact_ref") or ""),
            "artifact_ref_status": str(segment.get("artifact_ref_status") or ""),
            "content_sha256": str(segment.get("content_sha256") or ""),
            "text_sha256": str(segment.get("text_sha256") or ""),
            "returned_exact": segment.get("returned_exact") if isinstance(segment.get("returned_exact"), bool) else None,
            "stale": segment.get("stale") if isinstance(segment.get("stale"), bool) else None,
        }
    )


def _thin_coverage_projection(coverage: dict[str, Any]) -> dict[str, Any]:
    if not coverage:
        return {}
    covered_ranges = [
        dict(item)
        for item in list(coverage.get("covered_ranges") or coverage.get("merged_ranges") or [])
        if isinstance(item, dict)
    ]
    missing_ranges = [
        dict(item)
        for item in list(coverage.get("missing_ranges") or [])
        if isinstance(item, dict)
    ]
    return drop_empty(
        {
            "complete": coverage.get("complete") if isinstance(coverage.get("complete"), bool) else None,
            "start_line": coverage.get("start_line"),
            "end_line": coverage.get("end_line"),
            "total_lines": coverage.get("total_lines"),
            "covered_lines": coverage.get("covered_lines"),
            "covered_ranges": [_range_ref(item) for item in covered_ranges[-3:]],
            "missing_ranges": [_range_ref(item) for item in missing_ranges[:3]],
            "covered_range_count": _safe_int(coverage.get("range_count")) or len(covered_ranges),
            "missing_range_count": len(missing_ranges),
        }
    )


def _file_state_coverage_summary(coverage: dict[str, Any]) -> dict[str, Any]:
    if not coverage:
        return {}
    return drop_empty(
        {
            "complete": coverage.get("complete") if isinstance(coverage.get("complete"), bool) else None,
            "total_lines": coverage.get("total_lines"),
            "covered_lines": coverage.get("covered_lines"),
            "covered_range_count": _safe_int(coverage.get("range_count"))
            or len(list(coverage.get("covered_ranges") or coverage.get("merged_ranges") or [])),
            "missing_range_count": len(list(coverage.get("missing_ranges") or [])),
        }
    )


def _range_ref(value: dict[str, Any]) -> dict[str, Any]:
    return drop_empty(
        {
            "start_line": value.get("start_line"),
            "end_line": value.get("end_line"),
            "line_count": value.get("line_count"),
        }
    )


def _read_request_ref(value: dict[str, Any]) -> dict[str, Any]:
    return drop_empty(
        {
            "path": _projection_path(value),
            "start_line": value.get("start_line"),
            "line_count": value.get("line_count"),
            "reason": compact_text(value.get("reason") or "", limit=120),
        }
    )


def _dedupe_strings(values: Any) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return result


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
        projected = drop_empty(
            {
                "path": path,
                "read_ranges": ranges[-6:],
                "read_recommendations": _file_state_read_recommendations_projection(item.get("read_recommendations")),
                "recommended_read_windows": _file_state_recommended_windows_projection(item.get("recommended_read_windows")),
                "coverage": dict(item.get("coverage") or {}),
                "exact_coverage": dict(item.get("exact_coverage") or {}),
                "total_lines": item.get("total_lines"),
                "content_sha256": str(item.get("content_sha256") or ""),
                "mtime_ns": item.get("mtime_ns"),
                "last_observation_ref": str(item.get("last_observation_ref") or ""),
                "has_more": item.get("has_more") if isinstance(item.get("has_more"), bool) else None,
                "status": str(item.get("status") or ""),
                "stale_reason": compact_text(item.get("stale_reason") or "", limit=180),
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


def _file_state_read_recommendations_projection(value: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in dict_tuple(value)[-12:]:
        result.append(
            drop_empty(
                {
                    "start_line": item.get("start_line"),
                    "line_count": item.get("line_count"),
                    "match_line": item.get("match_line"),
                    "query": compact_text(item.get("query") or "", limit=120),
                    "status": str(item.get("status") or ""),
                    "reason": compact_text(item.get("reason") or "", limit=160),
                    "observation_ref": str(item.get("observation_ref") or ""),
                    "tool_call_id": str(item.get("tool_call_id") or ""),
                }
            )
        )
    return [item for item in result if item]


def _file_state_recommended_windows_projection(value: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in dict_tuple(value)[-8:]:
        result.append(
            drop_empty(
                {
                    "decision": str(item.get("decision") or "read_search_recommendation"),
                    "path": str(item.get("path") or ""),
                    "start_line": item.get("start_line"),
                    "line_count": item.get("line_count"),
                    "match_line": item.get("match_line"),
                    "query": compact_text(item.get("query") or "", limit=120),
                    "reason": compact_text(item.get("reason") or "", limit=160),
                    "source_observation_ref": str(item.get("source_observation_ref") or item.get("observation_ref") or ""),
                    "tool_call_id": str(item.get("tool_call_id") or ""),
                    "status": str(item.get("status") or ""),
                }
            )
        )
    return [item for item in result if item]


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
    text_sha256 = str(segment.get("text_sha256") or "")
    if text_sha256:
        payload["text_sha256"] = text_sha256
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
            _exact_artifact_window_decision(path=path, segment=segment)
            for segment in exact_ranges
            if _segment_has_exact_artifact(segment)
        ]
        reuse_windows = [_reuse_current_window_decision(path=path, segment=segment) for segment in exact_ranges]
        recommended_windows = _recommended_read_window_decisions(item)
        missing_windows = _read_missing_window_decisions(item, active_ranges=exact_ranges)
        stale_read_windows = [_read_after_stale_window_decision(path=path, segment=segment) for segment in stale_ranges]
        cautions = [
            *_partial_coverage_cautions(item, active_ranges=exact_ranges),
            *[window for window in stale_read_windows if window],
        ]
        projected = drop_empty(
            {
                "path": path,
                "status": str(item.get("status") or ""),
                "facts": _file_evidence_facts(
                    item,
                    exact_ranges=exact_ranges,
                    stale_ranges=stale_ranges,
                    recommended_windows=recommended_windows,
                    required_windows=missing_windows,
                ),
                "reusable_evidence": [window for window in [*artifact_windows, *reuse_windows] if window][-8:],
                "candidate_read_windows": [window for window in recommended_windows if window][-6:],
                "required_read_windows": [window for window in missing_windows if window][-4:],
                "cautions": [window for window in cautions if window][-8:],
                "policy_ref": "file_evidence_policy_stable.read_window_contract",
                "authority": "runtime.memory.file_state_authority.file_evidence_contract_projection",
            }
        )
        if projected:
            files.append(projected)
    return drop_empty(
        {
            "kind": "file_evidence_contract",
            "contract_version": "file_evidence_contract.v2",
            "authority_boundary": "observation_projection_only",
            "policy": {
                "agent_decides_next_read": True,
                "system_role": "facts_candidates_requirements_only",
                "ordinary_partial_read": "coverage_fact_not_continuation_request",
            },
            "authority": "runtime.memory.file_state_authority.file_evidence_contract_projection",
            "files": files[-10:],
        }
    )


def _file_evidence_facts(
    item: dict[str, Any],
    *,
    exact_ranges: list[dict[str, Any]],
    stale_ranges: list[dict[str, Any]],
    recommended_windows: list[dict[str, Any]],
    required_windows: list[dict[str, Any]],
) -> dict[str, Any]:
    coverage = dict(item.get("coverage") or {})
    exact_coverage = dict(item.get("exact_coverage") or {})
    return drop_empty(
        {
            "resource_status": str(item.get("status") or ""),
            "content_sha256": str(item.get("content_sha256") or ""),
            "total_lines": item.get("total_lines"),
            "coverage": _thin_coverage_projection(coverage),
            "exact_coverage": _thin_coverage_projection(exact_coverage),
            "current_exact_window_available": bool(exact_ranges),
            "candidate_read_window_available": bool(recommended_windows),
            "required_read_window_available": bool(required_windows),
            "stale_window_available": bool(stale_ranges),
            "coverage_complete": (
                coverage.get("complete")
                if isinstance(coverage.get("complete"), bool)
                else None
            ),
        }
    )


def _exact_artifact_window_decision(*, path: str, segment: dict[str, Any]) -> dict[str, Any]:
    artifact_ref = str(segment.get("exact_artifact_ref") or segment.get("reusable_result_ref") or "").strip()
    return drop_empty(
        {
            "evidence_kind": "exact_read_artifact_available",
            "path": path,
            "start_line": segment.get("start_line"),
            "end_line": segment.get("end_line"),
            "observation_ref": str(segment.get("observation_ref") or ""),
            "exact_artifact_ref": artifact_ref,
            "usage_condition": "reuse this exact artifact when the unchanged target range is inside this window",
        }
    )


def _reuse_current_window_decision(*, path: str, segment: dict[str, Any]) -> dict[str, Any]:
    return drop_empty(
        {
            "evidence_kind": "current_exact_read_window",
            "path": path,
            "start_line": segment.get("start_line"),
            "end_line": segment.get("end_line"),
            "observation_ref": str(segment.get("observation_ref") or ""),
            "exact_artifact_ref": str(segment.get("exact_artifact_ref") or segment.get("reusable_result_ref") or ""),
            "usage_condition": "reuse when the target is inside this current exact range",
        }
    )


def _recommended_read_window_decisions(item: dict[str, Any]) -> list[dict[str, Any]]:
    windows: list[dict[str, Any]] = []
    path = str(item.get("path") or "")
    for raw in dict_tuple(item.get("recommended_read_windows")) or dict_tuple(item.get("read_recommendations")):
        status = str(raw.get("status") or "pending").strip()
        if status and status != "pending":
            continue
        windows.append(
            drop_empty(
                {
                    "candidate_kind": "search_match_context_window",
                    "path": str(raw.get("path") or path),
                    "start_line": raw.get("start_line"),
                    "line_count": raw.get("line_count"),
                    "match_line": raw.get("match_line"),
                    "query": compact_text(raw.get("query") or "", limit=120),
                    "source_observation_ref": str(raw.get("source_observation_ref") or raw.get("observation_ref") or ""),
                    "tool_call_id": str(raw.get("tool_call_id") or ""),
                    "read_condition": "read this candidate only if exact current source around the search match is needed",
                    "reason": compact_text(raw.get("reason") or "search match recommendation", limit=180),
                }
            )
        )
    return [item for item in windows if item]


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
    if not _missing_window_read_is_required(item=item, coverage=coverage):
        return []
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
        policy_window = recommended_window_for_gap(
            start_line=start_line,
            end_line=end_line if end_line >= start_line else None,
            total_lines=_safe_int(item.get("total_lines")) or None,
            reason="target may be outside current read coverage",
        )
        windows.append(
            drop_empty(
                {
                    "requirement_kind": "target_outside_current_coverage",
                    "path": path,
                    "start_line": policy_window.get("start_line"),
                    "line_count": policy_window.get("line_count"),
                    "read_condition": "required only for the explicit target range outside current exact coverage",
                    "reason": str(policy_window.get("reason") or "target may be outside current read coverage"),
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
                "requirement_kind": "target_outside_current_coverage",
                "path": path,
                "start_line": next_read.get("start_line"),
                "line_count": next_read.get("line_count"),
                "read_condition": "required only when no active current read resource covers the explicit target",
                "reason": str(next_read.get("reason") or "no active current read window"),
            }
        )
    ]


def _missing_window_read_is_required(*, item: dict[str, Any], coverage: dict[str, Any]) -> bool:
    for payload in (item, coverage):
        for key in (
            "missing_window_read_required",
            "read_missing_required",
            "requires_missing_window_read",
            "requires_full_coverage",
            "target_line_outside_coverage",
        ):
            if payload.get(key) is True:
                return True
    return False


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
            "caution_kind": "stale_read_window",
            "path": path,
            "start_line": segment.get("start_line"),
            "end_line": segment.get("end_line"),
            "observation_ref": str(segment.get("observation_ref") or ""),
            "read_condition": "read the minimal current target window if exact current content is needed",
            "reason": "A later write/edit made this read window historical; read the minimal current target window if exact current content is needed.",
        }
    )


def _partial_coverage_cautions(item: dict[str, Any], *, active_ranges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    coverage = dict(item.get("exact_coverage") or item.get("coverage") or {})
    if not active_ranges:
        return []
    if coverage.get("complete") is True:
        return []
    return [
        drop_empty(
            {
                "caution_kind": "partial_coverage_fact",
                "path": str(item.get("path") or ""),
                "reason": "Current exact evidence covers only the listed ranges; this is not a request to continue reading.",
                "read_condition": "read another window only for a target outside coverage, stale evidence, search candidate, or explicit broader-context need",
            }
        )
    ]


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
    recommended_windows = _recommended_read_windows_from_decisions(file_evidence_decisions)
    if not active_files and not stale_files:
        if recommended_windows:
            latest = recommended_windows[-1]
            return drop_empty(
                {
                    "kind": "read_resource_state",
                    "authority_boundary": "resource_state_only",
                    "status": "search_matched",
                    "path": str(latest.get("path") or ""),
                    "candidate_read_windows": recommended_windows[-6:],
                    "file_evidence_decision_ref": "file_evidence_decisions",
                    "state_code": "recommended_read_window_available",
                    "collection_feedback": {
                        "status": "candidate_window_available",
                        "meaning": "search located a likely range; exact source still belongs to read_file",
                    },
                    "action_conditions": ["read candidate window only if exact current source around the match is needed"],
                    "authority": "harness.runtime.dynamic_context.read_resource_state",
                }
            )
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
                "candidate_read_windows": recommended_windows[-6:],
                "collection_feedback": {
                    "status": "stale_evidence",
                    "meaning": "historical windows remain useful for orientation but not exact current source",
                },
                "action_conditions": ["read the minimal current target window before relying on stale content"],
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
            "files": [_read_resource_file_ref(item) for item in active_files[-6:]],
            "active_file_count": len(active_files),
            "available_range_count": len(active_ranges),
            "available_evidence_refs": _read_resource_evidence_refs(active_files),
            "coverage": _thin_coverage_projection(dict(latest.get("coverage") or {})),
            "exact_coverage": _thin_coverage_projection(dict(latest.get("exact_coverage") or {})),
            "content_sha256": str(latest.get("content_sha256") or ""),
            "file_evidence_decision_ref": "file_evidence_decisions",
            "state_code": "current_read_resource_available",
            "reuse_feedback": {
                "status": "current_window_reusable",
                "meaning": "reuse current exact windows when the target is covered",
            },
            "action_conditions": ["read_file only when the target is outside coverage, the file changed, or broader context is explicitly needed"],
            "candidate_read_windows": recommended_windows[-6:],
            "authority": "harness.runtime.dynamic_context.read_resource_state",
        }
    )


def _recommended_read_windows_from_decisions(file_evidence_decisions: dict[str, Any] | None) -> list[dict[str, Any]]:
    windows: list[dict[str, Any]] = []
    for file_item in dict_tuple(dict(file_evidence_decisions or {}).get("files")):
        for raw in dict_tuple(file_item.get("candidate_read_windows")):
            windows.append(
                drop_empty(
                    {
                        "candidate_kind": str(raw.get("candidate_kind") or raw.get("decision") or "search_match_context_window"),
                        "path": str(raw.get("path") or file_item.get("path") or ""),
                        "start_line": raw.get("start_line"),
                        "line_count": raw.get("line_count"),
                        "match_line": raw.get("match_line"),
                        "query": compact_text(raw.get("query") or "", limit=120),
                        "source_observation_ref": str(raw.get("source_observation_ref") or ""),
                        "read_condition": compact_text(
                            raw.get("read_condition")
                            or "read this candidate only if exact current source around the search match is needed",
                            limit=160,
                        ),
                        "reason": compact_text(raw.get("reason") or "", limit=160),
                    }
                )
            )
    return [item for item in windows if item]


def _read_resource_file_ref(item: dict[str, Any]) -> dict[str, Any]:
    ranges = _current_read_ranges(item)
    return drop_empty(
        {
            "path": str(item.get("path") or ""),
            "status": str(item.get("status") or ""),
            "coverage": _thin_coverage_projection(dict(item.get("coverage") or {})),
            "exact_coverage": _thin_coverage_projection(dict(item.get("exact_coverage") or {})),
            "has_more": item.get("has_more") if isinstance(item.get("has_more"), bool) else None,
            "content_sha256": str(item.get("content_sha256") or ""),
            "last_observation_ref": str(item.get("last_observation_ref") or ""),
            "latest_read_window_ref": _file_state_cursor_read_window(ranges[-1]) if ranges else {},
            "read_window_count": len(ranges),
            "next_suggested_read": _read_request_ref(dict(item.get("next_suggested_read") or {})),
            "recommended_read_window_count": len(dict_tuple(item.get("recommended_read_windows"))),
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
