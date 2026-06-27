from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any

from .models import GraphBreakpointPacket
from .registry import HealthRegistry

logger = logging.getLogger(__name__)

_ACTIVE_WORK_ORDER_MISSING_EXECUTOR_MIN_AGE_SECONDS = 30.0


class GraphBreakpointSupervisor:
    def __init__(
        self,
        *,
        base_dir: Path,
        runtime: Any,
        poll_interval_seconds: float = 20.0,
        task_scan_limit: int = 200,
    ) -> None:
        self.base_dir = Path(base_dir)
        self.runtime = runtime
        self.poll_interval_seconds = max(5.0, float(poll_interval_seconds or 20.0))
        self.task_scan_limit = max(20, int(task_scan_limit or 200))

    async def run_forever(self) -> None:
        await asyncio.sleep(0.1)
        while True:
            try:
                await asyncio.to_thread(self.run_once)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("graph breakpoint supervision tick failed")
            await asyncio.sleep(self.poll_interval_seconds)

    def run_once(self) -> dict[str, Any]:
        packets = self._collect_breakpoint_packets()
        registry = HealthRegistry(self.base_dir)
        issues = [registry.upsert_graph_breakpoint_issue(packet) for packet in packets]
        commands = [
            registry.upsert_graph_breakpoint_command(issue=issue, packet=packet)
            for issue, packet in zip(issues, packets, strict=False)
        ]
        return {
            "authority": "health_system.graph_breakpoint_supervisor",
            "packet_count": len(packets),
            "issue_count": len(issues),
            "issue_ids": [item.issue_id for item in issues],
            "command_count": len(commands),
            "command_ids": [item.command_id for item in commands],
        }

    def _collect_breakpoint_packets(self) -> list[GraphBreakpointPacket]:
        harness_runtime = getattr(self.runtime, "harness_runtime", None)
        graph_system = getattr(harness_runtime, "graph_system", None)
        host = getattr(harness_runtime, "single_agent_runtime_host", None)
        state_index = getattr(host, "state_index", None)
        if graph_system is None or state_index is None:
            return []
        tasks = list(state_index.list_recent_task_runs(limit=self.task_scan_limit))
        packets: list[GraphBreakpointPacket] = []
        seen: set[tuple[str, str, str, str]] = set()
        for task_run in tasks:
            packet = _breakpoint_packet_from_task_run(task_run=task_run, graph_system=graph_system)
            if packet is not None:
                key = _packet_recovery_identity(packet)
                if key in seen:
                    continue
                seen.add(key)
                packets.append(packet)
        return packets


