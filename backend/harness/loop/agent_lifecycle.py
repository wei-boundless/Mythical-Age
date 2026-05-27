from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

from runtime.shared.checkpoint import RuntimeCheckpoint
from runtime.shared.dispatch_plan_compiler import compile_agent_dispatch_plan_from_graph_payload
from runtime.shared.models import AgentRun, CoordinationRun, RuntimeLoopState, TaskRun
from .graph_flow import build_graph_flow_state


@dataclass(frozen=True, slots=True)
class AgentRuntimeStartResult:
    task_run: TaskRun
    agent_run: AgentRun
    coordination_run: CoordinationRun | None
    loop_state: RuntimeLoopState
    checkpoint: RuntimeCheckpoint
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
    graph_ref: str = "",
    graph_payload: dict[str, Any] | None = None,
    topology_template_payload: dict[str, Any] | None = None,
    coordinator_agent_id: str = "",
    topology_template_id: str = "",
    communication_protocol_id: str = "",
    handoff_policy: str = "",
    failure_policy: str = "",
    merge_policy: str = "",
    runtime_assembly: dict[str, Any] | None = None,
    diagnostics: dict[str, Any] | None = None,
) -> AgentRuntimeStartResult:
    now = time.time()
    assembly_payload = dict(runtime_assembly or {})
    assembly_ref = str(assembly_payload.get("assembly_id") or "")
    manifest_ref = str(assembly_payload.get("manifest_ref") or "")
    working_memory_refs = working_memory_refs_from_assembly(assembly_payload)
    working_memory_diag = working_memory_diagnostics_from_assembly(assembly_payload)
    dispatch_graph_payload = dict(graph_payload or {})
    dispatch_topology_payload = dict(topology_template_payload or {})
    resolved_graph_ref = str(
        graph_ref
        or dispatch_graph_payload.get("graph_id")
        or dispatch_graph_payload.get("task_graph_id")
        or assembly_payload.get("graph_ref")
        or ""
    ).strip()
    task_run_id = f"taskrun:{session_id}:{task_id}:{uuid.uuid4().hex[:8]}"
    agent_run_id = f"agrun:{task_run_id}:main"
    coordination_run = (
        CoordinationRun(
            coordination_run_id=f"coordrun:{task_run_id}:primary",
            task_run_id=task_run_id,
            graph_ref=resolved_graph_ref,
            coordinator_agent_id=coordinator_agent_id or agent_id,
            topology_template_id=topology_template_id,
            communication_protocol_id=communication_protocol_id,
            handoff_policy=handoff_policy,
            failure_policy=failure_policy,
            merge_policy=merge_policy,
            status="running",
            created_at=now,
            updated_at=now,
            diagnostics={
                "coordination_candidate": True,
                "task_agent_binding_ref": task_agent_binding_ref,
                **dict(diagnostics or {}),
            },
        )
        if resolved_graph_ref
        else None
    )
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
            "single_agent": coordination_run is None,
            "multi_agent_enabled": coordination_run is not None,
            "graph_ref": resolved_graph_ref,
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
        role="main_executor" if coordination_run is None else "coordinator",
        spawn_mode=execution_mode,
        context_scope="task_default",
        runtime_lane=runtime_lane,
        coordination_run_ref=coordination_run.coordination_run_id if coordination_run is not None else "",
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
    coordination_run_event = None
    if coordination_run is not None:
        coordination_run_event = runtime_host.event_log.append(
            task_run_id,
            "coordination_run_created",
            payload={"coordination_run": coordination_run.to_dict()},
            refs={"coordination_run_ref": coordination_run.coordination_run_id},
        )
    initial_dispatch_plan = (
        compile_agent_dispatch_plan_from_graph_payload(
            task_run_id=task_run_id,
            coordination_run_id=coordination_run.coordination_run_id,
            graph_payload=dispatch_graph_payload,
            topology_template_payload=dispatch_topology_payload,
        )
        if coordination_run is not None
        else None
    )
    dispatch_plan_event = None
    if initial_dispatch_plan is not None:
        dispatch_plan_event = runtime_host.event_log.append(
            task_run_id,
            "agent_dispatch_plan_compiled",
            payload={"agent_dispatch_plan": initial_dispatch_plan.to_dict(), "source": "runtime_start"},
            refs={
                "coordination_run_ref": coordination_run.coordination_run_id,
                "dispatch_plan_ref": initial_dispatch_plan.dispatch_plan_id,
            },
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
    state = RuntimeLoopState(
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
            "working_memory_refs": working_memory_refs,
            **({"agent_dispatch_plan": initial_dispatch_plan.to_dict()} if initial_dispatch_plan is not None else {}),
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
        coordination_runs=((coordination_run,) if coordination_run is not None else ()),
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
            "single_agent": coordination_run is None,
            "agent_id": agent_id,
            "agent_profile_id": agent_profile_id,
            "runtime_lane": runtime_lane,
            "task_agent_binding_ref": task_agent_binding_ref,
            "skill_workflow_ref": skill_workflow_ref,
            "health_issue_ref": health_issue_ref,
            "main_agent_run_ref": agent_run.agent_run_id,
            "execution_mode": execution_mode,
            "graph_ref": resolved_graph_ref,
            "multi_agent_enabled": coordination_run is not None,
            "loop_limits": runtime_host.limits.to_dict(),
            "runtime_assembly_ref": assembly_ref,
            "contract_manifest_ref": manifest_ref,
            "working_memory_refs": working_memory_refs,
            **({"agent_dispatch_plan": initial_dispatch_plan.to_dict()} if initial_dispatch_plan is not None else {}),
            **working_memory_diag,
            **dict(diagnostics or {}),
        },
    )
    runtime_host.state_index.upsert_task_run(task_run)
    runtime_host.state_index.upsert_agent_run(agent_run)
    if coordination_run is not None:
        runtime_host.state_index.upsert_coordination_run(coordination_run)
    ordered_events = [started.to_dict(), agent_run_event.to_dict()]
    if coordination_run_event is not None:
        ordered_events.append(coordination_run_event.to_dict())
    if dispatch_plan_event is not None:
        ordered_events.append(dispatch_plan_event.to_dict())
    ordered_events.extend((iteration.to_dict(), checkpoint_event.to_dict()))
    return AgentRuntimeStartResult(
        task_run=task_run,
        agent_run=agent_run,
        coordination_run=coordination_run,
        loop_state=state,
        checkpoint=checkpoint,
        events=tuple(ordered_events),
    )


def write_checkpoint_event(runtime_host: Any, state: RuntimeLoopState, *, event_offset: int):
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
    state: RuntimeLoopState,
    ledger: Any | None,
    *,
    transition: str | None = None,
    task_result_ref: str | None = None,
    result_refs: list[str] | tuple[str, ...] | None = None,
    status: str | None = None,
    terminal_reason: str | None = None,
    diagnostics: dict[str, Any] | None = None,
    commit_state: dict[str, Any] | None = None,
) -> RuntimeLoopState:
    from task_system.tasks.run_models import task_run_step_count

    merged_diagnostics = dict(state.diagnostics)
    if diagnostics:
        merged_diagnostics.update(diagnostics)
    return RuntimeLoopState(
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
        projection_ref=state.projection_ref,
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


def build_coordination_state(*args: Any, **kwargs: Any):
    return build_graph_flow_state(*args, **kwargs)


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
