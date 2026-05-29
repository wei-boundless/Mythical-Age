from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.deps import require_runtime
from health_system import HealthRegistry
from health_system.governance import HealthGovernanceBuilder

router = APIRouter()


class HealthAgentRunPreviewRequest(BaseModel):
    health_action: str = Field(default="issue_triage")


class HealthAgentRunStartRequest(BaseModel):
    health_action: str = Field(default="issue_triage")
    session_id: str = Field(default="health-system")
    source: str = Field(default="health_system.manual")


class HealthIssueCreateRequest(BaseModel):
    title: str
    owner_system: str = Field(default="unknown")
    severity: str = Field(default="medium")
    status: str = Field(default="triage_ready")
    source: str = Field(default="manual")
    conversation_ref: str = Field(default="")
    runtime_trace_refs: list[str] = Field(default_factory=list)
    prompt_manifest_refs: list[str] = Field(default_factory=list)
    memory_refs: list[str] = Field(default_factory=list)
    assertion_refs: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class HealthManagementCommandRequest(BaseModel):
    command_type: str
    initiator_type: str = Field(default="user")
    initiator_ref: str = Field(default="")
    requested_by: str = Field(default="")
    source: str = Field(default="health_system.api")
    conversation_session_ref: str = Field(default="")
    target_scope: str = Field(default="")
    target_ref: str = Field(default="")
    health_action: str = Field(default="")
    payload: dict[str, Any] = Field(default_factory=dict)


class HealthTaskRecordPruneRequest(BaseModel):
    bucket: str = Field(default="static", max_length=40)
    task_run_ids: list[str] = Field(default_factory=list)
    dry_run: bool = Field(default=False)
    min_age_seconds: int = Field(default=24 * 60 * 60, ge=0)
    operation: str = Field(default="delete_expired", max_length=60)


class HealthAgentConversationSessionCreateRequest(BaseModel):
    active_issue_ref: str = Field(default="")
    active_run_ref: str = Field(default="")


class HealthAgentConversationMessageCreateRequest(BaseModel):
    role: str = Field(default="user")
    content: str
    command_ref: str = Field(default="")
    receipt_ref: str = Field(default="")
    report_ref: str = Field(default="")


@router.get("/health-system/overview")
async def health_system_overview() -> dict[str, Any]:
    runtime = require_runtime()
    return HealthGovernanceBuilder(runtime).build_overview()


@router.get("/health-system/tasks")
async def health_system_tasks(limit: int = 100) -> dict[str, Any]:
    runtime = require_runtime()
    return HealthGovernanceBuilder(runtime).build_tasks(limit=limit)


