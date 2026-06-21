from __future__ import annotations

import json
from typing import Any

from .models import dict_tuple, drop_empty


_SUBAGENT_CONTROL_TOOL_NAMES = frozenset(
    {
        "start_subagent",
        "send_subagent_message",
        "collect_subagent_result",
        "observe_subagents",
        "stop_subagent",
    }
)
_CODE_LOCATOR_TOOL_NAMES = frozenset({"codebase_search", "search_text", "search_files", "glob_paths"})


def classify_normalized_tool_result(
    normalized: dict[str, Any],
    *,
    content_replacements: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
) -> dict[str, Any]:
    payload = dict(normalized or {})
    tool_name = _normalized_tool_name(payload.get("tool_name"))
    structured = dict(payload.get("structured_payload") or {})
    control = structured.get("subagent_control")
    pending_actions = _subagent_result_actions(
        control if isinstance(control, dict) else {},
        source_tool=tool_name,
        observation_ref=str(payload.get("tool_result_ref") or payload.get("envelope_id") or ""),
        tool_call_id=str(payload.get("tool_call_id") or ""),
        action_request_id=str(payload.get("action_request_id") or ""),
    )
    integrity_errors = _projection_integrity_errors(
        payload,
        tool_name=tool_name,
        has_structured_subagent_control=isinstance(control, dict),
    )
    classes: list[str] = []
    if pending_actions or tool_name in _SUBAGENT_CONTROL_TOOL_NAMES:
        classes.append("execution_control")
    if tool_name or payload.get("tool_call_id") or payload.get("action_request_id"):
        classes.append("tool_invocation_identity")
    if tool_name == "read_file" and isinstance(payload.get("content_range"), dict) and payload.get("content_range"):
        classes.append("edit_critical_source")
    if tool_name in _CODE_LOCATOR_TOOL_NAMES or payload.get("code_structure"):
        classes.append("code_locator_evidence")
    if content_replacements:
        classes.append("preview_only_output")
    return drop_empty(
        {
            "semantic_payload_class": _dedupe_strings(classes),
            "execution_control": _execution_control_projection(pending_actions),
            "tool_invocation_identity": _tool_invocation_identity(payload, tool_name=tool_name),
            "edit_critical_source": _edit_critical_source(payload, tool_name=tool_name),
            "code_locator_evidence": _code_locator_evidence(payload, tool_name=tool_name),
            "preview_only_output": _preview_only_output(
                payload,
                tool_name=tool_name,
                content_replacements=list(content_replacements or ()),
            ),
            "runtime_accounting": _runtime_accounting(payload),
            "projection_integrity_errors": integrity_errors,
            "authority": "harness.runtime.dynamic_context.semantic_payload_classifier",
        }
    )


def pending_subagent_result_actions_from_normalized_tool_result(normalized: dict[str, Any]) -> list[dict[str, Any]]:
    semantic = classify_normalized_tool_result(normalized)
    return [
        dict(item)
        for item in dict_tuple(dict(semantic.get("execution_control") or {}).get("pending_subagent_result_actions"))
    ]


def pending_subagent_result_actions_from_observation(observation: dict[str, Any]) -> list[dict[str, Any]]:
    source = _source_observation_payload(observation)
    payload = dict(source.get("payload") or {})
    envelope = dict(payload.get("result_envelope") or source.get("result_envelope") or {})
    identity_source = envelope if envelope else payload
    structured = _merge_dicts(payload.get("structured_payload"), envelope.get("structured_payload"))
    control = structured.get("subagent_control")
    return _subagent_result_actions(
        control if isinstance(control, dict) else {},
        source_tool=_tool_name(source=source, payload=payload, envelope=envelope),
        observation_ref=str(source.get("observation_id") or observation.get("observation_id") or source.get("observation_ref") or ""),
        tool_call_id=str(identity_source.get("tool_call_id") or ""),
        action_request_id=str(identity_source.get("action_request_id") or ""),
    )


def merge_pending_subagent_result_actions(*groups: Any, limit: int = 12) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for group in groups:
        for item in dict_tuple(group):
            action = _subagent_result_action_projection(item)
            if not action:
                continue
            key = _subagent_result_action_key(action)
            if key in seen:
                continue
            seen.add(key)
            result.append(action)
    return result[-max(1, int(limit or 12)) :]


