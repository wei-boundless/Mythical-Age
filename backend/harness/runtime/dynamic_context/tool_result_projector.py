from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from artifact_system.artifact_authority import artifact_refs_from_tool_result_payload, model_visible_artifact_refs
from runtime_objects.tool_result_storage import DEFAULT_PREVIEW_SIZE_BYTES, ToolResultStore

from .models import compact_text, dict_tuple, drop_empty, stable_json_hash, string_tuple
from .replacement_store import ReplacementStore
from .semantic_payload_classifier import classify_normalized_tool_result
from .structured_error_projection import structured_error_projection
from .todo_plan_projection import DEFAULT_TODO_OPERATIONS, project_todo_plan


PROJECTOR_VERSION = "tool_result_projector.v3"

_CODE_LOCATOR_TOOL_NAMES = frozenset({"codebase_search", "search_text"})


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
        frozen = self.replacement_store.get_frozen(
            source_kind="tool_result",
            source_id=source_id,
            task_run_id=task_run_id,
            content=normalized,
            projection_policy=policy,
            projector_version=PROJECTOR_VERSION,
        )
        if frozen is not None:
            projection, record = frozen
            return projection, record.to_dict()
        projection, budget_decision = self._build_projection(normalized, task_run_id=task_run_id, projection_policy=policy)
        projection, record = self.replacement_store.get_or_put(
            source_kind="tool_result",
            source_id=source_id,
            task_run_id=task_run_id,
            content=normalized,
            projection_policy=policy,
            projector_version=PROJECTOR_VERSION,
            projection=projection,
            budget_decision=budget_decision,
        )
        return projection, record.to_dict()

    def _build_projection(
        self,
        normalized: dict[str, Any],
        *,
        task_run_id: str,
        projection_policy: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        text = str(normalized.get("text") or "")
        preview_limit = int(projection_policy.get("tool_result_preview_chars") or DEFAULT_PREVIEW_SIZE_BYTES)
        content_replacements: list[dict[str, Any]] = []
        preview = _preview_text_for_tool(normalized, limit=preview_limit)
        result_ref = str(normalized.get("result_ref") or "")
        if not _is_read_file_result(normalized) and len(text.encode("utf-8", errors="ignore")) > preview_limit:
            store = ToolResultStore(self.root_dir, run_id=task_run_id or "session", namespace="runtime_context")
            budgeted, replacements = store.apply_budget(
                {"text": text},
                field_limit_bytes=preview_limit,
                preview_size_bytes=preview_limit,
                payload_budget_bytes=max(preview_limit * 2, preview_limit + 1000),
                replacement_metadata=_replacement_source_metadata(normalized),
            )
            preview = str(budgeted.get("text") or preview)
            content_replacements = [item.to_dict() for item in replacements]
            if content_replacements and not result_ref:
                result_ref = str(content_replacements[0].get("path") or content_replacements[0].get("replacement_id") or "")
        evidence_policy = _evidence_policy(normalized, content_replacements=content_replacements)
        evidence_confidence = _evidence_confidence(
            normalized,
            evidence_policy=evidence_policy,
            content_replacements=content_replacements,
        )
        structured_error = dict(normalized.get("structured_error") or {})
        error = str(normalized.get("error") or structured_error.get("message") or structured_error.get("detail") or "")
        rehydration_plan = _build_rehydration_plan(
            normalized=normalized,
            result_ref=result_ref,
            content_replacements=content_replacements,
            task_run_id=task_run_id,
        )
        semantic_projection = classify_normalized_tool_result(
            normalized,
            content_replacements=content_replacements,
        )
        projection = drop_empty(
            {
                "tool_result_ref": str(normalized.get("tool_result_ref") or normalized.get("envelope_id") or ""),
                "tool_name": str(normalized.get("tool_name") or ""),
                "tool_call_id": str(normalized.get("tool_call_id") or ""),
                "action_request_id": str(normalized.get("action_request_id") or ""),
                "status": str(normalized.get("status") or ("error" if error else "ok")),
                "semantic_payload_class": list(semantic_projection.get("semantic_payload_class") or []),
                "execution_control": dict(semantic_projection.get("execution_control") or {}),
                "tool_invocation_identity": dict(semantic_projection.get("tool_invocation_identity") or {}),
                "edit_critical_source": dict(semantic_projection.get("edit_critical_source") or {}),
                "code_locator_evidence": dict(semantic_projection.get("code_locator_evidence") or {}),
                "preview_only_output": dict(semantic_projection.get("preview_only_output") or {}),
                "projection_integrity_errors": list(semantic_projection.get("projection_integrity_errors") or []),
                "preview": preview,
                "result_ref": result_ref,
                "todo_plan": _todo_plan_from_normalized_tool_result(normalized),
                "structured_error": structured_error_projection(structured_error),
                "error": compact_text(error, limit=500),
                "artifact_refs": model_visible_artifact_refs(normalized.get("artifact_refs")),
                "observed_paths": list(string_tuple(normalized.get("observed_paths"))),
                "matched_paths": list(string_tuple(normalized.get("matched_paths"))),
                "command_receipt": dict(normalized.get("command_receipt") or {}),
                "code_structure": _compact_code_structure(normalized.get("code_structure")),
                "content_range": dict(normalized.get("content_range") or {}),
                "evidence_policy": evidence_policy,
                "evidence_confidence": evidence_confidence,
                "content_replacements": content_replacements,
                "rehydration_plan": rehydration_plan,
                "authority": "harness.runtime.dynamic_context.tool_result_projection",
            }
        )
        budget_decision = _tool_result_budget_decision(
            normalized=normalized,
            projection_policy=projection_policy,
            preview_limit=preview_limit,
            preview=preview,
            content_replacements=content_replacements,
            rehydration_plan=rehydration_plan,
        )
        return projection, budget_decision


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
    parsed_structured_payload.pop("subagent_control", None)
    structured = _merge_dicts(parsed_structured_payload, envelope.get("structured_payload"), item.get("structured_payload"))
    nested_tool_result = _merge_dicts(parsed_tool_result, structured.get("tool_result"))
    result_metadata = _merge_dicts(item.get("result_metadata"), _read_file_metadata_from_structured(nested_tool_result, structured, item, envelope))
    artifact_refs = artifact_refs_from_tool_result_payload(item)
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
            "tool_name": _normalized_tool_name(envelope.get("tool_name") or item.get("tool_name") or parsed_text.get("tool_name") or ""),
            "tool_call_id": str(envelope.get("tool_call_id") or item.get("tool_call_id") or parsed_text.get("tool_call_id") or ""),
            "action_request_id": str(envelope.get("action_request_id") or item.get("action_request_id") or parsed_text.get("action_request_id") or ""),
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
            "code_structure": dict(envelope.get("code_structure") or item.get("code_structure") or parsed_text.get("code_structure") or structured.get("code_structure") or {}),
            "content_range": dict(result_metadata.get("content_range") or {}),
            "todo_plan": _todo_plan_from_parsed_text(parsed_text, envelope=envelope, item=item),
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
    tool_name = _normalized_tool_name(envelope.get("tool_name") or item.get("tool_name") or "")
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
            "mtime_ns": _int_or_none(source.get("mtime_ns")),
            "reusable_result_ref": str(source.get("reusable_result_ref") or "").strip(),
            "exact_artifact_ref": str(source.get("exact_artifact_ref") or "").strip(),
            "artifact_ref_status": str(source.get("artifact_ref_status") or "").strip(),
            "visible_exact": source.get("visible_exact") if isinstance(source.get("visible_exact"), bool) else None,
            "text_sha256": str(source.get("text_sha256") or "").strip(),
        }
    )
    if not content_range:
        return {}
    return {"content_range": content_range}