def _breakpoint_packet_from_task_run(*, task_run: Any, graph_system: Any) -> GraphBreakpointPacket | None:
    now = time.time()
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
    graph_run_id = str(diagnostics.get("graph_run_id") or "").strip()
    if not graph_run_id:
        return None
    task_status = str(getattr(task_run, "status", "") or "").strip()
    task_terminal_reason = str(getattr(task_run, "terminal_reason", "") or "").strip()
    task_status_is_breakpoint = task_status in {"blocked", "failed", "waiting_executor"} or task_terminal_reason in {
        "model_action_protocol_repair_required",
        "task_execution_step_budget_exhausted",
        "background_executor_missing_after_restart",
    }
    health_monitor = getattr(graph_system, "get_graph_run_health_monitor", None)
    if not callable(health_monitor):
        return None
    monitor = health_monitor(graph_run_id)
    if not monitor:
        return None
    graph_run = dict(monitor.get("graph_run") or {})
    graph_loop_state = dict(monitor.get("graph_loop_state") or {})
    graph_status = str(graph_run.get("status") or graph_loop_state.get("status") or "").strip()
    graph_terminal_reason = str(graph_run.get("terminal_reason") or graph_loop_state.get("terminal_reason") or "").strip()
    graph_status_is_breakpoint = graph_status in {"blocked", "failed", "waiting_human_gate", "waiting_executor", "budget_exhausted"} or graph_terminal_reason in {
        "model_action_protocol_repair_required",
        "task_execution_step_budget_exhausted",
        "background_executor_missing_after_restart",
        "max_node_executions_exhausted",
        "max_runtime_seconds_exhausted",
        "max_dispatches_exhausted",
    }
    recovery_signal = _running_graph_recovery_signal(monitor, now=now)
    if not task_status_is_breakpoint and not recovery_signal:
        return None
    if not graph_status_is_breakpoint and not recovery_signal:
        return None
    node_id, work_order_id, blocked_reason, response_diagnostics = _select_breakpoint_node(monitor)
    if recovery_signal:
        response_diagnostics = {
            **response_diagnostics,
            "graph_recovery_signal": recovery_signal,
        }
    recoverable_error = (
        {
            "error_code": str(recovery_signal.get("error_code") or ""),
            "retryable": True,
            "user_message": str(recovery_signal.get("user_message") or ""),
        }
        if recovery_signal
        else dict(diagnostics.get("recoverable_error") or {})
    )
    if not recovery_signal and not recoverable_error:
        recoverable_error = dict(response_diagnostics.get("recoverable_error") or {})
    parse_diagnostics = _parse_diagnostics_from_payloads(diagnostics, response_diagnostics)
    packet_task_status = graph_status if recovery_signal else task_status
    packet_task_run_id = (
        str(graph_run.get("task_run_id") or "").strip()
        if recovery_signal
        else str(getattr(task_run, "task_run_id", "") or "").strip()
    )
    packet_session_id = (
        str(graph_run.get("session_id") or "").strip()
        if recovery_signal
        else str(getattr(task_run, "session_id", "") or "").strip()
    )
    packet = GraphBreakpointPacket(
        graph_run_id=graph_run_id,
        graph_id=str(graph_run.get("graph_id") or diagnostics.get("graph_id") or "").strip(),
        graph_config_id=str(graph_run.get("config_id") or diagnostics.get("graph_config_id") or "").strip(),
        task_run_id=packet_task_run_id,
        session_id=packet_session_id,
        node_id=node_id,
        work_order_id=work_order_id,
        graph_status=graph_status,
        task_status=packet_task_status,
        terminal_reason=str(recovery_signal.get("terminal_reason") or "") or graph_terminal_reason or task_terminal_reason,
        blocked_reason=blocked_reason or str(recovery_signal.get("blocked_reason") or ""),
        recoverable_error=recoverable_error,
        parse_diagnostics=parse_diagnostics,
        response_diagnostics=response_diagnostics,
        task_run_monitor=dict(monitor.get("task_run_monitor") or {}),
        graph_loop_state={
            "status": graph_loop_state.get("status"),
            "terminal_reason": graph_loop_state.get("terminal_reason"),
            "blocked_node_ids": list(graph_loop_state.get("blocked_node_ids") or []),
            "failed_node_ids": list(graph_loop_state.get("failed_node_ids") or []),
            "running_node_ids": list(graph_loop_state.get("running_node_ids") or []),
        },
        active_node_runtime_views=tuple(dict(item) for item in list(monitor.get("active_node_runtime_views") or [])[:6]),
        refs={
            "task_run_ref": packet_task_run_id,
            "graph_run_ref": f"graph_run:{graph_run_id}",
            "session_ref": packet_session_id,
        },
        detected_at=now,
    )
    fingerprint = _packet_fingerprint(packet)
    return GraphBreakpointPacket(
        **{
            **packet.to_dict(),
            "active_node_runtime_views": tuple(packet.active_node_runtime_views),
            "fingerprint": fingerprint,
        }
    )


def _running_graph_recovery_signal(monitor: dict[str, Any], *, now: float) -> dict[str, Any]:
    graph_run = dict(monitor.get("graph_run") or {})
    graph_loop_state = dict(monitor.get("graph_loop_state") or {})
    graph_status = str(graph_run.get("status") or graph_loop_state.get("status") or "").strip()
    loop_status = str(graph_loop_state.get("status") or "").strip()
    graph_terminal_reason = str(graph_run.get("terminal_reason") or graph_loop_state.get("terminal_reason") or "").strip()
    budget_stopped_with_live_loop = (
        graph_status == "budget_exhausted"
        and loop_status in {"running", "waiting_executor"}
        and graph_terminal_reason in {
            "",
            "max_node_executions_exhausted",
            "max_runtime_seconds_exhausted",
            "max_dispatches_exhausted",
        }
    )
    if graph_status not in {"running", "waiting_executor"} and not budget_stopped_with_live_loop:
        return {}
    active_views = [dict(item) for item in list(monitor.get("active_node_runtime_views") or []) if isinstance(item, dict)]
    if not active_views and int(monitor.get("active_node_work_order_count") or 0) <= 0:
        return {}
    for view in active_views:
        node_id = str(view.get("node_id") or "").strip()
        work_order_id = str(view.get("work_order_id") or dict(view.get("work_order_summary") or {}).get("work_order_id") or "").strip()
        if not node_id or not work_order_id:
            continue
        executor_presence = str(view.get("executor_presence") or "").strip()
        task_monitor = dict(view.get("node_executor_task_run_monitor") or {})
        if not executor_presence:
            if bool(task_monitor.get("stale")) or str(task_monitor.get("lifecycle") or "") == "stale":
                executor_presence = "stale"
            elif view.get("node_executor_task_run") or str(view.get("node_executor_task_run_id") or "").strip():
                executor_presence = "present"
            else:
                executor_presence = "unknown"
        if executor_presence == "present":
            continue
        if executor_presence == "unknown":
            continue
        if executor_presence == "stale":
            return {
                "reason": "active_node_executor_stale",
                "terminal_reason": "task_executor_interrupted_by_runtime_restart",
                "blocked_reason": "active_node_executor_stale",
                "error_code": "task_executor_interrupted_by_runtime_restart",
                "node_id": node_id,
                "work_order_id": work_order_id,
                "user_message": "图节点执行器已经停滞，健康管家可以恢复并继续推进图任务。",
            }
        if executor_presence != "missing":
            continue
        if not _active_work_order_missing_executor_is_old_enough(
            graph_loop_state=graph_loop_state,
            node_id=node_id,
            now=now,
        ):
            continue
        return {
            "reason": "active_work_order_without_executor",
            "terminal_reason": "active_work_order_executor_missing_after_restart",
            "blocked_reason": "active_work_order_without_executor",
            "error_code": "active_work_order_executor_missing_after_restart",
            "node_id": node_id,
            "work_order_id": work_order_id,
            "user_message": "图运行状态仍有活跃工作单，但没有对应的节点执行器，健康管家可以恢复并继续推进图任务。",
        }
    return {}