def _subagent_result_actions(
    control: Any,
    *,
    source_tool: str,
    observation_ref: str,
    tool_call_id: str,
    action_request_id: str,
) -> list[dict[str, Any]]:
    if not isinstance(control, dict):
        return []
    actions: list[dict[str, Any]] = []
    for row in dict_tuple(control.get("subagents")):
        result_state = str(row.get("result_state") or "").strip()
        result_unread = row.get("result_unread") is True or result_state == "unread"
        if not result_unread:
            continue
        args = dict(row.get("collect_subagent_result_args") or {})
        subagent_run_ref = str(args.get("subagent_run_ref") or row.get("subagent_run_ref") or "").strip()
        if not subagent_run_ref:
            continue
        result_ref = str(row.get("result_ref") or "").strip()
        actions.append(
            _subagent_result_action_projection(
                {
                    "source_tool": source_tool,
                    "observation_ref": observation_ref,
                    "tool_call_id": tool_call_id,
                    "action_request_id": action_request_id,
                    "action": "collect_subagent_result",
                    "args": {"subagent_run_ref": subagent_run_ref},
                    "reason": "subagent_result_unread",
                    "result_ref": result_ref,
                    "result_state": "unread",
                    "result_unread": True,
                    "result_available": True,
                    "subagent_status": str(row.get("status") or ""),
                    "result_read_authority": str(row.get("result_read_authority") or "collect_subagent_result"),
                    "forbidden_action": "read_persisted_tool_result_with_result_ref",
                    "result_ref_usage": str(row.get("result_ref_usage") or ""),
                    "authority": "runtime.execution_control.subagent_result",
                }
            )
        )
    return merge_pending_subagent_result_actions(actions)


def _subagent_result_action_projection(value: dict[str, Any]) -> dict[str, Any]:
    args = dict(value.get("args") or value.get("collect_subagent_result_args") or {})
    subagent_run_ref = str(args.get("subagent_run_ref") or value.get("subagent_run_ref") or "").strip()
    action = str(value.get("action") or "").strip()
    if action == "collect_subagent_result" and not subagent_run_ref:
        return {}
    return drop_empty(
        {
            "source_tool": str(value.get("source_tool") or ""),
            "observation_ref": str(value.get("observation_ref") or ""),
            "tool_call_id": str(value.get("tool_call_id") or ""),
            "action_request_id": str(value.get("action_request_id") or ""),
            "action": action,
            "args": {"subagent_run_ref": subagent_run_ref} if subagent_run_ref else dict(args),
            "reason": str(value.get("reason") or ""),
            "result_ref": str(value.get("result_ref") or ""),
            "result_state": str(value.get("result_state") or ""),
            "result_unread": value.get("result_unread") if isinstance(value.get("result_unread"), bool) else None,
            "result_available": value.get("result_available") if isinstance(value.get("result_available"), bool) else None,
            "subagent_status": str(value.get("subagent_status") or ""),
            "result_read_authority": str(value.get("result_read_authority") or ""),
            "forbidden_action": str(value.get("forbidden_action") or ""),
            "result_ref_usage": str(value.get("result_ref_usage") or ""),
            "authority": str(value.get("authority") or "runtime.execution_control"),
        }
    )


def _execution_control_projection(pending_actions: list[dict[str, Any]]) -> dict[str, Any]:
    if not pending_actions:
        return {}
    return {
        "pending_subagent_result_actions": pending_actions,
        "authority": "runtime.execution_control.semantic_payload_classifier",
    }


def _tool_invocation_identity(payload: dict[str, Any], *, tool_name: str) -> dict[str, Any]:
    return drop_empty(
        {
            "tool_result_ref": str(payload.get("tool_result_ref") or payload.get("envelope_id") or ""),
            "tool_name": tool_name,
            "tool_call_id": str(payload.get("tool_call_id") or ""),
            "action_request_id": str(payload.get("action_request_id") or ""),
            "operation_id": str(payload.get("operation_id") or ""),
            "authority": "runtime.tool_invocation_identity",
        }
    )