def _todo_plan_from_parsed_text(
    parsed_text: dict[str, Any],
    *,
    envelope: dict[str, Any],
    item: dict[str, Any],
) -> dict[str, Any]:
    tool_name = _normalized_tool_name(envelope.get("tool_name") or item.get("tool_name") or parsed_text.get("tool_name") or "")
    if tool_name != "agent_todo":
        return {}
    if str(parsed_text.get("status") or "") == "error":
        return {}
    if not isinstance(parsed_text.get("items"), list):
        return {}
    return project_todo_plan(
        parsed_text,
        content_keys=("content",),
        allowed_operations=DEFAULT_TODO_OPERATIONS,
        authority="agent.todo_plan",
    )


def _todo_plan_from_normalized_tool_result(normalized: dict[str, Any]) -> dict[str, Any]:
    source = dict(normalized.get("todo_plan") or {})
    if not source and _normalized_tool_name(normalized.get("tool_name")) == "agent_todo":
        parsed = _parse_json_object(normalized.get("text"))
        if isinstance(parsed.get("items"), list):
            source = parsed
    return project_todo_plan(
        source,
        content_keys=("content",),
        allowed_operations=DEFAULT_TODO_OPERATIONS,
        authority="agent.todo_plan",
    )


def _build_rehydration_plan(
    *,
    normalized: dict[str, Any],
    result_ref: str,
    content_replacements: list[dict[str, Any]],
    task_run_id: str,
) -> dict[str, Any]:
    capabilities: list[dict[str, Any]] = []
    if content_replacements:
        request = _persisted_tool_result_request(content_replacements, task_run_id=task_run_id)
        persisted_instruction = (
            "The prompt contains only a preview of this non-code tool output. "
            "Use the persisted result reference only when exact omitted output is required."
        )
        capabilities.append(
            drop_empty(
                {
                    "capability": "read_persisted_tool_result",
                    "source": "runtime_context.tool_result_store",
                    "tool_name": request.get("tool_name"),
                    "args": request.get("args"),
                    "next_request": request,
                    "result_ref": str(result_ref or ""),
                    "content_replacements": [_replacement_rehydration_ref(item) for item in content_replacements],
                    "instruction": persisted_instruction,
                }
            )
        )
    content_range = dict(normalized.get("content_range") or {})
    if content_range:
        coverage = _read_file_coverage(content_range)
        capabilities.append(
            drop_empty(
                {
                    "capability": "read_file_range",
                    "source": "workspace.read_file",
                    "content_range": content_range,
                    "coverage": coverage,
                    "full_file_window": coverage == "full_file",
                    "instruction": _read_file_range_instruction(content_range),
                }
            )
        )
    if not capabilities:
        return {}
    return drop_empty(
        {
            "authority": "harness.runtime.dynamic_context.rehydration_plan",
            "source_kind": "tool_result",
            "tool_result_ref": str(normalized.get("tool_result_ref") or normalized.get("envelope_id") or ""),
            "tool_name": str(normalized.get("tool_name") or ""),
            "result_ref": str(result_ref or ""),
            "prompt_status": _prompt_status(
                has_persisted_output=bool(content_replacements),
                has_content_range=bool(content_range),
            ),
            "capabilities": capabilities,
            "instruction": (
                "Treat preview text as evidence preview only; for non-code omitted output, rehydrate before relying "
                "on exact content. For code edits, use current exact read_file evidence or read the current target window."
            ),
        }
    )


