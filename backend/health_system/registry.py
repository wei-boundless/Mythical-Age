from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from project_layout import ProjectLayout
from harness.runtime import AgentRunRequest

from .command_builder import HealthCommandBuilder
from .command_service import HealthCommandService
from .constants import HEALTH_AGENT_ID, HEALTH_SESSION_ID, health_specific_task_id
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
    ProblemNode,
)
from .runtime_admission import admit_health_command
from .store import HealthStore
from .trace_builder import build_agent_run_trace_report_payload


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
    return ()


def default_health_agent_runs(now: float | None = None) -> tuple[HealthAgentRun, ...]:
    _ = now
    return ()


class HealthRegistry:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)
        self.store_dir = ProjectLayout.from_backend_dir(self.base_dir).health_system_dir
        self.store = HealthStore(self.base_dir)
        self.command_builder = HealthCommandBuilder()
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

    def list_task_requests(self) -> list[HealthTaskRequest]:
        return self.store.load_task_requests()

    def create_conversation_session(self, payload: dict[str, Any]) -> HealthAgentConversationSession:
        now = time.time()
        session_id = _safe_health_runtime_id(
            str(payload.get("session_id") or "").strip() or f"health-agent-session-{int(now * 1000)}"
        )
        active_issue_ref = str(payload.get("active_issue_ref") or "").strip()
        active_run_ref = str(payload.get("active_run_ref") or "").strip()
        defaults = self._resolve_conversation_defaults(
            active_issue_ref=active_issue_ref,
            active_run_ref=active_run_ref,
            health_action=str(payload.get("health_action") or "issue_triage").strip() or "issue_triage",
        )
        session = HealthAgentConversationSession(
            session_id=session_id,
            agent_id=str(defaults["agent_id"] or HEALTH_AGENT_ID).strip(),
            agent_profile_id=str(defaults["agent_profile_id"] or ""),
            workflow_id=str(defaults["workflow_id"] or ""),
            runtime_lane=str(defaults["runtime_lane"] or ""),
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
            message_id=str(payload.get("message_id") or "").strip() or f"health-agent-message-{int(now * 1000)}",
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
        agent_runtime: Any,
        model_response_executor: Any,
        agent_runtime_chain: Any,
        runtime_context_manager: Any,
        tool_runtime_executor: Any | None = None,
        tool_instances: list[Any] | None = None,
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
            agent_runtime=agent_runtime,
            model_response_executor=model_response_executor,
            agent_runtime_chain=agent_runtime_chain,
            runtime_context_manager=runtime_context_manager,
            tool_runtime_executor=tool_runtime_executor,
            tool_instances=tool_instances,
        )
        self.store.append_conversation_message(assistant_message)
        return {"message": user_message, "assistant_message": assistant_message}

    async def submit_command(
        self,
        payload: dict[str, Any],
        *,
        agent_runtime: Any | None = None,
        model_response_executor: Any | None = None,
        agent_runtime_chain: Any | None = None,
        runtime_context_manager: Any | None = None,
        tool_runtime_executor: Any | None = None,
        tool_instances: list[Any] | None = None,
    ) -> dict[str, Any]:
        return await self.command_service.submit_command(
            payload,
            agent_runtime=agent_runtime,
            model_response_executor=model_response_executor,
            agent_runtime_chain=agent_runtime_chain,
            runtime_context_manager=runtime_context_manager,
            tool_runtime_executor=tool_runtime_executor,
            tool_instances=tool_instances,
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
        return {
            "authority": "health_system.registry",
            "summary": {
                "issue_count": len(issues),
                "open_issue_count": sum(1 for item in issues if item.status not in {"resolved", "closed"}),
                "agent_run_count": len(runs),
                "problem_node_count": len(problem_nodes),
                "command_count": len(commands),
                "report_count": len(reports),
            },
            "issues": [item.to_dict() for item in issues],
            "agent_runs": [item.to_dict() for item in runs],
            "problem_nodes": [item.to_dict() for item in problem_nodes],
            "commands": [item.to_dict() for item in commands],
            "reports": [item.to_dict() for item in reports],
        }

    def build_agent_run_trace_report(self, *, run_id: str, agent_runtime: Any) -> dict[str, Any]:
        run = self.get_agent_run(run_id)
        if run is None:
            raise KeyError(run_id)
        trace = agent_runtime.get_trace(run.task_run_id, include_payloads=True, include_model_messages=False)
        if trace is None:
            raise KeyError(run.task_run_id)
        result = self.get_agent_result(run.result_ref) if run.result_ref else None
        return build_agent_run_trace_report_payload(
            run=run,
            issue=self.get_issue(run.issue_id),
            result=result,
            trace=trace,
        )

    def preview_agent_run(self, *, issue_id: str, health_action: str = "issue_triage") -> dict[str, Any]:
        issue = next((item for item in self.list_issues() if item.issue_id == issue_id), None)
        if issue is None:
            raise KeyError(issue_id)
        plan = build_health_agent_execution_plan(
            self.base_dir,
            issue=issue,
            health_action=health_action,
            source="health_system.preview",
        )
        return build_health_agent_run_preview(plan, issue=issue)

    def _route_conversation_task_mode(self, *, user_message: str, session: HealthAgentConversationSession) -> str:
        """Return the governance health action for older callers."""
        return self._route_conversation_health_action(user_message=user_message, session=session)

    async def execute_agent_run(
        self,
        *,
        issue_id: str,
        health_action: str = "issue_triage",
        session_id: str = "health-system",
        source: str = "health_system.manual",
        agent_runtime: Any,
        model_response_executor: Any,
        agent_runtime_chain: Any,
        runtime_context_manager: Any,
        tool_runtime_executor: Any | None = None,
        tool_instances: list[Any] | None = None,
        user_message: str = "",
    ) -> dict[str, Any]:
        preview = self.preview_agent_run(issue_id=issue_id, health_action=health_action)
        if preview["status"] != "ready":
            return {
                "authority": "health_system.agent_run_projection",
                "status": "blocked",
                "reason": preview.get("reason") or "health agent run preview is not ready",
                "preview": preview,
            }

        issue = self.get_issue(issue_id)
        if issue is None:
            raise KeyError(issue_id)
        flow = dict(preview.get("flow") or {})
        binding = dict(preview.get("binding") or {})
        task_selection = _build_health_runtime_task_selection(
            issue=issue.to_dict(),
            health_action=health_action,
            user_message=user_message,
            source=source,
        )
        task_id = f"task.health.{health_action}:{issue_id}:{int(time.time() * 1000)}"
        task_request = HealthTaskRequest(
            request_id=f"health-task-request:{health_action}:{issue_id}:{int(time.time() * 1000)}",
            issue_id=issue_id,
            task_kind=health_action,
            task_id=task_id,
            flow_id=str(flow.get("flow_id") or ""),
            required_evidence_refs=tuple(
                item
                for item in (
                    issue.conversation_ref,
                    *issue.runtime_trace_refs,
                    *issue.prompt_manifest_refs,
                    *issue.memory_refs,
                    *issue.assertion_refs,
                )
                if str(item or "").strip()
            ),
            requested_by=source,
            created_at=time.time(),
            metadata={
                "session_id": session_id or HEALTH_SESSION_ID,
                "selected_task_id": task_selection["selected_task_id"],
                "execution_owner": "AgentRuntime.run_stream",
            },
        )
        self.store.upsert_task_request(task_request)

        final_event: dict[str, Any] = {}
        runtime_events: list[dict[str, Any]] = []
        started_task_run: dict[str, Any] = {}
        async for event in agent_runtime.run_stream(
            AgentRunRequest(
                session_id=session_id or HEALTH_SESSION_ID,
                task_id=task_id,
                user_message=_build_health_runtime_user_message(
                    issue=issue.to_dict(),
                    health_action=health_action,
                    user_message=user_message,
                ),
                history=[],
                source=source,
                agent_runtime_chain=agent_runtime_chain,
                model_response_executor=model_response_executor,
                runtime_context_manager=runtime_context_manager,
                task_selection=task_selection,
                tool_runtime_executor=tool_runtime_executor,
                tool_instances=list(tool_instances or []),
            )
        ):
            item = dict(event or {})
            if item.get("type") == "runtime_loop_started":
                started_task_run = dict(item.get("task_run") or {})
            if item.get("type") == "runtime_loop_event":
                runtime_events.append(dict(item.get("event") or {}))
            if item.get("type") in {"done", "error"}:
                final_event = item

        task_run_id = str(started_task_run.get("task_run_id") or "")
        if not task_run_id:
            raise RuntimeError("Health agent runtime did not emit runtime_loop_started")
        finished_task_run = agent_runtime.get_task_run(task_run_id)
        if finished_task_run is None:
            raise RuntimeError(f"TaskRun missing from RuntimeStateIndex: {task_run_id}")

        final_content = str(final_event.get("content") or final_event.get("error") or "").strip()
        status = str(finished_task_run.status or ("failed" if final_event.get("type") == "error" else "completed"))
        terminal_reason = str(finished_task_run.terminal_reason or final_event.get("terminal_reason") or "")
        result_ref = f"health-result:{task_run_id}"
        task_result = dict(final_event.get("task_result") or {})
        result_payload = {
            "result_ref": result_ref,
            "issue_id": issue_id,
            "task_run_id": task_run_id,
            "health_action": health_action,
            "output_contract_id": str(flow.get("output_contract_id") or ""),
            "content": final_content,
            "task_result": task_result,
            "created_at": time.time(),
            "authority": "health_system.agent_result",
        }
        self._append_agent_result(result_payload)
        trace = agent_runtime.get_trace(task_run_id, include_payloads=True, include_model_messages=False)
        checkpoint_ref = str(finished_task_run.latest_checkpoint_ref or "")
        health_run = HealthAgentRun(
            run_id=f"health-run:{task_run_id}",
            request_id=task_request.request_id,
            issue_id=issue_id,
            task_run_id=task_run_id,
            agent_id=str(finished_task_run.agent_id or ""),
            agent_profile_id=str(finished_task_run.agent_profile_id or ""),
            runtime_lane=str(finished_task_run.runtime_lane or ""),
            health_action=health_action,
            workflow_id=str(binding.get("workflow_id") or ""),
            admission_status="accepted",
            projection_id=str(dict(finished_task_run.diagnostics or {}).get("projection_ref") or ""),
            prompt_manifest_id=str(dict(finished_task_run.diagnostics or {}).get("prompt_manifest_ref") or ""),
            status=status,
            terminal_reason=terminal_reason,
            blocked_reasons=((terminal_reason,) if status == "blocked" and terminal_reason else ()),
            report_refs=(),
            trace_refs=(task_run_id,),
            artifact_refs=tuple(item for item in (result_ref, checkpoint_ref) if item),
            result_ref=result_ref,
            created_at=float(finished_task_run.created_at or time.time()),
            metadata={
                "source": source,
                "flow_id": str(flow.get("flow_id") or ""),
                "selected_task_id": task_selection["selected_task_id"],
                "task_agent_binding_ref": str(binding.get("binding_id") or ""),
                "runtime_execution_owner": "AgentRuntime.run_stream",
                "configuration_source": "task_system_orchestration_config",
                "checkpoint_ref": checkpoint_ref,
                "latest_event_offset": finished_task_run.latest_event_offset,
                "event_count": agent_runtime.event_count(task_run_id),
                "final_content_chars": len(final_content),
            },
        )
        self._upsert_agent_run(health_run)
        return {
            "authority": "health_system.agent_run_projection",
            "status": status,
            "health_agent_run": health_run.to_dict(),
            "task_request": task_request.to_dict(),
            "task_run": finished_task_run.to_dict(),
            "events": runtime_events,
            "trace": trace,
            "issue": issue.to_dict(),
            "flow": flow,
            "binding": binding,
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
    ) -> dict[str, Any]:
        self.store.append_receipt(receipt)
        updated, response = self.command_builder.complete_command(
            command,
            receipt=receipt,
            report=report,
            issue=issue,
            run_result=run_result,
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

    async def _build_conversation_reply(
        self,
        *,
        session: HealthAgentConversationSession,
        user_message: HealthAgentConversationMessage,
        agent_runtime: Any,
        model_response_executor: Any,
        agent_runtime_chain: Any,
        runtime_context_manager: Any,
        tool_runtime_executor: Any | None = None,
        tool_instances: list[Any] | None = None,
    ) -> HealthAgentConversationMessage:
        now = time.time()
        issue_id = str(session.active_issue_ref or "").strip()
        if not issue_id and str(session.active_run_ref or "").strip():
            run = self.get_agent_run(session.active_run_ref)
            if run is not None and str(run.issue_id or "").strip():
                issue_id = str(run.issue_id)
        if not issue_id:
            return HealthAgentConversationMessage(
                message_id=f"health-agent-message-{int(now * 1000)}",
                session_id=session.session_id,
                role="assistant",
                content="当前会话还没有绑定健康问题，所以我没法做真实分析。请先绑定一个问题，或从已关联问题的运行进入对话。",
                created_at=now,
            )

        health_action = self._route_conversation_health_action(
            user_message=user_message.content,
            session=session,
        )
        session = self._refresh_conversation_session_mode(
            session,
            health_action=health_action,
            active_issue_ref=issue_id,
        )
        run_result = await self.execute_agent_run(
            issue_id=issue_id,
            health_action=health_action,
            session_id=session.session_id,
            source="health_system.conversation",
            agent_runtime=agent_runtime,
            model_response_executor=model_response_executor,
            agent_runtime_chain=agent_runtime_chain,
            runtime_context_manager=runtime_context_manager,
            tool_runtime_executor=tool_runtime_executor,
            tool_instances=tool_instances,
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
            message_id=f"health-agent-message-{int(time.time() * 1000)}",
            session_id=session.session_id,
            role="assistant",
            content=content,
            report_ref=str(result.get("result_ref") or ""),
            created_at=time.time(),
            receipt_ref=str(health_run.get("run_id") or ""),
        )

    def _route_conversation_health_action(
        self,
        *,
        user_message: str,
        session: HealthAgentConversationSession,
    ) -> str:
        normalized = str(user_message or "").strip().lower()
        if any(token in normalized for token in ("链路", "trace", "节点", "根因", "分析运行")):
            return "trace_analysis"
        session_workflow = str(session.workflow_id or "").strip()
        session_lane = str(session.runtime_lane or "").strip()
        if "trace_analysis" in session_workflow or "trace" in session_lane:
            return "trace_analysis"
        return "issue_triage"

    def _resolve_conversation_defaults(
        self,
        *,
        active_issue_ref: str,
        active_run_ref: str,
        health_action: str,
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
                    health_action=health_action,
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
        health_action: str,
        active_issue_ref: str,
    ) -> HealthAgentConversationSession:
        defaults = self._resolve_conversation_defaults(
            active_issue_ref=active_issue_ref,
            active_run_ref=session.active_run_ref,
            health_action=health_action,
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


def _build_health_runtime_task_selection(
    *,
    issue: dict[str, Any],
    health_action: str,
    user_message: str,
    source: str,
) -> dict[str, Any]:
    selected_task_id = health_specific_task_id(health_action)
    return {
        "selected_task_id": selected_task_id,
        "specific_task_id": selected_task_id,
        "health_action": health_action,
        "health_issue_ref": str(issue.get("issue_id") or ""),
        "health_issue": issue,
        "runtime_trace_refs": list(issue.get("runtime_trace_refs") or []),
        "prompt_manifest_refs": list(issue.get("prompt_manifest_refs") or []),
        "memory_refs": list(issue.get("memory_refs") or []),
        "assertion_refs": list(issue.get("assertion_refs") or []),
        "conversation_ref": str(issue.get("conversation_ref") or ""),
        "source": source,
        "explicit_inputs": {
            "health_issue_ref": str(issue.get("issue_id") or ""),
            "health_action": health_action,
            "user_question": str(user_message or ""),
            "evidence_refs": [
                item
                for item in (
                    str(issue.get("conversation_ref") or ""),
                    *[str(ref) for ref in list(issue.get("runtime_trace_refs") or [])],
                    *[str(ref) for ref in list(issue.get("prompt_manifest_refs") or [])],
                    *[str(ref) for ref in list(issue.get("memory_refs") or [])],
                    *[str(ref) for ref in list(issue.get("assertion_refs") or [])],
                )
                if item
            ],
        },
    }


def _build_health_runtime_user_message(
    *,
    issue: dict[str, Any],
    health_action: str,
    user_message: str,
) -> str:
    lines = [
        f"请执行健康系统任务：{health_action}。",
        f"健康问题：{issue.get('title') or issue.get('issue_id') or ''}",
        f"问题编号：{issue.get('issue_id') or ''}",
        f"归属系统：{issue.get('owner_system') or ''}",
        f"严重级别：{issue.get('severity') or ''}",
    ]
    if user_message:
        lines.append(f"用户当前问题：{user_message}")
    evidence_refs = [
        item
        for item in (
            str(issue.get("conversation_ref") or ""),
            *[str(ref) for ref in list(issue.get("runtime_trace_refs") or [])],
            *[str(ref) for ref in list(issue.get("prompt_manifest_refs") or [])],
            *[str(ref) for ref in list(issue.get("memory_refs") or [])],
            *[str(ref) for ref in list(issue.get("assertion_refs") or [])],
        )
        if item
    ]
    if evidence_refs:
        lines.append("可用证据引用：")
        lines.extend(f"- {ref}" for ref in evidence_refs)
    lines.extend(
        [
            "请只基于可见证据和本任务配置给出候选分析。",
            "如果证据不足，请明确说明缺少什么证据以及它会影响哪个结论。",
        ]
    )
    return "\n".join(lines)


def _safe_health_runtime_id(value: str) -> str:
    safe = "".join(char if char.isalnum() or char in {"-", "_", "."} else "-" for char in str(value or "").strip())
    return safe.strip("-") or f"health-agent-session-{int(time.time() * 1000)}"
