from __future__ import annotations

import json
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from orchestration import RuntimeDirective, RuntimeLoopState, build_task_run_final_commit_decision
from operations import ResourceDecision, ResourcePolicy
from soul.projection_instances import ProjectionInstanceRegistry
from skill_system import SkillWorkflowRegistry
from tasks.flow_registry import TaskFlowRegistry

from .models import (
    HealthAgentConversationMessage,
    HealthAgentConversationSession,
    HealthAgentRun,
    HealthIssue,
    HealthManagementCommand,
    HealthManagementReceipt,
    HealthReport,
    HealthTestRun,
    ProblemNode,
)
from .runtime_admission import admit_health_command
from .test_catalog import default_health_test_scenarios


def default_health_issues(now: float | None = None) -> tuple[HealthIssue, ...]:
    timestamp = time.time() if now is None else now
    return (
        HealthIssue(
            issue_id="health:issue:sample-task-system-chain",
            title="任务系统链路权限样例问题",
            owner_system="task_system",
            severity="medium",
            status="triage_ready",
            source="system_bootstrap",
            conversation_ref="sample:conversation:task-system",
            runtime_trace_refs=("runtime-loop:sample",),
            prompt_manifest_refs=("prompt-manifest:sample",),
            memory_refs=("memory-runtime-view:sample",),
            assertion_refs=("assertion:sample",),
            created_at=timestamp,
            updated_at=timestamp,
            metadata={"sample": True},
        ),
    )


def default_problem_nodes() -> tuple[ProblemNode, ...]:
    return (
        ProblemNode(
            node_id="problem-node:sample:task-binding",
            issue_id="health:issue:sample-task-system-chain",
            system="task_system",
            stage="TaskAgentBinding",
            evidence_refs=("binding:flow.health.issue_triage:agent:health:maintainer",),
            diagnosis="样例节点：用于验证任务系统能展示绑定、权限和投影链路。",
            confidence=0.8,
            suggested_action="检查 AgentCapabilityProfile 与任务流绑定是否一致。",
        ),
    )


def default_health_agent_runs(now: float | None = None) -> tuple[HealthAgentRun, ...]:
    timestamp = time.time() if now is None else now
    return (
        HealthAgentRun(
            run_id="health-run:sample:issue-triage",
            issue_id="health:issue:sample-task-system-chain",
            task_run_id="taskrun:sample:health-issue-triage",
            agent_id="agent:health:maintainer",
            agent_profile_id="health_maintainer_agent",
            runtime_lane="health_issue_read",
            task_mode="issue_triage",
            workflow_id="workflow.health.issue_triage",
            projection_id="projection:xuannv__health_maintainer:sample",
            prompt_manifest_id="prompt-manifest:projection:xuannv__health_maintainer:sample",
            status="sample",
            terminal_reason="not_executed_sample",
            result_ref="HealthTriageResult:sample",
            created_at=timestamp,
            metadata={"sample": True},
        ),
    )


