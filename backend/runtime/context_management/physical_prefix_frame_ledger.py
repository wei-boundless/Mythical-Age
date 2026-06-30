from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from core.project_layout import ProjectLayout

from .physical_prefix_frame_models import (
    PHYSICAL_PREFIX_FRAME_CONFIRMED_STATUS,
    PHYSICAL_PREFIX_FRAME_LEDGER_SCHEMA_REVISION,
    PhysicalPrefixFrame,
    PhysicalPrefixFrameSegment,
    json_stable,
    stable_json_hash,
)
from .context_prefix_identity import build_context_prefix_identity


PHYSICAL_PREFIX_FRAME_LEDGER_AUTHORITY = "runtime.context_management.physical_prefix_frame_ledger"
PHYSICAL_PREFIX_FRAME_LEDGER_DIRNAME = "physical_prefix_frame_ledger"
PHYSICAL_PREFIX_FRAME_REJECTED_STATUS = "rejected"
PHYSICAL_PREFIX_FRAME_MAX_RETAINED = 64
PROVIDER_VISIBLE_CONTEXT_PREFIX = "provider_visible_context_prefix"


def append_physical_prefix_frame_from_provider_success(
    *,
    storage_root: Path | str | None,
    scope: str,
    provider: str,
    model: str,
    provider_lane: str,
    request_id: str,
    run_id: str = "",
    task_run_id: str = "",
    session_id: str = "",
    turn_id: str = "",
    provider_payload_manifest: Any | None = None,
    provider_payload_messages_hash: str = "",
    physical_payload_family_hash: str = "",
    current_append_entry_indexes: list[int] | tuple[int, ...] = (),
    provider_visible_append_confirmation: dict[str, Any] | None = None,
    provider_messages: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
    response_ref: str = "",
    reason: str = "provider_request_succeeded",
) -> dict[str, Any]:
    normalized_scope = str(scope or session_id or "default").strip() or "default"
    storage_path = Path(storage_root) if storage_root is not None else None
    ledger = load_physical_prefix_frame_ledger(storage_root=storage_path, scope=normalized_scope)
    previous = _latest_confirmed_frame_from_ledger(
        ledger,
        provider=provider,
        model=model,
        provider_lane=provider_lane,
    )
    frame = build_physical_prefix_frame_from_provider_payload(
        scope=normalized_scope,
        provider=provider,
        model=model,
        provider_lane=provider_lane,
        request_id=request_id,
        run_id=run_id,
        task_run_id=task_run_id,
        session_id=session_id,
        turn_id=turn_id,
        previous_frame_id=str(previous.get("frame_id") or ""),
        provider_payload_manifest=provider_payload_manifest,
        provider_payload_messages_hash=provider_payload_messages_hash,
        physical_payload_family_hash=physical_payload_family_hash,
        current_append_entry_indexes=current_append_entry_indexes,
        provider_visible_append_confirmation=provider_visible_append_confirmation,
        provider_messages=provider_messages,
        response_ref=response_ref,
        reason=reason,
    )
    if not frame.frame_id:
        return {}
    payload = _ledger_for_append(
        ledger=ledger,
        scope=normalized_scope,
        provider=provider,
        model=model,
    )
    frames = [
        dict(item)
        for item in list(payload.get("frames") or [])
        if isinstance(item, dict) and str(item.get("frame_id") or "") != frame.frame_id
    ]
    frames.append(frame.to_dict())
    payload["frames"] = frames[-PHYSICAL_PREFIX_FRAME_MAX_RETAINED:]
    if frame.status == PHYSICAL_PREFIX_FRAME_CONFIRMED_STATUS:
        payload["last_confirmed_frame_id"] = frame.frame_id
        payload["last_confirmed_request_id"] = frame.source_request_id
        payload["last_confirmed_provider_payload_prefix_hash"] = frame.provider_payload_prefix_hash
        payload["last_confirmed_physical_cache_spine_message_subtotal_hash"] = (
            frame.physical_cache_spine_message_subtotal_hash
        )
    payload = _finalize_ledger(payload)
    save_physical_prefix_frame_ledger(storage_root=storage_path, scope=normalized_scope, ledger=payload)
    return {
        "status": frame.status,
        "frame_id": frame.frame_id,
        "scope": normalized_scope,
        "provider": str(provider or ""),
        "model": str(model or ""),
        "provider_lane": str(provider_lane or ""),
        "source_request_id": frame.source_request_id,
        "source_turn_id": frame.source_turn_id,
        "previous_frame_id": frame.previous_frame_id,
        "provider_payload_prefix_hash": frame.provider_payload_prefix_hash,
        "physical_cache_spine_message_subtotal_hash": frame.physical_cache_spine_message_subtotal_hash,
        "segment_count": frame.segment_count,
        "message_segment_count": frame.message_segment_count,
        "tool_segment_count": frame.tool_segment_count,
        "current_append_entry_indexes": list(frame.current_append_entry_indexes),
        "validation": dict(frame.diagnostics.get("validation") or {}),
        "authority": PHYSICAL_PREFIX_FRAME_LEDGER_AUTHORITY,
    }


