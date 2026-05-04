from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.deps import require_runtime
from health_system import HealthRegistry
from health_system.maintenance.experiments import experiment_runner
from health_system.maintenance.test_system import test_system_service

router = APIRouter()


class HealthAgentRunPreviewRequest(BaseModel):
    task_mode: str = Field(default="issue_triage")


class HealthAgentRunStartRequest(BaseModel):
    task_mode: str = Field(default="issue_triage")
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
    task_mode: str = Field(default="")
    payload: dict[str, Any] = Field(default_factory=dict)


class HealthAgentConversationSessionCreateRequest(BaseModel):
    active_issue_ref: str = Field(default="")
    active_run_ref: str = Field(default="")


class HealthAgentConversationMessageCreateRequest(BaseModel):
    role: str = Field(default="user")
    content: str
    command_ref: str = Field(default="")
    receipt_ref: str = Field(default="")
    report_ref: str = Field(default="")


class StartTestRunRequest(BaseModel):
    profile: str
    scenario_ids: list[str] = Field(default_factory=list)


class CreateTestIssueRequest(BaseModel):
    title: str
    origin: str = Field(default="manual")
    owner_system: str = Field(default="test_system")
    severity: str = Field(default="medium")
    status: str = Field(default="open")
    observed: str = Field(default="")
    expected: str = Field(default="")
    reproduce: str = Field(default="")
    related_run_id: str = Field(default="")
    related_turn_id: str = Field(default="")
    related_task_id: str = Field(default="")
    related_session_id: str = Field(default="")
    related_skill: str = Field(default="")
    problem_node_id: str = Field(default="")
    problem_node_label: str = Field(default="")
    tags: list[str] = Field(default_factory=list)


class CreateTestCaseDraftRequest(BaseModel):
    title: str
    layer: str = Field(default="functional")
    owner_system: str = Field(default="test_system")
    source_issue_id: str = Field(default="")
    source_run_id: str = Field(default="")
    source_turn_id: str = Field(default="")
    trigger: str = Field(default="")
    expected: str = Field(default="")
    assertions: list[str] | str = Field(default_factory=list)
    profile: str = Field(default="functional")
    status: str = Field(default="draft")


class CreateManagedTestCaseRequest(BaseModel):
    case_id: str = Field(default="")
    title: str
    layer: str = Field(default="functional")
    path: str = Field(default="")
    owner_system: str = Field(default="test_system")
    runner: str = Field(default="pytest")
    status: str = Field(default="candidate")
    profiles: list[str] | str = Field(default_factory=list)
    description: str = Field(default="")
    problem_statement: str = Field(default="")
    pass_criteria: list[str] | str = Field(default_factory=list)
    scenario_turns: list[dict[str, Any]] = Field(default_factory=list)
    assertions: list[str] | str = Field(default_factory=list)
    tags: list[str] | str = Field(default_factory=list)
    source_template_id: str = Field(default="")


class StartExperimentRequest(BaseModel):
    profile: str


@router.get("/health-system/overview")
async def health_system_overview() -> dict[str, Any]:
    runtime = require_runtime()
    return HealthRegistry(runtime.base_dir).build_overview()


@router.get("/health-system/maintenance/test-system/profiles")
async def list_health_test_profiles() -> list[dict[str, Any]]:
    return test_system_service.profiles()


@router.get("/health-system/maintenance/test-system/cases")
async def list_health_test_cases() -> dict[str, Any]:
    return test_system_service.cases()


@router.get("/health-system/maintenance/test-system/agent/report")
async def get_health_test_agent_report() -> dict[str, Any]:
    return test_system_service.agent_report()


@router.get("/health-system/maintenance/test-system/harness-records")
async def get_health_test_harness_records() -> dict[str, Any]:
    return test_system_service.harness_records()


@router.get("/health-system/maintenance/test-system/harness-map")
async def get_health_test_harness_map() -> dict[str, Any]:
    return test_system_service.harness_map()


@router.get("/health-system/maintenance/test-system/case-templates")
async def get_health_test_case_templates() -> dict[str, Any]:
    return test_system_service.case_templates()


