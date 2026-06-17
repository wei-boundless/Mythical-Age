from __future__ import annotations

from typing import Any

from .models import compact_text, dict_tuple, drop_empty


DEFAULT_TODO_OPERATIONS = ("replace", "append", "start", "complete", "update_status", "remove", "clear", "view")


def project_todo_plan(
    value: dict[str, Any],
    *,
    content_keys: tuple[str, ...] = ("content", "title"),
    allowed_operations: list[str] | tuple[str, ...] | None = None,
    authority: str | None = None,
) -> dict[str, Any]:
    if not value:
        return {}
    items: list[dict[str, Any]] = []
    for item in dict_tuple(value.get("items"))[:40]:
        todo_id = str(item.get("todo_id") or "").strip()
        if not todo_id:
            continue
        items.append(
            drop_empty(
                {
                    "todo_id": todo_id,
                    "content": compact_text(_first_text(item, content_keys), limit=180),
                    "active_form": compact_text(item.get("active_form") or "", limit=120),
                    "status": str(item.get("status") or ""),
                    "notes": compact_text(item.get("notes") or "", limit=180),
                    "evidence_expectations": [
                        str(entry)
                        for entry in list(item.get("evidence_expectations") or [])
                        if str(entry).strip()
                    ],
                    "contract_refs": [
                        str(entry)
                        for entry in list(item.get("contract_refs") or [])
                        if str(entry).strip()
                    ],
                }
            )
        )
    return drop_empty(
        {
            "plan_id": str(value.get("plan_id") or ""),
            "active_item_id": str(value.get("active_item_id") or ""),
            "completion_ready": value.get("completion_ready") if isinstance(value.get("completion_ready"), bool) else None,
            "items": items,
            "allowed_operations": list(allowed_operations or value.get("allowed_operations") or DEFAULT_TODO_OPERATIONS),
            "authority": str(authority or value.get("authority") or "agent.todo_plan"),
        }
    )


def _first_text(item: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = str(item.get(key) or "").strip()
        if value:
            return value
    return ""