def build_physical_prefix_frame_from_provider_payload(
    *,
    scope: str,
    provider: str,
    model: str,
    provider_lane: str,
    request_id: str,
    run_id: str = "",
    task_run_id: str = "",
    session_id: str = "",
    turn_id: str = "",
    previous_frame_id: str = "",
    provider_payload_manifest: Any | None,
    provider_payload_messages_hash: str = "",
    physical_payload_family_hash: str = "",
    current_append_entry_indexes: list[int] | tuple[int, ...] = (),
    provider_visible_append_confirmation: dict[str, Any] | None = None,
    provider_messages: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
    response_ref: str = "",
    reason: str = "provider_request_succeeded",
) -> PhysicalPrefixFrame:
    manifest = _manifest_dict(provider_payload_manifest)
    if not manifest:
        return PhysicalPrefixFrame(
            frame_id="",
            scope_id=str(scope or "default"),
            provider=str(provider or ""),
            model=str(model or ""),
            provider_lane=str(provider_lane or ""),
            source_request_id=str(request_id or ""),
            status=PHYSICAL_PREFIX_FRAME_REJECTED_STATUS,
            diagnostics={
                "validation": {
                    "status": "rejected",
                    "reason": "missing_provider_payload_manifest",
                },
            },
        )
    cache_boundary = dict(manifest.get("cache_boundary") or {})
    physical_spine = dict(cache_boundary.get("physical_cache_spine") or {})
    full_segments = [
        dict(item)
        for item in list(manifest.get("segments") or [])
        if isinstance(item, dict)
    ]
    segments_by_id = {str(item.get("segment_id") or ""): dict(item) for item in full_segments}
    provider_message_list = [dict(item) for item in list(provider_messages or []) if isinstance(item, dict)]
    confirmation_by_item_key = _confirmation_indexes_by_item_key(provider_visible_append_confirmation)
    round_closed_by_id = {
        str(item.get("round_id") or ""): bool(item.get("closed") is True)
        for item in list(physical_spine.get("provider_tool_protocol_rounds") or [])
        if isinstance(item, dict) and str(item.get("round_id") or "")
    }
    normalized_current_append = tuple(
        sorted({_safe_int(value) for value in list(current_append_entry_indexes or []) if _safe_int(value) > 0})
    )
    frame_source_segments = _frame_source_segments(
        full_segments=full_segments,
        physical_spine=physical_spine,
        current_append_entry_indexes=normalized_current_append,
        confirmation_by_item_key=confirmation_by_item_key,
    )
    frame_segments: list[PhysicalPrefixFrameSegment] = []
    for spine_segment in frame_source_segments:
        if not isinstance(spine_segment, dict):
            continue
        segment_id = str(spine_segment.get("segment_id") or "")
        full = dict(segments_by_id.get(segment_id) or spine_segment)
        metadata = dict(full.get("metadata") or {})
        provider_visible_item_key = str(metadata.get("provider_visible_append_item_key") or "")
        provider_visible_hash = str(metadata.get("provider_visible_hash") or "")
        model_message_index = _safe_int(metadata.get("message_index"), default=-1)
        provider_message, provider_message_source = _select_physical_frame_provider_message(
            metadata=metadata,
            provider_message_list=provider_message_list,
            model_message_index=model_message_index,
            provider_visible_hash=provider_visible_hash,
            expected_role=str(full.get("role") or spine_segment.get("role") or ""),
        )
        provider_visible_entry_index = _safe_int(metadata.get("provider_visible_append_entry_index"))
        if provider_visible_entry_index <= 0 and provider_visible_item_key:
            provider_visible_entry_index = _safe_int(confirmation_by_item_key.get(provider_visible_item_key))
        protocol = dict(metadata.get("provider_tool_protocol") or {})
        round_id = str(protocol.get("round_id") or "")
        promoted_lane = _frame_segment_physical_lane(full, metadata=metadata)
        frame_metadata = _frame_segment_metadata(metadata)
        original_lane = str(
            full.get("physical_prefix_lane")
            or spine_segment.get("physical_prefix_lane")
            or metadata.get("physical_prefix_lane")
            or ""
        )
        if original_lane and original_lane != promoted_lane:
            frame_metadata["physical_prefix_frame_original_lane"] = original_lane
        frame_metadata["physical_prefix_frame_provider_message_source"] = provider_message_source
        segment_source_ref = str(full.get("source_ref") or spine_segment.get("source_ref") or "")
        segment_content_hash = str(full.get("content_hash") or spine_segment.get("content_hash") or "")
        segment_content_version_hash = str(
            full.get("content_version_hash")
            or spine_segment.get("content_version_hash")
            or segment_content_hash
            or ""
        )
        segment_provider_serialized_hash = str(
            full.get("provider_serialized_hash")
            or spine_segment.get("provider_serialized_hash")
            or segment_content_hash
            or ""
        )
        segment_semantic_source = str(full.get("semantic_source") or spine_segment.get("semantic_source") or "")
        segment_semantic_slot = str(full.get("semantic_slot") or spine_segment.get("semantic_slot") or "")
        original_prefix_identity = dict(full.get("prefix_identity") or spine_segment.get("prefix_identity") or {})
        frame_identity_metadata = {
            **frame_metadata,
            "context_prefix_lifecycle_state": "confirmed_frame_replay",
        }
        if original_prefix_identity:
            frame_identity_metadata.setdefault(
                "context_origin_authority",
                str(original_prefix_identity.get("origin_authority") or ""),
            )
            frame_identity_metadata.setdefault(
                "context_origin_ref",
                str(original_prefix_identity.get("origin_ref") or ""),
            )
        frame_prefix_identity = build_context_prefix_identity(
            kind=str(full.get("kind") or spine_segment.get("kind") or ""),
            metadata=frame_identity_metadata,
            source_ref=segment_source_ref,
            physical_lane=promoted_lane,
            semantic_source=segment_semantic_source,
            semantic_slot=segment_semantic_slot,
            content_version_hash=segment_content_version_hash,
            provider_serialized_hash=segment_provider_serialized_hash,
            request_ordinal=_safe_int(full.get("ordinal") or spine_segment.get("ordinal")),
            transport_location=str(full.get("transport_location") or spine_segment.get("transport_location") or ""),
        ).to_dict()
        frame_metadata["context_origin_authority"] = str(frame_prefix_identity.get("origin_authority") or "")
        frame_metadata["context_origin_ref"] = str(frame_prefix_identity.get("origin_ref") or "")
        frame_metadata["context_prefix_identity"] = frame_prefix_identity
        frame_metadata["logical_segment_ref"] = str(frame_prefix_identity.get("logical_segment_ref") or "")
        frame_segments.append(
            PhysicalPrefixFrameSegment(
                ordinal=_safe_int(full.get("ordinal") or spine_segment.get("ordinal")),
                segment_id=segment_id,
                transport_location=str(full.get("transport_location") or spine_segment.get("transport_location") or ""),
                role=str(full.get("role") or spine_segment.get("role") or ""),
                kind=str(full.get("kind") or spine_segment.get("kind") or ""),
                source_ref=segment_source_ref,
                content_hash=segment_content_hash,
                content_version_hash=segment_content_version_hash,
                provider_serialized_hash=segment_provider_serialized_hash,
                byte_length=_safe_int(full.get("byte_length") or spine_segment.get("byte_length")),
                physical_prefix_lane=promoted_lane,
                prefix_family=str(full.get("prefix_family") or spine_segment.get("prefix_family") or ""),
                logical_segment_ref=str(frame_prefix_identity.get("logical_segment_ref") or ""),
                prefix_segment_ref=str(frame_prefix_identity.get("logical_segment_ref") or ""),
                semantic_slot=segment_semantic_slot,
                prefix_identity=frame_prefix_identity,
                cache_scope=str(full.get("cache_scope") or "none"),
                cache_role=str(full.get("cache_role") or "volatile"),
                prefix_tier=str(full.get("prefix_tier") or "volatile"),
                provider_visible_entry_index=provider_visible_entry_index,
                provider_visible_hash=provider_visible_hash,
                provider_visible_item_key=provider_visible_item_key,
                provider_tool_round_id=round_id,
                provider_tool_round_closed=bool(round_closed_by_id.get(round_id)) if round_id else False,
                boundary_participation=str(full.get("boundary_participation") or spine_segment.get("boundary_participation") or ""),
                model_message_index=model_message_index,
                provider_message=provider_message,
                metadata=frame_metadata,
            )
        )

    validation = _validate_frame_segments(
        frame_segments,
        physical_spine=physical_spine,
        required_current_append_entry_indexes=normalized_current_append,
    )
    status = (
        PHYSICAL_PREFIX_FRAME_CONFIRMED_STATUS
        if str(validation.get("status") or "") == "ok"
        else PHYSICAL_PREFIX_FRAME_REJECTED_STATUS
    )
    timestamp = time.time()
    frame_seed = {
        "scope": str(scope or "default"),
        "provider": str(provider or ""),
        "model": str(model or ""),
        "provider_lane": str(provider_lane or ""),
        "request_id": str(request_id or ""),
        "turn_id": str(turn_id or ""),
        "status": status,
        "provider_payload_prefix_hash": str(cache_boundary.get("provider_payload_prefix_hash") or ""),
        "segment_ids": [segment.segment_id for segment in frame_segments],
        "content_hashes": [segment.content_hash for segment in frame_segments],
        "current_append_entry_indexes": list(normalized_current_append),
    }
    frame_id = "physframe:" + stable_json_hash(frame_seed).removeprefix("sha256:")[:16]
    message_segments = [segment for segment in frame_segments if segment.transport_location == "messages"]
    tool_segments = [segment for segment in frame_segments if segment.transport_location == "tools"]
    return PhysicalPrefixFrame(
        frame_id=frame_id,
        scope_id=str(scope or "default"),
        provider=str(provider or ""),
        model=str(model or ""),
        provider_lane=str(provider_lane or ""),
        source_request_id=str(request_id or ""),
        source_run_id=str(run_id or ""),
        source_task_run_id=str(task_run_id or ""),
        source_session_id=str(session_id or ""),
        source_turn_id=str(turn_id or ""),
        previous_frame_id=str(previous_frame_id or ""),
        status=status,
        transport_contract_hash=str(cache_boundary.get("transport_contract_hash") or physical_spine.get("transport_contract_hash") or ""),
        provider_payload_prefix_hash=str(cache_boundary.get("provider_payload_prefix_hash") or physical_spine.get("provider_payload_prefix_hash") or ""),
        physical_cache_spine_message_subtotal_hash=str(
            cache_boundary.get("physical_cache_spine_message_subtotal_hash")
            or physical_spine.get("physical_cache_spine_message_subtotal_hash")
            or ""
        ),
        provider_payload_messages_hash=str(provider_payload_messages_hash or ""),
        physical_payload_family_hash=str(physical_payload_family_hash or ""),
        boundary_segment_id=str(cache_boundary.get("selected_boundary_segment_id") or physical_spine.get("boundary_segment_id") or ""),
        segment_count=len(frame_segments),
        message_segment_count=len(message_segments),
        tool_segment_count=len(tool_segments),
        segments=tuple(frame_segments),
        current_append_entry_indexes=normalized_current_append,
        turn_snapshot=_turn_snapshot(
            request_id=request_id,
            response_ref=response_ref,
            run_id=run_id,
            task_run_id=task_run_id,
            session_id=session_id,
            turn_id=turn_id,
            provider_messages=provider_message_list,
            full_segments=full_segments,
            physical_spine=physical_spine,
            reason=reason,
        ),
        diagnostics={
            "validation": validation,
            "provider_payload_manifest_ref": str(manifest.get("manifest_id") or ""),
            "physical_cache_spine": {
                "segment_ids": [segment.segment_id for segment in frame_segments],
                "provider_payload_physical_cache_spine_segment_ids": list(physical_spine.get("segment_ids") or []),
                "lane_order": list(physical_spine.get("lane_order") or []),
                "provider_tool_protocol_rounds": list(physical_spine.get("provider_tool_protocol_rounds") or []),
            },
            "current_append_promotion": _current_append_promotion_diagnostics(
                frame_segments,
                required_current_append_entry_indexes=normalized_current_append,
            ),
            "authority": PHYSICAL_PREFIX_FRAME_LEDGER_AUTHORITY,
        },
        created_at=timestamp,
        confirmed_at=timestamp if status == PHYSICAL_PREFIX_FRAME_CONFIRMED_STATUS else 0.0,
    )


