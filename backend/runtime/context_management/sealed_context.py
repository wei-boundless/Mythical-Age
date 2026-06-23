from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from project_layout import ProjectLayout


SEALED_CONTEXT_NORMALIZATION_VERSION = "provider_visible_message_v1"


def assign_sealed_append_order(
    *,
    storage_root: Path | None,
    scope: str,
    item_key: str,
    receipt_authority: str,
    transport_contract_hash: str = "",
    stable_base_hash: str = "",
    physical_prefix_hash: str = "",
    sealed_context_hash: str = "",
) -> dict[str, Any]:
    normalized_scope = str(scope or "default").strip() or "default"
    key = str(item_key or "").strip()
    if not key:
        raise ValueError("sealed append item_key is required")
    receipt = load_sealed_context_receipt(storage_root=storage_root, scope=normalized_scope)
    receipt_needs_upgrade = _receipt_needs_upgrade(receipt)
    items = {} if receipt_needs_upgrade else dict(receipt.get("items") or {}) if isinstance(receipt.get("items"), dict) else {}
    next_order = 1 if receipt_needs_upgrade else _safe_int(receipt.get("next_order")) or (max([_safe_int(value) for value in items.values()] or [0]) + 1)
    existing_order = _safe_int(items.get(key))
    order_source = "receipt"
    changed = False
    if existing_order <= 0:
        existing_order = next_order
        items[key] = existing_order
        next_order += 1
        changed = True
        order_source = "new_append" if receipt.get("items") else "bootstrap"
    updated = {
        "authority": str(receipt_authority or "runtime.context_management.sealed_context"),
        "normalization_version": SEALED_CONTEXT_NORMALIZATION_VERSION,
        "scope": normalized_scope,
        "next_order": next_order,
        "items": items,
        "append_index": max([_safe_int(value) for value in items.values()] or [0]),
        "updated_at": time.time(),
    }
    for field_name, value in {
        "transport_contract_hash": transport_contract_hash,
        "stable_base_hash": stable_base_hash,
        "physical_prefix_hash": physical_prefix_hash,
        "sealed_context_hash": sealed_context_hash,
    }.items():
        if str(value or "").strip():
            updated[field_name] = str(value or "").strip()
    updated["receipt_id"] = "sealedctx:" + _stable_json_hash(
        {
            "scope": updated["scope"],
            "normalization_version": updated["normalization_version"],
            "items": updated["items"],
            "transport_contract_hash": updated.get("transport_contract_hash", ""),
            "stable_base_hash": updated.get("stable_base_hash", ""),
            "sealed_context_hash": updated.get("sealed_context_hash", ""),
        }
    )[:16]
    if changed or receipt_needs_upgrade:
        save_sealed_context_receipt(storage_root=storage_root, scope=normalized_scope, receipt=updated)
    return {
        "order": existing_order,
        "order_source": order_source,
        "receipt": updated,
        "changed": changed,
        "authority": "runtime.context_management.sealed_context.assign_sealed_append_order",
    }


def load_sealed_context_receipt(*, storage_root: Path | None, scope: str) -> dict[str, Any]:
    path = sealed_context_receipt_path(storage_root=storage_root, scope=scope)
    if path is None or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload or {}) if isinstance(payload, dict) else {}


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


def _receipt_needs_upgrade(receipt: dict[str, Any]) -> bool:
    if not receipt:
        return False
    return (
        str(receipt.get("normalization_version") or "") != SEALED_CONTEXT_NORMALIZATION_VERSION
        or "schema_revision" in receipt
        or "version" in receipt
    )


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
