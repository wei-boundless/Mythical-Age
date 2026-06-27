from __future__ import annotations

from typing import Any

from .models import compact_text, dict_tuple, drop_empty, stable_json_hash
from .todo_plan_projection import project_todo_plan


def build_task_mode_tail_contexts(
    task_state: dict[str, Any],
    *,
    task_run_id: str = "",
    task_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not _work_modes_from_task_contract(task_contract):
        return {}
    goal_context = _task_goal_context(
        task_run_id=task_run_id,
        goal_contract=_goal_contract_from_task_contract(task_contract),
    )
    plan_context = _task_plan_context(
        task_run_id=task_run_id,
        plan_contract=_plan_contract_from_task_contract(task_contract),
    )
    todo_context = _task_todo_context(
        task_state,
        task_run_id=task_run_id,
        todo_contract=_todo_contract_from_task_contract(task_contract),
    )
    return drop_empty(
        {
            "task_goal_context": goal_context,
            "task_plan_context": plan_context,
            "task_todo_context": todo_context,
        }
    )


def _task_goal_context(*, task_run_id: str, goal_contract: dict[str, Any]) -> dict[str, Any]:
    if not goal_contract:
        return {}
    seed = {
        "mode_instance_id": str(goal_contract.get("mode_instance_id") or ""),
        "mode_role": str(goal_contract.get("mode_role") or ""),
        "user_visible_goal": str(goal_contract.get("user_visible_goal") or ""),
        "task_run_goal": str(goal_contract.get("task_run_goal") or ""),
        "success_definition": str(goal_contract.get("success_definition") or ""),
        "non_goals": list(goal_contract.get("non_goals") or []),
        "completion_evidence": list(goal_contract.get("completion_evidence") or []),
    }
    goal_sha256 = stable_json_hash(seed)
    goal_ref = _mode_ref(task_run_id=task_run_id, mode_kind="goal", mode_id=goal_contract.get("mode_instance_id"), digest=goal_sha256)
    return drop_empty(
        {
            "active_goal": {
                "event": "goal_work_mode_active",
                "goal_ref": goal_ref,
                "goal_sha256": goal_sha256,
                "goal_contract_ref": "task_run_contract_stable.task_run_contract.goal_contract",
                "working_scope_ref": "task_run_contract_stable.task_run_contract.working_scope",
                "agent_use_contract": "Read full goal/scope from task_run_contract_stable; this pins the active version.",
                "authority": "harness.runtime.dynamic_context.task_goal_active_ref",
            },
            "authority": "harness.runtime.dynamic_context.task_mode_tail_context.task_goal_context",
        }
    )


def _task_plan_context(*, task_run_id: str, plan_contract: dict[str, Any]) -> dict[str, Any]:
    if not plan_contract:
        return {}
    plan_id = str(plan_contract.get("plan_id") or "current").strip() or "current"
    baseline_items = _baseline_items(plan_contract)
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
    return drop_empty(
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
                    "authority": "harness.runtime.dynamic_context.task_plan_baseline",
                }
            ),
            "task_plan_delta": {
                "event": "plan_work_mode_visible",
                "plan_baseline_ref": baseline_ref,
                "change_model": "plan_contract_baseline",
                "authority": "harness.runtime.dynamic_context.task_plan_delta",
            },
            "authority": "harness.runtime.dynamic_context.task_mode_tail_context.task_plan_context",
        }
    )


