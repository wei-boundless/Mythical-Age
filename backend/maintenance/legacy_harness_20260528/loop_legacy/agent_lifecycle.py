from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

from harness.loop_legacy.checkpoint_store import HarnessCheckpoint
from harness.loop_legacy.state import HarnessLoopState
from harness.runtime_legacy.agent_todo import initialize_agent_todo_plan
from runtime.shared.models import AgentRun, CoordinationRun, TaskRun


@dataclass(frozen=True, slots=True)
class AgentRuntimeStartResult:
    task_run: TaskRun
    agent_run: AgentRun
    coordination_run: CoordinationRun | None
    loop_state: HarnessLoopState
    checkpoint: HarnessCheckpoint
    events: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_run": self.task_run.to_dict(),
            "agent_run": self.agent_run.to_dict(),
            "coordination_run": self.coordination_run.to_dict() if self.coordination_run is not None else None,
            "loop_state": self.loop_state.to_dict(),
            "checkpoint": self.checkpoint.to_dict(),
            "events": [dict(item) for item in self.events],
        }


def start_agent_run(
    runtime_host: Any,
    *,
    session_id: str,
    task_id: str,
    task_contract_ref: str = "",
    agent_id: str = "agent:0",
    agent_profile_id: str = "main_interactive_agent",
    runtime_lane: str = "standard_task",
    task_agent_binding_ref: str = "",
    skill_workflow_ref: str = "",
    health_issue_ref: str = "",
    execution_mode: str = "agent_runtime",
    runtime_assembly: dict[str, Any] | None = None,
    diagnostics: dict[str, Any] | None = None,
) -> AgentRuntimeStartResult:
    now = time.time()
    assembly_payload = dict(runtime_assembly or {})
    assembly_ref = str(assembly_payload.get("assembly_id") or "")
    manifest_ref = str(assembly_payload.get("manifest_ref") or "")
    working_memory_refs = working_memory_refs_from_assembly(assembly_payload)
    working_memory_diag = working_memory_diagnostics_from_assembly(assembly_payload)
    task_run_id = f"taskrun:{session_id}:{task_id}:{uuid.uuid4().hex[:8]}"
    agent_run_id = f"agrun:{task_run_id}:main"
    started = runtime_host.event_log.append(
        task_run_id,
        "task_run_started",
        payload={
            "session_id": session_id,
            "task_id": task_id,
            "task_contract_ref": task_contract_ref,
            "agent_id": agent_id,
            "agent_profile_id": agent_profile_id,
            "runtime_lane": runtime_lane,
            "task_agent_binding_ref": task_agent_binding_ref,
            "skill_workflow_ref": skill_workflow_ref,
            "health_issue_ref": health_issue_ref,
            "execution_mode": execution_mode,
            "runtime_assembly_ref": assembly_ref,
            "contract_manifest_ref": manifest_ref,
            "working_memory_refs": working_memory_refs,
        },
        refs={
            "task_contract_ref": task_contract_ref,
            "runtime_assembly_ref": assembly_ref,
            "contract_manifest_ref": manifest_ref,
            "working_memory_ref": ",".join(working_memory_refs),
        },
    )
    agent_run = AgentRun(
        agent_run_id=agent_run_id,
        task_run_id=task_run_id,
        agent_id=agent_id,
        agent_profile_id=agent_profile_id,
        role="main_executor",
        spawn_mode=execution_mode,
        context_scope="task_default",
        runtime_lane=runtime_lane,
        status="running",
        created_at=now,
        updated_at=now,
        diagnostics={
            "task_agent_binding_ref": task_agent_binding_ref,
            "skill_workflow_ref": skill_workflow_ref,
            "health_issue_ref": health_issue_ref,
        },
    )
    agent_run_event = runtime_host.event_log.append(
        task_run_id,
        "agent_run_created",
        payload={"agent_run": agent_run.to_dict()},
        refs={"agent_run_ref": agent_run.agent_run_id},
    )
    iteration = runtime_host.event_log.append(
        task_run_id,
        "loop_iteration_started",
        payload={
            "transition": "start",
            "turn_count": 0,
            "step_count": 0,
        },
    )
    todo_plan = initialize_agent_todo_plan(
        root_dir=runtime_host.root_dir,
        session_id=session_id,
        task_id=task_id,
        task_run_id=task_run_id,
        coverage_refs=tuple(ref for ref in (task_contract_ref, assembly_ref, manifest_ref) if ref),
    )
    todo_event = runtime_host.event_log.append(
        task_run_id,
        "agent_todo_initialized",
        payload={
            "plan": todo_plan.to_dict(),
            "lifecycle_boundary": "task_run_start_initializes_todo",
        },
        refs={
            "agent_todo_plan_ref": todo_plan.plan_id,
            "task_contract_ref": task_contract_ref,
        },
    )
    state = HarnessLoopState(
        task_run_id=task_run_id,
        status="running",
        transition="start",
        agent_id=agent_id,
        agent_profile_id=agent_profile_id,
        runtime_lane=runtime_lane,
        task_agent_binding_ref=task_agent_binding_ref,
        task_template_id="",
        task_spec_ref="",
        task_result_ref="",
        skill_workflow_ref=skill_workflow_ref,
        health_issue_ref=health_issue_ref,
        diagnostics={
            "loop_owner": "harness.loop.agent_lifecycle",
            "loop_phase": "event_checkpoint_spine",
            "query_runtime_role": "adapter_only",
            "loop_limits": runtime_host.limits.to_dict(),
            "runtime_assembly_ref": assembly_ref,
            "contract_manifest_ref": manifest_ref,
            "agent_todo_plan_ref": todo_plan.plan_id,
            "working_memory_refs": working_memory_refs,
            **working_memory_diag,
            **dict(diagnostics or {}),
        },
    )
    checkpoint = runtime_host.checkpoints.write(
        state,
        event_offset=iteration.offset,
        execution_refs=(),
        execution_state_ref="",
        working_memory_refs=tuple(working_memory_refs),
        execution_summary=runtime_host.execution_store.build_summary(task_run_id),
        agent_runs=(agent_run,),
    )
    checkpoint_event = runtime_host.event_log.append(
        task_run_id,
        "checkpoint_written",
        payload={
            "checkpoint_id": checkpoint.checkpoint_id,
            "event_offset": checkpoint.event_offset,
            "checksum": checkpoint.checksum,
            "execution_summary": checkpoint.execution_summary,
            "runtime_objects_summary": checkpoint.runtime_objects_summary,
        },
        refs={"checkpoint_ref": checkpoint.checkpoint_id},
    )
    task_run = TaskRun(
        task_run_id=task_run_id,
        session_id=session_id,
        task_id=task_id,
        task_contract_ref=task_contract_ref,
        agent_id=agent_id,
        agent_profile_id=agent_profile_id,
        runtime_lane=runtime_lane,
        status="running",
        created_at=now,
        updated_at=time.time(),
        latest_event_offset=checkpoint_event.offset,
        latest_checkpoint_ref=checkpoint.checkpoint_id,
        diagnostics={
            "loop_owner": "harness.loop.agent_lifecycle",
            "agent_id": agent_id,
            "agent_profile_id": agent_profile_id,
            "runtime_lane": runtime_lane,
            "task_agent_binding_ref": task_agent_binding_ref,
            "skill_workflow_ref": skill_workflow_ref,
            "health_issue_ref": health_issue_ref,
            "main_agent_run_ref": agent_run.agent_run_id,
            "execution_mode": execution_mode,
            "loop_limits": runtime_host.limits.to_dict(),
            "runtime_assembly_ref": assembly_ref,
            "contract_manifest_ref": manifest_ref,
            "agent_todo_plan_ref": todo_plan.plan_id,
            "working_memory_refs": working_memory_refs,
            **working_memory_diag,
            **dict(diagnostics or {}),
        },
    )
    runtime_host.state_index.upsert_task_run(task_run)
    runtime_host.state_index.upsert_agent_run(agent_run)
    ordered_events = [started.to_dict(), agent_run_event.to_dict()]
    ordered_events.extend((iteration.to_dict(), todo_event.to_dict(), checkpoint_event.to_dict()))
    return AgentRuntimeStartResult(
        task_run=task_run,
        agent_run=agent_run,
        coordination_run=None,
        loop_state=state,
        checkpoint=checkpoint,
        events=tuple(ordered_events),
    )


