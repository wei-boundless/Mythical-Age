from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from runtime_objects.tool_result_storage import DEFAULT_PREVIEW_SIZE_BYTES, ToolResultStore

from .models import compact_text, dict_tuple, drop_empty, stable_json_hash, string_tuple
from .replacement_store import ReplacementStore
from .structured_error_projection import structured_error_projection


PROJECTOR_VERSION = "tool_result_projector.v1"


class ToolResultProjector:
    def __init__(self, *, root_dir: Path, replacement_store: ReplacementStore) -> None:
        self.root_dir = Path(root_dir)
        self.replacement_store = replacement_store

    def project_many(
        self,
        tool_results: list[dict[str, Any]] | tuple[dict[str, Any], ...],
        *,
        task_run_id: str = "",
        projection_policy: dict[str, Any] | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        projected: list[dict[str, Any]] = []
        records: list[dict[str, Any]] = []
        for item in list(tool_results or []):
            projection, record = self.project(item, task_run_id=task_run_id, projection_policy=projection_policy)
            if projection:
                projected.append(projection)
                records.append(record)
        return projected, records

    def project_from_observation(
        self,
        observation: dict[str, Any],
        *,
        task_run_id: str = "",
        projection_policy: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        tool_payload = _tool_payload_from_observation(observation)
        if not tool_payload:
            return {}, None
        return self.project(tool_payload, task_run_id=task_run_id, projection_policy=projection_policy)

    def project(
        self,
        tool_result: dict[str, Any],
        *,
        task_run_id: str = "",
        projection_policy: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        policy = dict(projection_policy or {})
        normalized = _normalize_tool_result(tool_result)
        source_id = (
            str(normalized.get("tool_result_ref") or "")
            or str(normalized.get("envelope_id") or "")
            or "tool_result:" + stable_json_hash(normalized).removeprefix("sha256:")[:16]
        )
        projection = self._build_projection(normalized, task_run_id=task_run_id, projection_policy=policy)
        projection, record = self.replacement_store.get_or_put(
            source_kind="tool_result",
            source_id=source_id,
            content=normalized,
            projection_policy=policy,
            projector_version=PROJECTOR_VERSION,
            projection=projection,
        )
        projection = {**projection, "replacement_ref": record.replacement_key}
        return projection, record.to_dict()

    def _build_projection(
        self,
        normalized: dict[str, Any],
        *,
        task_run_id: str,
        projection_policy: dict[str, Any],
    ) -> dict[str, Any]:
        text = str(normalized.get("text") or "")
        preview_limit = int(projection_policy.get("tool_result_preview_chars") or DEFAULT_PREVIEW_SIZE_BYTES)
        content_replacements: list[dict[str, Any]] = []
        preview = compact_text(text, limit=preview_limit)
        result_ref = str(normalized.get("result_ref") or "")
        if len(text.encode("utf-8", errors="ignore")) > preview_limit:
            store = ToolResultStore(self.root_dir, run_id=task_run_id or "session", namespace="runtime_context")
            budgeted, replacements = store.apply_budget(
                {"text": text},
                field_limit_bytes=preview_limit,
                preview_size_bytes=preview_limit,
                payload_budget_bytes=max(preview_limit * 2, preview_limit + 1000),
            )
            preview = str(budgeted.get("text") or preview)
            content_replacements = [item.to_dict() for item in replacements]
            if content_replacements and not result_ref:
                result_ref = str(content_replacements[0].get("path") or content_replacements[0].get("replacement_id") or "")
        structured_error = dict(normalized.get("structured_error") or {})
        error = str(normalized.get("error") or structured_error.get("message") or structured_error.get("detail") or "")
        return drop_empty(
            {
                "tool_result_ref": str(normalized.get("tool_result_ref") or normalized.get("envelope_id") or ""),
                "tool_name": str(normalized.get("tool_name") or ""),
                "status": str(normalized.get("status") or ("error" if error else "ok")),
                "preview": preview,
                "result_ref": result_ref,
                "structured_error": structured_error_projection(structured_error),
                "error": compact_text(error, limit=500),
                "artifact_refs": model_visible_artifact_refs(normalized.get("artifact_refs")),
                "observed_paths": list(string_tuple(normalized.get("observed_paths"))),
                "matched_paths": list(string_tuple(normalized.get("matched_paths"))),
                "command_receipt": dict(normalized.get("command_receipt") or {}),
                "content_range": dict(normalized.get("content_range") or {}),
                "tool_guidance": compact_text(normalized.get("tool_guidance") or "", limit=500),
                "content_replacements": content_replacements,
                "authority": "harness.runtime.dynamic_context.tool_result_projection",
            }
        )


def _tool_payload_from_observation(observation: dict[str, Any]) -> dict[str, Any]:
    item = dict(observation or {})
    wrapped = dict(item.get("observation") or {})
    source = wrapped if wrapped else item
    payload = dict(source.get("payload") or {})
    envelope = payload.get("result_envelope") or source.get("result_envelope") or item.get("result_envelope")
    structured_payload = payload.get("structured_payload") or source.get("structured_payload")
    has_tool_signal = bool(envelope or structured_payload or payload.get("tool_name") or source.get("tool_name"))
    if not has_tool_signal:
        return {}
    result = {
        "tool_result_ref": str(source.get("observation_id") or item.get("observation_id") or ""),
        "tool_name": str(payload.get("tool_name") or source.get("tool_name") or source.get("source") or ""),
        "text": payload.get("result") or source.get("content") or source.get("text") or source.get("summary") or source.get("result_preview") or "",
        "structured_payload": structured_payload or {},
        "result_metadata": source.get("result_metadata") or payload.get("result_metadata") or {},
        "structured_error": source.get("structured_error") or payload.get("structured_error") or {},
        "error": source.get("error") or payload.get("error") or "",
    }
    if isinstance(envelope, dict):
        result["result_envelope"] = dict(envelope)
    return result


def _normalize_tool_result(tool_result: dict[str, Any]) -> dict[str, Any]:
    item = dict(tool_result or {})
    envelope = dict(item.get("result_envelope") or item.get("envelope") or {})
    raw_text = (
        envelope.get("text")
        or item.get("text")
        or item.get("result")
        or item.get("content")
        or item.get("summary")
        or ""
    )
    parsed_text = _parse_json_object(raw_text)
    parsed_tool_result = dict(parsed_text.get("tool_result") or {})
    parsed_structured_payload = dict(parsed_text.get("structured_payload") or {})
    structured = _merge_dicts(parsed_structured_payload, envelope.get("structured_payload"), item.get("structured_payload"))
    nested_tool_result = _merge_dicts(parsed_tool_result, structured.get("tool_result"))
    result_metadata = _merge_dicts(item.get("result_metadata"), _read_file_metadata_from_structured(nested_tool_result, structured, item, envelope))
    artifact_refs = (
        item.get("artifact_refs")
        or envelope.get("artifact_refs")
        or structured.get("artifact_refs")
        or nested_tool_result.get("artifact_refs")
        or parsed_text.get("artifact_refs")
        or []
    )
    text = _first_text(
        envelope.get("text"),
        item.get("text"),
        item.get("content"),
        item.get("summary"),
        nested_tool_result.get("text"),
        nested_tool_result.get("data"),
        parsed_text.get("text"),
        parsed_text.get("summary"),
        parsed_text.get("result"),
        parsed_text.get("message"),
        parsed_text.get("error"),
        raw_text,
    )
    status = str(
        envelope.get("status")
        or item.get("status")
        or nested_tool_result.get("status")
        or parsed_text.get("status")
        or _status_from_ok(parsed_text.get("ok"))
        or ""
    ).strip()
    structured_error = _merge_dicts(
        parsed_text.get("structured_error"),
        nested_tool_result.get("structured_error"),
        envelope.get("structured_error"),
        item.get("structured_error"),
    )
    error = _first_text(
        envelope.get("error"),
        item.get("error"),
        nested_tool_result.get("error"),
        parsed_text.get("error"),
        structured_error.get("message"),
    )
    return drop_empty(
        {
            "tool_result_ref": str(item.get("tool_result_ref") or item.get("observation_id") or ""),
            "envelope_id": str(envelope.get("envelope_id") or ""),
            "tool_name": str(envelope.get("tool_name") or item.get("tool_name") or parsed_text.get("tool_name") or ""),
            "tool_args": dict(envelope.get("tool_args") or item.get("tool_args") or {}),
            "status": status or ("error" if error or structured_error else "ok"),
            "text": str(text or ""),
            "structured_payload": structured,
            "structured_error": structured_error,
            "observed_paths": list(
                string_tuple(envelope.get("observed_paths") or structured.get("observed_paths") or item.get("observed_paths") or parsed_text.get("observed_paths"))
            ),
            "matched_paths": list(
                string_tuple(envelope.get("matched_paths") or structured.get("matched_paths") or item.get("matched_paths") or parsed_text.get("matched_paths"))
            ),
            "artifact_refs": list(dict_tuple(artifact_refs)),
            "command_receipt": dict(
                envelope.get("command_receipt") or structured.get("command_receipt") or item.get("command_receipt") or parsed_text.get("command_receipt") or {}
            ),
            "result_ref": str(envelope.get("result_ref") or item.get("result_ref") or parsed_text.get("result_ref") or ""),
            "content_range": dict(result_metadata.get("content_range") or {}),
            "tool_guidance": str(result_metadata.get("tool_guidance") or ""),
            "error": error,
        }
    )


def _parse_json_object(value: Any) -> dict[str, Any]:
    if not isinstance(value, str):
        return {}
    text = value.strip()
    if not text or text[0] not in "{[":
        return {}
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _merge_dicts(*values: Any) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for value in values:
        if isinstance(value, dict):
            merged.update(value)
    return drop_empty(merged)


def _read_file_metadata_from_structured(
    tool_result: dict[str, Any],
    structured: dict[str, Any],
    item: dict[str, Any],
    envelope: dict[str, Any],
) -> dict[str, Any]:
    tool_name = str(envelope.get("tool_name") or item.get("tool_name") or "").strip()
    if tool_name and tool_name != "read_file":
        return {}
    source = dict(tool_result or {})
    if str(source.get("kind") or "") != "text_file" and not {"start_line", "end_line", "total_lines"} & set(source):
        return {}
    path = str(source.get("path") or _first_string(envelope.get("observed_paths"), structured.get("observed_paths"), item.get("observed_paths")) or "").strip()
    content_range = drop_empty(
        {
            "path": path,
            "start_line": _int_or_none(source.get("start_line")),
            "end_line": _int_or_none(source.get("end_line")),
            "returned_lines": _int_or_none(source.get("returned_lines")),
            "total_lines": _int_or_none(source.get("total_lines")),
            "line_count": _int_or_none(source.get("line_count")),
            "next_start_line": _int_or_none(source.get("next_start_line")),
            "has_more": bool(source.get("has_more") or source.get("truncated")),
            "truncated": bool(source.get("truncated") or source.get("has_more")),
            "content_sha256": str(source.get("content_sha256") or "").strip(),
        }
    )
    if not content_range:
        return {}
    next_start_line = content_range.get("next_start_line")
    if content_range.get("has_more") and next_start_line is not None:
        guidance = (
            f"read_file 已返回 {path} 的第 {content_range.get('start_line')} 行到第 {content_range.get('end_line')} 行。"
            f"如仍需要后续内容，下一次应使用 start_line={next_start_line} 和 line_count={content_range.get('line_count') or ''}；不要重复读取相同行窗口。"
        )
    else:
        guidance = f"read_file 已读到 {path} 的当前可用结尾；不要重复读取相同行窗口。"
    return {"content_range": content_range, "tool_guidance": guidance}


def _first_string(*values: Any) -> str:
    for value in values:
        for item in list(value or []):
            text = str(item or "").strip()
            if text:
                return text
    return ""


def _int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _first_text(*values: Any) -> str:
    for value in values:
        if value in (None, "", [], {}):
            continue
        if isinstance(value, str):
            return value
        if isinstance(value, (int, float, bool)):
            return str(value)
        try:
            return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError):
            return str(value)
    return ""


def _status_from_ok(value: Any) -> str:
    if value is True:
        return "ok"
    if value is False:
        return "error"
    return ""


def model_visible_artifact_refs(refs: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ref in dict_tuple(refs):
        path = str(ref.get("path") or ref.get("src") or ref.get("artifact_ref") or "").strip()
        if not path:
            absolute_path = str(ref.get("absolute_path") or "").strip()
            if absolute_path and not _is_runtime_sandbox_path(absolute_path):
                path = absolute_path
        payload = drop_empty(
            {
                "path": path,
                "artifact_ref": str(ref.get("artifact_ref") or "") if ref.get("artifact_ref") and ref.get("artifact_ref") != path else "",
                "kind": str(ref.get("kind") or ""),
                "source": str(ref.get("source") or ""),
                "summary": compact_text(ref.get("summary") or "", limit=240),
                "mime_type": str(ref.get("mime_type") or ""),
                "exists": ref.get("exists") if isinstance(ref.get("exists"), bool) else None,
                "size_bytes": ref.get("size_bytes") if isinstance(ref.get("size_bytes"), int) else None,
                "published": ref.get("published") if isinstance(ref.get("published"), bool) else None,
            }
        )
        key = str(payload.get("path") or payload.get("artifact_ref") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(payload)
    return result


def _is_runtime_sandbox_path(path: str) -> bool:
    normalized = str(path or "").replace("\\", "/").lower()
    return "/storage/runtime_state/sandboxes/" in normalized or normalized.startswith("storage/runtime_state/sandboxes/")
