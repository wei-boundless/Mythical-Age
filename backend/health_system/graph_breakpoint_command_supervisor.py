from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from task_system import TaskFlowRegistry

from .registry import HealthRegistry

logger = logging.getLogger(__name__)

_PROTOCOL_REPAIR_VALIDATION_ERRORS = {
    "public_progress_note_required",
    "public_action_state_required",
}
_PROTOCOL_REPAIR_REQUIRED_SIGNATURE = {
    "public_progress_note_required",
    "public_action_state_required",
}
_AUTO_RESUME_REASONS = {
    "active_work_order_executor_missing_after_restart",
    "active_work_order_executor_missing",
    "background_executor_missing_after_restart",
    "model_action_protocol_repair_required",
    "model_call_recovery_required",
    "quality_gate_failed",
    "task_execution_step_budget_exceeded",
    "task_execution_step_budget_exhausted",
    "task_executor_interrupted_by_runtime_restart",
    "task_run_executor_already_running",
    "waiting_executor",
}
_GRAPH_CONFIG_MISMATCH_ERRORS = {
    "GraphRun structure_hash does not match ExecutableGraphConfig",
    "GraphRun graph_id does not match ExecutableGraphConfig",
    "Graph operation requires a published ExecutableGraphConfig",
    "ExecutableGraphConfig config_hash mismatch (content_hash mismatch)",
    "graph_config_snapshot_missing",
}
_RUNTIME_RESOURCE_ERROR_PREFIXES = (
    "Worker prompt template resources missing from prompt_library/resources:",
)
_RETRYABLE_RECOVERY_FAILURE_KINDS = {
    "graph_runner_active",
    "runtime_prompt_catalog_unavailable",
}


