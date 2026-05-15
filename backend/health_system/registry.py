from __future__ import annotations

import json
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from orchestration import (
    ResourceDecision,
    ResourcePolicy,
    RuntimeDirective,
    RuntimeLoopState,
    build_task_run_final_commit_decision,
)
from project_layout import ProjectLayout
from tasks.workflow_registry import TaskWorkflowRegistry

from .command_builder import HealthCommandBuilder
from .command_service import HealthCommandService
from .constants import HEALTH_AGENT_ID, HEALTH_SESSION_ID
from .execution_planner import (
    build_health_agent_execution_plan,
    build_health_agent_run_preview,
)
from .models import (
    HealthAgentConversationMessage,
    HealthAgentConversationSession,
    HealthAgentRun,
    HealthIssue,
    HealthManagementCommand,
    HealthManagementReceipt,
    HealthReport,
    HealthTaskRequest,
    HealthTestRun,
    ProblemNode,
)
from .runtime_admission import admit_health_command
from .store import HealthStore
from .test_catalog import default_health_test_scenarios
from .trace_builder import build_agent_run_trace_report_payload
from .verification_service import HealthVerificationService


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
            evidence_refs=("binding:flow.health.issue_triage:agent:3",),
            diagnosis="样例节点：用于验证任务系统能展示绑定、权限和投影链路。",
            confidence=0.8,
            suggested_action="检查 AgentRuntimeProfile 与任务流绑定是否一致。",
        ),
    )


def default_health_agent_runs(now: float | None = None) -> tuple[HealthAgentRun, ...]:
    timestamp = time.time() if now is None else now
    return (
        HealthAgentRun(
            run_id="health-run:sample:issue-triage",
            request_id="health-task-request:sample:issue-triage",
            issue_id="health:issue:sample-task-system-chain",
            task_run_id="taskrun:sample:health-issue-triage",
            agent_id=HEALTH_AGENT_ID,
            agent_profile_id="health_maintainer_agent",
            runtime_lane="health_issue_read",
            task_mode="issue_triage",
            workflow_id="workflow.health.issue_triage",
            admission_status="accepted",
            projection_id="",
            prompt_manifest_id="",
            status="sample",
            terminal_reason="not_executed_sample",
            blocked_reasons=(),
            report_refs=(),
            trace_refs=("runtime-loop:sample",),
            artifact_refs=("HealthTriageResult:sample",),
            result_ref="HealthTriageResult:sample",
            created_at=timestamp,
            metadata={"sample": True},
        ),
    )


