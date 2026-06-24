from __future__ import annotations

import hashlib
import json
from typing import Any

from runtime.memory.file_state_authority import FileStateAuthority
from runtime.memory.tool_observation_ledger import ToolObservationLedger, build_tool_observation_record


_TOOL_OBSERVATION_FAILURE_STATUSES = {
    "error",
    "failed",
    "denied",
    "needs_approval",
    "needs_contract",
    "aborted",
    "canceled",
    "cancelled",
}


def build_tool_followup_evidence_delta_summary(
    *,
    current_observations: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    accumulated_observations: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    tool_iteration: int,
) -> dict[str, Any]:
    current_payloads = [dict(item) for item in list(current_observations or []) if isinstance(item, dict)]
    if not current_payloads:
        return {}
    accumulated_payloads = [dict(item) for item in list(accumulated_observations or []) if isinstance(item, dict)]
    current_records = _tool_observation_records(current_payloads)
    ledger = ToolObservationLedger(
        ledger_id=f"toolobs:single-agent-turn:{max(1, int(tool_iteration or 1))}",
        task_run_id="",
    )
    for record in _tool_observation_records(accumulated_payloads):
        ledger = ledger.append(record)
    new_observations = [
        item
        for item in (
            _tool_observation_evidence_item(observation, record=record)
            for observation, record in zip(current_payloads, current_records)
        )
        if item
    ]
    if not new_observations:
        return {}
    boundary = _cumulative_file_evidence_boundary(
        accumulated_payloads,
        relevant_paths=_paths_from_evidence_items(new_observations),
    )
    summary_seed = {
        "tool_iteration": int(tool_iteration or 0),
        "new_observations": new_observations,
        "boundary": boundary,
    }
    return _drop_empty(
        {
            "summary_ref": "evidence-delta:" + _stable_hash(summary_seed).removeprefix("sha256:")[:16],
            "tool_iteration": int(tool_iteration or 0),
            "current_observation_count": len(current_payloads),
            "cumulative_observation_count": len(accumulated_payloads),
            "new_observations": new_observations[:8],
            "cumulative_ledger_summary": _compact_ledger_summary(ledger.summary()),
            "cumulative_evidence_boundary": boundary,
            "agent_contract": [
                "如果证据只覆盖文件窗口，不要声称已经通读、完整审查或确认整个文件。",
                "如果需要完整结论，请继续读取 missing_ranges、required_read_windows 或搜索推荐窗口。",
                "如果直接回答，请在自然语言中说明已确认范围和未确认边界。",
                "如果动作没有执行回执，不要声称动作已经完成。",
            ],
            "authority": "runtime.memory.evidence_delta_summary",
        }
    )


def _tool_observation_records(observations: list[dict[str, Any]]) -> list[Any]:
    records: list[Any] = []
    for observation in observations:
        payload = dict(observation or {})
        envelope = dict(payload.get("result_envelope") or {})
        structured = dict(envelope.get("structured_payload") or {})
        structured_error = payload.get("structured_error") or structured.get("structured_error") or {}
        records.append(
            build_tool_observation_record(
                observation_ref=str(payload.get("observation_id") or payload.get("observation_ref") or ""),
                tool_name=str(payload.get("tool_name") or envelope.get("tool_name") or ""),
                tool_args=dict(envelope.get("tool_args") or {}),
                result=payload,
                structured_error=dict(structured_error) if isinstance(structured_error, dict) else {},
            )
        )
    return records


def _tool_observation_evidence_item(observation: dict[str, Any], *, record: Any) -> dict[str, Any]:
    payload = dict(observation or {})
    envelope = dict(payload.get("result_envelope") or {})
    structured = dict(envelope.get("structured_payload") or {})
    tool_result = dict(structured.get("tool_result") or {})
    tool_name = str(payload.get("tool_name") or envelope.get("tool_name") or getattr(record, "tool_name", "") or "").strip()
    status = str(payload.get("status") or envelope.get("status") or getattr(record, "status", "") or "").strip()
    base = {
        "observation_ref": str(payload.get("observation_id") or payload.get("observation_ref") or getattr(record, "observation_ref", "") or ""),
        "tool_call_id": _tool_call_id(payload),
        "tool_name": tool_name,
        "status": status,
    }
    error = str(envelope.get("error") or payload.get("error") or "").strip()
    if error or status in _TOOL_OBSERVATION_FAILURE_STATUSES:
        return _drop_empty(
            {
                **base,
                "error": _compact(error or payload.get("text") or "", limit=240),
                "usable_as": ["tool_failure_observation"],
                "not_usable_as": ["successful_execution_receipt"],
            }
        )
    metadata = dict(getattr(record, "result_metadata", {}) or {})
    if tool_name == "read_file":
        return _read_file_evidence_item(base=base, metadata=metadata, tool_result=tool_result)
    if tool_name in {"search_text", "search_files", "glob_paths"}:
        return _search_tool_evidence_item(base=base, tool_result=tool_result, envelope=envelope, record=record)
    command_receipt = dict(getattr(record, "command_receipt", {}) or envelope.get("command_receipt") or {})
    if command_receipt:
        return _drop_empty(
            {
                **base,
                "execution_receipt": _command_receipt_summary(command_receipt),
                "usable_as": ["execution_receipt"],
            }
        )
    write_paths = _bounded_texts(
        list(envelope.get("written_paths") or [])
        or list(structured.get("written_paths") or [])
        or list(payload.get("written_paths") or []),
        limit=8,
    )
    if write_paths:
        return _drop_empty(
            {
                **base,
                "written_paths": write_paths,
                "usable_as": ["write_execution_receipt"],
                "not_usable_as": ["post_write_file_text_evidence"],
            }
        )
    return _drop_empty(
        {
            **base,
            "observed_paths": _bounded_texts(getattr(record, "observed_paths", ()), limit=8),
            "matched_paths": _bounded_texts(getattr(record, "matched_paths", ()), limit=8),
            "usable_as": ["tool_observation"],
        }
    )


