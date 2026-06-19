from __future__ import annotations

from typing import Any

from .models import compact_text, dict_tuple, drop_empty, stable_json_hash
from .todo_plan_projection import project_todo_plan


def build_task_plan_context(task_state: dict[str, Any], *, task_run_id: str = "") -> dict[str, Any]:
    plan_source = _latest_plan_source(task_state)
    plan = dict(plan_source.get("plan") or {})
    if not plan:
        return {}

    baseline_items = _baseline_items(plan)
    if not baseline_items:
        return {}

    plan_id = str(plan.get("plan_id") or "current").strip() or "current"
    baseline_seed = {
        "plan_id": plan_id,
        "allowed_operations": list(plan.get("allowed_operations") or []),
        "items": baseline_items,
    }
    plan_sha256 = stable_json_hash(baseline_seed)
    baseline_ref = _baseline_ref(task_run_id=task_run_id, plan_id=plan_id, plan_sha256=plan_sha256)
    step_refs = {
        str(item.get("todo_id") or ""): _step_ref(baseline_ref=baseline_ref, todo_id=item.get("todo_id"))
        for item in baseline_items
        if str(item.get("todo_id") or "").strip()
    }
    visible_baseline_items = [
        {**item, "step_ref": step_refs.get(str(item.get("todo_id") or ""), str(item.get("step_ref") or ""))}
        for item in baseline_items
    ]
    cursor = _cursor(plan, baseline_ref=baseline_ref, step_refs=step_refs)
    cursor_hash = stable_json_hash(cursor) if cursor else ""
    return drop_empty(
        {
            "task_plan_context": drop_empty(
                {
                    "task_plan_baseline": drop_empty(
                        {
                            "plan_baseline_ref": baseline_ref,
                            "plan_id": plan_id,
                            "plan_sha256": plan_sha256,
                            "plan_version": plan_sha256.removeprefix("sha256:")[:16],
                            "approval_state": str(plan.get("approval_state") or "agent_managed"),
                            "allowed_operations": list(plan.get("allowed_operations") or []),
                            "items": visible_baseline_items,
                            "rehydration_action": "agent_todo:view",
                            "authority": "harness.runtime.dynamic_context.task_plan_baseline",
                        }
                    ),
                    "task_plan_cursor": cursor,
                    "task_plan_delta": drop_empty(
                        {
                            "event": "task_plan_cursor_visible",
                            "plan_baseline_ref": baseline_ref,
                            "source_observation_ref": str(plan_source.get("observation_ref") or ""),
                            "source_tool": str(plan_source.get("tool_name") or "agent_todo"),
                            "cursor_hash": cursor_hash,
                            "change_model": "baseline_content_plus_status_cursor",
                            "authority": "harness.runtime.dynamic_context.task_plan_delta",
                        }
                    ),
                    "authority": "harness.runtime.dynamic_context.task_plan_context",
                }
            )
        }
    )


def _latest_plan_source(task_state: dict[str, Any]) -> dict[str, Any]:
    latest: dict[str, Any] = {}
    for item in dict_tuple(dict(task_state or {}).get("latest_tool_results")):
        tool_name = _tool_name(item.get("tool_name") or item.get("source"))
        if tool_name != "agent_todo":
            continue
        plan = project_todo_plan(dict(item.get("todo_plan") or {}))
        if not plan:
            continue
        latest = {
            "plan": plan,
            "observation_ref": str(item.get("observation_ref") or item.get("observation_id") or ""),
            "tool_name": tool_name,
        }
    return latest


def _baseline_items(plan: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for item in dict_tuple(plan.get("items"))[:40]:
        todo_id = str(item.get("todo_id") or "").strip()
        if not todo_id:
            continue
        items.append(
            drop_empty(
                {
                    "step_ref": f"planstep:pending:{todo_id}",
                    "todo_id": todo_id,
                    "title": compact_text(item.get("content") or item.get("title") or "", limit=220),
                    "active_form": compact_text(item.get("active_form") or "", limit=160),
                    "evidence_expectations": [
                        compact_text(value, limit=180)
                        for value in list(item.get("evidence_expectations") or [])[:8]
                        if str(value).strip()
                    ],
                    "contract_refs": [
                        compact_text(value, limit=180)
                        for value in list(item.get("contract_refs") or [])[:8]
                        if str(value).strip()
                    ],
                }
            )
        )
    return items


def _cursor(plan: dict[str, Any], *, baseline_ref: str, step_refs: dict[str, str]) -> dict[str, Any]:
    item_statuses: list[dict[str, Any]] = []
    status_counts: dict[str, int] = {}
    active_item_id = str(plan.get("active_item_id") or "").strip()
    for item in dict_tuple(plan.get("items"))[:40]:
        todo_id = str(item.get("todo_id") or "").strip()
        if not todo_id:
            continue
        status = str(item.get("status") or "").strip()
        if status:
            status_counts[status] = status_counts.get(status, 0) + 1
        step_ref = step_refs.get(todo_id) or _step_ref(baseline_ref=baseline_ref, todo_id=todo_id)
        item_statuses.append(
            drop_empty(
                {
                    "step_ref": step_ref,
                    "todo_id": todo_id,
                    "status": status,
                    "active": True if todo_id == active_item_id else None,
                    "notes": compact_text(item.get("notes") or "", limit=220),
                }
            )
        )
    return drop_empty(
        {
            "plan_baseline_ref": baseline_ref,
            "active_item_id": active_item_id,
            "active_step_ref": step_refs.get(active_item_id, "") if active_item_id else "",
            "completion_ready": plan.get("completion_ready") if isinstance(plan.get("completion_ready"), bool) else None,
            "item_statuses": item_statuses,
            "completed_step_refs": [
                str(item.get("step_ref") or "")
                for item in item_statuses
                if str(item.get("status") or "") == "completed" and str(item.get("step_ref") or "")
            ],
            "blocked_step_refs": [
                str(item.get("step_ref") or "")
                for item in item_statuses
                if str(item.get("status") or "") == "blocked" and str(item.get("step_ref") or "")
            ],
            "status_counts": status_counts,
            "authority": "harness.runtime.dynamic_context.task_plan_cursor",
        }
    )


def _baseline_ref(*, task_run_id: str, plan_id: str, plan_sha256: str) -> str:
    scope = str(task_run_id or "session").replace(":", "_")
    plan = str(plan_id or "current").replace(":", "_")
    digest = str(plan_sha256 or "").removeprefix("sha256:")[:16]
    return f"taskplan:{scope}:{plan}:{digest}"


def _step_ref(*, baseline_ref: str, todo_id: Any) -> str:
    return f"{baseline_ref}:step:{str(todo_id or '').strip()}"


def _tool_name(value: Any) -> str:
    text = str(value or "").strip()
    return text.split(":", 1)[1] if text.startswith("tool:") else text
