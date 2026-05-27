from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from task_system.tasks.run_models import task_run_step_count

from runtime.context_management.system_retrieval import build_context_policy_with_retrieval
from runtime.shared.models import RuntimeLoopState


@dataclass(frozen=True, slots=True)
class AgentRuntimeContextPreflightResult:
    state: RuntimeLoopState
    context_snapshot: Any
    events: tuple[dict[str, Any], ...]


def prepare_agent_runtime_context(
    *,
    runtime_host: Any,
    state: RuntimeLoopState,
    runtime_task_ledger: Any,
    session_id: str,
    task_id: str,
    user_message: str,
    history: list[dict[str, Any]],
    memory_intent: Any,
    memory_view: dict[str, Any],
    context_policy: dict[str, Any],
    retrieval_results: list[dict[str, Any]] | None,
    agent_runtime_chain: Any,
    task_operation: dict[str, Any],
    allowed_search_sources: set[str],
    task_contract_ref: str,
    task_body_orchestration_payload: dict[str, Any],
    agent_runtime_spec_payload: dict[str, Any],
    assembly_contract: dict[str, Any],
    runtime_context_manager: Any,
    effective_runtime_execution_facts: dict[str, Any],
    selected_recipe_payload: dict[str, Any],
    task_spec_payload: dict[str, Any],
    effective_limits: Any,
) -> AgentRuntimeContextPreflightResult:
    """Build the model context snapshot from system-owned runtime observations."""

    events: list[dict[str, Any]] = []
    effective_context_policy = (
        build_context_policy_with_retrieval(
            agent_runtime_chain=agent_runtime_chain,
            session_id=session_id,
            user_message=user_message,
            memory_intent=memory_intent,
            task_operation=task_operation,
            retrieval_results=retrieval_results,
            allowed_search_sources=allowed_search_sources,
        )
        if retrieval_results
        else context_policy
    )
    context_snapshot = runtime_context_manager.prepare_model_context(
        session_id=session_id,
        task_id=task_id,
        user_message=user_message,
        history=history,
        memory_intent=memory_intent,
        memory_runtime_view=memory_view,
        context_policy_result=effective_context_policy,
        stage_projection_snapshot=None,
        runtime_execution_facts=effective_runtime_execution_facts,
        runtime_assembly=dict(
            assembly_contract.get("runtime_assembly")
            or dict(task_operation.get("current_turn_context") or {}).get("runtime_assembly")
            or {}
        ),
        agent_assembly_contract=assembly_contract,
    )
    context_event = runtime_host.event_log.append(
        state.task_run_id,
        "context_snapshot_built",
        payload={
            "context_snapshot": context_snapshot.to_dict(),
            "context_policy_result": effective_context_policy,
        },
        refs={
            "memory_runtime_view_ref": str(memory_view.get("view_id") or ""),
            "context_snapshot_ref": context_snapshot.snapshot_id,
            "context_policy_ref": context_snapshot.context_policy_ref,
            "task_body_orchestration_ref": str(task_body_orchestration_payload.get("orchestration_id") or ""),
            "agent_runtime_spec_ref": str(agent_runtime_spec_payload.get("runtime_spec_id") or ""),
        },
    )
    events.append({"type": "runtime_loop_event", "event": context_event.to_dict()})
    invariant_report = runtime_context_manager.check_invariants(context_snapshot)
    invariant_event = runtime_host.event_log.append(
        state.task_run_id,
        "context_invariant_checked",
        payload={"invariant_report": invariant_report.to_dict()},
        refs={
            "context_snapshot_ref": context_snapshot.snapshot_id,
            "invariant_report_ref": invariant_report.report_id,
        },
    )
    events.append({"type": "runtime_loop_event", "event": invariant_event.to_dict()})
    events.append({"type": "runtime_context_invariant", "report": invariant_report.to_dict()})

    updated_state = RuntimeLoopState(
        task_run_id=state.task_run_id,
        status="running",
        transition="start",
        turn_count=1,
        step_count=task_run_step_count(runtime_task_ledger),
        current_step_id=runtime_task_ledger.current_step_id if runtime_task_ledger is not None else "",
        agent_id=state.agent_id,
        agent_profile_id=state.agent_profile_id,
        runtime_lane=state.runtime_lane,
        task_agent_binding_ref=state.task_agent_binding_ref,
        task_template_id=str(
            selected_recipe_payload.get("template_id")
            or selected_recipe_payload.get("recipe_id")
            or ""
        ),
        task_spec_ref=str(task_spec_payload.get("task_spec_ref") or ""),
        task_result_ref="",
        skill_workflow_ref=state.skill_workflow_ref,
        health_issue_ref=state.health_issue_ref,
        memory_state_ref=str(memory_view.get("view_id") or ""),
        context_snapshot_ref=context_snapshot.snapshot_id,
        projection_ref="",
        prompt_manifest_ref="",
        token_pressure=dict(context_snapshot.token_pressure),
        diagnostics={
            **dict(state.diagnostics),
            "task_contract_ref": task_contract_ref,
            "runtime_chain_built": True,
            "effective_loop_limits": effective_limits.to_dict(),
            "runtime_context_manager_applied": True,
            "stage_projection_cycle_applied": False,
            "stage_projection_disabled_reason": "task_environment_runtime_start_packet",
            "task_body_orchestration_ref": str(task_body_orchestration_payload.get("orchestration_id") or ""),
            "agent_runtime_spec_ref": str(agent_runtime_spec_payload.get("runtime_spec_id") or ""),
            "context_invariant_checked": True,
            "context_needs_compaction": invariant_report.needs_compaction,
            "task_template_id": str(
                selected_recipe_payload.get("template_id")
                or selected_recipe_payload.get("recipe_id")
                or ""
            ),
            "task_spec_ref": str(task_spec_payload.get("task_spec_ref") or ""),
        },
    )
    checkpoint = runtime_host._write_checkpoint_event(updated_state, event_offset=invariant_event.offset)
    events.append({"type": "runtime_loop_event", "event": checkpoint.to_dict()})
    return AgentRuntimeContextPreflightResult(
        state=updated_state,
        context_snapshot=context_snapshot,
        events=tuple(events),
    )