def latest_confirmed_physical_prefix_frame(
    *,
    storage_root: Path | str | None,
    scope: str,
    provider: str = "",
    model: str = "",
    provider_lane: str = "",
) -> dict[str, Any]:
    ledger = load_physical_prefix_frame_ledger(
        storage_root=Path(storage_root) if storage_root is not None else None,
        scope=scope,
    )
    return _latest_confirmed_frame_from_ledger(
        ledger,
        provider=provider,
        model=model,
        provider_lane=provider_lane,
    )


def load_physical_prefix_frame_ledger(*, storage_root: Path | str | None, scope: str) -> dict[str, Any]:
    path = physical_prefix_frame_ledger_path(storage_root=storage_root, scope=scope)
    if path is None or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "authority": PHYSICAL_PREFIX_FRAME_LEDGER_AUTHORITY,
            "ledger_schema_revision": PHYSICAL_PREFIX_FRAME_LEDGER_SCHEMA_REVISION,
            "scope_id": str(scope or "default").strip() or "default",
            "status": "recovery_required",
            "ledger_failure": {
                "code": "physical_prefix_frame_ledger_json_corrupt",
                "message": str(exc),
                "path": str(path),
                "authority": PHYSICAL_PREFIX_FRAME_LEDGER_AUTHORITY,
            },
        }
    if not isinstance(payload, dict):
        return {
            "authority": PHYSICAL_PREFIX_FRAME_LEDGER_AUTHORITY,
            "ledger_schema_revision": PHYSICAL_PREFIX_FRAME_LEDGER_SCHEMA_REVISION,
            "scope_id": str(scope or "default").strip() or "default",
            "status": "recovery_required",
            "ledger_failure": {
                "code": "physical_prefix_frame_ledger_not_object",
                "path": str(path),
                "authority": PHYSICAL_PREFIX_FRAME_LEDGER_AUTHORITY,
            },
        }
    return dict(payload)


