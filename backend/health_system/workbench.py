from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from project_layout import ProjectLayout
from health_system.maintenance.experiments.artifacts import read_json_file
from health_system.maintenance.test_system.harness_records import HarnessRecordStore
from health_system.evidence_extractor import build_turn_artifact_evidence_packet

from context_system.budget.presets import (
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
        test_governance = self._build_test_governance_projection()
        run_diagnostics = self._build_run_diagnostic_projection(failed_runs=failed_runs)
        efficiency = self._build_efficiency_summary(recent_runs=verification_runs)
        evidence_gaps = self._build_evidence_gaps(open_issues=open_issues)
        inbox_items = self._build_inbox_items(
            open_issues=open_issues,
            failed_runs=failed_runs,
            evidence_gaps=evidence_gaps,
            run_diagnostics=run_diagnostics,
        )
        diagnosis_inbox = self._build_diagnosis_inbox(
            inbox_items=inbox_items,
            evidence_gaps=evidence_gaps,
            run_diagnostics=run_diagnostics,
        )
        recovery_inbox = self._build_recovery_inbox(run_diagnostics=run_diagnostics)
        failure_chains = self._build_failure_chains(run_diagnostics=run_diagnostics)
        regression_sample_inbox = self._build_regression_sample_inbox(test_governance=test_governance)
        evidence_packets = [
            dict(item.get("evidence_packet") or {})
            for item in run_diagnostics.values()
            if isinstance(item.get("evidence_packet"), dict) and item.get("evidence_packet")
        ]
        evidence_packets.extend(
            dict(item.get("evidence_packet") or {})
            for item in list(test_governance.get("regression_samples") or [])
            if isinstance(item, dict) and isinstance(item.get("evidence_packet"), dict) and item.get("evidence_packet")
        )

        return {
            "authority": "health_system.workbench",
            "summary": {
                "inbox_count": len(inbox_items),
                "diagnosis_inbox_count": len(diagnosis_inbox),
                "recovery_inbox_count": len(recovery_inbox),
                "failure_chain_count": len(failure_chains),
                "regression_sample_inbox_count": len(regression_sample_inbox),
                "evidence_packet_count": len(evidence_packets),
                "open_issue_count": len(open_issues),
                "verification_resource_count": len(cases),
                "evidence_gap_count": len(evidence_gaps),
                "failed_run_count": len(failed_runs),
                "regression_sample_count": int(dict(test_governance.get("summary") or {}).get("regression_sample_count") or 0),
                "scenario_contract_count": int(dict(test_governance.get("summary") or {}).get("scenario_contract_count") or 0),
                "pending_regression_verification_count": int(dict(test_governance.get("summary") or {}).get("pending_verification_count") or 0),
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
            "diagnosis_inbox": diagnosis_inbox,
            "recovery_inbox": recovery_inbox,
            "failure_chains": failure_chains,
            "regression_sample_inbox": regression_sample_inbox,
            "test_governance": test_governance,
            "evidence_packets": evidence_packets,
            "evidence_gaps": evidence_gaps,
            "efficiency": efficiency,
            "context_budget": self._build_context_budget_summary(),
            "recommended_actions": self._recommended_actions(inbox_items=inbox_items, evidence_gaps=evidence_gaps),
            "source_refs": {
                "health_overview": str(health.get("authority") or "health_system.registry"),
                "verification_resources": str(verification_resources.get("authority") or "health_system.verification_resources"),
                "gate_projection": str(gate_projection.get("authority") or "health_system.gate_projection"),
                "test_governance": str(test_governance.get("authority") or "test_system.harness_records"),
            },
        }

    def _build_test_governance_projection(self) -> dict[str, Any]:
        layout = ProjectLayout.from_backend_dir(self.base_dir)
        store = HarnessRecordStore(layout.test_system_dir / "harness_records.json")
        book = store.load()
        samples = [item.to_dict() for item in book.regression_samples]
        scenario_contracts = [
            dict(sample.get("contract") or {})
            for sample in samples
            if isinstance(sample.get("contract"), dict)
        ]
        pending = [
            sample
            for sample in samples
            if str(dict(sample.get("verification") or {}).get("status") or "") in {"", "not_run", "planned", "running"}
        ]
        return {
            "authority": "health_system.workbench.test_governance_projection",
            "record_store_ref": str(store.path),
            "regression_samples": samples,
            "scenario_contracts": scenario_contracts,
            "summary": {
                "issue_count": len(book.issues),
                "case_draft_count": len(book.case_drafts),
                "managed_case_count": len(book.managed_cases),
                "regression_sample_count": len(samples),
                "scenario_contract_count": len(scenario_contracts),
                "pending_verification_count": len(pending),
                "active_regression_sample_count": sum(1 for sample in samples if str(sample.get("status") or "") == "active"),
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
        run_diagnostics: dict[str, dict[str, Any]],
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
            diagnostic = run_diagnostics.get(run_id) or {}
            stuck_diagnosis = dict(diagnostic.get("stuck_diagnosis") or {})
            items.append(
                {
                    "item_id": f"inbox:run:{run_id}",
                    "item_type": "verification.failed",
                    "title": str(summary.get("first_failure") or stuck_diagnosis.get("reason") or "最近验证失败"),
                    "subject_type": "verification_run",
                    "subject_id": run_id,
                    "subject_title": str(run.get("profile") or run_id),
                    "severity": "high",
                    "reason": _diagnostic_reason(diagnostic) or "验证运行存在失败项，需要转成问题报告，并在报告内完成链路复盘。",
                    "primary_action": "解释失败",
                    "secondary_actions": ["查看失败链路", "检查恢复点", "登记健康问题"],
                    "evidence_state": "packet" if diagnostic.get("evidence_packet") else "linked",
                    "created_at": float(run.get("started_at") or 0),
                    "metadata": {
                        "profile": str(run.get("profile") or ""),
                        "has_evidence_packet": bool(diagnostic.get("evidence_packet")),
                        "has_recovery_handles": bool(diagnostic.get("recovery_handles")),
                        "last_task_run_id": str(stuck_diagnosis.get("last_task_run_id") or ""),
                        "last_checkpoint_ref": str(stuck_diagnosis.get("last_checkpoint_ref") or ""),
                        "last_coordination_checkpoint_ref": str(stuck_diagnosis.get("last_coordination_checkpoint_ref") or ""),
                    },
                }
            )
        return sorted(items, key=_inbox_sort_key)

    def _build_run_diagnostic_projection(self, *, failed_runs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        diagnostics: dict[str, dict[str, Any]] = {}
        for run in failed_runs[:12]:
            run_id = str(run.get("verification_run_id") or run.get("source_run_ref") or run.get("run_id") or "")
            output_dir = Path(str(run.get("output_dir") or ""))
            if not run_id or not output_dir.exists():
                continue
            stuck_diagnosis = _read_dict(output_dir / "stuck_diagnosis.json")
            if not stuck_diagnosis:
                stuck_diagnosis = _stuck_diagnosis_from_artifacts(output_dir, run=run)
            evidence_packet = _read_dict(output_dir / "evidence_packet.json")
            if not evidence_packet:
                evidence_packet = dict(stuck_diagnosis.get("evidence_packet") or {})
            recovery_handles = [
                dict(item)
                for item in list(stuck_diagnosis.get("recovery_handles") or evidence_packet.get("recovery_handles") or [])
                if isinstance(item, dict)
            ]
            progress_events = _read_jsonl_dicts(output_dir / "progress.jsonl")
            diagnostics[run_id] = {
                "run_id": run_id,
                "source_run_ref": str(run.get("source_run_ref") or ""),
                "profile": str(run.get("profile_id") or run.get("profile") or ""),
                "status": str(run.get("status") or ""),
                "output_dir": str(output_dir),
                "summary": dict(run.get("summary") or {}),
                "stuck_diagnosis": stuck_diagnosis,
                "evidence_packet": evidence_packet,
                "recovery_handles": recovery_handles,
                "last_progress_event": dict(stuck_diagnosis.get("last_progress_event") or (progress_events[-1] if progress_events else {})),
                "artifact_manifest": _read_dict(output_dir / "artifact_manifest.json"),
            }
        return diagnostics

    def _build_diagnosis_inbox(
        self,
        *,
        inbox_items: list[dict[str, Any]],
        evidence_gaps: list[dict[str, Any]],
        run_diagnostics: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for item in inbox_items[:8]:
            items.append(
                {
                    "diagnosis_id": f"diagnosis:{item.get('item_id')}",
                    "subject_type": str(item.get("subject_type") or ""),
                    "subject_id": str(item.get("subject_id") or ""),
                    "title": str(item.get("title") or "待诊断对象"),
                    "priority": str(item.get("severity") or "medium"),
                    "question": _diagnosis_question(item),
                    "evidence_state": str(item.get("evidence_state") or "unknown"),
                    "recommended_agent_role": _diagnosis_agent_role(item),
                    "source_item_id": str(item.get("item_id") or ""),
                    "metadata": dict(item.get("metadata") or {}),
                }
            )
        for gap in evidence_gaps[:5]:
            items.append(
                {
                    "diagnosis_id": f"diagnosis:{gap.get('gap_id')}",
                    "subject_type": str(gap.get("subject_type") or ""),
                    "subject_id": str(gap.get("subject_id") or ""),
                    "title": str(gap.get("title") or "证据缺口"),
                    "priority": str(gap.get("severity") or "medium"),
                    "question": "这个问题缺少哪些最小证据，应该先绑定哪条运行链路或对话引用？",
                    "evidence_state": "missing",
                    "recommended_agent_role": "Trace Diagnostician",
                    "source_item_id": str(gap.get("gap_id") or ""),
                    "metadata": {},
                }
            )
        for diagnostic in run_diagnostics.values():
            if not diagnostic.get("evidence_packet"):
                continue
            packet = dict(diagnostic.get("evidence_packet") or {})
            items.append(
                {
                    "diagnosis_id": f"diagnosis:evidence-packet:{diagnostic.get('run_id')}",
                    "subject_type": "verification_run",
                    "subject_id": str(diagnostic.get("run_id") or ""),
                    "title": "失败运行已有证据包，等待健康 Agent 解释",
                    "priority": "high",
                    "question": str(packet.get("question") or "这次失败的关键证据说明了什么？"),
                    "evidence_state": "packet",
                    "recommended_agent_role": "Trace Diagnostician",
                    "source_item_id": f"inbox:run:{diagnostic.get('run_id')}",
                    "metadata": {
                        "packet_id": str(packet.get("packet_id") or ""),
                        "verdict": str(packet.get("verdict") or ""),
                        "confidence": packet.get("confidence"),
                    },
                }
            )
        return _dedupe_by_key(items, key="diagnosis_id")[:12]

    def _build_recovery_inbox(self, *, run_diagnostics: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for diagnostic in run_diagnostics.values():
            run_id = str(diagnostic.get("run_id") or "")
            for index, handle in enumerate(list(diagnostic.get("recovery_handles") or [])[:6], start=1):
                kind = str(handle.get("kind") or "")
                ref = str(handle.get("ref") or "")
                if not kind or not ref:
                    continue
                safe_to_resume = bool(handle.get("safe_to_resume") is True)
                items.append(
                    {
                        "recovery_id": f"recovery:{run_id}:{kind}:{index}",
                        "subject_type": "verification_run",
                        "subject_id": run_id,
                        "title": _recovery_title(kind),
                        "handle_kind": kind,
                        "handle_ref": ref,
                        "safe_to_resume": safe_to_resume,
                        "side_effect_replay_risk": str(handle.get("side_effect_replay_risk") or "unknown"),
                        "recommended_action": _recovery_action(kind, safe_to_resume=safe_to_resume),
                        "requires_runtime_control": True,
                        "metadata": dict(handle.get("metadata") or {}),
                    }
                )
        return items[:12]

    def _build_regression_sample_inbox(self, *, test_governance: dict[str, Any]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for sample in list(test_governance.get("regression_samples") or []):
            if not isinstance(sample, dict):
                continue
            verification = dict(sample.get("verification") or {})
            contract = dict(sample.get("contract") or {})
            verification_status = str(verification.get("status") or "not_run")
            sample_id = str(sample.get("sample_id") or "")
            items.append(
                {
                    "sample_id": sample_id,
                    "title": str(sample.get("title") or "未命名回归样本"),
                    "scenario_id": str(sample.get("scenario_id") or contract.get("scenario_id") or ""),
                    "turn_id": str(sample.get("source_turn_id") or contract.get("turn_id") or ""),
                    "session_alias": str(sample.get("session_alias") or contract.get("session_alias") or ""),
                    "status": str(sample.get("status") or "candidate"),
                    "verification_status": verification_status,
                    "failure_summary": str(sample.get("failure_summary") or ""),
                    "task_run_id": str(sample.get("task_run_id") or ""),
                    "problem_node_id": str(sample.get("problem_node_id") or ""),
                    "problem_node_label": str(sample.get("problem_node_label") or ""),
                    "evidence_state": "packet" if sample.get("evidence_packet") else "linked",
                    "rerun_command": list(sample.get("rerun_command") or []),
                    "contract_ref": str(contract.get("contract_id") or ""),
                    "source_run_id": str(sample.get("source_run_id") or ""),
                    "source_artifact_path": str(sample.get("source_artifact_path") or ""),
                    "recommended_action": _sample_recommended_action(verification_status),
                    "created_at": float(sample.get("created_at") or 0.0),
                    "metadata": {
                        "assertion_count": len(list(contract.get("assertions") or [])),
                        "expected_tools": list(contract.get("expected_tools") or []),
                        "verification_run_id": str(verification.get("run_id") or ""),
                    },
                    "authority": "health_system.workbench.regression_sample_inbox_item",
                }
            )
        return sorted(items, key=lambda item: (0 if item["verification_status"] in {"not_run", "planned"} else 1, -float(item.get("created_at") or 0)))[:12]

    def _build_failure_chains(self, *, run_diagnostics: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        chains: list[dict[str, Any]] = []
        for diagnostic in run_diagnostics.values():
            run_id = str(diagnostic.get("run_id") or "")
            stuck_diagnosis = dict(diagnostic.get("stuck_diagnosis") or {})
            packet = dict(diagnostic.get("evidence_packet") or {})
            selected = [dict(item) for item in list(packet.get("selected_evidence") or []) if isinstance(item, dict)]
            last_progress = dict(diagnostic.get("last_progress_event") or {})
            steps: list[dict[str, Any]] = []
            if last_progress:
                steps.append(
                    {
                        "step_id": f"{run_id}:progress",
                        "step_type": "harness_progress",
                        "title": str(last_progress.get("event_type") or "last_progress"),
                        "summary": str(last_progress.get("message") or last_progress.get("turn_ref") or last_progress.get("artifact_ref") or ""),
                        "source_ref": str(last_progress.get("artifact_ref") or last_progress.get("event_id") or ""),
                    }
                )
            for evidence in selected[:5]:
                steps.append(
                    {
                        "step_id": str(evidence.get("candidate_id") or ""),
                        "step_type": str(evidence.get("event_type") or evidence.get("source_kind") or "evidence"),
                        "title": str(evidence.get("event_type") or "关键证据"),
                        "summary": str(evidence.get("summary") or ""),
                        "source_ref": str(evidence.get("source_ref") or evidence.get("raw_ref") or ""),
                    }
                )
            if not steps and stuck_diagnosis:
                steps.append(
                    {
                        "step_id": f"{run_id}:stuck",
                        "step_type": "stuck_diagnosis",
                        "title": "stuck diagnosis",
                        "summary": str(stuck_diagnosis.get("reason") or "失败运行缺少更细证据，需要检查 artifact。"),
                        "source_ref": str(stuck_diagnosis.get("last_turn_artifact") or ""),
                    }
                )
            if not steps:
                continue
            chains.append(
                {
                    "chain_id": f"failure-chain:{run_id}",
                    "subject_type": "verification_run",
                    "subject_id": run_id,
                    "title": str(dict(diagnostic.get("summary") or {}).get("first_failure") or "验证失败链路"),
                    "status": str(diagnostic.get("status") or "failed"),
                    "root_cause_candidate": str(packet.get("summary") or stuck_diagnosis.get("reason") or ""),
                    "last_task_run_id": str(stuck_diagnosis.get("last_task_run_id") or ""),
                    "last_checkpoint_ref": str(stuck_diagnosis.get("last_checkpoint_ref") or ""),
                    "last_coordination_checkpoint_ref": str(stuck_diagnosis.get("last_coordination_checkpoint_ref") or ""),
                    "steps": steps,
                    "evidence_packet_ref": str(packet.get("packet_id") or ""),
                }
            )
        return chains[:8]

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


def _stuck_diagnosis_from_artifacts(output_dir: Path, *, run: dict[str, Any]) -> dict[str, Any]:
    harness_state = _read_dict(output_dir / "harness_state.json")
    progress_events = _read_jsonl_dicts(output_dir / "progress.jsonl")
    last_progress = progress_events[-1] if progress_events else {}
    evidence_packet = _read_dict(output_dir / "evidence_packet.json")
    last_turn_artifact = str(last_progress.get("artifact_ref") or "")
    if not last_turn_artifact:
        latest_turn = _latest_turn_artifact(output_dir)
        last_turn_artifact = str(latest_turn or "")
    if not evidence_packet and last_turn_artifact:
        try:
            evidence_packet = build_turn_artifact_evidence_packet(
                last_turn_artifact,
                question="失败或卡住前最后一个 turn 的关键运行证据是什么？",
            )
        except Exception:
            evidence_packet = {}
    return {
        "authority": "health_system.workbench.stuck_diagnosis_projection",
        "status": str(harness_state.get("status") or run.get("status") or "unknown"),
        "reason": str(harness_state.get("stale_reason") or dict(run.get("summary") or {}).get("first_failure") or ""),
        "last_progress_event": dict(last_progress),
        "last_turn_artifact": last_turn_artifact,
        "last_task_run_id": _task_run_id_from_turn_artifact(Path(last_turn_artifact)) if last_turn_artifact else "",
        "last_heartbeat_at": float(harness_state.get("heartbeat_at") or 0.0),
        "last_progress_at": float(harness_state.get("last_progress_at") or 0.0),
        "recovery_handles": list(evidence_packet.get("recovery_handles") or []),
        "last_checkpoint_ref": _first_recovery_ref(evidence_packet, kind="checkpoint"),
        "last_coordination_checkpoint_ref": _first_recovery_ref(evidence_packet, kind="coordination_checkpoint"),
        "evidence_packet": evidence_packet,
    }


def _latest_turn_artifact(output_dir: Path) -> Path | None:
    paths = [path for path in output_dir.glob("artifacts/**/turn-*.json") if path.is_file()]
    if not paths:
        return None
    return max(paths, key=lambda item: item.stat().st_mtime)


def _task_run_id_from_turn_artifact(path: Path) -> str:
    payload = read_json_file(path, {})
    if not isinstance(payload, dict):
        return ""
    result = dict(payload.get("result") or {})
    if result.get("task_run_id"):
        return str(result.get("task_run_id") or "")
    for item in list(payload.get("events") or []):
        if not isinstance(item, dict):
            continue
        if str(item.get("event") or "") == "runtime_loop_started":
            task_run = dict(dict(item.get("data") or {}).get("task_run") or {})
            if task_run.get("task_run_id"):
                return str(task_run.get("task_run_id") or "")
        if str(item.get("event") or "") == "runtime_loop_event":
            event = dict(dict(item.get("data") or {}).get("event") or {})
            if event.get("task_run_id"):
                return str(event.get("task_run_id") or "")
    return ""


def _read_dict(path: Path) -> dict[str, Any]:
    payload = read_json_file(path, {})
    return dict(payload) if isinstance(payload, dict) else {}


def _read_jsonl_dicts(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except Exception:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _first_recovery_ref(packet: dict[str, Any], *, kind: str) -> str:
    for item in list(packet.get("recovery_handles") or []):
        handle = dict(item or {})
        if str(handle.get("kind") or "") == kind and str(handle.get("ref") or "").strip():
            return str(handle.get("ref") or "")
    return ""


def _diagnostic_reason(diagnostic: dict[str, Any]) -> str:
    stuck = dict(diagnostic.get("stuck_diagnosis") or {})
    packet = dict(diagnostic.get("evidence_packet") or {})
    if packet.get("summary"):
        return str(packet.get("summary") or "")
    if stuck.get("reason"):
        return str(stuck.get("reason") or "")
    return ""


def _diagnosis_question(item: dict[str, Any]) -> str:
    subject_type = str(item.get("subject_type") or "")
    if subject_type == "verification_run":
        return "这次验证失败从哪个运行事件开始偏离，是否存在安全恢复点？"
    if str(item.get("evidence_state") or "") == "missing":
        return "这个问题缺少哪些最小证据，应该先补哪条事实引用？"
    return "这个健康问题的责任层、失败链路和下一步验证动作是什么？"


def _diagnosis_agent_role(item: dict[str, Any]) -> str:
    if str(item.get("subject_type") or "") == "verification_run":
        return "Trace Diagnostician"
    if str(item.get("evidence_state") or "") == "missing":
        return "Evidence Curator"
    return "Trace Diagnostician"


def _recovery_title(kind: str) -> str:
    if kind == "checkpoint":
        return "RuntimeLoop checkpoint 恢复候选"
    if kind == "coordination_checkpoint":
        return "TaskGraph coordination checkpoint 恢复候选"
    if kind == "task_graph_node_resume_candidate":
        return "任务图节点级恢复候选"
    if kind == "tool_result_boundary":
        return "工具结果边界，需防重复执行"
    return "恢复候选"


def _recovery_action(kind: str, *, safe_to_resume: bool) -> str:
    if kind == "tool_result_boundary":
        return "只作为副作用边界参考，不直接重放工具。"
    if safe_to_resume:
        return "提交给 runtime control 校验后再恢复，健康系统只提供候选点。"
    return "先由 Recovery Planner 判断副作用风险，再交由正式 runtime control 处理。"


def _sample_recommended_action(verification_status: str) -> str:
    if verification_status == "running":
        return "等待 harness 产物落盘后读取 run_result 和 evidence packet，不能提前裁决。"
    if verification_status in {"passed", "failed"}:
        return "读取复跑 run_result，将结论同步到问题报告或回归门禁。"
    if verification_status == "unsupported":
        return "先补齐 runner 能力或前缀上下文，再启动复跑。"
    return "通过 test-system regression-samples/{sample_id}/rerun 启动目标 turn 复跑。"


def _dedupe_by_key(items: list[dict[str, Any]], *, key: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        value = str(item.get(key) or "")
        if value in seen:
            continue
        seen.add(value)
        result.append(item)
    return result


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