def _read_file_evidence_item(*, base: dict[str, Any], metadata: dict[str, Any], tool_result: dict[str, Any]) -> dict[str, Any]:
    content_range = dict(metadata.get("content_range") or {})
    if not content_range:
        return _drop_empty(
            {
                **base,
                "path": str(tool_result.get("path") or ""),
                "usable_as": ["tool_observation"],
                "not_usable_as": ["full_file_fact"],
            }
        )
    boundary = dict(metadata.get("result_boundary") or {})
    return _drop_empty(
        {
            **base,
            "path": str(content_range.get("path") or tool_result.get("path") or ""),
            "content_range": _content_range(content_range),
            "usable_as": list(boundary.get("usable_as") or []),
            "not_usable_as": list(boundary.get("not_usable_as") or []),
            "fact_status": str(boundary.get("fact_status") or "window_evidence"),
            "freshness": str(boundary.get("freshness") or ""),
            "recovery_options": _bounded_dicts(
                [dict(item) for item in list(metadata.get("recovery_options") or []) if isinstance(item, dict)],
                limit=3,
            ),
        }
    )


def _search_tool_evidence_item(
    *,
    base: dict[str, Any],
    tool_result: dict[str, Any],
    envelope: dict[str, Any],
    record: Any,
) -> dict[str, Any]:
    matches = [dict(item) for item in list(tool_result.get("matches") or []) if isinstance(item, dict)]
    matched_paths = _bounded_texts(
        list(getattr(record, "matched_paths", ()) or ())
        or list(envelope.get("matched_paths") or [])
        or [str(item.get("path") or "") for item in matches],
        limit=12,
    )
    return _drop_empty(
        {
            **base,
            "query": str(tool_result.get("query") or dict(getattr(record, "tool_args", {}) or {}).get("query") or ""),
            "matched_paths": matched_paths,
            "match_count_visible": len(matches),
            "recommended_read_windows": _bounded_dicts(
                [
                    _read_window_hint(item)
                    for item in list(tool_result.get("recommended_read_windows") or [])
                    if isinstance(item, dict)
                ],
                limit=5,
            ),
            "usable_as": ["locator_evidence"],
            "not_usable_as": ["current_exact_file_text", "full_file_fact"],
        }
    )


def _cumulative_file_evidence_boundary(observations: list[dict[str, Any]], *, relevant_paths: set[str]) -> dict[str, Any]:
    file_state = FileStateAuthority.from_observations(observations)
    projection = [dict(item) for item in list(file_state.projection(limit=12) or []) if isinstance(item, dict)]
    selected = [
        item
        for item in projection
        if str(item.get("path") or "").replace("\\", "/").strip("/") in relevant_paths
    ] if relevant_paths else []
    if not selected:
        selected = projection[-6:]
    return _drop_empty(
        {
            "files": [item for item in (_file_boundary_item(item) for item in selected[:8]) if item],
            "authority": "runtime.memory.file_state_authority",
        }
    )


