from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from project_layout import ProjectLayout


SEALED_CONTEXT_NORMALIZATION_VERSION = "provider_visible_message_v1"
SEALED_CONTEXT_RECEIPT_SCHEMA_VERSION = 2


def assign_sealed_append_order(
    *,
    storage_root: Path | None,
    scope: str,
    item_key: str,
    receipt_authority: str,
    provider_visible_hash: str = "",
    kind: str = "",
    source_ref: str = "",
    transport_contract_hash: str = "",
    stable_base_hash: str = "",
    physical_prefix_hash: str = "",
    sealed_context_hash: str = "",
    provider_visible_message: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_scope = str(scope or "default").strip() or "default"
    key = str(item_key or "").strip()
    if not key:
        raise ValueError("sealed append item_key is required")
    receipt = load_sealed_context_receipt(storage_root=storage_root, scope=normalized_scope)
    failure = _receipt_failure(receipt)
    receipt = _receipt_for_assignment(
        receipt,
        scope=normalized_scope,
        receipt_authority=receipt_authority,
        failure=failure,
    )
    items = dict(receipt.get("items") or {}) if isinstance(receipt.get("items"), dict) else {}
    entries = _entries_by_index(receipt)
    next_index = _next_append_index(receipt, entries=entries)
    existing_index = _safe_int(items.get(key))
    order_source = "receipt"
    changed = False
    integrity_status = "ok"
    integrity_failure: dict[str, Any] = {}

    previous_receipt_hash = str(receipt.get("receipt_hash") or _receipt_content_hash(receipt) or "")
    visible_hash = str(provider_visible_hash or "").strip()
    visible_message = _provider_visible_message(provider_visible_message)
    if existing_index > 0:
        entry = dict(entries.get(existing_index) or {})
        previous_visible_hash = str(entry.get("provider_visible_hash") or "").strip()
        if visible_hash and not previous_visible_hash:
            entry = {
                **entry,
                "provider_visible_hash": visible_hash,
                "kind": str(kind or entry.get("kind") or ""),
                "source_ref": str(source_ref or entry.get("source_ref") or ""),
                "normalization_version": SEALED_CONTEXT_NORMALIZATION_VERSION,
                "hash_backfilled_at": time.time(),
            }
            if visible_message:
                entry["provider_visible_message"] = visible_message
            entry["entry_hash"] = _stable_json_hash({key: value for key, value in entry.items() if key != "entry_hash"})
            receipt["entries"] = [
                entry if _safe_int(item.get("append_index")) == existing_index else dict(item)
                for item in list(receipt.get("entries") or [])
                if isinstance(item, dict)
            ]
            changed = True
            order_source = "receipt_hash_backfilled"
        elif visible_message and not isinstance(entry.get("provider_visible_message"), dict):
            entry = {
                **entry,
                "provider_visible_message": visible_message,
                "message_backfilled_at": time.time(),
            }
            entry["entry_hash"] = _stable_json_hash({key: value for key, value in entry.items() if key != "entry_hash"})
            receipt["entries"] = [
                entry if _safe_int(item.get("append_index")) == existing_index else dict(item)
                for item in list(receipt.get("entries") or [])
                if isinstance(item, dict)
            ]
            changed = True
            order_source = "receipt_message_backfilled"
        elif visible_hash and previous_visible_hash and visible_hash != previous_visible_hash:
            integrity_status = "failed"
            integrity_failure = _structured_failure(
                scope=normalized_scope,
                code="provider_visible_hash_changed_for_append_index",
                message="sealed context append index maps to different provider-visible content",
                details={
                    "append_index": existing_index,
                    "item_key": key,
                    "previous_provider_visible_hash": previous_visible_hash,
                    "current_provider_visible_hash": visible_hash,
                    "kind": str(kind or entry.get("kind") or ""),
                    "source_ref": str(source_ref or entry.get("source_ref") or ""),
                },
            )
            receipt = _record_recovery_event(receipt, integrity_failure)
            changed = True
            order_source = "receipt_integrity_failed"
    else:
        existing_index = next_index
        items[key] = existing_index
        entry = _sealed_entry(
            append_index=existing_index,
            item_key=key,
            provider_visible_hash=visible_hash,
            provider_visible_message=visible_message,
            kind=str(kind or ""),
            source_ref=str(source_ref or ""),
            previous_receipt_hash=previous_receipt_hash,
        )
        receipt.setdefault("entries", [])
        receipt["entries"] = [*list(receipt.get("entries") or []), entry]
        receipt["items"] = items
        receipt["next_append_index"] = existing_index + 1
        changed = True
        if failure:
            order_source = "structured_recovery_new_checkpoint"
        elif _safe_int(receipt.get("migrated_from_schema_version")) > 0:
            order_source = "migrated_receipt_new_append"
        else:
            order_source = "new_append" if len(items) > 1 else "bootstrap"

    receipt = _finalize_receipt(
        receipt,
        scope=normalized_scope,
        authority=receipt_authority,
        transport_contract_hash=transport_contract_hash,
        stable_base_hash=stable_base_hash,
        physical_prefix_hash=physical_prefix_hash,
        sealed_context_hash=sealed_context_hash,
    )
    if changed:
        save_sealed_context_receipt(storage_root=storage_root, scope=normalized_scope, receipt=receipt)
    return {
        "order": existing_index,
        "append_index": existing_index,
        "order_source": order_source,
        "receipt": receipt,
        "changed": changed,
        "integrity_status": integrity_status,
        "recovery_required": bool(failure or integrity_failure or str(receipt.get("status") or "") == "recovery_required"),
        "structured_failure": integrity_failure or failure,
        "authority": "runtime.context_management.sealed_context.assign_sealed_append_order",
    }


def load_sealed_context_receipt(*, storage_root: Path | None, scope: str) -> dict[str, Any]:
    normalized_scope = str(scope or "default").strip() or "default"
    path = sealed_context_receipt_path(storage_root=storage_root, scope=normalized_scope)
    if path is None or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "authority": "runtime.context_management.sealed_context.load",
            "schema_version": SEALED_CONTEXT_RECEIPT_SCHEMA_VERSION,
            "normalization_version": SEALED_CONTEXT_NORMALIZATION_VERSION,
            "scope": normalized_scope,
            "status": "recovery_required",
            "items": {},
            "entries": [],
            "receipt_failure": _structured_failure(
                scope=normalized_scope,
                code="receipt_json_corrupt",
                message="sealed context receipt could not be parsed",
                details={"path": str(path), "error": type(exc).__name__},
            ),
        }
    if not isinstance(payload, dict):
        return {
            "authority": "runtime.context_management.sealed_context.load",
            "schema_version": SEALED_CONTEXT_RECEIPT_SCHEMA_VERSION,
            "normalization_version": SEALED_CONTEXT_NORMALIZATION_VERSION,
            "scope": normalized_scope,
            "status": "recovery_required",
            "items": {},
            "entries": [],
            "receipt_failure": _structured_failure(
                scope=normalized_scope,
                code="receipt_not_object",
                message="sealed context receipt root is not an object",
                details={"path": str(path)},
            ),
        }
    receipt = dict(payload or {})
    version_failure = _version_failure(receipt, scope=normalized_scope)
    if version_failure:
        receipt = _migrate_legacy_receipt(receipt, scope=normalized_scope, failure=version_failure)
    return receipt


