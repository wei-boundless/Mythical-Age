from __future__ import annotations

import asyncio
import hashlib
import json
import re
import shutil
import threading
import time
from typing import Any
from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.deps import require_runtime
from capability_system import build_default_operation_registry
from capability_system import build_capability_catalog, build_orchestration_capability_items
from orchestration import (
    AgentGroupRegistry,
    AgentRegistry,
    AgentRuntimeRegistry,
    ControlKernel,
    CoordinationRun,
    TaskContract,
    default_worker_agent_blueprints,
    build_base_unit_catalog,
)
from orchestration.runtime_lane_registry import DEFAULT_RUNTIME_LANE_REGISTRY, runtime_lane_option_payloads
from orchestration.model_profile_resolver import build_provider_catalog
from orchestration.resource_inventory import build_runtime_resource_inventory
from runtime import TaskRun
from runtime.coordination_runtime.review_gate_verdict import (
    extract_review_verdict,
    review_verdict_is_accepted,
)
from runtime.shared.models import AgentRun, CoordinationRun as RuntimeCoordinationRun
from runtime.coordination_runtime.runtime import LangGraphCoordinationRuntimeResult
from runtime.shared.protocol_boundary import is_internal_protocol_input_key
from orchestration.delegation_catalog import DelegationCatalogBuilder
from understanding import analyze_memory_intent
from task_system.compiler.coordination_graph_compiler import compile_task_graph_definition_runtime_spec
from task_system import TaskFlowRegistry
from sessions import InvalidSessionId, validate_session_id

router = APIRouter()


_STAGE_EXECUTION_SCHEDULE_LOCK = threading.RLock()
_STAGE_EXECUTION_INFLIGHT: dict[str, dict[str, Any]] = {}


async def _execute_stage_request_in_background(
    *,
    runtime: Any,
    session_id: str,
    source: str,
    stage_execution_request: Any,
    current_turn_context: dict[str, Any] | None = None,
) -> None:
    if str(getattr(stage_execution_request, "executor_type", "") or "") == "graph_module":
        _start_graph_module_stage_request(
            runtime=runtime,
            session_id=session_id,
            source=source,
            stage_execution_request=stage_execution_request,
            current_turn_context=current_turn_context,
        )
        return
    continuation_payload = LangGraphCoordinationRuntimeResult(
        stage_execution_request=stage_execution_request,
    ).continuation_payload(
        session_id=session_id,
        current_turn_context=dict(current_turn_context or {}),
    )
    if not continuation_payload:
        return
    async for _event in runtime.query_runtime.task_run_loop._continue_coordination_delivery_stream(
        session_id=session_id,
        history=runtime.query_runtime.session_manager.load_session_for_agent(
            session_id,
            include_compressed_context=False,
        ),
        source=source,
        agent_runtime_chain=runtime.query_runtime.agent_runtime_chain,
        model_response_executor=runtime.query_runtime.model_response_executor,
        runtime_context_manager=runtime.query_runtime.runtime_context_manager,
        stage_projection_cycle=None,
        memory_intent=analyze_memory_intent(stage_execution_request.message),
        assistant_message_committer=lambda _payload: None,
        tool_runtime_executor=runtime.query_runtime.tool_runtime_executor,
        tool_instances=runtime.query_runtime._all_tool_instances(),
        agent_runtime_profile=runtime.query_runtime.agent_runtime_registry.get_profile(stage_execution_request.agent_id),
        continuation_payload=continuation_payload,
    ):
        pass