class HealthRegistry:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)
        self.store_dir = ProjectLayout.from_backend_dir(self.base_dir).health_system_dir
        self.store = HealthStore(self.base_dir)
        self.command_builder = HealthCommandBuilder()
        self.verification_service = HealthVerificationService(self.base_dir)
        self.command_service = HealthCommandService(self)

    def list_issues(self) -> list[HealthIssue]:
        issues = self.store.load_issues()
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
        self.store.upsert_issue(issue)
        return issue

    def list_commands(self) -> list[HealthManagementCommand]:
        return self.store.load_commands()

    def get_command(self, command_id: str) -> HealthManagementCommand | None:
        target = str(command_id or "").strip()
        return next((item for item in self.list_commands() if item.command_id == target), None)

    def list_receipts(self) -> list[HealthManagementReceipt]:
        return self.store.load_receipts()

    def get_receipt(self, receipt_id: str) -> HealthManagementReceipt | None:
        target = str(receipt_id or "").strip()
        return next((item for item in self.list_receipts() if item.receipt_id == target), None)

    def list_reports(self) -> list[HealthReport]:
        return self.store.load_reports()

    def get_report(self, report_id: str) -> HealthReport | None:
        target = str(report_id or "").strip()
        return next((item for item in self.list_reports() if item.report_id == target), None)

    def list_conversation_sessions(self) -> list[HealthAgentConversationSession]:
        return self.store.load_conversation_sessions()

    def get_conversation_session(self, session_id: str) -> HealthAgentConversationSession | None:
        target = str(session_id or "").strip()
        return next((item for item in self.list_conversation_sessions() if item.session_id == target), None)

    def list_conversation_messages(self, session_id: str = "") -> list[HealthAgentConversationMessage]:
        messages = self.store.load_conversation_messages()
        target = str(session_id or "").strip()
        return [item for item in messages if not target or item.session_id == target]

    def list_health_test_runs(self) -> list[HealthTestRun]:
        return self.store.load_health_test_runs()

    def list_task_requests(self) -> list[HealthTaskRequest]:
        return self.store.load_task_requests()

    def list_health_test_scenarios(self) -> list[dict[str, Any]]:
        return [item.to_dict() for item in default_health_test_scenarios()]

    def create_conversation_session(self, payload: dict[str, Any]) -> HealthAgentConversationSession:
        now = time.time()
        session_id = str(payload.get("session_id") or "").strip() or f"health-agent-session:{int(now * 1000)}"
        active_issue_ref = str(payload.get("active_issue_ref") or "").strip()
        active_run_ref = str(payload.get("active_run_ref") or "").strip()
        defaults = self._resolve_conversation_defaults(
            active_issue_ref=active_issue_ref,
            active_run_ref=active_run_ref,
            task_mode=str(payload.get("task_mode") or "issue_triage").strip() or "issue_triage",
        )
        session = HealthAgentConversationSession(
            session_id=session_id,
            agent_id=str(payload.get("agent_id") or defaults["agent_id"] or HEALTH_AGENT_ID).strip(),
            agent_profile_id=str(payload.get("agent_profile_id") or defaults["agent_profile_id"] or ""),
            workflow_id=str(payload.get("workflow_id") or payload.get("skill_workflow_id") or defaults["workflow_id"] or ""),
            runtime_lane=str(payload.get("runtime_lane") or defaults["runtime_lane"] or ""),
            active_issue_ref=active_issue_ref,
            active_run_ref=active_run_ref,
            command_refs=tuple(str(item) for item in list(payload.get("command_refs") or [])),
            status=str(payload.get("status") or "active"),
            created_at=now,
            updated_at=now,
        )
        self.store.upsert_conversation_session(session)
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
        self.store.append_conversation_message(message)
        return message

    async def respond_in_conversation(
        self,
        session_id: str,
        payload: dict[str, Any],
        *,
        task_run_loop: Any,
        model_response_executor: Any,
    ) -> dict[str, Any]:
        session = self.get_conversation_session(session_id)
        if session is None:
            raise KeyError(session_id)
        user_message = self.append_conversation_message(session_id, payload)
        if str(user_message.role or "user") != "user":
            return {"message": user_message, "assistant_message": None}

        assistant_message = await self._build_conversation_reply(
            session=session,
            user_message=user_message,
            task_run_loop=task_run_loop,
            model_response_executor=model_response_executor,
        )
        self.store.append_conversation_message(assistant_message)
        return {"message": user_message, "assistant_message": assistant_message}

    async def submit_command(
        self,
        payload: dict[str, Any],
        *,
        task_run_loop: Any | None = None,
        model_response_executor: Any | None = None,
        test_system_service: Any | None = None,
    ) -> dict[str, Any]:
        return await self.command_service.submit_command(
            payload,
            task_run_loop=task_run_loop,
            model_response_executor=model_response_executor,
            test_system_service=test_system_service,
        )

    def list_agent_runs(self) -> list[HealthAgentRun]:
        runs = self.store.load_agent_runs()
        seen = {item.run_id for item in runs}
        samples = [item for item in default_health_agent_runs() if item.run_id not in seen]
        return [*runs, *samples]

    def get_agent_run(self, run_id: str) -> HealthAgentRun | None:
        return next((item for item in self.list_agent_runs() if item.run_id == run_id), None)

    def get_agent_result(self, result_ref: str) -> dict[str, Any] | None:
        target = str(result_ref or "").strip()
        return next((item for item in self.store.load_agent_results() if str(item.get("result_ref") or "") == target), None)

    def list_problem_nodes(self) -> list[ProblemNode]:
        return list(default_problem_nodes())

    def build_overview(self) -> dict[str, Any]:
        issues = self.list_issues()
        runs = self.list_agent_runs()
        problem_nodes = self.list_problem_nodes()
        commands = self.list_commands()
        reports = self.list_reports()
        health_test_runs = self.list_health_test_runs()
        verification_runs = self.verification_service.list_verification_runs(limit=10)
        gate_projection = self.verification_service.build_gate_projection()
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
                "verification_run_count": len(verification_runs),
                "gate_profile_count": int(dict(gate_projection.get("summary") or {}).get("profile_count") or 0),
            },
            "issues": [item.to_dict() for item in issues],
            "agent_runs": [item.to_dict() for item in runs],
            "problem_nodes": [item.to_dict() for item in problem_nodes],
            "commands": [item.to_dict() for item in commands],
            "reports": [item.to_dict() for item in reports],
            "health_test_runs": [item.to_dict() for item in health_test_runs],
            "verification_runs": [item.to_dict() for item in verification_runs],
            "gate_projection": gate_projection,
        }

    def build_agent_run_trace_report(self, *, run_id: str, task_run_loop: Any) -> dict[str, Any]:
        run = self.get_agent_run(run_id)
        if run is None:
            raise KeyError(run_id)
        trace = task_run_loop.get_trace(run.task_run_id, include_payloads=True, include_model_messages=False)
        if trace is None:
            raise KeyError(run.task_run_id)
        result = self.get_agent_result(run.result_ref) if run.result_ref else None
        return build_agent_run_trace_report_payload(
            run=run,
            issue=self.get_issue(run.issue_id),
            result=result,
            trace=trace,
        )

    def preview_agent_run(self, *, issue_id: str, task_mode: str = "issue_triage") -> dict[str, Any]:
        issue = next((item for item in self.list_issues() if item.issue_id == issue_id), None)
        if issue is None:
            raise KeyError(issue_id)
        plan = build_health_agent_execution_plan(
            self.base_dir,
            issue=issue,
            task_mode=task_mode,
            source="health_system.preview",
        )
        return build_health_agent_run_preview(plan, issue=issue)

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
        task_execution_assembly = dict(preview.get("task_execution_assembly") or {})
        task_body_orchestration = dict(preview.get("task_body_orchestration") or {})
        agent_runtime_spec = dict(preview.get("agent_runtime_spec") or {})
        task_id = str(agent_runtime_spec.get("task_id") or f"task.health.{task_mode}:{issue_id}")
        task_contract_ref = str(task_execution_assembly.get("assembly_id") or task_id)
        task_request = HealthTaskRequest(
            request_id=f"health-task-request:{task_mode}:{issue_id}",
            issue_id=issue_id,
            task_kind=task_mode,
            task_id=task_id,
            flow_id=str(flow.get("flow_id") or ""),
            graph_id=f"graph.health.{task_mode}",
            entry_node_id="agent",
            required_evidence_refs=tuple(
                item
                for item in (
                    str(issue.get("conversation_ref") or ""),
                    *[str(item) for item in list(issue.get("runtime_trace_refs") or []) if str(item)],
                    *[str(item) for item in list(issue.get("prompt_manifest_refs") or []) if str(item)],
                )
                if item
            ),
            requested_by=source,
            created_at=time.time(),
            metadata={"session_id": session_id or HEALTH_SESSION_ID},
        )
        self.store.upsert_task_request(task_request)
        start = task_run_loop.start(
            session_id=session_id or HEALTH_SESSION_ID,
            task_id=task_id,
            task_contract_ref=task_contract_ref,
            agent_id=str(agent_runtime_spec.get("agent_id") or binding.get("agent_id") or "").strip(),
            agent_profile_id=str(binding.get("agent_profile_id") or ""),
            runtime_lane=str(agent_runtime_spec.get("runtime_lane") or binding.get("runtime_lane") or ""),
            task_agent_binding_ref=str(binding.get("binding_id") or ""),
            skill_workflow_ref=str(binding.get("workflow_id") or ""),
            health_issue_ref=issue_id,
            diagnostics={
                "health_system_agent_run": True,
                "health_issue_title": str(issue.get("title") or ""),
                "health_issue_source": str(issue.get("source") or ""),
                "health_run_source": source,
                "task_mode": task_mode,
                "flow_id": str(flow.get("flow_id") or ""),
                "output_contract_id": str(binding.get("output_contract_id") or ""),
                "memory_scope": str(binding.get("memory_scope") or ""),
                "task_execution_assembly_ref": str(task_execution_assembly.get("assembly_id") or ""),
                "task_body_orchestration_ref": str(task_body_orchestration.get("orchestration_id") or ""),
                "runtime_spec_ref": str(agent_runtime_spec.get("runtime_spec_id") or ""),
            },
        )
        task_run = start.task_run
        events = tuple(start.events)
        health_run = HealthAgentRun(
            run_id=f"health-run:{task_run.task_run_id}",
            request_id=task_request.request_id,
            issue_id=issue_id,
            task_run_id=task_run.task_run_id,
            agent_id=task_run.agent_id,
            agent_profile_id=task_run.agent_profile_id,
            runtime_lane=task_run.runtime_lane,
            task_mode=task_mode,
            workflow_id=str(binding.get("workflow_id") or ""),
            admission_status="accepted",
            projection_id=str(task_body_orchestration.get("projection_ref") or ""),
            prompt_manifest_id=str(task_body_orchestration.get("prompt_manifest_ref") or ""),
            status=task_run.status,
            terminal_reason=task_run.terminal_reason,
            blocked_reasons=(),
            report_refs=(),
            trace_refs=(task_run.task_run_id,),
            artifact_refs=(str(task_execution_assembly.get("assembly_id") or ""), str(task_body_orchestration.get("orchestration_id") or "")),
            result_ref="",
            created_at=task_run.created_at,
            metadata={
                "source": source,
                "flow_id": str(flow.get("flow_id") or ""),
                "task_contract_ref": task_contract_ref,
                "task_agent_binding_ref": str(binding.get("binding_id") or ""),
                "task_execution_assembly_ref": str(task_execution_assembly.get("assembly_id") or ""),
                "task_body_orchestration_ref": str(task_body_orchestration.get("orchestration_id") or ""),
                "runtime_spec_ref": str(agent_runtime_spec.get("runtime_spec_id") or ""),
                "checkpoint_ref": task_run.latest_checkpoint_ref,
                "latest_event_offset": task_run.latest_event_offset,
                "event_count": len(events),
                "real_runtime_loop_started": True,
            },
        )
        self._upsert_agent_run(health_run)
        trace = task_run_loop.get_trace(task_run.task_run_id, include_payloads=True, include_model_messages=False)
        return {
            "authority": "health_system.agent_run_start",
            "status": "running",
            "task_request": task_request.to_dict(),
            "health_agent_run": health_run.to_dict(),
            "task_run": task_run.to_dict(),
            "loop_state": start.loop_state.to_dict(),
            "checkpoint": start.checkpoint.to_dict(),
            "events": [dict(item) for item in events],
            "trace": trace,
            "issue": issue,
            "flow": flow,
            "binding": binding,
            "task_execution_assembly": task_execution_assembly,
            "task_body_orchestration": task_body_orchestration,
            "agent_runtime_spec": agent_runtime_spec,
            "runtime_directive_lane": {
                "lane_id": f"lane:{task_run.runtime_lane}:{issue_id}",
                "lane_type": task_run.runtime_lane,
                "agent_id": task_run.agent_id,
                "agent_profile_id": task_run.agent_profile_id,
                "task_id": task_id,
                "task_execution_assembly_ref": str(task_execution_assembly.get("assembly_id") or ""),
                "task_body_orchestration_ref": str(task_body_orchestration.get("orchestration_id") or ""),
                "runtime_spec_ref": str(agent_runtime_spec.get("runtime_spec_id") or ""),
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
        user_message: str = "",
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
        issue = dict(started["issue"])
        flow = dict(started["flow"])
        binding = dict(started["binding"])
        task_run_id = str(task_run.get("task_run_id") or "")
        task_id = str(task_run.get("task_id") or "")
        workflow = TaskWorkflowRegistry(self.base_dir).get_workflow(str(binding.get("workflow_id") or ""))
        workflow_payload = workflow.to_dict() if workflow is not None else {}
        model_messages = self._build_health_model_messages(
            issue=issue,
            flow=flow,
            binding=binding,
            workflow=workflow_payload,
            user_message=user_message,
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
                    "projection_ref": "",
                    "prompt_manifest_ref": "",
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
                "workflow_id": str(binding.get("workflow_id") or ""),
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
            skill_workflow_ref=str(binding.get("workflow_id") or ""),
            health_issue_ref=issue_id,
            transition="stop_after_final_output",
            terminal_reason=terminal_reason,
            context_snapshot_ref=f"ctx:{task_run_id}",
            memory_state_ref=f"health-memory-view:{issue_id}:{task_mode}",
            result_refs=tuple(result_refs),
            commit_state={"task_result_final": final_commit.to_dict(), "health_result_recorded": True},
            diagnostics={
                **dict(task_run.get("diagnostics") or {}),
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
            request_id=str(started["health_agent_run"].get("request_id") or ""),
            issue_id=issue_id,
            task_run_id=task_run_id,
            agent_id=str(task_run.get("agent_id") or ""),
            agent_profile_id=str(task_run.get("agent_profile_id") or ""),
            runtime_lane=str(task_run.get("runtime_lane") or ""),
            task_mode=task_mode,
            workflow_id=str(binding.get("workflow_id") or ""),
            admission_status="accepted",
            projection_id=str(terminal_state.projection_ref or ""),
            prompt_manifest_id=str(terminal_state.prompt_manifest_ref or ""),
            status=terminal_status,
            terminal_reason=terminal_reason,
            blocked_reasons=((terminal_reason,) if terminal_status == "blocked" else ()),
            report_refs=(),
            trace_refs=(task_run_id,),
            artifact_refs=(result_ref, checkpoint.checkpoint_id),
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
        self.store.append_receipt(receipt)
        updated, response = self.command_builder.complete_command(
            command,
            receipt=receipt,
            report=report,
            issue=issue,
            run_result=run_result,
            health_test_run=health_test_run,
        )
        self.store.upsert_command(updated)
        if command.conversation_session_ref:
            session = self.get_conversation_session(command.conversation_session_ref)
            if session is not None:
                self.store.append_command_ref_to_session(session, command.command_id)
        return response

    def _upsert_agent_run(self, run: HealthAgentRun) -> None:
        self.store.upsert_agent_run(run)

    def _append_agent_result(self, payload: dict[str, Any]) -> None:
        self.store.append_agent_result(payload)

    def _build_health_resource_policy(self, *, task_id: str, binding: dict[str, Any]) -> ResourcePolicy:
        from orchestration import AgentRuntimeRegistry

        profile = AgentRuntimeRegistry(self.base_dir).get_profile(str(binding.get("agent_id") or ""))
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
                "agent_runtime_profile_enforced": profile is not None,
                "task_agent_binding_ref": str(binding.get("binding_id") or ""),
                "workflow_ref": str(binding.get("workflow_id") or ""),
                "output_contract_id": str(binding.get("output_contract_id") or ""),
            },
        )

    def _build_health_model_messages(
        self,
        *,
        issue: dict[str, Any],
        flow: dict[str, Any],
        binding: dict[str, Any],
        workflow: dict[str, Any],
        user_message: str = "",
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
            ]
        )
        user_payload = {
            "issue": issue,
            "flow": flow,
            "binding": binding,
            "workflow": workflow,
        }
        return [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    "请执行本次健康维护任务，并基于用户当前提问给出候选结果。"
                    + (f"\n用户提问：{user_message}\n" if user_message else "\n")
                    + "输入如下：\n"
                    + json.dumps(user_payload, ensure_ascii=False, indent=2)
                ),
            },
        ]

    async def _build_conversation_reply(
        self,
        *,
        session: HealthAgentConversationSession,
        user_message: HealthAgentConversationMessage,
        task_run_loop: Any,
        model_response_executor: Any,
    ) -> HealthAgentConversationMessage:
        now = time.time()
        issue_id = str(session.active_issue_ref or "").strip()
        if not issue_id and str(session.active_run_ref or "").strip():
            run = self.get_agent_run(session.active_run_ref)
            if run is not None and str(run.issue_id or "").strip():
                issue_id = str(run.issue_id)
        if not issue_id:
            return HealthAgentConversationMessage(
                message_id=f"health-agent-message:{int(now * 1000)}",
                session_id=session.session_id,
                role="assistant",
                content="当前会话还没有绑定健康问题，所以我没法做真实分析。请先绑定一个问题，或从已关联问题的运行进入对话。",
                created_at=now,
            )

        task_mode = self._route_conversation_task_mode(
            user_message=user_message.content,
            session=session,
        )
        session = self._refresh_conversation_session_mode(
            session,
            task_mode=task_mode,
            active_issue_ref=issue_id,
        )
        run_result = await self.execute_agent_run(
            issue_id=issue_id,
            task_mode=task_mode,
            session_id=session.session_id,
            source="health_system.conversation",
            task_run_loop=task_run_loop,
            model_response_executor=model_response_executor,
            user_message=user_message.content,
        )
        result = dict(run_result.get("result") or {})
        health_run = dict(run_result.get("health_agent_run") or {})
        content = str(result.get("content") or "").strip()
        if not content:
            status = str(run_result.get("status") or "unknown")
            if status == "blocked":
                content = "本次健康分析被运行时门禁拦截，暂时没有生成结果。"
            elif status == "failed":
                content = "本次健康分析执行失败，暂时没有生成结果。"
            else:
                content = "本次健康分析没有产出正文结果。"
        return HealthAgentConversationMessage(
            message_id=f"health-agent-message:{int(time.time() * 1000)}",
            session_id=session.session_id,
            role="assistant",
            content=content,
            report_ref=str(result.get("result_ref") or ""),
            created_at=time.time(),
            receipt_ref=str(health_run.get("run_id") or ""),
        )

    def _route_conversation_task_mode(
        self,
        *,
        user_message: str,
        session: HealthAgentConversationSession,
    ) -> str:
        normalized = str(user_message or "").strip().lower()
        if any(token in normalized for token in ("修复验证", "验证修复", "verify fix", "fix verification", "验证是否修好")):
            return "fix_verification"
        if any(token in normalized for token in ("用例", "case", "断言", "复现草案", "测试草案")):
            return "case_draft"
        if any(token in normalized for token in ("链路", "trace", "节点", "根因", "分析运行")):
            return "trace_analysis"
        session_workflow = str(session.workflow_id or "").strip()
        session_lane = str(session.runtime_lane or "").strip()
        if "fix_verification" in session_workflow or "fix_verification" in session_lane:
            return "fix_verification"
        if "case_draft" in session_workflow or "case_draft" in session_lane:
            return "case_draft"
        if "trace_analysis" in session_workflow or "trace" in session_lane:
            return "trace_analysis"
        return "issue_triage"

    def _resolve_conversation_defaults(
        self,
        *,
        active_issue_ref: str,
        active_run_ref: str,
        task_mode: str,
    ) -> dict[str, str]:
        issue_id = str(active_issue_ref or "").strip()
        if not issue_id and str(active_run_ref or "").strip():
            run = self.get_agent_run(active_run_ref)
            if run is not None and str(run.issue_id or "").strip():
                issue_id = str(run.issue_id or "").strip()
        if issue_id:
            issue = self.get_issue(issue_id)
            if issue is not None:
                plan = build_health_agent_execution_plan(
                    self.base_dir,
                    issue=issue,
                    task_mode=task_mode,
                    session_id=HEALTH_SESSION_ID,
                    source="health_system.conversation_defaults",
                )
                return {
                    "agent_id": str(plan.agent_id or "").strip(),
                    "agent_profile_id": str(plan.agent_profile_id or ""),
                    "workflow_id": str(plan.workflow_id or ""),
                    "runtime_lane": str(plan.runtime_lane or ""),
                }
        return {
            "agent_id": HEALTH_AGENT_ID,
            "agent_profile_id": "",
            "workflow_id": "",
            "runtime_lane": "",
        }

    def _refresh_conversation_session_mode(
        self,
        session: HealthAgentConversationSession,
        *,
        task_mode: str,
        active_issue_ref: str,
    ) -> HealthAgentConversationSession:
        defaults = self._resolve_conversation_defaults(
            active_issue_ref=active_issue_ref,
            active_run_ref=session.active_run_ref,
            task_mode=task_mode,
        )
        updated = HealthAgentConversationSession(
            session_id=session.session_id,
            agent_id=str(defaults["agent_id"] or session.agent_id).strip(),
            agent_profile_id=str(defaults["agent_profile_id"] or session.agent_profile_id),
            workflow_id=str(defaults["workflow_id"] or session.workflow_id),
            runtime_lane=str(defaults["runtime_lane"] or session.runtime_lane),
            active_issue_ref=active_issue_ref or session.active_issue_ref,
            active_run_ref=session.active_run_ref,
            command_refs=session.command_refs,
            status=session.status,
            created_at=session.created_at,
            updated_at=time.time(),
        )
        self.store.upsert_conversation_session(updated)
        return updated

def _verdict_from_status(status: str) -> str:
    normalized = status.lower()
    if normalized in {"passed", "completed", "success"}:
        return "passed"
    if normalized in {"failed", "blocked", "cancelled"}:
        return "failed"
    if normalized in {"running", "queued"}:
        return "pending"
    return "unknown"