def save_sealed_context_receipt(*, storage_root: Path | None, scope: str, receipt: dict[str, Any]) -> None:
    path = sealed_context_receipt_path(storage_root=storage_root, scope=scope)
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_json_stable(dict(receipt or {})), ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )


def sealed_context_receipt_path(*, storage_root: Path | None, scope: str) -> Path | None:
    if storage_root is None:
        return None
    try:
        project_root = ProjectLayout.from_backend_dir(Path(storage_root)).project_root.resolve()
    except Exception:
        project_root = Path(storage_root).resolve().parent
    safe_scope = safe_context_receipt_filename(scope)
    if not safe_scope:
        return None
    return project_root / "storage" / "runtime_state" / "context_receipts" / "sealed_append_only_context" / f"{safe_scope}.json"


def safe_context_receipt_filename(value: str) -> str:
    text = str(value or "").strip()
    result = []
    for char in text:
        if char.isalnum() or char in {"-", "_", "."}:
            result.append(char)
        else:
            result.append("_")
    return "".join(result).strip("._")[:180] or "default"


def _receipt_for_assignment(
    receipt: dict[str, Any],
    *,
    scope: str,
    receipt_authority: str,
    failure: dict[str, Any],
) -> dict[str, Any]:
    if not receipt:
        return _new_receipt(scope=scope, authority=receipt_authority, status="ok")
    if failure:
        migrated = _new_receipt(scope=scope, authority=receipt_authority, status="recovery_required")
        migrated["recovery_events"] = [failure]
        return migrated
    payload = dict(receipt or {})
    payload.setdefault("schema_version", SEALED_CONTEXT_RECEIPT_SCHEMA_VERSION)
    payload.setdefault("normalization_version", SEALED_CONTEXT_NORMALIZATION_VERSION)
    payload.setdefault("scope", scope)
    payload.setdefault("status", "ok")
    payload.setdefault("items", {})
    payload.setdefault("entries", [])
    return payload