def _edit_critical_source(payload: dict[str, Any], *, tool_name: str) -> dict[str, Any]:
    content_range = dict(payload.get("content_range") or {})
    if tool_name != "read_file" or not content_range:
        return {}
    return drop_empty(
        {
            "source_kind": "edit_critical_source",
            "source_authority": "read_file_line_window",
            "visible_content_authority": "exact_visible_line_window",
            "candidate_only": False,
            "content_range": content_range,
            "authority": "runtime.source_evidence.read_file_window",
        }
    )


def _code_locator_evidence(payload: dict[str, Any], *, tool_name: str) -> dict[str, Any]:
    if tool_name not in _CODE_LOCATOR_TOOL_NAMES and not payload.get("code_structure"):
        return {}
    return {
        "source_kind": "code_locator",
        "source_authority": "locator_only",
        "candidate_only": True,
        "must_read_source_before_edit": True,
        "rehydration_preference": "read_file",
        "authority": "runtime.source_evidence.locator_only",
    }


def _preview_only_output(
    payload: dict[str, Any],
    *,
    tool_name: str,
    content_replacements: list[dict[str, Any]],
) -> dict[str, Any]:
    if not content_replacements:
        return {}
    return {
        "source_kind": "preview_only_output",
        "source_authority": "preview_only",
        "tool_name": tool_name,
        "replacement_count": len(content_replacements),
        "authority": "runtime.tool_output.preview_only",
    }


def _runtime_accounting(payload: dict[str, Any]) -> dict[str, Any]:
    accounting = dict(payload.get("runtime_accounting") or {})
    return drop_empty(
        {
            "cache_hit": accounting.get("cache_hit") if isinstance(accounting.get("cache_hit"), bool) else None,
            "cached_tokens": accounting.get("cached_tokens"),
            "context_pressure": accounting.get("context_pressure"),
            "model_visible": False,
            "authority": "runtime.accounting.diagnostics_only",
        }
    )


def _projection_integrity_errors(
    payload: dict[str, Any],
    *,
    tool_name: str,
    has_structured_subagent_control: bool,
) -> list[dict[str, Any]]:
    if tool_name not in _SUBAGENT_CONTROL_TOOL_NAMES or has_structured_subagent_control:
        return []
    candidate = _json_payload(payload.get("text"))
    if not _looks_like_subagent_control(candidate):
        return []
    return [
        {
            "code": "structured_subagent_control_missing",
            "tool_name": tool_name,
            "message": "Subagent control fields appeared only in text output; execution control was not projected from text.",
            "not_authoritative_sources": ["text", "result_preview", "summary"],
            "required_source": "result_envelope.structured_payload.subagent_control",
            "authority": "harness.runtime.dynamic_context.semantic_payload_integrity",
        }
    ]


def _looks_like_subagent_control(value: dict[str, Any]) -> bool:
    if not isinstance(value, dict) or not value:
        return False
    if isinstance(value.get("subagents"), list):
        return True
    return any(
        key in value
        for key in (
            "subagent_run_ref",
            "result_available",
            "result_unread",
            "collect_subagent_result_args",
        )
    )


def _subagent_result_action_key(action: dict[str, Any]) -> str:
    args = dict(action.get("args") or {})
    result_ref = str(action.get("result_ref") or "").strip()
    return "|".join(
        (
            str(action.get("action") or ""),
            str(args.get("subagent_run_ref") or ""),
            result_ref,
        )
    )


def _source_observation_payload(observation: dict[str, Any]) -> dict[str, Any]:
    item = dict(observation or {})
    wrapped = dict(item.get("observation") or {})
    return wrapped if wrapped else item


def _merge_dicts(*values: Any) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for value in values:
        if isinstance(value, dict):
            merged.update(value)
    return merged


def _tool_name(*, source: dict[str, Any], payload: dict[str, Any], envelope: dict[str, Any]) -> str:
    raw_source = str(source.get("source") or "")
    source_name = raw_source.split(":", 1)[1].strip() if raw_source.startswith("tool:") else raw_source
    return _normalized_tool_name(envelope.get("tool_name") or payload.get("tool_name") or source.get("tool_name") or source_name or "")


def _normalized_tool_name(value: Any) -> str:
    text = str(value or "").strip()
    return text.split(":", 1)[1].strip() if text.startswith("tool:") else text


def _json_payload(value: Any) -> dict[str, Any]:
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


def _dedupe_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result