class GraphBreakpointCommandSupervisor:
    def __init__(
        self,
        *,
        base_dir: Path,
        runtime: Any,
        poll_interval_seconds: float = 20.0,
        batch_limit: int = 1,
        max_resume_dispatch_requests: int = 4,
        max_retryable_recovery_attempts: int = 3,
        retryable_failure_cooldown_seconds: float = 120.0,
    ) -> None:
        self.base_dir = Path(base_dir)
        self.runtime = runtime
        self.poll_interval_seconds = max(5.0, float(poll_interval_seconds or 20.0))
        self.batch_limit = max(1, int(batch_limit or 1))
        self.max_resume_dispatch_requests = max(1, int(max_resume_dispatch_requests or 4))
        self.max_retryable_recovery_attempts = max(1, int(max_retryable_recovery_attempts or 3))
        self.retryable_failure_cooldown_seconds = max(30.0, float(retryable_failure_cooldown_seconds or 120.0))

    async def run_forever(self) -> None:
        await asyncio.sleep(0.1)
        while True:
            try:
                await asyncio.to_thread(_run_once_in_worker_loop, self)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("graph breakpoint command supervision tick failed")
            await asyncio.sleep(self.poll_interval_seconds)

    async def run_once(self) -> dict[str, Any]:
        registry = HealthRegistry(self.base_dir)
        pending = self._dedupe_pending_commands(registry, self._list_pending_commands(registry))
        processed: list[str] = []
        resumed: list[str] = []
        continued: list[str] = []
        observing: list[str] = []
        for command in pending[: self.batch_limit]:
            action = await self._process_command(registry, command)
            processed.append(command.command_id)
            if action.get("resume_attempted"):
                resumed.append(command.command_id)
            if action.get("continued"):
                continued.append(command.command_id)
            if action.get("observing"):
                observing.append(command.command_id)
        return {
            "authority": "health_system.graph_breakpoint_command_supervisor",
            "pending_count": len(pending),
            "processed_count": len(processed),
            "processed_command_ids": processed,
            "resumed_count": len(resumed),
            "resumed_command_ids": resumed,
            "pumped_count": 0,
            "pumped_command_ids": [],
            "continued_count": len(continued),
            "continued_command_ids": continued,
            "observing_count": len(observing),
            "observing_command_ids": observing,
        }

    def _list_pending_commands(self, registry: HealthRegistry) -> list[Any]:
        commands = [
            command
            for command in registry.list_commands()
            if command.status == "pending"
            and command.command_type == "analyze_trace"
            and command.health_action == "graph_breakpoint_diagnostics"
            and command.source == "health_system.graph_breakpoint_supervisor"
            and _command_ready_for_processing(command)
        ]
        commands.sort(key=lambda item: (float(item.created_at or 0.0), str(item.command_id or "")))
        return commands

    def _dedupe_pending_commands(self, registry: HealthRegistry, commands: list[Any]) -> list[Any]:
        seen: dict[str, str] = {}
        unique: list[Any] = []
        for command in commands:
            key = _command_recovery_key(command)
            if not key:
                unique.append(command)
                continue
            canonical_command_id = seen.get(key)
            if canonical_command_id:
                self._complete_duplicate_command(
                    registry,
                    command,
                    canonical_command_id=canonical_command_id,
                )
                continue
            seen[key] = str(command.command_id or "")
            unique.append(command)
        return unique

    def _complete_duplicate_command(
        self,
        registry: HealthRegistry,
        command: Any,
        *,
        canonical_command_id: str,
    ) -> None:
        issue = registry.get_issue(command.target_ref)
        payload = dict(command.payload or {})
        report = registry.command_builder.build_report(
            command=command,
            report_type="analyze_trace_report",
            issue_ref=issue.issue_id if issue is not None else command.target_ref,
            evidence_refs=(
                str(payload.get("graph_run_id") or ""),
                str(payload.get("task_run_id") or ""),
                str(payload.get("work_order_id") or ""),
            ),
            verdict="completed",
            severity=str(getattr(issue, "severity", "medium") or "medium"),
            summary=f"图断点重复监督命令已合并，跟随主命令：{canonical_command_id}。",
            recommended_actions=("follow_canonical_command",),
        )
        registry.store.append_report(report)
        receipt = registry.command_builder.build_receipt(
            command=command,
            accepted=True,
            status="completed",
            health_issue_ref=issue.issue_id if issue is not None else command.target_ref,
            report_ref=report.report_id,
            admission_status="graph_breakpoint_duplicate_merged",
            run_status="completed",
            blocked_reasons=(),
            diagnostics={
                "mode": "graph_breakpoint_duplicate_merged",
                "processed_at": time.time(),
                "canonical_command_ref": canonical_command_id,
                "recovery_key": _command_recovery_key(command),
            },
        )
        registry._complete_command(command, receipt=receipt, report=report)

    async def _process_command(self, registry: HealthRegistry, command: Any) -> dict[str, Any]:
        issue = registry.get_issue(command.target_ref)
        payload = dict(command.payload or {})
        verdict = self._build_verdict(payload)
        resume_result: dict[str, Any] | None = None
        recovery_error = ""
        recovery_failure_kind = ""
        if verdict["recommended_action"] == "resume_graph_run":
            try:
                recovery_result = await self._recover_graph_run(payload=payload, verdict=verdict)
                resume_result = dict(recovery_result.get("resume_result") or {})
            except Exception as exc:  # pragma: no cover - protected by tests via result payload
                recovery_error = str(exc) or exc.__class__.__name__
                recovery_failure_kind = _classify_recovery_error(recovery_error)
                if recovery_failure_kind:
                    logger.warning(
                        "graph breakpoint auto-resume rejected for %s: %s",
                        command.command_id,
                        recovery_failure_kind,
                    )
                else:
                    logger.exception("graph breakpoint auto-resume failed for %s", command.command_id)
        should_continue = False
        should_observe = self._should_observe_after_resume(
            verdict=verdict,
            resume_result=resume_result,
            recovery_error=recovery_error,
            recovery_failure_kind=recovery_failure_kind,
        )
        should_retry_later = self._should_retry_later(
            command=command,
            recovery_failure_kind=recovery_failure_kind,
        )
        pending_followup = should_retry_later
        command_failed = bool(recovery_error and not recovery_failure_kind)
        receipt_status = "pending" if pending_followup else ("observing" if should_observe else ("completed" if not command_failed else "failed"))
        run_status = (
            "continuing"
            if should_continue
            else ("waiting_runtime_resource" if should_retry_later else ("observing" if should_observe else ("blocked" if recovery_failure_kind else receipt_status)))
        )
        report = registry.command_builder.build_report(
            command=command,
            report_type="analyze_trace_report",
            issue_ref=issue.issue_id if issue is not None else command.target_ref,
            evidence_refs=(
                str(payload.get("graph_run_id") or ""),
                str(payload.get("task_run_id") or ""),
                str(payload.get("work_order_id") or ""),
            ),
            verdict="continuing" if pending_followup else ("observing" if should_observe else ("completed" if not command_failed else "failed")),
            severity=str(getattr(issue, "severity", "medium") or "medium"),
            summary=self._summary_text(
                payload=payload,
                verdict=verdict,
                resume_result=resume_result,
                recovery_error=recovery_error,
                recovery_failure_kind=recovery_failure_kind,
                continuing=should_continue,
                observing=should_observe,
                waiting_retry=should_retry_later,
            ),
            recommended_actions=tuple(
                self._recommended_actions(
                    verdict=verdict,
                    resume_result=resume_result,
                    recovery_error=recovery_error,
                    recovery_failure_kind=recovery_failure_kind,
                    continuing=should_continue,
                    observing=should_observe,
                    waiting_retry=should_retry_later,
                )
            ),
        )
        registry.store.append_report(report)
        receipt = registry.command_builder.build_receipt(
            command=command,
            accepted=not command_failed,
            status=receipt_status,
            health_issue_ref=issue.issue_id if issue is not None else command.target_ref,
            report_ref=report.report_id,
            admission_status="graph_breakpoint_short_recovery",
            run_status=run_status,
            blocked_reasons=tuple([recovery_failure_kind or recovery_error] if recovery_error else []),
            diagnostics={
                "mode": "graph_breakpoint_short_recovery",
                "processed_at": time.time(),
                "verdict": verdict,
                "resume_attempted": verdict["recommended_action"] == "resume_graph_run",
                "resume_result": _compact_graph_recovery_result(resume_result),
                "recovery_error": recovery_error,
                "recovery_failure_kind": recovery_failure_kind,
                "continued": should_continue,
                "observing": should_observe,
                "retry_later": should_retry_later,
            },
        )
        if pending_followup:
            self._defer_command_retry(
                registry,
                command,
                receipt=receipt,
                next_allowed_delay_seconds=self.retryable_failure_cooldown_seconds,
                run_status=run_status,
            )
        elif should_observe:
            self._observe_command(registry, command, receipt=receipt, report=report)
        else:
            registry._complete_command(command, receipt=receipt, report=report)
        return {
            "command_id": command.command_id,
            "resume_attempted": verdict["recommended_action"] == "resume_graph_run",
            "resume_result": resume_result or {},
            "recovery_error": recovery_error,
            "recovery_failure_kind": recovery_failure_kind,
            "continued": should_continue,
            "observing": should_observe,
            "retry_later": should_retry_later,
        }

    def _build_verdict(self, payload: dict[str, Any]) -> dict[str, Any]:
        graph_run_id = str(payload.get("graph_run_id") or "").strip()
        blocked_node_id = str(payload.get("node_id") or "").strip()
        recoverable_error = dict(payload.get("recoverable_error") or {})
        parse_diagnostics = dict(payload.get("parse_diagnostics") or {})
        graph_status = str(payload.get("graph_status") or "").strip()
        task_status = str(payload.get("task_status") or "").strip()
        validation_errors = [
            str(item).strip()
            for item in list(recoverable_error.get("validation_errors") or [])
            if str(item).strip()
        ]
        retryable = bool(recoverable_error.get("retryable", True))
        reason_candidates = [
            str(payload.get("terminal_reason") or "").strip(),
            str(payload.get("blocked_reason") or "").strip(),
            str(recoverable_error.get("error_code") or "").strip(),
        ]
        reasons = [item for item in reason_candidates if item]
        problem_type = "logic_blocking"
        recommended_action = "wait_human"
        confidence = 0.55
        reason = reasons[0] if reasons else "unknown"
        if not graph_run_id:
            confidence = 0.95
            reason = "graph_run_missing"
            recommended_action = "inspect_runtime_packet"
            problem_type = "system_fault"
        elif graph_status == "waiting_human_gate":
            confidence = 0.9
            recommended_action = "wait_human_gate"
            problem_type = "human_gate_required"
        elif self._is_state_split_recoverable(
            graph_status=graph_status,
            task_status=task_status,
            reasons=reasons,
            retryable=retryable,
            validation_errors=validation_errors,
        ):
            recommended_action = "resume_graph_run"
            problem_type = "runtime_recoverable"
            confidence = 0.93
        elif retryable and any(item in _AUTO_RESUME_REASONS for item in reasons):
            recommended_action = "resume_graph_run"
            problem_type = "runtime_recoverable"
            confidence = 0.84
        elif retryable and validation_errors and set(validation_errors).issubset(_PROTOCOL_REPAIR_VALIDATION_ERRORS):
            recommended_action = "resume_graph_run"
            problem_type = "runtime_recoverable"
            confidence = 0.88
        elif retryable and self._has_protocol_repair_signature(
            error_code=str(recoverable_error.get("error_code") or "").strip(),
            validation_errors=validation_errors,
            reasons=reasons,
        ):
            recommended_action = "resume_graph_run"
            problem_type = "runtime_recoverable"
            confidence = 0.91
        elif retryable and parse_diagnostics and "model_action_protocol_repair_required" in reasons:
            recommended_action = "resume_graph_run"
            problem_type = "runtime_recoverable"
            confidence = 0.82
        elif str(payload.get("blocked_reason") or "").strip() == "quality_gate_failed":
            recommended_action = "resume_graph_run"
            problem_type = "content_repairable"
            confidence = 0.67
        return {
            "problem_type": problem_type,
            "recommended_action": recommended_action,
            "retry_allowed": recommended_action == "resume_graph_run",
            "confidence": confidence,
            "graph_run_id": graph_run_id,
            "blocked_node_id": blocked_node_id,
            "reason": reason,
            "validation_errors": validation_errors,
            "parse_diagnostics_present": bool(parse_diagnostics),
        }

    def _is_state_split_recoverable(
        self,
        *,
        graph_status: str,
        task_status: str,
        reasons: list[str],
        retryable: bool,
        validation_errors: list[str],
    ) -> bool:
        if graph_status != "blocked":
            return False
        if task_status not in {"waiting_executor", "blocked"}:
            return False
        if any(item in _AUTO_RESUME_REASONS for item in reasons if item != "quality_gate_failed"):
            return retryable
        if self._has_protocol_repair_signature(
            error_code="model_action_invalid",
            validation_errors=validation_errors,
            reasons=reasons,
        ):
            return retryable
        return False

    def _has_protocol_repair_signature(
        self,
        *,
        error_code: str,
        validation_errors: list[str],
        reasons: list[str],
    ) -> bool:
        normalized = {item for item in validation_errors if item}
        if not _PROTOCOL_REPAIR_REQUIRED_SIGNATURE.issubset(normalized):
            return False
        if error_code == "model_action_invalid":
            return True
        return "model_action_protocol_repair_required" in reasons

    async def _recover_graph_run(self, *, payload: dict[str, Any], verdict: dict[str, Any]) -> dict[str, Any]:
        graph_config = self._resolve_graph_config(payload)
        resume_result = await asyncio.to_thread(self._resume_graph_run, payload, graph_config=graph_config)
        return {
            "resume_result": resume_result,
        }

    def _resume_graph_run(self, payload: dict[str, Any], *, graph_config: Any | None = None) -> dict[str, Any]:
        graph_run_id = str(payload.get("graph_run_id") or "").strip()
        if not graph_run_id:
            raise ValueError("graph_run_id_missing")
        resolved_graph_config = graph_config or self._resolve_graph_config(payload)
        result = self.runtime.harness_runtime.graph_system.resume_run(
            graph_config=resolved_graph_config,
            graph_run_id=graph_run_id,
            dispatch_ready=True,
            max_requests=self.max_resume_dispatch_requests,
        )
        return result.to_dict() if hasattr(result, "to_dict") else dict(result or {})

    def _resolve_graph_config(self, payload: dict[str, Any]) -> Any:
        config_id = str(payload.get("graph_config_id") or "").strip()
        graph_id = str(payload.get("graph_id") or "").strip()
        registry = TaskFlowRegistry(self.base_dir)
        if config_id:
            graph_config = registry.get_graph_config(config_id)
            if graph_config is None:
                raise ValueError("graph_config_snapshot_missing")
            return graph_config
        if str(payload.get("graph_run_id") or "").strip():
            raise ValueError("graph_config_snapshot_missing")
        graph_config = registry.get_published_graph_config(graph_id) if graph_id else None
        if graph_config is None:
            raise ValueError("graph_config_missing")
        return graph_config

    def _recommended_actions(
        self,
        *,
        verdict: dict[str, Any],
        resume_result: dict[str, Any] | None,
        recovery_error: str,
        recovery_failure_kind: str = "",
        continuing: bool = False,
        observing: bool = False,
        waiting_retry: bool = False,
    ) -> list[str]:
        actions = [str(verdict.get("recommended_action") or "inspect_breakpoint")]
        if continuing:
            actions.append("observe_graph_run_monitor")
        elif waiting_retry:
            if recovery_failure_kind == "graph_runner_active":
                actions.extend(["wait_active_graph_runner", "retry_short_graph_recovery", "observe_graph_run_monitor"])
            else:
                actions.extend(["wait_runtime_resource", "retry_short_graph_recovery", "inspect_prompt_catalog"])
        elif recovery_failure_kind == "graph_config_snapshot_mismatch":
            actions.extend(["inspect_graph_config_snapshot", "restart_from_matching_graph_config", "manual_repair"])
        elif recovery_error:
            actions.extend(["inspect_resume_failure", "review_breakpoint_packet"])
        elif observing:
            actions.append("observe_graph_run_monitor")
        elif resume_result:
            reason = str(resume_result.get("reason") or "")
            if reason == "blocked_not_recoverable":
                actions.extend(["review_breakpoint_packet", "manual_repair"])
            elif reason.startswith("terminal:"):
                actions.append("observe_terminal_state")
            else:
                actions.append("observe_graph_run_monitor")
        else:
            actions.append("review_breakpoint_packet")
        return list(dict.fromkeys(item for item in actions if item))

    def _summary_text(
        self,
        *,
        payload: dict[str, Any],
        verdict: dict[str, Any],
        resume_result: dict[str, Any] | None,
        recovery_error: str,
        recovery_failure_kind: str = "",
        continuing: bool = False,
        observing: bool = False,
        waiting_retry: bool = False,
    ) -> str:
        node_id = str(payload.get("node_id") or "graph-root")
        graph_run_id = str(payload.get("graph_run_id") or "unknown-graph")
        reason = str(verdict.get("reason") or "unknown")
        if waiting_retry:
            return f"图断点暂缓自动续跑：{node_id} / {graph_run_id}。运行资源暂不可用，健康管家已保留命令并将在冷却后重试：{recovery_error}。"
        if recovery_failure_kind == "graph_config_snapshot_mismatch":
            return f"图断点不能自动续跑：{node_id} / {graph_run_id}。运行快照与当前图配置不匹配，已停止自动恢复并要求检查配置快照。"
        if recovery_error:
            return f"图断点自动监督失败：{node_id} / {graph_run_id}。已判定可恢复，但续跑执行失败：{recovery_error}。"
        if verdict["recommended_action"] != "resume_graph_run":
            return f"图断点已分析：{node_id} / {graph_run_id}。判定为 {verdict['problem_type']}，当前不自动续跑，原因：{reason}。"
        if not resume_result:
            return f"图断点已分析：{node_id} / {graph_run_id}。判定可恢复，但未获得续跑结果。"
        resume_reason = str(resume_result.get("reason") or "unknown")
        if observing:
            return f"图断点已短恢复：{node_id} / {graph_run_id}。判定为 {verdict['problem_type']}，恢复结果：{resume_reason}；Graph Runtime 已接手活跃工作，健康管家转为观察。"
        return f"图断点已短恢复：{node_id} / {graph_run_id}。判定为 {verdict['problem_type']}，恢复结果：{resume_reason}。"

    def _should_observe_after_resume(
        self,
        *,
        verdict: dict[str, Any],
        resume_result: dict[str, Any] | None,
        recovery_error: str,
        recovery_failure_kind: str,
    ) -> bool:
        if recovery_error or recovery_failure_kind or not resume_result:
            return False
        if verdict.get("recommended_action") != "resume_graph_run":
            return False
        reason = str(resume_result.get("reason") or "").strip()
        if _recovery_result_has_active_work(resume_result):
            return True
        return reason in {
            "active_work_orders_reconnected",
            "ready_nodes_dispatched",
        }

    def _should_retry_later(
        self,
        *,
        command: Any,
        recovery_failure_kind: str,
    ) -> bool:
        if recovery_failure_kind not in _RETRYABLE_RECOVERY_FAILURE_KINDS:
            return False
        payload = dict(getattr(command, "payload", {}) or {})
        retry_count = int(payload.get("recovery_retry_count") or 0)
        return retry_count < self.max_retryable_recovery_attempts

    def _defer_command_retry(
        self,
        registry: HealthRegistry,
        command: Any,
        *,
        receipt: Any,
        next_allowed_delay_seconds: float = 0.0,
        run_status: str = "continuing",
    ) -> None:
        registry.store.append_receipt(receipt)
        payload = dict(getattr(command, "payload", {}) or {})
        retry_count = int(payload.get("recovery_retry_count") or 0) + 1
        next_allowed_at = time.time() + max(0.0, float(next_allowed_delay_seconds or 0.0))
        updated = replace(
            command,
            status="pending",
            updated_at=time.time(),
            payload={
                **payload,
                "recovery_retry_count": retry_count,
                "recovery_last_receipt_ref": receipt.receipt_id,
                "recovery_last_run_status": run_status,
                "recovery_next_allowed_at": next_allowed_at,
            },
        )
        registry.store.upsert_command(updated)

    def _observe_command(
        self,
        registry: HealthRegistry,
        command: Any,
        *,
        receipt: Any,
        report: Any,
    ) -> None:
        registry.store.append_receipt(receipt)
        payload = dict(getattr(command, "payload", {}) or {})
        registry.store.upsert_command(
            replace(
                command,
                status="observing",
                updated_at=time.time(),
                payload={
                    **payload,
                    "recovery_last_receipt_ref": receipt.receipt_id,
                    "recovery_last_run_status": "observing",
                    "recovery_observing_report_ref": getattr(report, "report_id", ""),
                },
            )
        )