def _tool_result_budget_decision(
    *,
    normalized: dict[str, Any],
    projection_policy: dict[str, Any],
    preview_limit: int,
    preview: str,
    content_replacements: list[dict[str, Any]],
    rehydration_plan: dict[str, Any],
) -> dict[str, Any]:
    tool_name = _normalized_tool_name(normalized.get("tool_name"))
    text = str(normalized.get("text") or "")
    return drop_empty(
        {
            "frozen": True,
            "model_visible": False,
            "decision_kind": _budget_decision_kind(tool_name=tool_name, content_replacements=content_replacements),
            "tool_name": tool_name,
            "input_size_bytes": _encoded_size(text),
            "preview_limit_bytes": max(1, int(preview_limit or DEFAULT_PREVIEW_SIZE_BYTES)),
            "preview_size_bytes": _encoded_size(preview),
            "replacement_count": len(content_replacements),
            "content_replacements": [_replacement_budget_ref(item) for item in content_replacements],
            "rehydration_capabilities": [
                str(item.get("capability") or "")
                for item in list(dict(rehydration_plan or {}).get("capabilities") or [])
                if isinstance(item, dict) and str(item.get("capability") or "")
            ],
            "projection_policy_hash": stable_json_hash(projection_policy),
            "authority": "harness.runtime.dynamic_context.tool_result_budget_decision",
        }
    )


def _budget_decision_kind(*, tool_name: str, content_replacements: list[dict[str, Any]]) -> str:
    if tool_name == "read_file":
        return "exact_read_file_output"
    if content_replacements:
        return "persisted_preview"
    return "inline_preview"


