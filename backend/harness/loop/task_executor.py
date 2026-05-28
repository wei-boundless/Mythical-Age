from __future__ import annotations

import json
import asyncio
import hashlib
import re
import shutil
import time
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any

from capability_system import build_default_operation_registry
from permissions import OperationGatePipelineContext, ResourcePolicy
from runtime.shared.action_request import RuntimeActionRequest
from runtime.shared.execution_record import (
    build_idempotency_token,
    build_request_fingerprint,
    derive_replay_policy,
)
from runtime.shared.models import AgentRun, AgentRunResult
from runtime.shared.safety import build_task_safety_validators
from runtime.memory.tool_observation_ledger import build_tool_observation_record

from orchestration.runtime_directive import RuntimeDirective
from project_layout import ProjectLayout
from harness.runtime import RuntimeCompiler, assemble_runtime, build_execution_context

from .admission import admit_model_action
from .agent_loop import _call_model_invoker, _compact_text, _model_action_timeout_seconds, _parse_json_object
from .model_action_protocol import ModelActionRequest, model_action_request_from_payload
from .task_lifecycle import TaskLifecycleRecord, finish_task_lifecycle


_MAX_TASK_EXECUTION_STEPS = 12
_MAX_MODEL_PROTOCOL_REPAIR_ATTEMPTS = 3


def is_task_run_executable(task_run: Any) -> bool:
    return str(task_run.status or "") in {"waiting_executor", "running", "blocked"} or _is_recoverable_protocol_terminal(task_run)


