from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from project_layout import ProjectLayout

from context_management.budget_presets import (
    get_context_budget_preset,
    list_context_budget_presets,
)

from .registry import HealthRegistry


CLOSED_ISSUE_STATES = {"resolved", "closed", "done"}


class HealthWorkbenchBuilder:
    """Build the user-task projection for the health workbench."""

    def __init__(self, base_dir: Path, settings_service: Any | None = None) -> None:
        self.base_dir = Path(base_dir)
        self.settings_service = settings_service

    def build_overview(self) -> dict[str, Any]:
        registry = HealthRegistry(self.base_dir)
        health = registry.build_overview()

        issues = [dict(item) for item in list(health.get("issues") or [])]
        verification_runs = [dict(item) for item in list(health.get("verification_runs") or [])]
        gate_projection = dict(health.get("gate_projection") or {})
        verification_resources = registry.verification_service.build_verification_resource_catalog()
        cases = [dict(item) for item in list(verification_resources.get("cases") or [])]
        features = [dict(item) for item in list(gate_projection.get("decisions") or [])]
        open_issues = [item for item in issues if str(item.get("status") or "").lower() not in CLOSED_ISSUE_STATES]
        failed_runs = [item for item in verification_runs if _verification_run_failed(item)]
        efficiency = self._build_efficiency_summary(recent_runs=verification_runs)
        evidence_gaps = self._build_evidence_gaps(open_issues=open_issues)
        inbox_items = self._build_inbox_items(
            open_issues=open_issues,
            failed_runs=failed_runs,
            evidence_gaps=evidence_gaps,
        )

        return {
            "authority": "health_system.workbench",
            "summary": {
                "inbox_count": len(inbox_items),
                "open_issue_count": len(open_issues),
                "verification_resource_count": len(cases),
                "evidence_gap_count": len(evidence_gaps),
                "failed_run_count": len(failed_runs),
                "slow_run_count": int(efficiency["latency"].get("slow_run_count") or 0),
                "efficiency_alert_count": len(efficiency["signals"]),
                "feature_count": len(features),
                "active_case_count": int(dict(verification_resources.get("summary") or {}).get("case_count") or 0),
            },
            "inbox_items": inbox_items,
            "selected_context": inbox_items[0] if inbox_items else {},
            "features": features,
            "verification_resources": cases,
            "recent_runs": verification_runs,
            "evidence_gaps": evidence_gaps,
            "efficiency": efficiency,
            "context_budget": self._build_context_budget_summary(),
            "recommended_actions": self._recommended_actions(inbox_items=inbox_items, evidence_gaps=evidence_gaps),
            "source_refs": {
                "health_overview": str(health.get("authority") or "health_system.registry"),
                "verification_resources": str(verification_resources.get("authority") or "health_system.verification_resources"),
                "gate_projection": str(gate_projection.get("authority") or "health_system.gate_projection"),
            },
        }

    def _build_context_budget_summary(self) -> dict[str, Any]:
        if self.settings_service is not None and hasattr(self.settings_service, "context_budget_payload"):
            return dict(self.settings_service.context_budget_payload())
        preset = get_context_budget_preset("deepseek_1m")
        return {
            "active_preset": preset.to_dict(),
            "preset_id": preset.preset_id,
            "presets": list_context_budget_presets(),
            "authority": "runtime.context_budget_presets",
        }

    def _build_evidence_gaps(
        self,
        *,
        open_issues: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        gaps: list[dict[str, Any]] = []
        for issue in open_issues:
            has_runtime = bool(issue.get("runtime_trace_refs"))
            has_conversation = bool(str(issue.get("conversation_ref") or "").strip())
            if not has_runtime and not has_conversation:
                gaps.append(
                    {
                        "gap_id": f"gap:issue:evidence:{issue.get('issue_id')}",
                        "subject_type": "health_issue",
                        "subject_id": str(issue.get("issue_id") or ""),
                        "title": "问题缺少可复盘证据",
                        "detail": "需要绑定对话引用或运行链路引用，健康子 Agent 才能定位问题。",
                        "severity": str(issue.get("severity") or "medium"),
                    }
                )
        return gaps

    def _build_inbox_items(
        self,
        *,
        open_issues: list[dict[str, Any]],
        failed_runs: list[dict[str, Any]],
        evidence_gaps: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        gap_subject_ids = {str(item.get("subject_id") or "") for item in evidence_gaps}
        for issue in open_issues:
            issue_id = str(issue.get("issue_id") or "")
            items.append(
                {
                    "item_id": f"inbox:issue:{issue_id}",
                    "item_type": "issue.needs_triage",
                    "title": str(issue.get("title") or "待分析健康问题"),
                    "subject_type": "health_issue",
                    "subject_id": issue_id,
                    "subject_title": str(issue.get("title") or issue_id),
                    "severity": str(issue.get("severity") or "medium"),
                    "reason": "开放问题需要确认问题类型、责任层、链路节点和下一步处理动作。",
                    "primary_action": "定位问题",
                    "secondary_actions": ["查看问题报告", "分析链路"],
                    "evidence_state": "missing" if issue_id in gap_subject_ids else "linked",
                    "created_at": float(issue.get("created_at") or 0),
                    "metadata": {"owner_system": str(issue.get("owner_system") or "")},
                }
            )
        for run in failed_runs:
            run_id = str(run.get("verification_run_id") or run.get("source_run_ref") or run.get("run_id") or "")
            summary = dict(run.get("summary") or {})
            items.append(
                {
                    "item_id": f"inbox:run:{run_id}",
                    "item_type": "verification.failed",
                    "title": str(summary.get("first_failure") or "最近验证失败"),
                    "subject_type": "verification_run",
                    "subject_id": run_id,
                    "subject_title": str(run.get("profile") or run_id),
                    "severity": "high",
                    "reason": "验证运行存在失败项，需要转成问题报告，并在报告内完成链路复盘。",
                    "primary_action": "解释失败",
                    "secondary_actions": ["生成问题报告", "登记健康问题"],
                    "evidence_state": "linked",
                    "created_at": float(run.get("started_at") or 0),
                    "metadata": {"profile": str(run.get("profile") or "")},
                }
            )
        return sorted(items, key=_inbox_sort_key)

    def _build_efficiency_summary(self, *, recent_runs: list[dict[str, Any]]) -> dict[str, Any]:
        durations = [float(item.get("duration_ms") or 0) for item in recent_runs if float(item.get("duration_ms") or 0) > 0]
        slow_threshold_ms = 180_000.0
        slow_runs = [item for item in recent_runs if float(item.get("duration_ms") or 0) >= slow_threshold_ms]
        signals: list[dict[str, Any]] = []
        for run in slow_runs[:5]:
            signals.append(
                {
                    "signal_id": f"efficiency:slow-run:{run.get('run_id')}",
                    "signal_type": "latency.slow_verification_run",
                    "subject_type": "verification_run",
                    "subject_id": str(run.get("run_id") or ""),
                    "title": "验证链路耗时偏高",
                    "detail": f"{run.get('profile') or 'unknown'} 最近耗时 {round(float(run.get('duration_ms') or 0) / 1000, 1)}s。",
                    "severity": "medium",
                    "metric": "duration_ms",
                    "value": float(run.get("duration_ms") or 0),
                    "threshold": slow_threshold_ms,
                }
            )
        token_health = self._build_token_usage_summary()
        return {
            "authority": "health_system.efficiency_projection",
            "latency": {
                "run_count": len(durations),
                "average_duration_ms": round(sum(durations) / len(durations), 2) if durations else 0,
                "max_duration_ms": round(max(durations), 2) if durations else 0,
                "slow_threshold_ms": slow_threshold_ms,
                "slow_run_count": len(slow_runs),
            },
            "tokens": token_health,
            "signals": signals,
        }

    def _build_token_usage_summary(self) -> dict[str, Any]:
        checkpoints_dir = ProjectLayout.from_backend_dir(self.base_dir).runtime_state_dir / "checkpoints"
        now = time.time()
        today = datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0)
        daily_start = today - timedelta(days=6)
        current_six_hour = datetime.fromtimestamp(now).replace(minute=0, second=0, microsecond=0)
        current_six_hour = current_six_hour.replace(hour=(current_six_hour.hour // 6) * 6)
        six_hour_start = current_six_hour - timedelta(hours=18)
        daily_buckets = {
            (daily_start + timedelta(days=index)).strftime("%Y-%m-%d"): {
                "bucket": (daily_start + timedelta(days=index)).strftime("%Y-%m-%d"),
                "tokens": 0,
                "records": 0,
                "sessions": 0,
            }
            for index in range(7)
        }
        six_hour_buckets: dict[str, dict[str, Any]] = {}
        for index in range(4):
            bucket_start = six_hour_start + timedelta(hours=index * 6)
            label = bucket_start.strftime("%m-%d %H:00")
            six_hour_buckets[label] = {"bucket": label, "tokens": 0, "records": 0, "sessions": 0}

        total_tokens = 0
        record_count = 0
        run_ids: set[str] = set()
        if checkpoints_dir.exists():
            for path in checkpoints_dir.glob("*.json"):
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                accounting = _runtime_token_accounting(payload)
                token_count = _runtime_accounted_tokens(accounting)
                if not accounting:
                    continue
                updated_at = _checkpoint_timestamp(payload, path)
                total_tokens += token_count
                record_count += 1
                task_run_id = str(payload.get("task_run_id") or dict(payload.get("loop_state") or {}).get("task_run_id") or "")
                if task_run_id:
                    run_ids.add(task_run_id)
                stamp = datetime.fromtimestamp(updated_at)
                day_key = stamp.strftime("%Y-%m-%d")
                if day_key in daily_buckets:
                    daily_buckets[day_key]["tokens"] += token_count
                    daily_buckets[day_key]["records"] += 1
                    daily_buckets[day_key]["sessions"] += 1
                bucket_hour = (stamp.hour // 6) * 6
                six_key = stamp.replace(hour=bucket_hour, minute=0, second=0, microsecond=0).strftime("%m-%d %H:00")
                if six_key in six_hour_buckets:
                    six_hour_buckets[six_key]["tokens"] += token_count
                    six_hour_buckets[six_key]["records"] += 1
                    six_hour_buckets[six_key]["sessions"] += 1

        return {
            "status": "recorded_from_runtime_accounting",
            "source": "storage.runtime_state.checkpoints.token_pressure.token_accounting",
            "granularity": ["daily", "six_hour"],
            "total_tokens": total_tokens,
            "session_count": record_count,
            "record_count": record_count,
            "task_run_count": len(run_ids),
            "daily": list(daily_buckets.values()),
            "six_hour": list(six_hour_buckets.values()),
            "note": "读取运行时 checkpoint 的 token_accounting；不再按会话文本长度估算。",
        }

    def _recommended_actions(
        self,
        *,
        inbox_items: list[dict[str, Any]],
        evidence_gaps: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        actions: list[dict[str, Any]] = []
        if evidence_gaps:
            actions.append(
                {
                    "action_id": "action:bind-missing-evidence",
                    "title": "先补齐缺失证据",
                    "detail": "缺少证据的对象会阻断问题定位，优先把对话、运行链路或测试文件并入问题报告。",
                    "target_page": "issues",
                }
            )
        if any(item.get("subject_type") == "health_issue" for item in inbox_items):
            actions.append(
                {
                    "action_id": "action:triage-health-issue",
                    "title": "分析当前健康问题",
                    "detail": "对已有证据的问题运行健康子 Agent，生成问题报告后再人工复核。",
                    "target_page": "issues",
                }
            )
        if any(item.get("subject_type") == "verification_run" for item in inbox_items):
            actions.append(
                {
                    "action_id": "action:review-failed-run",
                    "title": "复盘失败验证",
                    "detail": "从失败运行生成问题报告，把失败轮次转成可追踪问题。",
                    "target_page": "issues",
                }
            )
        if not actions:
            actions.append(
                {
                    "action_id": "action:keep-watch",
                    "title": "保持健康巡检",
                    "detail": "当前没有高优先级阻塞项，可运行快速门禁或在验证中心维护验证资源。",
                    "target_page": "verify",
                }
            )
        return actions[:3]


def _verification_run_failed(run: dict[str, Any]) -> bool:
    verdict = str(run.get("verdict") or "").lower()
    status = str(run.get("status") or "").lower()
    summary = dict(run.get("summary") or {})
    return verdict == "failed" or status == "failed" or int(summary.get("failed") or 0) > 0


def _runtime_token_accounting(payload: dict[str, Any]) -> dict[str, Any]:
    loop_state = dict(payload.get("loop_state") or {})
    token_pressure = dict(loop_state.get("token_pressure") or {})
    accounting = token_pressure.get("token_accounting")
    return dict(accounting) if isinstance(accounting, dict) else {}


def _runtime_accounted_tokens(accounting: dict[str, Any]) -> int:
    prompt_completion = _number(accounting.get("prompt_tokens")) + _number(accounting.get("completion_tokens"))
    if prompt_completion > 0:
        return prompt_completion
    for key in ("total_tokens", "total_token_count", "estimated_tokens_after"):
        value = _number(accounting.get(key))
        if value > 0:
            return value
    input_output = _number(accounting.get("input_tokens")) + _number(accounting.get("output_tokens"))
    if input_output > 0:
        return input_output
    included = _number(accounting.get("candidate_tokens_included"))
    dropped = _number(accounting.get("candidate_tokens_dropped"))
    if included or dropped:
        return included + dropped
    available = _number(accounting.get("available_context"))
    remaining = _number(accounting.get("remaining_context"))
    if available and remaining <= available:
        return max(0, available - remaining)
    return 0


def _checkpoint_timestamp(payload: dict[str, Any], path: Path) -> float:
    for key in ("updated_at", "created_at"):
        value = _number(payload.get(key))
        if value > 0:
            return float(value)
    loop_state = dict(payload.get("loop_state") or {})
    for key in ("updated_at", "created_at"):
        value = _number(loop_state.get(key))
        if value > 0:
            return float(value)
    return float(path.stat().st_mtime)


def _number(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _inbox_sort_key(item: dict[str, Any]) -> tuple[int, float]:
    severity = str(item.get("severity") or "").lower()
    priority = {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(severity, 4)
    created_at = float(item.get("created_at") or 0)
    return (priority, -created_at)