def _replacement_budget_ref(item: dict[str, Any]) -> dict[str, Any]:
    return drop_empty(
        {
            "replacement_id": _tool_result_replacement_id(item.get("replacement_id")),
            "json_path": str(item.get("json_path") or ""),
            "original_size_bytes": item.get("original_size_bytes"),
            "preview_size_bytes": item.get("preview_size_bytes"),
            "has_more": item.get("has_more") if isinstance(item.get("has_more"), bool) else None,
        }
    )


def _encoded_size(value: Any) -> int:
    return len(str(value or "").encode("utf-8", errors="replace"))


def _preview_text_for_tool(normalized: dict[str, Any], *, limit: int) -> str:
    text = str(normalized.get("text") or "")
    if _is_read_file_result(normalized):
        return text
    return compact_text(text, limit=limit)


def _compact_code_preview(value: Any, *, limit: int) -> str:
    text = str(value or "")
    if limit <= 0 or len(text) <= limit:
        return text
    return text[: max(0, limit - 25)].rstrip() + "\n... <preview truncated>"


def _evidence_policy(normalized: dict[str, Any], *, content_replacements: list[dict[str, Any]]) -> dict[str, Any]:
    tool_name = _normalized_tool_name(normalized.get("tool_name"))
    content_range = dict(normalized.get("content_range") or {})
    if tool_name == "read_file" and content_range:
        exact_artifact_ref = str(content_range.get("exact_artifact_ref") or "").strip()
        fresh_read_conditions = _fresh_read_conditions_for_read_file(
            content_range=content_range,
            content_replacements=content_replacements,
        )
        coverage = _read_file_coverage(content_range)
        return drop_empty(
            {
                "source_kind": "code_evidence",
                "source_authority": "read_file_line_window",
                "visible_content_authority": "exact_visible_line_window",
                "coverage": coverage,
                "full_file_window": coverage == "full_file",
                "candidate_only": False,
                "usable_as_evidence_for": _read_file_usable_as_evidence_for(fresh_read_conditions),
                "fresh_read_conditions": fresh_read_conditions,
                "rehydration_preference": (
                    "read_observation_artifact"
                    if exact_artifact_ref
                    else "reuse_visible_read_file_window"
                ),
                "instruction": _read_file_evidence_instruction(content_range),
            }
        )
    if tool_name in _CODE_LOCATOR_TOOL_NAMES or normalized.get("code_structure"):
        return {
            "source_kind": "code_locator",
            "source_authority": "locator_only",
            "candidate_only": True,
            "must_read_source_before_edit": True,
            "rehydration_preference": "read_file",
            "instruction": "Use paths and ranges to choose read_file calls; do not edit from snippets, summaries, or search previews.",
        }
    if content_replacements:
        return {
            "source_kind": "tool_output_preview",
            "source_authority": "preview_only",
            "rehydration_preference": "read_persisted_tool_result",
            "usable_as_evidence_for": ["omitted_tool_output_recovery"],
            "instruction": (
                "Use visible answer/text fields directly when they are sufficient. Only call "
                "read_persisted_tool_result for omitted exact output, and only with replacement_id values from "
                "rehydration_plan.content_replacements that start with tool_result:; never pass attachment paths, "
                "file paths, or internal dynamic-context replacement refs as replacement_id."
            ),
        }
    return {}


def _fresh_read_conditions_for_read_file(
    *,
    content_range: dict[str, Any],
    content_replacements: list[dict[str, Any]],
) -> list[str]:
    conditions: list[str] = []
    _ = content_replacements
    if bool(content_range.get("has_more") or content_range.get("truncated")):
        conditions.append("target_line_outside_visible_range")
    if not str(content_range.get("content_sha256") or "").strip():
        conditions.append("content_hash_missing")
    return conditions


def _read_file_coverage(content_range: dict[str, Any]) -> str:
    return "full_file" if _read_file_window_covers_full_file(content_range) else "partial_file_window"


def _read_file_window_covers_full_file(content_range: dict[str, Any]) -> bool:
    start_line = _int_or_none(content_range.get("start_line"))
    end_line = _int_or_none(content_range.get("end_line"))
    total_lines = _int_or_none(content_range.get("total_lines"))
    if start_line != 1 or end_line is None or total_lines is None:
        return False
    if bool(content_range.get("has_more") or content_range.get("truncated")):
        return False
    return end_line >= total_lines