async def execute_task_run(
    runtime: Any,
    task_run_id: str,
    *,
    max_steps: int = _MAX_TASK_EXECUTION_STEPS,
) -> dict[str, Any]:
    query_runtime = getattr(runtime, "query_runtime", runtime)
    runtime_host = query_runtime.single_agent_runtime_host
    task_run = runtime_host.state_index.get_task_run(task_run_id)
    if task_run is None:
        return _not_found(task_run_id)
    if str(task_run.runtime_lane or "") != "single_agent_task":
        return _conflict(task_run_id, "not_single_agent_task")
    if not is_task_run_executable(task_run):
        return _conflict(task_run_id, f"task_run_not_executable:{task_run.status}")

    contract = _load_contract(runtime_host, task_run)
    if not contract:
        failed_task, _lifecycle, event = _finish_without_executor(
            runtime_host,
            task_run=task_run,
            status="failed",
            terminal_reason="task_contract_missing",
        )
        return {"ok": False, "task_run": failed_task.to_dict(), "event": event, "error": "task_contract_missing"}

    agent_profile = query_runtime.agent_runtime_registry.get_profile("agent:0")
    diagnostics = dict(task_run.diagnostics or {})
    turn_id = str(diagnostics.get("turn_id") or task_run.task_id or task_run.task_run_id)
    runtime_assembly = assemble_runtime(
        backend_dir=query_runtime.base_dir,
        session_id=task_run.session_id,
        turn_id=turn_id,
        agent_invocation_id=f"aginvoke:{task_run.task_run_id}:executor",
        request_task_selection=_task_selection_from_task_run(task_run),
        model_selection={},
        agent_runtime_profile=agent_profile,
        tool_instances=query_runtime._all_tool_instances(),
        definitions_by_name=dict(runtime_host.tool_authorization_index.definitions_by_name or {}),
    )
    runtime_available_tools = _runtime_available_tools(runtime_assembly.to_dict())
    allowed_tool_names = _runtime_allowed_tool_names(runtime_available_tools)
    runtime_fingerprint = _current_runtime_fingerprint(
        runtime_assembly.to_dict(),
        runtime_host=runtime_host,
        query_runtime=query_runtime,
    )
    runtime_host.event_log.append(
        task_run.task_run_id,
        "task_run_executor_started",
        payload={"task_run": task_run.to_dict(), "runtime_assembly": runtime_assembly.to_dict()},
        refs={"task_run_ref": task_run.task_run_id},
    )
    _record_task_step_summary(
        runtime_host,
        task_run_id=task_run.task_run_id,
        step="task_executor_started",
        status="running",
        summary="任务执行器已接管正式 TaskRun，并重新装配本次任务运行时。",
    )

    observation_context = _observations_for_packet(
        runtime_host,
        task_run.task_run_id,
        current_fingerprint=runtime_fingerprint,
    )
    raw_observations: list[dict[str, Any]] = list(observation_context["raw_observations"])
    observations: list[dict[str, Any]] = list(observation_context["packet_observations"])
    execution_state: dict[str, Any] = dict(observation_context["execution_state"])
    artifact_refs: list[dict[str, Any]] = list(observation_context["artifact_refs"])
    compiler = RuntimeCompiler()
    current_task = replace(
        task_run,
        status="running",
        updated_at=time.time(),
        terminal_reason="",
        diagnostics={**_strip_terminal_diagnostics(diagnostics), "executor_status": "running"},
    )
    runtime_host.state_index.upsert_task_run(current_task)
    agent_run = _ensure_executor_agent_run(runtime_host, task_run=current_task)

    for step_index in range(1, max(1, int(max_steps or _MAX_TASK_EXECUTION_STEPS)) + 1):
        compilation = compiler.compile_task_execution_packet(
            session_id=current_task.session_id,
            task_run=current_task.to_dict(),
            contract=contract,
            observations=observations,
            execution_state=execution_state,
            agent_profile_ref=current_task.agent_profile_id,
            model_selection={},
            available_tools=runtime_available_tools,
            runtime_assembly=runtime_assembly,
            invocation_index=step_index,
        )
        packet_event = runtime_host.event_log.append(
            current_task.task_run_id,
            "runtime_invocation_packet_compiled",
            payload=compilation.to_dict(),
            refs={
                "task_run_ref": current_task.task_run_id,
                "runtime_envelope_ref": compilation.envelope.envelope_id,
                "runtime_invocation_packet_ref": compilation.packet.packet_id,
            },
        )
        _record_task_step_summary(
            runtime_host,
            task_run_id=current_task.task_run_id,
            step=f"task_execution_packet_compiled:{step_index}",
            status="running",
            summary="系统已为当前任务步骤装配 runtime packet，并交给 agent 判断下一步。",
            refs={"runtime_invocation_packet_ref": compilation.packet.packet_id},
        )
        try:
            action_request, protocol = await _invoke_task_model_action(
                model_runtime=query_runtime.model_runtime,
                packet=compilation.packet,
                task_run_id=current_task.task_run_id,
                invocation_index=step_index,
            )
        except Exception as exc:
            return _pause_executor_for_model_recovery(
                runtime_host,
                task_run=current_task,
                agent_run=agent_run,
                packet_ref=compilation.packet.packet_id,
                step_index=step_index,
                error=exc,
            )
        if action_request is None:
            repair_observation = _model_protocol_repair_observation(
                task_run_id=current_task.task_run_id,
                packet_ref=compilation.packet.packet_id,
                step_index=step_index,
                diagnostics=protocol,
                runtime_fingerprint=runtime_fingerprint,
            )
            raw_observations.append(repair_observation)
            runtime_host.runtime_objects.put_object("observation", repair_observation["observation_id"], repair_observation)
            runtime_host.event_log.append(
                current_task.task_run_id,
                "task_model_action_protocol_repair_required",
                payload={"observation": repair_observation, "diagnostics": protocol},
                refs={
                    "task_run_ref": current_task.task_run_id,
                    "observation_ref": repair_observation["observation_id"],
                    "runtime_invocation_packet_ref": compilation.packet.packet_id,
                },
            )
            _record_task_step_summary(
                runtime_host,
                task_run_id=current_task.task_run_id,
                step=f"model_action_protocol_repair_required:{step_index}",
                status="running",
                summary="agent 返回的任务动作未通过协议校验；系统已把校验错误作为观察回灌，要求 agent 修正下一步动作格式后继续。",
                refs={"observation_ref": repair_observation["observation_id"]},
            )
            if _model_protocol_repair_count(raw_observations) >= _MAX_MODEL_PROTOCOL_REPAIR_ATTEMPTS:
                return _finish_executor_blocked(
                    runtime_host,
                    task_run=current_task,
                    agent_run=agent_run,
                    terminal_reason="model_action_protocol_repair_required",
                    payload={
                        "diagnostics": protocol,
                        "recoverable_error": {
                            "error_code": "model_action_invalid",
                            "retryable": True,
                            "validation_errors": list(protocol.get("validation_errors") or []),
                        },
                        "recovery_action": "rerun_task_executor",
                    },
                )
            observation_context = _observations_for_packet(
                runtime_host,
                current_task.task_run_id,
                current_fingerprint=runtime_fingerprint,
                pending_observations=raw_observations,
            )
            raw_observations = list(observation_context["raw_observations"])
            observations = list(observation_context["packet_observations"])
            execution_state = dict(observation_context["execution_state"])
            artifact_refs = _dedupe_artifacts([*list(observation_context["artifact_refs"]), *artifact_refs])
            continue
        runtime_host.event_log.append(
            current_task.task_run_id,
            "model_action_request_received",
            payload={"model_action_request": action_request.to_dict(), "diagnostics": protocol},
            refs={
                "task_run_ref": current_task.task_run_id,
                "action_request_ref": action_request.request_id,
                "runtime_invocation_packet_ref": compilation.packet.packet_id,
            },
        )
        _record_task_step_summary(
            runtime_host,
            task_run_id=current_task.task_run_id,
            step=f"model_action_received:{step_index}",
            status="running",
            summary=f"agent 已返回任务动作请求：{action_request.action_type}。",
            refs={"action_request_ref": action_request.request_id},
        )

        project_root = ProjectLayout.from_backend_dir(runtime_host.backend_dir).project_root.resolve()
        admission = admit_model_action(
            action_request,
            definitions_by_name=getattr(runtime_host.tool_authorization_index, "definitions_by_name", {}),
            allowed_tool_names=allowed_tool_names,
            runtime_profile=dict(runtime_assembly.profile.to_dict()),
            operation_gate=None,
            permission_mode=runtime_host._current_permission_mode(),
            directive_ref=f"task-execution:{action_request.request_id}",
            workspace_root=project_root,
            side_effect_tools_allowed=True,
        )
        runtime_host.event_log.append(
            current_task.task_run_id,
            "model_action_admission_checked",
            payload={"admission": admission.to_dict()},
            refs={"task_run_ref": current_task.task_run_id, "action_request_ref": action_request.request_id},
        )
        if admission.decision != "allow":
            return _finish_executor_blocked(
                runtime_host,
                task_run=current_task,
                agent_run=agent_run,
                terminal_reason=admission.system_reason or admission.decision,
                payload={"admission": admission.to_dict(), "action_request": action_request.to_dict()},
            )

        if action_request.action_type == "tool_call":
            observation = await _execute_task_tool_call(
                runtime_host,
                query_runtime=query_runtime,
                task_run=current_task,
                packet_ref=compilation.packet.packet_id,
                action_request=action_request,
                runtime_assembly=runtime_assembly.to_dict(),
            )
            raw_observations.append(observation)
            runtime_host.runtime_objects.put_object("observation", observation["observation_id"], observation)
            runtime_host.event_log.append(
                current_task.task_run_id,
                "task_tool_observation_recorded",
                payload={"observation": observation},
                refs={
                    "task_run_ref": current_task.task_run_id,
                    "action_request_ref": action_request.request_id,
                    "observation_ref": observation["observation_id"],
                },
            )
            artifact_refs = _dedupe_artifacts([*artifact_refs, *_artifact_refs_from_observation(observation)])
            _record_task_step_summary(
                runtime_host,
                task_run_id=current_task.task_run_id,
                step=f"task_tool_observation_recorded:{step_index}",
                status="running",
                summary="系统已执行 agent 请求的任务工具调用，并把真实观察回灌给 agent。",
                refs={"observation_ref": observation["observation_id"]},
            )
            if observation.get("error"):
                _record_task_step_summary(
                    runtime_host,
                    task_run_id=current_task.task_run_id,
                    step=f"task_tool_repair_required:{step_index}",
                    status="running",
                    summary="工具调用失败；系统已把失败原因作为观察交还给 agent，由 agent 调整路径、参数或执行方式继续推进。",
                    refs={"observation_ref": observation["observation_id"]},
                )
            observation_context = _observations_for_packet(
                runtime_host,
                current_task.task_run_id,
                current_fingerprint=runtime_fingerprint,
                pending_observations=raw_observations,
            )
            raw_observations = list(observation_context["raw_observations"])
            observations = list(observation_context["packet_observations"])
            execution_state = dict(observation_context["execution_state"])
            artifact_refs = _dedupe_artifacts([*list(observation_context["artifact_refs"]), *artifact_refs])
            continue

        if action_request.action_type == "respond":
            candidate_artifacts = _dedupe_artifacts([*artifact_refs, *_artifacts_from_action(action_request)])
            verdict = _verify_completion(
                runtime_host=runtime_host,
                runtime_assembly=runtime_assembly.to_dict(),
                task_run_id=current_task.task_run_id,
                contract=contract,
                artifact_refs=candidate_artifacts,
            )
            if not verdict["ok"]:
                repair_observation = _completion_repair_observation(
                    task_run_id=current_task.task_run_id,
                    packet_ref=compilation.packet.packet_id,
                    action_request=action_request,
                    verdict=verdict,
                )
                raw_observations.append(repair_observation)
                runtime_host.runtime_objects.put_object("observation", repair_observation["observation_id"], repair_observation)
                runtime_host.event_log.append(
                    current_task.task_run_id,
                    "task_completion_repair_required",
                    payload={"observation": repair_observation, "verdict": verdict},
                    refs={"task_run_ref": current_task.task_run_id, "observation_ref": repair_observation["observation_id"]},
                )
                _record_task_step_summary(
                    runtime_host,
                    task_run_id=current_task.task_run_id,
                    step=f"task_completion_repair_required:{step_index}",
                    status="running",
                    summary="agent 尝试收尾，但合同证据不足；系统已把缺口作为观察回灌。",
                )
                observation_context = _observations_for_packet(
                    runtime_host,
                    current_task.task_run_id,
                    current_fingerprint=runtime_fingerprint,
                    pending_observations=raw_observations,
                )
                raw_observations = list(observation_context["raw_observations"])
                observations = list(observation_context["packet_observations"])
                execution_state = dict(observation_context["execution_state"])
                artifact_refs = _dedupe_artifacts([*list(observation_context["artifact_refs"]), *artifact_refs])
                continue
            return _finish_executor_success(
                runtime_host,
                task_run=current_task,
                agent_run=agent_run,
                final_answer=action_request.final_answer,
                artifact_refs=list(verdict.get("verified_artifacts") or []),
                observations=raw_observations,
            )

        if action_request.action_type == "ask_user":
            return _finish_executor_blocked(
                runtime_host,
                task_run=current_task,
                agent_run=agent_run,
                terminal_reason="user_input_required",
                payload={"user_question": action_request.user_question, "action_request": action_request.to_dict()},
            )

        if action_request.action_type == "block":
            return _finish_executor_blocked(
                runtime_host,
                task_run=current_task,
                agent_run=agent_run,
                terminal_reason=action_request.blocking_reason or "agent_blocked",
                payload={"action_request": action_request.to_dict()},
            )

    return _finish_executor_failure(
        runtime_host,
        task_run=current_task,
        agent_run=agent_run,
        terminal_reason="task_execution_step_budget_exceeded",
        payload={"max_steps": max_steps},
    )


async def _invoke_task_model_action(
    *,
    model_runtime: Any,
    packet: Any,
    task_run_id: str,
    invocation_index: int,
) -> tuple[ModelActionRequest | None, dict[str, Any]]:
    invoker = getattr(model_runtime, "invoke_messages", None)
    if not callable(invoker):
        return None, {"status": "invalid", "validation_errors": ["model_runtime_unavailable"]}
    timeout_seconds = _model_action_timeout_seconds(model_runtime, model_selection={})
    response = await asyncio.wait_for(
        _call_model_invoker(invoker, list(packet.model_messages), model_selection={}),
        timeout=timeout_seconds,
    )
    payload = _parse_json_object(getattr(response, "content", response))
    payload.setdefault("request_id", f"model-action:{task_run_id}:{invocation_index}")
    return model_action_request_from_payload(payload, turn_id=task_run_id)


