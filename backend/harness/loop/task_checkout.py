from __future__ import annotations

import time
import uuid
from dataclasses import replace
from typing import Any

from runtime.shared.models import AgentRun, TaskRun

from .task_lifecycle import TaskLifecycleRecord
from .work_rollout import clone_work_rollout_for_checkout, ensure_work_rollout, work_rollout_summary


def checkout_task_run_for_resume(
    runtime_host: Any,
    source_task_run_id: str,
    *,
    user_instruction: str = "",
    turn_id: str = "",
    reason: str = "conversation_continue",
) -> dict[str, Any]:
    source = runtime_host.state_index.get_task_run(source_task_run_id)
    if source is None:
        return {"ok": False, "error": "task_run_not_found", "task_run_id": source_task_run_id}
    if str(getattr(source, "execution_runtime_kind", "") or "") != "single_agent_task":
        return {"ok": False, "error": "not_single_agent_task_run", "task_run_id": source_task_run_id}
    diagnostics = dict(getattr(source, "diagnostics", {}) or {})
    if str(diagnostics.get("origin_kind") or dict(diagnostics.get("origin") or {}).get("origin_kind") or "") == "graph_node_assigned":
        return {"ok": False, "error": "graph_node_task_run_controlled_by_graph_runtime", "task_run_id": source_task_run_id}
    contract = _load_contract(runtime_host, source)
    if not contract:
        return {"ok": False, "error": "task_contract_missing", "task_run_id": source_task_run_id}
    ensure_work_rollout(runtime_host, source, status=str(getattr(source, "status", "") or "aborted"))
    source_rollout = work_rollout_summary(runtime_host, source)
    now = time.time()
    lineage = _lineage_for_checkout(source, rollout_summary=source_rollout, reason=reason, turn_id=turn_id)
    child_task_run_id = f"{source.task_run_id}:checkout:{uuid.uuid4().hex[:8]}"
    child_contract, child_contract_ref = _put_checkout_contract(
        runtime_host,
        source=source,
        contract=contract,
        child_task_run_id=child_task_run_id,
        user_instruction=user_instruction,
        reason=reason,
    )
    child = TaskRun(
        task_run_id=child_task_run_id,
        session_id=source.session_id,
        task_id=f"{source.task_id}:checkout" if str(source.task_id or "") else f"task:{child_task_run_id}",
        task_contract_ref=child_contract_ref,
        owner_agent_seat_id=source.owner_agent_seat_id,
        agent_id=source.agent_id,
        agent_profile_id=source.agent_profile_id,
        execution_runtime_kind="single_agent_task",
        status="waiting_executor",
        created_at=now,
        updated_at=now,
        terminal_reason="waiting_executor",
        diagnostics={
            **_checkout_diagnostics(source),
            "contract": child_contract,
            "runtime_task_selection": dict(diagnostics.get("runtime_task_selection") or diagnostics.get("task_selection") or {}),
            "logical_work_id": lineage["logical_work_id"],
            "root_task_run_id": lineage["root_task_run_id"],
            "parent_task_run_id": source.task_run_id,
            "lineage": lineage,
            "origin_kind": "checkout_resume",
            "origin": {"origin_kind": "checkout_resume", "parent_task_run_id": source.task_run_id},
            "latest_step": "task_run_checkout_created",
            "latest_step_status": "waiting_executor",
            "latest_step_summary": "已从上次中断处建立新的继续处理尝试。",
            "recovery_action": "checkout_resume",
        },
    )
    agent_run = AgentRun(
        agent_run_id=f"agrun:{child_task_run_id}:main",
        task_run_id=child_task_run_id,
        agent_id=source.agent_id or "agent:0",
        agent_profile_id=source.agent_profile_id,
        status="pending",
        execution_runtime_kind="single_agent_task",
        parent_agent_run_ref=_latest_agent_run_ref(runtime_host, source.task_run_id),
        created_at=now,
        updated_at=now,
        diagnostics={"turn_id": turn_id, "contract_ref": child_contract_ref, "lineage": lineage},
    )
    lifecycle = TaskLifecycleRecord(
        task_run_id=child_task_run_id,
        contract_ref=child_contract_ref,
        status="waiting_executor",
        created_at=now,
        updated_at=now,
    )
    runtime_host.state_index.upsert_task_run(child)
    runtime_host.state_index.upsert_agent_run(agent_run)
    lifecycle_ref = runtime_host.runtime_objects.put_object("task_lifecycle", child_task_run_id, lifecycle.to_dict())
    rollout = clone_work_rollout_for_checkout(
        runtime_host,
        source_task_run=source,
        child_task_run=child,
        fork_reason=reason,
        user_instruction=user_instruction,
        turn_id=turn_id,
    )
    event = runtime_host.event_log.append(
        child_task_run_id,
        "task_run_checkout_created",
        payload={
            "task_run": child.to_dict(),
            "agent_run": agent_run.to_dict(),
            "contract": child_contract,
            "lifecycle": lifecycle.to_dict(),
            "lineage": lineage,
            "work_rollout": rollout.to_dict(),
        },
        refs={
            "task_run_ref": child_task_run_id,
            "parent_task_run_ref": source.task_run_id,
            "task_contract_ref": child_contract_ref,
            "task_lifecycle_ref": lifecycle_ref,
        },
    )
    return {
        "ok": True,
        "accepted": True,
        "task_run": child.to_dict(),
        "source_task_run": source.to_dict(),
        "agent_run": agent_run.to_dict(),
        "lifecycle": lifecycle.to_dict(),
        "event": event.to_dict(),
        "work_rollout": rollout.to_dict(),
    }