def _command_recovery_key(command: Any) -> str:
    payload = dict(getattr(command, "payload", {}) or {})
    explicit = str(payload.get("graph_breakpoint_recovery_key") or "").strip()
    if explicit:
        return explicit
    graph_run_id = str(payload.get("graph_run_id") or "").strip()
    if not graph_run_id:
        return ""
    node_id = str(payload.get("node_id") or "").strip()
    terminal_reason = str(
        payload.get("terminal_reason")
        or payload.get("blocked_reason")
        or dict(payload.get("recoverable_error") or {}).get("error_code")
        or ""
    ).strip()
    config_id = str(payload.get("graph_config_id") or "config_unknown").strip()
    if not node_id or not terminal_reason:
        return ""
    return "|".join((graph_run_id, node_id, terminal_reason, config_id))


def _classify_recovery_error(error: str) -> str:
    normalized = str(error or "").strip()
    if "graph_run_runner_already_active" in normalized:
        return "graph_runner_active"
    if normalized in _GRAPH_CONFIG_MISMATCH_ERRORS:
        return "graph_config_snapshot_mismatch"
    if any(normalized.startswith(prefix) for prefix in _RUNTIME_RESOURCE_ERROR_PREFIXES):
        return "runtime_prompt_catalog_unavailable"
    return ""