def _read_file_range_instruction(content_range: dict[str, Any]) -> str:
    if _read_file_window_covers_full_file(content_range):
        return (
            "This read_file result covers the full current file: start_line is 1, end_line reaches total_lines, "
            "and has_more is false. Reuse this observation for planning unless a later write/edit makes the file "
            "state stale; read again only when current changed content is needed."
        )
    return (
        "This read_file result is a line window, not proof that the whole file is in prompt. "
        "Read another range only if the current target lines are outside this window. For code edits or error localization, reuse this "
        "window only when exact content is visible or backed by an exact read observation artifact; read_file "
        "again for stale files, changed files, missing artifacts, or target lines outside this window."
    )


def _read_file_evidence_instruction(content_range: dict[str, Any]) -> str:
    if _read_file_window_covers_full_file(content_range):
        return (
            "This describes an exact read_file window that covers the full current file. "
            "No additional read is needed for the same unchanged file content; use fresh_read_conditions "
            "to detect whether a later edit/write requires a new current read."
        )
    return (
        "This describes a read_file line window. Use it directly only when exact content is visible in the "
        "prompt or the context assembly injects the exact read observation artifact; otherwise call read_file "
        "for the current target range."
    )


def _read_file_usable_as_evidence_for(fresh_read_conditions: list[str]) -> list[str]:
    base = ["line_reference", "architecture_planning", "symbol_location"]
    if not fresh_read_conditions:
        return [*base, "edit_planning"]
    return base


def _evidence_confidence(
    normalized: dict[str, Any],
    *,
    evidence_policy: dict[str, Any],
    content_replacements: list[dict[str, Any]],
) -> dict[str, Any]:
    tool_name = _normalized_tool_name(normalized.get("tool_name"))
    content_range = dict(normalized.get("content_range") or {})
    if tool_name == "read_file" and content_range:
        return drop_empty(
            {
                "authority": "harness.runtime.dynamic_context.evidence_confidence",
                "source_kind": "read_file_line_window",
                "tool_name": tool_name,
                "confidence": "current_line_window",
                "coverage": _read_file_coverage(content_range),
                "full_file_window": _read_file_window_covers_full_file(content_range),
                "files": [
                    drop_empty(
                        {
                            "path": str(content_range.get("path") or ""),
                            "start_line": content_range.get("start_line"),
                            "end_line": content_range.get("end_line"),
                            "line_count": content_range.get("line_count"),
                            "coverage": _read_file_coverage(content_range),
                            "full_file_window": _read_file_window_covers_full_file(content_range),
                            "content_sha256": str(content_range.get("content_sha256") or ""),
                            "exact_artifact_ref": str(content_range.get("exact_artifact_ref") or ""),
                            "visible_exact": content_range.get("visible_exact") if isinstance(content_range.get("visible_exact"), bool) else None,
                            "fresh_read_conditions": list(evidence_policy.get("fresh_read_conditions") or []),
                            "usable_as_evidence_for": list(evidence_policy.get("usable_as_evidence_for") or []),
                        }
                    )
                ],
            }
        )
    if tool_name in _CODE_LOCATOR_TOOL_NAMES or normalized.get("code_structure"):
        return {
            "authority": "harness.runtime.dynamic_context.evidence_confidence",
            "source_kind": "code_locator",
            "tool_name": tool_name,
            "confidence": "locator_only",
            "fresh_read_conditions": ["read_file_required_before_edit"],
            "usable_as_evidence_for": ["path_selection", "symbol_location"],
        }
    return {}


def _is_read_file_result(normalized: dict[str, Any]) -> bool:
    return _normalized_tool_name(normalized.get("tool_name")) == "read_file"


def _is_read_file_window(normalized: dict[str, Any]) -> bool:
    return _is_read_file_result(normalized) and bool(dict(normalized.get("content_range") or {}))


def _normalized_tool_name(value: Any) -> str:
    text = str(value or "").strip()
    return text.removeprefix("tool:").strip()