async def _execute_task_tool_call(
    runtime_host: Any,
    *,
    query_runtime: Any,
    task_run: Any,
    packet_ref: str,
    action_request: ModelActionRequest,
    runtime_assembly: dict[str, Any],
) -> dict[str, Any]:
    tool_name = str(action_request.tool_call.get("tool_name") or action_request.tool_call.get("name") or "").strip()
    tool_args = dict(action_request.tool_call.get("args") or action_request.tool_call.get("tool_args") or {})
    definition = getattr(runtime_host.tool_authorization_index, "definitions_by_name", {}).get(tool_name)
    operation_id = str(getattr(definition, "operation_id", "") or tool_name)
    directive = RuntimeDirective(
        directive_id=f"runtime-directive:{task_run.task_run_id}:tool:{action_request.request_id}",
        task_id=task_run.task_id,
        plan_ref=f"orchplan:{task_run.task_run_id}:single-agent-task",
        stage_ref=f"orchstage:{task_run.task_run_id}:step",
        executor_type="tool",
        adopted_resource_policy_ref=f"respol:{task_run.task_run_id}:tool:{action_request.request_id}",
        operation_refs=(operation_id,),
        input_contract_ref=str(getattr(definition, "input_contract_ref", "") or ""),
        output_contract_ref=str(getattr(definition, "output_contract_ref", "") or ""),
        execution_graph_ref=f"execgraph:{task_run.task_run_id}:single-agent-task",
        diagnostics={"packet_ref": packet_ref, "source": "single_agent_task_executor"},
    )
    runtime_action = RuntimeActionRequest(
        request_id=action_request.request_id,
        task_run_id=task_run.task_run_id,
        request_type="tool_call",
        step_id=f"task-step:{action_request.request_id}",
        directive_ref=directive.directive_id,
        operation_id=operation_id,
        payload={
            "tool_name": tool_name,
            "tool_call": {
                "id": action_request.request_id,
                "name": tool_name,
                "args": tool_args,
            },
        },
        created_at=time.time(),
    )
    sandbox_policy = _task_sandbox_policy(runtime_assembly, runtime_host=runtime_host, task_run_id=task_run.task_run_id)
    file_policy = _task_file_policy(runtime_assembly, sandbox_policy=sandbox_policy)
    resource_policy = ResourcePolicy(
        policy_id=directive.adopted_resource_policy_ref,
        task_id=task_run.task_id,
        allowed_operations=(operation_id,),
        allowed_tools=(tool_name,),
        approval_policy="task_environment_sandbox",
        runtime_view_only=False,
        adopted=True,
        runtime_executable=True,
        diagnostics={"source": "single_agent_task_executor", "sandbox_policy": _public_policy(sandbox_policy)},
    )
    gate_result = runtime_host.operation_gate.check(
        operation_id,
        resource_policy=resource_policy,
        directive_ref=directive.directive_id,
        context=OperationGatePipelineContext(
            permission_mode="default",
            operation_input={"operation_id": operation_id, "tool_name": tool_name, "name": tool_name, "args": tool_args},
            validators=build_task_safety_validators(
                root_dir=runtime_host.backend_dir,
                safety_envelope={"write_mode": "bounded_create", "write_roots": _sandbox_relative_write_roots(sandbox_policy)},
                sandbox_policy=sandbox_policy,
            ),
            strip_dangerous_allow_rules=False,
        ),
    )
    if not getattr(gate_result, "allowed", False):
        observation = _executor_error_observation(
            task_run_id=task_run.task_run_id,
            request_ref=action_request.request_id,
            directive_ref=directive.directive_id,
            tool_name=tool_name,
            tool_args=tool_args,
            error=str(getattr(gate_result, "reason", "") or "operation_gate_denied"),
        )
        observation["payload"]["operation_gate"] = gate_result.to_dict() if hasattr(gate_result, "to_dict") else {}
        observation["payload"]["runtime_fingerprint"] = _current_runtime_fingerprint(
            runtime_assembly,
            runtime_host=runtime_host,
            query_runtime=query_runtime,
        )
        return observation
    execution_context = build_execution_context(
        packet_ref=packet_ref,
        action_request_ref=action_request.request_id,
        admission_ref="task_executor_admission",
        tool_name=tool_name,
        operation_id=operation_id,
        workspace_root=ProjectLayout.from_backend_dir(runtime_host.backend_dir).project_root.resolve(),
        permission_snapshot={"permission_mode": runtime_host._current_permission_mode(), "task_run": True},
    )
    fingerprint = build_request_fingerprint(
        step_id=runtime_action.step_id,
        operation_id=operation_id,
        payload=runtime_action.payload,
    )
    registry = build_default_operation_registry()
    descriptor = registry.get_operation(operation_id)
    record = runtime_host.execution_store.create_record(
        task_run_id=task_run.task_run_id,
        step_id=runtime_action.step_id,
        action_request=runtime_action,
        directive_ref=directive.directive_id,
        operation_id=operation_id,
        executor_type="tool",
        replay_policy=derive_replay_policy(descriptor),
        request_fingerprint=fingerprint,
        idempotency_token=build_idempotency_token(
            task_run_id=task_run.task_run_id,
            step_id=runtime_action.step_id,
            operation_id=operation_id,
            request_fingerprint=fingerprint,
        ),
        diagnostics={"execution_context": execution_context.to_dict(), "operation_gate": gate_result.to_dict()},
    )
    result = await query_runtime.tool_runtime_executor.run(
        task_run_id=task_run.task_run_id,
        action_request=runtime_action,
        directive=directive,
        execution_record=record,
        execution_store=runtime_host.execution_store,
        sandbox_policy=sandbox_policy,
        file_management_policy=file_policy,
    )
    observation = dict(result.get("observation").to_dict() if hasattr(result.get("observation"), "to_dict") else result.get("observation") or {})
    if result.get("error") or result.get("recoverable_error"):
        observation["error"] = str(result.get("error") or result.get("recoverable_error") or "tool_execution_failed")
    observation.setdefault("payload", {})
    if isinstance(observation.get("payload"), dict):
        observation["payload"]["runtime_fingerprint"] = _current_runtime_fingerprint(
            runtime_assembly,
            runtime_host=runtime_host,
            query_runtime=query_runtime,
        )
    return observation


def _load_contract(runtime_host: Any, task_run: Any) -> dict[str, Any]:
    try:
        contract = runtime_host.runtime_objects.get_object(task_run.task_contract_ref)
    except Exception:
        contract = {}
    if contract:
        return dict(contract)
    return dict(dict(task_run.diagnostics or {}).get("contract") or {})


def _task_selection_from_task_run(task_run: Any) -> dict[str, Any]:
    diagnostics = dict(task_run.diagnostics or {})
    original = dict(diagnostics.get("runtime_task_selection") or diagnostics.get("task_selection") or {})
    runtime_profile = dict(original.get("runtime_profile") or {})
    runtime_profile.setdefault("mode", "professional")
    return {
        **original,
        "runtime_mode": str(original.get("runtime_mode") or runtime_profile.get("mode") or "professional"),
        "runtime_profile": runtime_profile,
    }


def _task_sandbox_policy(runtime_assembly: dict[str, Any], *, runtime_host: Any, task_run_id: str) -> dict[str, Any]:
    environment = dict(runtime_assembly.get("task_environment") or {})
    storage = dict(environment.get("storage_space") or {})
    sandbox = dict(environment.get("sandbox_policy") or {})
    contract = _load_contract_for_policy(runtime_host, task_run_id)
    project_root = ProjectLayout.from_backend_dir(runtime_host.backend_dir).project_root.resolve()
    sandbox_root = str(sandbox.get("sandbox_root") or "").strip()
    if not sandbox_root:
        namespace = task_run_id.replace(":", "_")
        sandbox_root = str((Path(runtime_host.root_dir) / "sandboxes" / namespace).resolve())
    artifact_root = str(storage.get("artifact_root") or "").strip()
    write_scopes = _dedupe_strings(
        [
            *list(sandbox.get("write_scopes") or []),
            *([artifact_root] if artifact_root else []),
            *_explicit_contract_write_roots(contract),
        ]
    )
    return {
        **sandbox,
        "enabled": True,
        "sandbox_root": sandbox_root,
        "workspace_root": str(project_root),
        "artifact_root": artifact_root,
        "write_scopes": write_scopes,
        "read_scopes": ["."],
        "approval_policy": "sandboxed_side_effects",
        "side_effect_operations": list(sandbox.get("side_effect_operations") or ("op.write_file", "op.edit_file", "op.shell", "op.browser_control", "op.image_generate")),
    }


def _task_file_policy(runtime_assembly: dict[str, Any], *, sandbox_policy: dict[str, Any]) -> dict[str, Any]:
    environment = dict(runtime_assembly.get("task_environment") or {})
    storage = dict(environment.get("storage_space") or {})
    return {
        "file_management": dict(environment.get("file_management") or {}),
        "storage_space": storage,
        "artifact_root": str(storage.get("artifact_root") or sandbox_policy.get("artifact_root") or ""),
    }


