from __future__ import annotations

from typing import Any

from .models import compact_text, dict_tuple, drop_empty, stable_json_hash


EVIDENCE_ACQUISITION_HORIZON_AUTHORITY = "harness.runtime.dynamic_context.evidence_acquisition_horizon"


def build_evidence_acquisition_horizon(
    *,
    evidence_index_cursor_payload: dict[str, Any] | None = None,
    read_evidence_prompt_payload: dict[str, Any] | None = None,
    editor_context_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cursor = _evidence_index_cursor(evidence_index_cursor_payload)
    read_payload = dict(read_evidence_prompt_payload or {})
    editor_payload = dict(editor_context_payload or {})
    files = [dict(item) for item in dict_tuple(cursor.get("files"))]
    read_resource = dict(cursor.get("read_resource") or {}) if isinstance(cursor.get("read_resource"), dict) else {}

    required_reads: list[dict[str, Any]] = []
    stale_reads: list[dict[str, Any]] = []
    missing_ranges: list[dict[str, Any]] = []
    candidate_reads: list[dict[str, Any]] = []
    usable_evidence_refs: list[dict[str, Any]] = []
    cautions: list[dict[str, Any]] = []

    for file_item in files:
        path = _clean_path(file_item.get("path"))
        if not path:
            continue
        _collect_file_horizon(
            file_item,
            path=path,
            required_reads=required_reads,
            stale_reads=stale_reads,
            missing_ranges=missing_ranges,
            candidate_reads=candidate_reads,
            usable_evidence_refs=usable_evidence_refs,
            cautions=cautions,
        )

    for window in dict_tuple(read_resource.get("candidate_read_windows")):
        candidate_reads.append(_read_window(window, path=_clean_path(window.get("path") or read_resource.get("path")), source="read_resource_state"))

    for window in dict_tuple(read_payload.get("read_required_windows")):
        required_reads.append(_read_window(window, path=_clean_path(window.get("path")), source="read_evidence_projection"))

    for ref in dict_tuple(read_payload.get("read_evidence_refs")):
        usable = _read_evidence_ref(ref)
        if usable:
            usable_evidence_refs.append(usable)

    editor_refs = _editor_evidence_refs(editor_payload)
    if editor_refs:
        usable_evidence_refs.extend(editor_refs)

    required_reads = _dedupe_dicts(required_reads)[-8:]
    stale_reads = _dedupe_dicts(stale_reads)[-8:]
    missing_ranges = _dedupe_dicts(missing_ranges)[-8:]
    candidate_reads = _dedupe_dicts(candidate_reads)[-8:]
    usable_evidence_refs = _dedupe_dicts(usable_evidence_refs)[-12:]
    cautions = _dedupe_dicts(cautions)[-6:]

    if not (files or read_resource or required_reads or stale_reads or missing_ranges or candidate_reads or usable_evidence_refs or cautions):
        return {}

    boundary_state = _boundary_state(
        required_reads=required_reads,
        stale_reads=stale_reads,
        missing_ranges=missing_ranges,
        candidate_reads=candidate_reads,
        usable_evidence_refs=usable_evidence_refs,
        read_resource=read_resource,
    )
    seed = drop_empty(
        {
            "files": [_file_ref(item) for item in files],
            "read_resource": _read_resource_ref(read_resource),
            "required_reads": required_reads,
            "stale_reads": stale_reads,
            "missing_ranges": missing_ranges,
            "candidate_reads": candidate_reads,
            "usable_evidence_refs": usable_evidence_refs,
            "boundary_state": boundary_state,
        }
    )
    horizon = drop_empty(
        {
            "kind": "evidence_acquisition_horizon",
            "horizon_id": "evh:" + stable_json_hash(seed).removeprefix("sha256:")[:16],
            "boundary_state": boundary_state,
            "lifecycle": {
                "scope": "current_invocation",
                "history_policy": "dynamic_tail_only",
                "release_condition": "replace_on_next_context_projection",
            },
            "authority_order": {
                "higher_than": ["context_memory_prefix", "session_history_tail", "runtime_memory_summary"],
                "lower_than": ["current_user_instruction", "tool_authorization_policy"],
            },
            "decision_boundary": {
                "read_before_final_claim_when": [
                    "required_reads is non-empty for the target range",
                    "stale_reads is non-empty and exact current source is needed",
                    "missing_ranges overlaps the claim being made",
                ],
                "reuse_evidence_when": "usable_evidence_refs covers the target and is not stale",
                "do_not_treat_as_tool_authorization": True,
                "do_not_answer_from": ["stale_read_windows", "missing_or_unread_ranges"],
            },
            "required_reads": required_reads,
            "stale_reads": stale_reads,
            "missing_ranges": missing_ranges,
            "candidate_reads": candidate_reads,
            "usable_evidence_refs": usable_evidence_refs,
            "cautions": cautions,
            "read_resource": _read_resource_ref(read_resource),
            "source_refs": {
                "evidence_index_cursor_ref": _cursor_ref(cursor),
                "read_evidence_ref_count": len(dict_tuple(read_payload.get("read_evidence_refs"))),
                "editor_evidence_ref_count": len(editor_refs),
            },
            "projection": "refs_ranges_freshness_action_boundary_only",
            "authority": EVIDENCE_ACQUISITION_HORIZON_AUTHORITY,
        }
    )
    return {"evidence_acquisition_horizon": horizon}


def _collect_file_horizon(
    file_item: dict[str, Any],
    *,
    path: str,
    required_reads: list[dict[str, Any]],
    stale_reads: list[dict[str, Any]],
    missing_ranges: list[dict[str, Any]],
    candidate_reads: list[dict[str, Any]],
    usable_evidence_refs: list[dict[str, Any]],
    cautions: list[dict[str, Any]],
) -> None:
    freshness = str(file_item.get("freshness") or file_item.get("status") or "").strip()
    for window in dict_tuple(file_item.get("required_read_windows")):
        required_reads.append(_read_window(window, path=path, source="required_read_windows"))
    for window in dict_tuple(file_item.get("missing_ranges")):
        missing_ranges.append(_range_ref(window, path=path, source="missing_ranges"))
    for window in dict_tuple(file_item.get("candidate_read_windows")):
        candidate_reads.append(_read_window(window, path=path, source="candidate_read_windows"))
    for caution in dict_tuple(file_item.get("cautions")):
        if str(caution.get("caution_kind") or "") == "stale_read_window":
            stale_reads.append(_read_window(caution, path=path, source="stale_read_window"))
        else:
            cautions.append(_caution_ref(caution, path=path))
    for window in dict_tuple(file_item.get("read_window_refs")):
        if window.get("stale") is True or freshness == "stale":
            stale_reads.append(_read_window(window, path=path, source="read_window_refs"))
            continue
        usable = _usable_window_ref(window, path=path, freshness=freshness)
        if usable:
            usable_evidence_refs.append(usable)
    latest_ref = str(file_item.get("latest_evidence_ref") or "").strip()
    if latest_ref and freshness not in {"stale", "partially_stale", "missing"}:
        usable_evidence_refs.append(
            drop_empty(
                {
                    "path": path,
                    "evidence_ref": latest_ref,
                    "freshness": freshness,
                    "source": "latest_evidence_ref",
                }
            )
        )
    if str(file_item.get("rehydration_action") or "") == "read_file:missing_window":
        next_read = dict(file_item.get("next_suggested_read") or {})
        if next_read:
            required_reads.append(_read_window(next_read, path=path, source="next_suggested_read"))


def _evidence_index_cursor(payload: dict[str, Any] | None) -> dict[str, Any]:
    source = dict(payload or {})
    nested = source.get("evidence_index_cursor")
    if isinstance(nested, dict):
        return dict(nested)
    if str(source.get("kind") or "") == "evidence_index_cursor":
        return source
    return {}


def _read_window(value: dict[str, Any], *, path: str, source: str) -> dict[str, Any]:
    end_line = value.get("end_line")
    line_count = value.get("line_count")
    return drop_empty(
        {
            "path": _clean_path(value.get("path") or path),
            "start_line": value.get("start_line"),
            "end_line": end_line,
            "line_count": line_count,
            "requirement_kind": str(value.get("requirement_kind") or ""),
            "candidate_kind": str(value.get("candidate_kind") or ""),
            "caution_kind": str(value.get("caution_kind") or ""),
            "read_condition": compact_text(value.get("read_condition") or "", limit=180),
            "reason": compact_text(value.get("reason") or "", limit=180),
            "observation_ref": str(value.get("observation_ref") or value.get("source_observation_ref") or ""),
            "exact_artifact_ref": str(value.get("exact_artifact_ref") or value.get("artifact_ref") or ""),
            "source": source,
            "action": "read_file",
        }
    )


def _range_ref(value: dict[str, Any], *, path: str, source: str) -> dict[str, Any]:
    return drop_empty(
        {
            "path": path,
            "start_line": value.get("start_line"),
            "end_line": value.get("end_line"),
            "source": source,
        }
    )


def _usable_window_ref(value: dict[str, Any], *, path: str, freshness: str) -> dict[str, Any]:
    ref = str(value.get("exact_artifact_ref") or value.get("reusable_result_ref") or value.get("observation_ref") or "").strip()
    if not ref:
        return {}
    return drop_empty(
        {
            "path": path,
            "start_line": value.get("start_line"),
            "end_line": value.get("end_line"),
            "evidence_ref": ref,
            "freshness": freshness,
            "source": "read_window_refs",
        }
    )


def _read_evidence_ref(value: dict[str, Any]) -> dict[str, Any]:
    ref = str(
        value.get("artifact_ref")
        or value.get("exact_artifact_ref")
        or value.get("evidence_ref")
        or value.get("observation_ref")
        or value.get("tool_result_ref")
        or ""
    ).strip()
    return drop_empty(
        {
            "path": _clean_path(value.get("path")),
            "start_line": value.get("start_line"),
            "end_line": value.get("end_line"),
            "evidence_ref": ref,
            "visible_exact_in_current_packet": value.get("model_visible_exact_in_current_packet") is True,
            "source": "read_evidence_refs",
        }
    )


def _editor_evidence_refs(payload: dict[str, Any]) -> list[dict[str, Any]]:
    delta = dict(payload.get("current_editor_evidence_delta") or {}) if isinstance(payload.get("current_editor_evidence_delta"), dict) else {}
    refs: list[dict[str, Any]] = []
    for item in dict_tuple(delta.get("editor_evidence_refs") or delta.get("evidence_refs")):
        ref = str(item.get("evidence_ref") or item.get("artifact_ref") or item.get("observation_ref") or "").strip()
        if not ref:
            continue
        refs.append(
            drop_empty(
                {
                    "path": _clean_path(item.get("path")),
                    "start_line": item.get("start_line"),
                    "end_line": item.get("end_line"),
                    "evidence_ref": ref,
                    "source": "current_editor_evidence_delta",
                }
            )
        )
    return [item for item in refs if item]


def _caution_ref(value: dict[str, Any], *, path: str) -> dict[str, Any]:
    return drop_empty(
        {
            "path": path,
            "caution_kind": str(value.get("caution_kind") or ""),
            "reason": compact_text(value.get("reason") or "", limit=180),
            "read_condition": compact_text(value.get("read_condition") or "", limit=180),
        }
    )


def _read_resource_ref(value: dict[str, Any]) -> dict[str, Any]:
    return drop_empty(
        {
            "status": str(value.get("status") or ""),
            "path": _clean_path(value.get("path")),
            "active_file_count": value.get("active_file_count"),
            "available_range_count": value.get("available_range_count"),
            "available_evidence_refs": [str(item) for item in _as_list(value.get("available_evidence_refs"))[-8:] if str(item).strip()],
            "state_code": str(value.get("state_code") or ""),
            "action_conditions": [
                compact_text(item, limit=140)
                for item in _as_list(value.get("action_conditions"))[-4:]
                if str(item).strip()
            ],
        }
    )


def _file_ref(value: dict[str, Any]) -> dict[str, Any]:
    return drop_empty(
        {
            "path": _clean_path(value.get("path")),
            "freshness": str(value.get("freshness") or value.get("status") or ""),
            "version": str(value.get("version") or ""),
            "covered_ranges_ref": str(value.get("covered_ranges_ref") or ""),
            "latest_evidence_ref": str(value.get("latest_evidence_ref") or ""),
        }
    )


def _boundary_state(
    *,
    required_reads: list[dict[str, Any]],
    stale_reads: list[dict[str, Any]],
    missing_ranges: list[dict[str, Any]],
    candidate_reads: list[dict[str, Any]],
    usable_evidence_refs: list[dict[str, Any]],
    read_resource: dict[str, Any],
) -> str:
    if required_reads or missing_ranges:
        return "read_required_before_exact_claim"
    if stale_reads or str(read_resource.get("status") or "") == "stale":
        return "rehydrate_stale_before_exact_claim"
    if candidate_reads:
        return "candidate_reads_available"
    if usable_evidence_refs:
        return "usable_evidence_available"
    return "no_evidence_action_required"


def _cursor_ref(cursor: dict[str, Any]) -> str:
    if not cursor:
        return ""
    seed = {
        "files": [_file_ref(item) for item in dict_tuple(cursor.get("files"))],
        "read_resource": _read_resource_ref(dict(cursor.get("read_resource") or {})),
    }
    return "evcursor:" + stable_json_hash(seed).removeprefix("sha256:")[:16]


def _dedupe_dicts(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in values:
        item = drop_empty(dict(raw or {}))
        if not item:
            continue
        marker = stable_json_hash(item)
        if marker in seen:
            continue
        seen.add(marker)
        result.append(item)
    return result


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        return [value]
    return []


def _clean_path(value: Any) -> str:
    return str(value or "").replace("\\", "/").strip().strip("/")
