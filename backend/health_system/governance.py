from __future__ import annotations

import time
from typing import Any

from token_accounting import count_text_tokens


ACTIVE_STATUSES = {"created", "queued", "running", "waiting_approval", "paused"}
FAILED_STATUSES = {"failed", "aborted", "cancelled"}
WARNING_STATUSES = {"waiting_approval", "paused"}


class HealthGovernanceBuilder:
    def __init__(self, runtime: Any) -> None:
        self.runtime = runtime
        self.harness_service_host = runtime.query_runtime.harness_service_host
        self.state_index = self.harness_service_host.state_index
        self.now = time.time()

    def build_overview(self, *, limit: int = 80) -> dict[str, Any]:
        tasks = self.build_tasks(limit=limit)["tasks"]
        monitor = self._global_monitor(limit=limit)
        risks = self._risk_events(tasks=tasks, monitor=monitor)
        token_usage = self._token_usage(tasks)
        efficiency = self._efficiency(tasks)
        system_risks = self._system_risks(monitor=monitor)
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
        monitor = self.harness_service_host.get_task_run_live_monitor(task_run_id) or {}
        graph_monitor = self.harness_service_host.get_task_graph_run_monitor(task_run_id) or {}
        events = [item.to_dict() for item in self.harness_service_host.event_log.list_events(task_run_id)[-160:]]
        risks = self._task_risks(record, monitor=monitor, graph_monitor=graph_monitor)
        return {
            "authority": "health_system.governance.task_detail",
            "task": record,
            "monitor": monitor,
            "task_graph_monitor": graph_monitor,
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

    def build_token_usage(self, *, limit: int = 100) -> dict[str, Any]:
        return self._token_usage(self.build_tasks(limit=limit)["tasks"])

    def build_efficiency(self, *, limit: int = 100) -> dict[str, Any]:
        return self._efficiency(self.build_tasks(limit=limit)["tasks"])

    def _task_record(self, task_run: Any) -> dict[str, Any]:
        task_run_id = str(task_run.task_run_id or "")
        events = self.harness_service_host.event_log.list_events(task_run_id)
        event_dicts = [item.to_dict() for item in events]
        order_projection = self.state_index.task_order_projection_for_task_run(task_run_id) or {}
        order = dict(order_projection.get("task_order") or {})
        order_run = dict(order_projection.get("task_order_run") or {})
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
        token_total = self._session_token_total(str(task_run.session_id or ""))
        risk_level = self._risk_level(status=status, duration_seconds=duration, error_count=error_count)
        latest_risk = self._latest_task_risk_title(status=status, duration_seconds=duration, error_count=error_count)
        return {
            "task_run_id": task_run_id,
            "session_id": str(task_run.session_id or ""),
            "task_order_id": str(order.get("order_id") or order_run.get("order_id") or ""),
            "task_order_run_id": str(order_run.get("run_id") or ""),
            "title": str(order.get("objective") or task_run.task_id or task_run_id),
            "task_id": str(task_run.task_id or ""),
            "agent_id": str(task_run.agent_id or ""),
            "agent_profile_id": str(task_run.agent_profile_id or ""),
            "runtime_lane": str(task_run.runtime_lane or ""),
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
            "risk_level": risk_level,
            "latest_risk_event": latest_risk,
            "supervision_count": len(supervision_records),
            "latest_event_type": str(event_dicts[-1].get("event_type") if event_dicts else ""),
            "monitor_ref": f"runtime_monitor:{task_run_id}",
            "record_refs": {
                "task_run": task_run_id,
                "task_order": str(order.get("order_id") or ""),
                "task_order_run": str(order_run.get("run_id") or ""),
                "session": str(task_run.session_id or ""),
            },
        }

    def _global_monitor(self, *, limit: int) -> dict[str, Any]:
        try:
            return dict(self.harness_service_host.list_global_live_monitor(limit=limit) or {})
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
        return risks

    def _token_usage(self, tasks: list[dict[str, Any]]) -> dict[str, Any]:
        by_session: dict[str, dict[str, Any]] = {}
        for task in tasks:
            session_id = str(task.get("session_id") or "")
            if not session_id:
                continue
            current = by_session.setdefault(session_id, {"session_id": session_id, "total_tokens": 0, "task_count": 0, "max_task_tokens": 0})
            tokens = int(task.get("token_total") or 0)
            current["total_tokens"] = max(int(current["total_tokens"]), tokens)
            current["max_task_tokens"] = max(int(current["max_task_tokens"]), tokens)
            current["task_count"] = int(current["task_count"]) + 1
        rows = sorted(by_session.values(), key=lambda item: int(item.get("total_tokens") or 0), reverse=True)
        total = sum(int(item.get("total_tokens") or 0) for item in rows)
        daily = self._token_buckets(tasks, bucket_seconds=86400, bucket_count=7, label_mode="day")
        six_hour = self._token_buckets(tasks, bucket_seconds=21600, bucket_count=4, label_mode="hour")
        return {
            "authority": "health_system.governance.token_usage",
            "summary": {
                "session_count": len(rows),
                "total_tokens": total,
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
                        "risk_level": task["risk_level"],
                    }
                    for task in tasks
                ],
                key=lambda item: int(item.get("token_total") or 0),
                reverse=True,
            )[:80],
            "daily": daily,
            "six_hour": six_hour,
            "note": "读取任务记录和会话历史 token 估算；折线图按任务更新时间聚合。",
            "updated_at": self.now,
        }

    def _token_buckets(self, tasks: list[dict[str, Any]], *, bucket_seconds: int, bucket_count: int, label_mode: str) -> list[dict[str, Any]]:
        now_bucket = int(self.now // bucket_seconds) * bucket_seconds
        starts = [now_bucket - bucket_seconds * index for index in range(bucket_count - 1, -1, -1)]
        buckets: list[dict[str, Any]] = []
        for start in starts:
            end = start + bucket_seconds
            tokens = 0
            records = 0
            sessions: set[str] = set()
            for task in tasks:
                updated_at = float(task.get("updated_at") or task.get("created_at") or 0)
                if start <= updated_at < end:
                    tokens += int(task.get("token_total") or 0)
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

    def _session_token_total(self, session_id: str) -> int:
        if not session_id:
            return 0
        try:
            record = self.runtime.session_manager.get_history(session_id)
            messages = []
            for item in list(record.get("messages") or []):
                messages.append(str(item.get("content") or ""))
                for tool_call in item.get("tool_calls", []) or []:
                    messages.append(str(tool_call))
            return count_text_tokens("\n".join(messages))
        except Exception:
            return 0

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