def _sandbox_relative_write_roots(sandbox_policy: dict[str, Any]) -> list[str]:
    sandbox_root = Path(str(sandbox_policy.get("sandbox_root") or ".")).resolve()
    roots: list[str] = []
    for raw in list(sandbox_policy.get("write_scopes") or []):
        text = str(raw or "").replace("\\", "/").strip().strip("/")
        if not text:
            continue
        try:
            roots.append((sandbox_root / text).resolve().relative_to(sandbox_root).as_posix())
        except Exception:
            roots.append(text)
    return roots


def _load_contract_for_policy(runtime_host: Any, task_run_id: str) -> dict[str, Any]:
    task_run = runtime_host.state_index.get_task_run(task_run_id)
    if task_run is None:
        return {}
    return _load_contract(runtime_host, task_run)


def _explicit_contract_write_roots(contract: dict[str, Any]) -> list[str]:
    roots: list[str] = []
    for path in _explicit_contract_paths(contract):
        normalized = _normalize_contract_path(path)
        if not normalized:
            continue
        if normalized.endswith("/"):
            roots.append(normalized.strip("/"))
        else:
            parent = str(Path(normalized).parent).replace("\\", "/").strip(".")
            roots.append(parent if parent else normalized)
    return _dedupe_strings(roots)