def _load_contract(runtime_host: Any, task_run: Any) -> dict[str, Any]:
    try:
        payload = runtime_host.runtime_objects.get_object(task_run.task_contract_ref)
    except Exception:
        payload = {}
    if payload:
        return dict(payload)
    return dict(dict(getattr(task_run, "diagnostics", {}) or {}).get("contract") or {})


def _put_checkout_contract(
    runtime_host: Any,
    *,
    source: Any,
    contract: dict[str, Any],
    child_task_run_id: str,
    user_instruction: str,
    reason: str,
) -> tuple[dict[str, Any], str]:
    rollout_summary = work_rollout_summary(runtime_host, source)
    source_contract_id = str(contract.get("contract_id") or source.task_contract_ref or source.task_run_id)
    contract_id = f"{source_contract_id}:checkout:{uuid.uuid4().hex[:8]}"
    child = {
        **dict(contract),
        "contract_id": contract_id,
        "contract_source": "checkout_resume",
        "source_contract_ref": str(getattr(source, "task_contract_ref", "") or contract.get("source_contract_ref") or ""),
        "recovery_policy": {
            **dict(contract.get("recovery_policy") or {}),
            "resume_mode": "checkout_fork",
            "source_task_run_id": source.task_run_id,
            "reason": reason,
        },
        "prompt_contract": {
            **dict(contract.get("prompt_contract") or {}),
            "resume_context": {
                "summary": rollout_summary,
                "user_instruction": str(user_instruction or ""),
                "guidance": (
                    "你正在继续一项被用户中断过的工作。上次工作可能已经部分修改了文件或执行了工具。"
                    "继续前先检查当前工作区和已有结果，再决定下一步。不要假设中断前的最后动作一定完整成功。"
                ),
                "authority": "runtime.checkout_resume_context",
            },
        },
        "origin": {
            "origin_kind": "checkout_resume",
            "parent_task_run_id": source.task_run_id,
            "child_task_run_id": child_task_run_id,
        },
    }
    ref = runtime_host.runtime_objects.put_object("task_run_contract", contract_id, child)
    return child, ref


def _checkout_diagnostics(source: Any) -> dict[str, Any]:
    source_diagnostics = dict(getattr(source, "diagnostics", {}) or {})
    blocked = {
        "runtime_control",
        "executor_status",
        "latest_step",
        "latest_step_status",
        "latest_step_summary",
        "terminal_reason",
        "recoverable_error",
        "recovery_action",
        "final_answer",
        "final_action_diagnostics",
    }
    return {key: value for key, value in source_diagnostics.items() if key not in blocked}


def _lineage_for_checkout(source: Any, *, rollout_summary: dict[str, Any], reason: str, turn_id: str) -> dict[str, Any]:
    diagnostics = dict(getattr(source, "diagnostics", {}) or {})
    root_task_run_id = str(diagnostics.get("root_task_run_id") or source.task_run_id)
    logical_work_id = str(diagnostics.get("logical_work_id") or root_task_run_id)
    breakpoint = dict(rollout_summary.get("breakpoint") or {})
    rollout_event_offset = _int_value(rollout_summary.get("latest_event_offset"), -1)
    breakpoint_event_offset = _int_value(breakpoint.get("event_offset"), -1)
    source_event_offset = _int_value(getattr(source, "latest_event_offset", -1), -1)
    forked_from_event_offset = max(rollout_event_offset, breakpoint_event_offset)
    if forked_from_event_offset < 0:
        forked_from_event_offset = source_event_offset
    forked_from_checkpoint_ref = str(
        rollout_summary.get("latest_checkpoint_ref")
        or breakpoint.get("checkpoint_ref")
        or getattr(source, "latest_checkpoint_ref", "")
        or ""
    )
    return {
        "parent_task_run_id": source.task_run_id,
        "root_task_run_id": root_task_run_id,
        "logical_work_id": logical_work_id,
        "fork_reason": reason,
        "forked_from_event_offset": forked_from_event_offset,
        "forked_from_checkpoint_ref": forked_from_checkpoint_ref,
        "source_rollout_ref": str(rollout_summary.get("rollout_id") or ""),
        "turn_id": str(turn_id or ""),
        "authority": "runtime.task_checkout",
    }


def _int_value(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _latest_agent_run_ref(runtime_host: Any, task_run_id: str) -> str:
    try:
        runs = runtime_host.state_index.list_task_agent_runs(task_run_id)
    except Exception:
        runs = []
    if not runs:
        return ""
    return str(getattr(runs[-1], "agent_run_id", "") or "")
