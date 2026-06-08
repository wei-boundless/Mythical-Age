from __future__ import annotations

from typing import Any

from harness.runtime.public_timeline_projection import compact, public_text, stable_id


def public_todo_plan_item(plan: dict[str, Any]) -> dict[str, Any]:
    todo_plan = _record(plan)
    items = [_public_todo_item(item) for item in list(todo_plan.get("items") or []) if isinstance(item, dict)]
    items = [item for item in items if item]
    if not items:
        return {}
    completed = sum(1 for item in items if item.get("status") == "completed")
    refs = _trace_refs(todo_plan)
    return compact(
        {
            "item_id": stable_id("todo-plan", ",".join(refs), _text(todo_plan.get("plan_id")), str(items)),
            "kind": "todo_plan",
            "surface": "status",
            "source_authority": "runtime",
            "title": "处理清单",
            "detail": f"{completed}/{len(items)} 已完成",
            "state": "done" if todo_plan.get("completion_ready") else "running",
            "todo_items": items,
            "active_item_id": _text(todo_plan.get("active_item_id")),
            "completion_ready": bool(todo_plan.get("completion_ready")),
            "trace_refs": refs,
        }
    )


def _public_todo_item(item: dict[str, Any]) -> dict[str, Any]:
    content = public_text(item.get("content"), limit=180)
    return compact(
        {
            "todo_id": _text(item.get("todo_id")),
            "content": content,
            "active_form": public_text(item.get("active_form"), limit=180) or content,
            "status": _text(item.get("status") or "pending"),
            "notes": public_text(item.get("notes"), limit=180),
        }
    )


def _trace_refs(value: dict[str, Any]) -> list[str]:
    refs = value.get("trace_refs") or value.get("technical_trace_refs") or []
    if not isinstance(refs, list):
        return []
    return [_text(item) for item in refs if _text(item)]


def _record(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: Any) -> str:
    return str(value or "").strip()