def _persisted_tool_result_request(content_replacements: list[dict[str, Any]], *, task_run_id: str) -> dict[str, Any]:
    if not content_replacements:
        return {}
    _ = task_run_id
    first = dict(content_replacements[0] or {})
    replacement_id = _tool_result_replacement_id(first.get("replacement_id"))
    args = drop_empty(
        {
            "replacement_id": replacement_id,
            "path": str(first.get("path") or ""),
        }
    )
    if not args:
        return {}
    return {"tool_name": "read_persisted_tool_result", "args": args}


def _replacement_rehydration_ref(item: dict[str, Any]) -> dict[str, Any]:
    return drop_empty(
        {
            "replacement_id": _tool_result_replacement_id(item.get("replacement_id")),
            "path": str(item.get("path") or ""),
            "json_path": str(item.get("json_path") or ""),
            "original_size_bytes": item.get("original_size_bytes"),
            "preview_size_bytes": item.get("preview_size_bytes"),
            "has_more": item.get("has_more") if isinstance(item.get("has_more"), bool) else None,
            "source_metadata": dict(item.get("metadata") or {}),
        }
    )


def _replacement_source_metadata(normalized: dict[str, Any]) -> dict[str, Any]:
    tool_name = _normalized_tool_name(normalized.get("tool_name"))
    if tool_name != "read_file":
        return {}
    content_range = dict(normalized.get("content_range") or {})
    if not content_range:
        return {}
    return drop_empty(
        {
            "source_tool_name": "read_file",
            "source_tool_result_ref": str(normalized.get("tool_result_ref") or normalized.get("envelope_id") or ""),
            "source_tool_call_id": str(normalized.get("tool_call_id") or ""),
            "content_range": content_range,
            "authority": "harness.runtime.dynamic_context.tool_result_rehydration_metadata",
        }
    )


def _tool_result_replacement_id(value: Any) -> str:
    candidate = str(value or "").strip()
    return candidate if candidate.startswith("tool_result:") else ""


def _prompt_status(*, has_persisted_output: bool, has_content_range: bool) -> str:
    if has_persisted_output and has_content_range:
        return "preview_and_file_window_only"
    if has_persisted_output:
        return "preview_only"
    return "file_window_only"


def _compact_code_structure(value: Any) -> dict[str, Any]:
    source = dict(value) if isinstance(value, dict) else {}
    if not source:
        return {}
    files: list[dict[str, Any]] = []
    for file_item in dict_tuple(source.get("files"))[:16]:
        slices = []
        for slice_item in dict_tuple(file_item.get("slices"))[:8]:
            slices.append(
                drop_empty(
                    {
                        "evidence_ref": str(slice_item.get("evidence_ref") or ""),
                        "matched_line": _int_or_none(slice_item.get("matched_line")),
                        "start_line": _int_or_none(slice_item.get("start_line")),
                        "end_line": _int_or_none(slice_item.get("end_line")),
                        "symbol": str(slice_item.get("symbol") or ""),
                        "evidence_kind": str(slice_item.get("evidence_kind") or ""),
                        "score": slice_item.get("score"),
                        "read_request": dict(slice_item.get("read_request") or {}),
                    }
                )
            )
        files.append(
            drop_empty(
                {
                    "path": str(file_item.get("path") or ""),
                    "candidate_only": file_item.get("candidate_only") if isinstance(file_item.get("candidate_only"), bool) else True,
                    "must_read_source_before_edit": (
                        file_item.get("must_read_source_before_edit")
                        if isinstance(file_item.get("must_read_source_before_edit"), bool)
                        else True
                    ),
                    "evidence_refs": list(string_tuple(file_item.get("evidence_refs"))),
                    "slices": slices,
                }
            )
        )
    return drop_empty(
        {
            "authority": str(source.get("authority") or "capability.codebase_search.code_structure_map"),
            "source_kind": str(source.get("source_kind") or "codebase_search"),
            "candidate_only": source.get("candidate_only") if isinstance(source.get("candidate_only"), bool) else True,
            "source_authority": str(source.get("source_authority") or "locator_only"),
            "instruction": compact_text(
                source.get("instruction")
                or "Use code structure paths and line ranges to choose read_file calls; snippets are not complete source.",
                limit=300,
            ),
            "files": files,
            "limitations": list(string_tuple(source.get("limitations")))[:8],
        }
    )


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
