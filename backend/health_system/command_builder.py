from __future__ import annotations

import time
from dataclasses import replace
from typing import Any

from .models import (
    HealthIssue,
    HealthManagementCommand,
    HealthManagementReceipt,
    HealthReport,
    HealthTestRun,
)


class HealthCommandBuilder:
    def build_command(self, payload: dict[str, Any]) -> HealthManagementCommand:
        now = time.time()
        command_type = str(payload.get("command_type") or "").strip()
        if not command_type:
            raise ValueError("HealthManagementCommand requires command_type")
        return HealthManagementCommand(
            command_id=str(payload.get("command_id") or "").strip() or f"health-command:{int(now * 1000)}",
            command_type=command_type,
            initiator_type=str(payload.get("initiator_type") or "user"),
            initiator_ref=str(payload.get("initiator_ref") or ""),
            requested_by=str(payload.get("requested_by") or ""),
            source=str(payload.get("source") or "health_system.command_api"),
            conversation_session_ref=str(payload.get("conversation_session_ref") or ""),
            target_scope=str(payload.get("target_scope") or ""),
            target_ref=str(payload.get("target_ref") or ""),
            task_mode=str(payload.get("task_mode") or ""),
            payload=dict(payload.get("payload") or {}),
            status=str(payload.get("status") or "pending"),
            created_at=now,
            updated_at=now,
        )

    def build_receipt(
        self,
        *,
        command: HealthManagementCommand,
        accepted: bool,
        status: str,
        health_issue_ref: str = "",
        health_run_ref: str = "",
        test_run_ref: str = "",
        report_ref: str = "",
        blocked_reasons: tuple[str, ...] = (),
        diagnostics: dict[str, Any] | None = None,
    ) -> HealthManagementReceipt:
        now = time.time()
        return HealthManagementReceipt(
            receipt_id=f"health-receipt:{command.command_id}:{int(now * 1000)}",
            command_ref=command.command_id,
            accepted=accepted,
            status=status,
            health_issue_ref=health_issue_ref,
            health_run_ref=health_run_ref,
            test_run_ref=test_run_ref,
            report_ref=report_ref,
            blocked_reasons=blocked_reasons,
            diagnostics=dict(diagnostics or {}),
            created_at=now,
        )

    def build_report(
        self,
        *,
        command: HealthManagementCommand,
        report_type: str,
        issue_ref: str = "",
        agent_run_ref: str = "",
        test_run_ref: str = "",
        evidence_refs: tuple[str, ...] = (),
        verdict: str = "unknown",
        severity: str = "medium",
        summary: str = "",
        recommended_actions: tuple[str, ...] = (),
    ) -> HealthReport:
        now = time.time()
        return HealthReport(
            report_id=f"health-report:{command.command_id}:{int(now * 1000)}",
            report_type=report_type,
            issue_ref=issue_ref,
            command_ref=command.command_id,
            agent_run_ref=agent_run_ref,
            test_run_ref=test_run_ref,
            evidence_refs=tuple(item for item in evidence_refs if item),
            verdict=verdict,
            severity=severity,
            summary=summary,
            recommended_actions=recommended_actions,
            created_at=now,
        )

    def complete_command(
        self,
        command: HealthManagementCommand,
        *,
        receipt: HealthManagementReceipt,
        report: HealthReport | None = None,
        issue: HealthIssue | None = None,
        run_result: dict[str, Any] | None = None,
        health_test_run: HealthTestRun | None = None,
    ) -> tuple[HealthManagementCommand, dict[str, Any]]:
        status = "completed" if receipt.accepted else receipt.status
        updated = replace(command, status=status, updated_at=time.time())
        response: dict[str, Any] = {
            "authority": "health_system.management_command",
            "command": updated.to_dict(),
            "receipt": receipt.to_dict(),
        }
        if report is not None:
            response["report"] = report.to_dict()
        if issue is not None:
            response["issue"] = issue.to_dict()
        if run_result is not None:
            response["run_result"] = run_result
        if health_test_run is not None:
            response["health_test_run"] = health_test_run.to_dict()
        return updated, response
