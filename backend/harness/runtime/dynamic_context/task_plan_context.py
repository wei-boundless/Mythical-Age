from __future__ import annotations

from typing import Any

from .models import compact_text, dict_tuple, drop_empty, stable_json_hash
from .todo_plan_projection import project_todo_plan


def build_task_plan_context(
    task_state: dict[str, Any],
    *,
    task_run_id: str = "",
    task_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    plan_contract = _plan_contract_from_task_contract(task_contract)
    todo_source = _latest_todo_source(task_state)
    todo_plan = dict(todo_source.get("todo_plan") or {})
    if not plan_contract and not todo_plan:
        return {}

    plan_id = str(plan_contract.get("plan_id") or todo_plan.get("plan_id") or "current").strip() or "current"
    baseline_items = _baseline_items(plan_contract, fallback_todo_plan=todo_plan if not plan_contract else {})
    baseline_seed = {
        "plan_id": plan_id,
        "mode_instance_id": str(plan_contract.get("mode_instance_id") or ""),
        "plan_version": str(plan_contract.get("plan_version") or ""),
        "plan_status": str(plan_contract.get("plan_status") or ""),
        "strategy_summary": str(plan_contract.get("strategy_summary") or ""),
        "allowed_plan_operations": list(plan_contract.get("allowed_plan_operations") or []),
        "items": baseline_items,
    }
    plan_sha256 = stable_json_hash(baseline_seed)
    baseline_ref = _baseline_ref(task_run_id=task_run_id, plan_id=plan_id, plan_sha256=plan_sha256)
    step_refs = {
        str(item.get("step_id") or ""): _step_ref(baseline_ref=baseline_ref, step_id=item.get("step_id"))
        for item in baseline_items
        if str(item.get("step_id") or "").strip()
    }
    visible_baseline_items = [
        {**item, "step_ref": step_refs.get(str(item.get("step_id") or ""), str(item.get("step_ref") or ""))}
        for item in baseline_items
    ]
    cursor = _todo_cursor(todo_plan, baseline_ref=baseline_ref, step_refs=step_refs)
    cursor_hash = stable_json_hash(cursor) if cursor else ""
    return drop_empty(
        {
            "task_plan_context": drop_empty(
                {
                    "task_plan_baseline": drop_empty(
                        {
                            "plan_baseline_ref": baseline_ref,
                            "plan_id": plan_id,
                            "mode_instance_id": str(plan_contract.get("mode_instance_id") or ""),
                            "mode_role": str(plan_contract.get("mode_role") or ""),
                            "plan_sha256": plan_sha256,
                            "plan_version": str(plan_contract.get("plan_version") or plan_sha256.removeprefix("sha256:")[:16]),
                            "plan_status": str(plan_contract.get("plan_status") or "agent_managed"),
                            "strategy_summary": compact_text(plan_contract.get("strategy_summary") or "", limit=360),
                            "allowed_plan_operations": list(plan_contract.get("allowed_plan_operations") or []),
                            "replan_policy": dict(plan_contract.get("replan_policy") or {}),
                            "items": visible_baseline_items,
                            "todo_rehydration_action": "agent_todo:view",
                            "authority": "harness.runtime.dynamic_context.task_plan_baseline",
                        }
                    ),
                    "todo_cursor": cursor,
                    "task_plan_delta": drop_empty(
                        {
                            "event": "plan_contract_with_todo_cursor_visible",
                            "plan_baseline_ref": baseline_ref,
                            "source_observation_ref": str(todo_source.get("observation_ref") or ""),
                            "source_tool": str(todo_source.get("tool_name") or "agent_todo"),
                            "cursor_hash": cursor_hash,
                            "change_model": "plan_contract_baseline_plus_todo_cursor",
                            "authority": "harness.runtime.dynamic_context.task_plan_delta",
                        }
                    ),
                    "authority": "harness.runtime.dynamic_context.task_plan_context",
                }
            )
        }
    )


def _plan_contract_from_task_contract(task_contract: dict[str, Any] | None) -> dict[str, Any]:
    contract = dict(task_contract or {})
    plan_mode = _work_mode_from_task_contract(contract, "plan")
    raw = dict(plan_mode.get("contract") or {}) if plan_mode else {}
    if not raw:
        legacy_plan = contract.get("plan_contract")
        raw = dict(legacy_plan or {}) if isinstance(legacy_plan, dict) else {}
    if not raw:
        completion_criteria = [
            compact_text(value, limit=220)
            for value in list(contract.get("completion_criteria") or [])
            if str(value).strip()
        ]
        raw = drop_empty(
            {
                "plan_id": str(contract.get("plan_ref") or contract.get("external_plan_ref") or "plan:agent-managed"),
                "plan_status": "agent_managed",
                "major_steps": completion_criteria,
                "strategy_summary": "Agent manages the task strategy; todo is only the execution cursor.",
                "allowed_plan_operations": ["create", "update", "replan", "explain_deviation"],
            }
        )
    return drop_empty(
        {
            "plan_id": str(raw.get("plan_id") or _external_plan_ref(raw) or "plan:agent-managed").strip(),
            "mode_instance_id": str(plan_mode.get("mode_instance_id") or "").strip(),
            "mode_role": str(plan_mode.get("mode_role") or "").strip(),
            "plan_version": str(raw.get("plan_version") or "").strip(),
            "plan_status": str(raw.get("plan_status") or raw.get("approval_state") or "agent_managed").strip(),
            "strategy_summary": compact_text(raw.get("strategy_summary") or "", limit=360),
            "major_steps": _major_step_items(raw.get("major_steps") or raw.get("steps")),
            "allowed_plan_operations": [
                compact_text(value, limit=120)
                for value in list(raw.get("allowed_plan_operations") or raw.get("allowed_operations") or [])
                if str(value).strip()
            ],
            "replan_policy": dict(raw.get("replan_policy") or {}) if isinstance(raw.get("replan_policy"), dict) else {},
            "authority": str(raw.get("authority") or "harness.runtime.dynamic_context.plan_contract"),
        }
    )


def _work_mode_from_task_contract(task_contract: dict[str, Any], mode_kind: str) -> dict[str, Any]:
    contract = dict(task_contract or {})
    task_run_contract = (
        dict(contract.get("task_run_contract") or {})
        if isinstance(contract.get("task_run_contract"), dict)
        else contract
    )
    work_modes = [
        dict(item)
        for item in list(task_run_contract.get("work_modes") or [])
        if isinstance(item, dict)
    ]
    if not work_modes:
        return {}
    container_contract = (
        dict(task_run_contract.get("container_contract") or {})
        if isinstance(task_run_contract.get("container_contract"), dict)
        else {}
    )
    primary_ref = str(container_contract.get("primary_work_mode_ref") or "").strip()
    candidate: dict[str, Any] = {}
    for item in work_modes:
        if str(item.get("mode_kind") or "").strip() != mode_kind:
            continue
        if primary_ref and str(item.get("mode_instance_id") or "").strip() == primary_ref:
            return item
        if str(item.get("mode_role") or "").strip() == "primary":
            return item
        if not candidate:
            candidate = item
    return candidate


def _external_plan_ref(plan_contract: dict[str, Any]) -> str:
    value = plan_contract.get("external_plan_ref")
    if isinstance(value, dict):
        return str(value.get("ref") or value.get("id") or "").strip()
    return str(value or "").strip()


def _latest_todo_source(task_state: dict[str, Any]) -> dict[str, Any]:
    latest: dict[str, Any] = {}
    for item in dict_tuple(dict(task_state or {}).get("latest_tool_results")):
        tool_name = _tool_name(item.get("tool_name") or item.get("source"))
        if tool_name != "agent_todo":
            continue
        todo_plan = project_todo_plan(dict(item.get("todo_plan") or {}))
        if not todo_plan:
            continue
        latest = {
            "todo_plan": todo_plan,
            "observation_ref": str(item.get("observation_ref") or item.get("observation_id") or ""),
            "tool_name": tool_name,
        }
    return latest


def _major_step_items(value: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    raw_values = value if isinstance(value, (list, tuple)) else ([value] if value else [])
    for index, item in enumerate(raw_values, start=1):
        if isinstance(item, dict):
            title = compact_text(item.get("title") or item.get("content") or item.get("summary") or "", limit=220)
            if not title:
                continue
            step_id = str(item.get("step_id") or item.get("id") or f"plan_step:{index}").strip()
            items.append(drop_empty({"step_id": step_id, "title": title, "source": "plan_contract"}))
            continue
        title = compact_text(item, limit=220)
        if title:
            items.append({"step_id": f"plan_step:{index}", "title": title, "source": "plan_contract"})
    return items


def _baseline_items(plan_contract: dict[str, Any], *, fallback_todo_plan: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for item in list(plan_contract.get("major_steps") or [])[:40]:
        step_id = str(item.get("step_id") or "").strip()
        if not step_id:
            continue
        items.append(
            drop_empty(
                {
                    "step_ref": f"planstep:pending:{step_id}",
                    "step_id": step_id,
                    "title": compact_text(item.get("title") or "", limit=220),
                    "source": str(item.get("source") or "plan_contract"),
                }
            )
        )
    if items:
        return items
    fallback = dict(fallback_todo_plan or {})
    for item in dict_tuple(fallback.get("items"))[:40]:
        todo_id = str(item.get("todo_id") or "").strip()
        if not todo_id:
            continue
        items.append(
            drop_empty(
                {
                    "step_ref": f"planstep:pending:{todo_id}",
                    "step_id": todo_id,
                    "title": compact_text(item.get("content") or item.get("title") or "", limit=220),
                    "source": "todo_cursor_fallback",
                }
            )
        )
    return items


def _todo_cursor(todo_plan: dict[str, Any], *, baseline_ref: str, step_refs: dict[str, str]) -> dict[str, Any]:
    if not todo_plan:
        return {}
    item_statuses: list[dict[str, Any]] = []
    status_counts: dict[str, int] = {}
    active_item_id = str(todo_plan.get("active_item_id") or "").strip()
    for item in dict_tuple(todo_plan.get("items"))[:40]:
        todo_id = str(item.get("todo_id") or "").strip()
        if not todo_id:
            continue
        status = str(item.get("status") or "").strip()
        if status:
            status_counts[status] = status_counts.get(status, 0) + 1
        step_ref = step_refs.get(todo_id) or _step_ref(baseline_ref=baseline_ref, step_id=todo_id)
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
            "active_step_ref": (step_refs.get(active_item_id) or _step_ref(baseline_ref=baseline_ref, step_id=active_item_id)) if active_item_id else "",
            "completion_ready_signal": (
                {
                    "reported_by": "agent_todo",
                    "value": todo_plan.get("completion_ready"),
                    "authority": "progress_signal_not_completion_gate",
                }
                if isinstance(todo_plan.get("completion_ready"), bool)
                else None
            ),
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
            "authority": "harness.runtime.dynamic_context.todo_cursor",
        }
    )


def _baseline_ref(*, task_run_id: str, plan_id: str, plan_sha256: str) -> str:
    scope = str(task_run_id or "session").replace(":", "_")
    plan = str(plan_id or "current").replace(":", "_")
    digest = str(plan_sha256 or "").removeprefix("sha256:")[:16]
    return f"taskplan:{scope}:{plan}:{digest}"


def _step_ref(*, baseline_ref: str, step_id: Any) -> str:
    return f"{baseline_ref}:step:{str(step_id or '').strip()}"


def _tool_name(value: Any) -> str:
    text = str(value or "").strip()
    return text.split(":", 1)[1] if text.startswith("tool:") else text