def _new_receipt(*, scope: str, authority: str, status: str) -> dict[str, Any]:
    return {
        "authority": str(authority or "runtime.context_management.sealed_context"),
        "schema_version": SEALED_CONTEXT_RECEIPT_SCHEMA_VERSION,
        "normalization_version": SEALED_CONTEXT_NORMALIZATION_VERSION,
        "scope": str(scope or "default"),
        "status": str(status or "ok"),
        "next_append_index": 1,
        "items": {},
        "entries": [],
        "created_at": time.time(),
        "updated_at": time.time(),
    }


def _migrate_legacy_receipt(receipt: dict[str, Any], *, scope: str, failure: dict[str, Any]) -> dict[str, Any]:
    legacy_items = dict(receipt.get("items") or {}) if isinstance(receipt.get("items"), dict) else {}
    entries = []
    for item_key, raw_index in sorted(legacy_items.items(), key=lambda item: _safe_int(item[1])):
        append_index = _safe_int(raw_index)
        if append_index <= 0:
            continue
        entries.append(
            _sealed_entry(
                append_index=append_index,
                item_key=str(item_key or ""),
                provider_visible_hash="",
                provider_visible_message={},
                kind="legacy_unverified",
                source_ref="legacy_receipt_items",
                previous_receipt_hash="",
            )
        )
    payload = _new_receipt(scope=scope, authority=str(receipt.get("authority") or ""), status="recovery_required")
    payload["items"] = {str(key): _safe_int(value) for key, value in legacy_items.items() if _safe_int(value) > 0}
    payload["entries"] = entries
    payload["next_append_index"] = max([_safe_int(entry.get("append_index")) for entry in entries] or [0]) + 1
    payload["migrated_from_schema_version"] = _safe_int(receipt.get("schema_version") or receipt.get("version") or 1)
    payload["legacy_receipt_hash"] = _stable_json_hash(receipt)
    payload["recovery_events"] = [failure]
    return _finalize_receipt(payload, scope=scope, authority=str(payload.get("authority") or ""))


def _version_failure(receipt: dict[str, Any], *, scope: str) -> dict[str, Any]:
    schema_version = _safe_int(receipt.get("schema_version"))
    normalization = str(receipt.get("normalization_version") or "")
    if schema_version == SEALED_CONTEXT_RECEIPT_SCHEMA_VERSION and normalization == SEALED_CONTEXT_NORMALIZATION_VERSION:
        return {}
    return _structured_failure(
        scope=scope,
        code="receipt_schema_version_mismatch",
        message="sealed context receipt schema or normalization version does not match the active provider-visible ledger",
        details={
            "schema_version": schema_version,
            "normalization_version": normalization,
            "expected_schema_version": SEALED_CONTEXT_RECEIPT_SCHEMA_VERSION,
            "expected_normalization_version": SEALED_CONTEXT_NORMALIZATION_VERSION,
            "legacy_version": receipt.get("version"),
            "legacy_schema_revision": receipt.get("schema_revision"),
        },
    )


def _receipt_failure(receipt: dict[str, Any]) -> dict[str, Any]:
    failure = dict(receipt.get("receipt_failure") or {}) if isinstance(receipt.get("receipt_failure"), dict) else {}
    if failure:
        return failure
    return {}


def _record_recovery_event(receipt: dict[str, Any], failure: dict[str, Any]) -> dict[str, Any]:
    payload = dict(receipt or {})
    events = [dict(item) for item in list(payload.get("recovery_events") or []) if isinstance(item, dict)]
    events.append(dict(failure or {}))
    payload["recovery_events"] = events
    payload["status"] = "recovery_required"
    return payload