def _schedule_stage_execution_background(
    *,
    runtime: Any,
    session_id: str,
    source: str,
    stage_execution_request: Any,
    current_turn_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    task_run_loop = runtime.query_runtime.task_run_loop
    identity = _stage_execution_schedule_identity(stage_execution_request)
    schedule_key = str(identity.get("schedule_key") or "")
    with _STAGE_EXECUTION_SCHEDULE_LOCK:
        existing = _matching_stage_execution_task_run(
            task_run_loop=task_run_loop,
            session_id=session_id,
            identity=identity,
        )
        if existing is not None:
            result = {
                "background_started": False,
                "reason": "stage_execution_already_has_effective_task_run",
                "existing_task_run_id": existing.task_run_id,
                "existing_status": existing.status,
                "stage_execution_identity": identity,
            }
            _append_stage_execution_schedule_event(
                task_run_loop=task_run_loop,
                root_task_run_id=str(stage_execution_request.root_task_run_id or ""),
                event_type="coordination_stage_background_execution_skipped",
                payload={**result, "source": source},
                identity=identity,
            )
            return result
        if schedule_key and schedule_key in _STAGE_EXECUTION_INFLIGHT:
            inflight = dict(_STAGE_EXECUTION_INFLIGHT.get(schedule_key) or {})
            result = {
                "background_started": False,
                "reason": "stage_execution_already_scheduled",
                "existing_task_run_id": str(inflight.get("task_run_id") or ""),
                "existing_status": "scheduled",
                "stage_execution_identity": identity,
            }
            _append_stage_execution_schedule_event(
                task_run_loop=task_run_loop,
                root_task_run_id=str(stage_execution_request.root_task_run_id or ""),
                event_type="coordination_stage_background_execution_skipped",
                payload={**result, "source": source},
                identity=identity,
            )
            return result
        if schedule_key:
            _STAGE_EXECUTION_INFLIGHT[schedule_key] = {
                "coordination_run_id": identity.get("coordination_run_id"),
                "stage_id": identity.get("stage_id"),
                "request_id": identity.get("request_id"),
                "idempotency_key": identity.get("idempotency_key"),
                "scheduled_at": time.time(),
                "source": source,
            }

    def runner() -> None:
        try:
            asyncio.run(
                _execute_stage_request_in_background(
                    runtime=runtime,
                    session_id=session_id,
                    source=source,
                    stage_execution_request=stage_execution_request,
                    current_turn_context=current_turn_context,
                )
            )
        except Exception as exc:
            task_run_loop.event_log.append(
                stage_execution_request.root_task_run_id,
                "coordination_stage_background_execution_failed",
                payload={
                    "coordination_run_id": stage_execution_request.coordination_run_id,
                    "stage_id": stage_execution_request.stage_id,
                    "task_ref": stage_execution_request.task_ref,
                    "error": str(exc),
                    "error_type": exc.__class__.__name__,
                    "source": source,
                },
                refs={
                    "coordination_run_ref": stage_execution_request.coordination_run_id,
                    "stage_id": stage_execution_request.stage_id,
                },
            )
        finally:
            if schedule_key:
                with _STAGE_EXECUTION_SCHEDULE_LOCK:
                    _STAGE_EXECUTION_INFLIGHT.pop(schedule_key, None)

    thread = threading.Thread(
        target=runner,
        name=f"taskgraph-node-{str(stage_execution_request.stage_id or 'unknown')}",
        daemon=True,
    )
    thread.start()
    result = {
        "background_started": True,
        "reason": "scheduled",
        "existing_task_run_id": "",
        "existing_status": "",
        "stage_execution_identity": identity,
    }
    _append_stage_execution_schedule_event(
        task_run_loop=task_run_loop,
        root_task_run_id=str(stage_execution_request.root_task_run_id or ""),
        event_type="coordination_stage_background_execution_scheduled",
        payload={**result, "source": source},
        identity=identity,
    )
    return result


def _stage_execution_schedule_identity(stage_execution_request: Any) -> dict[str, Any]:
    from runtime.execution.node_execution_request import build_node_execution_idempotency_key

    payload = (
        stage_execution_request.to_dict()
        if hasattr(stage_execution_request, "to_dict")
        else dict(stage_execution_request or {})
    )
    stage_id = str(payload.get("stage_id") or payload.get("node_id") or "").strip()
    node_id = str(payload.get("node_id") or stage_id).strip()
    coordination_run_id = str(payload.get("coordination_run_id") or "").strip()
    request_id = str(payload.get("request_id") or "").strip()
    idempotency_key = str(payload.get("idempotency_key") or "").strip()
    if not idempotency_key:
        idempotency_key = build_node_execution_idempotency_key(
            coordination_run_id=coordination_run_id,
            node_id=node_id,
            explicit_inputs=dict(payload.get("explicit_inputs") or {}),
            dispatch_context=dict(payload.get("dispatch_context") or {}),
        )
    schedule_key = "|".join(
        [
            coordination_run_id,
            stage_id,
            idempotency_key or request_id,
        ]
    )
    return {
        "coordination_run_id": coordination_run_id,
        "root_task_run_id": str(payload.get("root_task_run_id") or "").strip(),
        "stage_id": stage_id,
        "node_id": node_id,
        "task_ref": str(payload.get("task_ref") or "").strip(),
        "request_id": request_id,
        "idempotency_key": idempotency_key,
        "dispatch_event_id": str(dict(payload.get("dispatch_context") or {}).get("dispatch_event_id") or "").strip(),
        "schedule_key": schedule_key,
    }


def _start_graph_module_stage_request(
    *,
    runtime: Any,
    session_id: str,
    source: str,
    stage_execution_request: Any,
    current_turn_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    task_run_loop = runtime.query_runtime.task_run_loop
    request_payload = (
        stage_execution_request.to_dict()
        if hasattr(stage_execution_request, "to_dict")
        else dict(stage_execution_request or {})
    )
    identity = _stage_execution_schedule_identity(stage_execution_request)
    handle = _graph_module_runtime_handle_from_request(request_payload)
    linked_graph_id = str(handle.get("linked_graph_id") or "").strip()
    if not linked_graph_id:
        raise ValueError("GraphModule stage request requires linked_graph_id")
    registry = TaskFlowRegistry(runtime.base_dir)
    graph = registry.get_task_graph(linked_graph_id)
    if graph is None:
        raise ValueError(f"GraphModule linked TaskGraph not found: {linked_graph_id}")
    if str(graph.publish_state or "") != "published":
        raise ValueError(f"GraphModule linked TaskGraph must be published before run start: {linked_graph_id}")
    protocol = registry.get_task_communication_protocol(
        str(graph.default_protocol_id or dict(graph.metadata or {}).get("protocol_id") or "")
    )
    runtime_spec = compile_task_graph_definition_runtime_spec(
        graph=graph,
        specific_tasks=tuple(registry.list_specific_task_records()),
        communication_protocol=protocol,
    )
    blocking_issues = [issue.to_dict() for issue in runtime_spec.issues if issue.severity == "error"]
    if blocking_issues:
        raise ValueError(f"GraphModule imported runtime spec has blocking issues: {blocking_issues}")
    importing_runtime_handle = {
        key: value
        for key, value in dict(handle).items()
        if key not in {"explicit_inputs", "standard_input_package"}
    }
    imported_initial_inputs = {
        str(key): value
        for key, value in dict(handle.get("explicit_inputs") or {}).items()
        if not is_internal_protocol_input_key(str(key))
    }
    diagnostics = {
        "source": "orchestration.graph_module_stage_request",
        "graph_module_imported_run": True,
        "graph_module_runtime_handle_id": str(handle.get("handle_id") or ""),
        "importing_graph_module_runtime_handle": importing_runtime_handle,
        "importing_stage_execution_request": request_payload,
        "importing_standard_input_package": dict(
            handle.get("standard_input_package")
            or request_payload.get("standard_input_package")
            or {}
        ),
        "linked_graph_id": linked_graph_id,
        "importing_graph_id": str(handle.get("importing_graph_id") or ""),
        "importing_coordination_run_id": str(handle.get("importing_coordination_run_id") or identity.get("coordination_run_id") or ""),
        "importing_root_task_run_id": str(handle.get("importing_root_task_run_id") or request_payload.get("root_task_run_id") or ""),
        "importing_stage_id": str(handle.get("importing_stage_id") or identity.get("stage_id") or ""),
        "importing_node_id": str(handle.get("importing_node_id") or identity.get("node_id") or ""),
        "importing_task_ref": str(request_payload.get("task_ref") or identity.get("task_ref") or ""),
        "importing_stage_request_id": str(identity.get("request_id") or ""),
        "importing_stage_idempotency_key": str(identity.get("idempotency_key") or ""),
        "importing_dispatch_event_id": str(identity.get("dispatch_event_id") or ""),
        "importing_source": source,
        "stage_id": str(identity.get("stage_id") or ""),
        "coordination_stage_id": str(identity.get("stage_id") or ""),
        "coordination_run_id": str(identity.get("coordination_run_id") or ""),
        "stage_request_id": str(identity.get("request_id") or ""),
        "stage_idempotency_key": str(identity.get("idempotency_key") or ""),
        "current_turn_context": dict(current_turn_context or {}),
    }
    start = task_run_loop.start_task_graph_run(
        session_id=session_id,
        task_id=f"task_graph.graph_module.{linked_graph_id}",
        graph=graph,
        runtime_spec=runtime_spec,
        initial_inputs=imported_initial_inputs,
        diagnostics=diagnostics,
    )
    imported_coordination_run_id = start.coordination_run.coordination_run_id if start.coordination_run is not None else ""
    imported_request = dict(start.loop_state.diagnostics.get("stage_execution_request") or {})
    _attach_graph_module_imported_run_identity(
        task_run_loop=task_run_loop,
        imported_task_run=start.task_run,
        imported_coordination_run_id=imported_coordination_run_id,
        handle=handle,
        identity=identity,
    )
    task_run_loop.event_log.append(
        str(request_payload.get("root_task_run_id") or ""),
        "coordination_graph_module_imported_run_started",
        payload={
            "source": source,
            "importing_coordination_run_id": str(identity.get("coordination_run_id") or ""),
            "importing_stage_id": str(identity.get("stage_id") or ""),
            "importing_node_id": str(identity.get("node_id") or ""),
            "graph_module_runtime_handle_id": str(handle.get("handle_id") or ""),
            "linked_graph_id": linked_graph_id,
            "imported_task_run_id": start.task_run.task_run_id,
            "imported_coordination_run_id": imported_coordination_run_id,
            "imported_initial_stage_execution_request": imported_request,
        },
        refs={
            "coordination_run_ref": str(identity.get("coordination_run_id") or ""),
            "stage_id": str(identity.get("stage_id") or ""),
            "imported_task_run_ref": start.task_run.task_run_id,
            "imported_coordination_run_ref": imported_coordination_run_id,
        },
    )
    auto_start = bool(dict(request_payload.get("executor_binding") or {}).get("auto_start_imported_initial_stage", False) is True)
    auto_start = bool(dict(handle.get("executor_policy") or {}).get("auto_start_imported_initial_stage", auto_start) is not False)
    if auto_start and imported_request:
        from runtime.execution.node_execution_request import NodeExecutionRequest

        _schedule_stage_execution_background(
            runtime=runtime,
            session_id=session_id,
            source=f"{source}:graph_module_imported_initial_stage",
            stage_execution_request=NodeExecutionRequest.from_dict(imported_request),
            current_turn_context={
                "authority": "context.graph_module_imported_run",
                "importing_coordination_run_id": str(identity.get("coordination_run_id") or ""),
                "importing_stage_id": str(identity.get("stage_id") or ""),
                "graph_module_runtime_handle_id": str(handle.get("handle_id") or ""),
                "task_graph_id": linked_graph_id,
                "selected_graph_id": linked_graph_id,
            },
        )
    return {
        "imported_task_run_id": start.task_run.task_run_id,
        "imported_coordination_run_id": imported_coordination_run_id,
        "linked_graph_id": linked_graph_id,
        "graph_module_runtime_handle_id": str(handle.get("handle_id") or ""),
        "imported_stage_execution_request": imported_request,
    }


def _attach_graph_module_imported_run_identity(
    *,
    task_run_loop: Any,
    imported_task_run: TaskRun,
    imported_coordination_run_id: str,
    handle: dict[str, Any],
    identity: dict[str, Any],
) -> None:
    current = task_run_loop.state_index.get_task_run(imported_task_run.task_run_id) or imported_task_run
    diagnostics = {
        **dict(current.diagnostics or {}),
        "imported_coordination_run_id": imported_coordination_run_id,
        "imported_task_run_id": current.task_run_id,
        "importing_coordination_run_id": str(handle.get("importing_coordination_run_id") or identity.get("coordination_run_id") or ""),
        "importing_root_task_run_id": str(handle.get("importing_root_task_run_id") or identity.get("root_task_run_id") or ""),
        "importing_stage_id": str(handle.get("importing_stage_id") or identity.get("stage_id") or ""),
        "importing_node_id": str(handle.get("importing_node_id") or identity.get("node_id") or ""),
        "importing_task_ref": str(identity.get("task_ref") or ""),
        "importing_stage_request_id": str(identity.get("request_id") or ""),
        "importing_stage_idempotency_key": str(identity.get("idempotency_key") or ""),
    }
    task_run_loop.state_index.upsert_task_run(
        TaskRun(
            task_run_id=current.task_run_id,
            session_id=current.session_id,
            task_id=current.task_id,
            task_contract_ref=current.task_contract_ref,
            owner_agent_seat_id=current.owner_agent_seat_id,
            agent_id=current.agent_id,
            agent_profile_id=current.agent_profile_id,
            runtime_lane=current.runtime_lane,
            status=current.status,
            created_at=current.created_at,
            updated_at=time.time(),
            latest_event_offset=current.latest_event_offset,
            latest_checkpoint_ref=current.latest_checkpoint_ref,
            terminal_reason=current.terminal_reason,
            diagnostics=diagnostics,
        )
    )


def _graph_module_runtime_handle_from_request(request_payload: dict[str, Any]) -> dict[str, Any]:
    runtime_assembly = dict(request_payload.get("runtime_assembly") or {})
    executor_binding = dict(request_payload.get("executor_binding") or {})
    handle = dict(
        runtime_assembly.get("graph_module_runtime_handle")
        or executor_binding.get("graph_module_runtime_handle")
        or {}
    )
    if handle:
        handle.setdefault("executor_policy", dict(executor_binding.get("executor_policy") or runtime_assembly.get("executor_policy") or {}))
        return handle
    graph_module_plan = dict(
        runtime_assembly.get("graph_module_runtime_plan")
        or executor_binding.get("graph_module_runtime_plan")
        or {}
    )
    return {
        "authority": "orchestration.graph_module_runtime_handle",
        "handle_id": str(runtime_assembly.get("handle_id") or executor_binding.get("handle_id") or ""),
        "importing_coordination_run_id": str(request_payload.get("coordination_run_id") or ""),
        "importing_root_task_run_id": str(request_payload.get("root_task_run_id") or ""),
        "importing_stage_id": str(request_payload.get("stage_id") or ""),
        "importing_node_id": str(request_payload.get("node_id") or ""),
        "linked_graph_id": str(
            runtime_assembly.get("linked_graph_id")
            or executor_binding.get("linked_graph_id")
            or executor_binding.get("imported_graph_id")
            or graph_module_plan.get("linked_graph_id")
            or ""
        ),
        "graph_module_runtime_plan_id": str(
            runtime_assembly.get("graph_module_runtime_plan_id")
            or executor_binding.get("graph_module_runtime_plan_id")
            or graph_module_plan.get("plan_id")
            or ""
        ),
        "graph_module_runtime_plan": graph_module_plan,
        "explicit_inputs": dict(request_payload.get("explicit_inputs") or {}),
        "standard_input_package": dict(request_payload.get("standard_input_package") or {}),
    }


def _matching_stage_execution_task_run(
    *,
    task_run_loop: Any,
    session_id: str,
    identity: dict[str, Any],
) -> TaskRun | None:
    coordination_run_id = str(identity.get("coordination_run_id") or "").strip()
    stage_id = str(identity.get("stage_id") or "").strip()
    request_id = str(identity.get("request_id") or "").strip()
    idempotency_key = str(identity.get("idempotency_key") or "").strip()
    effective_statuses = {"created", "running", "waiting_approval", "blocked", "completed"}
    candidates = task_run_loop.state_index.list_session_task_runs(session_id) if session_id else task_run_loop.state_index.list_task_runs()
    matches: list[TaskRun] = []
    for task_run in candidates:
        status = str(task_run.status or "")
        if status not in effective_statuses:
            continue
        diagnostics = dict(task_run.diagnostics or {})
        if status == "completed" and diagnostics.get("invalidated_by_coordination_rewind"):
            continue
        run_coordination_id = str(diagnostics.get("coordination_run_id") or "").strip()
        if coordination_run_id and run_coordination_id and run_coordination_id != coordination_run_id:
            continue
        run_stage_id = str(
            diagnostics.get("stage_id")
            or diagnostics.get("coordination_stage_id")
            or _stage_id_from_task_run(task_run)
        ).strip()
        if stage_id and run_stage_id and run_stage_id != stage_id:
            continue
        run_idempotency_key = str(diagnostics.get("stage_idempotency_key") or "").strip()
        run_request_id = str(diagnostics.get("stage_request_id") or "").strip()
        if idempotency_key and run_idempotency_key == idempotency_key:
            matches.append(task_run)
            continue
        if request_id and run_request_id == request_id:
            matches.append(task_run)
            continue
    if not matches:
        return None
    return sorted(matches, key=lambda item: float(item.updated_at or item.created_at or 0.0), reverse=True)[0]


def _append_stage_execution_schedule_event(
    *,
    task_run_loop: Any,
    root_task_run_id: str,
    event_type: str,
    payload: dict[str, Any],
    identity: dict[str, Any],
) -> None:
    if not root_task_run_id:
        return
    try:
        task_run_loop.event_log.append(
            root_task_run_id,
            event_type,
            payload=payload,
            refs={
                "coordination_run_ref": str(identity.get("coordination_run_id") or ""),
                "stage_id": str(identity.get("stage_id") or ""),
                "node_execution_request_ref": str(identity.get("request_id") or ""),
                "idempotency_key": str(identity.get("idempotency_key") or ""),
            },
        )
    except Exception:
        return


def _sanitize_replayed_writing_stage_request_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Clean stale chapter revision fields before replaying a persisted stage request."""
    if str(payload.get("stage_id") or payload.get("node_id") or "").strip() != "chapter_draft":
        return payload
    explicit_inputs = dict(payload.get("explicit_inputs") or {})
    if explicit_inputs.get("revision_required") is not True and "chapter_revision_requirements" not in explicit_inputs:
        return payload

    sanitized_inputs = _sanitize_writing_chapter_revision_inputs(explicit_inputs)
    sanitized = dict(payload)
    sanitized["explicit_inputs"] = sanitized_inputs
    sanitized["request_id"] = ""
    sanitized["idempotency_key"] = ""
    sanitized["a2a_payload"] = _replace_nested_explicit_inputs(
        dict(sanitized.get("a2a_payload") or {}),
        sanitized_inputs,
    )
    sanitized["runtime_assembly"] = _replace_nested_explicit_inputs(
        dict(sanitized.get("runtime_assembly") or {}),
        sanitized_inputs,
    )
    return sanitized


def _sanitize_writing_chapter_revision_inputs(explicit_inputs: dict[str, Any]) -> dict[str, Any]:
    inputs = dict(explicit_inputs)
    artifact_root = Path(str(inputs.get("artifact_root") or ""))
    batch_dir_name = _writing_batch_dir_name(inputs)

    latest_review_ref = _latest_artifact_ref(
        artifact_root / "reviews" / "chapters" / batch_dir_name,
        "review_round_*.md",
    )
    latest_draft_ref = _latest_artifact_ref(
        artifact_root / "chapters" / batch_dir_name,
        "draft_round_*.md",
    )
    if latest_review_ref:
        inputs["previous_chapter_review_ref"] = latest_review_ref
    if latest_draft_ref:
        inputs["previous_chapter_draft_ref"] = latest_draft_ref

    batch_start = _safe_int(inputs.get("batch_start_index") or inputs.get("chapter_index"), 1)
    batch_end = _safe_int(inputs.get("batch_end_index"), batch_start)
    chapters_per_round = _safe_int(inputs.get("chapters_per_round") or inputs.get("chapter_batch_size"), 10)
    chapter_target_words = _safe_int(inputs.get("chapter_target_words"), 2000)
    batch_chapter_numbers = list(range(batch_start, batch_end + 1))
    inputs["batch_chapter_numbers"] = batch_chapter_numbers
    inputs["batch_chapter_list"] = "、".join(f"第{i}章" for i in batch_chapter_numbers)
    review_hint = ""
    review_text = _read_artifact_text(latest_review_ref)
    if review_text:
        review_hint = "\n最新审核意见摘要：\n" + _compact_review_text(review_text, max_chars=6000)
    inputs["chapter_revision_requirements"] = (
        f"第{batch_start}章至第{batch_end}章上一轮审核未通过。"
        f"本轮必须严格依据最新审核意见重写完整批次，共{chapters_per_round}章；"
        f"每章约{chapter_target_words}字，只输出完整正文，不要输出摘要、提纲、解释、拒绝、等待补充或工作说明。"
        f"{review_hint}"
    )
    inputs["revision_required"] = True
    inputs["force_replay"] = True
    inputs["force_replay_after"] = time.time()
    for key in list(inputs):
        if str(key).endswith(":artifact_refs") and "chapter_draft" in str(key):
            inputs.pop(key, None)
    inputs.pop("previous_quality_failure_stage_id", None)
    return inputs


def _replace_nested_explicit_inputs(value: Any, explicit_inputs: dict[str, Any]) -> Any:
    if isinstance(value, dict):
        replaced: dict[str, Any] = {}
        for key, child in value.items():
            if key == "explicit_inputs" and isinstance(child, dict):
                replaced[key] = dict(explicit_inputs)
            else:
                replaced[key] = _replace_nested_explicit_inputs(child, explicit_inputs)
        return replaced
    if isinstance(value, list):
        return [_replace_nested_explicit_inputs(item, explicit_inputs) for item in value]
    return value


def _writing_batch_dir_name(inputs: dict[str, Any]) -> str:
    batch_index = _safe_int(inputs.get("batch_index"), 1)
    batch_start = _safe_int(inputs.get("batch_start_index") or inputs.get("chapter_index"), 1)
    batch_end = _safe_int(inputs.get("batch_end_index"), batch_start)
    return f"batch_{batch_index:03d}_chapters_{batch_start:03d}_{batch_end:03d}"


def _latest_artifact_ref(directory: Path, pattern: str) -> str:
    if not directory.exists() or not directory.is_dir():
        return ""
    files = [path for path in directory.glob(pattern) if path.is_file()]
    if not files:
        return ""
    latest = max(files, key=lambda path: path.stat().st_mtime)
    return f"artifact:{latest.as_posix()}"


def _read_artifact_text(artifact_ref: str, *, max_chars: int = 8000) -> str:
    path_text = str(artifact_ref or "")
    if path_text.startswith("artifact:"):
        path_text = path_text[len("artifact:") :]
    if not path_text:
        return ""
    path = Path(path_text)
    if not path.exists() or not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")[:max_chars]
    except OSError:
        return ""


def _compact_review_text(text: str, *, max_chars: int = 3000) -> str:
    raw = str(text or "").strip()
    sections = _extract_named_review_sections(
        raw,
        section_names=(
            "裁决",
            "裁决理由",
            "阻塞问题",
            "非阻塞问题",
            "下一轮修改要求",
            "canon一致性检查",
            "承接与推进检查",
            "商业阅读体验检查",
            "爽点与章末追读检查",
        ),
    )
    if sections:
        compact = "\n\n".join(sections)
    else:
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        important = [
            line
            for line in lines
            if any(
                marker in line
                for marker in (
                    "阻塞",
                    "修改",
                    "问题",
                    "必须",
                    "裁决",
                    "verdict",
                    "revise",
                    "未通过",
                    "断裂",
                    "失衡",
                    "过于简单",
                    "不允许",
                )
            )
        ]
        compact = "\n".join(important or lines)
    return compact[:max_chars]


def _extract_named_review_sections(text: str, *, section_names: tuple[str, ...]) -> list[str]:
    sections: list[tuple[str, list[str]]] = []
    current_name = ""
    current_lines: list[str] = []
    for line in str(text or "").splitlines():
        stripped = line.strip()
        matched_name = ""
        for name in section_names:
            if stripped.startswith(f"【{name}】"):
                matched_name = name
                break
        if matched_name:
            if current_name and current_lines:
                sections.append((current_name, current_lines))
            current_name = matched_name
            current_lines = [stripped]
            continue
        if current_name:
            if stripped.startswith("【") and stripped.endswith("】"):
                if current_lines:
                    sections.append((current_name, current_lines))
                current_name = ""
                current_lines = []
            else:
                current_lines.append(line)
    if current_name and current_lines:
        sections.append((current_name, current_lines))
    wanted = set(section_names)
    return ["\n".join(lines).strip() for name, lines in sections if name in wanted and "\n".join(lines).strip()]


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class BehaviorDryRunRequest(BaseModel):
    session_id: str
    message: str = Field(..., min_length=1)
    ephemeral_system_messages: list[str] = Field(default_factory=list)
    explicit_subtasks: list[dict[str, Any]] = Field(default_factory=list)


class OrchestrationModeRequest(BaseModel):
    mode: str = Field(default="primary")


class AgentRuntimeProfileRequest(BaseModel):
    agent_profile_id: str = Field(default="", max_length=160)
    allowed_runtime_lanes: list[str] = Field(default_factory=list)
    allowed_operations: list[str] = Field(default_factory=list)
    blocked_operations: list[str] = Field(default_factory=list)
    allowed_memory_scopes: list[str] = Field(default_factory=list)
    allowed_context_sections: list[str] = Field(default_factory=list)
    use_shared_contract: bool = True
    can_delegate_to_agents: bool = False
    allowed_delegate_agent_ids: list[str] = Field(default_factory=list)
    max_delegate_calls_per_turn: int = Field(default=1, ge=0)
    delegate_context_policy: str = Field(default="summary_and_refs_only", max_length=120)
    approval_policy: str = Field(default="default", max_length=80)
    trace_policy: str = Field(default="runtime_event_log", max_length=120)
    lifecycle_policy: str = Field(default="orchestration_managed", max_length=120)
    model_profile: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class OrchestrationAgentUpsertRequest(BaseModel):
    agent_id: str = Field(..., min_length=3, max_length=160)
    agent_name: str = Field(..., min_length=1, max_length=160)
    agent_category: str = Field(default="custom_agent", max_length=80)
    interface_target: str = Field(default="", max_length=160)
    description: str = Field(default="", max_length=1000)
    enabled: bool = True
    editable: bool = True
    default_soul_id: str = Field(default="", max_length=160)
    default_projection_id: str = Field(default="", max_length=160)
    metadata: dict[str, Any] = Field(default_factory=dict)


class OrchestrationAgentGroupUpsertRequest(BaseModel):
    group_id: str = Field(..., min_length=3, max_length=160)
    title: str = Field(..., min_length=1, max_length=160)
    group_kind: str = Field(default="coordination_team", max_length=120)
    coordinator_agent_id: str = Field(default="", max_length=160)
    member_agent_ids: list[str] = Field(default_factory=list)
    description: str = Field(default="", max_length=1000)
    lifecycle_state: str = Field(default="enabled", max_length=80)
    metadata: dict[str, Any] = Field(default_factory=dict)


class OrchestrationPreviewRequest(BaseModel):
    session_id: str = Field(default="session-preview")
    turn_id: str = Field(default="turn:session-preview:1")
    task_id: str = Field(default="taskinst:turn:session-preview:1:general_response")
    user_goal: str = Field(..., min_length=1)
    source: str = Field(default="orchestration_preview")
    task_selection: dict[str, Any] = Field(default_factory=dict)


class CoordinationRunResumeRequest(BaseModel):
    resume_payload: dict[str, Any] = Field(default_factory=dict)


class CoordinationRunContinueRequest(BaseModel):
    source: str = Field(default="orchestration.coordination_run_continue_api", max_length=180)
    current_turn_context: dict[str, Any] = Field(default_factory=dict)


class CoordinationRunDispatchReadyBatchesRequest(BaseModel):
    source: str = Field(default="orchestration.coordination_run_dispatch_ready_batches_api", max_length=180)
    current_turn_context: dict[str, Any] = Field(default_factory=dict)
    max_requests: int = Field(default=4, ge=1, le=32)
    include_current_request: bool = True
    execute_background: bool = False


class CoordinationRunRewindRequest(BaseModel):
    stage_id: str = Field(..., min_length=1, max_length=180)
    reason: str = Field(default="stage_output_invalid", max_length=180)
    source: str = Field(default="orchestration.coordination_run_rewind_api", max_length=180)
    artifact_root: str = Field(default="", max_length=500)
    include_downstream: bool = True
    move_artifacts: bool = True
    refresh_graph_spec: bool = True
    continue_after_rewind: bool = True
    current_turn_context: dict[str, Any] = Field(default_factory=dict)


class TaskRunStopRequest(BaseModel):
    reason: str = Field(default="user_aborted", max_length=120)
    message: str = Field(default="", max_length=500)
    coordination_run_id: str = Field(default="", max_length=180)


class TaskGraphRunStartRequest(BaseModel):
    session_id: str = Field(default="task_graph_studio", max_length=180)
    task_id: str = Field(default="", max_length=180)
    initial_inputs: dict[str, Any] = Field(default_factory=dict)
    require_published: bool = True
    include_trace: bool = True
    execute_initial_stage: bool = True


class TaskGraphMonitorEvaluateRequest(BaseModel):
    monitor_node_id: str = Field(default="", max_length=180)
    monitor_policy: dict[str, Any] = Field(default_factory=dict)


class DelegationPreviewRequest(BaseModel):
    parent_agent_id: str = Field(default="")
    target_agent_id: str = Field(default="")
    delegation_kind: str = Field(default="")


OPTION_LABELS: dict[str, str] = {
    "general": "通用任务域",
    "development": "开发任务域",
    "longform_novel_writing": "长篇小说创作域",
    "writing": "写作任务域",
    "health": "健康任务域",
    "capability": "能力调用域",
    "general_task": "通用任务",
    "bounded_patch": "受限补丁",
    "light_web_game": "轻量网页小游戏",
    "arcade_game_bundle": "复合网页游戏包",
    "longform_novel_graph": "长篇小说图运行",
    "knowledge_retrieval": "知识检索",
    "information_search": "信息搜索",
    "capability_execution": "能力执行",
    "main_conversation_entry": "主会话入口",
    "issue_triage": "健康问题分诊",
    "trace_analysis": "健康链路分析",
    "case_draft": "健康用例草案",
    "fix_verification": "健康修复验证",
    "session_memory_maintenance": "会话记忆维护",
    "durable_memory_extraction": "长期记忆提取",
    "memory_candidate_review": "记忆候选审核",
    "op.model_response": "模型响应",
    "op.read_file": "读取文件",
    "op.search_files": "搜索文件",
    "op.search_text": "搜索文本",
    "op.list_dir": "列出目录",
    "op.stat_path": "读取路径信息",
    "op.path_exists": "检查路径存在",
    "op.glob_paths": "通配查找路径",
    "op.read_structured_file": "读取结构化文件",
    "op.web_search": "网页搜索",
    "op.fetch_url": "抓取网页",
    "op.git_status": "查看 Git 状态",
    "op.git_diff": "查看 Git 差异",
    "op.git_log": "查看 Git 日志",
    "op.git_show": "查看 Git 对象",
    "op.write_file": "写入文件",
    "op.edit_file": "编辑文件",
    "op.shell": "终端命令",
    "op.python_repl": "Python 执行",
    "op.memory_read": "读取记忆",
    "op.memory_write_candidate": "提交记忆候选",
    "op.mcp_retrieval": "检索 MCP",
    "op.mcp_pdf": "PDF MCP",
    "op.mcp_structured_data": "结构化数据 MCP",
    "op.delegate_to_agent": "委派子Agent",
    "op.agent_bounded": "运行受限 Agent",
    "op.session_message_candidate": "提交会话消息候选",
    "op.artifact_result_ref": "提交产物引用候选",
    "default": "默认审批",
    "read_only_first": "只读优先",
    "manual_approval_required": "需要人工审批",
    "deny_destructive": "拒绝破坏性操作",
    "runtime_event_log": "运行事件追踪",
    "full_trace": "完整追踪",
    "minimal_trace": "最小追踪",
    "conversation": "会话内容",
    "state": "当前状态",
    "task": "任务信息",
    "projection": "投影信息",
    "tool": "工具结果",
    "health_issue": "健康事项",
    "runtime_trace": "运行追踪",
    "prompt_manifest": "提示结构",
    "memory_runtime_view": "记忆视图",
    "runtime_contracts": "运行契约",
    "artifact_refs": "产物引用",
    "upstream_outputs": "上游交接",
    "working_memory": "工作记忆包",
    "task_durable_memory": "任务持久记忆",
    "coordination_task_state": "协调任务状态",
    "assertions": "验收断言",
    "conversation_readonly": "会话记忆只读",
    "state_readonly": "状态记忆只读",
    "long_term_candidate": "长期记忆候选",
    "session_memory_write_candidate": "会话记忆写入候选",
    "durable_memory_write_candidate": "长期记忆写入候选",
    "issue_local_readonly": "事项局部只读",
    "health_trace_readonly": "健康追踪只读",
    "formal_memory_read": "正式记忆读取",
    "formal_memory_write_candidate": "正式记忆写入候选",
}

def _option_label(value: str, fallback: str = "") -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return fallback or "未配置"
    if normalized in OPTION_LABELS:
        return OPTION_LABELS[normalized]
    return fallback or normalized


def _option(value: str, *, label: str = "", description: str = "") -> dict[str, str]:
    normalized = str(value or "").strip()
    return {
        "id": normalized,
        "value": normalized,
        "label": _option_label(normalized, label),
        "description": str(description or "").strip(),
    }


def _operation_option(operation: Any) -> dict[str, str]:
    operation_id = str(getattr(operation, "operation_id", "") or "").strip()
    return {
        **_option(
            operation_id,
            label=str(getattr(operation, "title", "") or ""),
            description=str(getattr(operation, "capability_summary", "") or ""),
        ),
        "operation_type": str(getattr(operation, "operation_type", "") or ""),
    }


def _memory_scope_option(value: str) -> dict[str, str]:
    descriptions = {
        "conversation_readonly": "只读取会话连续性候选；普通主回答不直接读取 Session Memory 热摘要。",
        "state_readonly": "只读取 process_state.json 派生的状态快照和恢复候选。",
        "long_term_candidate": "读取长期记忆候选；不能直接写入长期记忆。",
        "session_memory_write_candidate": "仅记忆管理 Agent 使用：提交后维护 Session Memory。",
        "durable_memory_write_candidate": "仅记忆管理 Agent 使用：提交长期记忆写入计划并接受沙箱校验。",
        "formal_memory_read": "读取正式记忆模型。",
        "formal_memory_write_candidate": "提交正式记忆候选，不自动落盘。",
        "issue_local_readonly": "读取健康事项局部记忆。",
        "health_trace_readonly": "读取健康追踪记忆。",
    }
    normalized = str(value or "").strip()
    return _option(normalized, description=descriptions.get(normalized, ""))


def _choice_label_from_map(value: str, labels: dict[str, str]) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return "未配置"
    return str(labels.get(normalized) or _option_label(normalized, normalized)).strip()


def _record_field_text(record: Any, field: str) -> str:
    if isinstance(record, dict):
        value = record.get(field)
    else:
        value = getattr(record, field, "")
    return str(value or "").strip()


def _task_graph_option(value: str, *, label: str, description: str = "", source: str = "") -> dict[str, str]:
    option = _option(value, label=label, description=description)
    option["source"] = str(source or "").strip()
    return option


def _build_task_graph_options(task_registry: TaskFlowRegistry) -> tuple[list[str], list[dict[str, str]]]:
    options_by_value: dict[str, dict[str, str]] = {}

    def add(value: str, *, label: str, description: str = "", source: str = "") -> None:
        normalized = str(value or "").strip()
        if not normalized or normalized in options_by_value:
            return
        options_by_value[normalized] = _task_graph_option(
            normalized,
            label=label,
            description=description,
            source=source,
        )

    for graph in task_registry.list_task_graphs():
        if not graph.enabled and graph.publish_state == "archived":
            continue
        add(
            graph.graph_id,
            label=f"{graph.title} · 任务图",
            description=f"{graph.graph_kind} / {graph.publish_state}",
            source="task_graph",
        )

    options = sorted(options_by_value.values(), key=lambda item: (item.get("source", ""), item["label"], item["value"]))
    return [item["value"] for item in options], options


DEFAULT_ORCHESTRATION_CONTEXT_SECTIONS = (
    "conversation",
    "state",
    "task",
    "projection",
    "tool",
    "runtime_contracts",
    "artifact_refs",
    "upstream_outputs",
    "working_memory",
    "task_durable_memory",
    "health_issue",
    "runtime_trace",
    "prompt_manifest",
    "memory_runtime_view",
    "assertions",
)


DEFAULT_ORCHESTRATION_MEMORY_SCOPES = (
    "conversation_readonly",
    "state_readonly",
    "long_term_candidate",
    "session_memory_write_candidate",
    "durable_memory_write_candidate",
    "formal_memory_read",
    "formal_memory_write_candidate",
    "issue_local_readonly",
    "health_trace_readonly",
)


def _build_runtime_profile_option_values(
    profiles: list[Any],
    *,
    field: str,
    defaults: tuple[str, ...],
) -> list[str]:
    values = {
        str(item).strip()
        for profile in profiles
        for item in tuple(getattr(profile, field, ()) or ())
        if str(item).strip()
    }
    values.update(defaults)
    values.discard("")
    values.discard("conversation_read_write")
    values.discard("state_read_write")
    return sorted(values)


@router.post("/orchestration/dry-run")
async def orchestration_dry_run(payload: BehaviorDryRunRequest) -> dict[str, Any]:
    runtime = require_runtime()
    try:
        task = TaskContract(
            task_id=f"dry-run:{payload.session_id}",
            session_id=payload.session_id,
            user_goal=payload.message,
            inputs={
                "ephemeral_system_message_count": len(payload.ephemeral_system_messages),
                "explicit_subtask_count": len(payload.explicit_subtasks),
            },
        )
        control = ControlKernel().collect(task=task)
        return {
            "state": "wiring_cleared",
            "control": control.to_dict(),
            "unit_catalog": build_base_unit_catalog().to_list(),
            "runtime_available": runtime is not None,
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/orchestration/catalog")
async def orchestration_catalog() -> dict[str, Any]:
    runtime = require_runtime()
    skills = []
    for skill in runtime.skill_registry.skills:
        skills.append(
            {
                "runtime": asdict(skill.runtime),
                "prompt_view": skill.prompt_view.to_dict() if hasattr(skill.prompt_view, "to_dict") else {
                    "name": skill.prompt_view.name,
                    "title": skill.prompt_view.title,
                    "capability": skill.prompt_view.capability,
                    "use_when": skill.prompt_view.use_when,
                    "output_rule": skill.prompt_view.output_rule,
                },
            }
        )
    tools = [tool.to_registry_record() for tool in runtime.tool_runtime.definitions]
    return {
        "permission_mode": runtime.permission_service.current_mode(),
        "supported_permission_modes": runtime.permission_service.supported_modes(),
        "tool_contract_mode": runtime.query_runtime.tool_contract_gate.mode,
        "orchestration_plan_mode": runtime.settings.get_orchestration_plan_mode(),
        "orchestration_state": "wiring_cleared",
        "supported_orchestration_plan_modes": ["primary"],
        "unit_catalog": build_base_unit_catalog().to_list(),
        "skills": skills,
        "tools": tools,
    }


@router.get("/orchestration/agents")
async def orchestration_agents() -> dict[str, Any]:
    runtime = require_runtime()
    registry = AgentRuntimeRegistry(runtime.base_dir)
    catalog = registry.build_catalog()
    groups = AgentGroupRegistry(runtime.base_dir).list_groups()
    options_payload = await orchestration_runtime_options()
    return {
        **catalog,
        "agent_groups": [item.to_dict() for item in groups],
        "options": dict(options_payload.get("options") or _empty_orchestration_runtime_options()),
    }


def _empty_orchestration_runtime_options() -> dict[str, Any]:
    return {
        "operations": [],
        "task_graphs": [],
        "runtime_lanes": [],
        "runtime_lane_registry": {},
        "runtime_lane_diagnostics": {"authority": "orchestration.runtime_lane_registry"},
        "memory_scopes": [],
        "context_sections": [],
        "approval_policies": [],
        "trace_policies": [],
        "operation_options": [],
        "task_graph_options": [],
        "runtime_lane_options": [],
        "memory_scope_options": [],
        "context_section_options": [],
        "approval_policy_options": [],
        "trace_policy_options": [],
        "worker_blueprints": [],
        "capability_items": [],
    }


@router.get("/orchestration/runtime-options")
async def orchestration_runtime_options() -> dict[str, Any]:
    runtime = require_runtime()
    registry = AgentRuntimeRegistry(runtime.base_dir)
    task_registry = TaskFlowRegistry(runtime.base_dir)
    profiles = registry.list_profiles()
    operations = build_default_operation_registry().list_operations()
    task_graph_refs, task_graph_options = _build_task_graph_options(task_registry)
    profile_runtime_lanes = {
        lane
        for profile in profiles
        for lane in profile.allowed_runtime_lanes
        if lane
    }
    task_graph_runtime_lanes = {
        lane
        for graph in task_registry.list_task_graphs()
        for node in graph.nodes
        for lane in [_record_field_text(node, "runtime_lane")]
        if lane
    }
    registered_runtime_lanes = {item.lane_id for item in DEFAULT_RUNTIME_LANE_REGISTRY.list_lanes()}
    runtime_lanes = [item["value"] for item in runtime_lane_option_payloads(include_non_requestable=False)]
    runtime_lane_diagnostics = {
        "authority": "orchestration.runtime_lane_registry",
        "profile_unregistered_lanes": sorted(profile_runtime_lanes - registered_runtime_lanes),
        "task_graph_unregistered_lanes": sorted(task_graph_runtime_lanes - registered_runtime_lanes),
        "task_graph_non_requestable_lanes": sorted(
            lane
            for lane in task_graph_runtime_lanes
            if (descriptor := DEFAULT_RUNTIME_LANE_REGISTRY.get(lane)) is not None and not descriptor.requestable
        ),
    }
    memory_scopes = _build_runtime_profile_option_values(
        profiles,
        field="allowed_memory_scopes",
        defaults=DEFAULT_ORCHESTRATION_MEMORY_SCOPES,
    )
    context_sections = _build_runtime_profile_option_values(
        profiles,
        field="allowed_context_sections",
        defaults=DEFAULT_ORCHESTRATION_CONTEXT_SECTIONS,
    )
    approval_policies = ["default", "read_only_first", "manual_approval_required", "deny_destructive"]
    trace_policies = ["runtime_event_log", "full_trace", "minimal_trace"]
    return {
        "authority": "orchestration.runtime_options",
        "options": {
            "operations": [item.to_dict() for item in operations],
            "task_graphs": task_graph_refs,
            "runtime_lanes": runtime_lanes,
            "runtime_lane_registry": DEFAULT_RUNTIME_LANE_REGISTRY.catalog_payload(),
            "runtime_lane_diagnostics": runtime_lane_diagnostics,
            "memory_scopes": memory_scopes,
            "context_sections": context_sections,
            "approval_policies": approval_policies,
            "trace_policies": trace_policies,
            "operation_options": [_operation_option(item) for item in operations],
            "task_graph_options": task_graph_options,
            "runtime_lane_options": runtime_lane_option_payloads(include_non_requestable=False),
            "memory_scope_options": [_memory_scope_option(item) for item in memory_scopes],
            "context_section_options": [_option(item) for item in context_sections],
            "approval_policy_options": [_option(item) for item in approval_policies],
            "trace_policy_options": [_option(item) for item in trace_policies],
            "worker_blueprints": [item.to_dict() for item in default_worker_agent_blueprints()],
            "capability_items": [],
            "model_provider_catalog": build_provider_catalog(getattr(runtime, "settings", None)),
        },
    }


@router.get("/orchestration/capability-items")
async def orchestration_capability_items() -> dict[str, Any]:
    runtime = require_runtime()
    capability_catalog = build_capability_catalog(runtime, {})
    return {
        "authority": "orchestration.capability_items",
        "capability_items": build_orchestration_capability_items(capability_catalog),
    }


@router.get("/orchestration/resource-inventory")
async def orchestration_resource_inventory() -> dict[str, Any]:
    runtime = require_runtime()
    return build_runtime_resource_inventory(runtime.base_dir).to_dict()


@router.get("/orchestration/agents/next-worker-id")
async def next_orchestration_worker_agent_id() -> dict[str, str]:
    runtime = require_runtime()
    return {
        "authority": "orchestration.agent_registry",
        "agent_id": AgentRegistry(runtime.base_dir).next_worker_agent_id(),
    }


@router.put("/orchestration/agents/{agent_id}")
async def upsert_orchestration_agent(
    agent_id: str,
    payload: OrchestrationAgentUpsertRequest,
) -> dict[str, Any]:
    runtime = require_runtime()
    if payload.agent_id != agent_id:
        payload = payload.model_copy(update={"agent_id": agent_id})
    try:
        AgentRegistry(runtime.base_dir).upsert_agent(
            agent_id=payload.agent_id,
            agent_name=payload.agent_name,
            agent_category=payload.agent_category,
            interface_target=payload.interface_target,
            description=payload.description,
            enabled=payload.enabled,
            editable=payload.editable,
            default_soul_id=payload.default_soul_id,
            default_projection_id=payload.default_projection_id,
            metadata={**payload.metadata, "managed_by": "orchestration_console"},
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await orchestration_agents()


@router.delete("/orchestration/agents/{agent_id}")
async def delete_orchestration_agent(agent_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    try:
        AgentRegistry(runtime.base_dir).delete_agent(agent_id)
        AgentRuntimeRegistry(runtime.base_dir).delete_profile(agent_id)
        AgentGroupRegistry(runtime.base_dir).remove_agent_refs(agent_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Agent not found") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await orchestration_agents()


@router.put("/orchestration/agent-groups/{group_id}")
async def upsert_orchestration_agent_group(
    group_id: str,
    payload: OrchestrationAgentGroupUpsertRequest,
) -> dict[str, Any]:
    runtime = require_runtime()
    if payload.group_id != group_id:
        payload = payload.model_copy(update={"group_id": group_id})
    try:
        AgentGroupRegistry(runtime.base_dir).upsert_group(
            group_id=payload.group_id,
            title=payload.title,
            group_kind=payload.group_kind,
            coordinator_agent_id=payload.coordinator_agent_id,
            member_agent_ids=tuple(payload.member_agent_ids),
            description=payload.description,
            lifecycle_state=payload.lifecycle_state,
            metadata={**payload.metadata, "managed_by": "orchestration_console"},
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await orchestration_agents()


@router.delete("/orchestration/agent-groups/{group_id}")
async def delete_orchestration_agent_group(group_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    try:
        AgentGroupRegistry(runtime.base_dir).delete_group(group_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Agent group not found") from exc
    return await orchestration_agents()


@router.post("/orchestration/body-preview")
async def orchestration_body_preview(payload: OrchestrationPreviewRequest) -> dict[str, Any]:
    runtime = require_runtime()
    agent_profile = runtime.query_runtime.agent_runtime_registry.get_profile("agent:0")
    chain = runtime.query_runtime.agent_runtime_chain.build_runtime(
        session_id=payload.session_id,
        task_id=payload.task_id,
        turn_id=payload.turn_id,
        message=payload.user_goal,
        source=payload.source,
        task_selection={"turn_id": payload.turn_id, **dict(payload.task_selection or {})},
        agent_runtime_profile=agent_profile,
    )
    task_operation = dict(chain.get("task_operation") or {})
    return {
        "authority": "orchestration.body_preview",
        "task_execution_assembly": dict(chain.get("task_execution_assembly") or task_operation.get("task_execution_assembly") or {}),
        "task_body_orchestration": dict(chain.get("task_body_orchestration") or task_operation.get("task_body_orchestration") or {}),
        "agent_body_profile": dict(task_operation.get("agent_body_profile") or {}),
        "prompt_structure_profile": dict(task_operation.get("prompt_structure_profile") or {}),
        "memory_scope_profile": dict(task_operation.get("memory_scope_profile") or {}),
        "runtime_lane_profile": dict(task_operation.get("runtime_lane_profile") or {}),
        "output_boundary_profile": dict(task_operation.get("output_boundary_profile") or {}),
        "memory_runtime_view": dict(chain.get("memory_runtime_view") or {}),
        "context_policy_result": dict(chain.get("context_policy_result") or {}),
    }


@router.post("/orchestration/runtime-spec-preview")
async def orchestration_runtime_spec_preview(payload: OrchestrationPreviewRequest) -> dict[str, Any]:
    runtime = require_runtime()
    agent_profile = runtime.query_runtime.agent_runtime_registry.get_profile("agent:0")
    chain = runtime.query_runtime.agent_runtime_chain.build_runtime(
        session_id=payload.session_id,
        task_id=payload.task_id,
        turn_id=payload.turn_id,
        message=payload.user_goal,
        source=payload.source,
        task_selection={"turn_id": payload.turn_id, **dict(payload.task_selection or {})},
        agent_runtime_profile=agent_profile,
    )
    task_operation = dict(chain.get("task_operation") or {})
    return {
        "authority": "orchestration.runtime_spec_preview",
        "task_execution_assembly": dict(chain.get("task_execution_assembly") or task_operation.get("task_execution_assembly") or {}),
        "task_body_orchestration": dict(chain.get("task_body_orchestration") or task_operation.get("task_body_orchestration") or {}),
        "agent_runtime_spec": dict(chain.get("agent_runtime_spec") or task_operation.get("agent_runtime_spec") or {}),
        "memory_runtime_view": dict(chain.get("memory_runtime_view") or {}),
        "context_policy_result": dict(chain.get("context_policy_result") or {}),
    }


@router.put("/orchestration/agents/{agent_id}/runtime-profile")
async def upsert_orchestration_agent_runtime_profile(
    agent_id: str,
    payload: AgentRuntimeProfileRequest,
) -> dict[str, Any]:
    runtime = require_runtime()
    try:
        AgentRuntimeRegistry(runtime.base_dir).upsert_profile(
            agent_id=agent_id,
            agent_profile_id=payload.agent_profile_id,
            allowed_runtime_lanes=tuple(payload.allowed_runtime_lanes),
            allowed_operations=tuple(payload.allowed_operations),
            blocked_operations=tuple(payload.blocked_operations),
            allowed_memory_scopes=tuple(payload.allowed_memory_scopes),
            allowed_context_sections=tuple(payload.allowed_context_sections),
            use_shared_contract=payload.use_shared_contract,
            can_delegate_to_agents=payload.can_delegate_to_agents,
            allowed_delegate_agent_ids=tuple(payload.allowed_delegate_agent_ids),
            max_delegate_calls_per_turn=payload.max_delegate_calls_per_turn,
            delegate_context_policy=payload.delegate_context_policy,
            approval_policy=payload.approval_policy,
            trace_policy=payload.trace_policy,
            lifecycle_policy=payload.lifecycle_policy,
            model_profile=payload.model_profile,
            metadata=payload.metadata,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await orchestration_agents()


@router.post("/orchestration/catalog/refresh")
async def refresh_orchestration_catalog() -> dict[str, Any]:
    runtime = require_runtime()
    runtime.refresh_catalogs()
    return await orchestration_catalog()


@router.get("/orchestration/delegation-catalog")
async def orchestration_delegation_catalog(parent_agent_id: str = "") -> dict[str, Any]:
    runtime = require_runtime()
    return DelegationCatalogBuilder(runtime.base_dir).build(parent_agent_id=parent_agent_id)


@router.post("/orchestration/delegation-catalog/preview")
async def orchestration_delegation_preview(payload: DelegationPreviewRequest) -> dict[str, Any]:
    runtime = require_runtime()
    return DelegationCatalogBuilder(runtime.base_dir).preview(
        parent_agent_id=payload.parent_agent_id,
        target_agent_id=payload.target_agent_id,
        delegation_kind=payload.delegation_kind,
    )


@router.get("/orchestration/runtime-loop/sessions/{session_id}/task-runs")
async def list_runtime_loop_task_runs(session_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    return runtime.query_runtime.task_run_loop.list_session_traces(session_id)


@router.get("/orchestration/runtime-loop/sessions/{session_id}/live-monitor")
async def get_runtime_loop_session_live_monitor(session_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    return runtime.query_runtime.task_run_loop.get_session_live_monitor(session_id)


@router.get("/orchestration/runtime-loop/task-runs/{task_run_id}")
async def get_runtime_loop_trace(
    task_run_id: str,
    include_payloads: bool = False,
    include_model_messages: bool = False,
) -> dict[str, Any]:
    runtime = require_runtime()
    trace = runtime.query_runtime.task_run_loop.get_trace(
        task_run_id,
        include_payloads=include_payloads,
        include_model_messages=include_model_messages,
    )
    if trace is None:
        raise HTTPException(status_code=404, detail="TaskRun trace not found")
    return trace


@router.get("/orchestration/runtime-loop/task-runs/{task_run_id}/live-monitor")
async def get_runtime_loop_task_run_live_monitor(task_run_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    monitor = runtime.query_runtime.task_run_loop.get_task_run_live_monitor(task_run_id)
    if monitor is None:
        raise HTTPException(status_code=404, detail="TaskRun live monitor not found")
    return monitor


@router.get("/orchestration/runtime-loop/task-runs/{task_run_id}/task-graph-monitor")
async def get_runtime_loop_task_graph_run_monitor(task_run_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    monitor = runtime.query_runtime.task_run_loop.get_task_graph_run_monitor(task_run_id)
    if monitor is None:
        raise HTTPException(status_code=404, detail="TaskGraph run monitor not found")
    return monitor


@router.post("/orchestration/runtime-loop/task-runs/{task_run_id}/task-graph-monitor/evaluate")
async def evaluate_runtime_loop_task_graph_monitor(
    task_run_id: str,
    payload: TaskGraphMonitorEvaluateRequest,
) -> dict[str, Any]:
    runtime = require_runtime()
    evaluation = runtime.query_runtime.task_run_loop.evaluate_task_graph_monitor(
        task_run_id,
        monitor_node_id=payload.monitor_node_id.strip(),
        monitor_policy=dict(payload.monitor_policy or {}),
    )
    if evaluation is None:
        raise HTTPException(status_code=404, detail="TaskGraph run monitor not found")
    return evaluation


@router.get("/orchestration/runtime-loop/task-runs/{task_run_id}/monitor-decisions")
async def list_runtime_loop_task_graph_monitor_decisions(task_run_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    return runtime.query_runtime.task_run_loop.list_task_graph_monitor_decisions(task_run_id)


@router.get("/orchestration/runtime-loop/task-runs/{task_run_id}/artifacts")
async def get_runtime_loop_task_run_artifacts(task_run_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    return runtime.query_runtime.task_run_loop.get_task_run_artifacts(task_run_id)


@router.get("/orchestration/runtime-loop/task-runs/{task_run_id}/memory-receipts")
async def get_runtime_loop_task_run_memory_receipts(task_run_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    return runtime.query_runtime.task_run_loop.get_task_run_memory_receipts(task_run_id)


@router.get("/orchestration/projects/{project_id}/runtime-status")
async def get_project_runtime_status(project_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    status = runtime.query_runtime.task_run_loop.get_project_runtime_status(project_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Project runtime status not found")
    return status


@router.post("/orchestration/runtime-loop/task-graphs/{graph_id}/start")
async def start_task_graph_runtime_loop_run(
    graph_id: str,
    payload: TaskGraphRunStartRequest,
) -> dict[str, Any]:
    runtime = require_runtime()
    registry = TaskFlowRegistry(runtime.base_dir)
    graph = registry.get_task_graph(graph_id)
    if graph is None:
        raise HTTPException(status_code=404, detail="TaskGraph not found")
    if payload.require_published and graph.publish_state != "published":
        raise HTTPException(status_code=409, detail="TaskGraph must be published before run start")
    protocol = registry.get_task_communication_protocol(
        str(graph.default_protocol_id or dict(graph.metadata or {}).get("protocol_id") or "")
    )
    runtime_spec = compile_task_graph_definition_runtime_spec(
        graph=graph,
        specific_tasks=tuple(registry.list_specific_task_records()),
        communication_protocol=protocol,
    )
    blocking_issues = [issue.to_dict() for issue in runtime_spec.issues if issue.severity == "error"]
    if blocking_issues:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "TaskGraph runtime spec has blocking issues",
                "issues": blocking_issues,
            },
        )
    session_id = payload.session_id.strip() or "task_graph_studio"
    try:
        session_id = validate_session_id(session_id or "task_graph_studio")
    except InvalidSessionId as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    start = runtime.query_runtime.task_run_loop.start_task_graph_run(
        session_id=session_id,
        task_id=payload.task_id.strip(),
        graph=graph,
        runtime_spec=runtime_spec,
        initial_inputs=dict(payload.initial_inputs or {}),
        diagnostics={
            "source": "runtime.task_graph_start_api",
            "require_published": payload.require_published,
        },
    )
    stage_execution_request = dict(start.loop_state.diagnostics.get("stage_execution_request") or {})
    initial_stage_execution_events: list[dict[str, Any]] = []
    initial_stage_execution_error: dict[str, Any] | None = None
    initial_stage_execution_background = False
    initial_stage_execution_schedule: dict[str, Any] = {}
    if payload.execute_initial_stage and stage_execution_request:
        from runtime.execution.node_execution_request import NodeExecutionRequest

        request = NodeExecutionRequest.from_dict(stage_execution_request)
        try:
            initial_stage_execution_schedule = _schedule_stage_execution_background(
                runtime=runtime,
                session_id=session_id,
                source="runtime.task_graph_start_api",
                stage_execution_request=request,
                current_turn_context={
                    "authority": "context.task_graph_start",
                    "task_graph_id": graph.graph_id,
                    "selected_graph_id": graph.graph_id,
                    "explicit_inputs": dict(payload.initial_inputs or {}),
                },
            )
            initial_stage_execution_background = bool(initial_stage_execution_schedule.get("background_started"))
        except Exception as exc:
            initial_stage_execution_error = {
                "error": str(exc),
                "type": exc.__class__.__name__,
            }
    return {
        "authority": "orchestration.task_graph_run_start",
        "graph_id": graph.graph_id,
        "task_run_id": start.task_run.task_run_id,
        "coordination_run_id": start.coordination_run.coordination_run_id if start.coordination_run is not None else "",
        "task_run": start.task_run.to_dict(),
        "coordination_run": start.coordination_run.to_dict() if start.coordination_run is not None else None,
        "checkpoint": start.checkpoint.to_dict(),
        "runtime_spec": runtime_spec.to_dict(),
        "stage_execution_request": stage_execution_request or None,
        "initial_stage_execution_events": initial_stage_execution_events,
        "initial_stage_execution_event_count": len(initial_stage_execution_events),
        "initial_stage_execution_error": initial_stage_execution_error,
        "initial_stage_execution_background": initial_stage_execution_background,
        "initial_stage_execution_schedule": initial_stage_execution_schedule,
        "trace": (
            runtime.query_runtime.task_run_loop.get_trace(start.task_run.task_run_id)
            if payload.include_trace
            else None
        ),
        "events": [dict(item) for item in start.events],
    }


@router.get("/orchestration/coordination-runs/{coordination_run_id}/task-graph-monitor")
async def get_coordination_run_task_graph_monitor(coordination_run_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    monitor = runtime.query_runtime.task_run_loop.get_coordination_run_monitor(coordination_run_id)
    if monitor is None:
        raise HTTPException(status_code=404, detail="CoordinationRun task graph monitor not found")
    return monitor


@router.post("/orchestration/coordination-runs/{coordination_run_id}/dispatch-ready-batches")
async def dispatch_coordination_ready_batches(
    coordination_run_id: str,
    payload: CoordinationRunDispatchReadyBatchesRequest,
) -> dict[str, Any]:
    from runtime.execution.node_execution_request import NodeExecutionRequest

    runtime = require_runtime()
    task_run_loop = runtime.query_runtime.task_run_loop
    coordination_run = task_run_loop.state_index.get_coordination_run(coordination_run_id)
    if coordination_run is None:
        raise HTTPException(status_code=404, detail="CoordinationRun not found")
    task_run = task_run_loop.state_index.get_task_run(coordination_run.task_run_id)
    session_id = str(getattr(task_run, "session_id", "") or "").strip()
    if not session_id:
        raise HTTPException(status_code=409, detail="CoordinationRun root TaskRun has no session_id")
    result = task_run_loop.langgraph_coordination_runtime.dispatch_ready_batch_requests(
        coordination_run=coordination_run,
        max_requests=payload.max_requests,
        include_current_request=payload.include_current_request,
        checkpoint_reason="dispatch_ready_batches_api",
    )
    if result.diagnostics.get("reason") == "missing_checkpoint":
        raise HTTPException(status_code=409, detail="CoordinationRun has no LangGraph checkpoint")
    requests = [dict(item) for item in list(result.diagnostics.get("stage_execution_requests") or []) if isinstance(item, dict)]
    schedule_results: list[dict[str, Any]] = []
    if payload.execute_background:
        for request_payload in requests:
            request = NodeExecutionRequest.from_dict(request_payload)
            schedule_results.append(
                _schedule_stage_execution_background(
                    runtime=runtime,
                    session_id=session_id,
                    source=payload.source,
                    stage_execution_request=request,
                    current_turn_context={
                        "authority": "context.coordination_run_dispatch_ready_batches",
                        "coordination_run_id": coordination_run_id,
                        "task_graph_id": coordination_run.graph_ref,
                        "selected_graph_id": coordination_run.graph_ref,
                        "explicit_inputs": dict(request_payload.get("explicit_inputs") or {}),
                        **dict(payload.current_turn_context or {}),
                    },
                )
            )
    return {
        "authority": "orchestration.coordination_run_dispatch_ready_batches",
        "coordination_run_id": coordination_run_id,
        "task_run_id": coordination_run.task_run_id,
        "session_id": session_id,
        "checkpoint_ref": result.checkpoint_ref,
        "stage_execution_requests": requests,
        "request_count": len(requests),
        "execute_background": payload.execute_background,
        "background_started_count": sum(1 for item in schedule_results if bool(item.get("background_started"))),
        "stage_execution_schedules": schedule_results,
        "batch_dispatcher": dict(result.diagnostics.get("batch_dispatcher") or {}),
        "events": [
            event.to_dict() if hasattr(event, "to_dict") else dict(event)
            for event in result.events
        ],
    }


@router.post("/orchestration/coordination-runs/{coordination_run_id}/resume")
async def resume_coordination_run(
    coordination_run_id: str,
    payload: CoordinationRunResumeRequest,
) -> dict[str, Any]:
    runtime = require_runtime()
    result = runtime.query_runtime.task_run_loop.langgraph_coordination_runtime.resume_human_gate(
        coordination_run_id=coordination_run_id,
        resume_payload=dict(payload.resume_payload or {}),
    )
    if result.diagnostics.get("reason") == "missing_coordination_run":
        raise HTTPException(status_code=404, detail="CoordinationRun not found")
    if result.diagnostics.get("reason") == "missing_checkpoint":
        raise HTTPException(status_code=409, detail="CoordinationRun has no LangGraph checkpoint")
    return {
        "authority": "orchestration.coordination_run_resume",
        "coordination_run_id": coordination_run_id,
        "checkpoint_ref": result.checkpoint_ref,
        "diagnostics": dict(result.diagnostics),
        "stage_execution_request": (
            result.stage_execution_request.to_dict()
            if result.stage_execution_request is not None
            else None
        ),
        "events": [
            event.to_dict() if hasattr(event, "to_dict") else dict(event)
            for event in result.events
        ],
    }


@router.post("/orchestration/coordination-runs/{coordination_run_id}/continue-current-stage")
async def continue_coordination_current_stage(
    coordination_run_id: str,
    payload: CoordinationRunContinueRequest,
) -> dict[str, Any]:
    from runtime.execution.node_execution_request import NodeExecutionRequest, NodeResultReadyEvent

    runtime = require_runtime()
    coordination_run = runtime.query_runtime.task_run_loop.state_index.get_coordination_run(coordination_run_id)
    if coordination_run is None:
        raise HTTPException(status_code=404, detail="CoordinationRun not found")
    state = runtime.query_runtime.task_run_loop.langgraph_coordination_runtime.checkpoints.get_state(
        thread_id=coordination_run_id,
    )
    if not state:
        raise HTTPException(status_code=409, detail="CoordinationRun has no LangGraph checkpoint")
    task_run = runtime.query_runtime.task_run_loop.state_index.get_task_run(coordination_run.task_run_id)
    session_id = str(getattr(task_run, "session_id", "") or "").strip()
    if not session_id:
        raise HTTPException(status_code=409, detail="CoordinationRun root TaskRun has no session_id")

    current_event = dict(state.get("current_event") or {})
    current_stage_payload = dict(state.get("stage_execution_request") or {})
    active_stage_id = str(
        state.get("active_stage_id")
        or current_stage_payload.get("stage_id")
        or ""
    ).strip()
    current_event_stage_id = str(current_event.get("stage_id") or "").strip()
    current_event_task_run_id = str(current_event.get("task_run_id") or "").strip()
    current_stage_result_task_run_id = str(
        dict(dict(state.get("stage_results") or {}).get(active_stage_id) or {}).get("task_run_id") or ""
    ).strip()
    current_event_is_active_stage_result = bool(
        str(current_event.get("event_type") or "") == "task_result_ready"
        and active_stage_id
        and current_event_stage_id == active_stage_id
        and current_event_task_run_id
        and current_event_task_run_id == current_stage_result_task_run_id
    )
    graph_module_imported_result = _latest_unconsumed_graph_module_imported_result(
        runtime=runtime,
        session_id=session_id,
        state=state,
        active_stage_id=active_stage_id,
        coordination_run_id=coordination_run_id,
    )
    if graph_module_imported_result:
        resume_event = NodeResultReadyEvent(**graph_module_imported_result["event"])
        result = runtime.query_runtime.task_run_loop.langgraph_coordination_runtime.resume_from_task_result(
            coordination_run=coordination_run,
            event=resume_event,
            current_task_result=dict(graph_module_imported_result.get("task_result") or {}),
            inherited_inputs=dict(graph_module_imported_result.get("explicit_inputs") or {}),
            artifact_root=str(graph_module_imported_result.get("artifact_root") or ""),
        )
        _mark_graph_module_imported_output_packet_committed(
            task_run_loop=runtime.query_runtime.task_run_loop,
            imported_task_run_id=str(graph_module_imported_result.get("task_run_id") or ""),
            packet_ref=str(graph_module_imported_result.get("packet_ref") or ""),
            packet=dict(graph_module_imported_result.get("packet") or {}),
        )
        request = result.stage_execution_request
        schedule_result: dict[str, Any] = {}
        if request is not None:
            schedule_result = _schedule_stage_execution_background(
                runtime=runtime,
                session_id=session_id,
                source=payload.source or "orchestration.coordination_run_continue_api",
                stage_execution_request=request,
                current_turn_context={
                    "authority": "context.coordination_run_continue",
                    "coordination_run_id": coordination_run_id,
                    "task_graph_id": coordination_run.graph_ref,
                    "selected_graph_id": coordination_run.graph_ref,
                    **dict(payload.current_turn_context or {}),
                },
            )
        return {
            "authority": "orchestration.coordination_run_continue_current_stage",
            "coordination_run_id": coordination_run_id,
            "task_run_id": coordination_run.task_run_id,
            "session_id": session_id,
            "stage_execution_request": request.to_dict() if request is not None else None,
            "background_started": bool(schedule_result.get("background_started")),
            "stage_execution_schedule": schedule_result,
            "mode": "resumed_from_graph_module_imported_output_packet",
            "consumed_task_run_id": str(graph_module_imported_result.get("task_run_id") or ""),
            "packet_ref": str(graph_module_imported_result.get("packet_ref") or ""),
        }
    recovered_stage_result = _recover_active_stage_completed_checkpoint(
        runtime=runtime,
        session_id=session_id,
        state=state,
        active_stage_id=active_stage_id,
        coordination_run_id=coordination_run_id,
        current_turn_context=dict(payload.current_turn_context or {}),
    )
    if recovered_stage_result.get("recovered"):
        continuation_payload = dict(recovered_stage_result.get("continuation_payload") or {})
        request_payload = dict(continuation_payload.get("stage_execution_request") or {})
        request = NodeExecutionRequest.from_dict(request_payload) if request_payload else None
        schedule_result: dict[str, Any] = {}
        if request is not None:
            schedule_result = _schedule_stage_execution_background(
                runtime=runtime,
                session_id=session_id,
                source=payload.source or "orchestration.coordination_run_continue_api:completed_checkpoint_recovery",
                stage_execution_request=request,
                current_turn_context={
                    "authority": "context.coordination_run_continue",
                    "coordination_run_id": coordination_run_id,
                    "task_graph_id": coordination_run.graph_ref,
                    "selected_graph_id": coordination_run.graph_ref,
                    **dict(continuation_payload.get("current_turn_context") or {}),
                    **dict(payload.current_turn_context or {}),
                },
            )
        return {
            "authority": "orchestration.coordination_run_continue_current_stage",
            "coordination_run_id": coordination_run_id,
            "task_run_id": coordination_run.task_run_id,
            "session_id": session_id,
            "stage_execution_request": request.to_dict() if request is not None else None,
            "background_started": bool(schedule_result.get("background_started")),
            "stage_execution_schedule": schedule_result,
            "mode": "recovered_completed_checkpoint_stage_task_run",
            "consumed_task_run_id": str(recovered_stage_result.get("task_run_id") or ""),
            "recovery": recovered_stage_result,
        }
    latest_unconsumed_stage_result = (
        {}
        if current_event_is_active_stage_result
        else _latest_unconsumed_stage_task_result(
            runtime=runtime,
            session_id=session_id,
            state=state,
            active_stage_id=active_stage_id,
            coordination_run_id=coordination_run_id,
        )
    )
    if latest_unconsumed_stage_result:
        resume_event = NodeResultReadyEvent(**latest_unconsumed_stage_result["event"])
        result = runtime.query_runtime.task_run_loop.langgraph_coordination_runtime.resume_from_task_result(
            coordination_run=coordination_run,
            event=resume_event,
            current_task_result=dict(latest_unconsumed_stage_result.get("task_result") or {}),
            inherited_inputs=dict(latest_unconsumed_stage_result.get("explicit_inputs") or {}),
            artifact_root=str(latest_unconsumed_stage_result.get("artifact_root") or ""),
        )
        request = result.stage_execution_request
        schedule_result: dict[str, Any] = {}
        if request is not None:
            schedule_result = _schedule_stage_execution_background(
                runtime=runtime,
                session_id=session_id,
                source=payload.source or "orchestration.coordination_run_continue_api",
                stage_execution_request=request,
                current_turn_context={
                    "authority": "context.coordination_run_continue",
                    "coordination_run_id": coordination_run_id,
                    "task_graph_id": coordination_run.graph_ref,
                    "selected_graph_id": coordination_run.graph_ref,
                    **dict(payload.current_turn_context or {}),
                },
            )
        return {
            "authority": "orchestration.coordination_run_continue_current_stage",
            "coordination_run_id": coordination_run_id,
            "task_run_id": coordination_run.task_run_id,
            "session_id": session_id,
            "stage_execution_request": request.to_dict() if request is not None else None,
            "background_started": bool(schedule_result.get("background_started")),
            "stage_execution_schedule": schedule_result,
            "mode": "resumed_from_unconsumed_stage_task_result",
            "consumed_task_run_id": str(latest_unconsumed_stage_result.get("task_run_id") or ""),
        }
    if current_stage_payload and _stage_request_matches_active_stage(
        state=state,
        request_payload=current_stage_payload,
        active_stage_id=active_stage_id,
    ):
        request = NodeExecutionRequest.from_dict(
            _sanitize_replayed_writing_stage_request_payload(current_stage_payload)
        )
        current_turn_context = {
            "authority": "context.coordination_run_continue",
            "coordination_run_id": coordination_run_id,
            "task_graph_id": coordination_run.graph_ref,
            "selected_graph_id": coordination_run.graph_ref,
            **dict(payload.current_turn_context or {}),
        }
        schedule_result = _schedule_stage_execution_background(
            runtime=runtime,
            session_id=session_id,
            source=payload.source or "orchestration.coordination_run_continue_api",
            stage_execution_request=request,
            current_turn_context=current_turn_context,
        )
        return {
            "authority": "orchestration.coordination_run_continue_current_stage",
            "coordination_run_id": coordination_run_id,
            "task_run_id": coordination_run.task_run_id,
            "session_id": session_id,
            "stage_execution_request": request.to_dict(),
            "background_started": bool(schedule_result.get("background_started")),
            "stage_execution_schedule": schedule_result,
            "mode": "replayed_active_stage_request",
        }
    if str(current_event.get("event_type") or "") != "task_result_ready":
        request_payload = current_stage_payload
        if not request_payload:
            raise HTTPException(status_code=409, detail="CoordinationRun has no resumable stage result or current stage execution request")
        request = NodeExecutionRequest.from_dict(
            _sanitize_replayed_writing_stage_request_payload(request_payload)
        )
        current_turn_context = {
            "authority": "context.coordination_run_continue",
            "coordination_run_id": coordination_run_id,
            "task_graph_id": coordination_run.graph_ref,
            "selected_graph_id": coordination_run.graph_ref,
            **dict(payload.current_turn_context or {}),
        }
        schedule_result = _schedule_stage_execution_background(
            runtime=runtime,
            session_id=session_id,
            source=payload.source or "orchestration.coordination_run_continue_api",
            stage_execution_request=request,
            current_turn_context=current_turn_context,
        )
        return {
            "authority": "orchestration.coordination_run_continue_current_stage",
            "coordination_run_id": coordination_run_id,
            "task_run_id": coordination_run.task_run_id,
            "session_id": session_id,
            "stage_execution_request": request.to_dict(),
            "background_started": bool(schedule_result.get("background_started")),
            "stage_execution_schedule": schedule_result,
            "mode": "replayed_current_stage_request",
        }

    if not current_stage_payload and active_stage_id and active_stage_id != str(current_event.get("stage_id") or "").strip():
        repaired_state = dict(state)
        repaired_statuses = dict(repaired_state.get("node_statuses") or {})
        if repaired_statuses.get(active_stage_id) == "running":
            repaired_statuses[active_stage_id] = "pending"
            repaired_state["node_statuses"] = repaired_statuses
            repaired_state["terminal_status"] = ""
            repaired_state["stage_execution_request"] = {}
            repaired_state["diagnostics"] = {
                **dict(repaired_state.get("diagnostics") or {}),
                "continue_current_stage_repaired_pending_active_stage": active_stage_id,
            }
            runtime.query_runtime.task_run_loop.langgraph_coordination_runtime.checkpoints.put_state(
                thread_id=coordination_run_id,
                state=repaired_state,
                metadata={"event": "continue_current_stage_repair_pending_active_stage", "stage_id": active_stage_id},
            )

    current_task_result = dict(dict(state.get("stage_results") or {}).get(str(current_event.get("stage_id") or "")) or {})
    artifact_root = str(
        dict(payload.current_turn_context or {}).get("artifact_root")
        or dict(state.get("pending_inputs") or {}).get("artifact_root")
        or ""
    )
    resume_event = NodeResultReadyEvent(
        event_type=str(current_event.get("event_type") or "task_result_ready"),
        coordination_run_id=str(current_event.get("coordination_run_id") or coordination_run_id),
        task_run_id=str(current_event.get("task_run_id") or coordination_run.task_run_id),
        stage_id=str(current_event.get("stage_id") or ""),
        task_ref=str(current_event.get("task_ref") or ""),
        task_result_ref=str(current_event.get("task_result_ref") or ""),
        artifact_refs=tuple(str(item) for item in list(current_event.get("artifact_refs") or []) if str(item)),
        accepted=bool(current_event.get("accepted") is True),
        agent_run_result_ref=str(current_event.get("agent_run_result_ref") or ""),
        diagnostics=dict(current_event.get("diagnostics") or {}),
    )
    result = runtime.query_runtime.task_run_loop.langgraph_coordination_runtime.resume_from_task_result(
        coordination_run=coordination_run,
        event=resume_event,
        current_task_result=current_task_result,
        inherited_inputs=dict(payload.current_turn_context or {}),
        artifact_root=artifact_root,
    )
    request = result.stage_execution_request
    schedule_result: dict[str, Any] = {}
    if request is not None:
        schedule_result = _schedule_stage_execution_background(
            runtime=runtime,
            session_id=session_id,
            source=payload.source or "orchestration.coordination_run_continue_api",
            stage_execution_request=request,
            current_turn_context={
                "authority": "context.coordination_run_continue",
                "coordination_run_id": coordination_run_id,
                "task_graph_id": coordination_run.graph_ref,
                "selected_graph_id": coordination_run.graph_ref,
                **dict(payload.current_turn_context or {}),
            },
        )
    return {
        "authority": "orchestration.coordination_run_continue_current_stage",
        "coordination_run_id": coordination_run_id,
        "task_run_id": coordination_run.task_run_id,
        "session_id": session_id,
        "stage_execution_request": request.to_dict() if request is not None else None,
        "background_started": bool(schedule_result.get("background_started")),
        "stage_execution_schedule": schedule_result,
        "mode": "resumed_from_task_result",
    }


@router.post("/orchestration/coordination-runs/{coordination_run_id}/rewind-from-stage")
async def rewind_coordination_run_from_stage(
    coordination_run_id: str,
    payload: CoordinationRunRewindRequest,
) -> dict[str, Any]:
    runtime = require_runtime()
    task_run_loop = runtime.query_runtime.task_run_loop
    coordination_run = task_run_loop.state_index.get_coordination_run(coordination_run_id)
    if coordination_run is None:
        raise HTTPException(status_code=404, detail="CoordinationRun not found")
    previous_state = task_run_loop.langgraph_coordination_runtime.checkpoints.get_state(
        thread_id=coordination_run_id,
    )
    if not previous_state:
        raise HTTPException(status_code=409, detail="CoordinationRun has no LangGraph checkpoint")

    stage_id = payload.stage_id.strip()
    invalidated_stage_ids = _coordination_downstream_stage_ids(
        state=previous_state,
        stage_id=stage_id,
        include_downstream=payload.include_downstream,
    )
    artifact_root = str(
        payload.artifact_root
        or payload.current_turn_context.get("artifact_root")
        or dict(previous_state.get("pending_inputs") or {}).get("artifact_root")
        or ""
    ).strip()
    invalidated_artifacts = _coordination_stage_artifact_paths(
        state=previous_state,
        stage_ids=invalidated_stage_ids,
    )
    invalidated_task_runs = _mark_invalidated_stage_task_runs(
        task_run_loop=task_run_loop,
        coordination_run=coordination_run,
        stage_ids=invalidated_stage_ids,
        reason=payload.reason,
    )
    moved_artifacts = []
    if payload.move_artifacts and artifact_root:
        moved_artifacts = _move_invalidated_artifacts(
            artifact_refs=invalidated_artifacts,
            artifact_root=artifact_root,
            stage_id=stage_id,
            reason=payload.reason,
        )

    result = task_run_loop.langgraph_coordination_runtime.rewind_from_stage(
        coordination_run_id=coordination_run_id,
        stage_id=stage_id,
        reason=payload.reason,
        inherited_inputs={
            **dict(payload.current_turn_context or {}),
            "artifact_root": artifact_root,
            "rewind_invalidated_artifacts": moved_artifacts,
        },
        refresh_graph_spec=payload.refresh_graph_spec,
    )
    if result.diagnostics.get("reason") == "missing_coordination_run":
        raise HTTPException(status_code=404, detail="CoordinationRun not found")
    if result.diagnostics.get("reason") == "missing_checkpoint":
        raise HTTPException(status_code=409, detail="CoordinationRun has no LangGraph checkpoint")
    if result.diagnostics.get("reason") == "stage_not_in_order":
        raise HTTPException(status_code=409, detail="Stage is not part of this CoordinationRun")

    request = result.stage_execution_request
    background_started = False
    task_run = task_run_loop.state_index.get_task_run(coordination_run.task_run_id)
    if task_run is not None and str(task_run.status or "") in {"aborted", "failed", "completed"}:
        _mark_rewound_task_run_running(
            task_run_loop=task_run_loop,
            task_run=task_run,
            coordination_run=coordination_run,
            checkpoint_ref=result.checkpoint_ref,
            reason=payload.reason,
            stage_id=stage_id,
        )
        task_run = task_run_loop.state_index.get_task_run(coordination_run.task_run_id)
    session_id = str(getattr(task_run, "session_id", "") or "").strip()
    schedule_result: dict[str, Any] = {}
    if payload.continue_after_rewind and request is not None:
        if not session_id:
            raise HTTPException(status_code=409, detail="CoordinationRun root TaskRun has no session_id")
        schedule_result = _schedule_stage_execution_background(
            runtime=runtime,
            session_id=session_id,
            source=payload.source,
            stage_execution_request=request,
            current_turn_context={
                "authority": "context.coordination_run_rewind",
                "coordination_run_id": coordination_run_id,
                "task_graph_id": coordination_run.graph_ref,
                "selected_graph_id": coordination_run.graph_ref,
                "artifact_root": artifact_root,
                **dict(payload.current_turn_context or {}),
            },
        )
        background_started = bool(schedule_result.get("background_started"))

    return {
        "authority": "orchestration.coordination_run_rewind_from_stage",
        "coordination_run_id": coordination_run_id,
        "task_run_id": coordination_run.task_run_id,
        "session_id": session_id,
        "stage_id": stage_id,
        "reason": payload.reason,
        "invalidated_stage_ids": invalidated_stage_ids,
        "invalidated_task_runs": invalidated_task_runs,
        "invalidated_artifact_refs": invalidated_artifacts,
        "moved_artifacts": moved_artifacts,
        "checkpoint_ref": result.checkpoint_ref,
        "stage_execution_request": request.to_dict() if request is not None else None,
        "background_started": background_started,
        "stage_execution_schedule": schedule_result,
        "diagnostics": dict(result.diagnostics),
    }


def _mark_rewound_task_run_running(
    *,
    task_run_loop: Any,
    task_run: TaskRun,
    coordination_run: RuntimeCoordinationRun,
    checkpoint_ref: str,
    reason: str,
    stage_id: str,
) -> None:
    diagnostics = dict(task_run.diagnostics or {})
    previous_status = str(task_run.status or "")
    previous_terminal_reason = str(task_run.terminal_reason or "")
    diagnostics["last_rewind_reactivated_task_run"] = {
        "stage_id": stage_id,
        "reason": reason,
        "previous_status": previous_status,
        "previous_terminal_reason": previous_terminal_reason,
        "created_at": time.time(),
    }
    diagnostics.pop("stop_request", None)
    task_run_loop.state_index.upsert_task_run(
        TaskRun(
            task_run_id=task_run.task_run_id,
            session_id=task_run.session_id,
            task_id=task_run.task_id,
            task_contract_ref=task_run.task_contract_ref,
            owner_agent_seat_id=task_run.owner_agent_seat_id,
            agent_id=task_run.agent_id,
            agent_profile_id=task_run.agent_profile_id,
            runtime_lane=task_run.runtime_lane,
            status="running",
            created_at=task_run.created_at,
            updated_at=time.time(),
            latest_event_offset=task_run.latest_event_offset,
            latest_checkpoint_ref=checkpoint_ref or task_run.latest_checkpoint_ref,
            terminal_reason="",  # type: ignore[arg-type]
            diagnostics=diagnostics,
        )
    )
    coordination_diagnostics = dict(coordination_run.diagnostics or {})
    coordination_diagnostics.pop("stop_request", None)
    coordination_diagnostics["last_rewind_reactivated_task_run"] = diagnostics["last_rewind_reactivated_task_run"]
    task_run_loop.state_index.upsert_coordination_run(
        RuntimeCoordinationRun(
            coordination_run_id=coordination_run.coordination_run_id,
            task_run_id=coordination_run.task_run_id,
            graph_ref=coordination_run.graph_ref,
            coordinator_agent_id=coordination_run.coordinator_agent_id,
            topology_template_id=coordination_run.topology_template_id,
            communication_protocol_id=coordination_run.communication_protocol_id,
            handoff_policy=coordination_run.handoff_policy,
            failure_policy=coordination_run.failure_policy,
            merge_policy=coordination_run.merge_policy,
            status="running",
            latest_checkpoint_ref=checkpoint_ref or coordination_run.latest_checkpoint_ref,
            latest_merge_result_ref=coordination_run.latest_merge_result_ref,
            created_at=coordination_run.created_at,
            updated_at=time.time(),
            diagnostics=coordination_diagnostics,
        )
    )


def _mark_invalidated_stage_task_runs(
    *,
    task_run_loop: Any,
    coordination_run: RuntimeCoordinationRun,
    stage_ids: list[str],
    reason: str,
) -> list[dict[str, Any]]:
    stage_set = {str(item) for item in list(stage_ids or []) if str(item)}
    if not stage_set:
        return []
    session_id = str(getattr(task_run_loop.state_index.get_task_run(coordination_run.task_run_id), "session_id", "") or "")
    changed: list[dict[str, Any]] = []
    now = time.time()
    for task_run in task_run_loop.state_index.list_task_runs():
        if str(task_run.task_run_id or "") == str(coordination_run.task_run_id or ""):
            continue
        if session_id and str(task_run.session_id or "") != session_id:
            continue
        stage_id = _stage_id_from_task_run(task_run)
        if stage_id not in stage_set:
            continue
        previous_status = str(task_run.status or "")
        if previous_status in {"completed", "failed", "aborted"}:
            continue
        diagnostics = dict(task_run.diagnostics or {})
        diagnostics["invalidated_by_coordination_rewind"] = {
            "coordination_run_id": coordination_run.coordination_run_id,
            "root_task_run_id": coordination_run.task_run_id,
            "stage_id": stage_id,
            "reason": reason,
            "previous_status": previous_status,
            "created_at": now,
        }
        task_run_loop.state_index.upsert_task_run(
            TaskRun(
                task_run_id=task_run.task_run_id,
                session_id=task_run.session_id,
                task_id=task_run.task_id,
                task_contract_ref=task_run.task_contract_ref,
                owner_agent_seat_id=task_run.owner_agent_seat_id,
                agent_id=task_run.agent_id,
                agent_profile_id=task_run.agent_profile_id,
                runtime_lane=task_run.runtime_lane,
                status="aborted",
                created_at=task_run.created_at,
                updated_at=now,
                latest_event_offset=task_run.latest_event_offset,
                latest_checkpoint_ref=task_run.latest_checkpoint_ref,
                terminal_reason="user_aborted",  # type: ignore[arg-type]
                diagnostics=diagnostics,
            )
        )
        for agent_run in task_run_loop.state_index.list_task_agent_runs(task_run.task_run_id):
            if str(agent_run.status or "") not in {"pending", "running"}:
                continue
            agent_diagnostics = dict(agent_run.diagnostics or {})
            agent_diagnostics["invalidated_by_coordination_rewind"] = diagnostics["invalidated_by_coordination_rewind"]
            task_run_loop.state_index.upsert_agent_run(
                AgentRun(
                    agent_run_id=agent_run.agent_run_id,
                    task_run_id=agent_run.task_run_id,
                    agent_id=agent_run.agent_id,
                    agent_profile_id=agent_run.agent_profile_id,
                    role=agent_run.role,
                    spawn_mode=agent_run.spawn_mode,
                    context_scope=agent_run.context_scope,
                    runtime_lane=agent_run.runtime_lane,
                    parent_agent_run_ref=agent_run.parent_agent_run_ref,
                    coordination_run_ref=agent_run.coordination_run_ref,
                    status="killed",
                    latest_checkpoint_ref=agent_run.latest_checkpoint_ref,
                    result_ref=agent_run.result_ref,
                    created_at=agent_run.created_at,
                    updated_at=now,
                    diagnostics=agent_diagnostics,
                )
            )
        changed.append(
            {
                "task_run_id": task_run.task_run_id,
                "stage_id": stage_id,
                "previous_status": previous_status,
                "status": "aborted",
            }
        )
    return changed


def _stage_id_from_task_run(task_run: TaskRun) -> str:
    diagnostics = dict(task_run.diagnostics or {})
    for key in ("stage_id", "node_id", "coordination_stage_id", "coordination_node_id"):
        value = str(diagnostics.get(key) or "").strip()
        if value:
            return value
    task_id = str(task_run.task_id or "")
    task_id_parts = [part for part in task_id.split(":") if part]
    if task_id_parts and task_id_parts[0] == "taskinst" and task_id_parts[-1]:
        return task_id_parts[-1]
    if "." in task_id:
        dotted_stage = task_id.rsplit(".", 1)[-1].strip()
        if dotted_stage:
            return dotted_stage
    task_run_id = str(task_run.task_run_id or "")
    parts = [part for part in task_run_id.split(":") if part]
    if len(parts) >= 2 and parts[-2]:
        return parts[-2]
    return ""


def _stage_request_matches_active_stage(
    *,
    state: dict[str, Any],
    request_payload: dict[str, Any],
    active_stage_id: str,
) -> bool:
    request_stage_id = str(request_payload.get("stage_id") or "").strip()
    if not request_stage_id or request_stage_id != active_stage_id:
        return False
    node_status = str(dict(state.get("node_statuses") or {}).get(active_stage_id) or "")
    if node_status not in {"running", "pending"}:
        return False
    current_event_stage_id = str(dict(state.get("current_event") or {}).get("stage_id") or "").strip()
    if current_event_stage_id != active_stage_id:
        return True
    request_inputs = dict(request_payload.get("explicit_inputs") or {})
    if request_inputs.get("force_replay") is True or request_inputs.get("revision_required") is True:
        return True
    current_event = dict(state.get("current_event") or {})
    if current_event.get("accepted") is False:
        return True
    return False


def _coordination_downstream_stage_ids(
    *,
    state: dict[str, Any],
    stage_id: str,
    include_downstream: bool,
) -> list[str]:
    target = str(stage_id or "").strip()
    order = [str(item) for item in list(state.get("stage_order") or []) if str(item)]
    if not target:
        return []
    if not include_downstream:
        return [target]
    known = set(order)
    order_index = {item: index for index, item in enumerate(order)}
    graph_spec = dict(dict(state.get("diagnostics") or {}).get("coordination_graph_spec") or {})
    outgoing: dict[str, list[str]] = {item: [] for item in known}
    for raw_edge in list(graph_spec.get("edges") or []):
        edge = dict(raw_edge or {})
        source = str(edge.get("source_node_id") or edge.get("from") or edge.get("source") or "").strip()
        next_stage = str(edge.get("target_node_id") or edge.get("to") or edge.get("target") or "").strip()
        if source in known and next_stage in known and order_index.get(next_stage, -1) < order_index.get(source, -1):
            source, next_stage = next_stage, source
        if (
            source in known
            and next_stage in known
            and _coordination_edge_allows_downstream_invalidation(edge=edge, source=source, target=next_stage, order_index=order_index)
            and next_stage not in outgoing.setdefault(source, [])
        ):
            outgoing[source].append(next_stage)
    visited: set[str] = set()
    queue = [target]
    while queue:
        current = queue.pop(0)
        if current in visited:
            continue
        visited.add(current)
        for next_stage in outgoing.get(current, []):
            if next_stage not in visited:
                queue.append(next_stage)
    ordered = [item for item in order if item in visited]
    if len(ordered) <= 1 and target in order:
        start = order.index(target)
        return order[start:]
    return ordered if ordered else [target]


def _coordination_edge_allows_downstream_invalidation(
    *,
    edge: dict[str, Any],
    source: str,
    target: str,
    order_index: dict[str, int],
) -> bool:
    metadata = dict(edge.get("metadata") or {})
    mode = str(edge.get("mode") or edge.get("edge_type") or metadata.get("edge_type") or "").strip()
    dependency_role = str(metadata.get("dependency_role") or edge.get("dependency_role") or "").strip()
    loop_role = str(metadata.get("loop_role") or edge.get("loop_role") or "").strip()
    verdict = str(metadata.get("verdict") or edge.get("verdict") or "").strip()
    if mode in {"review_feedback", "repair_feedback", "conditional_feedback"}:
        return False
    if mode in {"revision_request", "repair_route", "human_handoff", "fail_closed", "conditional_route"}:
        return False
    if dependency_role in {
        "feedback",
        "conditional_feedback",
        "repair_feedback",
        "non_blocking_feedback",
        "conditional_route",
        "repair_route",
        "failure_route",
        "human_handoff",
    }:
        return False
    if loop_role in {"repair", "feedback"}:
        return False
    if verdict in {
        "revise",
        "repair_world",
        "repair_outline",
        "repair_character",
        "human_review_required",
        "fail_closed",
    }:
        return False
    return order_index.get(target, -1) >= order_index.get(source, -1)


def _coordination_stage_artifact_paths(
    *,
    state: dict[str, Any],
    stage_ids: list[str],
) -> list[str]:
    stage_set = {str(item) for item in list(stage_ids or []) if str(item)}
    refs: list[str] = []
    for stage, result in dict(state.get("stage_results") or {}).items():
        if str(stage) not in stage_set or not isinstance(result, dict):
            continue
        refs.extend(str(item) for item in list(result.get("artifact_refs") or []) if str(item).startswith("artifact:"))
    for item in list(state.get("artifact_refs") or []):
        if not isinstance(item, dict) or str(item.get("stage_id") or "") not in stage_set:
            continue
        ref = str(item.get("ref") or "")
        if ref.startswith("artifact:"):
            refs.append(ref)
    return list(dict.fromkeys(refs))


def _move_invalidated_artifacts(
    *,
    artifact_refs: list[str],
    artifact_root: str,
    stage_id: str,
    reason: str,
) -> list[dict[str, Any]]:
    root = _resolve_artifact_root(artifact_root)
    invalidated_root = root / "invalidated" / (
        f"{time.strftime('%Y%m%d-%H%M%S')}-{_safe_path_component(stage_id)}-{_safe_path_component(reason)}"
    )
    moved: list[dict[str, Any]] = []
    for ref in artifact_refs:
        source_text = str(ref or "")
        if not source_text.startswith("artifact:"):
            continue
        source = _resolve_artifact_ref_path(source_text.removeprefix("artifact:"), artifact_root=root)
        try:
            source.relative_to(root)
        except ValueError:
            moved.append({"artifact_ref": ref, "status": "skipped_outside_artifact_root"})
            continue
        if not source.exists() or not source.is_file():
            moved.append({"artifact_ref": ref, "status": "missing"})
            continue
        relative = source.relative_to(root)
        target = invalidated_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(target))
        moved.append(
            {
                "artifact_ref": ref,
                "status": "moved",
                "from": str(source),
                "to": str(target),
            }
        )
    return moved


def _resolve_artifact_root(artifact_root: str) -> Path:
    raw = Path(str(artifact_root or "").strip())
    if raw.is_absolute():
        return raw.resolve()
    repo_root = Path(__file__).resolve().parents[2]
    candidates = [
        raw.resolve(),
        (repo_root / raw).resolve(),
        (Path.cwd().parent / raw).resolve(),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[1]


def _resolve_artifact_ref_path(ref_path: str, *, artifact_root: Path) -> Path:
    raw = Path(str(ref_path or "").strip())
    if raw.is_absolute():
        return raw.resolve()
    root = artifact_root.resolve()
    raw_parts = raw.parts
    root_parts = root.parts
    for start in range(len(root_parts)):
        root_suffix = root_parts[start:]
        if root_suffix and tuple(raw_parts[: len(root_suffix)]) == tuple(root_suffix):
            remainder = raw_parts[len(root_suffix) :]
            return (root / Path(*remainder)).resolve() if remainder else root
    root_relative = (root / raw).resolve()
    if root_relative.exists():
        return root_relative
    repo_relative = (Path(__file__).resolve().parents[2] / raw).resolve()
    if repo_relative.exists():
        return repo_relative
    return raw.resolve()


def _safe_path_component(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value or "").strip()).strip("-")
    return safe[:80] or "stage"


def _latest_unconsumed_stage_task_result(
    *,
    runtime: Any,
    session_id: str,
    state: dict[str, Any],
    active_stage_id: str,
    coordination_run_id: str,
) -> dict[str, Any]:
    if not active_stage_id:
        return {}
    stage_results = dict(state.get("stage_results") or {})
    already_consumed_task_run_id = str(dict(stage_results.get(active_stage_id) or {}).get("task_run_id") or "")
    contracts = dict(state.get("stage_contracts") or {})
    contract = dict(contracts.get(active_stage_id) or {})
    active_task_ref = str(contract.get("task_ref") or state.get("active_task_ref") or "").strip()
    expected_task_suffix = active_stage_id
    candidates = []
    for task_run in runtime.query_runtime.task_run_loop.state_index.list_session_task_runs(session_id):
        if str(task_run.status or "") != "completed":
            continue
        if str(task_run.task_run_id or "") == already_consumed_task_run_id:
            continue
        pending_inputs = dict(state.get("pending_inputs") or {})
        force_replay_after = float(pending_inputs.get("force_replay_after") or 0.0)
        if force_replay_after and float(task_run.updated_at or task_run.created_at or 0.0) <= force_replay_after:
            continue
        task_id = str(task_run.task_id or "")
        task_contract_ref = str(task_run.task_contract_ref or "")
        exact_task_match = bool(active_task_ref and active_task_ref in {task_id, task_contract_ref})
        stage_suffix_match = bool(
            task_id.endswith(f":{expected_task_suffix}")
            or task_contract_ref.endswith(f":{expected_task_suffix}")
        )
        if not exact_task_match and not stage_suffix_match:
            continue
        diagnostics = dict(task_run.diagnostics or {})
        materialization = dict(diagnostics.get("artifact_materialization") or {})
        artifact_refs = [
            str(item)
            for item in list(materialization.get("artifact_refs") or [])
            if str(item).startswith("artifact:")
        ]
        checkpoint = runtime.query_runtime.task_run_loop.checkpoints.load_latest(task_run.task_run_id)
        task_result = dict(getattr(checkpoint, "commit_state", {}) or {}).get("task_result") if checkpoint is not None else {}
        task_result = dict(task_result or {})
        if artifact_refs:
            task_result["output_refs"] = list(dict.fromkeys([*list(task_result.get("output_refs") or []), *artifact_refs]))
        accepted = bool(str(task_run.status or "") == "completed" and (artifact_refs or not dict(contract.get("artifact_policy") or {}).get("enabled")))
        acceptance_diagnostics: dict[str, Any] = {
            "terminal_reason": str(task_run.terminal_reason or ""),
            "recovered_from_completed_stage_task_run": True,
        }
        if active_stage_id == "chapter_draft":
            artifact_text = _read_first_artifact_text(runtime=runtime, artifact_refs=artifact_refs)
            quality = _chapter_draft_recovery_quality_gate(
                artifact_text,
                explicit_inputs=pending_inputs,
            )
            accepted = bool(accepted and quality.get("accepted") is True)
            acceptance_diagnostics.update(quality)
        elif _is_review_gate_contract(contract):
            artifact_text = _read_first_artifact_text(runtime=runtime, artifact_refs=artifact_refs)
            quality = _review_gate_recovery_quality_gate(artifact_text)
            accepted = bool(accepted and quality.get("accepted") is True)
            acceptance_diagnostics.update(quality)
        candidates.append((float(task_run.updated_at or task_run.created_at or 0.0), task_run, task_result, artifact_refs, materialization, accepted, acceptance_diagnostics))
    if not candidates:
        return {}
    _updated_at, task_run, task_result, artifact_refs, materialization, accepted, acceptance_diagnostics = sorted(candidates, key=lambda item: item[0], reverse=True)[0]
    pending_inputs = dict(state.get("pending_inputs") or {})
    artifact_root = str(
        materialization.get("artifact_root")
        or pending_inputs.get("artifact_root")
        or ""
    )
    return {
        "task_run_id": task_run.task_run_id,
        "task_result": task_result,
        "explicit_inputs": pending_inputs,
        "artifact_root": artifact_root,
        "event": {
            "event_type": "task_result_ready",
            "coordination_run_id": coordination_run_id,
            "task_run_id": task_run.task_run_id,
            "stage_id": active_stage_id,
            "task_ref": active_task_ref or task_run.task_id,
            "task_result_ref": str(task_result.get("result_id") or f"taskresult:{task_run.task_run_id}"),
            "artifact_refs": tuple(artifact_refs),
            "accepted": bool(accepted),
            "agent_run_result_ref": "",
            "diagnostics": acceptance_diagnostics,
        },
    }


def _recover_active_stage_completed_checkpoint(
    *,
    runtime: Any,
    session_id: str,
    state: dict[str, Any],
    active_stage_id: str,
    coordination_run_id: str,
    current_turn_context: dict[str, Any],
) -> dict[str, Any]:
    if not active_stage_id:
        return {}
    stage_results = dict(state.get("stage_results") or {})
    already_consumed_task_run_id = str(dict(stage_results.get(active_stage_id) or {}).get("task_run_id") or "")
    contracts = dict(state.get("stage_contracts") or {})
    contract = dict(contracts.get(active_stage_id) or {})
    active_task_ref = str(contract.get("task_ref") or state.get("active_task_ref") or "").strip()
    candidates = []
    task_run_loop = runtime.query_runtime.task_run_loop
    for task_run in task_run_loop.state_index.list_session_task_runs(session_id):
        if str(task_run.task_run_id or "") == already_consumed_task_run_id:
            continue
        if str(task_run.status or "") in {"completed", "failed", "aborted"}:
            continue
        task_id = str(task_run.task_id or "")
        task_contract_ref = str(task_run.task_contract_ref or "")
        exact_task_match = bool(active_task_ref and active_task_ref in {task_id, task_contract_ref})
        stage_suffix_match = bool(
            task_id.endswith(f":{active_stage_id}")
            or task_contract_ref.endswith(f":{active_stage_id}")
        )
        if not exact_task_match and not stage_suffix_match:
            continue
        checkpoint = task_run_loop.checkpoints.load_latest(task_run.task_run_id)
        if checkpoint is None:
            continue
        if str(checkpoint.loop_state.status or "") != "completed":
            continue
        if str(checkpoint.loop_state.terminal_reason or "") != "completed":
            continue
        candidates.append((float(task_run.updated_at or task_run.created_at or 0.0), task_run))
    if not candidates:
        return {}
    _updated_at, task_run = sorted(candidates, key=lambda item: item[0], reverse=True)[0]
    recovered = task_run_loop.recover_completed_checkpoint_task_run(
        task_run_id=task_run.task_run_id,
        current_turn_context={
            "coordination_run_id": coordination_run_id,
            "task_graph_id": str(state.get("graph_id") or ""),
            "selected_graph_id": str(state.get("graph_id") or ""),
            "stage_execution_request": dict(state.get("stage_execution_request") or {}),
            "explicit_inputs": dict(state.get("pending_inputs") or {}),
            **dict(current_turn_context or {}),
        },
    )
    payload = recovered.to_dict()
    payload["task_run_id"] = task_run.task_run_id
    return payload


def _latest_unconsumed_graph_module_imported_result(
    *,
    runtime: Any,
    session_id: str,
    state: dict[str, Any],
    active_stage_id: str,
    coordination_run_id: str,
) -> dict[str, Any]:
    if not active_stage_id or not _active_stage_is_graph_module(state=state, active_stage_id=active_stage_id):
        return {}
    stage_results = dict(state.get("stage_results") or {})
    already_consumed_task_run_id = str(dict(stage_results.get(active_stage_id) or {}).get("task_run_id") or "").strip()
    current_stage_payload = dict(state.get("stage_execution_request") or {})
    active_task_ref = str(
        current_stage_payload.get("task_ref")
        or dict(dict(state.get("stage_contracts") or {}).get(active_stage_id) or {}).get("task_ref")
        or state.get("active_task_ref")
        or ""
    ).strip()
    active_request_id = str(current_stage_payload.get("request_id") or "").strip()
    active_idempotency_key = str(current_stage_payload.get("idempotency_key") or "").strip()
    pending_inputs = dict(state.get("pending_inputs") or {})
    candidates: list[tuple[float, TaskRun, dict[str, Any], dict[str, Any]]] = []
    for imported_run in runtime.query_runtime.task_run_loop.state_index.list_session_task_runs(session_id):
        if str(imported_run.task_run_id or "") == already_consumed_task_run_id:
            continue
        diagnostics = dict(imported_run.diagnostics or {})
        if diagnostics.get("graph_module_imported_run") is not True:
            continue
        if str(diagnostics.get("importing_coordination_run_id") or "").strip() != coordination_run_id:
            continue
        if str(diagnostics.get("importing_stage_id") or diagnostics.get("stage_id") or "").strip() != active_stage_id:
            continue
        imported_request_id = str(diagnostics.get("importing_stage_request_id") or "").strip()
        imported_idempotency_key = str(diagnostics.get("importing_stage_idempotency_key") or "").strip()
        if active_request_id and imported_request_id and imported_request_id != active_request_id:
            continue
        if active_idempotency_key and imported_idempotency_key and imported_idempotency_key != active_idempotency_key:
            continue
        committed = dict(
            diagnostics.get("graph_module_output_packet_committed")
            or diagnostics.get("graph_module_failure_packet_committed")
            or {}
        )
        if (
            committed
            and str(committed.get("importing_coordination_run_id") or "").strip() == coordination_run_id
            and str(committed.get("importing_stage_id") or "").strip() == active_stage_id
        ):
            continue
        completion = _graph_module_imported_completion_packet(
            runtime=runtime,
            imported_task_run=imported_run,
            diagnostics=diagnostics,
        )
        if not completion:
            continue
        candidates.append((float(imported_run.updated_at or imported_run.created_at or 0.0), imported_run, completion, diagnostics))
    if not candidates:
        return {}
    _updated_at, imported_run, packet, diagnostics = sorted(candidates, key=lambda item: item[0], reverse=True)[0]
    packet_status = str(packet.get("status") or "").strip()
    packet_collection = "graph_module_failure_packets" if packet_status in {"failed", "blocked", "waiting_for_human"} else "graph_module_output_packets"
    packet_ref = runtime.query_runtime.task_run_loop.runtime_objects.put_object(
        packet_collection,
        _graph_module_output_packet_object_id(
            importing_coordination_run_id=coordination_run_id,
            importing_stage_id=active_stage_id,
            imported_task_run_id=imported_run.task_run_id,
        ),
        packet,
    )
    artifact_refs = [
        str(item)
        for item in list(packet.get("artifact_refs") or [])
        if str(item).startswith("artifact:")
    ]
    task_result = {
        "result_id": packet_ref,
        "task_result_ref": packet_ref,
        "outputs": dict(packet.get("outputs") or {}),
        "final_outputs": {
            **dict(packet.get("outputs") or {}),
            "graph_module_output_packet_ref": packet_ref,
            "graph_module_output_packet": packet,
        },
        "output_refs": list(dict.fromkeys([*list(packet.get("output_refs") or []), *artifact_refs])),
        "result_refs": list(dict.fromkeys([packet_ref, *list(packet.get("result_refs") or [])])),
        "diagnostics": {
            "authority": "orchestration.graph_module_committed_output_packet_result",
            "graph_module_output_packet_ref": packet_ref,
            "graph_module_output_packet": packet,
            "linked_graph_id": str(packet.get("linked_graph_id") or ""),
            "imported_coordination_run_id": str(packet.get("imported_coordination_run_id") or ""),
        },
    }
    return {
        "task_run_id": imported_run.task_run_id,
        "packet": packet,
        "packet_ref": packet_ref,
        "task_result": task_result,
        "explicit_inputs": pending_inputs,
        "artifact_root": str(pending_inputs.get("artifact_root") or ""),
        "event": {
            "event_type": "task_result_ready",
            "coordination_run_id": coordination_run_id,
            "task_run_id": imported_run.task_run_id,
            "stage_id": active_stage_id,
            "task_ref": active_task_ref or str(diagnostics.get("importing_task_ref") or imported_run.task_id or ""),
            "task_result_ref": packet_ref,
            "artifact_refs": tuple(artifact_refs or [packet_ref]),
            "accepted": bool(packet.get("accepted") is True),
            "agent_run_result_ref": "",
            "request_id": active_request_id or str(diagnostics.get("importing_stage_request_id") or ""),
            "dispatch_event_id": str(diagnostics.get("importing_dispatch_event_id") or ""),
            "diagnostics": {
                "authority": "orchestration.graph_module_committed_output_packet" if bool(packet.get("accepted") is True) else "orchestration.graph_module_committed_failure_packet",
                "graph_module_output_packet_ref": packet_ref,
                "graph_module_output_packet": packet,
                "graph_module_imported_run": True,
                "imported_task_run_id": imported_run.task_run_id,
                "imported_coordination_run_id": str(packet.get("imported_coordination_run_id") or ""),
                "linked_graph_id": str(packet.get("linked_graph_id") or ""),
                "terminal_reason": str(imported_run.terminal_reason or "completed"),
            },
        },
    }


def _active_stage_is_graph_module(*, state: dict[str, Any], active_stage_id: str) -> bool:
    request_payload = dict(state.get("stage_execution_request") or {})
    if str(request_payload.get("executor_type") or "") == "graph_module":
        return True
    contract = dict(dict(state.get("stage_contracts") or {}).get(active_stage_id) or {})
    if str(contract.get("node_type") or "") == "graph_module":
        return True
    metadata = dict(contract.get("metadata") or {})
    executor_policy = dict(contract.get("executor_policy") or {})
    return bool(metadata.get("graph_module")) or str(executor_policy.get("default_executor") or "") == "graph_module"


def _graph_module_imported_completion_packet(
    *,
    runtime: Any,
    imported_task_run: TaskRun,
    diagnostics: dict[str, Any],
) -> dict[str, Any]:
    task_run_loop = runtime.query_runtime.task_run_loop
    imported_coordination_run_id = str(diagnostics.get("imported_coordination_run_id") or "").strip()
    if not imported_coordination_run_id:
        for coordination_run in task_run_loop.state_index.list_task_coordination_runs(imported_task_run.task_run_id):
            imported_coordination_run_id = coordination_run.coordination_run_id
            break
    imported_coordination_run = (
        task_run_loop.state_index.get_coordination_run(imported_coordination_run_id)
        if imported_coordination_run_id
        else None
    )
    imported_state = (
        task_run_loop.langgraph_coordination_runtime.checkpoints.get_state(thread_id=imported_coordination_run_id)
        if imported_coordination_run_id
        else {}
    )
    merge_result = (
        task_run_loop.state_index.get_latest_coordination_merge_result(imported_coordination_run_id)
        if imported_coordination_run_id
        else None
    )
    imported_terminal_status = _graph_module_imported_terminal_status(
        imported_task_run=imported_task_run,
        imported_coordination_run=imported_coordination_run,
        imported_state=imported_state,
        merge_result=merge_result,
    )
    if imported_terminal_status in {"failed", "blocked", "waiting_for_human"}:
        return _graph_module_imported_failure_packet(
            imported_task_run=imported_task_run,
            diagnostics=diagnostics,
            imported_coordination_run_id=imported_coordination_run_id,
            imported_coordination_run=imported_coordination_run,
            imported_state=imported_state,
            imported_terminal_status=imported_terminal_status,
        )
    if imported_terminal_status != "completed":
        return {}
    checkpoint = task_run_loop.checkpoints.load_latest(imported_task_run.task_run_id)
    checkpoint_task_result = dict(getattr(checkpoint, "commit_state", {}) or {}).get("task_result") if checkpoint is not None else {}
    checkpoint_task_result = dict(checkpoint_task_result or {})
    stage_results = {
        str(key): dict(value)
        for key, value in dict(imported_state.get("stage_results") or {}).items()
        if str(key) and isinstance(value, dict)
    }
    artifact_refs = _dedupe_strings(
        [
            *[
                str(ref)
                for result in stage_results.values()
                for ref in list(result.get("artifact_refs") or [])
                if str(ref)
            ],
            *[
                str(ref)
                for ref in list(checkpoint_task_result.get("output_refs") or [])
                if str(ref).startswith("artifact:")
            ],
        ]
    )
    output_refs = _dedupe_strings(
        [
            *artifact_refs,
            *[str(ref) for result in stage_results.values() for ref in list(dict(result.get("outputs") or {}).get("output_refs") or []) if str(ref)],
            *[str(ref) for ref in list(checkpoint_task_result.get("output_refs") or []) if str(ref)],
        ]
    )
    final_result_ref = str(
        dict(imported_state or {}).get("final_result_ref")
        or getattr(merge_result, "final_result_ref", "")
        or checkpoint_task_result.get("result_id")
        or imported_task_run.latest_checkpoint_ref
        or imported_task_run.task_run_id
        or ""
    )
    result_refs = _dedupe_strings(
        [
            final_result_ref,
            str(getattr(merge_result, "merge_result_id", "") or ""),
            *[str(ref) for ref in list(checkpoint_task_result.get("result_refs") or []) if str(ref)],
        ]
    )
    imported_flow = dict(dict(getattr(imported_coordination_run, "diagnostics", {}) or {}).get("coordination_flow") or {})
    stage_summaries = [
        {
            "stage_id": str(stage_id),
            "task_result_ref": str(result.get("task_result_ref") or ""),
            "artifact_refs": list(result.get("artifact_refs") or []),
            "accepted": bool(result.get("accepted") is True),
        }
        for stage_id, result in stage_results.items()
    ]
    artifact_refs_by_stage = {
        str(stage_id): [
            str(ref)
            for ref in list(result.get("artifact_refs") or [])
            if str(ref).startswith("artifact:")
        ]
        for stage_id, result in stage_results.items()
    }
    core_artifact_refs = _graph_module_core_artifact_refs(
        artifact_refs_by_stage=artifact_refs_by_stage,
        all_artifact_refs=artifact_refs,
    )
    handle = dict(diagnostics.get("importing_graph_module_runtime_handle") or {})
    if not handle:
        handle = {
            key: diagnostics.get(key)
            for key in (
                "graph_module_runtime_handle_id",
                "linked_graph_id",
                "importing_graph_id",
                "importing_coordination_run_id",
                "importing_root_task_run_id",
                "importing_stage_id",
                "importing_node_id",
            )
            if diagnostics.get(key) is not None
        }
    return {
        "authority": "orchestration.graph_module_committed_output_packet",
        "packet_id": f"graph-module-output:{_hash_payload({'importing': diagnostics.get('importing_coordination_run_id'), 'stage': diagnostics.get('importing_stage_id'), 'imported': imported_task_run.task_run_id})}",
        "status": "completed",
        "accepted": True,
        "importing_coordination_run_id": str(diagnostics.get("importing_coordination_run_id") or ""),
        "importing_root_task_run_id": str(diagnostics.get("importing_root_task_run_id") or ""),
        "importing_stage_id": str(diagnostics.get("importing_stage_id") or ""),
        "importing_node_id": str(diagnostics.get("importing_node_id") or ""),
        "importing_stage_request_id": str(diagnostics.get("importing_stage_request_id") or ""),
        "importing_stage_idempotency_key": str(diagnostics.get("importing_stage_idempotency_key") or ""),
        "imported_task_run_id": imported_task_run.task_run_id,
        "imported_coordination_run_id": imported_coordination_run_id,
        "linked_graph_id": str(diagnostics.get("linked_graph_id") or ""),
        "graph_module_runtime_handle_id": str(diagnostics.get("graph_module_runtime_handle_id") or ""),
        "graph_module_runtime_plan_id": str(handle.get("graph_module_runtime_plan_id") or ""),
        "handoff_contract_id": str(handle.get("handoff_contract_id") or ""),
        "input_port_id": str(handle.get("input_port_id") or ""),
        "output_port_id": str(handle.get("output_port_id") or ""),
        "isolation_policy": str(handle.get("isolation_policy") or "isolated_per_graph_module_run"),
        "visibility_policy": str(handle.get("visibility_policy") or "committed_only"),
        "detach_policy": str(handle.get("detach_policy") or "preserve_version_anchor"),
        "final_result_ref": final_result_ref,
        "merge_result_ref": str(getattr(merge_result, "merge_result_id", "") or ""),
        "artifact_refs": artifact_refs,
        "artifact_refs_by_stage": artifact_refs_by_stage,
        "core_artifact_refs": core_artifact_refs,
        "output_refs": output_refs,
        "result_refs": result_refs,
        "outputs": {
            "graph_module_output_packet_id": f"graph-module-output:{_hash_payload({'importing': diagnostics.get('importing_coordination_run_id'), 'stage': diagnostics.get('importing_stage_id'), 'imported': imported_task_run.task_run_id})}",
            "imported_task_run_id": imported_task_run.task_run_id,
            "imported_coordination_run_id": imported_coordination_run_id,
            "linked_graph_id": str(diagnostics.get("linked_graph_id") or ""),
            "final_result_ref": final_result_ref,
            "merge_result_ref": str(getattr(merge_result, "merge_result_id", "") or ""),
            "artifact_refs": artifact_refs,
            "artifact_refs_by_stage": artifact_refs_by_stage,
            "core_artifact_refs": core_artifact_refs,
            "output_refs": output_refs,
        },
        "imported_summary": {
            "task_run_status": str(imported_task_run.status or ""),
            "task_run_terminal_reason": str(imported_task_run.terminal_reason or ""),
            "coordination_status": str(getattr(imported_coordination_run, "status", "") or ""),
            "coordination_terminal_status": str(imported_state.get("terminal_status") or imported_flow.get("terminal_status") or ""),
            "completed_stage_ids": list(imported_flow.get("completed_stage_ids") or imported_state.get("completed_nodes") or []),
            "stage_result_count": len(stage_results),
            "stage_results": stage_summaries,
        },
        "created_at": time.time(),
    }


def _graph_module_imported_failure_packet(
    *,
    imported_task_run: TaskRun,
    diagnostics: dict[str, Any],
    imported_coordination_run_id: str,
    imported_coordination_run: Any,
    imported_state: dict[str, Any],
    imported_terminal_status: str,
) -> dict[str, Any]:
    imported_flow = dict(dict(getattr(imported_coordination_run, "diagnostics", {}) or {}).get("coordination_flow") or {})
    handle = dict(diagnostics.get("importing_graph_module_runtime_handle") or {})
    if not handle:
        handle = {
            key: diagnostics.get(key)
            for key in (
                "graph_module_runtime_handle_id",
                "linked_graph_id",
                "importing_graph_id",
                "importing_coordination_run_id",
                "importing_root_task_run_id",
                "importing_stage_id",
                "importing_node_id",
            )
            if diagnostics.get(key) is not None
        }
    failed_stage_ids = _dedupe_strings(
        [
            *list(imported_state.get("failed_nodes") or []),
            *list(imported_flow.get("failed_stage_ids") or []),
        ]
    )
    blocked_stage_ids = _dedupe_strings(
        [
            *list(imported_state.get("blocked_nodes") or []),
            *list(imported_flow.get("blocked_stage_ids") or []),
        ]
    )
    packet_id = f"graph-module-failure:{_hash_payload({'importing': diagnostics.get('importing_coordination_run_id'), 'stage': diagnostics.get('importing_stage_id'), 'imported': imported_task_run.task_run_id, 'status': imported_terminal_status})}"
    return {
        "authority": "orchestration.graph_module_committed_failure_packet",
        "packet_id": packet_id,
        "status": imported_terminal_status or "failed",
        "accepted": False,
        "importing_coordination_run_id": str(diagnostics.get("importing_coordination_run_id") or ""),
        "importing_root_task_run_id": str(diagnostics.get("importing_root_task_run_id") or ""),
        "importing_stage_id": str(diagnostics.get("importing_stage_id") or ""),
        "importing_node_id": str(diagnostics.get("importing_node_id") or ""),
        "importing_stage_request_id": str(diagnostics.get("importing_stage_request_id") or ""),
        "importing_stage_idempotency_key": str(diagnostics.get("importing_stage_idempotency_key") or ""),
        "imported_task_run_id": imported_task_run.task_run_id,
        "imported_coordination_run_id": imported_coordination_run_id,
        "linked_graph_id": str(diagnostics.get("linked_graph_id") or ""),
        "graph_module_runtime_handle_id": str(diagnostics.get("graph_module_runtime_handle_id") or ""),
        "graph_module_runtime_plan_id": str(handle.get("graph_module_runtime_plan_id") or ""),
        "handoff_contract_id": str(handle.get("handoff_contract_id") or ""),
        "input_port_id": str(handle.get("input_port_id") or ""),
        "output_port_id": str(handle.get("output_port_id") or ""),
        "isolation_policy": str(handle.get("isolation_policy") or "isolated_per_graph_module_run"),
        "visibility_policy": str(handle.get("visibility_policy") or "committed_only"),
        "detach_policy": str(handle.get("detach_policy") or "preserve_version_anchor"),
        "final_result_ref": str(imported_state.get("final_result_ref") or imported_task_run.latest_checkpoint_ref or imported_task_run.task_run_id or ""),
        "artifact_refs": [],
        "output_refs": [],
        "result_refs": _dedupe_strings([str(imported_state.get("final_result_ref") or ""), imported_task_run.latest_checkpoint_ref, imported_task_run.task_run_id]),
        "outputs": {
            "graph_module_failure_packet_id": packet_id,
            "imported_task_run_id": imported_task_run.task_run_id,
            "imported_coordination_run_id": imported_coordination_run_id,
            "linked_graph_id": str(diagnostics.get("linked_graph_id") or ""),
            "terminal_status": imported_terminal_status or "failed",
            "failed_stage_ids": failed_stage_ids,
            "blocked_stage_ids": blocked_stage_ids,
        },
        "imported_summary": {
            "task_run_status": str(imported_task_run.status or ""),
            "task_run_terminal_reason": str(imported_task_run.terminal_reason or ""),
            "coordination_status": str(getattr(imported_coordination_run, "status", "") or ""),
            "coordination_terminal_status": str(imported_state.get("terminal_status") or imported_flow.get("terminal_status") or imported_terminal_status),
            "failed_stage_ids": failed_stage_ids,
            "blocked_stage_ids": blocked_stage_ids,
        },
        "created_at": time.time(),
    }


def _graph_module_imported_terminal_status(
    *,
    imported_task_run: TaskRun,
    imported_coordination_run: Any,
    imported_state: dict[str, Any],
    merge_result: Any,
) -> str:
    if merge_result is not None and getattr(merge_result, "accepted", False) is True:
        return "completed"
    state_terminal = str(imported_state.get("terminal_status") or "").strip()
    if state_terminal in {"completed", "failed", "blocked", "waiting_for_human"}:
        return state_terminal
    coordination_status = str(getattr(imported_coordination_run, "status", "") or "").strip()
    if coordination_status in {"completed", "failed", "blocked", "waiting"}:
        return "completed" if coordination_status == "completed" else coordination_status
    return ""


def _mark_graph_module_imported_output_packet_committed(
    *,
    task_run_loop: Any,
    imported_task_run_id: str,
    packet_ref: str,
    packet: dict[str, Any],
) -> None:
    if not imported_task_run_id or not packet_ref:
        return
    imported_run = task_run_loop.state_index.get_task_run(imported_task_run_id)
    if imported_run is None:
        return
    diagnostics = dict(imported_run.diagnostics or {})
    committed_key = "graph_module_output_packet_committed" if bool(packet.get("accepted") is True) else "graph_module_failure_packet_committed"
    diagnostics[committed_key] = {
        "packet_ref": packet_ref,
        "packet_id": str(packet.get("packet_id") or ""),
        "status": str(packet.get("status") or ""),
        "accepted": bool(packet.get("accepted") is True),
        "importing_coordination_run_id": str(packet.get("importing_coordination_run_id") or ""),
        "importing_stage_id": str(packet.get("importing_stage_id") or ""),
        "imported_coordination_run_id": str(packet.get("imported_coordination_run_id") or ""),
        "linked_graph_id": str(packet.get("linked_graph_id") or ""),
        "committed_at": time.time(),
    }
    task_run_loop.state_index.upsert_task_run(
        TaskRun(
            task_run_id=imported_run.task_run_id,
            session_id=imported_run.session_id,
            task_id=imported_run.task_id,
            task_contract_ref=imported_run.task_contract_ref,
            owner_agent_seat_id=imported_run.owner_agent_seat_id,
            agent_id=imported_run.agent_id,
            agent_profile_id=imported_run.agent_profile_id,
            runtime_lane=imported_run.runtime_lane,
            status=imported_run.status,
            created_at=imported_run.created_at,
            updated_at=time.time(),
            latest_event_offset=imported_run.latest_event_offset,
            latest_checkpoint_ref=imported_run.latest_checkpoint_ref,
            terminal_reason=imported_run.terminal_reason,
            diagnostics=diagnostics,
        )
    )


def _graph_module_output_packet_object_id(
    *,
    importing_coordination_run_id: str,
    importing_stage_id: str,
    imported_task_run_id: str,
) -> str:
    return _safe_path_component(
        "graph-module-output-"
        + _hash_payload(
            {
                "importing_coordination_run_id": importing_coordination_run_id,
                "importing_stage_id": importing_stage_id,
                "imported_task_run_id": imported_task_run_id,
            }
        )
    )


def _dedupe_strings(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in values:
        value = str(item or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _graph_module_core_artifact_refs(
    *,
    artifact_refs_by_stage: dict[str, list[str]],
    all_artifact_refs: list[str],
) -> list[str]:
    priority_stage_ids = [
        "project_brief",
        "world_design",
        "world_review",
        "memory_commit_world",
        "character_design",
        "plot_design",
        "design_sync",
        "outline_design",
        "outline_review",
        "baseline_memory_seed",
        "volume_plan",
        "chapter_outline",
        "chapter_draft",
        "chapter_review",
        "memory_commit_chapter",
        "volume_review",
        "volume_commit",
    ]
    selected: list[str] = []
    for stage_id in priority_stage_ids:
        selected.extend(
            ref
            for ref in list(artifact_refs_by_stage.get(stage_id) or [])
            if _graph_module_core_artifact_ref(ref)
        )
    if not selected:
        selected.extend(ref for ref in all_artifact_refs if _graph_module_core_artifact_ref(ref))
    return _dedupe_strings(selected)


def _graph_module_core_artifact_ref(ref: str) -> bool:
    normalized = str(ref or "").replace("\\", "/").lower()
    if not normalized.startswith("artifact:"):
        return False
    if "/debug/" in normalized or "run_report_" in normalized:
        return False
    return normalized.endswith(".md")


def _hash_payload(payload: Any) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def _read_first_artifact_text(*, runtime: Any, artifact_refs: list[str]) -> str:
    root_dir = getattr(runtime.query_runtime.task_run_loop, "root_dir", None)
    if root_dir is None:
        return ""
    root_path = root_dir if hasattr(root_dir, "exists") else None
    candidate_roots = []
    if root_path is not None:
        candidate_roots.extend([root_path, root_path.parent, root_path.parent.parent])
    for ref in artifact_refs:
        raw = str(ref or "")
        if not raw.startswith("artifact:"):
            continue
        rel = raw[len("artifact:") :]
        paths = []
        try:
            paths.append(__import__("pathlib").Path(rel))
        except Exception:
            paths = []
        for base in candidate_roots:
            try:
                paths.append(base / rel)
            except TypeError:
                continue
        for path in paths:
            try:
                if path.exists() and path.is_file():
                    return path.read_text(encoding="utf-8")
            except OSError:
                continue
    return ""


def _is_review_gate_contract(contract: dict[str, Any]) -> bool:
    node_type = str(contract.get("node_type") or "").strip()
    gate_policy = str(contract.get("gate_policy") or "").strip()
    return node_type == "review_gate" or gate_policy == "review_gate" or bool(dict(contract.get("review_gate_policy") or {}))


def _review_gate_recovery_quality_gate(content: str) -> dict[str, Any]:
    text = str(content or "").strip()
    verdict = extract_review_verdict(text)
    accepted = review_verdict_is_accepted(verdict)
    return {
        "accepted": accepted,
        "stage_business_acceptance": {
            "accepted": accepted,
            "policy": "review_gate_verdict_recovery",
            "verdict": verdict,
            "authority": "orchestration.stage_business_acceptance",
        },
        "review_verdict": verdict,
        "accepted_by_recovery_quality_gate": accepted,
        "recovered_from_completed_stage_task_run": True,
    }


def _chapter_draft_recovery_quality_gate(content: str, *, explicit_inputs: dict[str, Any]) -> dict[str, Any]:
    text = str(content or "").strip()
    words = _count_longform_words(text)
    chapters_per_round = max(_safe_int(explicit_inputs.get("chapters_per_round") or explicit_inputs.get("chapter_batch_size")), 1)
    start_index = _safe_int(explicit_inputs.get("batch_start_index") or explicit_inputs.get("chapter_index"), 1)
    end_index = _safe_int(explicit_inputs.get("batch_end_index"), start_index + chapters_per_round - 1)
    expected_indexes = list(range(start_index, end_index + 1)) if end_index >= start_index else [start_index]
    found_indexes = _extract_chapter_heading_indexes(text)
    missing_indexes = [index for index in expected_indexes if index not in found_indexes]
    target_words = _safe_int(explicit_inputs.get("batch_target_words")) or ((_safe_int(explicit_inputs.get("chapter_target_words")) or 2000) * chapters_per_round)
    min_words = max(1200 * chapters_per_round, int(target_words * 0.55))
    refusal_detected = any(
        marker in text
        for marker in (
            "抱歉，我无法",
            "无法执行这个请求",
            "请先提供",
            "缺少前置资产",
            "我没有读取到",
            "当前可推进步骤",
            "不能直接产出",
        )
    )
    issues: list[str] = []
    if not text:
        issues.append("empty_content")
    if refusal_detected:
        issues.append("refusal_or_process_text_detected")
    if words < min_words:
        issues.append(f"insufficient_words:{words}<{min_words}")
    if missing_indexes:
        issues.append("missing_chapter_headings:" + ",".join(str(index) for index in missing_indexes))
    return {
        "accepted": not issues,
        "stage_business_acceptance": {
            "accepted": not issues,
            "policy": "chapter_draft_batch_quality_recovery",
            "issues": issues,
        },
        "chapter_words": words,
        "accepted_by_recovery_quality_gate": not issues,
        "recovery_quality_issues": issues,
        "expected_chapter_indexes": expected_indexes,
        "found_chapter_indexes": sorted(found_indexes),
        "missing_chapter_indexes": missing_indexes,
        "recovered_from_completed_stage_task_run": True,
    }


def _count_longform_words(content: str) -> int:
    text = str(content or "").strip()
    if not text:
        return 0
    return len(re.findall(r"[\u4e00-\u9fff]", text)) + len(re.findall(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)?", text))


def _extract_chapter_heading_indexes(content: str) -> set[int]:
    indexes: set[int] = set()
    for match in re.finditer(r"第\s*([0-9一二三四五六七八九十百零〇两]+)\s*[章节回]", str(content or "")):
        parsed = _parse_chapter_heading_number(match.group(1))
        if parsed > 0:
            indexes.add(parsed)
    return indexes


def _parse_chapter_heading_number(value: str) -> int:
    raw = str(value or "").strip()
    if not raw:
        return 0
    if raw.isdigit():
        return int(raw)
    digits = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    total = 0
    current = 0
    for char in raw:
        if char in digits:
            current = digits[char]
        elif char == "十":
            total += (current or 1) * 10
            current = 0
        elif char == "百":
            total += (current or 1) * 100
            current = 0
    return total + current


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value if value not in (None, "") else default)
    except (TypeError, ValueError):
        return default


@router.post("/orchestration/runtime-loop/task-runs/{task_run_id}/stop")
async def stop_task_run(
    task_run_id: str,
    payload: TaskRunStopRequest,
) -> dict[str, Any]:
    try:
        runtime = require_runtime()
        task_run_loop = runtime.query_runtime.task_run_loop
        state_index = task_run_loop.state_index
        task_run = state_index.get_task_run(task_run_id)
        if task_run is None:
            raise HTTPException(status_code=404, detail="TaskRun not found")
        coordination_run_id = payload.coordination_run_id.strip()
        coordination_run = (
            state_index.get_coordination_run(coordination_run_id)
            if coordination_run_id
            else None
        )
        checkpoint = task_run_loop.checkpoints.load_latest(task_run_id)
        if checkpoint is None:
            raise HTTPException(status_code=409, detail="TaskRun has no checkpoint to stop from")
        terminal_reason = "user_aborted" if payload.reason.strip() == "user_aborted" else payload.reason.strip() or "user_aborted"
        loop_state = checkpoint.loop_state.with_status(
            "aborted",
            transition="stop_after_final_output",
            terminal_reason=terminal_reason,
            diagnostics={
                **dict(checkpoint.loop_state.diagnostics),
                "stop_request": {
                    "reason": terminal_reason,
                    "message": payload.message.strip(),
                    "stopped_at": time.time(),
                },
            },
        )
        checkpoint_event = task_run_loop._write_checkpoint_event(loop_state, event_offset=checkpoint.event_offset)
        task_run_event = task_run_loop.event_log.append(
            task_run_id,
            "task_run_stopped",
            payload={
                "task_run_id": task_run_id,
                "reason": terminal_reason,
                "message": payload.message.strip(),
                "coordination_run_id": coordination_run.coordination_run_id if coordination_run is not None else "",
                "checkpoint_ref": checkpoint_event.refs.get("checkpoint_ref") or checkpoint.checkpoint_id,
            },
            refs={
                "task_run_ref": task_run_id,
                "checkpoint_ref": checkpoint_event.refs.get("checkpoint_ref") or checkpoint.checkpoint_id,
                "coordination_run_ref": coordination_run.coordination_run_id if coordination_run is not None else "",
            },
        )
        state_index.upsert_task_run(
            TaskRun(
                task_run_id=task_run.task_run_id,
                session_id=task_run.session_id,
                task_id=task_run.task_id,
                task_contract_ref=task_run.task_contract_ref,
                owner_agent_seat_id=task_run.owner_agent_seat_id,
                agent_id=task_run.agent_id,
                agent_profile_id=task_run.agent_profile_id,
                runtime_lane=task_run.runtime_lane,
                status="aborted",
                created_at=task_run.created_at,
                updated_at=time.time(),
                latest_event_offset=checkpoint_event.offset,
                latest_checkpoint_ref=str(checkpoint_event.refs.get("checkpoint_ref") or checkpoint.checkpoint_id),
                terminal_reason=terminal_reason,  # type: ignore[arg-type]
                diagnostics={
                    **dict(task_run.diagnostics),
                    "stop_request": {"reason": terminal_reason, "message": payload.message.strip()},
                },
            )
        )
        if coordination_run is not None:
            state_index.upsert_coordination_run(
                CoordinationRun(
                    coordination_run_id=coordination_run.coordination_run_id,
                    task_run_id=coordination_run.task_run_id,
                    graph_ref=coordination_run.graph_ref,
                    coordinator_agent_id=coordination_run.coordinator_agent_id,
                    topology_template_id=coordination_run.topology_template_id,
                    communication_protocol_id=coordination_run.communication_protocol_id,
                    handoff_policy=coordination_run.handoff_policy,
                    failure_policy=coordination_run.failure_policy,
                    merge_policy=coordination_run.merge_policy,
                    status="aborted",
                    latest_checkpoint_ref=str(checkpoint_event.refs.get("checkpoint_ref") or checkpoint.checkpoint_id),
                    latest_merge_result_ref=coordination_run.latest_merge_result_ref,
                    created_at=coordination_run.created_at,
                    updated_at=time.time(),
                    diagnostics={
                        **dict(coordination_run.diagnostics),
                        "stop_request": {"reason": terminal_reason, "message": payload.message.strip()},
                    },
                )
            )
        return {
            "authority": "orchestration.task_run_stop",
            "task_run_id": task_run_id,
            "reason": terminal_reason,
            "checkpoint_ref": str(checkpoint_event.refs.get("checkpoint_ref") or checkpoint.checkpoint_id),
            "event_ref": task_run_event.event_id,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"task_run_stop_failed: {exc}") from exc


@router.put("/orchestration/plan-mode")
async def set_orchestration_plan_mode(payload: OrchestrationModeRequest) -> dict[str, Any]:
    runtime = require_runtime()
    config = runtime.settings.set_orchestration_plan_mode(payload.mode)
    return {
        "mode": str(config.get("orchestration_plan_mode", "primary") or "primary"),
        "supported_modes": ["primary"],
    }
