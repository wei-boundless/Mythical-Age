from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from core.project_layout import ProjectLayout


CONTEXT_COMMIT_RECORD_SCHEMA_VERSION = 1


def create_session_context_commit_record(
    *,
    storage_root: Path | str | None,
    session_id: str,
    session_payload: dict[str, Any],
    provider_visible_anchor: dict[str, Any] | None = None,
    reason: str = "session_snapshot",
) -> dict[str, Any]:
    normalized_session_id = str(session_id or "").strip()
    payload = dict(session_payload or {})
    public_messages = [dict(item) for item in list(payload.get("messages") or []) if isinstance(item, dict)]
    api_transcript = [dict(item) for item in list(payload.get("api_transcript") or []) if isinstance(item, dict)]
    compressed_context = str(payload.get("compressed_context") or "")
    anchor = dict(provider_visible_anchor or {})
    seed = {
        "session_id": normalized_session_id,
        "public_message_count": len(public_messages),
        "api_transcript_count": len(api_transcript),
        "last_public_message_hash": _message_hash(public_messages[-1]) if public_messages else "",
        "last_api_message_hash": _message_hash(api_transcript[-1]) if api_transcript else "",
        "compressed_context_hash": _text_hash(compressed_context) if compressed_context else "",
        "provider_visible_anchor_id": str(anchor.get("anchor_id") or ""),
        "provider_visible_terminal_hash": str(anchor.get("terminal_cumulative_prefix_hash") or ""),
        "reason": str(reason or ""),
    }
    record_hash = _stable_json_hash(seed)
    record = {
        "schema_version": CONTEXT_COMMIT_RECORD_SCHEMA_VERSION,
        "record_id": "ctxcommit:" + record_hash.removeprefix("sha256:")[:16],
        "record_hash": record_hash,
        "session_id": normalized_session_id,
        "turn_id": _last_turn_id(public_messages, api_transcript),
        "public_message_count": len(public_messages),
        "api_transcript_count": len(api_transcript),
        "compressed_context_hash": seed["compressed_context_hash"],
        "provider_visible_ledger_anchor": anchor,
        "cache_spine_hash": str(
            anchor.get("provider_payload_prefix_hash")
            or anchor.get("terminal_cumulative_prefix_hash")
            or ""
        ),
        "compaction_generation": str(payload.get("compaction_generation") or ""),
        "reason": str(reason or "session_snapshot"),
        "created_at": time.time(),
        "authority": "runtime.context_management.context_commit_record",
    }
    path = context_commit_record_path(storage_root=storage_root, session_id=normalized_session_id, record_id=record["record_id"])
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(_json_stable(record), ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
    return record


def create_provider_request_context_commit_record(
    *,
    storage_root: Path | str | None,
    session_id: str,
    request_id: str,
    status: str,
    model_request: Any,
    provider_visible_anchor_before: dict[str, Any] | None = None,
    provider_visible_confirmation: dict[str, Any] | None = None,
    response_ref: str = "",
    error: BaseException | dict[str, Any] | str | None = None,
    reason: str = "provider_request",
) -> dict[str, Any]:
    normalized_session_id = str(session_id or "").strip()
    normalized_request_id = str(request_id or "").strip()
    request_payload = _model_request_projection(model_request)
    tool_context = _tool_context_projection(model_request)
    confirmation = dict(provider_visible_confirmation or {})
    anchor_before = dict(provider_visible_anchor_before or {})
    anchor_after = _provider_visible_anchor_after(confirmation) or anchor_before
    error_payload = _error_payload(error)
    provider_payload_segments = [
        dict(item)
        for item in list(request_payload.get("provider_payload_segments") or [])
        if isinstance(item, dict)
    ]
    provider_payload_segments_hash = _stable_json_hash(provider_payload_segments) if provider_payload_segments else ""
    seed = {
        "session_id": normalized_session_id,
        "request_id": normalized_request_id,
        "status": str(status or ""),
        "provider_payload_prefix_hash": str(request_payload.get("provider_payload_prefix_hash") or ""),
        "provider_payload_messages_hash": str(request_payload.get("provider_payload_messages_hash") or ""),
        "provider_payload_segments_hash": provider_payload_segments_hash,
        "provider_visible_anchor_before": str(anchor_before.get("anchor_id") or ""),
        "provider_visible_anchor_after": str(anchor_after.get("anchor_id") or ""),
        "tool_context_hash": str(tool_context.get("tool_context_hash") or ""),
        "error": error_payload,
        "reason": str(reason or ""),
    }
    record_hash = _stable_json_hash(seed)
    prompt_manifest = dict(request_payload.get("prompt_manifest") or {})
    context_physical = dict(prompt_manifest.get("context_physical_assembly") or {})
    provider_payload_cache_boundary = dict(request_payload.get("provider_payload_cache_boundary") or {})
    record = {
        "schema_version": CONTEXT_COMMIT_RECORD_SCHEMA_VERSION,
        "record_type": "provider_request_context_commit",
        "record_id": "ctxcommitreq:" + record_hash.removeprefix("sha256:")[:16],
        "record_hash": record_hash,
        "session_id": normalized_session_id,
        "turn_id": str(request_payload.get("turn_id") or ""),
        "request_id": normalized_request_id,
        "status": str(status or ""),
        "provider": str(request_payload.get("provider") or ""),
        "model": str(request_payload.get("model") or ""),
        "message_count": _safe_int(request_payload.get("message_count")),
        "tool_count": _safe_int(request_payload.get("tool_count")),
        "provider_payload_manifest_ref": str(request_payload.get("provider_payload_manifest_ref") or ""),
        "provider_payload_prefix_hash": str(request_payload.get("provider_payload_prefix_hash") or ""),
        "provider_payload_message_prefix_hash": str(request_payload.get("provider_payload_message_prefix_hash") or ""),
        "provider_payload_messages_hash": str(request_payload.get("provider_payload_messages_hash") or ""),
        "transport_contract_hash": str(request_payload.get("transport_contract_hash") or ""),
        "transport_contract_ref": str(request_payload.get("transport_contract_ref") or ""),
        "cache_sensitive_params_hash": str(request_payload.get("cache_sensitive_params_hash") or ""),
        "cache_sensitive_params": dict(request_payload.get("cache_relevant_params") or {}),
        "tool_catalog_hash": str(request_payload.get("tool_catalog_hash") or ""),
        "stable_tool_catalog_hash": str(request_payload.get("stable_tool_catalog_hash") or ""),
        "provider_messages": [dict(item) for item in list(request_payload.get("provider_messages") or []) if isinstance(item, dict)],
        "provider_message_hashes": list(request_payload.get("provider_message_hashes") or []),
        "provider_tools": [dict(item) for item in list(request_payload.get("provider_tools") or []) if isinstance(item, dict)],
        "provider_tools_hash": str(request_payload.get("provider_tools_hash") or ""),
        "provider_payload_segment_count": len(provider_payload_segments),
        "provider_payload_segments_hash": provider_payload_segments_hash,
        "provider_payload_segments": provider_payload_segments,
        "provider_payload_cache_boundary": provider_payload_cache_boundary,
        "provider_payload_transport_contract": dict(request_payload.get("provider_payload_transport_contract") or {}),
        "cache_spine_hash": str(
            context_physical.get("cache_spine_hash")
            or request_payload.get("cache_spine_hash")
            or request_payload.get("provider_payload_prefix_hash")
            or ""
        ),
        "compaction_generation": str(
            context_physical.get("cache_spine_generation")
            or request_payload.get("compaction_generation")
            or ""
        ),
        "provider_visible_ledger_anchor_before": anchor_before,
        "provider_visible_ledger_confirmation": confirmation,
        "provider_visible_ledger_anchor_after": anchor_after,
        "tool_context_anchor": str(tool_context.get("tool_context_hash") or ""),
        "tool_context_projection": tool_context,
        "response_ref": str(response_ref or ""),
        "error": error_payload,
        "reason": str(reason or "provider_request"),
        "created_at": time.time(),
        "authority": "runtime.context_management.context_commit_record.provider_request",
    }
    path = context_commit_record_path(storage_root=storage_root, session_id=normalized_session_id, record_id=record["record_id"])
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(_json_stable(record), ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
    return record


def context_commit_record_path(*, storage_root: Path | str | None, session_id: str, record_id: str) -> Path | None:
    if storage_root is None:
        return None
    try:
        runtime_state_dir = ProjectLayout.from_runtime_root(Path(storage_root)).runtime_state_dir.resolve()
    except Exception:
        runtime_state_dir = Path(storage_root).resolve()
    safe_session = _safe_filename(session_id)
    safe_record = _safe_filename(record_id)
    if not safe_session or not safe_record:
        return None
    return runtime_state_dir / "context_commit_records" / safe_session / f"{safe_record}.json"


def latest_provider_request_context_commit_record(
    *,
    storage_root: Path | str | None,
    session_id: str,
    status: str = "succeeded",
) -> dict[str, Any]:
    directory = _context_commit_record_session_dir(storage_root=storage_root, session_id=session_id)
    if directory is None or not directory.exists():
        return {}
    expected_status = str(status or "").strip()
    records: list[dict[str, Any]] = []
    for path in directory.glob("ctxcommitreq*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        if str(payload.get("record_type") or "") != "provider_request_context_commit":
            continue
        if expected_status and str(payload.get("status") or "") != expected_status:
            continue
        records.append(payload)
    if not records:
        return {}
    records.sort(
        key=lambda item: (
            _safe_float(item.get("created_at")),
            str(item.get("record_id") or ""),
        )
    )
    return dict(records[-1])


def _context_commit_record_session_dir(*, storage_root: Path | str | None, session_id: str) -> Path | None:
    if storage_root is None:
        return None
    try:
        runtime_state_dir = ProjectLayout.from_runtime_root(Path(storage_root)).runtime_state_dir.resolve()
    except Exception:
        runtime_state_dir = Path(storage_root).resolve()
    safe_session = _safe_filename(session_id)
    if not safe_session:
        return None
    return runtime_state_dir / "context_commit_records" / safe_session


def _model_request_projection(model_request: Any) -> dict[str, Any]:
    payload = model_request.to_dict() if hasattr(model_request, "to_dict") else dict(model_request or {}) if isinstance(model_request, dict) else {}
    diagnostics = dict(payload.get("diagnostics") or {})
    provider_transport = dict(diagnostics.get("provider_transport_payload") or {})
    prompt_manifest = dict(diagnostics.get("prompt_manifest") or {})
    provider_payload_manifest = dict(payload.get("provider_payload_manifest") or {})
    provider_payload_segments = [
        dict(item)
        for item in list(provider_payload_manifest.get("segments") or [])
        if isinstance(item, dict)
    ]
    provider_payload_cache_boundary = dict(
        diagnostics.get("provider_payload_cache_boundary")
        or provider_payload_manifest.get("cache_boundary")
        or {}
    )
    provider_payload_transport_contract = dict(provider_payload_manifest.get("transport_contract") or {})
    provider_messages = [dict(item) for item in list(payload.get("messages") or []) if isinstance(item, dict)]
    provider_tools = [dict(item) for item in list(payload.get("tools") or []) if isinstance(item, dict)]
    return {
        "request_id": str(payload.get("request_id") or ""),
        "provider": str(payload.get("provider") or ""),
        "model": str(payload.get("model") or ""),
        "turn_id": str(diagnostics.get("turn_id") or ""),
        "message_count": len(provider_messages),
        "tool_count": len(provider_tools),
        "provider_messages": provider_messages,
        "provider_message_hashes": list(provider_transport.get("message_hashes") or []),
        "provider_tools": provider_tools,
        "provider_tools_hash": str(provider_transport.get("tools_hash") or ""),
        "cache_relevant_params": dict(diagnostics.get("cache_relevant_params") or {}),
        "provider_payload_manifest_ref": str(
            diagnostics.get("provider_payload_manifest_ref")
            or provider_payload_manifest.get("manifest_id")
            or ""
        ),
        "provider_payload_prefix_hash": str(payload.get("provider_payload_prefix_hash") or ""),
        "provider_payload_message_prefix_hash": str(payload.get("provider_payload_message_prefix_hash") or ""),
        "provider_payload_messages_hash": str(provider_transport.get("messages_hash") or payload.get("canonical_hash") or ""),
        "transport_contract_hash": str(payload.get("transport_contract_hash") or ""),
        "transport_contract_ref": str(payload.get("transport_contract_ref") or provider_payload_cache_boundary.get("transport_contract_ref") or ""),
        "cache_sensitive_params_hash": str(payload.get("cache_sensitive_params_hash") or provider_payload_cache_boundary.get("cache_sensitive_params_hash") or ""),
        "tool_catalog_hash": str(payload.get("tool_catalog_hash") or provider_payload_cache_boundary.get("tool_catalog_hash") or ""),
        "stable_tool_catalog_hash": str(payload.get("stable_tool_catalog_hash") or provider_payload_cache_boundary.get("stable_tool_catalog_hash") or ""),
        "provider_payload_cache_boundary": provider_payload_cache_boundary,
        "provider_payload_segments": provider_payload_segments,
        "provider_payload_transport_contract": provider_payload_transport_contract,
        "cache_spine_hash": str(provider_payload_cache_boundary.get("cache_spine_hash") or ""),
        "compaction_generation": str(provider_payload_cache_boundary.get("cache_spine_generation") or ""),
        "prompt_manifest": prompt_manifest,
    }


def _provider_visible_anchor_after(confirmation: dict[str, Any]) -> dict[str, Any]:
    anchors = [
        dict(item)
        for item in list(dict(confirmation or {}).get("provider_success_anchors") or [])
        if isinstance(item, dict)
    ]
    return anchors[-1] if anchors else {}


def _tool_context_projection(model_request: Any) -> dict[str, Any]:
    payload = model_request.to_dict() if hasattr(model_request, "to_dict") else dict(model_request or {}) if isinstance(model_request, dict) else {}
    provider_payload_manifest = dict(payload.get("provider_payload_manifest") or {})
    segments = [
        dict(item)
        for item in list(provider_payload_manifest.get("segments") or [])
        if isinstance(item, dict)
    ]
    tool_segments: list[dict[str, Any]] = []
    for segment in segments:
        metadata = dict(segment.get("metadata") or {})
        kind = str(segment.get("kind") or metadata.get("kind") or "").strip()
        semantic_slot = str(metadata.get("context_semantic_slot") or metadata.get("semantic_slot") or "").strip()
        authority_class = str(metadata.get("authority_class") or "").strip()
        if not (
            kind in {"single_agent_turn_tool_call", "single_agent_turn_tool_observation", "tool_observations"}
            or semantic_slot == "tool_transcript"
            or authority_class == "append_only_tool_observation_context"
        ):
            continue
        tool_segments.append(
            _drop_empty(
                {
                    "segment_id": str(segment.get("segment_id") or ""),
                    "kind": kind,
                    "source_ref": str(segment.get("source_ref") or ""),
                    "tool_observation_ref": str(metadata.get("tool_observation_ref") or ""),
                    "tool_call_id": str(metadata.get("tool_call_id") or ""),
                    "content_hash": str(segment.get("content_hash") or metadata.get("content_hash") or ""),
                    "physical_prefix_lane": str(metadata.get("physical_prefix_lane") or ""),
                    "compaction_generation": str(metadata.get("compaction_generation") or ""),
                }
            )
        )
    projection = {
        "tool_context_segment_count": len(tool_segments),
        "tool_context_segments": tool_segments,
    }
    projection["tool_context_hash"] = _stable_json_hash(projection) if tool_segments else ""
    projection["authority"] = "runtime.context_management.context_commit_record.tool_context_projection"
    return projection


def _error_payload(error: BaseException | dict[str, Any] | str | None) -> dict[str, Any]:
    if error is None:
        return {}
    if isinstance(error, dict):
        return dict(error)
    if isinstance(error, BaseException):
        return {
            "type": type(error).__name__,
            "message": str(error),
        }
    return {"message": str(error or "")}


def _last_turn_id(public_messages: list[dict[str, Any]], api_transcript: list[dict[str, Any]]) -> str:
    for collection in (api_transcript, public_messages):
        for message in reversed(collection):
            turn_id = str(dict(message).get("turn_id") or "").strip()
            if turn_id:
                return turn_id
    return ""


def _message_hash(message: dict[str, Any]) -> str:
    return _stable_json_hash(
        {
            "role": str(dict(message or {}).get("role") or ""),
            "content": str(dict(message or {}).get("content") or ""),
            "turn_id": str(dict(message or {}).get("turn_id") or ""),
        }
    )


def _text_hash(value: str) -> str:
    return "sha256:" + hashlib.sha256(str(value or "").encode("utf-8", errors="ignore")).hexdigest()


def _stable_json_hash(value: Any) -> str:
    payload = json.dumps(_json_stable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()


def _json_stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_stable(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_json_stable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in dict(payload or {}).items()
        if value not in {"", None, (), []}
    }


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


def _safe_filename(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_", "."} else "-" for char in str(value or "").strip())