def write_checkpoint_event(runtime_host: Any, state: HarnessLoopState, *, event_offset: int):
    execution_summary = runtime_host.execution_store.build_summary(state.task_run_id)
    execution_refs = tuple(str(item) for item in list(execution_summary.get("execution_refs") or []))
    execution_state_ref = str(execution_summary.get("latest_execution_id") or "")
    agent_runs = tuple(runtime_host.state_index.list_task_agent_runs(state.task_run_id))
    coordination_runs = tuple(runtime_host.state_index.list_task_coordination_runs(state.task_run_id))
    checkpoint = runtime_host.checkpoints.write(
        state,
        event_offset=event_offset,
        execution_refs=execution_refs,
        execution_state_ref=execution_state_ref,
        working_memory_refs=tuple(
            str(item).strip()
            for item in list(state.diagnostics.get("working_memory_refs") or [])
            if str(item).strip()
        ),
        execution_summary=execution_summary,
        agent_runs=agent_runs,
        coordination_runs=coordination_runs,
    )
    return runtime_host.event_log.append(
        state.task_run_id,
        "checkpoint_written",
        payload={
            "checkpoint_id": checkpoint.checkpoint_id,
            "event_offset": checkpoint.event_offset,
            "checksum": checkpoint.checksum,
            "execution_summary": execution_summary,
            "runtime_objects_summary": checkpoint.runtime_objects_summary,
        },
        refs={"checkpoint_ref": checkpoint.checkpoint_id},
    )


