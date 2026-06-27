from __future__ import annotations

from typing import Any

from .models import compact_text, dict_tuple, drop_empty, stable_json_hash


EVIDENCE_INDEX_AUTHORITY = "harness.runtime.dynamic_context.evidence_index_cursor"


def split_evidence_index_cursor(task_state_cursor: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    cursor = dict(task_state_cursor or {})
    file_state = [dict(item) for item in dict_tuple(cursor.pop("file_state", ())) if item]
    file_state_source = str(cursor.pop("file_state_source", "") or "")
    file_evidence_decisions = dict(cursor.pop("file_evidence_decisions", {}) or {})
    read_resource_state = dict(cursor.pop("read_resource_state", {}) or {})
    evidence_confidence = dict(cursor.pop("evidence_confidence", {}) or {})
    progress = dict(cursor.get("task_progress_facts") or {})
    if progress:
        progress.pop("file_evidence", None)
        if progress:
            cursor["task_progress_facts"] = progress
        else:
            cursor.pop("task_progress_facts", None)
    evidence_index = build_evidence_index_cursor(
        file_state=file_state,
        file_state_source=file_state_source,
        file_evidence_decisions=file_evidence_decisions,
        read_resource_state=read_resource_state,
        evidence_confidence=evidence_confidence,
    )
    return evidence_index, drop_empty(cursor)


def build_evidence_index_cursor(
    *,
    file_state: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    file_state_source: str = "",
    file_evidence_decisions: dict[str, Any] | None = None,
    read_resource_state: dict[str, Any] | None = None,
    evidence_confidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    decisions_by_path = _decisions_by_path(file_evidence_decisions)
    confidence_by_path = _confidence_by_path(evidence_confidence)
    files: list[dict[str, Any]] = []
    for item in dict_tuple(file_state):
        path = _clean_path(item.get("path"))
        if not path:
            continue
        decision = dict(decisions_by_path.get(path) or {})
        confidence = dict(confidence_by_path.get(path) or {})
        windows = _read_window_refs(item)
        status = str(item.get("status") or "").strip()
        files.append(
            drop_empty(
                {
                    "path": path,
                    "status": status,
                    "freshness": _freshness(status=status, windows=windows),
                    "version": str(item.get("content_sha256") or ""),
                    "total_lines": item.get("total_lines"),
                    "has_more": item.get("has_more") if isinstance(item.get("has_more"), bool) else None,
                    "latest_evidence_ref": _latest_evidence_ref(item, windows=windows),
                    "covered_ranges_ref": _covered_ranges_ref(path=path, item=item, windows=windows),
                    "read_window_refs": windows,
                    "missing_ranges": _missing_ranges(decision, item),
                    "cautions": _decision_windows(decision.get("cautions")),
                    "candidate_read_windows": _decision_windows(decision.get("candidate_read_windows")),
                    "required_read_windows": _decision_windows(decision.get("required_read_windows")),
                    "next_suggested_read": _read_request_ref(dict(item.get("next_suggested_read") or {})),
                    "confidence": _file_confidence(confidence),
                    "rehydration_action": _rehydration_action(status=status, decision=decision, item=item),
                }
            )
        )
    read_resource = _read_resource_cursor(read_resource_state)
    if not files and not read_resource:
        return {}
    return {
        "evidence_index_cursor": drop_empty(
            {
                "kind": "evidence_index_cursor",
                "file_state_source": file_state_source,
                "files": files[-12:],
                "read_resource": read_resource,
                "policy_ref": "file_evidence_policy_stable.read_evidence_reuse_contract",
                "projection": "ref_hash_range_freshness_only",
                "authority": EVIDENCE_INDEX_AUTHORITY,
            }
        )
    }


def file_state_from_evidence_index_cursor(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    cursor = dict(dict(payload or {}).get("evidence_index_cursor") or {})
    result: list[dict[str, Any]] = []
    for item in dict_tuple(cursor.get("files")):
        result.append(
            drop_empty(
                {
                    "path": _clean_path(item.get("path")),
                    "status": str(item.get("status") or ""),
                    "content_sha256": str(item.get("content_sha256") or item.get("version") or ""),
                    "total_lines": item.get("total_lines"),
                    "has_more": item.get("has_more") if isinstance(item.get("has_more"), bool) else None,
                    "read_window_refs": [dict(window) for window in dict_tuple(item.get("read_window_refs"))],
                    "evidence_refs": _dedupe_strings(item.get("evidence_refs"))[-10:],
                    "next_suggested_read": dict(item.get("next_suggested_read") or {}),
                }
            )
        )
    return result


def file_evidence_decisions_from_evidence_index_cursor(payload: dict[str, Any] | None) -> dict[str, Any]:
    cursor = dict(dict(payload or {}).get("evidence_index_cursor") or {})
    files: list[dict[str, Any]] = []
    for item in dict_tuple(cursor.get("files")):
        files.append(
            drop_empty(
                {
                    "path": _clean_path(item.get("path")),
                    "status": str(item.get("status") or ""),
                    "required_read_windows": _decision_windows(item.get("required_read_windows")),
                    "candidate_read_windows": _decision_windows(item.get("candidate_read_windows")),
                    "cautions": _decision_windows(item.get("cautions")),
                    "policy_ref": "file_evidence_policy_stable.read_window_contract",
                    "authority": EVIDENCE_INDEX_AUTHORITY,
                }
            )
        )
    return drop_empty(
        {
            "kind": "file_evidence_contract",
            "contract_version": "file_evidence_contract.v2",
            "authority_boundary": "observation_projection_only",
            "authority": EVIDENCE_INDEX_AUTHORITY,
            "files": files,
        }
    )


def _decisions_by_path(value: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in dict_tuple(dict(value or {}).get("files")):
        path = _clean_path(item.get("path"))
        if path:
            result[path] = dict(item)
    return result


def _confidence_by_path(value: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in dict_tuple(dict(value or {}).get("files")):
        path = _clean_path(item.get("path"))
        if path:
            result[path] = dict(item)
    return result


def _read_window_refs(item: dict[str, Any]) -> list[dict[str, Any]]:
    windows: list[dict[str, Any]] = []
    for segment in dict_tuple(item.get("read_window_refs") or item.get("read_ranges"))[-8:]:
        exact_ref = str(segment.get("exact_artifact_ref") or "")
        reusable_ref = str(segment.get("reusable_result_ref") or "")
        observation_ref = "" if exact_ref or reusable_ref else str(segment.get("observation_ref") or "")
        windows.append(
            drop_empty(
                {
                    "start_line": segment.get("start_line"),
                    "end_line": segment.get("end_line"),
                    "observation_ref": observation_ref,
                    "exact_artifact_ref": exact_ref,
                    "reusable_result_ref": reusable_ref,
                    "stale": segment.get("stale") if isinstance(segment.get("stale"), bool) else None,
                }
            )
        )
    return [window for window in windows if window]


def _freshness(*, status: str, windows: list[dict[str, Any]]) -> str:
    normalized = str(status or "").strip().lower()
    if normalized in {"stale", "missing"}:
        return normalized
    if any(window.get("stale") is True for window in windows):
        return "partially_stale"
    if windows:
        return "fresh"
    return "metadata_only"


def _latest_evidence_ref(item: dict[str, Any], *, windows: list[dict[str, Any]]) -> str:
    for window in reversed(windows):
        for key in ("exact_artifact_ref", "reusable_result_ref", "observation_ref"):
            value = str(window.get(key) or "").strip()
            if value:
                return value
    return str(item.get("last_observation_ref") or "")


def _covered_ranges_ref(*, path: str, item: dict[str, Any], windows: list[dict[str, Any]]) -> str:
    seed = {
        "path": path,
        "content_sha256": str(item.get("content_sha256") or ""),
        "windows": [
            {
                "start_line": window.get("start_line"),
                "end_line": window.get("end_line"),
                "observation_ref": str(window.get("observation_ref") or ""),
                "artifact_ref": str(window.get("exact_artifact_ref") or window.get("reusable_result_ref") or ""),
                "stale": window.get("stale") is True,
            }
            for window in windows
        ],
    }
    return "evcov:" + stable_json_hash(seed).removeprefix("sha256:")[:16]


def _missing_ranges(decision: dict[str, Any], item: dict[str, Any]) -> list[dict[str, Any]]:
    windows = _decision_windows(decision.get("required_read_windows"))
    if windows:
        return windows
    coverage = dict(item.get("coverage") or {})
    result: list[dict[str, Any]] = []
    for segment in dict_tuple(coverage.get("missing_ranges"))[-4:]:
        result.append(
            drop_empty(
                {
                    "start_line": segment.get("start_line"),
                    "end_line": segment.get("end_line"),
                }
            )
        )
    return [entry for entry in result if entry]


def _decision_windows(value: Any) -> list[dict[str, Any]]:
    windows: list[dict[str, Any]] = []
    for item in dict_tuple(value)[-6:]:
        windows.append(
            drop_empty(
                {
                    "candidate_kind": str(item.get("candidate_kind") or ""),
                    "requirement_kind": str(item.get("requirement_kind") or ""),
                    "caution_kind": str(item.get("caution_kind") or ""),
                    "evidence_kind": str(item.get("evidence_kind") or ""),
                    "decision": str(item.get("decision") or ""),
                    "path": _clean_path(item.get("path")),
                    "start_line": item.get("start_line"),
                    "end_line": item.get("end_line"),
                    "line_count": item.get("line_count"),
                    "observation_ref": str(item.get("observation_ref") or ""),
                    "source_observation_ref": str(item.get("source_observation_ref") or ""),
                    "exact_artifact_ref": str(item.get("exact_artifact_ref") or ""),
                    "read_condition": compact_text(item.get("read_condition") or "", limit=160),
                    "usage_condition": compact_text(item.get("usage_condition") or "", limit=160),
                    "reason": compact_text(item.get("reason") or "", limit=160),
                }
            )
        )
    return [window for window in windows if window]


def _read_request_ref(value: dict[str, Any]) -> dict[str, Any]:
    return drop_empty(
        {
            "path": _clean_path(value.get("path")),
            "start_line": value.get("start_line"),
            "line_count": value.get("line_count"),
            "reason": compact_text(value.get("reason") or "", limit=160),
        }
    )


def _file_confidence(value: dict[str, Any]) -> dict[str, Any]:
    return drop_empty(
        {
            "start_line": value.get("start_line"),
            "end_line": value.get("end_line"),
            "content_sha256": str(value.get("content_sha256") or ""),
        }
    )


def _rehydration_action(*, status: str, decision: dict[str, Any], item: dict[str, Any]) -> str:
    normalized = str(status or "").strip().lower()
    stale_cautions = [
        caution
        for caution in dict_tuple(decision.get("cautions"))
        if str(caution.get("caution_kind") or "") == "stale_read_window"
    ]
    if normalized == "stale" or stale_cautions:
        return "read_file:stale_window"
    if dict_tuple(decision.get("required_read_windows")) or dict(item.get("next_suggested_read") or {}):
        return "read_file:missing_window"
    if _latest_evidence_ref(item, windows=_read_window_refs(item)).startswith("read_observation:"):
        return "reuse_read_observation_ref"
    return ""


def _read_resource_cursor(value: dict[str, Any] | None) -> dict[str, Any]:
    source = dict(value or {})
    if not source:
        return {}
    return drop_empty(
        {
            "status": str(source.get("status") or ""),
            "path": _clean_path(source.get("path")),
            "active_file_count": source.get("active_file_count"),
            "available_range_count": source.get("available_range_count"),
            "available_evidence_refs": _dedupe_strings(source.get("available_evidence_refs"))[-10:],
            "state_code": str(source.get("state_code") or ""),
            "reuse_feedback": dict(source.get("reuse_feedback") or {}),
            "collection_feedback": dict(source.get("collection_feedback") or {}),
            "action_conditions": [
                compact_text(item, limit=120)
                for item in list(source.get("action_conditions") or [])[-4:]
                if str(item).strip()
            ],
        }
    )


def _dedupe_strings(values: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    raw_values = [values] if isinstance(values, str) else list(values or [])
    for raw in raw_values:
        text = str(raw or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _clean_path(value: Any) -> str:
    return str(value or "").replace("\\", "/").strip().strip("/")