def _task_todo_context(
    task_state: dict[str, Any],
    *,
    task_run_id: str,
    todo_contract: dict[str, Any],
) -> dict[str, Any]:
    todo_source = _latest_todo_source(task_state)
    todo_plan = dict(todo_source.get("todo_plan") or {})
    contract_plan = _todo_plan_from_contract(todo_contract)
    if not todo_contract:
        return {}
    baseline_plan = contract_plan or todo_plan
    todo_id = str(
        todo_contract.get("todo_list_id")
        or baseline_plan.get("plan_id")
        or todo_plan.get("plan_id")
        or "current"
    ).strip() or "current"
    baseline_items = _todo_baseline_items(baseline_plan)
    baseline_seed = {
        "todo_id": todo_id,
        "mode_instance_id": str(todo_contract.get("mode_instance_id") or ""),
        "items": baseline_items,
    }
    todo_sha256 = stable_json_hash(baseline_seed)
    baseline_ref = _mode_ref(task_run_id=task_run_id, mode_kind="todo", mode_id=todo_id, digest=todo_sha256)
    item_refs = {
        str(item.get("todo_id") or ""): _todo_item_ref(baseline_ref=baseline_ref, todo_id=item.get("todo_id"))
        for item in baseline_items
        if str(item.get("todo_id") or "").strip()
    }
    visible_items = [
        {**item, "todo_item_ref": item_refs.get(str(item.get("todo_id") or ""), str(item.get("todo_item_ref") or ""))}
        for item in baseline_items
    ]
    cursor_plan = todo_plan or contract_plan
    cursor = _todo_cursor(cursor_plan, baseline_ref=baseline_ref, item_refs=item_refs)
    cursor_hash = stable_json_hash(cursor) if cursor else ""
    return drop_empty(
        {
            "task_todo_baseline": drop_empty(
                {
                    "todo_baseline_ref": baseline_ref,
                    "todo_list_id": todo_id,
                    "mode_instance_id": str(todo_contract.get("mode_instance_id") or ""),
                    "mode_role": str(todo_contract.get("mode_role") or ""),
                    "todo_sha256": todo_sha256,
                    "completion_policy": str(todo_contract.get("completion_policy") or ""),
                    "allowed_todo_operations": list(cursor_plan.get("allowed_operations") or []),
                    "items": visible_items,
                    "authority": "harness.runtime.dynamic_context.task_todo_baseline",
                }
            ),
            "todo_cursor": cursor,
            "task_todo_delta": drop_empty(
                {
                    "event": "todo_cursor_visible",
                    "todo_baseline_ref": baseline_ref,
                    "source_observation_ref": str(todo_source.get("observation_ref") or ""),
                    "source_tool": str(todo_source.get("tool_name") or "agent_todo") if todo_source else "",
                    "cursor_hash": cursor_hash,
                    "change_model": "todo_contract_baseline_plus_runtime_cursor",
                    "authority": "harness.runtime.dynamic_context.task_todo_delta",
                }
            ),
            "authority": "harness.runtime.dynamic_context.task_mode_tail_context.task_todo_context",
        }
    )


def _plan_contract_from_task_contract(task_contract: dict[str, Any] | None) -> dict[str, Any]:
    contract = dict(task_contract or {})
    plan_mode = _work_mode_from_task_contract(contract, "plan")
    raw = dict(plan_mode.get("contract") or {}) if plan_mode else {}
    if not raw:
        return {}
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


def _goal_contract_from_task_contract(task_contract: dict[str, Any] | None) -> dict[str, Any]:
    contract = dict(task_contract or {})
    goal_mode = _work_mode_from_task_contract(contract, "goal")
    raw = dict(goal_mode.get("contract") or {}) if goal_mode else {}
    if not raw:
        return {}
    return drop_empty(
        {
            "mode_instance_id": str(goal_mode.get("mode_instance_id") or "").strip(),
            "mode_role": str(goal_mode.get("mode_role") or "").strip(),
            "user_visible_goal": compact_text(raw.get("user_visible_goal") or "", limit=500),
            "task_run_goal": compact_text(raw.get("task_run_goal") or raw.get("agent_goal") or "", limit=500),
            "success_definition": compact_text(raw.get("success_definition") or "", limit=500),
            "non_goals": [
                compact_text(value, limit=220)
                for value in list(raw.get("non_goals") or [])
                if str(value).strip()
            ],
            "completion_evidence": [
                compact_text(value, limit=220)
                for value in list(raw.get("completion_evidence") or [])
                if str(value).strip()
            ],
            "evidence_contract": dict(raw.get("evidence_contract") or {}) if isinstance(raw.get("evidence_contract"), dict) else {},
            "working_scope": dict(raw.get("working_scope") or {}) if isinstance(raw.get("working_scope"), dict) else {},
            "authority": str(raw.get("authority") or "harness.runtime.dynamic_context.goal_contract"),
        }
    )


def _todo_contract_from_task_contract(task_contract: dict[str, Any] | None) -> dict[str, Any]:
    contract = dict(task_contract or {})
    todo_mode = _work_mode_from_task_contract(contract, "todo")
    raw = dict(todo_mode.get("contract") or {}) if todo_mode else {}
    if not raw:
        return {}
    return drop_empty(
        {
            "mode_instance_id": str(todo_mode.get("mode_instance_id") or "").strip(),
            "mode_role": str(todo_mode.get("mode_role") or "").strip(),
            "todo_list_id": str(raw.get("todo_list_id") or raw.get("plan_id") or "").strip(),
            "active_item_id": str(raw.get("active_item_id") or "").strip(),
            "items": [
                drop_empty(
                    {
                        "todo_id": str(item.get("todo_id") or item.get("item_id") or item.get("id") or "").strip(),
                        "content": compact_text(item.get("content") or item.get("title") or item.get("summary") or "", limit=220),
                        "status": str(item.get("status") or "").strip(),
                        "notes": compact_text(item.get("notes") or "", limit=220),
                    }
                )
                for item in list(raw.get("items") or [])[:40]
                if isinstance(item, dict)
            ],
            "completion_policy": str(raw.get("completion_policy") or "").strip(),
            "allowed_operations": [
                compact_text(value, limit=120)
                for value in list(raw.get("allowed_todo_operations") or raw.get("allowed_operations") or [])
                if str(value).strip()
            ],
            "working_scope": dict(raw.get("working_scope") or {}) if isinstance(raw.get("working_scope"), dict) else {},
            "authority": str(raw.get("authority") or "harness.runtime.dynamic_context.todo_contract"),
        }
    )