def state_with_task_run_ledger(
    state: HarnessLoopState,
    ledger: Any | None,
    *,
    transition: str | None = None,
    task_result_ref: str | None = None,
    result_refs: list[str] | tuple[str, ...] | None = None,
    status: str | None = None,
    terminal_reason: str | None = None,
    diagnostics: dict[str, Any] | None = None,
    commit_state: dict[str, Any] | None = None,
) -> HarnessLoopState:
    from task_system.tasks.run_models import task_run_step_count

    merged_diagnostics = dict(state.diagnostics)
    if diagnostics:
        merged_diagnostics.update(diagnostics)
    return HarnessLoopState(
        task_run_id=state.task_run_id,
        status=status or state.status,
        turn_count=state.turn_count,
        step_count=task_run_step_count(ledger),
        current_step_id=ledger.current_step_id if ledger is not None else state.current_step_id,
        agent_id=state.agent_id,
        agent_profile_id=state.agent_profile_id,
        runtime_lane=state.runtime_lane,
        task_agent_binding_ref=state.task_agent_binding_ref,
        task_template_id=ledger.template_id if ledger is not None else state.task_template_id,
        task_spec_ref=ledger.task_spec_ref if ledger is not None else state.task_spec_ref,
        task_result_ref=task_result_ref if task_result_ref is not None else state.task_result_ref,
        skill_workflow_ref=state.skill_workflow_ref,
        health_issue_ref=state.health_issue_ref,
        transition=transition or state.transition,
        terminal_reason=terminal_reason if terminal_reason is not None else state.terminal_reason,
        messages_ref=state.messages_ref,
        context_snapshot_ref=state.context_snapshot_ref,
        memory_state_ref=state.memory_state_ref,
        prompt_manifest_ref=state.prompt_manifest_ref,
        pending_action_requests=state.pending_action_requests,
        pending_approval_state=state.pending_approval_state,
        denial_tracking_state=state.denial_tracking_state,
        token_pressure=state.token_pressure,
        compaction_state=state.compaction_state,
        result_refs=tuple(result_refs) if result_refs is not None else state.result_refs,
        commit_state=dict(commit_state or state.commit_state),
        diagnostics=merged_diagnostics,
    )
def working_memory_refs_from_assembly(assembly: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for section in list(dict(assembly or {}).get("context_sections") or []):
        if not isinstance(section, dict):
            continue
        metadata = dict(section.get("metadata") or {})
        for item in list(metadata.get("refs") or []):
            value = str(item or "").strip()
            if value and value not in refs:
                refs.append(value)
    return refs


def working_memory_diagnostics_from_assembly(assembly: dict[str, Any]) -> dict[str, Any]:
    diagnostics = dict(dict(assembly or {}).get("diagnostics") or {})
    keys = (
        "working_memory_enabled",
        "working_memory_task_run_id",
        "working_memory_graph_id",
        "working_memory_owner_node_id",
        "working_memory_node_run_id",
        "working_memory_run_attempt_id",
        "working_memory_required_count",
        "working_memory_preferred_count",
        "working_memory_conflict_count",
    )
    return {
        key: diagnostics.get(key)
        for key in keys
        if key in diagnostics
    }