def save_physical_prefix_frame_ledger(
    *,
    storage_root: Path | str | None,
    scope: str,
    ledger: dict[str, Any],
) -> None:
    path = physical_prefix_frame_ledger_path(storage_root=storage_root, scope=scope)
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(json_stable(dict(ledger or {})), ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )


def truncate_physical_prefix_frame_ledger_after_session_cutoff(
    *,
    storage_root: Path | str | None,
    scope: str,
    kept_turn_ids: set[str] | list[str] | tuple[str, ...],
    cutoff_created_before: float,
    reason: str = "session_history_truncated",
) -> dict[str, Any]:
    normalized_scope = str(scope or "default").strip() or "default"
    kept = {str(item or "").strip() for item in list(kept_turn_ids or []) if str(item or "").strip()}
    cutoff_ts = float(cutoff_created_before or time.time())
    ledger = load_physical_prefix_frame_ledger(storage_root=storage_root, scope=normalized_scope)
    frames = [dict(item) for item in list(ledger.get("frames") or []) if isinstance(item, dict)]
    if not frames:
        return {
            "authority": PHYSICAL_PREFIX_FRAME_LEDGER_AUTHORITY,
            "scope": normalized_scope,
            "removed_count": 0,
            "retained_count": 0,
            "reason": "physical_prefix_frame_ledger_empty",
        }
    target_frame = _latest_frame_for_kept_turn_lineage(frames, kept_turn_ids=kept)
    retained_ids = _physical_frame_lineage_ids(frames, target_frame)
    retained: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    for frame in frames:
        frame_id = str(frame.get("frame_id") or "").strip()
        if frame_id and frame_id in retained_ids:
            retained.append(frame)
        else:
            removed.append(frame)
    if not removed:
        payload = dict(ledger or {})
        payload["last_truncate_cutoff"] = {
            "reason": str(reason or "session_history_truncated"),
            "cutoff_created_before": cutoff_ts,
            "kept_turn_ids": sorted(kept),
            "target_frame_id": str(target_frame.get("frame_id") or "") if target_frame else "",
            "removed_frame_ids": [],
            "removed_turn_ids": [],
            "retained_lineage_frame_ids": sorted(retained_ids),
            "authority": PHYSICAL_PREFIX_FRAME_LEDGER_AUTHORITY,
        }
        payload = _finalize_ledger(payload)
        save_physical_prefix_frame_ledger(storage_root=storage_root, scope=normalized_scope, ledger=payload)
        return {
            "authority": PHYSICAL_PREFIX_FRAME_LEDGER_AUTHORITY,
            "scope": normalized_scope,
            "removed_count": 0,
            "retained_count": len(retained),
            "last_confirmed_frame_id": str(payload.get("last_confirmed_frame_id") or ""),
            "reason": "physical_prefix_frame_lineage_already_at_cutoff",
        }
    payload = dict(ledger or {})
    payload["frames"] = retained[-PHYSICAL_PREFIX_FRAME_MAX_RETAINED:]
    latest = _latest_confirmed_frame_from_ledger(
        payload,
        provider="",
        model="",
        provider_lane="",
    )
    if latest:
        payload["last_confirmed_frame_id"] = str(latest.get("frame_id") or "")
        payload["last_confirmed_request_id"] = str(latest.get("source_request_id") or "")
        payload["last_confirmed_provider_payload_prefix_hash"] = str(latest.get("provider_payload_prefix_hash") or "")
        payload["last_confirmed_physical_cache_spine_message_subtotal_hash"] = str(
            latest.get("physical_cache_spine_message_subtotal_hash") or ""
        )
    else:
        payload["last_confirmed_frame_id"] = ""
        payload["last_confirmed_request_id"] = ""
        payload["last_confirmed_provider_payload_prefix_hash"] = ""
        payload["last_confirmed_physical_cache_spine_message_subtotal_hash"] = ""
    payload["last_truncate_cutoff"] = {
        "reason": str(reason or "session_history_truncated"),
        "cutoff_created_before": cutoff_ts,
        "kept_turn_ids": sorted(kept),
        "target_frame_id": str(target_frame.get("frame_id") or "") if target_frame else "",
        "removed_frame_ids": [str(item.get("frame_id") or "") for item in removed if str(item.get("frame_id") or "")],
        "removed_turn_ids": sorted(
            {
                _frame_source_turn_id(item)
                for item in removed
                if _frame_source_turn_id(item)
            }
        ),
        "retained_lineage_frame_ids": sorted(retained_ids),
        "authority": PHYSICAL_PREFIX_FRAME_LEDGER_AUTHORITY,
    }
    payload = _finalize_ledger(payload)
    save_physical_prefix_frame_ledger(storage_root=storage_root, scope=normalized_scope, ledger=payload)
    return {
        "authority": PHYSICAL_PREFIX_FRAME_LEDGER_AUTHORITY,
        "scope": normalized_scope,
        "removed_count": len(removed),
        "retained_count": len(payload.get("frames") or []),
        "last_confirmed_frame_id": str(payload.get("last_confirmed_frame_id") or ""),
        "removed_frame_ids": [str(item.get("frame_id") or "") for item in removed if str(item.get("frame_id") or "")],
        "reason": str(reason or "session_history_truncated"),
    }


