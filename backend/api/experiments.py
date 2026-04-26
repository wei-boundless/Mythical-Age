from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from experiments import experiment_runner

router = APIRouter()


class StartExperimentRequest(BaseModel):
    profile: str


@router.get("/experiments/profiles")
async def list_experiment_profiles() -> list[dict[str, object]]:
    return experiment_runner.profiles()


@router.get("/experiments/runs")
async def list_experiment_runs(limit: int = 20) -> list[dict[str, object]]:
    return experiment_runner.list_runs(limit=max(1, min(int(limit or 20), 100)))


@router.post("/experiments/runs")
async def start_experiment_run(payload: StartExperimentRequest) -> dict[str, object]:
    try:
        return experiment_runner.start(payload.profile)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/experiments/runs/{run_id}")
async def get_experiment_run(run_id: str) -> dict[str, object]:
    try:
        return experiment_runner.get_run(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/experiments/runs/{run_id}/artifacts")
async def get_experiment_artifacts(run_id: str) -> dict[str, object]:
    try:
        return experiment_runner.get_artifacts(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/experiments/runs/{run_id}/turns")
async def list_experiment_turns(run_id: str) -> list[dict[str, object]]:
    try:
        return experiment_runner.get_turns(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/experiments/runs/{run_id}/graph-overlay")
async def get_experiment_graph_overlay(run_id: str) -> dict[str, object]:
    try:
        return experiment_runner.get_graph_overlay(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/experiments/runs/{run_id}/turns/{turn_id}/graph-overlay")
async def get_experiment_turn_graph_overlay(run_id: str, turn_id: str) -> dict[str, object]:
    try:
        return experiment_runner.get_turn_graph_overlay(run_id, turn_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/experiments/runs/{run_id}/turns/{turn_id}/prompt-manifest")
async def get_experiment_turn_prompt_manifest(run_id: str, turn_id: str) -> dict[str, object]:
    try:
        return experiment_runner.get_turn_prompt_manifest(run_id, turn_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/experiments/runs/{run_id}/turns/{turn_id}/memory-trace")
async def get_experiment_turn_memory_trace(run_id: str, turn_id: str) -> dict[str, object]:
    try:
        return experiment_runner.get_turn_memory_trace(run_id, turn_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/experiments/runs/{run_id}/turns/{turn_id}/orchestration")
async def get_experiment_turn_orchestration(run_id: str, turn_id: str, artifact_path: str = "") -> dict[str, object]:
    try:
        return experiment_runner.get_turn_orchestration_snapshot(run_id, turn_id, artifact_path=artifact_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/experiments/runs/{run_id}/cancel")
async def cancel_experiment_run(run_id: str) -> dict[str, object]:
    try:
        return experiment_runner.cancel(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
