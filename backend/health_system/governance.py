from __future__ import annotations

import time
from typing import Any

from runtime.environment import RuntimeEnvironment, check_runtime_connection_health
from runtime.prompt_accounting import TokenCounterRegistry

from .store import HealthStore
from .task_record_maintenance import HealthTaskRecordMaintenanceService


ACTIVE_STATUSES = {"created", "queued", "running", "waiting_approval", "paused"}
FAILED_STATUSES = {"failed", "aborted", "cancelled"}
WARNING_STATUSES = {"waiting_approval", "paused"}


class HealthGovernanceBuilder:
    def __init__(self, runtime: Any) -> None:
        self.runtime = runtime
        self.runtime_host = runtime.query_runtime.single_agent_runtime_host
        self.state_index = self.runtime_host.state_index
        self.prompt_accounting_ledger = getattr(self.runtime_host, "prompt_accounting_ledger", None)
        self.token_counter = TokenCounterRegistry()
        self.now = time.time()
        self.store = self._build_store()

    def build_overview(self, *, limit: int = 80) -> dict[str, Any]:
        tasks = self.build_tasks(limit=limit)["tasks"]
        monitor = self._global_monitor(limit=limit)
        risks = self._risk_events(tasks=tasks, monitor=monitor)
        token_usage = self._token_usage(tasks)
        efficiency = self._efficiency(tasks)
        system_risks = self._system_risks(monitor=monitor)
        monitor_governance = self._monitor_governance(monitor=monitor)
        recommendations = self._recommendations(risks=risks, token_usage=token_usage, efficiency=efficiency)
        summary = {
            "task_count": len(tasks),
            "running_task_count": sum(1 for item in tasks if item["status"] in ACTIVE_STATUSES),
            "waiting_task_count": sum(1 for item in tasks if item["status"] in WARNING_STATUSES),
            "failed_task_count": sum(1 for item in tasks if item["status"] in FAILED_STATUSES),
            "risk_event_count": len(risks),
            "critical_risk_count": sum(1 for item in risks if item["severity"] == "critical"),
            "high_risk_count": sum(1 for item in risks if item["severity"] == "high"),
            "token_total": int(token_usage["summary"].get("total_tokens") or 0),
            "slow_task_count": int(efficiency["summary"].get("slow_task_count") or 0),
        }
        return {
            "authority": "health_system.governance",
            "summary": summary,
            "tasks": tasks,
            "risks": risks,
            "system_risks": system_risks,
            "token_usage": token_usage,
            "efficiency": efficiency,
            "recommendations": recommendations,
            "monitor": monitor,
            "monitor_governance": monitor_governance,
            "updated_at": self.now,
        }

    def build_tasks(self, *, limit: int = 100) -> dict[str, Any]:
        task_runs = sorted(
            self.state_index.list_task_runs(),
            key=lambda item: float(item.updated_at or item.created_at or 0.0),
            reverse=True,
        )[: max(1, min(int(limit or 100), 300))]
        tasks = [self._task_record(task_run) for task_run in task_runs]
        return {
            "authority": "health_system.governance.tasks",
            "tasks": tasks,
            "summary": {
                "task_count": len(tasks),
                "running_task_count": sum(1 for item in tasks if item["status"] in ACTIVE_STATUSES),
                "failed_task_count": sum(1 for item in tasks if item["status"] in FAILED_STATUSES),
            },
            "updated_at": self.now,
        }

    def build_task_detail(self, task_run_id: str) -> dict[str, Any]:
        task_run = self.state_index.get_task_run(task_run_id)
        if task_run is None:
            raise KeyError(task_run_id)
        record = self._task_record(task_run)
        monitor = self.runtime_host.get_task_run_live_monitor(task_run_id) or {}
        graph_monitor: dict[str, Any] = {}
        events = [item.to_dict() for item in self.runtime_host.event_log.list_events(task_run_id)[-160:]]
        risks = self._task_risks(record, monitor=monitor, graph_monitor=graph_monitor)
        prompt_accounting = self._task_prompt_accounting_detail(task_run_id)
        return {
            "authority": "health_system.governance.task_detail",
            "task": record,
            "monitor": monitor,
            "task_graph_monitor": graph_monitor,
            "prompt_accounting": prompt_accounting,
            "risks": risks,
            "recent_events": events,
            "updated_at": self.now,
        }

    def build_risks(self, *, limit: int = 100) -> dict[str, Any]:
        overview = self.build_overview(limit=limit)
        return {
            "authority": "health_system.governance.risks",
            "risks": overview["risks"],
            "summary": {
                "risk_event_count": len(overview["risks"]),
                "critical_risk_count": overview["summary"]["critical_risk_count"],
                "high_risk_count": overview["summary"]["high_risk_count"],
            },
            "updated_at": self.now,
        }

    def build_system_risks(self) -> dict[str, Any]:
        monitor = self._global_monitor(limit=80)
        risks = self._system_risks(monitor=monitor)
        return {
            "authority": "health_system.governance.system_risks",
            "system_risks": risks,
            "summary": {"system_risk_count": len(risks)},
            "monitor": monitor,
            "updated_at": self.now,
        }

    def build_monitor_governance(self) -> dict[str, Any]:
        monitor = self._global_monitor(limit=120)
        return self._monitor_governance(monitor=monitor)

    def build_token_usage(self, *, limit: int = 100) -> dict[str, Any]:
        return self._token_usage(self.build_tasks(limit=limit)["tasks"])

    def build_efficiency(self, *, limit: int = 100) -> dict[str, Any]:
        return self._efficiency(self.build_tasks(limit=limit)["tasks"])

    def build_task_record_maintenance(
        self,
        *,
        bucket: str = "static",
        task_run_ids: list[str] | None = None,
        min_age_seconds: int = 24 * 60 * 60,
    ) -> dict[str, Any]:
        return self._maintenance_service().build_view(
            bucket=bucket,
            task_run_ids=task_run_ids,
            min_age_seconds=min_age_seconds,
        )

    def prune_task_records(
        self,
        *,
        bucket: str = "static",
        task_run_ids: list[str] | None = None,
        dry_run: bool = False,
        min_age_seconds: int = 24 * 60 * 60,
        operation: str = "delete_expired",
    ) -> dict[str, Any]:
        result = self._maintenance_service().prune_task_records(
            bucket=bucket,
            task_run_ids=task_run_ids,
            dry_run=dry_run,
            min_age_seconds=min_age_seconds,
            operation=operation,
        )
        result["monitor"] = self._global_monitor(limit=80)
        return result

    def _maintenance_service(self) -> HealthTaskRecordMaintenanceService:
        return HealthTaskRecordMaintenanceService(
            runtime_host=self.runtime_host,
            prompt_accounting_ledger=self.prompt_accounting_ledger,
            store=self.store,
            now=self.now,
        )

    def _build_store(self) -> HealthStore | None:
        base_dir = getattr(self.runtime, "base_dir", None)
        if base_dir is None:
            return None
        return HealthStore(base_dir)

    def _task_record(self, task_run: Any) -> dict[str, Any]:
        task_run_id = str(task_run.task_run_id or "")
        events = self.runtime_host.event_log.list_events(task_run_id)
        event_dicts = [item.to_dict() for item in events]
        agent_runs = self.state_index.list_task_agent_runs(task_run_id)
        worker_requests = self.state_index.list_task_worker_spawn_requests(task_run_id)
        worker_results = self.state_index.list_task_worker_spawn_results(task_run_id)
        supervision_records = self.state_index.list_task_supervision_records(task_run_id)
        status = str(task_run.status or "unknown")
        duration = self._duration(task_run.created_at, task_run.updated_at, status=status)
        tool_count = sum(1 for item in event_dicts if "tool" in str(item.get("event_type") or ""))
        error_count = sum(
            1
            for item in event_dicts
            if "error" in str(item.get("event_type") or "").lower()
            or str(item.get("payload") or "").lower().find("error") >= 0
        )
        token_summary = self._task_token_summary(task_run, event_dicts)
        token_total = int(token_summary.get("effective_total_tokens") or token_summary.get("total_tokens") or 0)
        risk_level = self._risk_level(status=status, duration_seconds=duration, error_count=error_count)
        latest_risk = self._latest_task_risk_title(status=status, duration_seconds=duration, error_count=error_count)
        return {
            "task_run_id": task_run_id,
            "session_id": str(task_run.session_id or ""),
            "task_contract_ref": str(task_run.task_contract_ref or ""),
            "title": str(
                dict(task_run.diagnostics or {}).get("title")
                or dict(task_run.diagnostics or {}).get("task_graph_title")
                or dict(task_run.diagnostics or {}).get("project_title")
                or task_run.task_id
                or task_run_id
            ),
            "task_id": str(task_run.task_id or ""),
            "agent_id": str(task_run.agent_id or ""),
            "agent_profile_id": str(task_run.agent_profile_id or ""),
            "runtime_lane": self._task_runtime_lane(task_run),
            "status": status,
            "terminal_reason": str(task_run.terminal_reason or ""),
            "created_at": float(task_run.created_at or 0.0),
            "updated_at": float(task_run.updated_at or 0.0),
            "duration_seconds": duration,
            "agent_count": max(len(agent_runs), 1 if str(task_run.agent_id or "") else 0),
            "worker_request_count": len(worker_requests),
            "worker_result_count": len(worker_results),
            "tool_call_count": tool_count,
            "event_count": len(events),
            "error_count": error_count,
            "token_total": token_total,
            "token_source": self._token_source(token_summary),
            "exact_token_total": int(token_summary.get("exact_total_tokens") or 0),
            "predicted_token_total": int(token_summary.get("predicted_total_tokens") or 0),
            "trace_estimate_token_total": int(token_summary.get("trace_estimate_total_tokens") or 0),
            "cached_tokens": int(token_summary.get("cached_tokens") or 0),
            "cache_savings_tokens": int(token_summary.get("cache_savings_tokens") or 0),
            "token_record_count": int(token_summary.get("record_count") or 0),
            "risk_level": risk_level,
            "latest_risk_event": latest_risk,
            "supervision_count": len(supervision_records),
            "latest_event_type": str(event_dicts[-1].get("event_type") if event_dicts else ""),
            "monitor_ref": f"runtime_monitor:{task_run_id}",
            "record_refs": {
                "task_run": task_run_id,
                "task_contract": str(task_run.task_contract_ref or ""),
                "session": str(task_run.session_id or ""),
            },
        }

    def _global_monitor(self, *, limit: int) -> dict[str, Any]:
        try:
            return dict(self.runtime_host.list_global_live_monitor(limit=limit) or {})
        except Exception as exc:
            return {
                "authority": "runtime_live_monitor.global",
                "summary": {"total": 0, "running": 0, "waiting": 0, "failed": 0, "stale": 0},
                "task_runs": [],
                "error": str(exc),
                "updated_at": self.now,
            }

    def _risk_events(self, *, tasks: list[dict[str, Any]], monitor: dict[str, Any]) -> list[dict[str, Any]]:
        risks: list[dict[str, Any]] = []
        for task in tasks:
            risks.extend(self._task_risks(task, monitor={}, graph_monitor={}))
        risks.extend(self._system_risks(monitor=monitor))
        severity_order = {"critical": 0, "high": 1, "warning": 2, "info": 3}
        return sorted(
            risks,
            key=lambda item: (severity_order.get(str(item.get("severity") or "info"), 9), -float(item.get("created_at") or 0.0)),
        )[:120]

    def _task_risks(self, task: dict[str, Any], *, monitor: dict[str, Any], graph_monitor: dict[str, Any]) -> list[dict[str, Any]]:
        risks: list[dict[str, Any]] = []
        task_run_id = str(task.get("task_run_id") or "")
        status = str(task.get("status") or "")
        duration = float(task.get("duration_seconds") or 0.0)
        error_count = int(task.get("error_count") or 0)
        if status in FAILED_STATUSES:
            risks.append(self._risk("task", "critical", task_run_id, "任务运行失败", task.get("terminal_reason") or "任务已进入失败或中止状态。"))
        if status in WARNING_STATUSES:
            risks.append(self._risk("task", "high", task_run_id, "任务等待处理", "任务处于等待确认或暂停状态，需要人工处理或恢复。"))
        if status in ACTIVE_STATUSES and duration > 1800:
            risks.append(self._risk("efficiency", "high", task_run_id, "任务运行时间过长", f"任务已运行约 {int(duration)} 秒，建议检查是否卡住或空转。"))
        if error_count > 0:
            risks.append(self._risk("task", "warning", task_run_id, "任务事件包含错误", f"最近事件中发现 {error_count} 个错误信号。"))
        if int(task.get("token_total") or 0) > 120000:
            risks.append(self._risk("token", "warning", task_run_id, "会话 token 压力偏高", "该任务所在会话 token 使用较高，可能需要摘要或上下文裁剪。"))
        graph_status = str(graph_monitor.get("status") or "")
        if graph_status in FAILED_STATUSES:
            risks.append(self._risk("task", "critical", task_run_id, "任务图运行失败", "任务图监控显示运行失败。"))
        monitor_status = str(dict(monitor.get("task_run") or {}).get("status") or "")
        if monitor_status in WARNING_STATUSES:
            risks.append(self._risk("task", "high", task_run_id, "监控显示任务等待处理", "实时监控显示任务需要处理。"))
        return risks

    def _system_risks(self, *, monitor: dict[str, Any]) -> list[dict[str, Any]]:
        risks: list[dict[str, Any]] = []
        summary = dict(monitor.get("summary") or {})
        if monitor.get("error"):
            risks.append(self._risk("system", "high", "runtime_monitor", "运行监控读取失败", str(monitor.get("error") or "")))
        if int(summary.get("stale") or 0) > 0:
            risks.append(self._risk("system", "warning", "runtime_monitor", "存在停滞运行", f"{summary.get('stale')} 个运行长时间未更新。"))
        if int(summary.get("waiting") or 0) > 0:
            risks.append(self._risk("task", "high", "runtime_monitor", "存在等待处理任务", f"{summary.get('waiting')} 个任务正在等待确认或人工处理。"))
        risks.extend(self._environment_risks())
        risks.extend(self._instrumentation_risks())
        return risks

    def _monitor_governance(self, *, monitor: dict[str, Any]) -> dict[str, Any]:
        summary = dict(monitor.get("summary") or {})
        task_runs = [dict(item) for item in list(monitor.get("task_runs") or []) if isinstance(item, dict)]
        stale_items = [item for item in task_runs if item.get("stale")]
        action_required = [item for item in task_runs if item.get("action_required")]
        diagnostics = [item for item in task_runs if str(item.get("bucket") or "") == "diagnostics"]
        failed_count = int(summary.get("failed") or 0)
        recommended_actions: list[dict[str, Any]] = []
        if failed_count:
            recommended_actions.append({
                "title": "查看失败运行",
                "summary": f"{failed_count} 个运行处于失败 bucket，建议进入任务健康详情确认是否需要登记健康问题。",
                "priority": "high",
            })
        if stale_items:
            recommended_actions.append({
                "title": "检查停滞运行",
                "summary": f"{len(stale_items)} 个运行长时间没有活动，优先打开任务详情查看最近事件。",
                "priority": "high",
            })
        if action_required:
            recommended_actions.append({
                "title": "处理等待确认任务",
                "summary": f"{len(action_required)} 个运行需要人工确认或解除阻塞。",
                "priority": "high",
            })
        if not recommended_actions:
            recommended_actions.append({
                "title": "监控状态稳定",
                "summary": "运行监控没有需要立即处理的停滞或等待确认信号。",
                "priority": "info",
            })
        health_status = "healthy"
        if monitor.get("error") or stale_items:
            health_status = "degraded"
        if action_required or failed_count > 0:
            health_status = "attention_required"
        return {
            "authority": "health_system.monitor_governance",
            "monitor_authority": str(monitor.get("authority") or ""),
            "revision": str(monitor.get("revision") or ""),
            "status": health_status,
            "summary": {
                "total": int(summary.get("total") or len(task_runs)),
                "running": int(summary.get("running") or 0),
                "completed": int(summary.get("completed") or 0),
                "failed": int(summary.get("failed") or 0),
                "diagnostics": int(summary.get("diagnostics") or len(diagnostics)),
                "stale": len(stale_items),
                "action_required": len(action_required),
            },
            "risk_escalations": [
                self._risk("system", "warning", str(item.get("task_run_id") or "runtime_monitor"), "运行监控诊断项", ", ".join(str(reason) for reason in list(item.get("diagnostic_reasons") or [])) or "运行监控发现诊断项。")
                for item in diagnostics[:20]
            ],
            "recommended_actions": recommended_actions,
            "updated_at": self.now,
        }

    def _token_usage(self, tasks: list[dict[str, Any]]) -> dict[str, Any]:
        by_session: dict[str, dict[str, Any]] = {}
        for task in tasks:
            session_id = str(task.get("session_id") or "")
            if not session_id:
                continue
            current = by_session.setdefault(
                session_id,
                {
                    "session_id": session_id,
                    "total_tokens": 0,
                    "exact_total_tokens": 0,
                    "predicted_total_tokens": 0,
                    "trace_estimate_total_tokens": 0,
                    "cached_tokens": 0,
                    "cache_savings_tokens": 0,
                    "task_count": 0,
                    "max_task_tokens": 0,
                    "provider_usage_task_count": 0,
                    "prediction_only_task_count": 0,
                    "trace_estimate_task_count": 0,
                },
            )
            tokens = int(task.get("token_total") or 0)
            current["total_tokens"] = int(current["total_tokens"]) + tokens
            current["exact_total_tokens"] = int(current["exact_total_tokens"]) + int(task.get("exact_token_total") or 0)
            current["predicted_total_tokens"] = int(current["predicted_total_tokens"]) + int(task.get("predicted_token_total") or 0)
            current["trace_estimate_total_tokens"] = int(current["trace_estimate_total_tokens"]) + int(task.get("trace_estimate_token_total") or 0)
            current["cached_tokens"] = int(current["cached_tokens"]) + int(task.get("cached_tokens") or 0)
            current["cache_savings_tokens"] = int(current["cache_savings_tokens"]) + int(task.get("cache_savings_tokens") or 0)
            current["max_task_tokens"] = max(int(current["max_task_tokens"]), tokens)
            current["task_count"] = int(current["task_count"]) + 1
            token_source = str(task.get("token_source") or "")
            if token_source == "provider_usage":
                current["provider_usage_task_count"] = int(current["provider_usage_task_count"]) + 1
            elif token_source == "local_prediction":
                current["prediction_only_task_count"] = int(current["prediction_only_task_count"]) + 1
            elif token_source == "trace_estimate":
                current["trace_estimate_task_count"] = int(current["trace_estimate_task_count"]) + 1
        rows = sorted(by_session.values(), key=lambda item: int(item.get("total_tokens") or 0), reverse=True)
        total = sum(int(item.get("total_tokens") or 0) for item in rows)
        exact_total = sum(int(item.get("exact_total_tokens") or 0) for item in rows)
        predicted_total = sum(int(item.get("predicted_total_tokens") or 0) for item in rows)
        trace_total = sum(int(item.get("trace_estimate_total_tokens") or 0) for item in rows)
        cached_total = sum(int(item.get("cached_tokens") or 0) for item in rows)
        cache_savings_total = sum(int(item.get("cache_savings_tokens") or 0) for item in rows)
        daily = self._token_buckets(tasks, bucket_seconds=86400, bucket_count=7, label_mode="day")
        six_hour = self._token_buckets(tasks, bucket_seconds=21600, bucket_count=4, label_mode="hour")
        return {
            "authority": "health_system.governance.token_usage",
            "summary": {
                "session_count": len(rows),
                "total_tokens": total,
                "exact_total_tokens": exact_total,
                "predicted_total_tokens": predicted_total,
                "trace_estimate_total_tokens": trace_total,
                "cached_tokens": cached_total,
                "cache_savings_tokens": cache_savings_total,
                "provider_usage_task_count": sum(1 for item in tasks if str(item.get("token_source") or "") == "provider_usage"),
                "prediction_only_task_count": sum(1 for item in tasks if str(item.get("token_source") or "") == "local_prediction"),
                "trace_estimate_task_count": sum(1 for item in tasks if str(item.get("token_source") or "") == "trace_estimate"),
                "high_pressure_session_count": sum(1 for item in rows if int(item.get("total_tokens") or 0) > 120000),
                "record_count": len(tasks),
            },
            "sessions": rows[:80],
            "tasks": sorted(
                [
                    {
                        "task_run_id": task["task_run_id"],
                        "title": task["title"],
                        "session_id": task["session_id"],
                        "token_total": task["token_total"],
                        "token_source": task.get("token_source", ""),
                        "exact_token_total": task.get("exact_token_total", 0),
                        "predicted_token_total": task.get("predicted_token_total", 0),
                        "trace_estimate_token_total": task.get("trace_estimate_token_total", 0),
                        "cached_tokens": task.get("cached_tokens", 0),
                        "cache_savings_tokens": task.get("cache_savings_tokens", 0),
                        "risk_level": task["risk_level"],
                    }
                    for task in tasks
                ],
                key=lambda item: int(item.get("token_total") or 0),
                reverse=True,
            )[:80],
            "daily": daily,
            "six_hour": six_hour,
            "note": "按 PromptAccounting 账本聚合：provider_usage 为精确消耗，local_prediction 为请求前预测，trace_estimate 只用于旧任务迁移回退。",
            "updated_at": self.now,
        }

    def _token_buckets(self, tasks: list[dict[str, Any]], *, bucket_seconds: int, bucket_count: int, label_mode: str) -> list[dict[str, Any]]:
        now_bucket = int(self.now // bucket_seconds) * bucket_seconds
        starts = [now_bucket - bucket_seconds * index for index in range(bucket_count - 1, -1, -1)]
        buckets: list[dict[str, Any]] = []
        for start in starts:
            end = start + bucket_seconds
            tokens = 0
            exact_tokens = 0
            predicted_tokens = 0
            trace_tokens = 0
            cache_savings_tokens = 0
            records = 0
            sessions: set[str] = set()
            for task in tasks:
                updated_at = float(task.get("updated_at") or task.get("created_at") or 0)
                if start <= updated_at < end:
                    tokens += int(task.get("token_total") or 0)
                    exact_tokens += int(task.get("exact_token_total") or 0)
                    predicted_tokens += int(task.get("predicted_token_total") or 0)
                    trace_tokens += int(task.get("trace_estimate_token_total") or 0)
                    cache_savings_tokens += int(task.get("cache_savings_tokens") or 0)
                    records += 1
                    session_id = str(task.get("session_id") or "")
                    if session_id:
                        sessions.add(session_id)
            buckets.append(
                {
                    "bucket": self._bucket_label(start, label_mode=label_mode),
                    "bucket_start": start,
                    "bucket_end": end,
                    "tokens": tokens,
                    "exact_tokens": exact_tokens,
                    "predicted_tokens": predicted_tokens,
                    "trace_estimate_tokens": trace_tokens,
                    "cache_savings_tokens": cache_savings_tokens,
                    "records": records,
                    "sessions": len(sessions),
                }
            )
        return buckets

    def _bucket_label(self, timestamp: int, *, label_mode: str) -> str:
        local = time.localtime(timestamp)
        if label_mode == "day":
            return time.strftime("%m-%d", local)
        return time.strftime("%m-%d %H:00", local)

    def _efficiency(self, tasks: list[dict[str, Any]]) -> dict[str, Any]:
        rows = []
        for task in tasks:
            duration = float(task.get("duration_seconds") or 0.0)
            events = max(int(task.get("event_count") or 0), 1)
            tokens = int(task.get("token_total") or 0)
            score = 100
            if duration > 1800:
                score -= 35
            elif duration > 600:
                score -= 15
            if int(task.get("error_count") or 0) > 0:
                score -= 25
            if tokens > 120000:
                score -= 15
            rows.append({
                "task_run_id": task["task_run_id"],
                "title": task["title"],
                "status": task["status"],
                "duration_seconds": duration,
                "event_count": events,
                "tool_call_count": task["tool_call_count"],
                "error_count": task["error_count"],
                "tokens_per_event": round(tokens / events, 2) if events else 0,
                "efficiency_score": max(score, 0),
            })
        slow = [item for item in rows if float(item["duration_seconds"]) > 600]
        return {
            "authority": "health_system.governance.efficiency",
            "summary": {
                "task_count": len(rows),
                "slow_task_count": len(slow),
                "average_duration_seconds": round(sum(float(item["duration_seconds"]) for item in rows) / len(rows), 2) if rows else 0,
                "average_efficiency_score": round(sum(float(item["efficiency_score"]) for item in rows) / len(rows), 2) if rows else 100,
            },
            "tasks": sorted(rows, key=lambda item: (float(item["efficiency_score"]), -float(item["duration_seconds"])))[:80],
            "updated_at": self.now,
        }

    def _recommendations(self, *, risks: list[dict[str, Any]], token_usage: dict[str, Any], efficiency: dict[str, Any]) -> list[dict[str, Any]]:
        recommendations: list[dict[str, Any]] = []
        if any(item["severity"] == "critical" for item in risks):
            recommendations.append({"title": "优先处理失败任务", "summary": "存在 critical 风险，建议先打开任务健康详情查看失败原因和最近事件。", "priority": "high"})
        if int(token_usage["summary"].get("high_pressure_session_count") or 0) > 0:
            recommendations.append({"title": "压缩高 token 会话", "summary": "部分会话 token 压力偏高，建议触发摘要、裁剪无关上下文或拆分任务。", "priority": "medium"})
        if int(efficiency["summary"].get("slow_task_count") or 0) > 0:
            recommendations.append({"title": "检查慢任务和空转", "summary": "存在运行超过 10 分钟的任务，建议检查工具等待、循环重试或人工确认。", "priority": "medium"})
        if not recommendations:
            recommendations.append({"title": "当前无高优先级健康动作", "summary": "没有发现 critical/high 风险，保持监控即可。", "priority": "info"})
        return recommendations

    def _task_trace_token_total(self, task_run: Any, events: list[dict[str, Any]]) -> int:
        fragments: list[str] = [
            str(getattr(task_run, "task_id", "") or ""),
            str(getattr(task_run, "terminal_reason", "") or ""),
        ]
        diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
        for key in ("title", "task_graph_title", "project_title", "goal", "task_goal", "summary", "latest_step_summary"):
            value = diagnostics.get(key)
            if value:
                fragments.append(str(value))
        for event in events:
            fragments.extend(self._event_token_fragments(event))
        return self.token_counter.count_text(
            "\n".join(item for item in fragments if item),
            provider="trace",
            model="legacy_trace_estimate",
        ).tokens

    def _task_token_summary(self, task_run: Any, events: list[dict[str, Any]]) -> dict[str, Any]:
        task_run_id = str(getattr(task_run, "task_run_id", "") or "")
        ledger_summary = {}
        summarizer = getattr(self.prompt_accounting_ledger, "summarize_task", None)
        if callable(summarizer) and task_run_id:
            try:
                ledger_summary = dict(summarizer(task_run_id) or {})
            except Exception:
                ledger_summary = {}
        if int(ledger_summary.get("record_count") or 0) > 0:
            return ledger_summary
        trace_tokens = self._task_trace_token_total(task_run, events)
        return {
            "exact_total_tokens": 0,
            "predicted_total_tokens": 0,
            "trace_estimate_total_tokens": trace_tokens,
            "effective_total_tokens": trace_tokens,
            "total_tokens": trace_tokens,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "reasoning_tokens": 0,
            "cached_tokens": 0,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 0,
            "cache_savings_tokens": 0,
            "provider_usage_record_count": 0,
            "local_prediction_record_count": 0,
            "trace_estimate_record_count": 1 if trace_tokens else 0,
            "record_count": 1 if trace_tokens else 0,
            "billing_truth_available": False,
        }

    def _environment_risks(self) -> list[dict[str, Any]]:
        base_dir = getattr(self.runtime, "base_dir", None)
        if base_dir is None:
            return [self._risk("system", "info", "runtime_environment", "运行环境健康探针未接入", "unknown/not_instrumented，当前 runtime 没有 base_dir。")]
        try:
            environment = RuntimeEnvironment(workspace_root=base_dir.parent)
            health = check_runtime_connection_health(environment)
            payload = health.to_dict()
        except Exception as exc:
            return [self._risk("system", "high", "runtime_environment", "运行环境健康检查失败", str(exc))]
        risks: list[dict[str, Any]] = []
        diagnostics = dict(payload.get("diagnostics") or {})
        ports = dict(payload.get("ports") or {})
        if not payload.get("ok"):
            risks.append(self._risk("system", "high", "runtime_environment", "固定运行环境异常", payload.get("error") or "runtime_environment_error"))
        if not diagnostics.get("api_base_ok", True):
            risks.append(self._risk("system", "high", "api_base", "前端 API Base 配置异常", f"期望 {diagnostics.get('api_base_expected')}，实际 {diagnostics.get('api_base_actual')}。"))
        if diagnostics.get("sse_status") == "not_checked":
            risks.append(self._risk("system", "info", "sse", "SSE 连接未纳入健康探针", "当前只能确认 API base 和端口，SSE 状态仍为 unknown/not_checked。"))
        for name, raw_probe in dict(ports.get("diagnostics") or {}).items():
            if not isinstance(raw_probe, dict):
                continue
            probe = dict(raw_probe)
            if probe.get("status") == "wrong_process_on_fixed_port":
                risks.append(self._risk("system", "high", f"port:{name}", "固定端口被非项目进程占用", str(probe.get("summary") or "")))
            elif not probe.get("listening"):
                risks.append(self._risk("system", "warning", f"port:{name}", "固定端口未监听", f"{name} 端口 {probe.get('port')} 当前未监听。"))
        return risks

    def _instrumentation_risks(self) -> list[dict[str, Any]]:
        risks: list[dict[str, Any]] = []
        for target in ("tool_runtime", "model_runtime", "sandbox"):
            risks.append(self._risk("system", "info", target, f"{target} 健康探针未接入", "unknown/not_instrumented，不能默认为 healthy。"))
        return risks

    def _task_prompt_accounting_detail(self, task_run_id: str) -> dict[str, Any]:
        ledger = self.prompt_accounting_ledger
        if ledger is None:
            return {
                "authority": "health_system.governance.prompt_accounting_detail",
                "task_run_id": task_run_id,
                "available": False,
                "segment_maps": [],
                "usage_records": [],
                "cache_records": [],
                "summary": {},
            }
        try:
            segment_maps = list(getattr(ledger, "list_segment_maps")(task_run_id=task_run_id))[-5:]
        except Exception:
            segment_maps = []
        try:
            usage_records = [item.to_dict() for item in ledger.list_token_usage(task_run_id=task_run_id)[-20:]]
        except Exception:
            usage_records = []
        try:
            cache_records = [item.to_dict() for item in ledger.list_prompt_cache(task_run_id=task_run_id)[-20:]]
        except Exception:
            cache_records = []
        try:
            summary = dict(ledger.summarize_task(task_run_id) or {})
        except Exception:
            summary = {}
        return {
            "authority": "health_system.governance.prompt_accounting_detail",
            "task_run_id": task_run_id,
            "available": bool(segment_maps or usage_records or cache_records),
            "segment_maps": segment_maps,
            "usage_records": usage_records,
            "cache_records": cache_records,
            "summary": summary,
        }

    @staticmethod
    def _token_source(summary: dict[str, Any]) -> str:
        if int(summary.get("provider_usage_record_count") or 0) > 0:
            return "provider_usage"
        if int(summary.get("local_prediction_record_count") or 0) > 0:
            return "local_prediction"
        if int(summary.get("trace_estimate_record_count") or 0) > 0:
            return "trace_estimate"
        return "none"

    @staticmethod
    def _task_runtime_lane(task_run: Any) -> str:
        diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
        for key in ("runtime_lane", "runtime_directive_lane", "lane_type"):
            value = str(diagnostics.get(key) or "").strip()
            if value:
                return value
        return str(getattr(task_run, "execution_runtime_kind", "") or "")

    def _event_token_fragments(self, event: dict[str, Any]) -> list[str]:
        event_type = str(event.get("event_type") or "")
        payload = dict(event.get("payload") or {})
        fragments = [event_type]
        for key in ("summary", "content", "final_answer", "error", "reason", "terminal_reason"):
            value = payload.get(key)
            if value:
                fragments.append(str(value))
        step_summary = payload.get("summary")
        if isinstance(step_summary, str):
            fragments.append(step_summary)
        action_request = payload.get("action_request")
        if isinstance(action_request, dict):
            fragments.extend(self._compact_record_values(action_request, keys=("action_type", "tool_name", "request_type")))
            request_payload = action_request.get("payload")
            if isinstance(request_payload, dict):
                fragments.extend(self._compact_record_values(request_payload, keys=("tool_name", "command", "path", "query", "assistant_content_preview")))
        observation = payload.get("observation")
        if isinstance(observation, dict):
            fragments.extend(self._compact_record_values(observation, keys=("source", "summary", "content")))
            observation_payload = observation.get("payload")
            if isinstance(observation_payload, dict):
                fragments.extend(self._compact_record_values(observation_payload, keys=("tool_name", "result", "error", "command", "path", "query")))
        return [fragment[:4000] for fragment in fragments if fragment]

    @staticmethod
    def _compact_record_values(record: dict[str, Any], *, keys: tuple[str, ...]) -> list[str]:
        values: list[str] = []
        for key in keys:
            value = record.get(key)
            if value:
                values.append(str(value))
        return values

    def _duration(self, created_at: float, updated_at: float, *, status: str) -> float:
        created = float(created_at or 0.0)
        updated = float(updated_at or 0.0)
        if not created:
            return 0.0
        end = self.now if status in ACTIVE_STATUSES else updated or self.now
        return max(0.0, end - created)

    def _risk_level(self, *, status: str, duration_seconds: float, error_count: int) -> str:
        if status in FAILED_STATUSES:
            return "critical"
        if status in WARNING_STATUSES or (status in ACTIVE_STATUSES and duration_seconds > 1800):
            return "high"
        if error_count > 0 or duration_seconds > 600:
            return "warning"
        return "normal"

    def _latest_task_risk_title(self, *, status: str, duration_seconds: float, error_count: int) -> str:
        if status in FAILED_STATUSES:
            return "任务运行失败"
        if status in WARNING_STATUSES:
            return "任务等待处理"
        if status in ACTIVE_STATUSES and duration_seconds > 1800:
            return "任务可能卡住"
        if error_count > 0:
            return "存在错误事件"
        return ""

    def _risk(self, scope: str, severity: str, target_ref: str, title: str, summary: str) -> dict[str, Any]:
        return {
            "event_id": f"health-risk:{scope}:{target_ref}:{title}",
            "source": "health_governance",
            "scope": scope,
            "severity": severity,
            "target_ref": target_ref,
            "title": title,
            "summary": summary,
            "recommended_action": self._recommended_action_for(scope, severity),
            "created_at": self.now,
        }

    def _recommended_action_for(self, scope: str, severity: str) -> str:
        if severity in {"critical", "high"} and scope == "task":
            return "打开任务健康详情，检查最近事件、监控状态和可恢复动作。"
        if scope == "token":
            return "检查上下文注入和记忆载荷，必要时压缩或拆分任务。"
        if scope == "efficiency":
            return "检查工具等待、循环次数、人工确认和重复执行。"
        return "继续监控并在风险升级时处理。"