def physical_prefix_frame_ledger_path(*, storage_root: Path | str | None, scope: str) -> Path | None:
    if storage_root is None:
        return None
    try:
        runtime_state_dir = ProjectLayout.from_runtime_root(Path(storage_root)).runtime_state_dir.resolve()
    except Exception:
        runtime_state_dir = Path(storage_root).resolve()
    safe_scope = safe_physical_prefix_frame_scope_filename(scope)
    if not safe_scope:
        return None
    return runtime_state_dir / PHYSICAL_PREFIX_FRAME_LEDGER_DIRNAME / f"{safe_scope}.json"


def safe_physical_prefix_frame_scope_filename(value: str) -> str:
    text = str(value or "").strip()
    result = []
    for char in text:
        if char.isalnum() or char in {"-", "_", "."}:
            result.append(char)
        else:
            result.append("_")
    return "".join(result).strip("._")[:180] or "default"


def _latest_frame_for_kept_turn_lineage(frames: list[dict[str, Any]], *, kept_turn_ids: set[str]) -> dict[str, Any]:
    if not kept_turn_ids:
        return {}
    candidates: list[tuple[int, float, dict[str, Any]]] = []
    for index, frame in enumerate(list(frames or [])):
        if str(frame.get("status") or "") != PHYSICAL_PREFIX_FRAME_CONFIRMED_STATUS:
            continue
        if _frame_source_turn_id(frame) not in kept_turn_ids:
            continue
        candidates.append((index, _safe_float(frame.get("confirmed_at") or frame.get("created_at")), frame))
    if not candidates:
        return {}
    candidates.sort(key=lambda item: (item[1], item[0]))
    return dict(candidates[-1][2])


def _physical_frame_lineage_ids(frames: list[dict[str, Any]], target_frame: dict[str, Any]) -> set[str]:
    target_id = str(dict(target_frame or {}).get("frame_id") or "").strip()
    if not target_id:
        return set()
    by_id = {
        str(frame.get("frame_id") or "").strip(): dict(frame)
        for frame in list(frames or [])
        if isinstance(frame, dict) and str(frame.get("frame_id") or "").strip()
    }
    lineage: set[str] = set()
    current_id = target_id
    while current_id and current_id in by_id and current_id not in lineage:
        lineage.add(current_id)
        current = by_id.get(current_id) or {}
        current_id = str(current.get("previous_frame_id") or "").strip()
    return lineage


def _frame_source_turn_id(frame: dict[str, Any]) -> str:
    return str(
        dict(frame or {}).get("source_turn_id")
        or dict(dict(frame or {}).get("turn_snapshot") or {}).get("turn_id")
        or ""
    ).strip()


def _ledger_for_append(*, ledger: dict[str, Any], scope: str, provider: str, model: str) -> dict[str, Any]:
    if not ledger:
        return {
            "authority": PHYSICAL_PREFIX_FRAME_LEDGER_AUTHORITY,
            "ledger_schema_revision": PHYSICAL_PREFIX_FRAME_LEDGER_SCHEMA_REVISION,
            "scope_id": str(scope or "default"),
            "provider": str(provider or ""),
            "model": str(model or ""),
            "status": "ok",
            "frames": [],
            "created_at": time.time(),
            "updated_at": time.time(),
        }
    payload = dict(ledger or {})
    payload.setdefault("authority", PHYSICAL_PREFIX_FRAME_LEDGER_AUTHORITY)
    payload.setdefault("ledger_schema_revision", PHYSICAL_PREFIX_FRAME_LEDGER_SCHEMA_REVISION)
    payload.setdefault("scope_id", str(scope or "default"))
    payload.setdefault("provider", str(provider or payload.get("provider") or ""))
    payload.setdefault("model", str(model or payload.get("model") or ""))
    payload.setdefault("status", "ok")
    payload.setdefault("frames", [])
    payload.setdefault("created_at", time.time())
    return payload


def _finalize_ledger(ledger: dict[str, Any]) -> dict[str, Any]:
    payload = dict(ledger or {})
    payload["authority"] = PHYSICAL_PREFIX_FRAME_LEDGER_AUTHORITY
    payload["ledger_schema_revision"] = PHYSICAL_PREFIX_FRAME_LEDGER_SCHEMA_REVISION
    payload["frames"] = [dict(item) for item in list(payload.get("frames") or []) if isinstance(item, dict)]
    payload["frame_count"] = len(payload["frames"])
    payload["updated_at"] = time.time()
    payload["ledger_hash"] = stable_json_hash(
        {
            key: value
            for key, value in payload.items()
            if key not in {"ledger_hash", "updated_at"}
        }
    )
    payload["ledger_id"] = "physframeledger:" + str(payload["ledger_hash"]).removeprefix("sha256:")[:16]
    return payload