def _explicit_contract_paths(contract: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    for item in list(contract.get("required_artifacts") or []):
        if not isinstance(item, dict):
            continue
        for key in ("path", "output_path", "artifact_path", "target_path"):
            value = str(item.get(key) or "").strip()
            if value:
                paths.append(value)
        paths.extend(_path_tokens_from_text(str(item.get("description") or "")))
    for key in ("completion_criteria", "required_verifications"):
        for item in list(contract.get(key) or []):
            if isinstance(item, dict):
                paths.extend(_path_tokens_from_text(json.dumps(item, ensure_ascii=False)))
            else:
                paths.extend(_path_tokens_from_text(str(item or "")))
    return _dedupe_strings(paths)


_CONTRACT_PATH_TOKEN_RE = re.compile(r"(?<![\w:])([A-Za-z0-9_.\-\u4e00-\u9fff]+(?:/[A-Za-z0-9_.\-\u4e00-\u9fff]+)+(?:/|\\.[A-Za-z0-9]{1,12})?)")


def _path_tokens_from_text(text: str) -> list[str]:
    return [match.group(1) for match in _CONTRACT_PATH_TOKEN_RE.finditer(str(text or "").replace("\\", "/"))]


def _normalize_contract_path(path: str) -> str:
    normalized = str(path or "").replace("\\", "/").strip().strip("'\"`")
    while "//" in normalized:
        normalized = normalized.replace("//", "/")
    normalized = normalized.strip("/")
    if not normalized or normalized.startswith("../") or "/../" in f"/{normalized}/":
        return ""
    if "://" in normalized or normalized.startswith(("/", "\\")):
        return ""
    return normalized


def _dedupe_strings(values: list[str] | tuple[str, ...]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = str(value or "").replace("\\", "/").strip().strip("/")
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _verify_completion(
    *,
    runtime_host: Any,
    runtime_assembly: dict[str, Any],
    task_run_id: str,
    contract: dict[str, Any],
    artifact_refs: list[dict[str, Any]],
) -> dict[str, Any]:
    required_artifacts = [dict(item) for item in list(contract.get("required_artifacts") or []) if isinstance(item, dict)]
    verified_artifacts = _verified_artifacts(
        runtime_host=runtime_host,
        runtime_assembly=runtime_assembly,
        task_run_id=task_run_id,
        artifact_refs=artifact_refs,
    )
    if required_artifacts and not verified_artifacts:
        return {
            "ok": False,
            "missing": ["required_artifacts"],
            "required_artifacts": required_artifacts,
            "artifact_refs": artifact_refs,
            "verified_artifacts": [],
            "reason": "required artifacts must resolve to existing files",
        }
    return {"ok": True, "missing": [], "verified_artifacts": verified_artifacts}


def _finish_executor_success(
    runtime_host: Any,
    *,
    task_run: Any,
    agent_run: Any,
    final_answer: str,
    artifact_refs: list[dict[str, Any]],
    observations: list[dict[str, Any]],
) -> dict[str, Any]:
    result_ref = runtime_host.runtime_objects.put_object(
        "agent_run_result",
        f"{agent_run.agent_run_id}:result",
        {
            "final_answer": final_answer,
            "artifact_refs": artifact_refs,
            "observation_refs": [str(item.get("observation_id") or "") for item in observations if item.get("observation_id")],
        },
    )
    now = time.time()
    updated_agent = replace(agent_run, status="completed", updated_at=now, result_ref=result_ref)
    runtime_host.state_index.upsert_agent_run(updated_agent)
    runtime_host.state_index.upsert_agent_run_result(
        AgentRunResult(
            agent_run_result_id=f"agresult:{agent_run.agent_run_id}",
            agent_run_id=agent_run.agent_run_id,
            task_run_id=task_run.task_run_id,
            agent_id=agent_run.agent_id,
            status="completed",
            output_ref=result_ref,
            summary=_compact_text(final_answer, limit=500),
            artifact_refs=tuple(str(item.get("path") or item.get("src") or item) for item in artifact_refs),
            created_at=now,
            diagnostics={"artifact_refs": artifact_refs},
        )
    )
    lifecycle = _load_lifecycle(runtime_host, task_run)
    finished_task, finished_lifecycle, event = finish_task_lifecycle(
        runtime_host,
        task_run=replace(task_run, diagnostics={**dict(task_run.diagnostics or {}), "artifact_refs": artifact_refs, "final_answer": final_answer}),
        lifecycle=lifecycle,
        status="completed",
        terminal_reason="completed",
        observation_refs=tuple(str(item.get("observation_id") or "") for item in observations if item.get("observation_id")),
    )
    _record_task_step_summary(
        runtime_host,
        task_run_id=task_run.task_run_id,
        step="task_run_completed",
        status="completed",
        summary="任务合同已满足，执行器已完成收尾并记录真实交付物证据。",
    )
    return {
        "ok": True,
        "task_run": finished_task.to_dict(),
        "lifecycle": finished_lifecycle.to_dict(),
        "event": event,
        "final_answer": final_answer,
        "artifact_refs": artifact_refs,
    }


def _finish_executor_failure(runtime_host: Any, *, task_run: Any, agent_run: Any, terminal_reason: str, payload: dict[str, Any]) -> dict[str, Any]:
    return _finish_executor_terminal(
        runtime_host,
        task_run=task_run,
        agent_run=agent_run,
        status="failed",
        terminal_reason=terminal_reason,
        payload=payload,
    )


def _finish_executor_blocked(runtime_host: Any, *, task_run: Any, agent_run: Any, terminal_reason: str, payload: dict[str, Any]) -> dict[str, Any]:
    return _finish_executor_terminal(
        runtime_host,
        task_run=task_run,
        agent_run=agent_run,
        status="blocked",
        terminal_reason=terminal_reason,
        payload=payload,
    )


def _finish_executor_terminal(runtime_host: Any, *, task_run: Any, agent_run: Any, status: str, terminal_reason: str, payload: dict[str, Any]) -> dict[str, Any]:
    now = time.time()
    runtime_host.state_index.upsert_agent_run(
        replace(agent_run, status="failed" if status == "failed" else "completed", updated_at=now, diagnostics={**dict(agent_run.diagnostics or {}), "terminal_reason": terminal_reason})
    )
    lifecycle = _load_lifecycle(runtime_host, task_run)
    finished_task, finished_lifecycle, event = finish_task_lifecycle(
        runtime_host,
        task_run=replace(task_run, diagnostics={**dict(task_run.diagnostics or {}), **dict(payload or {})}),
        lifecycle=lifecycle,
        status=status,  # type: ignore[arg-type]
        terminal_reason=terminal_reason,
    )
    _record_task_step_summary(
        runtime_host,
        task_run_id=task_run.task_run_id,
        step=f"task_run_{status}",
        status=status,
        summary=f"任务执行器已停止：{terminal_reason}。",
    )
    return {"ok": False, "task_run": finished_task.to_dict(), "lifecycle": finished_lifecycle.to_dict(), "event": event, "error": terminal_reason}


def _finish_without_executor(runtime_host: Any, *, task_run: Any, status: str, terminal_reason: str) -> tuple[Any, TaskLifecycleRecord, dict[str, Any]]:
    lifecycle = _load_lifecycle(runtime_host, task_run)
    return finish_task_lifecycle(
        runtime_host,
        task_run=task_run,
        lifecycle=lifecycle,
        status=status,  # type: ignore[arg-type]
        terminal_reason=terminal_reason,
    )


def _is_recoverable_protocol_terminal(task_run: Any) -> bool:
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
    recoverable = dict(diagnostics.get("recoverable_error") or {})
    terminal_reason = str(getattr(task_run, "terminal_reason", "") or "")
    return (
        str(getattr(task_run, "status", "") or "") in {"failed", "blocked"}
        and terminal_reason in {"model_action_invalid", "model_action_protocol_repair_required"}
        and bool(recoverable.get("retryable", True))
    )


def _pause_executor_for_model_recovery(
    runtime_host: Any,
    *,
    task_run: Any,
    agent_run: Any,
    packet_ref: str,
    step_index: int,
    error: Exception,
) -> dict[str, Any]:
    now = time.time()
    error_payload = _model_error_payload(error)
    observation = {
        "observation_id": f"rtobs:{task_run.task_run_id}:{uuid.uuid4().hex[:8]}",
        "task_run_id": task_run.task_run_id,
        "observation_type": "executor_error",
        "source": "system:model_runtime",
        "request_ref": f"model-action:{task_run.task_run_id}:{step_index}",
        "directive_ref": packet_ref,
        "content_chars": len(str(error_payload.get("detail") or "")),
        "payload": error_payload,
        "needs_model_followup": False,
        "created_at": now,
        "authority": "orchestration.runtime_observation",
        "error": str(error_payload.get("code") or "model_call_failed"),
    }
    runtime_host.runtime_objects.put_object("observation", observation["observation_id"], observation)
    runtime_host.event_log.append(
        task_run.task_run_id,
        "task_executor_model_call_failed",
        payload={"observation": observation},
        refs={"task_run_ref": task_run.task_run_id, "observation_ref": observation["observation_id"], "runtime_invocation_packet_ref": packet_ref},
    )
    paused_task = replace(
        task_run,
        status="blocked",
        updated_at=now,
        terminal_reason="model_call_recovery_required",
        diagnostics={
            **dict(task_run.diagnostics or {}),
            "executor_status": "blocked",
            "recoverable_error": error_payload,
            "recovery_action": "rerun_task_executor",
        },
    )
    runtime_host.state_index.upsert_task_run(paused_task)
    runtime_host.state_index.upsert_agent_run(
        replace(
            agent_run,
            status="blocked",
            updated_at=now,
            diagnostics={**dict(agent_run.diagnostics or {}), "terminal_reason": "model_call_recovery_required", "recoverable_error": error_payload},
        )
    )
    _record_task_step_summary(
        runtime_host,
        task_run_id=task_run.task_run_id,
        step="task_executor_model_recovery_required",
        status="blocked",
        summary=f"模型调用失败，任务已保留在可续跑状态：{error_payload['user_message']}",
        refs={"observation_ref": observation["observation_id"]},
    )
    return {"ok": False, "task_run": paused_task.to_dict(), "observation": observation, "error": "model_call_recovery_required"}


def _model_error_payload(error: Exception) -> dict[str, Any]:
    return {
        "error_code": "model_call_failed",
        "code": str(getattr(error, "code", "") or error.__class__.__name__),
        "retryable": bool(getattr(error, "retryable", True)),
        "user_message": str(getattr(error, "user_message", "") or "模型调用失败，任务可以稍后续跑。"),
        "provider": str(getattr(error, "provider", "") or ""),
        "model": str(getattr(error, "model", "") or ""),
        "detail": str(getattr(error, "detail", "") or error),
    }


def _load_lifecycle(runtime_host: Any, task_run: Any) -> TaskLifecycleRecord:
    try:
        payload = runtime_host.runtime_objects.get_object(f"rtobj:task_lifecycle:{task_run.task_run_id}")
    except Exception:
        payload = {}
    if payload:
        return TaskLifecycleRecord(
            task_run_id=str(payload.get("task_run_id") or task_run.task_run_id),
            contract_ref=str(payload.get("contract_ref") or task_run.task_contract_ref),
            status=str(payload.get("status") or "running"),  # type: ignore[arg-type]
            created_at=float(payload.get("created_at") or task_run.created_at or time.time()),
            updated_at=float(payload.get("updated_at") or task_run.updated_at or time.time()),
            terminal_reason=str(payload.get("terminal_reason") or ""),
            acceptance_refs=tuple(str(item) for item in list(payload.get("acceptance_refs") or [])),
            observation_refs=tuple(str(item) for item in list(payload.get("observation_refs") or [])),
        )
    return TaskLifecycleRecord(
        task_run_id=task_run.task_run_id,
        contract_ref=task_run.task_contract_ref,
        status="running",
        created_at=float(task_run.created_at or time.time()),
        updated_at=float(task_run.updated_at or time.time()),
    )


def _ensure_executor_agent_run(runtime_host: Any, *, task_run: Any) -> Any:
    runs = runtime_host.state_index.list_task_agent_runs(task_run.task_run_id)
    if runs:
        current = runs[-1]
        updated = replace(current, status="running", updated_at=time.time())
        runtime_host.state_index.upsert_agent_run(updated)
        return updated
    now = time.time()
    agent_run = AgentRun(
        agent_run_id=f"agrun:{task_run.task_run_id}:main",
        task_run_id=task_run.task_run_id,
        agent_id="agent:0",
        agent_profile_id=task_run.agent_profile_id,
        status="running",
        runtime_lane="single_agent_task",
        created_at=now,
        updated_at=now,
    )
    runtime_host.state_index.upsert_agent_run(agent_run)
    return agent_run


def _existing_observations(runtime_host: Any, task_run_id: str) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    for event in runtime_host.event_log.list_events(task_run_id):
        payload = dict(getattr(event, "payload", {}) or {})
        observation = payload.get("observation")
        if isinstance(observation, dict):
            observations.append(dict(observation))
    return observations


def _reusable_observations(runtime_host: Any, task_run_id: str) -> list[dict[str, Any]]:
    context = _observations_for_packet(runtime_host, task_run_id, current_fingerprint={})
    return list(context["packet_observations"])


def _observations_for_packet(
    runtime_host: Any,
    task_run_id: str,
    *,
    current_fingerprint: dict[str, Any],
    pending_observations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    raw_observations = [*_existing_observations(runtime_host, task_run_id), *list(pending_observations or [])]
    deduped = _dedupe_observations(raw_observations)
    records = [
        _tool_record_from_observation(observation, current_fingerprint=current_fingerprint)
        for observation in deduped
    ]
    projection = _build_execution_state_projection(records)
    return {
        "raw_observations": deduped,
        "tool_observation_records": records,
        "packet_observations": _packet_observations_from_records(records),
        "execution_state": {
            "system_projection": projection,
            "memory_summary": {},
            "context_summary": {},
            "authority": "harness.task_observation_projection",
        },
        "artifact_refs": _dedupe_artifacts(
            [
                dict(ref)
                for record in records
                if str(record.get("status") or "") == "ok" and _record_visibility(record) == "active"
                for ref in list(record.get("artifact_refs") or [])
                if isinstance(ref, dict)
            ]
        ),
    }


def _tool_record_from_observation(observation: dict[str, Any], *, current_fingerprint: dict[str, Any]) -> dict[str, Any]:
    payload = dict(observation.get("payload") or {})
    tool_name = _observation_tool_name(observation)
    tool_args = _observation_tool_args(observation)
    result_payload = _observation_result_payload(observation)
    structured_error = _structured_error_from_observation(observation)
    previous_fingerprint = _observation_runtime_fingerprint(observation)
    freshness = _classify_record_freshness(
        observation=observation,
        status=_observation_status(observation),
        structured_error=structured_error,
        previous_fingerprint=previous_fingerprint,
        current_fingerprint=current_fingerprint,
    )
    record = build_tool_observation_record(
        observation_ref=str(observation.get("observation_id") or observation.get("observation_ref") or ""),
        tool_name=tool_name,
        tool_args=tool_args,
        result=result_payload,
        runtime_fingerprint=previous_fingerprint or current_fingerprint,
        structured_error=structured_error,
        freshness=freshness,
    ).to_dict()
    status = _observation_status(observation) or str(record.get("status") or "ok")
    if status in {"failed", "denied", "canceled", "error"}:
        record["status"] = "error"
    record["source_observation"] = _compact_observation_for_record(observation)
    if payload.get("operation_gate"):
        record["side_effect_kind"] = "gate"
    return record


def _classify_record_freshness(
    *,
    observation: dict[str, Any],
    status: str,
    structured_error: dict[str, Any],
    previous_fingerprint: dict[str, Any],
    current_fingerprint: dict[str, Any],
) -> dict[str, Any]:
    if _is_completion_repair_observation(observation):
        return {
            "visibility": "active",
            "reuse_as_fact": False,
            "reuse_as_repair_context": True,
            "reason": "completion_evidence_missing",
        }
    if status not in {"failed", "denied", "canceled", "error"}:
        return {
            "visibility": "active",
            "reuse_as_fact": True,
            "reuse_as_repair_context": False,
            "reason": "current_success",
        }
    if not previous_fingerprint and current_fingerprint:
        return {
            "visibility": "historical",
            "reuse_as_fact": False,
            "reuse_as_repair_context": False,
            "reason": "missing_runtime_fingerprint",
        }
    if _fingerprints_compatible(previous_fingerprint, current_fingerprint):
        return {
            "visibility": "active",
            "reuse_as_fact": False,
            "reuse_as_repair_context": True,
            "reason": str(structured_error.get("code") or "current_failure"),
        }
    return {
        "visibility": "historical",
        "reuse_as_fact": False,
        "reuse_as_repair_context": False,
        "reason": "superseded_by_runtime_change",
    }


def _build_execution_state_projection(records: list[dict[str, Any]]) -> dict[str, Any]:
    current_facts: list[dict[str, Any]] = []
    artifact_evidence: list[dict[str, Any]] = []
    active_failures: list[dict[str, Any]] = []
    historical_failures: list[dict[str, Any]] = []
    repair_focus: list[dict[str, Any]] = []
    last_action_receipts: list[dict[str, Any]] = []
    for record in records:
        visibility = _record_visibility(record)
        status = str(record.get("status") or "ok")
        summary = _record_summary(record)
        receipt = {
            "observation_ref": str(record.get("observation_ref") or ""),
            "tool_name": str(record.get("tool_name") or ""),
            "status": status,
            "visibility": visibility,
            "summary": summary,
        }
        last_action_receipts.append(receipt)
        if status == "ok" and visibility == "active":
            current_facts.append(receipt)
            for ref in list(record.get("artifact_refs") or []):
                if isinstance(ref, dict):
                    artifact_evidence.append({**dict(ref), "observation_ref": receipt["observation_ref"]})
            continue
        failure = {
            **receipt,
            "error": dict(record.get("structured_error") or {}),
            "reason": str(dict(record.get("runtime_freshness") or {}).get("reason") or ""),
        }
        if visibility == "historical":
            historical_failures.append({**failure, "current_runtime_fact": False})
        else:
            active_failures.append(failure)
            if str(dict(record.get("structured_error") or {}).get("origin") or "") == "validator" or str(record.get("side_effect_kind") or "") == "repair":
                repair_focus.append(failure)
    return {
        "current_facts": current_facts[-12:],
        "artifact_evidence": _dedupe_artifacts(artifact_evidence)[-20:],
        "active_failures": active_failures[-8:],
        "historical_failures": historical_failures[-8:],
        "repair_focus": repair_focus[-8:],
        "open_questions": [],
        "last_action_receipts": last_action_receipts[-12:],
        "authority": "harness.task_observation_projection",
    }


def _packet_observations_from_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    packet: list[dict[str, Any]] = []
    for record in records:
        visibility = _record_visibility(record)
        status = str(record.get("status") or "ok")
        if visibility == "active" or status == "ok" or _is_record_completion_repair(record):
            packet.append(record)
        elif visibility == "historical":
            packet.append(
                {
                    "observation_ref": str(record.get("observation_ref") or ""),
                    "tool_name": str(record.get("tool_name") or ""),
                    "status": status,
                    "runtime_freshness": dict(record.get("runtime_freshness") or {}),
                    "structured_error": dict(record.get("structured_error") or {}),
                    "result_preview": _record_summary(record),
                    "authority": "orchestration.tool_observation_record.historical_summary",
                }
            )
    return packet[-24:]


def _current_runtime_fingerprint(runtime_assembly: dict[str, Any], *, runtime_host: Any, query_runtime: Any) -> dict[str, Any]:
    profile = dict(runtime_assembly.get("profile") or {})
    environment = dict(runtime_assembly.get("task_environment") or {})
    config = _safe_backend_config(query_runtime)
    return {
        "runtime_assembly_id": str(runtime_assembly.get("assembly_id") or ""),
        "agent_profile_id": str(runtime_assembly.get("agent_profile_ref") or ""),
        "runtime_mode": str(profile.get("mode") or ""),
        "task_environment_id": str(environment.get("environment_id") or ""),
        "tool_registry_hash": _stable_hash(_runtime_available_tools(runtime_assembly)),
        "tool_config_hash": _stable_hash(_tool_config_fingerprint(config)),
        "sandbox_policy_hash": _stable_hash(environment.get("sandbox_policy") or {}),
        "permission_policy_hash": _stable_hash(profile.get("permission_policy") or {}),
        "backend_config_hash": _stable_hash(config),
        "permission_mode": str(runtime_host._current_permission_mode()) if hasattr(runtime_host, "_current_permission_mode") else "",
    }


def _dedupe_observations(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in observations:
        if not isinstance(item, dict):
            continue
        if str(item.get("authority") or "") == "orchestration.tool_observation_record":
            continue
        key = str(item.get("observation_id") or item.get("observation_ref") or item.get("request_ref") or json.dumps(item, ensure_ascii=False, sort_keys=True))
        if key in seen:
            continue
        seen.add(key)
        result.append(dict(item))
    return result


def _observation_tool_name(observation: dict[str, Any]) -> str:
    payload = dict(observation.get("payload") or {})
    envelope = dict(payload.get("result_envelope") or {})
    source = str(observation.get("source") or "")
    if source.startswith("tool:"):
        source_name = source.split(":", 1)[1].strip()
    else:
        source_name = ""
    return str(
        payload.get("tool_name")
        or envelope.get("tool_name")
        or dict(payload.get("tool_call") or {}).get("name")
        or source_name
        or "system"
    ).strip()


def _observation_tool_args(observation: dict[str, Any]) -> dict[str, Any]:
    payload = dict(observation.get("payload") or {})
    envelope = dict(payload.get("result_envelope") or {})
    return dict(
        payload.get("tool_args")
        or envelope.get("tool_args")
        or dict(payload.get("tool_call") or {}).get("args")
        or {}
    )


def _observation_result_payload(observation: dict[str, Any]) -> Any:
    payload = dict(observation.get("payload") or {})
    if payload.get("result_envelope"):
        return {"result_envelope": dict(payload.get("result_envelope") or {})}
    if payload.get("structured_payload"):
        return {
            "result_envelope": {
                "tool_name": _observation_tool_name(observation),
                "tool_args": _observation_tool_args(observation),
                "status": "error" if _observation_status(observation) in {"failed", "denied", "canceled", "error"} else "ok",
                "text": str(payload.get("result") or payload.get("error") or ""),
                "structured_payload": dict(payload.get("structured_payload") or {}),
                "artifact_refs": list(payload.get("artifact_refs") or []),
                "error": str(payload.get("error") or observation.get("error") or ""),
            }
        }
    if payload.get("result") is not None:
        return str(payload.get("result") or "")
    if payload.get("error") or observation.get("error"):
        return {
            "result_envelope": {
                "tool_name": _observation_tool_name(observation),
                "tool_args": _observation_tool_args(observation),
                "status": "error",
                "text": str(payload.get("error") or observation.get("error") or ""),
                "structured_payload": {},
                "error": str(payload.get("error") or observation.get("error") or ""),
            }
        }
    return payload


def _observation_status(observation: dict[str, Any]) -> str:
    payload = dict(observation.get("payload") or {})
    envelope = dict(payload.get("result_envelope") or {})
    structured = dict(payload.get("structured_payload") or envelope.get("structured_payload") or {})
    tool_result = dict(structured.get("tool_result") or {}) if isinstance(structured.get("tool_result"), dict) else {}
    operation_gate = dict(payload.get("operation_gate") or {})
    if operation_gate and operation_gate.get("allowed") is False:
        return "denied"
    if str(observation.get("observation_type") or "") == "executor_error":
        return "failed"
    if observation.get("error") or payload.get("error"):
        return "failed"
    if str(envelope.get("status") or "").strip() in {"error", "failed", "denied", "canceled"}:
        return "failed"
    if str(tool_result.get("status") or "").strip() in {"error", "failed", "denied", "canceled"}:
        return "failed"
    parsed = _json_payload(payload.get("result"))
    if parsed.get("ok") is False:
        return "failed"
    if parsed.get("ok") is True:
        return "ok"
    return "ok"


def _structured_error_from_observation(observation: dict[str, Any]) -> dict[str, Any]:
    payload = dict(observation.get("payload") or {})
    envelope = dict(payload.get("result_envelope") or {})
    structured = dict(payload.get("structured_payload") or envelope.get("structured_payload") or {})
    tool_result = dict(structured.get("tool_result") or {}) if isinstance(structured.get("tool_result"), dict) else {}
    operation_gate = dict(payload.get("operation_gate") or {})
    if operation_gate and operation_gate.get("allowed") is False:
        return {
            "code": str(operation_gate.get("reason") or payload.get("error") or "operation_gate_denied"),
            "message": str(operation_gate.get("reason") or payload.get("error") or "operation gate denied"),
            "retryable": False,
            "origin": "operation_gate",
        }
    for source in (tool_result, structured, envelope, payload):
        error = source.get("error") if isinstance(source, dict) else None
        if isinstance(error, dict):
            return {
                "code": str(error.get("code") or error.get("error_code") or source.get("code") or "tool_error"),
                "message": str(error.get("message") or error.get("detail") or error),
                "retryable": bool(error.get("retryable", source.get("retryable", True))),
                "origin": str(error.get("origin") or source.get("origin") or "tool_provider"),
            }
    message = str(payload.get("error") or envelope.get("error") or observation.get("error") or tool_result.get("error") or "")
    if message:
        structured_error = payload.get("structured_error")
        if isinstance(structured_error, dict) and structured_error:
            return {
                "code": str(structured_error.get("code") or payload.get("error_code") or payload.get("code") or "tool_error"),
                "message": str(structured_error.get("message") or message),
                "retryable": bool(structured_error.get("retryable", payload.get("retryable", True))),
                "origin": str(structured_error.get("origin") or _error_origin(observation)),
            }
        return {
            "code": str(payload.get("error_code") or payload.get("code") or "tool_error"),
            "message": message,
            "retryable": bool(payload.get("retryable", True)),
            "origin": _error_origin(observation),
        }
    if _is_completion_repair_observation(observation):
        return {
            "code": "completion_evidence_missing",
            "message": "completion evidence missing",
            "retryable": True,
            "origin": "validator",
        }
    return {}


def _error_origin(observation: dict[str, Any]) -> str:
    source = str(observation.get("source") or "")
    if source == "system:model_runtime":
        return "model_runtime"
    if source == "system:model_action_protocol":
        return "model_protocol"
    if source == "system:task_completion_validator":
        return "validator"
    if source.startswith("tool:"):
        return "tool_provider"
    return "runtime"


def _observation_runtime_fingerprint(observation: dict[str, Any]) -> dict[str, Any]:
    payload = dict(observation.get("payload") or {})
    for source in (
        payload.get("runtime_fingerprint"),
        dict(payload.get("runtime_freshness") or {}).get("fingerprint") if isinstance(payload.get("runtime_freshness"), dict) else {},
        dict(observation.get("runtime_freshness") or {}).get("fingerprint") if isinstance(observation.get("runtime_freshness"), dict) else {},
    ):
        if isinstance(source, dict) and source:
            return dict(source)
    packet_ref = str(observation.get("directive_ref") or "")
    assembly_id = ""
    if ":task_execution:" in packet_ref:
        assembly_id = packet_ref.split(":task_execution:", 1)[0].replace("rtpacket:", "rtasm:")
    return {"runtime_assembly_id": assembly_id} if assembly_id else {}


def _fingerprints_compatible(previous: dict[str, Any], current: dict[str, Any]) -> bool:
    if not previous or not current:
        return True
    keys = ("tool_registry_hash", "tool_config_hash", "sandbox_policy_hash", "permission_policy_hash", "backend_config_hash")
    compared = [key for key in keys if previous.get(key) and current.get(key)]
    if not compared:
        return str(previous.get("runtime_assembly_id") or "") == str(current.get("runtime_assembly_id") or "") or not previous.get("runtime_assembly_id")
    return all(str(previous.get(key)) == str(current.get(key)) for key in compared)


def _is_completion_repair_observation(observation: dict[str, Any]) -> bool:
    payload = dict(observation.get("payload") or {})
    return str(payload.get("error_code") or "") == "completion_evidence_missing" or str(observation.get("source") or "") == "system:task_completion_validator"


def _is_record_completion_repair(record: dict[str, Any]) -> bool:
    error = dict(record.get("structured_error") or {})
    return str(error.get("origin") or "") == "validator" or str(error.get("code") or "") == "completion_evidence_missing"


def _record_visibility(record: dict[str, Any]) -> str:
    return str(dict(record.get("runtime_freshness") or {}).get("visibility") or "active")


def _record_summary(record: dict[str, Any]) -> str:
    error = dict(record.get("structured_error") or {})
    if error.get("message"):
        return _compact_text(str(error.get("message") or ""), limit=400)
    return _compact_text(str(record.get("result_preview") or ""), limit=400)


def _compact_observation_for_record(observation: dict[str, Any]) -> dict[str, Any]:
    return {
        "observation_id": str(observation.get("observation_id") or ""),
        "observation_type": str(observation.get("observation_type") or ""),
        "source": str(observation.get("source") or ""),
        "request_ref": str(observation.get("request_ref") or ""),
        "created_at": observation.get("created_at"),
    }


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _safe_backend_config(query_runtime: Any) -> dict[str, Any]:
    config = dict(getattr(query_runtime, "config", {}) or {})
    image = dict(config.get("image_generation") or config.get("images") or config.get("soul_image_assets") or {})
    return {
        "image_generation": {
            "base_url": str(image.get("base_url") or image.get("api_base") or ""),
            "model": str(image.get("model") or ""),
            "api_key_present": bool(image.get("api_key") or image.get("key")),
        }
    }


def _tool_config_fingerprint(config: dict[str, Any]) -> dict[str, Any]:
    return dict(config.get("image_generation") or {})


def _strip_terminal_diagnostics(diagnostics: dict[str, Any]) -> dict[str, Any]:
    payload = dict(diagnostics or {})
    for key in (
        "observation",
        "latest_step",
        "latest_step_status",
        "latest_step_summary",
        "terminal_reason",
        "action_request",
        "admission",
        "diagnostics",
        "recoverable_error",
        "recovery_action",
        "user_question",
    ):
        payload.pop(key, None)
    return payload


def _completion_repair_observation(*, task_run_id: str, packet_ref: str, action_request: ModelActionRequest, verdict: dict[str, Any]) -> dict[str, Any]:
    return {
        "observation_id": f"rtobs:{task_run_id}:{uuid.uuid4().hex[:8]}",
        "task_run_id": task_run_id,
        "observation_type": "executor_error",
        "source": "system:task_completion_validator",
        "request_ref": action_request.request_id,
        "directive_ref": packet_ref,
        "content_chars": 0,
        "payload": {"error_code": "completion_evidence_missing", "verdict": verdict, "rejected_action_request": action_request.to_dict()},
        "needs_model_followup": True,
        "created_at": time.time(),
        "authority": "orchestration.runtime_observation",
        "error": "completion_evidence_missing",
    }


def _model_protocol_repair_observation(
    *,
    task_run_id: str,
    packet_ref: str,
    step_index: int,
    diagnostics: dict[str, Any],
    runtime_fingerprint: dict[str, Any],
) -> dict[str, Any]:
    errors = [str(item) for item in list(dict(diagnostics or {}).get("validation_errors") or [])]
    message = "model action request failed protocol validation"
    if errors:
        message = f"{message}: {', '.join(errors)}"
    return {
        "observation_id": f"rtobs:{task_run_id}:{uuid.uuid4().hex[:8]}",
        "task_run_id": task_run_id,
        "observation_type": "executor_error",
        "source": "system:model_action_protocol",
        "request_ref": f"model-action:{task_run_id}:{step_index}",
        "directive_ref": packet_ref,
        "content_chars": len(message),
        "payload": {
            "tool_name": "model_action_protocol",
            "tool_args": {},
            "error": message,
            "error_code": "model_action_invalid",
            "validation_errors": errors,
            "structured_error": {
                "code": "model_action_invalid",
                "message": message,
                "retryable": True,
                "origin": "model_protocol",
            },
            "runtime_fingerprint": dict(runtime_fingerprint or {}),
        },
        "needs_model_followup": True,
        "created_at": time.time(),
        "authority": "orchestration.runtime_observation",
        "error": "model_action_invalid",
    }


def _model_protocol_repair_count(observations: list[dict[str, Any]]) -> int:
    return sum(1 for item in observations if str(item.get("source") or "") == "system:model_action_protocol")


def _executor_error_observation(*, task_run_id: str, request_ref: str, directive_ref: str, tool_name: str, tool_args: dict[str, Any], error: str) -> dict[str, Any]:
    return {
        "observation_id": f"rtobs:{task_run_id}:{uuid.uuid4().hex[:8]}",
        "task_run_id": task_run_id,
        "observation_type": "executor_error",
        "source": f"tool:{tool_name}",
        "request_ref": request_ref,
        "directive_ref": directive_ref,
        "content_chars": len(error),
        "payload": {"tool_name": tool_name, "tool_args": tool_args, "error": error},
        "needs_model_followup": False,
        "created_at": time.time(),
        "authority": "orchestration.runtime_observation",
        "error": error,
    }


def _artifact_refs_from_observations(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for observation in observations:
        refs.extend(_artifact_refs_from_observation(observation))
    return _dedupe_artifacts(refs)


def _artifact_refs_from_observation(observation: dict[str, Any]) -> list[dict[str, Any]]:
    payload = dict(observation.get("payload") or {})
    envelope = dict(payload.get("result_envelope") or {})
    structured = dict(payload.get("structured_payload") or envelope.get("structured_payload") or {})
    refs = [
        dict(item)
        for item in list(payload.get("artifact_refs") or envelope.get("artifact_refs") or structured.get("artifact_refs") or [])
        if isinstance(item, dict)
    ]
    if refs:
        return refs
    image = dict(_json_payload(payload.get("result")).get("image") or {})
    path = str(image.get("file_path") or image.get("src") or "").strip()
    if path:
        return [{"path": path, "kind": "image", "source": "image_generate"}]
    return []


def _artifacts_from_action(action_request: ModelActionRequest) -> list[dict[str, Any]]:
    diagnostics = dict(action_request.diagnostics or {})
    return [dict(item) for item in list(diagnostics.get("artifacts") or []) if isinstance(item, dict)]


def _dedupe_artifacts(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ref in refs:
        key = str(ref.get("path") or ref.get("src") or json.dumps(ref, ensure_ascii=False, sort_keys=True))
        if key in seen:
            continue
        seen.add(key)
        result.append(dict(ref))
    return result


def _verified_artifacts(
    *,
    runtime_host: Any,
    runtime_assembly: dict[str, Any],
    task_run_id: str,
    artifact_refs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    project_root = ProjectLayout.from_backend_dir(runtime_host.backend_dir).project_root.resolve()
    sandbox_policy = _task_sandbox_policy(runtime_assembly, runtime_host=runtime_host, task_run_id=task_run_id)
    sandbox_root = Path(str(sandbox_policy.get("sandbox_root") or "")).resolve()
    artifact_root = str(sandbox_policy.get("artifact_root") or "").replace("\\", "/").strip().strip("/")
    publish_roots = tuple(
        str(item or "").replace("\\", "/").strip().strip("/")
        for item in list(sandbox_policy.get("write_scopes") or [])
        if str(item or "").strip()
    )
    verified: list[dict[str, Any]] = []
    for ref in _dedupe_artifacts(artifact_refs):
        resolved = _publish_or_resolve_artifact_ref(
            ref,
            project_root=project_root,
            sandbox_root=sandbox_root,
            artifact_root=artifact_root,
            publish_roots=publish_roots,
        )
        if resolved is None or not resolved.exists() or not resolved.is_file():
            continue
        try:
            logical_path = resolved.relative_to(project_root).as_posix()
        except ValueError:
            logical_path = str(resolved)
        verified.append(
            {
                **dict(ref),
                "path": logical_path,
                "absolute_path": str(resolved),
                "exists": True,
                "size_bytes": resolved.stat().st_size,
                "published": True,
            }
        )
    return _dedupe_artifacts(verified)


def _publish_or_resolve_artifact_ref(
    ref: dict[str, Any],
    *,
    project_root: Path,
    sandbox_root: Path,
    artifact_root: str,
    publish_roots: tuple[str, ...] = (),
) -> Path | None:
    logical_path = str(ref.get("path") or ref.get("published_path") or ref.get("src") or "").replace("\\", "/").strip().strip("/")
    if logical_path:
        project_candidate = (project_root / logical_path).resolve()
        if _is_inside(project_candidate, project_root) and project_candidate.exists() and project_candidate.is_file():
            return project_candidate
    sandbox_source = _sandbox_artifact_source(ref, sandbox_root=sandbox_root)
    if sandbox_source is None or not sandbox_source.exists() or not sandbox_source.is_file():
        return None
    if not logical_path or not _logical_path_publish_allowed(logical_path, artifact_root, publish_roots):
        return None
    publish_target = (project_root / logical_path).resolve()
    if not _is_inside(publish_target, project_root):
        return None
    publish_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(sandbox_source, publish_target)
    return publish_target


def _sandbox_artifact_source(ref: dict[str, Any], *, sandbox_root: Path) -> Path | None:
    for key in ("absolute_path", "sandbox_path"):
        raw = str(ref.get(key) or "").strip()
        if not raw:
            continue
        candidate = Path(raw)
        if candidate.is_absolute():
            resolved = candidate.resolve()
        else:
            resolved = (sandbox_root / raw).resolve()
        if _is_inside(resolved, sandbox_root):
            return resolved
    return None


def _logical_path_within_artifact_root(logical_path: str, artifact_root: str) -> bool:
    if not artifact_root:
        return False
    return logical_path == artifact_root or logical_path.startswith(f"{artifact_root}/")


def _logical_path_publish_allowed(logical_path: str, artifact_root: str, publish_roots: tuple[str, ...]) -> bool:
    normalized = str(logical_path or "").replace("\\", "/").strip().strip("/")
    if not normalized:
        return False
    if _logical_path_within_artifact_root(normalized, artifact_root):
        return True
    for root in publish_roots:
        clean_root = str(root or "").replace("\\", "/").strip().strip("/")
        if clean_root and (normalized == clean_root or normalized.startswith(f"{clean_root}/")):
            return True
    return False


def _is_inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _json_payload(value: Any) -> dict[str, Any]:
    try:
        parsed = json.loads(str(value or ""))
    except Exception:
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _runtime_available_tools(runtime_assembly_payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        dict(item)
        for item in list(runtime_assembly_payload.get("available_tools") or [])
        if isinstance(item, dict) and str(item.get("tool_name") or "").strip()
    ]


def _runtime_allowed_tool_names(available_tools: list[dict[str, Any]]) -> set[str]:
    return {str(item.get("tool_name") or "").strip() for item in available_tools if str(item.get("tool_name") or "").strip()}


def _record_task_step_summary(runtime_host: Any, *, task_run_id: str, step: str, status: str, summary: str, refs: dict[str, Any] | None = None) -> dict[str, Any]:
    event = runtime_host.event_log.append(
        task_run_id,
        "step_summary_recorded",
        payload={"task_run_id": task_run_id, "step": step, "status": status, "summary": summary},
        refs={"task_run_ref": task_run_id, **dict(refs or {})},
    )
    current = runtime_host.state_index.get_task_run(task_run_id)
    if current is not None:
        runtime_host.state_index.upsert_task_run(
            replace(
                current,
                updated_at=event.created_at,
                latest_event_offset=event.offset,
                diagnostics={**dict(current.diagnostics or {}), "latest_step": step, "latest_step_status": status, "latest_step_summary": summary},
            )
        )
    return event.to_dict()


def _public_policy(policy: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in dict(policy or {}).items()
        if key in {"enabled", "sandbox_root", "workspace_root", "artifact_root", "write_scopes", "approval_policy", "side_effect_operations"}
    }


def _not_found(task_run_id: str) -> dict[str, Any]:
    return {"ok": False, "task_run_id": task_run_id, "error": "task_run_not_found"}


def _conflict(task_run_id: str, error: str) -> dict[str, Any]:
    return {"ok": False, "task_run_id": task_run_id, "error": error}
