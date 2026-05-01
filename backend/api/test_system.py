from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.deps import require_runtime
from test_system import test_system_service

router = APIRouter()


class StartTestRunRequest(BaseModel):
    profile: str
    scenario_ids: list[str] = []


class CreateTestIssueRequest(BaseModel):
    title: str
    origin: str = "manual"
    owner_system: str = "test_system"
    severity: str = "medium"
    status: str = "open"
    observed: str = ""
    expected: str = ""
    reproduce: str = ""
    related_run_id: str = ""
    related_turn_id: str = ""
    related_task_id: str = ""
    related_session_id: str = ""
    related_skill: str = ""
    problem_node_id: str = ""
    problem_node_label: str = ""
    tags: list[str] = []


class CreateTestCaseDraftRequest(BaseModel):
    title: str
    layer: str = "functional"
    owner_system: str = "test_system"
    source_issue_id: str = ""
    source_run_id: str = ""
    source_turn_id: str = ""
    trigger: str = ""
    expected: str = ""
    assertions: list[str] | str = []
    profile: str = "functional"
    status: str = "draft"


class CreateManagedTestCaseRequest(BaseModel):
    case_id: str = ""
    title: str
    layer: str = "functional"
    path: str = ""
    owner_system: str = "test_system"
    runner: str = "pytest"
    status: str = "candidate"
    profiles: list[str] | str = []
    description: str = ""
    problem_statement: str = ""
    pass_criteria: list[str] | str = []
    scenario_turns: list[dict[str, Any]] = []
    assertions: list[str] | str = []
    tags: list[str] | str = []
    source_template_id: str = ""


@router.get("/test-system/profiles")
async def list_test_profiles() -> list[dict[str, Any]]:
    return test_system_service.profiles()


@router.get("/test-system/cases")
async def list_test_cases(include_legacy: bool = True) -> dict[str, Any]:
    return test_system_service.cases(include_legacy=include_legacy)


@router.get("/test-system/agent/report")
async def get_test_agent_report() -> dict[str, Any]:
    return test_system_service.agent_report()


@router.get("/test-system/harness-records")
async def get_test_harness_records() -> dict[str, Any]:
    return test_system_service.harness_records()


@router.get("/test-system/harness-map")
async def get_test_harness_map() -> dict[str, Any]:
    return test_system_service.harness_map()


@router.get("/test-system/case-templates")
async def get_test_case_templates() -> dict[str, Any]:
    return test_system_service.case_templates()


@router.get("/test-system/long-scenarios")
async def list_long_scenarios() -> dict[str, Any]:
    return test_system_service.long_scenarios()


@router.post("/test-system/issues")
async def create_test_issue(payload: CreateTestIssueRequest) -> dict[str, Any]:
    return test_system_service.create_issue(payload.model_dump())


@router.post("/test-system/case-drafts")
async def create_test_case_draft(payload: CreateTestCaseDraftRequest) -> dict[str, Any]:
    return test_system_service.create_case_draft(payload.model_dump())


@router.post("/test-system/managed-cases")
async def create_managed_test_case(payload: CreateManagedTestCaseRequest) -> dict[str, Any]:
    return test_system_service.create_managed_case(payload.model_dump())


@router.delete("/test-system/managed-cases/{case_id}")
async def delete_managed_test_case(case_id: str) -> dict[str, Any]:
    try:
        return test_system_service.delete_managed_case(case_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/test-system/runs")
async def list_test_runs(limit: int = 20) -> list[dict[str, Any]]:
    return test_system_service.list_runs(limit=max(1, min(int(limit or 20), 100)))


@router.post("/test-system/runs")
async def start_test_run(payload: StartTestRunRequest) -> dict[str, Any]:
    try:
        return test_system_service.start(payload.profile, scenario_ids=payload.scenario_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/test-system/runs/{run_id}")
async def get_test_run(run_id: str) -> dict[str, Any]:
    try:
        return test_system_service.get_run(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/test-system/runs/{run_id}/cancel")
async def cancel_test_run(run_id: str) -> dict[str, Any]:
    try:
        return test_system_service.cancel(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/test-system/runs/{run_id}/artifacts")
async def get_test_artifacts(run_id: str) -> dict[str, Any]:
    try:
        return test_system_service.get_artifacts(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/test-system/runs/{run_id}/turns")
async def list_test_turns(run_id: str) -> list[dict[str, Any]]:
    try:
        return test_system_service.get_turns(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/test-system/runs/{run_id}/turns/{turn_id}/runtime-loop")
async def get_test_turn_runtime_loop(run_id: str, turn_id: str) -> dict[str, Any]:
    try:
        return test_system_service.get_turn_runtime_loop(run_id, turn_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/test-system/runtime-loop/task-runs/{task_run_id}/monitor")
async def get_task_run_monitor(task_run_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    try:
        return test_system_service.get_task_run_monitor(
            task_run_id,
            runtime_loop=runtime.query_runtime.task_run_loop,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