@router.get("/health-system/tasks/{task_run_id}")
async def health_system_task_detail(task_run_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    try:
        return HealthGovernanceBuilder(runtime).build_task_detail(task_run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown task run") from exc


@router.post("/health-system/task-records/prune")
async def health_system_prune_task_records(payload: HealthTaskRecordPruneRequest) -> dict[str, Any]:
    runtime = require_runtime()
    try:
        return HealthGovernanceBuilder(runtime).prune_task_records(
            bucket=payload.bucket,
            task_run_ids=payload.task_run_ids,
            dry_run=payload.dry_run,
            min_age_seconds=payload.min_age_seconds,
            operation=payload.operation,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/health-system/task-records/maintenance")
async def health_system_task_record_maintenance(
    bucket: str = "static",
    min_age_seconds: int = 24 * 60 * 60,
) -> dict[str, Any]:
    runtime = require_runtime()
    try:
        return HealthGovernanceBuilder(runtime).build_task_record_maintenance(
            bucket=bucket,
            min_age_seconds=max(0, int(min_age_seconds or 0)),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/health-system/risks")
async def health_system_risks(limit: int = 100) -> dict[str, Any]:
    runtime = require_runtime()
    return HealthGovernanceBuilder(runtime).build_risks(limit=limit)


@router.get("/health-system/system-risks")
async def health_system_system_risks() -> dict[str, Any]:
    runtime = require_runtime()
    return HealthGovernanceBuilder(runtime).build_system_risks()


@router.get("/health-system/monitor-governance")
async def health_system_monitor_governance() -> dict[str, Any]:
    runtime = require_runtime()
    return HealthGovernanceBuilder(runtime).build_monitor_governance()


@router.get("/health-system/token-usage")
async def health_system_token_usage(limit: int = 100) -> dict[str, Any]:
    runtime = require_runtime()
    return HealthGovernanceBuilder(runtime).build_token_usage(limit=limit)


@router.get("/health-system/efficiency")
async def health_system_efficiency(limit: int = 100) -> dict[str, Any]:
    runtime = require_runtime()
    return HealthGovernanceBuilder(runtime).build_efficiency(limit=limit)


@router.get("/health-system/commands")
async def health_system_commands() -> dict[str, Any]:
    runtime = require_runtime()
    registry = HealthRegistry(runtime.base_dir)
    return {"authority": "health_system.commands", "commands": [item.to_dict() for item in registry.list_commands()]}


@router.post("/health-system/commands")
async def health_system_submit_command(payload: HealthManagementCommandRequest) -> dict[str, Any]:
    runtime = require_runtime()
    try:
        return await HealthRegistry(runtime.base_dir).submit_command(
            payload.model_dump(),
            agent_runtime=runtime.query_runtime.agent_harness,
            model_response_executor=runtime.query_runtime.model_response_executor,
            tool_runtime_executor=runtime.query_runtime.tool_runtime_executor,
            tool_instances=runtime.query_runtime._all_tool_instances(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/health-system/commands/{command_id}")
async def health_system_command(command_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    command = HealthRegistry(runtime.base_dir).get_command(command_id)
    if command is None:
        raise HTTPException(status_code=404, detail="Unknown health command")
    return command.to_dict()


@router.get("/health-system/receipts/{receipt_id}")
async def health_system_receipt(receipt_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    receipt = HealthRegistry(runtime.base_dir).get_receipt(receipt_id)
    if receipt is None:
        raise HTTPException(status_code=404, detail="Unknown health receipt")
    return receipt.to_dict()


@router.get("/health-system/reports")
async def health_system_reports() -> dict[str, Any]:
    runtime = require_runtime()
    registry = HealthRegistry(runtime.base_dir)
    return {"authority": "health_system.reports", "reports": [item.to_dict() for item in registry.list_reports()]}


@router.get("/health-system/reports/{report_id}")
async def health_system_report(report_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    report = HealthRegistry(runtime.base_dir).get_report(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Unknown health report")
    return report.to_dict()


@router.post("/health-system/conversation-sessions")
async def health_system_create_conversation_session(
    payload: HealthAgentConversationSessionCreateRequest,
) -> dict[str, Any]:
    runtime = require_runtime()
    session = HealthRegistry(runtime.base_dir).create_conversation_session(payload.model_dump())
    return {
        "authority": "health_system.agent_conversation_session",
        "session": session.to_dict(),
        "messages": [],
    }


@router.get("/health-system/conversation-sessions/{session_id}")
async def health_system_conversation_session(session_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    registry = HealthRegistry(runtime.base_dir)
    session = registry.get_conversation_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Unknown health conversation session")
    return {
        "authority": "health_system.agent_conversation_session",
        "session": session.to_dict(),
        "messages": [item.to_dict() for item in registry.list_conversation_messages(session_id)],
    }


@router.post("/health-system/conversation-sessions/{session_id}/messages")
async def health_system_append_conversation_message(
    session_id: str,
    payload: HealthAgentConversationMessageCreateRequest,
) -> dict[str, Any]:
    runtime = require_runtime()
    registry = HealthRegistry(runtime.base_dir)
    try:
        response = await registry.respond_in_conversation(
            session_id,
            payload.model_dump(),
            agent_runtime=runtime.query_runtime.agent_harness,
            model_response_executor=runtime.query_runtime.model_response_executor,
            tool_runtime_executor=runtime.query_runtime.tool_runtime_executor,
            tool_instances=runtime.query_runtime._all_tool_instances(),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown health conversation session") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "authority": "health_system.agent_conversation_message",
        "message": response["message"].to_dict(),
        "assistant_message": (
            response["assistant_message"].to_dict() if response.get("assistant_message") is not None else None
        ),
    }


@router.get("/health-system/issues")
async def health_system_issues() -> dict[str, Any]:
    runtime = require_runtime()
    registry = HealthRegistry(runtime.base_dir)
    return {"authority": "health_system.issues", "issues": [item.to_dict() for item in registry.list_issues()]}


@router.post("/health-system/issues")
async def health_system_create_issue(payload: HealthIssueCreateRequest) -> dict[str, Any]:
    runtime = require_runtime()
    registry = HealthRegistry(runtime.base_dir)
    try:
        response = await registry.submit_command(
            {
                "command_type": "report_issue",
                "initiator_type": "user",
                "source": "health_system.issues_api",
                "payload": payload.model_dump(),
            },
            agent_runtime=runtime.query_runtime.agent_harness,
            model_response_executor=runtime.query_runtime.model_response_executor,
            tool_runtime_executor=runtime.query_runtime.tool_runtime_executor,
            tool_instances=runtime.query_runtime._all_tool_instances(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return dict(response.get("issue") or {})


@router.get("/health-system/issues/{issue_id}")
async def health_system_issue(issue_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    issue = HealthRegistry(runtime.base_dir).get_issue(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="Unknown health issue")
    return issue.to_dict()


@router.get("/health-system/agent-runs/{run_id}")
async def health_system_agent_run(run_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    run = HealthRegistry(runtime.base_dir).get_agent_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Unknown health agent run")
    return run.to_dict()


@router.get("/health-system/agent-runs/{run_id}/result")
async def health_system_agent_run_result(run_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    registry = HealthRegistry(runtime.base_dir)
    run = registry.get_agent_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Unknown health agent run")
    if not run.result_ref:
        raise HTTPException(status_code=404, detail="Health agent run has no result yet")
    result = registry.get_agent_result(run.result_ref)
    if result is None:
        raise HTTPException(status_code=404, detail="Health agent result not found")
    return result


@router.get("/health-system/agent-runs/{run_id}/trace-report")
async def health_system_agent_run_trace_report(run_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    try:
        return HealthRegistry(runtime.base_dir).build_agent_run_trace_report(
            run_id=run_id,
            agent_runtime=runtime.query_runtime.agent_harness,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown health agent run or trace") from exc


@router.post("/health-system/issues/{issue_id}/agent-runs/preview")
async def health_system_agent_run_preview(issue_id: str, payload: HealthAgentRunPreviewRequest) -> dict[str, Any]:
    runtime = require_runtime()
    try:
        return HealthRegistry(runtime.base_dir).preview_agent_run(issue_id=issue_id, health_action=payload.health_action)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown health issue or health action") from exc


@router.post("/health-system/issues/{issue_id}/agent-runs")
async def health_system_agent_run_start(issue_id: str, payload: HealthAgentRunStartRequest) -> dict[str, Any]:
    runtime = require_runtime()
    try:
        response = await HealthRegistry(runtime.base_dir).submit_command(
            {
                "command_type": "analyze_trace",
                "initiator_type": "user",
                "source": payload.source or "health_system.agent_runs_api",
                "conversation_session_ref": payload.session_id,
                "target_scope": "health_issue",
                "target_ref": issue_id,
                "health_action": payload.health_action,
            },
            agent_runtime=runtime.query_runtime.agent_harness,
            model_response_executor=runtime.query_runtime.model_response_executor,
            tool_runtime_executor=runtime.query_runtime.tool_runtime_executor,
            tool_instances=runtime.query_runtime._all_tool_instances(),
        )
        return dict(response.get("run_result") or response)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown health issue or health action") from exc