def _work_mode_from_task_contract(task_contract: dict[str, Any], mode_kind: str) -> dict[str, Any]:
    work_modes = _work_modes_from_task_contract(task_contract)
    if not work_modes:
        return {}
    contract = dict(task_contract or {})
    task_run_contract = (
        dict(contract.get("task_run_contract") or {})
        if isinstance(contract.get("task_run_contract"), dict)
        else contract
    )
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


def _work_modes_from_task_contract(task_contract: dict[str, Any] | None) -> list[dict[str, Any]]:
    contract = dict(task_contract or {})
    task_run_contract = (
        dict(contract.get("task_run_contract") or {})
        if isinstance(contract.get("task_run_contract"), dict)
        else contract
    )
    return [
        dict(item)
        for item in list(task_run_contract.get("work_modes") or [])
        if isinstance(item, dict)
    ]


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


def _baseline_items(plan_contract: dict[str, Any]) -> list[dict[str, Any]]:
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
    return items


def _todo_plan_from_contract(todo_contract: dict[str, Any]) -> dict[str, Any]:
    if not todo_contract:
        return {}
    return project_todo_plan(
        {
            "plan_id": str(todo_contract.get("todo_list_id") or ""),
            "active_item_id": str(todo_contract.get("active_item_id") or ""),
            "items": list(todo_contract.get("items") or []),
            "allowed_operations": list(todo_contract.get("allowed_operations") or []),
            "authority": str(todo_contract.get("authority") or "harness.runtime.dynamic_context.todo_contract"),
        },
        content_keys=("content", "title"),
        allowed_operations=list(todo_contract.get("allowed_operations") or []),
        authority="harness.runtime.dynamic_context.todo_contract_plan",
    )


def _todo_baseline_items(todo_plan: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for item in dict_tuple(dict(todo_plan or {}).get("items"))[:40]:
        todo_id = str(item.get("todo_id") or "").strip()
        if not todo_id:
            continue
        items.append(
            drop_empty(
                {
                    "todo_item_ref": f"todoitem:pending:{todo_id}",
                    "todo_id": todo_id,
                    "content": compact_text(item.get("content") or item.get("title") or "", limit=220),
                    "status": str(item.get("status") or "").strip(),
                    "notes": compact_text(item.get("notes") or "", limit=220),
                    "source": "todo_contract",
                }
            )
        )
    return items


def _todo_cursor(todo_plan: dict[str, Any], *, baseline_ref: str, item_refs: dict[str, str]) -> dict[str, Any]:
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
        todo_item_ref = item_refs.get(todo_id) or _todo_item_ref(baseline_ref=baseline_ref, todo_id=todo_id)
        item_statuses.append(
            drop_empty(
                {
                    "todo_item_ref": todo_item_ref,
                    "todo_id": todo_id,
                    "status": status,
                    "active": True if todo_id == active_item_id else None,
                    "notes": compact_text(item.get("notes") or "", limit=220),
                }
            )
        )
    return drop_empty(
        {
            "todo_baseline_ref": baseline_ref,
            "active_item_id": active_item_id,
            "active_item_ref": (item_refs.get(active_item_id) or _todo_item_ref(baseline_ref=baseline_ref, todo_id=active_item_id)) if active_item_id else "",
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
            "completed_item_refs": [
                str(item.get("todo_item_ref") or "")
                for item in item_statuses
                if str(item.get("status") or "") == "completed" and str(item.get("todo_item_ref") or "")
            ],
            "blocked_item_refs": [
                str(item.get("todo_item_ref") or "")
                for item in item_statuses
                if str(item.get("status") or "") == "blocked" and str(item.get("todo_item_ref") or "")
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


def _mode_ref(*, task_run_id: str, mode_kind: str, mode_id: Any, digest: str) -> str:
    scope = str(task_run_id or "session").replace(":", "_")
    mode = str(mode_kind or "mode").replace(":", "_")
    identity = str(mode_id or "current").replace(":", "_")
    short_digest = str(digest or "").removeprefix("sha256:")[:16]
    return f"taskmode:{scope}:{mode}:{identity}:{short_digest}"


def _step_ref(*, baseline_ref: str, step_id: Any) -> str:
    return f"{baseline_ref}:step:{str(step_id or '').strip()}"


def _todo_item_ref(*, baseline_ref: str, todo_id: Any) -> str:
    return f"{baseline_ref}:todo:{str(todo_id or '').strip()}"


def _tool_name(value: Any) -> str:
    text = str(value or "").strip()
    return text.split(":", 1)[1] if text.startswith("tool:") else text