@router.get("/health-system/maintenance/test-system/long-scenarios")
async def list_health_long_scenarios() -> dict[str, Any]:
    return test_system_service.long_scenarios()


@router.post("/health-system/maintenance/test-system/issues")
async def create_health_test_issue(payload: CreateTestIssueRequest) -> dict[str, Any]:
    return test_system_service.create_issue(payload.model_dump())


@router.post("/health-system/maintenance/test-system/case-drafts")
async def create_health_test_case_draft(payload: CreateTestCaseDraftRequest) -> dict[str, Any]:
    return test_system_service.create_case_draft(payload.model_dump())


@router.post("/health-system/maintenance/test-system/managed-cases")
async def create_health_managed_test_case(payload: CreateManagedTestCaseRequest) -> dict[str, Any]:
    return test_system_service.create_managed_case(payload.model_dump())


@router.delete("/health-system/maintenance/test-system/managed-cases/{case_id}")
async def delete_health_managed_test_case(case_id: str) -> dict[str, Any]:
    try:
        return test_system_service.delete_managed_case(case_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/health-system/maintenance/test-system/runs")
async def list_health_test_runs(limit: int = 20) -> list[dict[str, Any]]:
    return test_system_service.list_runs(limit=max(1, min(int(limit or 20), 100)))


@router.post("/health-system/maintenance/test-system/runs")
async def start_health_test_run(payload: StartTestRunRequest) -> dict[str, Any]:
    try:
        return test_system_service.start(payload.profile, scenario_ids=payload.scenario_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/health-system/maintenance/test-system/runs/{run_id}")
async def get_health_test_run(run_id: str) -> dict[str, Any]:
    try:
        return test_system_service.get_run(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/health-system/maintenance/test-system/runs/{run_id}/cancel")
async def cancel_health_test_run(run_id: str) -> dict[str, Any]:
    try:
        return test_system_service.cancel(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/health-system/maintenance/test-system/runs/{run_id}/artifacts")
async def get_health_test_artifacts(run_id: str) -> dict[str, Any]:
    try:
        return test_system_service.get_artifacts(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/health-system/maintenance/test-system/runs/{run_id}/turns")
async def list_health_test_turns(run_id: str) -> list[dict[str, Any]]:
    try:
        return test_system_service.get_turns(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/health-system/maintenance/test-system/runs/{run_id}/turns/{turn_id}/runtime-loop")
async def get_health_test_turn_runtime_loop(run_id: str, turn_id: str) -> dict[str, Any]:
    try:
        return test_system_service.get_turn_runtime_loop(run_id, turn_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/health-system/maintenance/test-system/runtime-loop/task-runs/{task_run_id}/monitor")
async def get_health_task_run_monitor(task_run_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    try:
        return test_system_service.get_task_run_monitor(
            task_run_id,
            runtime_loop=runtime.query_runtime.task_run_loop,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/health-system/maintenance/experiments/profiles")
async def list_health_experiment_profiles() -> list[dict[str, object]]:
    return experiment_runner.profiles()


@router.get("/health-system/maintenance/experiments/runs")
async def list_health_experiment_runs(limit: int = 20) -> list[dict[str, object]]:
    return experiment_runner.list_runs(limit=max(1, min(int(limit or 20), 100)))


@router.post("/health-system/maintenance/experiments/runs")
async def start_health_experiment_run(payload: StartExperimentRequest) -> dict[str, object]:
    try:
        return experiment_runner.start(payload.profile)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/health-system/maintenance/experiments/runs/{run_id}")
async def get_health_experiment_run(run_id: str) -> dict[str, object]:
    try:
        return experiment_runner.get_run(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/health-system/maintenance/experiments/runs/{run_id}/artifacts")
async def get_health_experiment_artifacts(run_id: str) -> dict[str, object]:
    try:
        return experiment_runner.get_artifacts(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/health-system/maintenance/experiments/runs/{run_id}/turns")
async def list_health_experiment_turns(run_id: str) -> list[dict[str, object]]:
    try:
        return experiment_runner.get_turns(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/health-system/maintenance/experiments/runs/{run_id}/graph-overlay")
async def get_health_experiment_graph_overlay(run_id: str) -> dict[str, object]:
    try:
        return experiment_runner.get_graph_overlay(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/health-system/maintenance/experiments/runs/{run_id}/turns/{turn_id}/graph-overlay")
async def get_health_experiment_turn_graph_overlay(run_id: str, turn_id: str) -> dict[str, object]:
    try:
        return experiment_runner.get_turn_graph_overlay(run_id, turn_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/health-system/maintenance/experiments/runs/{run_id}/turns/{turn_id}/prompt-manifest")
async def get_health_experiment_turn_prompt_manifest(run_id: str, turn_id: str) -> dict[str, object]:
    try:
        return experiment_runner.get_turn_prompt_manifest(run_id, turn_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/health-system/maintenance/experiments/runs/{run_id}/turns/{turn_id}/memory-trace")
async def get_health_experiment_turn_memory_trace(run_id: str, turn_id: str) -> dict[str, object]:
    try:
        return experiment_runner.get_turn_memory_trace(run_id, turn_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/health-system/maintenance/experiments/runs/{run_id}/turns/{turn_id}/orchestration")
async def get_health_experiment_turn_orchestration(
    run_id: str,
    turn_id: str,
    artifact_path: str = "",
) -> dict[str, object]:
    try:
        return experiment_runner.get_turn_orchestration_snapshot(run_id, turn_id, artifact_path=artifact_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/health-system/maintenance/experiments/runs/{run_id}/cancel")
async def cancel_health_experiment_run(run_id: str) -> dict[str, object]:
    try:
        return experiment_runner.cancel(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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
            task_run_loop=runtime.query_runtime.task_run_loop,
            model_response_executor=runtime.query_runtime.model_response_executor,
            test_system_service=test_system_service,
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


@router.get("/health-system/test-scenarios")
async def health_system_test_scenarios() -> dict[str, Any]:
    runtime = require_runtime()
    registry = HealthRegistry(runtime.base_dir)
    return {
        "authority": "health_system.test_scenarios",
        "scenarios": registry.list_health_test_scenarios(),
    }


@router.get("/health-system/test-runs")
async def health_system_test_runs() -> dict[str, Any]:
    runtime = require_runtime()
    registry = HealthRegistry(runtime.base_dir)
    return {
        "authority": "health_system.test_runs",
        "health_test_runs": [item.to_dict() for item in registry.list_health_test_runs()],
    }


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
        message = registry.append_conversation_message(session_id, payload.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown health conversation session") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "authority": "health_system.agent_conversation_message",
        "message": message.to_dict(),
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
                "source": "health_system.issues_compat_api",
                "payload": payload.model_dump(),
            },
            task_run_loop=runtime.query_runtime.task_run_loop,
            model_response_executor=runtime.query_runtime.model_response_executor,
            test_system_service=test_system_service,
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
            task_run_loop=runtime.query_runtime.task_run_loop,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown health agent run or trace") from exc


@router.post("/health-system/issues/{issue_id}/agent-runs/preview")
async def health_system_agent_run_preview(issue_id: str, payload: HealthAgentRunPreviewRequest) -> dict[str, Any]:
    runtime = require_runtime()
    try:
        return HealthRegistry(runtime.base_dir).preview_agent_run(issue_id=issue_id, task_mode=payload.task_mode)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown health issue or task mode") from exc


@router.post("/health-system/issues/{issue_id}/agent-runs")
async def health_system_agent_run_start(issue_id: str, payload: HealthAgentRunStartRequest) -> dict[str, Any]:
    runtime = require_runtime()
    try:
        response = await HealthRegistry(runtime.base_dir).submit_command(
            {
                "command_type": "analyze_trace",
                "initiator_type": "user",
                "source": payload.source or "health_system.agent_runs_compat_api",
                "conversation_session_ref": payload.session_id,
                "target_scope": "health_issue",
                "target_ref": issue_id,
                "task_mode": payload.task_mode,
            },
            task_run_loop=runtime.query_runtime.task_run_loop,
            model_response_executor=runtime.query_runtime.model_response_executor,
            test_system_service=test_system_service,
        )
        return dict(response.get("run_result") or response)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown health issue or task mode") from exc