def _latest_confirmed_frame_from_ledger(
    ledger: dict[str, Any],
    *,
    provider: str,
    model: str,
    provider_lane: str,
) -> dict[str, Any]:
    frames = [
        dict(item)
        for item in list(dict(ledger or {}).get("frames") or [])
        if isinstance(item, dict)
        and str(item.get("status") or "") == PHYSICAL_PREFIX_FRAME_CONFIRMED_STATUS
        and _matches_or_empty(item.get("provider"), provider)
        and _matches_or_empty(item.get("model"), model)
        and _matches_or_empty(item.get("provider_lane"), provider_lane)
    ]
    if not frames:
        return {}
    frames.sort(
        key=lambda item: (
            _safe_float(item.get("confirmed_at") or item.get("created_at")),
            str(item.get("frame_id") or ""),
        )
    )
    return dict(frames[-1])


def _matches_or_empty(previous: Any, current: Any) -> bool:
    previous_text = str(previous or "").strip()
    current_text = str(current or "").strip()
    return not previous_text or not current_text or previous_text == current_text


def _manifest_dict(value: Any | None) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "to_dict"):
        return dict(value.to_dict())
    if isinstance(value, dict):
        return dict(value)
    return {}


def _confirmation_indexes_by_item_key(confirmation: dict[str, Any] | None) -> dict[str, int]:
    result: dict[str, int] = {}
    for item in list(dict(confirmation or {}).get("confirmations") or []):
        if not isinstance(item, dict):
            continue
        key = str(item.get("item_key") or "").strip()
        index = _safe_int(item.get("entry_index"))
        if key and index > 0:
            result[key] = index
    return result


def _validate_frame_segments(
    segments: list[PhysicalPrefixFrameSegment],
    *,
    physical_spine: dict[str, Any],
    required_current_append_entry_indexes: list[int] | tuple[int, ...] = (),
) -> dict[str, Any]:
    del physical_spine
    if not segments:
        return {
            "status": "rejected",
            "reason": "empty_physical_cache_spine",
            "authority": PHYSICAL_PREFIX_FRAME_LEDGER_AUTHORITY,
        }
    missing_current_append = _missing_current_append_entry_indexes(
        segments,
        required_current_append_entry_indexes=required_current_append_entry_indexes,
    )
    if missing_current_append:
        return {
            "status": "rejected",
            "reason": "confirmed_current_append_missing_from_physical_prefix_frame",
            "missing_current_append_entry_indexes": missing_current_append,
            "required_current_append_entry_indexes": [
                _safe_int(value)
                for value in list(required_current_append_entry_indexes or [])
                if _safe_int(value) > 0
            ],
            "authority": PHYSICAL_PREFIX_FRAME_LEDGER_AUTHORITY,
        }
    provider_message_failure = _provider_visible_frame_message_source_failure(segments)
    if provider_message_failure:
        return provider_message_failure
    for index, segment in enumerate(segments, start=1):
        if not segment.content_hash:
            return {
                "status": "rejected",
                "reason": "physical_prefix_segment_missing_content_hash",
                "ordinal": index,
                "segment_id": segment.segment_id,
                "authority": PHYSICAL_PREFIX_FRAME_LEDGER_AUTHORITY,
            }
    return {
        "status": "ok",
        "segment_count": len(segments),
        "validation_scope": "physical_storage_replay_only",
        "authority": PHYSICAL_PREFIX_FRAME_LEDGER_AUTHORITY,
    }