def _finalize_receipt(
    receipt: dict[str, Any],
    *,
    scope: str,
    authority: str,
    transport_contract_hash: str = "",
    stable_base_hash: str = "",
    physical_prefix_hash: str = "",
    sealed_context_hash: str = "",
) -> dict[str, Any]:
    payload = dict(receipt or {})
    payload["authority"] = str(authority or payload.get("authority") or "runtime.context_management.sealed_context")
    payload["schema_version"] = SEALED_CONTEXT_RECEIPT_SCHEMA_VERSION
    payload["normalization_version"] = SEALED_CONTEXT_NORMALIZATION_VERSION
    payload["scope"] = str(scope or payload.get("scope") or "default")
    payload["items"] = dict(payload.get("items") or {}) if isinstance(payload.get("items"), dict) else {}
    payload["entries"] = [dict(item) for item in list(payload.get("entries") or []) if isinstance(item, dict)]
    payload["append_index"] = max([_safe_int(entry.get("append_index")) for entry in payload["entries"]] or [0])
    payload["next_append_index"] = max(_safe_int(payload.get("next_append_index")), int(payload["append_index"]) + 1)
    payload["updated_at"] = time.time()
    for field_name, value in {
        "transport_contract_hash": transport_contract_hash,
        "stable_base_hash": stable_base_hash,
        "physical_prefix_hash": physical_prefix_hash,
        "sealed_context_hash": sealed_context_hash,
    }.items():
        if str(value or "").strip():
            payload[field_name] = str(value or "").strip()
    content_hash = _receipt_content_hash(payload)
    payload["receipt_hash"] = content_hash
    payload["receipt_id"] = "sealedctx:" + content_hash[:16]
    return payload


def _sealed_entry(
    *,
    append_index: int,
    item_key: str,
    provider_visible_hash: str,
    provider_visible_message: dict[str, Any],
    kind: str,
    source_ref: str,
    previous_receipt_hash: str,
) -> dict[str, Any]:
    payload = {
        "append_index": int(append_index or 0),
        "item_key": str(item_key or ""),
        "provider_visible_hash": str(provider_visible_hash or ""),
        "provider_visible_message": dict(provider_visible_message or {}),
        "kind": str(kind or ""),
        "source_ref": str(source_ref or ""),
        "previous_receipt_hash": str(previous_receipt_hash or ""),
        "normalization_version": SEALED_CONTEXT_NORMALIZATION_VERSION,
        "created_at": time.time(),
    }
    payload["entry_hash"] = _stable_json_hash(payload)
    return payload


def _provider_visible_message(value: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return _json_stable(dict(value or {}))


def _entries_by_index(receipt: dict[str, Any]) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for raw in list(receipt.get("entries") or []):
        if not isinstance(raw, dict):
            continue
        index = _safe_int(raw.get("append_index"))
        if index > 0:
            result[index] = dict(raw)
    return result


def _next_append_index(receipt: dict[str, Any], *, entries: dict[int, dict[str, Any]]) -> int:
    next_index = _safe_int(receipt.get("next_append_index"))
    if next_index > 0:
        return next_index
    item_indexes = [
        _safe_int(value)
        for value in dict(receipt.get("items") or {}).values()
    ] if isinstance(receipt.get("items"), dict) else []
    return max([*item_indexes, *entries.keys(), 0]) + 1


def _structured_failure(*, scope: str, code: str, message: str, details: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": str(code or "sealed_context_receipt_failure"),
        "message": str(message or ""),
        "scope": str(scope or "default"),
        "severity": "p0",
        "recovery_policy": "use_lossless_receipt_migration_or_compacted_recovery_context_before_trusting_cache_lineage",
        "recovery_position": "sealed_context_prefix",
        "details": dict(details or {}),
        "authority": "runtime.context_management.sealed_context.structured_failure",
    }


def _receipt_content_hash(receipt: dict[str, Any]) -> str:
    payload = {
        key: value
        for key, value in dict(receipt or {}).items()
        if key not in {"receipt_hash", "receipt_id", "updated_at"}
    }
    return _stable_json_hash(payload)


def _stable_json_hash(value: Any) -> str:
    payload = json.dumps(_json_stable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()


def _json_stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_stable(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_json_stable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
