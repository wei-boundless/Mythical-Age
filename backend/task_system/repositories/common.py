from __future__ import annotations

from typing import Any


def next_prefixed_id(existing_ids: list[str], *, prefix: str, width: int = 6) -> str:
    max_value = 0
    for raw in existing_ids:
        value = str(raw or "").strip()
        if not value.startswith(prefix):
            continue
        suffix = value[len(prefix):]
        if suffix.isdigit():
            max_value = max(max_value, int(suffix))
    return f"{prefix}{max_value + 1:0{width}d}"


def merge_authoritative_defaults_by_key(
    default_items: list[dict[str, Any]],
    stored_items: list[dict[str, Any]],
    *,
    key: str,
) -> list[dict[str, Any]]:
    defaults_by_key = {
        str(item.get(key) or "").strip(): dict(item)
        for item in default_items
        if str(item.get(key) or "").strip()
    }
    merged: dict[str, dict[str, Any]] = {item_key: dict(item) for item_key, item in defaults_by_key.items()}
    for stored in stored_items:
        item_key = str(stored.get(key) or "").strip()
        if not item_key:
            continue
        default_item = dict(defaults_by_key.get(item_key) or {})
        if default_item and is_system_managed_item(default_item):
            continue
        if default_item:
            merged[item_key] = {**default_item, **dict(stored)}
            continue
        merged[item_key] = dict(stored)
    return list(merged.values())


def merge_default_overlay_by_key(
    default_items: list[dict[str, Any]],
    stored_items: list[dict[str, Any]],
    *,
    key: str,
) -> list[dict[str, Any]]:
    defaults_by_key = {
        str(item.get(key) or "").strip(): dict(item)
        for item in default_items
        if str(item.get(key) or "").strip()
    }
    merged: dict[str, dict[str, Any]] = {}
    for item_key, item in defaults_by_key.items():
        merged[item_key] = dict(item)
    for stored in stored_items:
        item_key = str(stored.get(key) or "").strip()
        if not item_key:
            continue
        base = dict(defaults_by_key.get(item_key) or {})
        merged_item = {**base, **dict(stored)}
        if isinstance(base.get("metadata"), dict) or isinstance(stored.get("metadata"), dict):
            merged_item["metadata"] = {
                **dict(base.get("metadata") or {}),
                **{
                    meta_key: meta_value
                    for meta_key, meta_value in dict(stored.get("metadata") or {}).items()
                    if meta_value not in ("", None, [], {})
                    or meta_key not in dict(base.get("metadata") or {})
                },
            }
        if isinstance(base.get("task_policy"), dict) or isinstance(stored.get("task_policy"), dict):
            base_policy = dict(base.get("task_policy") or {})
            stored_policy = dict(stored.get("task_policy") or {})
            merged_policy = {**base_policy, **stored_policy}
            if isinstance(base_policy.get("task_structure"), dict) or isinstance(stored_policy.get("task_structure"), dict):
                merged_policy["task_structure"] = {
                    **dict(base_policy.get("task_structure") or {}),
                    **dict(stored_policy.get("task_structure") or {}),
                }
            if isinstance(base_policy.get("safety_policy"), dict) or isinstance(stored_policy.get("safety_policy"), dict):
                merged_policy["safety_policy"] = {
                    **dict(base_policy.get("safety_policy") or {}),
                    **dict(stored_policy.get("safety_policy") or {}),
                }
            merged_item["task_policy"] = merged_policy
        merged[item_key] = merged_item
    return list(merged.values())


def merge_items_by_key(
    default_items: list[dict[str, Any]],
    stored_items: list[dict[str, Any]],
    *,
    key: str,
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for item in default_items:
        item_key = str(item.get(key) or "").strip()
        if item_key:
            merged[item_key] = dict(item)
    for item in stored_items:
        item_key = str(item.get(key) or "").strip()
        if item_key:
            merged[item_key] = dict(item)
    return list(merged.values())


def is_system_managed_item(item: dict[str, Any]) -> bool:
    metadata = dict(item.get("metadata") or {})
    if str(metadata.get("managed_by") or "").strip() == "task_system":
        return True
    return bool(str(metadata.get("task_resource") or "").strip())


