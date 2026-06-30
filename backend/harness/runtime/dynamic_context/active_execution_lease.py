from __future__ import annotations

from typing import Any

from .models import compact_text, dict_tuple, drop_empty, stable_json_hash


ACTIVE_EXECUTION_LEASE_AUTHORITY = "harness.runtime.dynamic_context.active_execution_lease"

_RELEASED_LEASE_STATES = {"released", "completed", "canceled", "cancelled", "superseded", "terminated", "failed"}
_TERMINAL_TASK_STATUSES = {"completed", "succeeded", "failed", "aborted", "cancelled", "canceled", "superseded", "released"}
_SUSPENDED_TASK_STATUSES = {"blocked", "paused", "waiting_approval", "waiting_user", "interrupted"}


def build_active_execution_lease_context(
    *,
    task_run: dict[str, Any] | None = None,
    task_run_contract: dict[str, Any] | None = None,
    turn_state_attention_contexts: dict[str, Any] | None = None,
    task_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    run = dict(task_run or {})
    if not run:
        return {}
    diagnostics = dict(run.get("diagnostics") or {}) if isinstance(run.get("diagnostics"), dict) else {}
    status = _task_status(run, diagnostics=diagnostics)
    lease_seed = dict(diagnostics.get("active_execution_lease") or {}) if isinstance(diagnostics.get("active_execution_lease"), dict) else {}
    seed_state = str(lease_seed.get("lease_state") or lease_seed.get("status") or "").strip().lower()
    if seed_state in _RELEASED_LEASE_STATES or _task_status_is_released(status, diagnostics=diagnostics):
        return {}

    contract = _task_run_contract_root(task_run_contract or {})
    turn_contexts = dict(turn_state_attention_contexts or {})
    plan_source = _plan_source_snapshot(diagnostics, contract=contract, turn_contexts=turn_contexts)
    execution_contract = _execution_contract(
        diagnostics,
        contract=contract,
        plan_source=plan_source,
        turn_contexts=turn_contexts,
    )
    lease_state = _lease_state(status, diagnostics=diagnostics)
    if lease_state not in {"active", "recoverable", "suspended"}:
        return {}
    task_run_id = str(run.get("task_run_id") or diagnostics.get("task_run_id") or "").strip()
    task_id = str(run.get("task_id") or diagnostics.get("task_id") or "").strip()
    work_item = _work_item(run, diagnostics=diagnostics, contract=contract, task_run_id=task_run_id, task_id=task_id)
    todo_cursor = _todo_cursor(turn_contexts, task_state=task_state)
    lease = drop_empty(
        {
            "kind": "active_execution_lease",
            "lease_id": str(lease_seed.get("lease_id") or _lease_id(task_run_id=task_run_id, plan_source=plan_source, execution_contract=execution_contract)),
            "lease_state": lease_state,
            "task_status": status,
            "work_item": work_item,
            "plan_source_snapshot": plan_source,
            "execution_contract": execution_contract,
            "todo_cursor": todo_cursor,
            "recovery_checkpoint": _recovery_checkpoint(diagnostics),
            "lifecycle": {
                "scope": "current_task_execution",
                "inject_only_when": ["active", "recoverable", "suspended"],
                "release_on": ["completed", "canceled", "superseded", "terminated", "released"],
                "closed_lease_history_policy": "do_not_inject_current_boundary",
            },
            "authority_order": {
                "higher_than": ["task_plan_context", "task_todo_context", "runtime_memory_context"],
                "lower_than": ["current_user_instruction", "task_run_contract_stable", "action_authorization"],
            },
            "agent_use_contract": (
                "Treat this as the current execution lease. Continue executing only while lease_state is active, "
                "recoverable, or suspended; do not infer active execution from old plan text when this lease is absent."
            ),
            "projection": "plan_source_execution_contract_active_lease_refs_only",
            "authority": ACTIVE_EXECUTION_LEASE_AUTHORITY,
        }
    )
    return {"active_execution_lease": lease} if lease else {}


def _plan_source_snapshot(
    diagnostics: dict[str, Any],
    *,
    contract: dict[str, Any],
    turn_contexts: dict[str, Any],
) -> dict[str, Any]:
    explicit = dict(diagnostics.get("plan_source_snapshot") or {}) if isinstance(diagnostics.get("plan_source_snapshot"), dict) else {}
    if explicit:
        return explicit
    plan_context = dict(turn_contexts.get("task_plan_context") or {})
    baseline = dict(plan_context.get("task_plan_baseline") or {})
    plan_contract = _plan_contract(contract)
    source_seed = drop_empty(
        {
            "plan_baseline_ref": baseline.get("plan_baseline_ref"),
            "plan_id": baseline.get("plan_id") or plan_contract.get("plan_id"),
            "plan_sha256": baseline.get("plan_sha256"),
            "strategy_summary": baseline.get("strategy_summary") or plan_contract.get("strategy_summary"),
            "external_plan_ref": plan_contract.get("external_plan_ref") or plan_contract.get("plan_id"),
        }
    )
    if not source_seed:
        return {}
    source_hash = stable_json_hash(source_seed)
    return drop_empty(
        {
            "snapshot_id": "plansrc:" + source_hash.removeprefix("sha256:")[:16],
            "source_kind": "task_plan_context" if baseline else "task_plan_contract",
            "source_ref": str(baseline.get("plan_baseline_ref") or plan_contract.get("external_plan_ref") or plan_contract.get("plan_id") or ""),
            "content_hash": source_hash,
            "summary": compact_text(source_seed.get("strategy_summary") or "", limit=360),
            "immutability": "snapshot_ref_hash_only",
            "authority": "harness.runtime.dynamic_context.active_execution_lease.plan_source_snapshot",
        }
    )


def _execution_contract(
    diagnostics: dict[str, Any],
    *,
    contract: dict[str, Any],
    plan_source: dict[str, Any],
    turn_contexts: dict[str, Any],
) -> dict[str, Any]:
    explicit = dict(diagnostics.get("active_execution_contract") or {}) if isinstance(diagnostics.get("active_execution_contract"), dict) else {}
    if explicit:
        return explicit
    plan_context = dict(turn_contexts.get("task_plan_context") or {})
    todo_context = dict(turn_contexts.get("task_todo_context") or {})
    plan_baseline = dict(plan_context.get("task_plan_baseline") or {})
    todo_baseline = dict(todo_context.get("task_todo_baseline") or {})
    lifecycle = _lifecycle_contract(contract)
    acceptance = _acceptance_contract(contract)
    seed = drop_empty(
        {
            "plan_source_snapshot_id": plan_source.get("snapshot_id"),
            "plan_baseline_ref": plan_baseline.get("plan_baseline_ref"),
            "todo_baseline_ref": todo_baseline.get("todo_baseline_ref"),
            "allowed_states": lifecycle.get("allowed_states"),
            "completion_criteria": acceptance.get("completion_criteria"),
            "final_answer_requirements": acceptance.get("final_answer_requirements"),
        }
    )
    if not seed:
        return {}
    contract_hash = stable_json_hash(seed)
    return drop_empty(
        {
            "execution_contract_id": "exec:" + contract_hash.removeprefix("sha256:")[:16],
            "plan_source_snapshot_id": plan_source.get("snapshot_id"),
            "plan_baseline_ref": plan_baseline.get("plan_baseline_ref"),
            "todo_baseline_ref": todo_baseline.get("todo_baseline_ref"),
            "completion_criteria": _string_list(acceptance.get("completion_criteria"), limit=8, chars=240),
            "final_answer_requirements": _string_list(acceptance.get("final_answer_requirements"), limit=8, chars=240),
            "allowed_lifecycle_states": _string_list(lifecycle.get("allowed_states"), limit=12, chars=80),
            "release_policy": "release_or_hide_on_completed_canceled_superseded_terminated",
            "authority": "harness.runtime.dynamic_context.active_execution_lease.execution_contract",
        }
    )


def _work_item(
    run: dict[str, Any],
    *,
    diagnostics: dict[str, Any],
    contract: dict[str, Any],
    task_run_id: str,
    task_id: str,
) -> dict[str, Any]:
    goal = _goal_contract(contract)
    return drop_empty(
        {
            "work_item_id": f"work:{task_run_id}" if task_run_id else "",
            "task_run_id": task_run_id,
            "task_id": task_id,
            "session_id": str(run.get("session_id") or diagnostics.get("session_id") or ""),
            "origin_ref": str(dict(diagnostics.get("origin") or {}).get("origin_ref") or diagnostics.get("origin_ref") or ""),
            "user_visible_goal": compact_text(
                goal.get("user_visible_goal")
                or contract.get("user_visible_goal")
                or diagnostics.get("user_visible_goal")
                or "",
                limit=500,
            ),
        }
    )


def _todo_cursor(turn_contexts: dict[str, Any], *, task_state: dict[str, Any] | None) -> dict[str, Any]:
    todo_context = dict(turn_contexts.get("task_todo_context") or {})
    cursor = dict(todo_context.get("todo_cursor") or {})
    baseline = dict(todo_context.get("task_todo_baseline") or {})
    state_cursor = dict(dict(task_state or {}).get("todo_cursor") or {})
    active_item_ref = str(cursor.get("active_item_ref") or state_cursor.get("active_item_ref") or "").strip()
    return drop_empty(
        {
            "todo_baseline_ref": str(baseline.get("todo_baseline_ref") or ""),
            "active_item_id": str(cursor.get("active_item_id") or state_cursor.get("active_item_id") or ""),
            "active_item_ref": active_item_ref,
            "cursor_hash": stable_json_hash(cursor) if cursor else "",
            "status_counts": dict(cursor.get("status_counts") or {}),
        }
    )


def _recovery_checkpoint(diagnostics: dict[str, Any]) -> dict[str, Any]:
    recoverable = dict(diagnostics.get("recoverable_error") or {}) if isinstance(diagnostics.get("recoverable_error"), dict) else {}
    recovery_packet = dict(diagnostics.get("recovery_packet") or {}) if isinstance(diagnostics.get("recovery_packet"), dict) else {}
    return drop_empty(
        {
            "recoverable_error_code": str(recoverable.get("error_code") or recoverable.get("code") or ""),
            "retryable": recoverable.get("retryable") if isinstance(recoverable.get("retryable"), bool) else None,
            "recovery_action": str(diagnostics.get("recovery_action") or recoverable.get("recovery_action") or ""),
            "recovery_packet_ref": str(recovery_packet.get("packet_id") or recovery_packet.get("recovery_packet_id") or ""),
        }
    )


def _task_status(run: dict[str, Any], *, diagnostics: dict[str, Any]) -> str:
    return str(run.get("status") or diagnostics.get("status") or diagnostics.get("runtime_status") or "").strip().lower()


def _task_status_is_released(status: str, *, diagnostics: dict[str, Any]) -> bool:
    normalized = str(status or "").strip().lower()
    if normalized in _TERMINAL_TASK_STATUSES:
        recoverable = dict(diagnostics.get("recoverable_error") or {}) if isinstance(diagnostics.get("recoverable_error"), dict) else {}
        return not recoverable or recoverable.get("retryable") is False
    return False


def _lease_state(status: str, *, diagnostics: dict[str, Any]) -> str:
    recoverable = dict(diagnostics.get("recoverable_error") or {}) if isinstance(diagnostics.get("recoverable_error"), dict) else {}
    if recoverable and recoverable.get("retryable") is not False:
        return "recoverable"
    normalized = str(status or "").strip().lower()
    if normalized in _SUSPENDED_TASK_STATUSES:
        return "suspended"
    if normalized in _TERMINAL_TASK_STATUSES:
        return "released"
    return "active"


def _lease_id(*, task_run_id: str, plan_source: dict[str, Any], execution_contract: dict[str, Any]) -> str:
    seed = {
        "task_run_id": task_run_id,
        "plan_source_snapshot_id": plan_source.get("snapshot_id"),
        "execution_contract_id": execution_contract.get("execution_contract_id"),
    }
    return "lease:" + stable_json_hash(seed).removeprefix("sha256:")[:18]


def _plan_contract(contract: dict[str, Any]) -> dict[str, Any]:
    root = _task_run_contract_root(contract)
    work_mode_contract = _work_mode_contract(root, "plan")
    if work_mode_contract:
        return work_mode_contract
    if isinstance(contract.get("plan_contract"), dict):
        return dict(contract.get("plan_contract") or {})
    if isinstance(root.get("plan_contract"), dict):
        return dict(root.get("plan_contract") or {})
    return {}


def _goal_contract(contract: dict[str, Any]) -> dict[str, Any]:
    root = _task_run_contract_root(contract)
    work_mode_contract = _work_mode_contract(root, "goal")
    if work_mode_contract:
        return work_mode_contract
    if isinstance(root.get("goal_contract"), dict):
        return dict(root.get("goal_contract") or {})
    return {}


def _lifecycle_contract(contract: dict[str, Any]) -> dict[str, Any]:
    root = _task_run_contract_root(contract)
    return dict(root.get("lifecycle_contract") or {}) if isinstance(root.get("lifecycle_contract"), dict) else {}


def _acceptance_contract(contract: dict[str, Any]) -> dict[str, Any]:
    root = _task_run_contract_root(contract)
    return dict(root.get("acceptance_contract") or {}) if isinstance(root.get("acceptance_contract"), dict) else {}


def _task_run_contract_root(value: Any) -> dict[str, Any]:
    contract = dict(value or {}) if isinstance(value, dict) else {}
    if isinstance(contract.get("task_run_contract"), dict):
        return dict(contract.get("task_run_contract") or {})
    return contract


def _work_mode_contract(contract: dict[str, Any], mode_kind: str) -> dict[str, Any]:
    mode = _work_mode(contract, mode_kind)
    raw = dict(mode.get("contract") or {}) if isinstance(mode.get("contract"), dict) else {}
    if not raw:
        return {}
    return {
        **raw,
        "mode_instance_id": str(mode.get("mode_instance_id") or "").strip(),
        "mode_role": str(mode.get("mode_role") or "").strip(),
    }


def _work_mode(contract: dict[str, Any], mode_kind: str) -> dict[str, Any]:
    work_modes = [dict(item) for item in list(dict(contract or {}).get("work_modes") or []) if isinstance(item, dict)]
    if not work_modes:
        return {}
    container_contract = dict(contract.get("container_contract") or {}) if isinstance(contract.get("container_contract"), dict) else {}
    primary_ref = str(container_contract.get("primary_work_mode_ref") or "").strip()
    candidate: dict[str, Any] = {}
    for item in work_modes:
        if str(item.get("mode_kind") or "").strip() != mode_kind:
            continue
        if primary_ref and str(item.get("mode_instance_id") or "").strip() == primary_ref:
            return dict(item)
        if str(item.get("mode_role") or "").strip() == "primary":
            return dict(item)
        if not candidate:
            candidate = dict(item)
    return candidate


def _string_list(value: Any, *, limit: int, chars: int) -> list[str]:
    values = value if isinstance(value, (list, tuple)) else ([value] if value else [])
    result: list[str] = []
    seen: set[str] = set()
    for raw in list(values)[: max(1, int(limit or 8))]:
        text = compact_text(raw, limit=max(10, int(chars or 120)))
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result