class HealthRegistry:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)
        self.store_dir = self.base_dir / "health-system"
        self.issues_path = self.store_dir / "issues.jsonl"
        self.agent_runs_path = self.store_dir / "agent_runs.jsonl"
        self.agent_results_path = self.store_dir / "agent_results.jsonl"
        self.commands_path = self.store_dir / "commands.jsonl"
        self.receipts_path = self.store_dir / "receipts.jsonl"
        self.reports_path = self.store_dir / "reports.jsonl"
        self.conversation_sessions_path = self.store_dir / "conversation_sessions.jsonl"
        self.conversation_messages_path = self.store_dir / "conversation_messages.jsonl"
        self.health_test_runs_path = self.store_dir / "health_test_runs.jsonl"

    def list_issues(self) -> list[HealthIssue]:
        issues = self._load_issues()
        seen = {item.issue_id for item in issues}
        samples = [item for item in default_health_issues() if item.issue_id not in seen]
        return [*issues, *samples]

    def get_issue(self, issue_id: str) -> HealthIssue | None:
        target = str(issue_id or "").strip()
        return next((item for item in self.list_issues() if item.issue_id == target), None)

    def create_issue(self, payload: dict[str, Any]) -> HealthIssue:
        now = time.time()
        title = str(payload.get("title") or "").strip()
        if not title:
            raise ValueError("HealthIssue requires title")
        issue_id = str(payload.get("issue_id") or "").strip() or f"health:issue:{int(now * 1000)}"
        issue = HealthIssue(
            issue_id=issue_id,
            title=title,
            owner_system=str(payload.get("owner_system") or "unknown"),
            severity=str(payload.get("severity") or "medium"),
            status=str(payload.get("status") or "triage_ready"),
            source=str(payload.get("source") or "manual"),
            conversation_ref=str(payload.get("conversation_ref") or ""),
            runtime_trace_refs=tuple(str(item) for item in list(payload.get("runtime_trace_refs") or [])),
            prompt_manifest_refs=tuple(str(item) for item in list(payload.get("prompt_manifest_refs") or [])),
            memory_refs=tuple(str(item) for item in list(payload.get("memory_refs") or [])),
            assertion_refs=tuple(str(item) for item in list(payload.get("assertion_refs") or [])),
            duplicate_of=str(payload.get("duplicate_of") or ""),
            created_at=now,
            updated_at=now,
            metadata=dict(payload.get("metadata") or {}),
        )
        self._upsert_issue(issue)
        return issue

    def list_commands(self) -> list[HealthManagementCommand]:
        return self._load_commands()

    def get_command(self, command_id: str) -> HealthManagementCommand | None:
        target = str(command_id or "").strip()
        return next((item for item in self.list_commands() if item.command_id == target), None)

    def list_receipts(self) -> list[HealthManagementReceipt]:
        return self._load_receipts()

    def get_receipt(self, receipt_id: str) -> HealthManagementReceipt | None:
        target = str(receipt_id or "").strip()
        return next((item for item in self.list_receipts() if item.receipt_id == target), None)

    def list_reports(self) -> list[HealthReport]:
        return self._load_reports()

    def get_report(self, report_id: str) -> HealthReport | None:
        target = str(report_id or "").strip()
        return next((item for item in self.list_reports() if item.report_id == target), None)

    def list_conversation_sessions(self) -> list[HealthAgentConversationSession]:
        return self._load_conversation_sessions()

    def get_conversation_session(self, session_id: str) -> HealthAgentConversationSession | None:
        target = str(session_id or "").strip()
        return next((item for item in self.list_conversation_sessions() if item.session_id == target), None)

    def list_conversation_messages(self, session_id: str = "") -> list[HealthAgentConversationMessage]:
        messages = self._load_conversation_messages()
        target = str(session_id or "").strip()
        return [item for item in messages if not target or item.session_id == target]

    def list_health_test_runs(self) -> list[HealthTestRun]:
        return self._load_health_test_runs()

    def list_health_test_scenarios(self) -> list[dict[str, Any]]:
        return [item.to_dict() for item in default_health_test_scenarios()]

    def create_conversation_session(self, payload: dict[str, Any]) -> HealthAgentConversationSession:
        now = time.time()
        task_registry = TaskFlowRegistry(self.base_dir)
        flow = next((item for item in task_registry.list_flows() if item.task_mode == "issue_triage"), None)
        binding = task_registry.build_binding_for_flow(flow) if flow is not None else None
        session_id = str(payload.get("session_id") or "").strip() or f"health-agent-session:{int(now * 1000)}"
        session = HealthAgentConversationSession(
            session_id=session_id,
            agent_id=str(payload.get("agent_id") or (binding.agent_id if binding is not None else "agent:health:maintainer")),
            agent_profile_id=str(payload.get("agent_profile_id") or (binding.agent_profile_id if binding is not None else "")),
            projection_template_id=str(
                payload.get("projection_template_id")
                or (binding.projection_template_id if binding is not None else "xuannv__health_maintainer")
            ),
            skill_workflow_id=str(
                payload.get("skill_workflow_id") or (binding.skill_workflow_id if binding is not None else "workflow.health.issue_triage")
            ),
            runtime_lane=str(payload.get("runtime_lane") or (binding.runtime_lane if binding is not None else "health_issue_read")),
            active_issue_ref=str(payload.get("active_issue_ref") or ""),
            active_run_ref=str(payload.get("active_run_ref") or ""),
            command_refs=tuple(str(item) for item in list(payload.get("command_refs") or [])),
            status=str(payload.get("status") or "active"),
            created_at=now,
            updated_at=now,
        )
        self._upsert_conversation_session(session)
        return session

    def append_conversation_message(self, session_id: str, payload: dict[str, Any]) -> HealthAgentConversationMessage:
        session = self.get_conversation_session(session_id)
        if session is None:
            raise KeyError(session_id)
        now = time.time()
        content = str(payload.get("content") or "").strip()
        if not content:
            raise ValueError("HealthAgentConversationMessage requires content")
        message = HealthAgentConversationMessage(
            message_id=str(payload.get("message_id") or "").strip() or f"health-agent-message:{int(now * 1000)}",
            session_id=session.session_id,
            role=str(payload.get("role") or "user"),
            content=content,
            command_ref=str(payload.get("command_ref") or ""),
            receipt_ref=str(payload.get("receipt_ref") or ""),
            report_ref=str(payload.get("report_ref") or ""),
            created_at=now,
        )
        self._append_conversation_message(message)
        return message

    async def submit_command(
        self,
        payload: dict[str, Any],
        *,
        task_run_loop: Any | None = None,
        model_response_executor: Any | None = None,
        test_system_service: Any | None = None,
    ) -> dict[str, Any]:
        command = self._build_command(payload)
        self._upsert_command(command)
        try:
            result = await self._handle_command(
                command,
                task_run_loop=task_run_loop,
                model_response_executor=model_response_executor,
                test_system_service=test_system_service,
            )
        except Exception as exc:
            receipt = self._build_receipt(
                command=command,
                accepted=False,
                status="failed",
                blocked_reasons=(exc.__class__.__name__,),
                diagnostics={"error": str(exc)},
            )
            self._append_receipt(receipt)
            failed = replace(command, status="failed", updated_at=time.time())
            self._upsert_command(failed)
            return {
                "authority": "health_system.management_command",
                "command": failed.to_dict(),
                "receipt": receipt.to_dict(),
            }
        return result

    async def _handle_command(
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
            issue = self.create_issue(
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
            report = self._build_report(
                command=command,
                report_type="issue_intake_report",
                issue_ref=issue.issue_id,
                evidence_refs=(issue.conversation_ref, *issue.runtime_trace_refs),
                verdict="accepted",
                severity=issue.severity,
                summary=f"已登记健康问题：{issue.title}",
                recommended_actions=("analyze_trace",),
            )
            self._append_report(report)
            receipt = self._build_receipt(
                command=command,
                accepted=True,
                status="completed",
                health_issue_ref=issue.issue_id,
                report_ref=report.report_id,
                diagnostics={"issue": issue.to_dict()},
            )
            return self._complete_command(command, receipt=receipt, report=report, issue=issue)

        if command.command_type in {"analyze_trace", "draft_case", "verify_fix"}:
            admission = admit_health_command(self.base_dir, command)
            if not admission.admitted:
                receipt = self._build_receipt(
                    command=command,
                    accepted=False,
                    status="rejected",
                    blocked_reasons=admission.blocked_reasons,
                    diagnostics={"admission": admission.to_dict()},
                )
                return self._complete_command(command, receipt=receipt)
            if task_run_loop is None or model_response_executor is None:
                receipt = self._build_receipt(
                    command=command,
                    accepted=False,
                    status="rejected",
                    blocked_reasons=("runtime_dependency_missing",),
                    diagnostics={"admission": admission.to_dict()},
                )
                return self._complete_command(command, receipt=receipt)
            issue_id = command.target_ref
            if command.target_scope and command.target_scope not in {"health_issue", "issue"}:
                issue_id = str(command.payload.get("issue_id") or "")
            if not issue_id:
                receipt = self._build_receipt(
                    command=command,
                    accepted=False,
                    status="rejected",
                    blocked_reasons=("health_issue_ref_missing",),
                    diagnostics={"admission": admission.to_dict()},
                )
                return self._complete_command(command, receipt=receipt)
            run_result = await self.execute_agent_run(
                issue_id=issue_id,
                task_mode=admission.task_mode,
                session_id=command.conversation_session_ref or "health-system",
                source=command.source or "health_management_command",
                task_run_loop=task_run_loop,
                model_response_executor=model_response_executor,
            )
            health_run = dict(run_result.get("health_agent_run") or {})
            report = self._build_report(
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
            self._append_report(report)
            receipt = self._build_receipt(
                command=command,
                accepted=str(run_result.get("status") or "") not in {"blocked", "failed"},
                status=str(run_result.get("status") or "unknown"),
                health_issue_ref=issue_id,
                health_run_ref=str(health_run.get("run_id") or ""),
                report_ref=report.report_id,
                diagnostics={"admission": admission.to_dict(), "run": run_result},
            )
            return self._complete_command(command, receipt=receipt, report=report, run_result=run_result)

        if command.command_type == "launch_health_test":
            if test_system_service is None:
                receipt = self._build_receipt(
                    command=command,
                    accepted=False,
                    status="rejected",
                    blocked_reasons=("test_system_service_missing",),
                )
                return self._complete_command(command, receipt=receipt)
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
            self._upsert_health_test_run(health_test_run)
            report = self._build_report(
                command=command,
                report_type="health_test_run_report",
                test_run_ref=health_test_run.test_system_run_ref,
                evidence_refs=health_test_run.artifact_refs,
                verdict=health_test_run.verdict,
                summary=f"健康验证已启动：{profile}",
                recommended_actions=("inspect_test_artifacts", "review_health_readiness"),
            )
            self._append_report(report)
            health_test_run = replace(health_test_run, report_refs=(report.report_id,))
            self._upsert_health_test_run(health_test_run)
            receipt = self._build_receipt(
                command=command,
                accepted=True,
                status=health_test_run.status,
                test_run_ref=health_test_run.test_system_run_ref,
                report_ref=report.report_id,
                diagnostics={"health_test_run": health_test_run.to_dict(), "test_run": test_run},
            )
            return self._complete_command(command, receipt=receipt, report=report, health_test_run=health_test_run)

        if command.command_type == "build_cutover_readiness":
            report = self._build_report(
                command=command,
                report_type="cutover_readiness_report",
                evidence_refs=tuple(item.report_id for item in self.list_reports()[-10:]),
                verdict="ready_with_review" if self.list_reports() else "insufficient_evidence",
                severity="medium",
                summary="已生成健康系统切流准备度报告草案。",
                recommended_actions=("review_recent_reports", "run_required_health_scenarios"),
            )
            self._append_report(report)
            receipt = self._build_receipt(command=command, accepted=True, status="completed", report_ref=report.report_id)
            return self._complete_command(command, receipt=receipt, report=report)

        receipt = self._build_receipt(
            command=command,
            accepted=False,
            status="rejected",
            blocked_reasons=("unsupported_command_type",),
            diagnostics={"command_type": command.command_type},
        )
        return self._complete_command(command, receipt=receipt)

    def list_agent_runs(self) -> list[HealthAgentRun]:
        runs = self._load_agent_runs()
        seen = {item.run_id for item in runs}
        samples = [item for item in default_health_agent_runs() if item.run_id not in seen]
        return [*runs, *samples]

    def get_agent_run(self, run_id: str) -> HealthAgentRun | None:
        return next((item for item in self.list_agent_runs() if item.run_id == run_id), None)

    def get_agent_result(self, result_ref: str) -> dict[str, Any] | None:
        target = str(result_ref or "").strip()
        return next((item for item in self._load_agent_results() if str(item.get("result_ref") or "") == target), None)

    def list_problem_nodes(self) -> list[ProblemNode]:
        return list(default_problem_nodes())

    def build_overview(self) -> dict[str, Any]:
        issues = self.list_issues()
        runs = self.list_agent_runs()
        problem_nodes = self.list_problem_nodes()
        commands = self.list_commands()
        reports = self.list_reports()
        health_test_runs = self.list_health_test_runs()
        return {
            "authority": "health_system.registry",
            "summary": {
                "issue_count": len(issues),
                "open_issue_count": sum(1 for item in issues if item.status not in {"resolved", "closed"}),
                "agent_run_count": len(runs),
                "problem_node_count": len(problem_nodes),
                "command_count": len(commands),
                "report_count": len(reports),
                "health_test_run_count": len(health_test_runs),
            },
            "issues": [item.to_dict() for item in issues],
            "agent_runs": [item.to_dict() for item in runs],
            "problem_nodes": [item.to_dict() for item in problem_nodes],
            "commands": [item.to_dict() for item in commands],
            "reports": [item.to_dict() for item in reports],
            "health_test_runs": [item.to_dict() for item in health_test_runs],
        }

    def build_agent_run_trace_report(self, *, run_id: str, task_run_loop: Any) -> dict[str, Any]:
        run = self.get_agent_run(run_id)
        if run is None:
            raise KeyError(run_id)
        trace = task_run_loop.get_trace(run.task_run_id, include_payloads=True, include_model_messages=False)
        if trace is None:
            raise KeyError(run.task_run_id)
        events = list(trace.get("events") or [])
        result = self.get_agent_result(run.result_ref) if run.result_ref else None
        event_type_counts: dict[str, int] = {}
        problem_events: list[dict[str, Any]] = []
        for event in events:
            event_type = str(dict(event).get("event_type") or "")
            event_type_counts[event_type] = event_type_counts.get(event_type, 0) + 1
            payload = dict(dict(event).get("payload") or {})
            if event_type in {"loop_error", "operation_gate_checked", "loop_terminal"}:
                problem_events.append(
                    {
                        "event_id": str(dict(event).get("event_id") or ""),
                        "event_type": event_type,
                        "offset": int(dict(event).get("offset") or 0),
                        "summary": _health_event_summary(event_type, payload),
                        "refs": dict(dict(event).get("refs") or {}),
                    }
                )
        return {
            "authority": "health_system.trace_report",
            "run": run.to_dict(),
            "issue": self.get_issue(run.issue_id).to_dict() if self.get_issue(run.issue_id) else None,
            "result": result,
            "event_count": len(events),
            "event_type_counts": event_type_counts,
            "problem_events": problem_events,
            "prompt_manifest_ref": run.prompt_manifest_id,
            "projection_ref": run.projection_id,
            "task_run_trace": trace,
        }

    def preview_agent_run(self, *, issue_id: str, task_mode: str = "issue_triage") -> dict[str, Any]:
        issue = next((item for item in self.list_issues() if item.issue_id == issue_id), None)
        if issue is None:
            raise KeyError(issue_id)
        task_registry = TaskFlowRegistry(self.base_dir)
        flow = next((item for item in task_registry.list_flows() if item.task_mode == task_mode), None)
        if flow is None:
            raise KeyError(task_mode)
        binding = task_registry.build_binding_for_flow(flow)
        if binding.validation_state != "valid":
            return {
                "authority": "health_system.agent_run_preview",
                "status": "blocked",
                "issue": issue.to_dict(),
                "flow": flow.to_dict(),
                "binding": binding.to_dict(),
                "reason": "task agent binding is invalid",
            }
        projection = ProjectionInstanceRegistry(self.base_dir).preview_instance(
            template_id=binding.projection_template_id,
            task_id=f"task.health.{task_mode}:{issue.issue_id}",
            agent_id=binding.agent_id,
            runtime_lane=binding.runtime_lane,
            resource_policy_ref=binding.resource_policy_ref,
        )
        return {
            "authority": "health_system.agent_run_preview",
            "status": "ready",
            "issue": issue.to_dict(),
            "flow": flow.to_dict(),
            "binding": binding.to_dict(),
            "projection_instance": projection.to_dict(),
            "runtime_directive_lane": {
                "lane_id": f"lane:{binding.runtime_lane}:{issue.issue_id}",
                "lane_type": binding.runtime_lane,
                "agent_id": binding.agent_id,
                "agent_profile_id": binding.agent_profile_id,
                "task_id": f"task.health.{task_mode}:{issue.issue_id}",
                "memory_scope": binding.memory_scope,
                "output_contract_id": binding.output_contract_id,
            },
        }

    def start_agent_run(
        self,
        *,
        issue_id: str,
        task_mode: str = "issue_triage",
        session_id: str = "health-system",
        source: str = "health_system.manual",
        task_run_loop: Any,
    ) -> dict[str, Any]:
        preview = self.preview_agent_run(issue_id=issue_id, task_mode=task_mode)
        if preview["status"] != "ready":
            return {
                "authority": "health_system.agent_run_start",
                "status": "blocked",
                "reason": preview.get("reason") or "health agent run preview is not ready",
                "preview": preview,
            }

        issue = dict(preview["issue"])
        flow = dict(preview["flow"])
        binding = dict(preview["binding"])
        task_id = f"task.health.{task_mode}:{issue_id}"
        task_contract_ref = f"health-task-contract:{task_id}"
        start = task_run_loop.start(
            session_id=session_id or "health-system",
            task_id=task_id,
            task_contract_ref=task_contract_ref,
            agent_id=str(binding.get("agent_id") or ""),
            agent_profile_id=str(binding.get("agent_profile_id") or ""),
            runtime_lane=str(binding.get("runtime_lane") or ""),
            task_agent_binding_ref=str(binding.get("binding_id") or ""),
            skill_workflow_ref=str(binding.get("skill_workflow_id") or ""),
            health_issue_ref=issue_id,
            diagnostics={
                "health_system_agent_run": True,
                "health_issue_title": str(issue.get("title") or ""),
                "health_issue_source": str(issue.get("source") or ""),
                "health_run_source": source,
                "task_mode": task_mode,
                "flow_id": str(flow.get("flow_id") or ""),
                "projection_template_id": str(binding.get("projection_template_id") or ""),
                "output_contract_id": str(binding.get("output_contract_id") or ""),
                "memory_scope": str(binding.get("memory_scope") or ""),
            },
        )
        projection = ProjectionInstanceRegistry(self.base_dir).build_instance(
            template_id=str(binding.get("projection_template_id") or ""),
            task_id=task_id,
            task_run_id=start.task_run.task_run_id,
            agent_id=str(binding.get("agent_id") or ""),
            runtime_lane=str(binding.get("runtime_lane") or ""),
            resource_policy_ref=str(binding.get("resource_policy_ref") or ""),
            candidate_only=False,
        )
        projection_event = task_run_loop.event_log.append(
            start.task_run.task_run_id,
            "stage_projection_built",
            payload={
                "projection_instance": projection.to_dict(),
                "health_issue_ref": issue_id,
                "task_agent_binding_ref": str(binding.get("binding_id") or ""),
                "source": source,
            },
            refs={
                "projection_ref": projection.projection_id,
                "prompt_manifest_ref": projection.prompt_manifest_id,
                "health_issue_ref": issue_id,
            },
        )
        loop_state = replace(
            start.loop_state,
            projection_ref=projection.projection_id,
            prompt_manifest_ref=projection.prompt_manifest_id,
            diagnostics={
                **dict(start.loop_state.diagnostics),
                "projection_instance_built": True,
                "projection_candidate_only": False,
                "prompt_manifest_id": projection.prompt_manifest_id,
            },
        )
        checkpoint = task_run_loop.checkpoints.write(loop_state, event_offset=projection_event.offset)
        checkpoint_event = task_run_loop.event_log.append(
            start.task_run.task_run_id,
            "checkpoint_written",
            payload={
                "checkpoint_id": checkpoint.checkpoint_id,
                "event_offset": checkpoint.event_offset,
                "checksum": checkpoint.checksum,
                "source": "health_system.agent_run_start",
            },
            refs={"checkpoint_ref": checkpoint.checkpoint_id},
        )
        task_run = replace(
            start.task_run,
            updated_at=time.time(),
            latest_event_offset=checkpoint_event.offset,
            latest_checkpoint_ref=checkpoint.checkpoint_id,
            diagnostics={
                **dict(start.task_run.diagnostics),
                "projection_ref": projection.projection_id,
                "prompt_manifest_ref": projection.prompt_manifest_id,
                "health_agent_run_linked": True,
            },
        )
        task_run_loop.state_index.upsert_task_run(task_run)
        events = (*start.events, projection_event.to_dict(), checkpoint_event.to_dict())
        health_run = HealthAgentRun(
            run_id=f"health-run:{task_run.task_run_id}",
            issue_id=issue_id,
            task_run_id=task_run.task_run_id,
            agent_id=task_run.agent_id,
            agent_profile_id=task_run.agent_profile_id,
            runtime_lane=task_run.runtime_lane,
            task_mode=task_mode,
            workflow_id=str(binding.get("skill_workflow_id") or ""),
            projection_id=projection.projection_id,
            prompt_manifest_id=projection.prompt_manifest_id,
            status=task_run.status,
            terminal_reason=task_run.terminal_reason,
            result_ref="",
            created_at=task_run.created_at,
            metadata={
                "source": source,
                "flow_id": str(flow.get("flow_id") or ""),
                "task_contract_ref": task_contract_ref,
                "task_agent_binding_ref": str(binding.get("binding_id") or ""),
                "checkpoint_ref": checkpoint.checkpoint_id,
                "latest_event_offset": checkpoint_event.offset,
                "event_count": len(events),
                "real_runtime_loop_started": True,
            },
        )
        self._upsert_agent_run(health_run)
        trace = task_run_loop.get_trace(task_run.task_run_id, include_payloads=True, include_model_messages=False)
        return {
            "authority": "health_system.agent_run_start",
            "status": "running",
            "health_agent_run": health_run.to_dict(),
            "task_run": task_run.to_dict(),
            "loop_state": loop_state.to_dict(),
            "checkpoint": checkpoint.to_dict(),
            "events": [dict(item) for item in events],
            "trace": trace,
            "issue": issue,
            "flow": flow,
            "binding": binding,
            "projection_instance": projection.to_dict(),
            "runtime_directive_lane": {
                "lane_id": f"lane:{task_run.runtime_lane}:{issue_id}",
                "lane_type": task_run.runtime_lane,
                "agent_id": task_run.agent_id,
                "agent_profile_id": task_run.agent_profile_id,
                "task_id": task_id,
                "memory_scope": str(binding.get("memory_scope") or ""),
                "output_contract_id": str(binding.get("output_contract_id") or ""),
            },
        }

    async def execute_agent_run(
        self,
        *,
        issue_id: str,
        task_mode: str = "issue_triage",
        session_id: str = "health-system",
        source: str = "health_system.manual",
        task_run_loop: Any,
        model_response_executor: Any,
    ) -> dict[str, Any]:
        started = self.start_agent_run(
            issue_id=issue_id,
            task_mode=task_mode,
            session_id=session_id,
            source=source,
            task_run_loop=task_run_loop,
        )
        if started["status"] != "running":
            return started

        task_run = dict(started["task_run"])
        loop_state = dict(started["loop_state"])
        issue = dict(started["issue"])
        flow = dict(started["flow"])
        binding = dict(started["binding"])
        projection = dict(started["projection_instance"])
        task_run_id = str(task_run.get("task_run_id") or "")
        task_id = str(task_run.get("task_id") or "")
        workflow = SkillWorkflowRegistry(self.base_dir).get_workflow(str(binding.get("skill_workflow_id") or ""))
        workflow_payload = workflow.to_dict() if workflow is not None else {}
        model_messages = self._build_health_model_messages(
            issue=issue,
            flow=flow,
            binding=binding,
            projection=projection,
            workflow=workflow_payload,
        )
        task_contract_ref = str(task_run.get("task_contract_ref") or f"health-task-contract:{task_id}")
        task_contract_event = task_run_loop.event_log.append(
            task_run_id,
            "task_contract_built",
            payload={
                "task_contract": {
                    "task_id": task_id,
                    "session_id": str(task_run.get("session_id") or ""),
                    "task_mode": task_mode,
                    "input_contract_id": str(flow.get("input_contract_id") or ""),
                    "output_contract_id": str(flow.get("output_contract_id") or ""),
                    "user_goal": f"对健康问题进行 {task_mode}：{issue.get('title') or issue_id}",
                },
                "source": source,
            },
            refs={"task_contract_ref": task_contract_ref, "health_issue_ref": issue_id},
        )
        memory_event = task_run_loop.event_log.append(
            task_run_id,
            "memory_runtime_view_built",
            payload={
                "memory_runtime_view_ref": f"health-memory-view:{issue_id}:{task_mode}",
                "memory_scope": str(binding.get("memory_scope") or ""),
                "conversation_candidate_count": 1 if issue.get("conversation_ref") else 0,
                "state_candidate_count": len(list(issue.get("runtime_trace_refs") or [])),
                "long_term_candidate_count": 0,
            },
            refs={"memory_runtime_view_ref": f"health-memory-view:{issue_id}:{task_mode}"},
        )
        context_event = task_run_loop.event_log.append(
            task_run_id,
            "context_snapshot_built",
            payload={
                "context_snapshot": {
                    "snapshot_id": f"ctx:{task_run_id}",
                    "task_run_id": task_run_id,
                    "model_messages": model_messages,
                    "history_message_count": 0,
                    "pending_user_message_chars": len(model_messages[-1]["content"]),
                    "system_prompt_chars": len(model_messages[0]["content"]),
                    "memory_runtime_view_ref": f"health-memory-view:{issue_id}:{task_mode}",
                    "projection_ref": str(projection.get("projection_id") or ""),
                    "prompt_manifest_ref": str(projection.get("prompt_manifest_id") or ""),
                    "token_pressure": {"level": "unknown", "source": "health_system"},
                },
                "context_policy_result": {
                    "memory_scope": str(binding.get("memory_scope") or ""),
                    "allowed_context_sections": ["health_issue", "runtime_trace", "prompt_manifest", "assertions"],
                },
            },
            refs={
                "memory_runtime_view_ref": f"health-memory-view:{issue_id}:{task_mode}",
                "context_snapshot_ref": f"ctx:{task_run_id}",
                "projection_ref": str(projection.get("projection_id") or ""),
                "prompt_manifest_ref": str(projection.get("prompt_manifest_id") or ""),
            },
        )
        resource_policy = self._build_health_resource_policy(task_id=task_id, binding=binding)
        directive = RuntimeDirective(
            directive_id=f"runtime-directive:{task_id}:health-model-response",
            task_id=task_id,
            plan_ref=f"orchplan:{task_id}:runtime",
            stage_ref=f"orchstage:{task_id}:health-model:runtime",
            executor_type="model",
            adopted_resource_policy_ref=resource_policy.policy_id,
            operation_refs=("op.model_response",),
            input_contract_ref=str(flow.get("input_contract_id") or ""),
            output_contract_ref=str(flow.get("output_contract_id") or ""),
            execution_graph_ref=f"execgraph:{task_id}:runtime",
            diagnostics={
                "agent_id": str(binding.get("agent_id") or ""),
                "agent_profile_id": str(binding.get("agent_profile_id") or ""),
                "runtime_lane": str(binding.get("runtime_lane") or ""),
                "health_issue_ref": issue_id,
                "workflow_id": str(binding.get("skill_workflow_id") or ""),
            },
        )
        directive_event = task_run_loop.event_log.append(
            task_run_id,
            "runtime_directive_issued",
            payload={"directive": directive.to_dict(), "resource_policy": resource_policy.to_dict()},
            refs={"directive_ref": directive.directive_id, "resource_policy_ref": resource_policy.policy_id},
        )
        gate_result = task_run_loop.operation_gate.check(
            "op.model_response",
            resource_policy=resource_policy,
            directive_ref=directive.directive_id,
        )
        gate_event = task_run_loop.event_log.append(
            task_run_id,
            "operation_gate_checked",
            payload={"gate": gate_result.to_dict()},
            refs={"operation_id": gate_result.operation_id, "directive_ref": directive.directive_id},
        )
        final_content = ""
        result_refs = [
            f"health_issue:{issue_id}",
            f"projection:{projection.get('projection_id') or ''}",
            f"prompt_manifest:{projection.get('prompt_manifest_id') or ''}",
        ]
        terminal_reason = "completed"
        executor_events: list[dict[str, Any]] = []
        if not gate_result.allowed:
            terminal_reason = "blocked_by_gate"
            final_content = gate_result.reason
        else:
            executor_started_event = task_run_loop.event_log.append(
                task_run_id,
                "executor_started",
                payload={
                    "executor_type": "model",
                    "directive_ref": directive.directive_id,
                    "model_message_count": len(model_messages),
                    "agent_id": str(binding.get("agent_id") or ""),
                },
                refs={"directive_ref": directive.directive_id},
            )
            executor_events.append(executor_started_event.to_dict())
            try:
                async for event in model_response_executor.stream(
                    user_message=model_messages[-1]["content"],
                    model_messages=model_messages,
                    directive=directive,
                    tool_instances=[],
                ):
                    event_type = str(event.get("type") or "")
                    if event_type == "answer_candidate":
                        final_content = str(event.get("content") or final_content)
                        runtime_event = task_run_loop.event_log.append(
                            task_run_id,
                            "executor_observation_received",
                            payload={
                                "source": str(event.get("source") or "runtime_directive:model_response"),
                                "content": final_content,
                                "content_chars": len(final_content),
                                "directive_ref": directive.directive_id,
                                "health_issue_ref": issue_id,
                            },
                            refs={"directive_ref": directive.directive_id, "health_issue_ref": issue_id},
                        )
                        executor_events.append(runtime_event.to_dict())
                    elif event_type == "output_boundary":
                        runtime_event = task_run_loop.event_log.append(
                            task_run_id,
                            "output_boundary_applied",
                            payload={"output": dict(event.get("output") or {}), "health_issue_ref": issue_id},
                            refs={"directive_ref": directive.directive_id, "health_issue_ref": issue_id},
                        )
                        executor_events.append(runtime_event.to_dict())
                    elif event_type == "runtime_commit_gate":
                        runtime_event = task_run_loop.event_log.append(
                            task_run_id,
                            "commit_gate_checked",
                            payload={"commit_gate": dict(event.get("commit_gate") or {})},
                            refs={
                                "commit_gate_ref": str(dict(event.get("commit_gate") or {}).get("gate_id") or ""),
                                "commit_type": str(dict(event.get("commit_gate") or {}).get("commit_type") or ""),
                            },
                        )
                        executor_events.append(runtime_event.to_dict())
                    elif event_type == "done":
                        final_content = str(event.get("content") or final_content)
                    elif event_type == "error":
                        terminal_reason = "executor_failed"
                        final_content = str(event.get("content") or event.get("error") or "健康子 Agent 执行失败")
                        runtime_event = task_run_loop.event_log.append(
                            task_run_id,
                            "loop_error",
                            payload={"error": str(event.get("error") or ""), "content": final_content},
                            refs={"directive_ref": directive.directive_id, "health_issue_ref": issue_id},
                        )
                        executor_events.append(runtime_event.to_dict())
                        break
            except Exception as exc:
                terminal_reason = "executor_failed"
                final_content = str(getattr(exc, "user_message", "") or exc or "健康子 Agent 执行异常")
                runtime_event = task_run_loop.event_log.append(
                    task_run_id,
                    "loop_error",
                    payload={
                        "error": exc.__class__.__name__,
                        "content": final_content,
                        "provider_error_code": str(getattr(exc, "code", "") or ""),
                    },
                    refs={"directive_ref": directive.directive_id, "health_issue_ref": issue_id},
                )
                executor_events.append(runtime_event.to_dict())
        result_ref = f"health-result:{task_run_id}"
        result_payload = {
            "result_ref": result_ref,
            "issue_id": issue_id,
            "task_run_id": task_run_id,
            "task_mode": task_mode,
            "output_contract_id": str(flow.get("output_contract_id") or ""),
            "content": final_content,
            "workflow": workflow_payload,
            "created_at": time.time(),
            "authority": "health_system.agent_result",
        }
        self._append_agent_result(result_payload)
        result_refs.append(result_ref)
        final_commit = build_task_run_final_commit_decision(
            task_run_id=task_run_id,
            task_id=task_id,
            terminal_reason=terminal_reason,
            final_content_chars=len(final_content),
        )
        commit_event = task_run_loop.event_log.append(
            task_run_id,
            "commit_gate_checked",
            payload={"commit_decision": final_commit.to_dict()},
            refs={"commit_gate_ref": final_commit.gate_id, "commit_type": final_commit.commit_type},
        )
        terminal_status = "completed" if terminal_reason == "completed" else "blocked" if terminal_reason == "blocked_by_gate" else "failed"
        terminal_state = RuntimeLoopState(
            task_run_id=task_run_id,
            status=terminal_status,
            turn_count=1,
            step_count=1,
            agent_id=str(task_run.get("agent_id") or ""),
            agent_profile_id=str(task_run.get("agent_profile_id") or ""),
            runtime_lane=str(task_run.get("runtime_lane") or ""),
            task_agent_binding_ref=str(binding.get("binding_id") or ""),
            skill_workflow_ref=str(binding.get("skill_workflow_id") or ""),
            health_issue_ref=issue_id,
            transition="stop_after_final_output",
            terminal_reason=terminal_reason,
            context_snapshot_ref=f"ctx:{task_run_id}",
            memory_state_ref=f"health-memory-view:{issue_id}:{task_mode}",
            projection_ref=str(projection.get("projection_id") or ""),
            prompt_manifest_ref=str(projection.get("prompt_manifest_id") or ""),
            result_refs=tuple(result_refs),
            commit_state={"task_result_final": final_commit.to_dict(), "health_result_recorded": True},
            diagnostics={
                **dict(loop_state.get("diagnostics") or {}),
                "health_agent_model_executed": gate_result.allowed,
                "final_content_chars": len(final_content),
                "output_contract_id": str(flow.get("output_contract_id") or ""),
            },
        )
        terminal_event = task_run_loop.event_log.append(
            task_run_id,
            "loop_terminal",
            payload={
                "terminal_reason": terminal_reason,
                "status": terminal_status,
                "final_content_chars": len(final_content),
                "result_ref": result_ref,
            },
            refs={"result_ref": result_ref, "health_issue_ref": issue_id},
        )
        checkpoint = task_run_loop.checkpoints.write(terminal_state, event_offset=terminal_event.offset)
        checkpoint_event = task_run_loop.event_log.append(
            task_run_id,
            "checkpoint_written",
            payload={
                "checkpoint_id": checkpoint.checkpoint_id,
                "event_offset": checkpoint.event_offset,
                "checksum": checkpoint.checksum,
                "source": "health_system.agent_run_execute",
            },
            refs={"checkpoint_ref": checkpoint.checkpoint_id},
        )
        start_task_run = task_run_loop.state_index.get_task_run(task_run_id)
        if start_task_run is None:
            raise RuntimeError(f"TaskRun missing from RuntimeStateIndex: {task_run_id}")
        finished_task_run = replace(
            start_task_run,
            status=terminal_status,
            updated_at=time.time(),
            latest_event_offset=checkpoint_event.offset,
            latest_checkpoint_ref=checkpoint.checkpoint_id,
            terminal_reason=terminal_reason,
            diagnostics={
                **dict(task_run.get("diagnostics") or {}),
                "health_agent_model_executed": gate_result.allowed,
                "result_ref": result_ref,
                "final_content_chars": len(final_content),
            },
        )
        task_run_loop.state_index.upsert_task_run(finished_task_run)
        health_run = HealthAgentRun(
            run_id=str(started["health_agent_run"]["run_id"]),
            issue_id=issue_id,
            task_run_id=task_run_id,
            agent_id=str(task_run.get("agent_id") or ""),
            agent_profile_id=str(task_run.get("agent_profile_id") or ""),
            runtime_lane=str(task_run.get("runtime_lane") or ""),
            task_mode=task_mode,
            workflow_id=str(binding.get("skill_workflow_id") or ""),
            projection_id=str(projection.get("projection_id") or ""),
            prompt_manifest_id=str(projection.get("prompt_manifest_id") or ""),
            status=terminal_status,
            terminal_reason=terminal_reason,
            result_ref=result_ref,
            created_at=float(task_run.get("created_at") or time.time()),
            metadata={
                **dict(started["health_agent_run"].get("metadata") or {}),
                "model_executed": gate_result.allowed,
                "operation_gate_allowed": gate_result.allowed,
                "checkpoint_ref": checkpoint.checkpoint_id,
                "latest_event_offset": checkpoint_event.offset,
                "event_count": len(task_run_loop.event_log.list_events(task_run_id)),
                "final_content_chars": len(final_content),
            },
        )
        self._upsert_agent_run(health_run)
        trace = task_run_loop.get_trace(task_run_id, include_payloads=True, include_model_messages=False)
        return {
            "authority": "health_system.agent_run_execute",
            "status": terminal_status,
            "health_agent_run": health_run.to_dict(),
            "task_run": finished_task_run.to_dict(),
            "loop_state": terminal_state.to_dict(),
            "checkpoint": checkpoint.to_dict(),
            "events": [
                *list(started["events"]),
                task_contract_event.to_dict(),
                memory_event.to_dict(),
                context_event.to_dict(),
                directive_event.to_dict(),
                gate_event.to_dict(),
                *executor_events,
                commit_event.to_dict(),
                terminal_event.to_dict(),
                checkpoint_event.to_dict(),
            ],
            "trace": trace,
            "issue": issue,
            "flow": flow,
            "binding": binding,
            "projection_instance": projection,
            "runtime_directive_lane": {
                "lane_id": f"lane:{task_run.get('runtime_lane') or ''}:{issue_id}",
                "lane_type": str(task_run.get("runtime_lane") or ""),
                "agent_id": str(task_run.get("agent_id") or ""),
                "agent_profile_id": str(task_run.get("agent_profile_id") or ""),
                "task_id": task_id,
                "memory_scope": str(binding.get("memory_scope") or ""),
                "output_contract_id": str(binding.get("output_contract_id") or ""),
            },
            "result": result_payload,
        }

    def _build_command(self, payload: dict[str, Any]) -> HealthManagementCommand:
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

    def _build_receipt(
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

    def _build_report(
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

    def _complete_command(
        self,
        command: HealthManagementCommand,
        *,
        receipt: HealthManagementReceipt,
        report: HealthReport | None = None,
        issue: HealthIssue | None = None,
        run_result: dict[str, Any] | None = None,
        health_test_run: HealthTestRun | None = None,
    ) -> dict[str, Any]:
        self._append_receipt(receipt)
        status = "completed" if receipt.accepted else receipt.status
        updated = replace(command, status=status, updated_at=time.time())
        self._upsert_command(updated)
        if command.conversation_session_ref:
            self._append_command_ref_to_session(command.conversation_session_ref, command.command_id)
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
        return response

    def _load_agent_runs(self) -> list[HealthAgentRun]:
        if not self.agent_runs_path.exists():
            return []
        runs: list[HealthAgentRun] = []
        for line in self.agent_runs_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                runs.append(_agent_run_from_payload(payload))
        return runs

    def _load_issues(self) -> list[HealthIssue]:
        if not self.issues_path.exists():
            return []
        issues: list[HealthIssue] = []
        for line in self.issues_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                issues.append(_issue_from_payload(payload))
        return issues

    def _load_commands(self) -> list[HealthManagementCommand]:
        return [_command_from_payload(item) for item in self._read_jsonl_dicts(self.commands_path)]

    def _load_receipts(self) -> list[HealthManagementReceipt]:
        return [_receipt_from_payload(item) for item in self._read_jsonl_dicts(self.receipts_path)]

    def _load_reports(self) -> list[HealthReport]:
        return [_report_from_payload(item) for item in self._read_jsonl_dicts(self.reports_path)]

    def _load_conversation_sessions(self) -> list[HealthAgentConversationSession]:
        return [_conversation_session_from_payload(item) for item in self._read_jsonl_dicts(self.conversation_sessions_path)]

    def _load_conversation_messages(self) -> list[HealthAgentConversationMessage]:
        return [_conversation_message_from_payload(item) for item in self._read_jsonl_dicts(self.conversation_messages_path)]

    def _load_health_test_runs(self) -> list[HealthTestRun]:
        return [_health_test_run_from_payload(item) for item in self._read_jsonl_dicts(self.health_test_runs_path)]

    def _upsert_issue(self, issue: HealthIssue) -> None:
        self.store_dir.mkdir(parents=True, exist_ok=True)
        issues = [item for item in self._load_issues() if item.issue_id != issue.issue_id]
        issues.append(issue)
        self.issues_path.write_text(
            "\n".join(json.dumps(item.to_dict(), ensure_ascii=False) for item in issues) + "\n",
            encoding="utf-8",
        )

    def _upsert_command(self, command: HealthManagementCommand) -> None:
        self._upsert_jsonl(self.commands_path, "command_id", command.command_id, command.to_dict())

    def _append_receipt(self, receipt: HealthManagementReceipt) -> None:
        self._append_jsonl(self.receipts_path, receipt.to_dict())

    def _append_report(self, report: HealthReport) -> None:
        self._append_jsonl(self.reports_path, report.to_dict())

    def _upsert_conversation_session(self, session: HealthAgentConversationSession) -> None:
        self._upsert_jsonl(self.conversation_sessions_path, "session_id", session.session_id, session.to_dict())

    def _append_conversation_message(self, message: HealthAgentConversationMessage) -> None:
        self._append_jsonl(self.conversation_messages_path, message.to_dict())

    def _upsert_health_test_run(self, run: HealthTestRun) -> None:
        self._upsert_jsonl(self.health_test_runs_path, "health_test_run_id", run.health_test_run_id, run.to_dict())

    def _append_command_ref_to_session(self, session_id: str, command_id: str) -> None:
        session = self.get_conversation_session(session_id)
        if session is None:
            return
        command_refs = tuple(dict.fromkeys((*session.command_refs, command_id)))
        self._upsert_conversation_session(replace(session, command_refs=command_refs, updated_at=time.time()))

    def _read_jsonl_dicts(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                rows.append(payload)
        return rows

    def _append_jsonl(self, path: Path, payload: dict[str, Any]) -> None:
        self.store_dir.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def _upsert_jsonl(self, path: Path, key: str, value: str, payload: dict[str, Any]) -> None:
        self.store_dir.mkdir(parents=True, exist_ok=True)
        rows = [item for item in self._read_jsonl_dicts(path) if str(item.get(key) or "") != value]
        rows.append(payload)
        path.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in rows) + "\n", encoding="utf-8")

    def _upsert_agent_run(self, run: HealthAgentRun) -> None:
        self.store_dir.mkdir(parents=True, exist_ok=True)
        runs = [item for item in self._load_agent_runs() if item.run_id != run.run_id]
        runs.append(run)
        self.agent_runs_path.write_text(
            "\n".join(json.dumps(item.to_dict(), ensure_ascii=False) for item in runs) + "\n",
            encoding="utf-8",
        )

    def _append_agent_result(self, payload: dict[str, Any]) -> None:
        self.store_dir.mkdir(parents=True, exist_ok=True)
        with self.agent_results_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def _load_agent_results(self) -> list[dict[str, Any]]:
        if not self.agent_results_path.exists():
            return []
        results: list[dict[str, Any]] = []
        for line in self.agent_results_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                results.append(payload)
        return results

    def _build_health_resource_policy(self, *, task_id: str, binding: dict[str, Any]) -> ResourcePolicy:
        profile = TaskFlowRegistry(self.base_dir).agent_registry.get_capability_profile(str(binding.get("agent_id") or ""))
        allowed = tuple(item for item in (profile.allowed_operations if profile is not None else ("op.model_response",)) if item)
        denied = tuple(profile.blocked_operations if profile is not None else ())
        decision = ResourceDecision(
            operation_id="op.model_response",
            decision="allow" if "op.model_response" in allowed else "deny",
            reason="health agent model response lane adopted by RuntimeLoop",
            risk_tags=("health_agent", "read_only", str(binding.get("runtime_lane") or "")),
            diagnostics={
                "agent_id": str(binding.get("agent_id") or ""),
                "agent_profile_id": str(binding.get("agent_profile_id") or ""),
                "runtime_lane": str(binding.get("runtime_lane") or ""),
            },
        )
        return ResourcePolicy(
            policy_id=str(binding.get("resource_policy_ref") or f"resource-policy:{task_id}:health"),
            task_id=task_id,
            allowed_operations=allowed,
            denied_operations=denied,
            memory_read_scope=str(binding.get("memory_scope") or "issue_local_readonly"),
            memory_write_scope="none",
            approval_policy="read_only_first",
            runtime_view_only=False,
            adopted=True,
            runtime_executable=True,
            decisions=(decision,),
            diagnostics={
                "agent_capability_profile_enforced": profile is not None,
                "task_agent_binding_ref": str(binding.get("binding_id") or ""),
                "skill_workflow_ref": str(binding.get("skill_workflow_id") or ""),
                "output_contract_id": str(binding.get("output_contract_id") or ""),
            },
        )

    def _build_health_model_messages(
        self,
        *,
        issue: dict[str, Any],
        flow: dict[str, Any],
        binding: dict[str, Any],
        projection: dict[str, Any],
        workflow: dict[str, Any],
    ) -> list[dict[str, str]]:
        system_prompt = "\n".join(
            [
                "你是玄女健康管家，是一个受限健康维护子 Agent。",
                "你的任务是维护系统健康：阅读问题、证据引用、运行链路和工作流，然后给出候选分析。",
                "你不能声称已经修改代码、写入长期记忆、执行 shell、调用其它子 Agent 或扩大权限。",
                "你必须基于输入中的 evidence refs 回答；证据不足时明确标记 needs_evidence。",
                "输出请使用中文，结构包括：结论、归属系统、证据引用、问题节点、风险、下一步建议。",
                f"输出合同：{flow.get('output_contract_id') or binding.get('output_contract_id') or 'HealthTriageResult'}",
                f"RuntimeLane：{binding.get('runtime_lane') or ''}",
                f"MemoryScope：{binding.get('memory_scope') or ''}",
                f"Projection：{projection.get('projection_id') or ''}",
                f"PromptManifest：{projection.get('prompt_manifest_id') or ''}",
            ]
        )
        user_payload = {
            "issue": issue,
            "flow": flow,
            "binding": binding,
            "workflow": workflow,
            "projection_instance": projection,
        }
        return [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    "请执行本次健康维护任务，并给出候选结果。输入如下：\n"
                    + json.dumps(user_payload, ensure_ascii=False, indent=2)
                ),
            },
        ]


def _agent_run_from_payload(payload: dict[str, Any]) -> HealthAgentRun:
    return HealthAgentRun(
        run_id=str(payload.get("run_id") or ""),
        issue_id=str(payload.get("issue_id") or ""),
        task_run_id=str(payload.get("task_run_id") or ""),
        agent_id=str(payload.get("agent_id") or ""),
        agent_profile_id=str(payload.get("agent_profile_id") or ""),
        runtime_lane=str(payload.get("runtime_lane") or ""),
        task_mode=str(payload.get("task_mode") or ""),
        workflow_id=str(payload.get("workflow_id") or ""),
        projection_id=str(payload.get("projection_id") or ""),
        prompt_manifest_id=str(payload.get("prompt_manifest_id") or ""),
        status=str(payload.get("status") or "unknown"),
        terminal_reason=str(payload.get("terminal_reason") or ""),
        result_ref=str(payload.get("result_ref") or ""),
        created_at=float(payload.get("created_at") or 0.0),
        metadata=dict(payload.get("metadata") or {}),
    )


def _issue_from_payload(payload: dict[str, Any]) -> HealthIssue:
    return HealthIssue(
        issue_id=str(payload.get("issue_id") or ""),
        title=str(payload.get("title") or ""),
        owner_system=str(payload.get("owner_system") or ""),
        severity=str(payload.get("severity") or "medium"),
        status=str(payload.get("status") or "triage_ready"),
        source=str(payload.get("source") or "manual"),
        conversation_ref=str(payload.get("conversation_ref") or ""),
        runtime_trace_refs=tuple(str(item) for item in list(payload.get("runtime_trace_refs") or [])),
        prompt_manifest_refs=tuple(str(item) for item in list(payload.get("prompt_manifest_refs") or [])),
        memory_refs=tuple(str(item) for item in list(payload.get("memory_refs") or [])),
        assertion_refs=tuple(str(item) for item in list(payload.get("assertion_refs") or [])),
        duplicate_of=str(payload.get("duplicate_of") or ""),
        created_at=float(payload.get("created_at") or 0.0),
        updated_at=float(payload.get("updated_at") or 0.0),
        metadata=dict(payload.get("metadata") or {}),
    )


def _command_from_payload(payload: dict[str, Any]) -> HealthManagementCommand:
    return HealthManagementCommand(
        command_id=str(payload.get("command_id") or ""),
        command_type=str(payload.get("command_type") or ""),
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
        created_at=float(payload.get("created_at") or 0.0),
        updated_at=float(payload.get("updated_at") or 0.0),
    )


def _receipt_from_payload(payload: dict[str, Any]) -> HealthManagementReceipt:
    return HealthManagementReceipt(
        receipt_id=str(payload.get("receipt_id") or ""),
        command_ref=str(payload.get("command_ref") or ""),
        accepted=bool(payload.get("accepted", False)),
        status=str(payload.get("status") or "unknown"),
        health_issue_ref=str(payload.get("health_issue_ref") or ""),
        health_run_ref=str(payload.get("health_run_ref") or ""),
        test_run_ref=str(payload.get("test_run_ref") or ""),
        report_ref=str(payload.get("report_ref") or ""),
        blocked_reasons=tuple(str(item) for item in list(payload.get("blocked_reasons") or [])),
        diagnostics=dict(payload.get("diagnostics") or {}),
        created_at=float(payload.get("created_at") or 0.0),
    )


def _report_from_payload(payload: dict[str, Any]) -> HealthReport:
    return HealthReport(
        report_id=str(payload.get("report_id") or ""),
        report_type=str(payload.get("report_type") or ""),
        issue_ref=str(payload.get("issue_ref") or ""),
        command_ref=str(payload.get("command_ref") or ""),
        agent_run_ref=str(payload.get("agent_run_ref") or ""),
        test_run_ref=str(payload.get("test_run_ref") or ""),
        evidence_refs=tuple(str(item) for item in list(payload.get("evidence_refs") or [])),
        verdict=str(payload.get("verdict") or "unknown"),
        severity=str(payload.get("severity") or "medium"),
        summary=str(payload.get("summary") or ""),
        recommended_actions=tuple(str(item) for item in list(payload.get("recommended_actions") or [])),
        created_at=float(payload.get("created_at") or 0.0),
    )


def _conversation_session_from_payload(payload: dict[str, Any]) -> HealthAgentConversationSession:
    return HealthAgentConversationSession(
        session_id=str(payload.get("session_id") or ""),
        agent_id=str(payload.get("agent_id") or ""),
        agent_profile_id=str(payload.get("agent_profile_id") or ""),
        projection_template_id=str(payload.get("projection_template_id") or ""),
        skill_workflow_id=str(payload.get("skill_workflow_id") or ""),
        runtime_lane=str(payload.get("runtime_lane") or ""),
        active_issue_ref=str(payload.get("active_issue_ref") or ""),
        active_run_ref=str(payload.get("active_run_ref") or ""),
        command_refs=tuple(str(item) for item in list(payload.get("command_refs") or [])),
        status=str(payload.get("status") or "active"),
        created_at=float(payload.get("created_at") or 0.0),
        updated_at=float(payload.get("updated_at") or 0.0),
    )


def _conversation_message_from_payload(payload: dict[str, Any]) -> HealthAgentConversationMessage:
    return HealthAgentConversationMessage(
        message_id=str(payload.get("message_id") or ""),
        session_id=str(payload.get("session_id") or ""),
        role=str(payload.get("role") or "user"),
        content=str(payload.get("content") or ""),
        command_ref=str(payload.get("command_ref") or ""),
        receipt_ref=str(payload.get("receipt_ref") or ""),
        report_ref=str(payload.get("report_ref") or ""),
        created_at=float(payload.get("created_at") or 0.0),
    )


def _health_test_run_from_payload(payload: dict[str, Any]) -> HealthTestRun:
    return HealthTestRun(
        health_test_run_id=str(payload.get("health_test_run_id") or ""),
        command_ref=str(payload.get("command_ref") or ""),
        test_system_run_ref=str(payload.get("test_system_run_ref") or ""),
        profile=str(payload.get("profile") or ""),
        scenario_refs=tuple(str(item) for item in list(payload.get("scenario_refs") or [])),
        status=str(payload.get("status") or "unknown"),
        verdict=str(payload.get("verdict") or "unknown"),
        artifact_refs=tuple(str(item) for item in list(payload.get("artifact_refs") or [])),
        issue_refs=tuple(str(item) for item in list(payload.get("issue_refs") or [])),
        report_refs=tuple(str(item) for item in list(payload.get("report_refs") or [])),
        started_at=float(payload.get("started_at") or 0.0),
        finished_at=float(payload.get("finished_at") or 0.0),
    )


def _verdict_from_status(status: str) -> str:
    normalized = status.lower()
    if normalized in {"passed", "completed", "success"}:
        return "passed"
    if normalized in {"failed", "blocked", "cancelled"}:
        return "failed"
    if normalized in {"running", "queued"}:
        return "pending"
    return "unknown"


def _health_event_summary(event_type: str, payload: dict[str, Any]) -> str:
    if event_type == "operation_gate_checked":
        gate = dict(payload.get("gate") or {})
        return f"{gate.get('operation_id') or ''}: {gate.get('decision') or ''} / {gate.get('reason') or ''}"
    if event_type == "loop_terminal":
        return f"{payload.get('status') or ''}: {payload.get('terminal_reason') or ''}"
    if event_type == "loop_error":
        return str(payload.get("error") or payload.get("content") or "loop error")
    return event_type