def _file_boundary_item(file_payload: dict[str, Any]) -> dict[str, Any]:
    payload = dict(file_payload or {})
    coverage = dict(payload.get("coverage") or {})
    exact_coverage = dict(payload.get("exact_coverage") or {})
    read_ranges = [
        _drop_empty(
            {
                "start_line": item.get("start_line"),
                "end_line": item.get("end_line"),
                "observation_ref": item.get("observation_ref"),
                "visible_exact": item.get("visible_exact"),
                "stale": item.get("stale"),
            }
        )
        for item in list(payload.get("read_ranges") or [])
        if isinstance(item, dict)
    ]
    return _drop_empty(
        {
            "path": str(payload.get("path") or ""),
            "status": str(payload.get("status") or ""),
            "total_lines": payload.get("total_lines"),
            "coverage_complete": coverage.get("complete"),
            "covered_lines": coverage.get("covered_lines"),
            "covered_ranges": _bounded_dicts(list(coverage.get("merged_ranges") or []), limit=6),
            "missing_ranges": _bounded_dicts(list(coverage.get("missing_ranges") or []), limit=6),
            "exact_coverage_complete": exact_coverage.get("complete"),
            "read_ranges": _bounded_dicts(read_ranges, limit=6),
            "next_suggested_read": _read_window_hint(dict(payload.get("next_suggested_read") or {})),
            "recommended_read_windows": _bounded_dicts(
                [
                    _read_window_hint(item)
                    for item in list(payload.get("recommended_read_windows") or [])
                    if isinstance(item, dict)
                ],
                limit=4,
            ),
        }
    )


def _compact_ledger_summary(summary: dict[str, Any]) -> dict[str, Any]:
    payload = dict(summary or {})
    return _drop_empty(
        {
            "record_count": payload.get("record_count"),
            "read_count": payload.get("read_count"),
            "write_count": payload.get("write_count"),
            "verification_count": payload.get("verification_count"),
            "observed_paths": _bounded_texts(payload.get("observed_paths"), limit=12),
            "matched_paths": _bounded_texts(payload.get("matched_paths"), limit=12),
            "verification_passed": payload.get("verification_passed") if int(payload.get("verification_count") or 0) else None,
        }
    )


def _content_range(content_range: dict[str, Any]) -> dict[str, Any]:
    payload = dict(content_range or {})
    return _drop_empty(
        {
            "path": payload.get("path"),
            "start_line": payload.get("start_line"),
            "end_line": payload.get("end_line"),
            "returned_lines": payload.get("returned_lines"),
            "line_count": payload.get("line_count"),
            "total_lines": payload.get("total_lines"),
            "has_more": payload.get("has_more"),
            "next_start_line": payload.get("next_start_line"),
            "content_sha256": payload.get("content_sha256"),
        }
    )


def _read_window_hint(value: dict[str, Any]) -> dict[str, Any]:
    payload = dict(value or {})
    return _drop_empty(
        {
            "path": payload.get("path"),
            "start_line": payload.get("start_line"),
            "end_line": payload.get("end_line"),
            "line_count": payload.get("line_count"),
            "reason": _compact(payload.get("reason"), limit=160),
            "query": _compact(payload.get("query"), limit=160),
            "match_line": payload.get("match_line"),
            "source_observation_ref": payload.get("source_observation_ref") or payload.get("observation_ref"),
            "status": payload.get("status"),
        }
    )


def _command_receipt_summary(receipt: dict[str, Any]) -> dict[str, Any]:
    payload = dict(receipt or {})
    return _drop_empty(
        {
            "command": _compact(payload.get("command"), limit=240),
            "exit_code": payload.get("exit_code"),
            "passed": payload.get("passed"),
            "failure_kind": payload.get("failure_kind"),
            "output_preview": _compact(payload.get("output_preview"), limit=320),
        }
    )


def _paths_from_evidence_items(items: list[dict[str, Any]]) -> set[str]:
    paths: set[str] = set()
    for item in items:
        payload = dict(item or {})
        for key in ("path",):
            _add_path(paths, payload.get(key))
        for key in ("observed_paths", "matched_paths", "written_paths"):
            for value in list(payload.get(key) or []):
                _add_path(paths, value)
        _add_path(paths, dict(payload.get("content_range") or {}).get("path"))
    return paths


def _add_path(paths: set[str], value: Any) -> None:
    text = str(value or "").replace("\\", "/").strip().strip("/")
    if text:
        paths.add(text)


def _bounded_dicts(values: list[Any] | tuple[Any, ...], *, limit: int) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in list(values or [])[: max(0, int(limit or 0))]:
        if not isinstance(item, dict):
            continue
        clean = _drop_empty(dict(item))
        if clean:
            result.append(clean)
    return result


def _bounded_texts(values: Any, *, limit: int) -> list[str]:
    if isinstance(values, str):
        raw_values = [values]
    else:
        raw_values = list(values or [])
    return [str(item) for item in raw_values[: max(0, int(limit or 0))] if str(item or "")]


def _tool_call_id(observation: dict[str, Any]) -> str:
    payload = dict(observation or {})
    envelope = dict(payload.get("result_envelope") or {})
    execution_receipt = dict(payload.get("execution_receipt") or envelope.get("execution_receipt") or {})
    return str(payload.get("tool_call_id") or envelope.get("tool_call_id") or execution_receipt.get("tool_call_id") or "").strip()


def _stable_hash(value: Any) -> str:
    raw = json.dumps(_json_stable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()


def _json_stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_stable(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_json_stable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def _compact(value: Any, *, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if limit <= 0 or len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in dict(payload or {}).items() if value not in ("", None, [], {}, ())}
