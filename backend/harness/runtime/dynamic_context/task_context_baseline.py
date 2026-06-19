from __future__ import annotations

from typing import Any

from .models import drop_empty, stable_json_hash


def build_task_context_baseline_receipt(
    *,
    invocation_kind: str,
    session_id: str,
    task_run_id: str,
    runtime_baseline_refs: dict[str, Any],
    task_state_replay_entries: tuple[dict[str, Any], ...],
    volatile_state_projection: dict[str, Any],
    dynamic_runtime_projection: dict[str, Any],
) -> dict[str, Any]:
    if str(invocation_kind or "") != "task_execution":
        return {}
    replay_refs = [
        str(item.get("observation_ref") or item.get("entry_ref") or "")
        for item in tuple(task_state_replay_entries or ())
        if str(item.get("observation_ref") or item.get("entry_ref") or "")
    ]
    summary_receipts = [
        _summary_receipt(item)
        for item in tuple(task_state_replay_entries or ())
        if str(item.get("entry_kind") or "") == "task_state_replay_summary"
    ]
    task_state_cursor = dict(dict(volatile_state_projection or {}).get("task_state") or {})
    seed = {
        "session_id": str(session_id or ""),
        "task_run_id": str(task_run_id or ""),
        "runtime_baseline_hash": str(dict(runtime_baseline_refs or {}).get("runtime_baseline_hash") or ""),
        "dynamic_runtime_projection_hash": stable_json_hash(dynamic_runtime_projection or {}),
        "replay_refs": replay_refs,
        "summary_receipts": summary_receipts,
        "cursor_shape_hash": stable_json_hash(_cursor_shape(task_state_cursor)),
    }
    baseline_hash = stable_json_hash(seed)
    return drop_empty(
        {
            "baseline_id": "taskctx:" + baseline_hash.removeprefix("sha256:")[:16],
            "session_id": str(session_id or ""),
            "task_run_id": str(task_run_id or ""),
            "baseline_hash": baseline_hash,
            "runtime_baseline_hash": str(dict(runtime_baseline_refs or {}).get("runtime_baseline_hash") or ""),
            "dynamic_runtime_projection_hash": seed["dynamic_runtime_projection_hash"],
            "replay_entry_count": len(tuple(task_state_replay_entries or ())),
            "replay_head_ref": replay_refs[0] if replay_refs else "",
            "replay_tail_ref": replay_refs[-1] if replay_refs else "",
            "replay_refs_hash": stable_json_hash(replay_refs),
            "summary_receipts": summary_receipts,
            "cursor_shape_hash": seed["cursor_shape_hash"],
            "memory_contract": "baseline_plus_append_only_replay_plus_bounded_cursor",
            "rehydration_contract": "history remains recoverable through refs, hashes, ranges, and tool/artifact rehydration",
            "authority": "harness.runtime.dynamic_context.task_context_baseline",
        }
    )


def _summary_receipt(entry: dict[str, Any]) -> dict[str, Any]:
    return drop_empty(
        {
            "summary_ref": str(entry.get("summary_ref") or entry.get("entry_ref") or ""),
            "retained_prefix_entry_count": entry.get("retained_prefix_entry_count"),
            "summarized_entry_count": entry.get("summarized_entry_count"),
            "total_entry_count": entry.get("total_entry_count"),
            "summarized_refs_hash": stable_json_hash(list(entry.get("summarized_refs") or [])),
            "reset_reason": str(entry.get("replay_summary_policy") or "summary_replacement"),
        }
    )


def _cursor_shape(cursor: dict[str, Any]) -> dict[str, Any]:
    return {
        str(key): _shape(value)
        for key, value in sorted(dict(cursor or {}).items(), key=lambda item: str(item[0]))
    }


def _shape(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _shape(item) for key, item in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, list):
        return ["list", len(value), _shape(value[0]) if value else ""]
    if isinstance(value, tuple):
        return ["tuple", len(value), _shape(value[0]) if value else ""]
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if value is None:
        return "none"
    return "string"