def _active_work_order_missing_executor_is_old_enough(
    *,
    graph_loop_state: dict[str, Any],
    node_id: str,
    now: float,
) -> bool:
    node_state = dict(dict(graph_loop_state.get("node_states") or {}).get(node_id) or {})
    updated_at = _safe_float(node_state.get("updated_at"))
    if updated_at <= 0:
        return True
    return now - updated_at >= _ACTIVE_WORK_ORDER_MISSING_EXECUTOR_MIN_AGE_SECONDS


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _select_breakpoint_node(monitor: dict[str, Any]) -> tuple[str, str, str, dict[str, Any]]:
    graph_loop_state = dict(monitor.get("graph_loop_state") or {})
    active_views = [dict(item) for item in list(monitor.get("active_node_runtime_views") or []) if isinstance(item, dict)]
    preferred = [*active_views]
    blocked_ids = [str(item) for item in list(graph_loop_state.get("blocked_node_ids") or []) if str(item)]
    if blocked_ids:
        for node_id in blocked_ids:
            preferred.append({"node_id": node_id})
    for view in preferred:
        node_id = str(view.get("node_id") or "").strip()
        if not node_id:
            continue
        task_run = dict(view.get("node_executor_task_run") or {})
        task_monitor = dict(view.get("node_executor_task_run_monitor") or {})
        work_order = dict(view.get("work_order_summary") or {})
        diagnostics = dict(task_run.get("runtime_scope") or {})
        step = dict(task_monitor.get("step") or {})
        executor_presence = str(view.get("executor_presence") or "")
        blocked_reason = str(
            view.get("terminal_reason")
            or task_run.get("terminal_reason")
            or step.get("terminal_reason")
            or ""
        ).strip()
        response_diagnostics = {
            **({"executor_presence": executor_presence} if executor_presence else {}),
            **({"node_executor_task_run": task_run} if task_run else {}),
            **({"node_executor_task_run_monitor": task_monitor} if task_monitor else {}),
            **({"runtime_scope": diagnostics} if diagnostics else {}),
        }
        return node_id, str(work_order.get("work_order_id") or view.get("work_order_id") or "").strip(), blocked_reason, response_diagnostics
    return "", "", "", {}


def _parse_diagnostics_from_payloads(*payloads: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for payload in payloads:
        parse_error = dict(payload.get("parse_error") or payload.get("parse_diagnostics") or {})
        if parse_error:
            result.update(parse_error)
        for key in ("parse_error_message", "parse_error_line", "parse_error_column", "repair_applied"):
            if key in payload and payload.get(key) not in ("", None):
                result[key] = payload.get(key)
    return result


def _packet_fingerprint(packet: GraphBreakpointPacket) -> str:
    payload = {
        "graph_run_id": packet.graph_run_id,
        "node_id": packet.node_id,
        "work_order_id": packet.work_order_id,
        "graph_status": packet.graph_status,
        "task_status": packet.task_status,
        "terminal_reason": packet.terminal_reason,
        "blocked_reason": packet.blocked_reason,
        "recoverable_error": packet.recoverable_error,
        "parse_diagnostics": packet.parse_diagnostics,
    }
    return hashlib.sha1(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def _packet_recovery_identity(packet: GraphBreakpointPacket) -> tuple[str, str, str, str]:
    recoverable_error = dict(packet.recoverable_error or {})
    reason = packet.terminal_reason or packet.blocked_reason or str(recoverable_error.get("error_code") or "") or "unknown"
    return (
        packet.graph_run_id,
        packet.node_id or "graph",
        reason,
        packet.graph_config_id,
    )