def _command_ready_for_processing(command: Any) -> bool:
    payload = dict(getattr(command, "payload", {}) or {})
    next_allowed_at = _safe_float(payload.get("recovery_next_allowed_at"))
    return next_allowed_at <= 0 or time.time() >= next_allowed_at


def _run_once_in_worker_loop(supervisor: GraphBreakpointCommandSupervisor) -> dict[str, Any]:
    return asyncio.run(supervisor.run_once())


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _recovery_result_has_active_work(result: dict[str, Any] | None) -> bool:
    if not result:
        return False
    if list(result.get("active_work_orders") or []):
        return True
    if list(result.get("active_node_work_orders") or []):
        return True
    if int(result.get("active_node_work_order_count") or 0) > 0:
        return True
    loop_state = dict(result.get("graph_loop_state") or {})
    return bool(list(loop_state.get("running_node_ids") or []))


def _compact_graph_recovery_result(result: dict[str, Any] | None) -> dict[str, Any]:
    if not result:
        return {}
    loop_state = dict(result.get("graph_loop_state") or {})
    compact: dict[str, Any] = {
        "authority": result.get("authority"),
        "graph_run_id": result.get("graph_run_id"),
        "status": result.get("status"),
        "reason": result.get("reason"),
        "terminal_reason": result.get("terminal_reason"),
        "blocked_reason": result.get("blocked_reason"),
        "budget_exhausted": result.get("budget_exhausted"),
        "resumed": result.get("resumed"),
        "executed_work_order_count": result.get("executed_work_order_count"),
        "accepted_result_count": result.get("accepted_result_count"),
        "dispatch_count": result.get("dispatch_count"),
        "active_node_work_order_count": result.get("active_node_work_order_count"),
        "graph_loop_state": {
            "status": loop_state.get("status"),
            "terminal_reason": loop_state.get("terminal_reason"),
            "ready_node_ids": _compact_string_list(loop_state.get("ready_node_ids")),
            "running_node_ids": _compact_string_list(loop_state.get("running_node_ids")),
            "blocked_node_ids": _compact_string_list(loop_state.get("blocked_node_ids")),
            "failed_node_ids": _compact_string_list(loop_state.get("failed_node_ids")),
        },
        "active_work_orders": _compact_work_orders(result.get("active_work_orders")),
        "node_work_orders": _compact_work_orders(result.get("node_work_orders")),
        "active_node_work_orders": _compact_work_orders(result.get("active_node_work_orders")),
    }
    return {key: value for key, value in compact.items() if value not in (None, "", [], {})}


def _compact_string_list(value: Any, *, limit: int = 12) -> list[str]:
    return [str(item) for item in list(value or [])[:limit] if str(item)]


def _compact_work_orders(value: Any, *, limit: int = 8) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for item in list(value or [])[:limit]:
        row = dict(item or {}) if isinstance(item, dict) else {}
        compact.append(
            {
                key: row.get(key)
                for key in ("work_order_id", "node_id", "status", "task_run_id", "terminal_reason")
                if row.get(key) not in (None, "", [], {})
            }
        )
    return [item for item in compact if item]
