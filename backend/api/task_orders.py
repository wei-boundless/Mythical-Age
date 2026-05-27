from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from api.deps import require_runtime
from sessions import validate_session_id
from task_system.registry.flow_registry import TaskFlowRegistry
from task_system.orders.api_models import TaskOrderCreateRequest
from task_system.orders.legacy_runtime_adapter import attach_legacy_runtime_read_model
from task_system.orders.order_factory import TaskOrderFactory
from task_system.orders.order_registry import TaskOrderRegistry

router = APIRouter()


def _state_index():
    runtime = require_runtime()
    return runtime.query_runtime.harness_service_host.state_index


def _query_runtime():
    return require_runtime().query_runtime


@router.post("/tasks/orders")
async def create_task_order(payload: TaskOrderCreateRequest):
    runtime = _query_runtime()
    session_id = validate_session_id(payload.session_id)
    task_id = str(
        payload.task_id
        or payload.task_selection.get("selected_task_id")
        or payload.task_order_intent.get("task_id")
        or ""
    ).strip()
    if not task_id:
        raise HTTPException(status_code=400, detail="task_id is required")

    flow_registry = TaskFlowRegistry(runtime.base_dir)
    task_record = flow_registry.get_specific_task_record(task_id)
    if task_record is None:
        raise HTTPException(status_code=404, detail="Specific task not found")
    if not task_record.enabled:
        raise HTTPException(status_code=409, detail="Specific task is disabled")

    flow_contract_binding = flow_registry.get_flow_contract_binding(task_id)
    execution_policy = flow_registry.get_task_execution_policy(task_id)
    creation = TaskOrderFactory().create_specific_task_order(
        session_id=session_id,
        task_record=task_record.to_dict(),
        objective=str(payload.objective or payload.message or task_record.task_title).strip(),
        source=str(payload.source or "task_library").strip() or "task_library",
        source_ref=str(payload.source_ref or f"task_system.specific_task:{task_id}").strip(),
        environment_id=str(
            payload.environment_id
            or getattr(task_record, "environment_id", "")
            or task_record.metadata.get("environment_id")
            or "env.general_workspace"
        ).strip(),
        flow_contract_binding=flow_contract_binding.to_dict() if flow_contract_binding is not None else None,
        execution_policy=execution_policy.to_dict() if execution_policy is not None else None,
        order_intent=dict(payload.task_order_intent or {}),
        idempotency_key=str(payload.idempotency_key or "").strip(),
    )
    creation = attach_legacy_runtime_read_model(creation)
    TaskOrderRegistry(runtime.harness_service_host.state_index).upsert_creation(creation)
    return {
        **creation.projection(),
        "authority": "task_system.task_orders_api",
    }


@router.get("/tasks/orders")
async def list_task_orders(session_id: str | None = Query(default=None)):
    state_index = _state_index()
    orders = (
        state_index.list_session_task_orders(session_id)
        if session_id
        else state_index.list_task_orders()
    )
    return {
        "orders": [item.to_dict() for item in orders],
        "count": len(orders),
        "session_id": session_id or "",
        "authority": "task_system.task_orders_api",
    }


@router.get("/tasks/orders/{order_id}")
async def get_task_order(order_id: str):
    state_index = _state_index()
    order = state_index.get_task_order(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Task order not found")
    return {
        "order": order.to_dict(),
        "runs": [item.to_dict() for item in state_index.list_order_runs(order_id)],
        "authority": "task_system.task_orders_api",
    }


@router.get("/tasks/order-runs/{run_id}")
async def get_task_order_run(run_id: str):
    state_index = _state_index()
    run = state_index.get_task_order_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Task order run not found")
    order = state_index.get_task_order(run.order_id)
    channel = state_index.get_execution_channel_by_order_run(run.run_id)
    envelope = state_index.get_task_execution_envelope_by_order_run(run.run_id)
    return {
        "order": order.to_dict() if order is not None else None,
        "run": run.to_dict(),
        "execution_channel": channel.to_dict() if channel is not None else None,
        "task_execution_envelope": envelope.to_dict() if envelope is not None else None,
        "authority": "task_system.task_orders_api",
    }


@router.get("/tasks/order-runs/by-task-run/{task_run_id}")
async def get_task_order_run_by_task_run(task_run_id: str):
    state_index = _state_index()
    projection = state_index.task_order_projection_for_task_run(task_run_id)
    if projection is None:
        raise HTTPException(status_code=404, detail="Task order run binding not found")
    return projection


@router.get("/tasks/order-runs/{run_id}/monitor")
async def get_task_order_run_monitor(run_id: str):
    runtime = require_runtime()
    state_index = runtime.query_runtime.harness_service_host.state_index
    run = state_index.get_task_order_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Task order run not found")
    monitor = (
        runtime.query_runtime.harness_service_host.get_task_run_live_monitor(run.task_run_id)
        if run.task_run_id
        else None
    )
    return {
        "task_order_projection": state_index.task_order_projection_for_task_run(run.task_run_id) if run.task_run_id else None,
        "monitor": monitor,
        "authority": "task_system.task_order_run_monitor_api",
    }