def _frame_source_segments(
    *,
    full_segments: list[dict[str, Any]],
    physical_spine: dict[str, Any],
    current_append_entry_indexes: list[int] | tuple[int, ...] = (),
    confirmation_by_item_key: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    included_ids = {
        str(segment_id)
        for segment_id in list(dict(physical_spine or {}).get("segment_ids") or [])
        if str(segment_id or "")
    }
    current_append_indexes = {
        _safe_int(value)
        for value in list(current_append_entry_indexes or [])
        if _safe_int(value) > 0
    }
    item_key_confirmations = {
        str(key or ""): _safe_int(value)
        for key, value in dict(confirmation_by_item_key or {}).items()
        if str(key or "") and _safe_int(value) > 0
    }
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    seen_entry_indexes: set[int] = set()
    for segment in full_segments:
        segment_id = str(segment.get("segment_id") or "")
        if not segment_id or segment_id not in included_ids:
            continue
        entry_index = _resolved_segment_provider_visible_entry_index(
            segment,
            confirmation_by_item_key=item_key_confirmations,
        )
        if entry_index > 0 and entry_index in seen_entry_indexes:
            continue
        result.append(dict(segment))
        seen.add(segment_id)
        if entry_index > 0:
            seen_entry_indexes.add(entry_index)
    for segment in full_segments:
        segment_id = str(segment.get("segment_id") or "")
        if not segment_id or segment_id in seen:
            continue
        entry_index = _resolved_segment_provider_visible_entry_index(
            segment,
            confirmation_by_item_key=item_key_confirmations,
        )
        if entry_index > 0 and entry_index in seen_entry_indexes:
            continue
        if (
            entry_index in current_append_indexes
            and _segment_is_confirmed_current_append(segment)
        ):
            result.append(dict(segment))
            seen.add(segment_id)
            seen_entry_indexes.add(entry_index)
    return sorted(result, key=lambda item: _safe_int(item.get("ordinal")))


def _select_physical_frame_provider_message(
    *,
    metadata: dict[str, Any],
    provider_message_list: list[dict[str, Any]],
    model_message_index: int,
    provider_visible_hash: str,
    expected_role: str,
) -> tuple[dict[str, Any], str]:
    candidate = dict(metadata.get("provider_visible_append_candidate_message") or {})
    indexed = (
        dict(provider_message_list[model_message_index])
        if 0 <= model_message_index < len(provider_message_list)
        else {}
    )
    expected_hash = str(provider_visible_hash or "").strip()
    if expected_hash:
        if candidate and _provider_message_hash(candidate) == expected_hash:
            return candidate, "provider_visible_append_candidate_message"
        if indexed and _provider_message_hash(indexed) == expected_hash:
            return indexed, "provider_request.messages"
    if candidate and _provider_message_shape_matches(candidate, expected_role=expected_role):
        return candidate, "provider_visible_append_candidate_message"
    if indexed and _provider_message_shape_matches(indexed, expected_role=expected_role):
        return indexed, "provider_request.messages"
    if candidate:
        return candidate, "provider_visible_append_candidate_message"
    return indexed, "provider_request.messages" if indexed else ""


def _provider_message_hash(message: dict[str, Any]) -> str:
    return stable_json_hash(json_stable(dict(message or {})))


def _provider_message_shape_matches(message: dict[str, Any], *, expected_role: str) -> bool:
    role = str(dict(message or {}).get("role") or "").strip()
    expected = str(expected_role or "").strip()
    if expected and role != expected:
        return False
    if role == "assistant":
        return bool(dict(message or {}).get("tool_calls")) or bool(str(dict(message or {}).get("content") or ""))
    if role == "tool":
        return bool(str(dict(message or {}).get("tool_call_id") or "").strip())
    return bool(role)


def _segment_provider_visible_entry_index(segment: dict[str, Any]) -> int:
    metadata = dict(segment.get("metadata") or {})
    return _safe_int(
        metadata.get("provider_visible_append_entry_index")
        or segment.get("provider_visible_entry_index")
    )


def _resolved_segment_provider_visible_entry_index(
    segment: dict[str, Any],
    *,
    confirmation_by_item_key: dict[str, int],
) -> int:
    entry_index = _segment_provider_visible_entry_index(segment)
    if entry_index > 0:
        return entry_index
    metadata = dict(segment.get("metadata") or {})
    item_key = str(metadata.get("provider_visible_append_item_key") or "").strip()
    if item_key:
        confirmed = _safe_int(confirmation_by_item_key.get(item_key))
        if confirmed > 0:
            return confirmed
    return 0


def _segment_is_confirmed_current_append(segment: dict[str, Any]) -> bool:
    if str(segment.get("transport_location") or "") != "messages":
        return False
    metadata = dict(segment.get("metadata") or {})
    if str(metadata.get("provider_visible_append_commit_stage") or "") != "provider_success_required":
        return False
    if not str(metadata.get("provider_visible_hash") or "").strip():
        return False
    if str(metadata.get("context_commit_policy") or metadata.get("memory_commit_policy") or "").strip() != "append_then_seal":
        return False
    if str(metadata.get("context_replay_policy") or "").strip() == "current_dynamic_tail_only":
        return False
    if str(metadata.get("context_cache_section") or "").strip() == "dynamic_tail":
        return False
    return True


def _frame_segment_physical_lane(segment: dict[str, Any], *, metadata: dict[str, Any]) -> str:
    if _segment_is_confirmed_current_append(segment):
        return PROVIDER_VISIBLE_CONTEXT_PREFIX
    return str(
        segment.get("physical_prefix_lane")
        or metadata.get("physical_prefix_lane")
        or ""
    )


def _missing_current_append_entry_indexes(
    segments: list[PhysicalPrefixFrameSegment],
    *,
    required_current_append_entry_indexes: list[int] | tuple[int, ...],
) -> list[int]:
    required = {
        _safe_int(value)
        for value in list(required_current_append_entry_indexes or [])
        if _safe_int(value) > 0
    }
    if not required:
        return []
    promoted = {
        _safe_int(segment.provider_visible_entry_index)
        for segment in segments
        if _safe_int(segment.provider_visible_entry_index) > 0
        and str(segment.physical_prefix_lane or "") == PROVIDER_VISIBLE_CONTEXT_PREFIX
    }
    return sorted(required - promoted)


def _provider_visible_frame_message_source_failure(
    segments: list[PhysicalPrefixFrameSegment],
) -> dict[str, Any]:
    for segment in segments:
        if str(segment.transport_location or "") != "messages":
            continue
        if str(segment.physical_prefix_lane or "") != PROVIDER_VISIBLE_CONTEXT_PREFIX:
            continue
        if not dict(segment.provider_message or {}):
            return {
                "status": "rejected",
                "reason": "provider_visible_frame_segment_missing_provider_message",
                "segment_id": segment.segment_id,
                "provider_visible_entry_index": segment.provider_visible_entry_index,
                "authority": PHYSICAL_PREFIX_FRAME_LEDGER_AUTHORITY,
            }
        message_source = str(
            dict(segment.metadata or {}).get("physical_prefix_frame_provider_message_source") or ""
        ).strip()
        if message_source not in {"provider_request.messages", "provider_visible_append_candidate_message"}:
            return {
                "status": "rejected",
                "reason": "provider_visible_frame_segment_not_copied_from_provider_request",
                "segment_id": segment.segment_id,
                "provider_visible_entry_index": segment.provider_visible_entry_index,
                "message_source": message_source,
                "authority": PHYSICAL_PREFIX_FRAME_LEDGER_AUTHORITY,
            }
        expected_hash = str(segment.provider_visible_hash or segment.content_hash or "").strip()
        if expected_hash and _provider_message_hash(dict(segment.provider_message or {})) != expected_hash:
            return {
                "status": "rejected",
                "reason": "provider_visible_frame_segment_provider_message_hash_mismatch",
                "segment_id": segment.segment_id,
                "provider_visible_entry_index": segment.provider_visible_entry_index,
                "message_source": message_source,
                "expected_provider_visible_hash": expected_hash,
                "actual_provider_visible_hash": _provider_message_hash(dict(segment.provider_message or {})),
                "authority": PHYSICAL_PREFIX_FRAME_LEDGER_AUTHORITY,
            }
    return {}


def _current_append_promotion_diagnostics(
    segments: list[PhysicalPrefixFrameSegment],
    *,
    required_current_append_entry_indexes: list[int] | tuple[int, ...],
) -> dict[str, Any]:
    required = sorted(
        {
            _safe_int(value)
            for value in list(required_current_append_entry_indexes or [])
            if _safe_int(value) > 0
        }
    )
    promoted_segments = [
        segment
        for segment in segments
        if _safe_int(segment.provider_visible_entry_index) in set(required)
        and str(segment.physical_prefix_lane or "") == PROVIDER_VISIBLE_CONTEXT_PREFIX
    ]
    promoted = sorted(
        {
            _safe_int(segment.provider_visible_entry_index)
            for segment in promoted_segments
            if _safe_int(segment.provider_visible_entry_index) > 0
        }
    )
    return {
        "required_current_append_entry_indexes": required,
        "promoted_current_append_entry_indexes": promoted,
        "missing_current_append_entry_indexes": sorted(set(required) - set(promoted)),
        "promoted_segment_ids": [segment.segment_id for segment in promoted_segments],
        "selector": "provider_visible_append_confirmation_item_key_or_hash",
        "content_source_rule": "copy_exact_provider_message_from_provider_request",
        "authority": PHYSICAL_PREFIX_FRAME_LEDGER_AUTHORITY,
    }


def _turn_snapshot(
    *,
    request_id: str,
    response_ref: str,
    run_id: str,
    task_run_id: str,
    session_id: str,
    turn_id: str,
    provider_messages: list[dict[str, Any]],
    full_segments: list[dict[str, Any]],
    physical_spine: dict[str, Any],
    reason: str,
) -> dict[str, Any]:
    message_hashes = [stable_json_hash(message) for message in provider_messages]
    prefix_segment_ids = {str(item) for item in list(dict(physical_spine or {}).get("segment_ids") or []) if str(item)}
    tail_segments: list[dict[str, Any]] = []
    current_append_segments: list[dict[str, Any]] = []
    for segment in full_segments:
        if str(segment.get("transport_location") or "") != "messages":
            continue
        metadata = dict(segment.get("metadata") or {})
        projection = _segment_projection(segment)
        if str(segment.get("segment_id") or "") not in prefix_segment_ids:
            tail_segments.append(projection)
        if str(metadata.get("provider_visible_append_commit_stage") or "") == "provider_success_required":
            current_append_segments.append(projection)
    snapshot_seed = {
        "request_id": str(request_id or ""),
        "turn_id": str(turn_id or ""),
        "message_hashes": message_hashes,
        "prefix_segment_ids": sorted(prefix_segment_ids),
        "tail_segments": tail_segments,
        "current_append_segments": current_append_segments,
    }
    return {
        "snapshot_id": "physframesnapshot:" + stable_json_hash(snapshot_seed).removeprefix("sha256:")[:16],
        "request_id": str(request_id or ""),
        "response_ref": str(response_ref or ""),
        "run_id": str(run_id or ""),
        "task_run_id": str(task_run_id or ""),
        "session_id": str(session_id or ""),
        "turn_id": str(turn_id or ""),
        "reason": str(reason or ""),
        "provider_message_count": len(provider_messages),
        "provider_messages": [dict(item) for item in provider_messages],
        "provider_message_hashes": message_hashes,
        "dynamic_tail_segments": tail_segments,
        "current_append_segments": current_append_segments,
        "current_append_segment_count": len(current_append_segments),
        "dynamic_tail_segment_count": len(tail_segments),
        "recovery_memory_contract": {
            "abort_recovery": "resume_from_latest_physical_frame_plus_turn_snapshot",
            "active_steer": "append_steer_after_confirmed_frame_without_rewriting_old_prefix",
            "rewrite": "rewrite_tail_or_current_append_without_reordering_confirmed_frame",
            "authority": PHYSICAL_PREFIX_FRAME_LEDGER_AUTHORITY,
        },
        "authority": "runtime.context_management.physical_prefix_frame.turn_snapshot",
    }


def _segment_projection(segment: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(segment.get("metadata") or {})
    return {
        "segment_id": str(segment.get("segment_id") or ""),
        "ordinal": _safe_int(segment.get("ordinal")),
        "transport_location": str(segment.get("transport_location") or ""),
        "role": str(segment.get("role") or ""),
        "kind": str(segment.get("kind") or ""),
        "source_ref": str(segment.get("source_ref") or ""),
        "content_hash": str(segment.get("content_hash") or ""),
        "physical_prefix_lane": str(segment.get("physical_prefix_lane") or metadata.get("physical_prefix_lane") or ""),
        "context_cache_section": str(metadata.get("context_cache_section") or ""),
        "context_replay_policy": str(metadata.get("context_replay_policy") or ""),
        "provider_visible_append_entry_index": _safe_int(
            metadata.get("provider_visible_append_entry_index")
        ),
        "provider_visible_append_item_key": str(metadata.get("provider_visible_append_item_key") or ""),
        "provider_visible_hash": str(metadata.get("provider_visible_hash") or ""),
    }


def _frame_segment_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    keys = {
        "context_cache_section",
        "context_identity_policy",
        "context_origin_authority",
        "context_origin_ref",
        "context_replay_policy",
        "context_semantic_slot",
        "origin_authority",
        "origin_ref",
        "prefix_origin_authority",
        "prefix_origin_ref",
        "semantic_commit_class",
        "semantic_visibility",
        "stable_origin_ref",
        "validity_scope",
        "provider_visible_payload_authority",
        "provider_visible_append_ledger_authority",
        "provider_visible_append_commit_stage",
        "provider_visible_append_ledger_scope",
        "provider_visible_append_candidate_kind",
        "provider_visible_append_candidate_source_ref",
        "provider_visible_append_candidate_semantic_commit_class",
        "provider_adapter_contract",
        "provider_tool_protocol",
        "cache_spine_hash",
        "cache_spine_generation",
    }
    return {key: metadata.get(key) for key in sorted(keys) if key in metadata}


def _safe_int(value: Any, *, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
