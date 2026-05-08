from __future__ import annotations

import time
from dataclasses import replace
from typing import Any

from .constants import HEALTH_SESSION_ID
from .models import HealthManagementCommand, HealthTestRun
from .runtime_admission import admit_health_command


class HealthCommandService:
    def __init__(self, registry: Any) -> None:
        self.registry = registry

    async def submit_command(
        self,
        payload: dict[str, Any],
        *,
        task_run_loop: Any | None = None,
        model_response_executor: Any | None = None,
        test_system_service: Any | None = None,
    ) -> dict[str, Any]:
        command = self.registry.command_builder.build_command(payload)
        self.registry.store.upsert_command(command)
        try:
            return await self.handle_command(
                command,
                task_run_loop=task_run_loop,
                model_response_executor=model_response_executor,
                test_system_service=test_system_service,
            )
        except Exception as exc:
            receipt = self.registry.command_builder.build_receipt(
                command=command,
                accepted=False,
                status="failed",
                admission_status="accepted",
                run_status="failed",
                blocked_reasons=(exc.__class__.__name__,),
                diagnostics={"error": str(exc)},
            )
            self.registry.store.append_receipt(receipt)
            failed = replace(command, status="failed", updated_at=time.time())
            self.registry.store.upsert_command(failed)
            return {
                "authority": "health_system.management_command",
                "command": failed.to_dict(),
                "receipt": receipt.to_dict(),
            }

    async def handle_command(
        self,
        command: HealthManagementCommand,
        *,
        task_run_loop: Any | None,
        model_response_executor: Any | None,
        test_system_service: Any | None,
    ) -> dict[str, Any]:
        if command.command_type == "report_issue":
            issue_payload = {**command.payload}
            if command.target_ref and "conversation_ref" not in issue_payload:
                issue_payload["conversation_ref"] = command.target_ref if command.target_scope == "conversation" else ""
            issue = self.registry.create_issue(
                {
                    "title": issue_payload.get("title") or command.payload.get("summary") or "健康系统登记问题",
                    "owner_system": issue_payload.get("owner_system") or "unknown",
                    "severity": issue_payload.get("severity") or "medium",
                    "status": issue_payload.get("status") or "triage_ready",
                    "source": command.source or "health_management_command",
                    "conversation_ref": issue_payload.get("conversation_ref") or "",
                    "runtime_trace_refs": issue_payload.get("runtime_trace_refs") or [],
                    "prompt_manifest_refs": issue_payload.get("prompt_manifest_refs") or [],
                    "memory_refs": issue_payload.get("memory_refs") or [],
                    "assertion_refs": issue_payload.get("assertion_refs") or [],
                    "metadata": {
                        **dict(issue_payload.get("metadata") or {}),
                        "command_ref": command.command_id,
                        "initiator_type": command.initiator_type,
                        "initiator_ref": command.initiator_ref,
                    },
                }
            )
            report = self.registry.command_builder.build_report(
                command=command,
                report_type="issue_intake_report",
                issue_ref=issue.issue_id,
                evidence_refs=(issue.conversation_ref, *issue.runtime_trace_refs),
                verdict="accepted",
                severity=issue.severity,
                summary=f"已登记健康问题：{issue.title}",
                recommended_actions=("analyze_trace",),
            )
            self.registry.store.append_report(report)
            receipt = self.registry.command_builder.build_receipt(
                command=command,
                accepted=True,
                status="completed",
                health_issue_ref=issue.issue_id,
                report_ref=report.report_id,
                diagnostics={"issue": issue.to_dict()},
            )
            return self.registry._complete_command(command, receipt=receipt, report=report, issue=issue)

        if command.command_type in {"analyze_trace", "draft_case", "verify_fix"}:
            admission = admit_health_command(self.registry.base_dir, command)
            if admission.status != "accepted":
                receipt = self.registry.command_builder.build_receipt(
                    command=command,
                    accepted=False,
                    status=admission.status,
                    admission_status=admission.status,
                    blocked_reasons=admission.blocked_reasons,
                    diagnostics={"admission": admission.to_dict()},
                )
                return self.registry._complete_command(command, receipt=receipt)
            if task_run_loop is None or model_response_executor is None:
                receipt = self.registry.command_builder.build_receipt(
                    command=command,
                    accepted=False,
                    status="rejected",
                    admission_status="rejected",
                    blocked_reasons=("runtime_dependency_missing",),
                    diagnostics={"admission": admission.to_dict()},
                )
                return self.registry._complete_command(command, receipt=receipt)
            issue_id = command.target_ref
            if command.target_scope and command.target_scope not in {"health_issue", "issue"}:
                issue_id = str(command.payload.get("issue_id") or "")
            if not issue_id:
                receipt = self.registry.command_builder.build_receipt(
                    command=command,
                    accepted=False,
                    status="rejected",
                    admission_status="rejected",
                    blocked_reasons=("health_issue_ref_missing",),
                    diagnostics={"admission": admission.to_dict()},
                )
                return self.registry._complete_command(command, receipt=receipt)
            run_result = await self.registry.execute_agent_run(
                issue_id=issue_id,
                task_mode=admission.task_mode,
                session_id=command.conversation_session_ref or HEALTH_SESSION_ID,
                source=command.source or "health_management_command",
                task_run_loop=task_run_loop,
                model_response_executor=model_response_executor,
            )
            health_run = dict(run_result.get("health_agent_run") or {})
            report = self.registry.command_builder.build_report(
                command=command,
                report_type=f"{command.command_type}_report",
                issue_ref=issue_id,
                agent_run_ref=str(health_run.get("run_id") or ""),
                evidence_refs=(
                    str(health_run.get("task_run_id") or ""),
                    str(health_run.get("result_ref") or ""),
                    admission.binding_id,
                    admission.resource_policy_ref,
                ),
                verdict=str(run_result.get("status") or "unknown"),
                severity=str(dict(run_result.get("issue") or {}).get("severity") or "medium"),
                summary=f"健康管理 agent 已执行 {command.command_type}，状态：{run_result.get('status') or 'unknown'}",
                recommended_actions=("review_report", "follow_receipt"),
            )
            self.registry.store.append_report(report)
            receipt = self.registry.command_builder.build_receipt(
                command=command,
                accepted=str(run_result.get("status") or "") == "completed",
                status=str(run_result.get("status") or "unknown"),
                health_issue_ref=issue_id,
                health_run_ref=str(health_run.get("run_id") or ""),
                report_ref=report.report_id,
                admission_status=admission.status,
                run_status=str(run_result.get("status") or "unknown"),
                diagnostics={"admission": admission.to_dict(), "run": run_result},
            )
            return self.registry._complete_command(command, receipt=receipt, report=report, run_result=run_result)

        if command.command_type == "launch_health_test":
            if test_system_service is None:
                receipt = self.registry.command_builder.build_receipt(
                    command=command,
                    accepted=False,
                    status="rejected",
                    admission_status="rejected",
                    blocked_reasons=("test_system_service_missing",),
                )
                return self.registry._complete_command(command, receipt=receipt)
            profile = str(command.payload.get("profile") or "functional")
            scenario_refs = tuple(str(item) for item in list(command.payload.get("scenario_refs") or command.payload.get("scenario_ids") or []))
            test_run = test_system_service.start(profile, scenario_ids=list(scenario_refs))
            health_test_run = HealthTestRun(
                health_test_run_id=f"health-test-run:{test_run.get('run_id') or int(time.time() * 1000)}",
                command_ref=command.command_id,
                test_system_run_ref=str(test_run.get("run_id") or ""),
                profile=profile,
                scenario_refs=scenario_refs,
                status=str(test_run.get("status") or "unknown"),
                verdict=_verdict_from_status(str(test_run.get("status") or "")),
                artifact_refs=(str(test_run.get("output_dir") or ""), str(test_run.get("log_path") or "")),
                started_at=float(test_run.get("started_at") or time.time()),
                finished_at=float(test_run.get("ended_at") or 0.0),
            )
            self.registry.store.upsert_health_test_run(health_test_run)
            verification_run = self.registry.verification_service.record_verification_run(
                test_run,
                command_ref=command.command_id,
            )
            report = self.registry.command_builder.build_report(
                command=command,
                report_type="health_test_run_report",
                test_run_ref=verification_run.source_run_ref,
                evidence_refs=verification_run.artifact_refs,
                verdict=health_test_run.verdict,
                summary=f"健康验证已启动：{profile}",
                recommended_actions=("inspect_test_artifacts", "review_health_readiness"),
            )
            self.registry.store.append_report(report)
            health_test_run = replace(health_test_run, report_refs=(report.report_id,))
            self.registry.store.upsert_health_test_run(health_test_run)
            receipt = self.registry.command_builder.build_receipt(
                command=command,
                accepted=True,
                status=health_test_run.status,
                test_run_ref=health_test_run.test_system_run_ref,
                verification_run_ref=verification_run.verification_run_id,
                report_ref=report.report_id,
                admission_status="accepted",
                run_status=health_test_run.status,
                diagnostics={"health_test_run": health_test_run.to_dict(), "test_run": test_run},
            )
            return self.registry._complete_command(command, receipt=receipt, report=report, health_test_run=health_test_run)

        if command.command_type == "build_cutover_readiness":
            gate_projection = self.registry.verification_service.build_gate_projection()
            report = self.registry.command_builder.build_report(
                command=command,
                report_type="cutover_readiness_report",
                evidence_refs=tuple(str(item.get("gate_decision_id") or "") for item in list(gate_projection.get("decisions") or []) if str(item.get("gate_decision_id") or "")),
                verdict="ready_with_review" if int(dict(gate_projection.get("summary") or {}).get("failing_profile_count") or 0) == 0 else "insufficient_evidence",
                severity="medium",
                summary="已生成健康系统切流准备度报告草案。",
                recommended_actions=("review_recent_reports", "run_required_health_scenarios"),
            )
            self.registry.store.append_report(report)
            receipt = self.registry.command_builder.build_receipt(command=command, accepted=True, status="completed", report_ref=report.report_id)
            return self.registry._complete_command(command, receipt=receipt, report=report)

        receipt = self.registry.command_builder.build_receipt(
            command=command,
            accepted=False,
            status="rejected",
            admission_status="rejected",
            blocked_reasons=("unsupported_command_type",),
            diagnostics={"command_type": command.command_type},
        )
        return self.registry._complete_command(command, receipt=receipt)


def _verdict_from_status(status: str) -> str:
    normalized = status.lower()
    if normalized in {"passed", "completed", "success"}:
        return "passed"
    if normalized in {"failed", "blocked", "cancelled"}:
        return "failed"
    if normalized in {"running", "queued"}:
        return "pending"
    return "unknown"
