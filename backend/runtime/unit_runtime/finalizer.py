from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from artifact_system import ArtifactRepositoryService

from .artifact_paths import _successful_write_file_paths, _workspace_root_from_runtime_root
from ..shared.artifact_refs import collect_task_result_output_refs, dedupe_refs as dedupe_artifact_refs
from ..shared.checkpoint import RuntimeCheckpoint, RuntimeCheckpointStore
from ..shared.event_log import RuntimeEventLog
from ..shared.execution_record import RuntimeExecutionStore
from ..coordination_runtime.runtime import LangGraphCoordinationRuntime
from ..shared.models import (
    AgentRun,
    AgentRunResult,
    CoordinationRun,
    RuntimeLoopState,
    TaskRun,
)
from ..execution.node_execution_request import NodeResultReadyEvent
from ..agent_assembly import sanitize_explicit_inputs
from ..memory.project_supervision import (
    build_runtime_status,
    classify_blocker,
    clear_recovered_failure,
    ensure_project_runtime_inputs,
    make_initial_project_ledger,
    make_supervision_record,
    record_delivery_state,
    record_failure,
    record_progress_unit_commit,
)
from task_system.runtime_semantics.quality_gates import (
    count_text_units_for_quality_gate,
    safe_int,
    stage_business_acceptance,
)
from ..shared.runtime_object_store import RuntimeObjectStore
from ..memory.state_index import RuntimeStateIndex
from .artifact_materializer import MaterializedTaskArtifacts, materialize_task_artifacts
from task_system.registry.flow_registry import TaskFlowRegistry
from task_system.tasks.run_models import project_task_result_from_ledger


@dataclass(frozen=True, slots=True)
class FinishedTaskRunResult:
    events: tuple[Any, ...]
    continuation_payload: dict[str, Any] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "continuation_payload", dict(self.continuation_payload or {}))


@dataclass(frozen=True, slots=True)
class CompletedCheckpointRecoveryResult:
    recovered: bool
    reason: str = ""
    task_run_id: str = ""
    final_content_chars: int = 0
    events: tuple[Any, ...] = ()
    continuation_payload: dict[str, Any] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "continuation_payload", dict(self.continuation_payload or {}))

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": "orchestration.completed_checkpoint_recovery",
            "recovered": self.recovered,
            "reason": self.reason,
            "task_run_id": self.task_run_id,
            "final_content_chars": self.final_content_chars,
            "event_count": len(self.events),
            "continuation_payload": dict(self.continuation_payload),
        }


class TaskRunFinalizer:
    def __init__(
        self,
        *,
        root_dir: Path,
        state_index: RuntimeStateIndex,
        event_log: RuntimeEventLog,
        checkpoints: RuntimeCheckpointStore,
        execution_store: RuntimeExecutionStore,
        runtime_objects: RuntimeObjectStore,
        task_flow_registry: TaskFlowRegistry,
        langgraph_coordination_runtime: LangGraphCoordinationRuntime,
        artifact_repository: ArtifactRepositoryService,
    ) -> None:
        self.root_dir = Path(root_dir)
        self.state_index = state_index
        self.event_log = event_log
        self.checkpoints = checkpoints
        self.execution_store = execution_store
        self.runtime_objects = runtime_objects
        self.task_flow_registry = task_flow_registry
        self.langgraph_coordination_runtime = langgraph_coordination_runtime
        self.artifact_repository = artifact_repository

    def upsert_finished_task_run(
        self,
        *,
        start_task_run: TaskRun,
        start_agent_run: AgentRun,
        start_coordination_run: CoordinationRun | None,
        task_contract_ref: str,
        terminal_state: RuntimeLoopState,
        checkpoint_event: Any,
        final_content: str,
        task_result: dict[str, Any] | None = None,
        task_spec_payload: dict[str, Any] | None = None,
        current_turn_context: dict[str, Any] | None = None,
        user_message: str = "",
        diagnostics: dict[str, Any] | None = None,
    ) -> FinishedTaskRunResult:
        events: list[Any] = []
        continuation_payload: dict[str, Any] = {}
        existing_task_run = self.state_index.get_task_run(start_task_run.task_run_id)
        base_task_run = existing_task_run or start_task_run
        finalization_suppression_reason = _task_run_finalization_suppression_reason(
            existing_task_run=existing_task_run,
            terminal_state=terminal_state,
            events=self.event_log.list_events(start_task_run.task_run_id),
        )
        if finalization_suppression_reason:
            suppression_event = self.event_log.append(
                start_task_run.task_run_id,
                "task_run_finalization_suppressed",
                payload={
                    "reason": finalization_suppression_reason,
                    "incoming_status": str(terminal_state.status or ""),
                    "incoming_terminal_reason": str(terminal_state.terminal_reason or ""),
                    "preserved_status": str(base_task_run.status or ""),
                    "preserved_terminal_reason": str(base_task_run.terminal_reason or ""),
                    "checkpoint_ref": str(checkpoint_event.refs.get("checkpoint_ref") or ""),
                },
                refs={
                    "task_run_ref": start_task_run.task_run_id,
                    "checkpoint_ref": str(checkpoint_event.refs.get("checkpoint_ref") or ""),
                },
            )
            events.append(suppression_event)
            self._preserve_suppressed_task_run_state(
                task_run=base_task_run,
                event_offset=suppression_event.offset,
                reason=finalization_suppression_reason,
                checkpoint_ref=str(base_task_run.latest_checkpoint_ref or ""),
                incoming_status=str(terminal_state.status or ""),
                incoming_terminal_reason=str(terminal_state.terminal_reason or ""),
            )
            self._close_running_agent_runs_after_suppressed_finalization(
                task_run_id=start_task_run.task_run_id,
                fallback_agent_run=start_agent_run,
                status=_suppressed_agent_run_status(finalization_suppression_reason),
                checkpoint_ref=str(base_task_run.latest_checkpoint_ref or ""),
                reason=finalization_suppression_reason,
            )
            return FinishedTaskRunResult(events=tuple(events), continuation_payload={})
        start_task_run_diagnostics = dict(base_task_run.diagnostics or {})
        stage_execution_request = _stage_execution_request_for_finalizer(
            task_run_diagnostics=start_task_run_diagnostics,
            current_turn_context=current_turn_context,
            coordination_run=start_coordination_run,
            langgraph_coordination_runtime=self.langgraph_coordination_runtime,
        )
        explicit_inputs = sanitize_explicit_inputs(
            dict(current_turn_context or {}).get("explicit_inputs")
            or stage_execution_request.get("explicit_inputs")
            or {}
        )
        task_ref_for_artifacts = str(
            dict(current_turn_context or {}).get("selected_task_id")
            or dict(current_turn_context or {}).get("task_id")
            or task_contract_ref
            or base_task_run.task_id
            or ""
        ).strip()
        task_policy_for_artifacts: dict[str, Any] = {}
        task_record_for_artifacts = (
            self.task_flow_registry.get_specific_task_record(task_ref_for_artifacts)
            if task_ref_for_artifacts
            else None
        )
        if task_record_for_artifacts is None:
            task_record_for_artifacts = _specific_task_record_for_runtime_ref(
                self.task_flow_registry,
                task_ref_for_artifacts or task_contract_ref or base_task_run.task_id,
            )
        if task_record_for_artifacts is not None:
            task_ref_for_artifacts = str(getattr(task_record_for_artifacts, "task_id", "") or task_ref_for_artifacts)
            task_policy_for_artifacts = dict(task_record_for_artifacts.task_policy or {})
        stage_artifact_policy = dict(stage_execution_request.get("artifact_policy") or {})
        if stage_artifact_policy:
            task_policy_for_artifacts = {
                **task_policy_for_artifacts,
                "artifact_policy": {
                    **dict(task_policy_for_artifacts.get("artifact_policy") or {}),
                    **stage_artifact_policy,
                },
            }
        stage_contract_for_acceptance: dict[str, Any] = {}
        stage_acceptance_preview: dict[str, Any] = {}
        requires_file_artifact_refs_preview = bool(
            dict(stage_execution_request.get("artifact_policy") or {}).get("enabled")
            or stage_execution_request.get("artifact_targets")
        )
        if str(stage_execution_request.get("stage_id") or "") == "project_brief":
            requires_file_artifact_refs_preview = False
        if stage_execution_request and start_coordination_run is not None:
            coordination_state_for_acceptance = self.langgraph_coordination_runtime.checkpoints.get_state(
                thread_id=start_coordination_run.coordination_run_id,
            ) or {}
            stage_contract_for_acceptance = dict(
                dict(coordination_state_for_acceptance.get("stage_contracts") or {}).get(
                    str(stage_execution_request.get("stage_id") or "")
                )
                or {}
            )
            if not requires_file_artifact_refs_preview:
                stage_acceptance_preview = stage_business_acceptance(
                    stage_id=str(stage_execution_request.get("stage_id") or ""),
                    contract=stage_contract_for_acceptance,
                    explicit_inputs=explicit_inputs,
                    final_content=final_content,
                    output_refs=[],
                    terminal_status=terminal_state.status,
                    requires_file_artifact_refs=requires_file_artifact_refs_preview,
                )
        acceptance_status = (
            "accepted"
            if bool(stage_acceptance_preview.get("accepted") is True)
            else "rejected"
            if stage_execution_request
            and stage_acceptance_preview
            and requires_file_artifact_refs_preview
            else ""
        )
        stage_id = str(stage_execution_request.get("stage_id") or "").strip()
        node_run_id = str(stage_execution_request.get("node_run_id") or stage_execution_request.get("request_id") or "").strip()
        producer_node_id = str(stage_execution_request.get("node_id") or stage_id or "").strip()
        output_contract_id = str(
            stage_execution_request.get("output_contract_id")
            or stage_contract_for_acceptance.get("output_contract_id")
            or ""
        ).strip()
        try:
            artifact_materialization = materialize_task_artifacts(
                workspace_root=_workspace_root_from_runtime_root(self.root_dir),
                task_run_id=start_task_run.task_run_id,
                session_id=start_task_run.session_id,
                task_ref=task_ref_for_artifacts,
                coordination_run_id=start_coordination_run.coordination_run_id if start_coordination_run is not None else "",
                final_content=final_content,
                user_message=user_message,
                explicit_inputs=explicit_inputs,
                task_policy=task_policy_for_artifacts,
                task_status=terminal_state.status,
                terminal_reason=terminal_state.terminal_reason,
                task_diagnostics=dict(terminal_state.diagnostics or {}),
                acceptance_status=acceptance_status,
                stage_id=stage_id,
                request_id=str(stage_execution_request.get("request_id") or ""),
            )
        except Exception as exc:
            artifact_materialization = MaterializedTaskArtifacts(
                enabled=True,
                diagnostics={
                    "status": "failed",
                    "reason": str(exc),
                    "source": "task_policy.artifact_policy",
                },
            )
        artifact_materialization_payload = artifact_materialization.to_dict()
        artifact_repository_record: dict[str, Any] = {}
        if artifact_materialization.enabled and artifact_materialization.artifact_refs:
            artifact_policy = dict(dict(task_policy_for_artifacts.get("artifact_policy") or {}))
            artifact_repository_record = self.artifact_repository.record_materialization(
                task_run_id=start_task_run.task_run_id,
                graph_id=str(dict(start_task_run.diagnostics or {}).get("graph_ref") or ""),
                stage_id=stage_id,
                node_run_id=node_run_id,
                task_ref=task_ref_for_artifacts,
                coordination_run_id=start_coordination_run.coordination_run_id if start_coordination_run is not None else "",
                output_contract_id=output_contract_id,
                producer_node_id=producer_node_id,
                materialization_id=str(stage_execution_request.get("request_id") or node_run_id or ""),
                artifact_refs=list(artifact_materialization.artifact_refs),
                artifact_root=artifact_materialization.artifact_root,
                created_files=list(artifact_materialization.created_files),
                status=acceptance_status or "accepted",
                repository_id=str(artifact_policy.get("repository_id") or "artifact.repository.default"),
                collection_id=str(artifact_policy.get("collection_id") or artifact_policy.get("collection") or "default"),
                lifecycle_policy=dict(artifact_policy.get("lifecycle_policy") or {}),
                metadata={
                    "source": "task_artifact_materializer",
                    "stage_execution_request_id": str(stage_execution_request.get("request_id") or ""),
                    "output_contract_id": output_contract_id,
                    "producer_node_id": producer_node_id,
                },
            )
            artifact_materialization_payload = {
                **artifact_materialization_payload,
                "artifact_repository": artifact_repository_record,
            }
        if artifact_materialization.enabled and artifact_materialization.artifact_refs:
            task_result_payload = dict(task_result or {})
            if output_contract_id:
                task_result_payload["output_contract_id"] = output_contract_id
            task_result_payload["output_refs"] = self._dedupe_refs(
                [
                    *list(task_result_payload.get("output_refs") or []),
                    *list(artifact_materialization.artifact_refs),
                ]
            )
            task_result_payload["diagnostics"] = {
                **dict(task_result_payload.get("diagnostics") or {}),
                **({"output_contract_id": output_contract_id} if output_contract_id else {}),
                "artifact_materialization": artifact_materialization_payload,
            }
            final_outputs = dict(task_result_payload.get("final_outputs") or {})
            final_outputs["artifact_materialization"] = artifact_materialization_payload
            task_result_payload["final_outputs"] = final_outputs
            task_result = task_result_payload
        elif artifact_materialization.enabled:
            task_result = {
                **dict(task_result or {}),
                **({"output_contract_id": output_contract_id} if output_contract_id else {}),
                "diagnostics": {
                    **dict(dict(task_result or {}).get("diagnostics") or {}),
                    **({"output_contract_id": output_contract_id} if output_contract_id else {}),
                    "artifact_materialization": artifact_materialization_payload,
                },
            }
        artifact_event = self.event_log.append(
            start_task_run.task_run_id,
            "task_artifacts_materialized" if artifact_materialization.enabled else "task_artifact_materialization_checked",
            payload={
                "artifact_materialization": artifact_materialization_payload,
                "artifact_repository": artifact_repository_record,
                "resolved_task_ref": task_ref_for_artifacts,
                "artifact_policy_enabled": bool(dict(task_policy_for_artifacts.get("artifact_policy") or {}).get("enabled")),
                "output_contract_id": output_contract_id,
                "producer_node_id": producer_node_id,
                "task_policy_keys": sorted(str(key) for key in task_policy_for_artifacts.keys()),
            },
            refs={
                "task_ref": task_ref_for_artifacts,
                "artifact_root": artifact_materialization.artifact_root,
            },
        )
        events.append(artifact_event)
        self.state_index.upsert_task_run(
            TaskRun(
                task_run_id=base_task_run.task_run_id,
                session_id=base_task_run.session_id,
                task_id=base_task_run.task_id,
                task_contract_ref=task_contract_ref,
                agent_id=base_task_run.agent_id,
                agent_profile_id=base_task_run.agent_profile_id,
                runtime_lane=base_task_run.runtime_lane,
                status=terminal_state.status,
                created_at=base_task_run.created_at,
                updated_at=time.time(),
                latest_event_offset=checkpoint_event.offset,
                latest_checkpoint_ref=str(checkpoint_event.refs.get("checkpoint_ref") or ""),
                terminal_reason=terminal_state.terminal_reason,
                diagnostics={
                    **dict(base_task_run.diagnostics),
                    **dict(diagnostics or {}),
                    **(
                        {"artifact_materialization": artifact_materialization_payload}
                        if artifact_materialization.enabled
                        else {}
                    ),
                },
            )
        )
        agent_run_result = AgentRunResult(
            agent_run_result_id=f"agresult:{start_agent_run.agent_run_id}",
            agent_run_id=start_agent_run.agent_run_id,
            task_run_id=start_agent_run.task_run_id,
            agent_id=start_agent_run.agent_id,
            status="completed" if terminal_state.status == "completed" else "failed",
            output_ref=str(checkpoint_event.refs.get("checkpoint_ref") or ""),
            summary=final_content[:280],
            artifact_refs=tuple(
                ref
                for ref in collect_task_result_output_refs(dict(task_result or {}))
                if str(ref).startswith("artifact:")
            ),
            created_at=time.time(),
            diagnostics={
                "terminal_reason": terminal_state.terminal_reason,
                "task_contract_ref": task_contract_ref,
            },
        )
        self.state_index.upsert_agent_run(
            AgentRun(
                agent_run_id=start_agent_run.agent_run_id,
                task_run_id=start_agent_run.task_run_id,
                agent_id=start_agent_run.agent_id,
                agent_profile_id=start_agent_run.agent_profile_id,
                role=start_agent_run.role,
                spawn_mode=start_agent_run.spawn_mode,
                context_scope=start_agent_run.context_scope,
                runtime_lane=start_agent_run.runtime_lane,
                parent_agent_run_ref=start_agent_run.parent_agent_run_ref,
                coordination_run_ref=start_agent_run.coordination_run_ref,
                status="completed" if terminal_state.status == "completed" else "failed",
                latest_checkpoint_ref=str(checkpoint_event.refs.get("checkpoint_ref") or ""),
                result_ref=agent_run_result.agent_run_result_id,
                created_at=start_agent_run.created_at,
                updated_at=time.time(),
                diagnostics={
                    **dict(start_agent_run.diagnostics),
                    "terminal_reason": terminal_state.terminal_reason,
                },
            )
        )
        self.state_index.upsert_agent_run_result(agent_run_result)
        current_agent_runs = self.state_index.list_task_agent_runs(start_task_run.task_run_id)
        for agent_run in current_agent_runs:
            if agent_run.agent_run_id == start_agent_run.agent_run_id:
                continue
            participant_status = "completed" if terminal_state.status == "completed" else "failed"
            participant_result = AgentRunResult(
                agent_run_result_id=f"agresult:{agent_run.agent_run_id}",
                agent_run_id=agent_run.agent_run_id,
                task_run_id=agent_run.task_run_id,
                agent_id=agent_run.agent_id,
                status=participant_status,
                output_ref=str(checkpoint_event.refs.get("checkpoint_ref") or ""),
                summary=final_content[:200],
                created_at=time.time(),
                diagnostics={
                    "terminal_reason": terminal_state.terminal_reason,
                    "derived_from_coordination_finalize": True,
                    "parent_agent_run_ref": agent_run.parent_agent_run_ref,
                },
            )
            self.state_index.upsert_agent_run_result(participant_result)
            self.state_index.upsert_agent_run(
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
                    status=participant_status,
                    latest_checkpoint_ref=str(checkpoint_event.refs.get("checkpoint_ref") or ""),
                    result_ref=participant_result.agent_run_result_id,
                    created_at=agent_run.created_at,
                    updated_at=time.time(),
                    diagnostics={
                        **dict(agent_run.diagnostics),
                        "terminal_reason": terminal_state.terminal_reason,
                    },
                )
            )
        continuation_coordination_run_id = str(
            dict(current_turn_context or {}).get("coordination_run_id")
            or dict(task_spec_payload or {}).get("inputs", {}).get("coordination_run_id")
            or ""
        ).strip()
        continuation_coordination_run = (
            self.state_index.get_coordination_run(continuation_coordination_run_id)
            if continuation_coordination_run_id
            else None
        )
        current_coordination_runs = self.state_index.list_task_coordination_runs(start_task_run.task_run_id)
        target_coordination_run = (
            continuation_coordination_run
            or (current_coordination_runs[0] if current_coordination_runs else start_coordination_run)
        )
        worker_spawn_results = self.state_index.list_task_worker_spawn_results(start_task_run.task_run_id)
        worker_agent_runs = [
            item
            for item in self.state_index.list_task_agent_runs(start_task_run.task_run_id)
            if str(item.spawn_mode or "") == "worker_spawn"
        ]
        worker_spawn_summary = {
            "spawn_request_count": len(self.state_index.list_task_worker_spawn_requests(start_task_run.task_run_id)),
            "spawn_result_count": len(worker_spawn_results),
            "spawned_agent_ids": [
                str(item.spawned_agent_id or "")
                for item in worker_spawn_results
                if str(item.status or "") == "spawned" and str(item.spawned_agent_id or "")
            ],
            "blocked_spawn_count": sum(1 for item in worker_spawn_results if str(item.status or "") == "blocked"),
            "worker_agent_run_ids": [str(item.agent_run_id or "") for item in worker_agent_runs if str(item.agent_run_id or "")],
        }
        if target_coordination_run is not None:
            graph_record = self._resolve_task_graph_view(target_coordination_run.graph_ref)
            if self.langgraph_coordination_runtime.supports(target_coordination_run):
                raw_flow_state = dict(target_coordination_run.diagnostics.get("coordination_flow") or {})
                current_stage_request = _stage_execution_request_for_finalizer(
                    task_run_diagnostics=dict(start_task_run.diagnostics or {}),
                    current_turn_context=current_turn_context,
                    coordination_run=target_coordination_run,
                    langgraph_coordination_runtime=self.langgraph_coordination_runtime,
                )
                request_stage_id = str(current_stage_request.get("stage_id") or "").strip()
                flow_stage_id = str(raw_flow_state.get("current_stage_id") or "").strip()
                resolved_stage_id = self._stage_id_for_task_ref(
                    coordination_task=graph_record,
                    task_ref=task_contract_ref or start_task_run.task_id,
                )
                current_stage_id = request_stage_id or resolved_stage_id or flow_stage_id
                if (
                    request_stage_id
                    and flow_stage_id
                    and request_stage_id != flow_stage_id
                ):
                    terminal_state.diagnostics["coordination_flow_stage_repaired"] = {
                        "request_stage_id": request_stage_id,
                        "stale_flow_stage_id": flow_stage_id,
                        "resolved_stage_id": resolved_stage_id,
                        "authority": "orchestration.task_run_loop",
                    }
                all_output_refs = collect_task_result_output_refs(dict(task_result or {}))
                requires_file_artifact_refs = bool(
                    dict(current_stage_request.get("artifact_policy") or {}).get("enabled")
                    or current_stage_request.get("artifact_targets")
                )
                output_refs = [
                    ref
                    for ref in all_output_refs
                    if str(ref or "").startswith("artifact:")
                ] if requires_file_artifact_refs else all_output_refs
                materialization_payload = dict(dict(task_result or {}).get("diagnostics", {}).get("artifact_materialization") or {})
                materialized_refs = [
                    str(item)
                    for item in list(dict(materialization_payload or {}).get("artifact_refs") or [])
                    if str(item)
                ]
                if materialized_refs:
                    output_refs = self._dedupe_refs([*output_refs, *materialized_refs])
                task_result_ref = str(dict(task_result or {}).get("result_id") or agent_run_result.agent_run_result_id)
                coordination_state_before_resume = self.langgraph_coordination_runtime.checkpoints.get_state(
                    thread_id=target_coordination_run.coordination_run_id,
                ) or {}
                stage_contract = dict(
                    dict(coordination_state_before_resume.get("stage_contracts") or {}).get(current_stage_id) or {}
                )
                stage_acceptance = stage_business_acceptance(
                    stage_id=current_stage_id,
                    contract=stage_contract,
                    explicit_inputs=dict(current_stage_request.get("explicit_inputs") or {}),
                    final_content=final_content,
                    output_refs=output_refs,
                    terminal_status=terminal_state.status,
                    requires_file_artifact_refs=requires_file_artifact_refs,
                )
                accepted_content_metric_total = int(
                    stage_acceptance.get("content_metric_total")
                    or count_text_units_for_quality_gate(final_content)
                )
                ready_event = NodeResultReadyEvent(
                    event_type="task_result_ready",
                    coordination_run_id=target_coordination_run.coordination_run_id,
                    task_run_id=start_task_run.task_run_id,
                    stage_id=current_stage_id,
                    task_ref=task_contract_ref or start_task_run.task_id,
                    task_result_ref=task_result_ref,
                    artifact_refs=tuple(output_refs),
                    accepted=bool(stage_acceptance.get("accepted") is True),
                    agent_run_result_ref=agent_run_result.agent_run_result_id,
                    request_id=str(current_stage_request.get("request_id") or ""),
                    dispatch_event_id=str(dict(current_stage_request.get("dispatch_context") or {}).get("dispatch_event_id") or ""),
                    diagnostics={
                        "terminal_reason": terminal_state.terminal_reason,
                        "last_error": dict(terminal_state.diagnostics.get("last_error") or {}),
                        "content_metric_total": accepted_content_metric_total,
                        "raw_content_metric_total": count_text_units_for_quality_gate(final_content),
                        "stage_business_acceptance": stage_acceptance,
                    },
                )
                artifact_root = self._artifact_root_from_context_or_events(
                    current_task_run_id=start_task_run.task_run_id,
                    current_turn_context=dict(current_turn_context or {}),
                )
                runtime_result = self.langgraph_coordination_runtime.resume_from_task_result(
                    coordination_run=target_coordination_run,
                    event=ready_event,
                    current_task_result=dict(task_result or {}),
                    inherited_inputs=dict(dict(current_turn_context or {}).get("explicit_inputs") or {}),
                    artifact_root=artifact_root,
                )
                events.extend(runtime_result.events)
                if runtime_result.stage_execution_request is not None:
                    continuation_payload = runtime_result.continuation_payload(
                        session_id=start_task_run.session_id,
                        current_turn_context=dict(current_turn_context or {}),
                    )
                worker_spawn_summary = {
                    **worker_spawn_summary,
                    "coordination_runtime": "langgraph_runtime",
                    "stage_execution_request": bool(runtime_result.stage_execution_request is not None),
                }
                self.state_index.upsert_task_run(
                    TaskRun(
                        task_run_id=start_task_run.task_run_id,
                        session_id=start_task_run.session_id,
                        task_id=start_task_run.task_id,
                        task_contract_ref=task_contract_ref,
                        agent_id=start_task_run.agent_id,
                        agent_profile_id=start_task_run.agent_profile_id,
                        runtime_lane=start_task_run.runtime_lane,
                        status=terminal_state.status,
                        created_at=start_task_run.created_at,
                        updated_at=time.time(),
                        latest_event_offset=checkpoint_event.offset,
                        latest_checkpoint_ref=str(checkpoint_event.refs.get("checkpoint_ref") or ""),
                        terminal_reason=terminal_state.terminal_reason,
                        diagnostics={
                            **dict(self.state_index.get_task_run(start_task_run.task_run_id).diagnostics if self.state_index.get_task_run(start_task_run.task_run_id) else {}),
                            **dict(diagnostics or {}),
                            "worker_spawn_summary": worker_spawn_summary,
                        },
                    )
                )
                refreshed_task_run = self.state_index.get_task_run(start_task_run.task_run_id) or start_task_run
                refreshed_coordination_run = (
                    self.state_index.get_coordination_run(target_coordination_run.coordination_run_id)
                    or target_coordination_run
                )
                self._update_project_supervision_state(
                    task_run=refreshed_task_run,
                    coordination_run=refreshed_coordination_run,
                    current_turn_context=dict(current_turn_context or {}),
                    stage_id=current_stage_id,
                    task_result=dict(task_result or {}),
                    accepted=bool(ready_event.accepted),
                    terminal_status=str(terminal_state.status or ""),
                    terminal_reason=str(terminal_state.terminal_reason or ""),
                    metric_value=int(dict(ready_event.diagnostics or {}).get("content_metric_total") or 0),
                    coordination_state_before_resume=dict(runtime_result.state or coordination_state_before_resume or {}),
                    artifact_root=artifact_root,
                )
                return FinishedTaskRunResult(events=tuple(events), continuation_payload=continuation_payload)
            raise RuntimeError(
                f"Legacy coordination continuation path was removed for unsupported coordination run: {target_coordination_run.coordination_run_id}"
            )
        self.state_index.upsert_task_run(
            TaskRun(
                task_run_id=start_task_run.task_run_id,
                session_id=start_task_run.session_id,
                task_id=start_task_run.task_id,
                task_contract_ref=task_contract_ref,
                agent_id=start_task_run.agent_id,
                agent_profile_id=start_task_run.agent_profile_id,
                runtime_lane=start_task_run.runtime_lane,
                status=terminal_state.status,
                created_at=start_task_run.created_at,
                updated_at=time.time(),
                latest_event_offset=checkpoint_event.offset,
                latest_checkpoint_ref=str(checkpoint_event.refs.get("checkpoint_ref") or ""),
                terminal_reason=terminal_state.terminal_reason,
                diagnostics={
                    **dict(self.state_index.get_task_run(start_task_run.task_run_id).diagnostics if self.state_index.get_task_run(start_task_run.task_run_id) else {}),
                    **dict(diagnostics or {}),
                    "worker_spawn_summary": worker_spawn_summary,
                },
            )
        )
        return FinishedTaskRunResult(
            events=tuple(events),
            continuation_payload=continuation_payload,
        )

    def _preserve_suppressed_task_run_state(
        self,
        *,
        task_run: TaskRun,
        event_offset: int,
        reason: str,
        checkpoint_ref: str,
        incoming_status: str,
        incoming_terminal_reason: str,
    ) -> None:
        self.state_index.upsert_task_run(
            TaskRun(
                task_run_id=task_run.task_run_id,
                session_id=task_run.session_id,
                task_id=task_run.task_id,
                task_contract_ref=task_run.task_contract_ref,
                owner_agent_seat_id=task_run.owner_agent_seat_id,
                agent_id=task_run.agent_id,
                agent_profile_id=task_run.agent_profile_id,
                runtime_lane=task_run.runtime_lane,
                status=task_run.status,
                created_at=task_run.created_at,
                updated_at=time.time(),
                latest_event_offset=event_offset,
                latest_checkpoint_ref=checkpoint_ref,
                terminal_reason=task_run.terminal_reason,
                diagnostics={
                    **dict(task_run.diagnostics or {}),
                    "suppressed_finalization": {
                        "reason": reason,
                        "incoming_status": incoming_status,
                        "incoming_terminal_reason": incoming_terminal_reason,
                        "suppressed_at": time.time(),
                    },
                },
            )
        )

    def _close_running_agent_runs_after_suppressed_finalization(
        self,
        *,
        task_run_id: str,
        fallback_agent_run: AgentRun,
        status: str,
        checkpoint_ref: str,
        reason: str,
    ) -> None:
        agent_runs = self.state_index.list_task_agent_runs(task_run_id)
        if not agent_runs:
            agent_runs = [fallback_agent_run]
        for agent_run in agent_runs:
            if str(agent_run.status or "") not in {"pending", "running"}:
                continue
            self.state_index.upsert_agent_run(
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
                    status=status,
                    latest_checkpoint_ref=checkpoint_ref or agent_run.latest_checkpoint_ref,
                    result_ref=agent_run.result_ref,
                    created_at=agent_run.created_at,
                    updated_at=time.time(),
                    diagnostics={
                        **dict(agent_run.diagnostics or {}),
                        "suppressed_finalization": {"reason": reason},
                    },
                )
            )

    def recover_completed_checkpoint_task_run(
        self,
        *,
        task_run: TaskRun,
        checkpoint: RuntimeCheckpoint,
        current_turn_context: dict[str, Any] | None = None,
        user_message: str = "",
    ) -> CompletedCheckpointRecoveryResult:
        if task_run.status in {"completed", "failed", "aborted"} and self.state_index.list_task_agent_run_results(task_run.task_run_id):
            return CompletedCheckpointRecoveryResult(
                recovered=False,
                reason="already_finalized",
                task_run_id=task_run.task_run_id,
            )
        terminal_state = checkpoint.loop_state
        if terminal_state.status not in {"completed", "failed", "aborted"}:
            return CompletedCheckpointRecoveryResult(
                recovered=False,
                reason="checkpoint_not_terminal",
                task_run_id=task_run.task_run_id,
            )
        if str(terminal_state.terminal_reason or "") != "completed":
            return CompletedCheckpointRecoveryResult(
                recovered=False,
                reason="checkpoint_terminal_reason_not_recoverable",
                task_run_id=task_run.task_run_id,
            )
        existing_materialization = dict(dict(task_run.diagnostics or {}).get("artifact_materialization") or {})
        if existing_materialization.get("artifact_refs") and self.state_index.list_task_agent_run_results(task_run.task_run_id):
            return CompletedCheckpointRecoveryResult(
                recovered=False,
                reason="already_materialized",
                task_run_id=task_run.task_run_id,
            )
        final_content = self._recover_final_content_from_events(task_run.task_run_id)
        if not final_content.strip():
            return CompletedCheckpointRecoveryResult(
                recovered=False,
                reason="missing_final_content",
                task_run_id=task_run.task_run_id,
            )
        start_agent_run = self._recover_start_agent_run(task_run)
        start_coordination_run = self._recover_coordination_run_for_checkpoint(
            terminal_state,
            current_turn_context=dict(current_turn_context or {}),
        )
        checkpoint_event = self._write_checkpoint_event(
            terminal_state,
            event_offset=max(checkpoint.event_offset, self.event_log.next_offset(task_run.task_run_id) - 1),
        )
        recovered_context = {
            **self._recover_current_turn_context_for_checkpoint(
                terminal_state,
                current_turn_context=dict(current_turn_context or {}),
            ),
            "completed_checkpoint_recovery": True,
        }
        task_result = self._recover_task_result_from_checkpoint(
            checkpoint=checkpoint,
            task_run=task_run,
            final_content=final_content,
        )
        finished = self.upsert_finished_task_run(
            start_task_run=task_run,
            start_agent_run=start_agent_run,
            start_coordination_run=start_coordination_run,
            task_contract_ref=task_run.task_contract_ref or task_run.task_id,
            terminal_state=terminal_state,
            checkpoint_event=checkpoint_event,
            final_content=final_content,
            task_result=task_result,
            task_spec_payload={},
            current_turn_context=recovered_context,
            user_message=user_message,
            diagnostics={
                "final_content_chars": len(final_content),
                "completed_checkpoint_recovery": True,
            },
        )
        return CompletedCheckpointRecoveryResult(
            recovered=True,
            reason="recovered_completed_checkpoint",
            task_run_id=task_run.task_run_id,
            final_content_chars=len(final_content),
            events=finished.events,
            continuation_payload=finished.continuation_payload,
        )

    def _resolve_task_graph_view(self, graph_ref: str):
        target = str(graph_ref or "").strip()
        if not target:
            return None
        task_graph = self.task_flow_registry.get_task_graph(target)
        if task_graph is None:
            return None
        return self.task_flow_registry.derive_coordination_task_view_from_graph(task_graph)

    @staticmethod
    def _stage_id_for_task_ref(*, coordination_task: Any | None, task_ref: str) -> str:
        target = str(task_ref or "").strip()
        metadata = dict(getattr(coordination_task, "metadata", {}) or {}) if coordination_task is not None else {}
        for stage in list(metadata.get("stage_sequence") or []):
            if not isinstance(stage, dict):
                continue
            if str(stage.get("task_ref") or "").strip() == target:
                return str(stage.get("stage_id") or "").strip()
        contracts = list(metadata.get("stage_contracts") or [])
        for contract in contracts:
            if not isinstance(contract, dict):
                continue
            if str(contract.get("task_ref") or "").strip() == target:
                return str(contract.get("stage_id") or "").strip()
        return ""

    def _artifact_root_from_context_or_events(
        self,
        *,
        current_task_run_id: str,
        current_turn_context: dict[str, Any],
    ) -> str:
        artifact_root = str(
            current_turn_context.get("artifact_root")
            or current_turn_context.get("workspace_root")
            or dict(current_turn_context.get("explicit_inputs") or {}).get("artifact_root")
            or dict(current_turn_context.get("explicit_inputs") or {}).get("workspace_root")
            or ""
        ).strip()
        if not artifact_root:
            write_paths = _successful_write_file_paths(
                root_dir=self.root_dir,
                event_log_events=[item.to_dict() for item in self.event_log.list_events(current_task_run_id)],
            )
            if write_paths:
                artifact_root = str(Path(write_paths[0]["absolute_path"]).parent.as_posix())
        if artifact_root:
            workspace_root = _workspace_root_from_runtime_root(self.root_dir)
            artifact_root = artifact_root.replace("\\", "/").rstrip("/")
            workspace_posix = workspace_root.as_posix().rstrip("/")
            if artifact_root.startswith(workspace_posix + "/"):
                artifact_root = artifact_root[len(workspace_posix) + 1 :]
        return artifact_root

    def _project_id_for_task_run(
        self,
        *,
        task_run: TaskRun | None,
        current_turn_context: dict[str, Any] | None = None,
    ) -> str:
        turn_inputs = dict(dict(current_turn_context or {}).get("explicit_inputs") or {})
        if turn_inputs.get("project_id"):
            return str(turn_inputs.get("project_id") or "").strip()
        if task_run is not None:
            diagnostics = dict(task_run.diagnostics or {})
            if diagnostics.get("project_id"):
                return str(diagnostics.get("project_id") or "").strip()
            initial_inputs_ref = str(diagnostics.get("task_graph_initial_inputs_ref") or "").strip()
            if initial_inputs_ref:
                payload = dict(self.runtime_objects.get_object(initial_inputs_ref) or {})
                initial_inputs = dict(payload.get("initial_inputs") or {})
                if initial_inputs.get("project_id"):
                    return str(initial_inputs.get("project_id") or "").strip()
        return ""

    @staticmethod
    def _coordination_active_node_id(coordination_state: dict[str, Any] | None) -> str:
        state = dict(coordination_state or {})
        return str(state.get("active_stage_id") or state.get("active_node_id") or "").strip()

    def _update_project_supervision_state(
        self,
        *,
        task_run: TaskRun | None,
        coordination_run: CoordinationRun | None,
        current_turn_context: dict[str, Any] | None = None,
        stage_id: str = "",
        task_result: dict[str, Any] | None = None,
        accepted: bool = False,
        terminal_status: str = "",
        terminal_reason: str = "",
        metric_value: int = 0,
        coordination_state_before_resume: dict[str, Any] | None = None,
        artifact_root: str = "",
    ) -> None:
        if task_run is None:
            return
        project_id = self._project_id_for_task_run(task_run=task_run, current_turn_context=current_turn_context)
        if not project_id:
            return
        current_turn_context = dict(current_turn_context or {})
        explicit_inputs = dict(current_turn_context.get("explicit_inputs") or {})
        diagnostics = dict(task_run.diagnostics or {})
        ledger = self.state_index.get_project_progress_ledger(project_id)
        if ledger is None:
            initial_inputs_ref = str(diagnostics.get("task_graph_initial_inputs_ref") or "").strip()
            restored_inputs = {}
            if initial_inputs_ref:
                restored_inputs = dict(dict(self.runtime_objects.get_object(initial_inputs_ref) or {}).get("initial_inputs") or {})
            normalized_inputs = ensure_project_runtime_inputs(
                initial_inputs={**restored_inputs, **explicit_inputs},
                graph_id=str(diagnostics.get("task_graph_id") or diagnostics.get("graph_ref") or ""),
                session_id=task_run.session_id,
            )
            ledger = make_initial_project_ledger(
                project_id=project_id,
                session_id=task_run.session_id,
                graph_id=str(diagnostics.get("task_graph_id") or diagnostics.get("graph_ref") or ""),
                task_family=str(diagnostics.get("task_family") or ""),
                project_title=str(normalized_inputs.get("project_title") or project_id),
                metric_label=str(normalized_inputs.get("metric_label") or diagnostics.get("metric_label") or "units"),
                target_metric_total=int(
                    normalized_inputs.get("target_metric_total")
                    or normalized_inputs.get("target_words")
                    or diagnostics.get("target_metric_total")
                    or diagnostics.get("target_words")
                    or 0
                ),
                task_run_id=task_run.task_run_id,
            )
        coordination_state = dict(coordination_state_before_resume or {})
        pending_inputs = dict(coordination_state.get("pending_inputs") or {})
        stage_contract = dict(dict(coordination_state.get("stage_contracts") or {}).get(stage_id) or {})
        progress_policy = dict(stage_contract.get("progress_commit_policy") or {})
        if progress_policy.get("enabled") is True and accepted:
            unit_index_key = str(progress_policy.get("unit_index_key") or "unit_index")
            unit_start_key = str(progress_policy.get("unit_start_key") or unit_index_key)
            unit_end_key = str(progress_policy.get("unit_end_key") or unit_start_key)
            unit_count_key = str(progress_policy.get("unit_count_key") or "")
            metric_value_key = str(progress_policy.get("metric_value_key") or "content_metric_total")
            metric_target_key = str(progress_policy.get("metric_target_key") or "target_metric_total")
            unit_index = int(
                explicit_inputs.get(unit_index_key)
                or pending_inputs.get(unit_index_key)
                or 0
            )
            units_per_commit = max(
                safe_int(
                    explicit_inputs.get(unit_count_key)
                    or pending_inputs.get(unit_count_key)
                    or 1
                ),
                1,
            )
            batch_start_index = safe_int(
                explicit_inputs.get(unit_start_key)
                or pending_inputs.get(unit_start_key)
                or unit_index
                or 0
            )
            batch_end_index = safe_int(
                explicit_inputs.get(unit_end_key)
                or pending_inputs.get(unit_end_key)
                or (batch_start_index + units_per_commit - 1 if batch_start_index else 0)
            )
            resolved_metric = int(
                metric_value
                or pending_inputs.get(metric_value_key)
                or dict(dict(coordination_state.get("diagnostics") or {}).get("runtime_loop") or {}).get(metric_value_key)
                or explicit_inputs.get(metric_target_key)
                or pending_inputs.get(metric_target_key)
                or 0
            )
            result_payload = dict(task_result or {})
            artifact_refs = collect_task_result_output_refs(result_payload)
            unit_ref = next((ref for ref in artifact_refs if str(ref).startswith("artifact:")), "")
            receipt_ref = str(result_payload.get("result_id") or f"{task_run.task_run_id}:{stage_id}:{unit_index}")
            total_units = max(batch_end_index - batch_start_index + 1, 1)
            per_unit_metric = max(int(resolved_metric / total_units), 0) if total_units > 1 else resolved_metric
            remainder_metric = max(resolved_metric - (per_unit_metric * total_units), 0)
            for offset, current_unit_index in enumerate(range(batch_start_index, batch_end_index + 1)):
                if current_unit_index <= 0:
                    continue
                current_metric = per_unit_metric + (remainder_metric if offset == total_units - 1 else 0)
                current_ref = f"{unit_ref}#unit_{current_unit_index:03d}" if unit_ref and total_units > 1 else unit_ref
                current_receipt_ref = f"{receipt_ref}:unit_{current_unit_index:03d}" if total_units > 1 else receipt_ref
                ledger = record_progress_unit_commit(
                    ledger,
                    task_run_id=task_run.task_run_id,
                    unit_index=current_unit_index,
                    unit_ref=current_ref,
                    metric_value=current_metric,
                    receipt_ref=current_receipt_ref,
                )
            self.state_index.upsert_supervision_record(
                make_supervision_record(
                    project_id=project_id,
                    session_id=task_run.session_id,
                    task_run_id=task_run.task_run_id,
                    coordination_run_id=coordination_run.coordination_run_id if coordination_run is not None else "",
                    issue_type="progress_unit_committed",
                    issue_summary=(
                        f"Progress unit batch {batch_start_index}-{batch_end_index} committed."
                        if units_per_commit > 1
                        else f"Progress unit {unit_index} committed."
                    ),
                    repair_result="progress_updated",
                    followup_status="watching",
                    diagnostics={
                        "unit_index": unit_index,
                        "batch_start_index": batch_start_index,
                        "batch_end_index": batch_end_index,
                        "units_per_commit": units_per_commit,
                        "metric_value": resolved_metric,
                        "unit_ref": unit_ref,
                    },
                )
            )
        if stage_id == "memory_finalize" and accepted:
            ledger = record_delivery_state(
                ledger,
                task_run_id=task_run.task_run_id,
                delivery_state="completed",
            )
        elif stage_id == "final_review" and accepted:
            ledger = record_delivery_state(
                ledger,
                task_run_id=task_run.task_run_id,
                delivery_state="delivery_ready",
            )
        if terminal_status in {"failed", "aborted"}:
            failure = {
                "terminal_status": terminal_status,
                "terminal_reason": terminal_reason,
                "stage_id": stage_id,
                "task_run_id": task_run.task_run_id,
            }
            ledger = record_failure(
                ledger,
                task_run_id=task_run.task_run_id,
                failure=failure,
            )
            self.state_index.upsert_supervision_record(
                make_supervision_record(
                    project_id=project_id,
                    session_id=task_run.session_id,
                    task_run_id=task_run.task_run_id,
                    coordination_run_id=coordination_run.coordination_run_id if coordination_run is not None else "",
                    issue_type="run_failed",
                    issue_summary=str(terminal_reason or terminal_status or "Task run failed"),
                    followup_status="needs_repair",
                    diagnostics=failure,
                )
            )
        elif accepted:
            ledger = clear_recovered_failure(
                ledger,
                task_run_id=task_run.task_run_id,
                stage_id=stage_id,
            )
        self.state_index.upsert_project_progress_ledger(ledger)
        latest_event_at = float(task_run.updated_at or time.time())
        coordination_active_status = str((coordination_run.status if coordination_run is not None else task_run.status) or "")
        coordination_terminal_reason = ""
        if coordination_run is not None:
            flow = dict(dict(coordination_run.diagnostics or {}).get("coordination_flow") or {})
            runtime_state = dict(dict(coordination_run.diagnostics or {}).get("langgraph_runtime_state") or {})
            coordination_terminal = str(flow.get("terminal_status") or runtime_state.get("terminal_status") or "").strip()
            if coordination_terminal == "completed":
                coordination_active_status = "completed"
                coordination_terminal_reason = "completed"
            elif coordination_terminal in {"failed", "blocked"}:
                coordination_active_status = "failed"
                coordination_terminal_reason = coordination_terminal
            elif coordination_terminal == "waiting_for_human":
                coordination_active_status = "waiting"
                coordination_terminal_reason = "waiting_for_human"
            elif coordination_active_status in {"failed", "aborted"} and not coordination_terminal:
                coordination_active_status = "running"
        blocker = classify_blocker(
            run_status=coordination_active_status,
            terminal_reason=str(coordination_terminal_reason or terminal_reason or task_run.terminal_reason or ""),
            active_node_id=self._coordination_active_node_id(coordination_state),
            stage_execution_request=dict(coordination_state.get("stage_execution_request") or {}),
            last_event_at=latest_event_at,
            failure=ledger.last_failure,
        )
        recovery_state = dict(ledger.last_repair_action or {})
        project_active_task_run_id = (
            str(coordination_run.task_run_id or "")
            if coordination_run is not None and str(coordination_run.task_run_id or "").strip()
            else task_run.task_run_id
        )
        project_status = build_runtime_status(
            ledger=ledger,
            task_run_id=project_active_task_run_id,
            coordination_run_id=coordination_run.coordination_run_id if coordination_run is not None else "",
            active_run_status=coordination_active_status,
            latest_artifact_root=str(artifact_root or dict(diagnostics.get("artifact_materialization") or {}).get("artifact_root") or ""),
            latest_event_offset=int(task_run.latest_event_offset or 0),
            latest_event_at=latest_event_at,
            last_effective_output_at=float(task_run.updated_at or time.time()),
            blocker=blocker,
            recovery_state=recovery_state,
        )
        self.state_index.upsert_project_runtime_status(project_status)

    def _recover_start_agent_run(self, task_run: TaskRun) -> AgentRun:
        existing = self.state_index.list_task_agent_runs(task_run.task_run_id)
        if existing:
            return existing[0]
        return AgentRun(
            agent_run_id=f"agrun:{task_run.task_run_id}:main",
            task_run_id=task_run.task_run_id,
            agent_id=task_run.agent_id,
            agent_profile_id=task_run.agent_profile_id,
            runtime_lane=task_run.runtime_lane,
            status="running",
            created_at=task_run.created_at,
            updated_at=time.time(),
            diagnostics={"created_by_completed_checkpoint_recovery": True},
        )

    def _recover_coordination_run_for_checkpoint(
        self,
        terminal_state: RuntimeLoopState,
        *,
        current_turn_context: dict[str, Any],
    ) -> CoordinationRun | None:
        coordination_run_id = str(
            current_turn_context.get("coordination_run_id")
            or dict(terminal_state.diagnostics or {}).get("coordination_run_id")
            or ""
        ).strip()
        if not coordination_run_id:
            return None
        return self.state_index.get_coordination_run(coordination_run_id)

    def _recover_current_turn_context_for_checkpoint(
        self,
        terminal_state: RuntimeLoopState,
        *,
        current_turn_context: dict[str, Any],
    ) -> dict[str, Any]:
        recovered = dict(current_turn_context or {})
        diagnostics = dict(terminal_state.diagnostics or {})
        coordination_run_id = str(recovered.get("coordination_run_id") or diagnostics.get("coordination_run_id") or "")
        if coordination_run_id:
            recovered["coordination_run_id"] = coordination_run_id
        stage_request = dict(recovered.get("stage_execution_request") or {})
        if not stage_request and coordination_run_id:
            coordination_state = self.langgraph_coordination_runtime.checkpoints.get_state(
                thread_id=coordination_run_id,
            ) or {}
            active_stage_id = str(
                diagnostics.get("stage_id")
                or diagnostics.get("coordination_stage_id")
                or coordination_state.get("active_stage_id")
                or ""
            ).strip()
            candidate_request = dict(coordination_state.get("stage_execution_request") or {})
            if active_stage_id and str(candidate_request.get("stage_id") or "").strip() == active_stage_id:
                stage_request = candidate_request
        if stage_request:
            recovered["stage_execution_request"] = stage_request
            recovered.setdefault("selected_task_id", str(stage_request.get("task_ref") or ""))
            recovered.setdefault("task_id", str(stage_request.get("task_ref") or ""))
            recovered.setdefault("explicit_inputs", dict(stage_request.get("explicit_inputs") or {}))
            recovered.setdefault("agent_id", str(stage_request.get("agent_id") or ""))
            runtime_assembly = dict(stage_request.get("runtime_assembly") or {})
            projection_id = str(runtime_assembly.get("projection_id") or stage_request.get("projection_id") or "")
            if projection_id:
                recovered.setdefault("projection_id", projection_id)
                recovered.setdefault("selected_projection_id", projection_id)
        elif "explicit_inputs" not in recovered:
            recovered["explicit_inputs"] = {}
        return recovered

    def _recover_final_content_from_events(self, task_run_id: str) -> str:
        events = self.event_log.list_events(task_run_id)
        for event in reversed(events):
            if event.event_type != "output_boundary_applied":
                continue
            output = dict(event.payload.get("output") or {})
            for key in ("canonical_answer", "visible_text", "content"):
                value = str(output.get(key) or "").strip()
                if value:
                    return value
        for event in reversed(events):
            if event.event_type != "commit_gate_checked":
                continue
            commit_decision = dict(event.payload.get("commit_decision") or {})
            candidate = dict(commit_decision.get("commit_candidate") or {})
            payload = dict(candidate.get("payload") or {})
            content = str(payload.get("content") or "").strip()
            if content:
                return content
        return ""

    def _recover_task_result_from_checkpoint(
        self,
        *,
        checkpoint: RuntimeCheckpoint,
        task_run: TaskRun,
        final_content: str,
    ) -> dict[str, Any]:
        checkpoint_result = dict(dict(checkpoint.commit_state or {}).get("task_result") or {})
        if checkpoint_result:
            return checkpoint_result
        ledger = self._recover_task_run_ledger_from_events(task_run.task_run_id)
        if ledger is None:
            return {
                "result_id": f"taskresult:{task_run.task_run_id}",
                "task_run_id": task_run.task_run_id,
                "task_id": task_run.task_id,
                "task_spec_ref": checkpoint.loop_state.task_spec_ref or task_run.task_contract_ref or task_run.task_id,
                "template_id": checkpoint.loop_state.task_template_id,
                "status": checkpoint.loop_state.status,
                "terminal_reason": checkpoint.loop_state.terminal_reason,
                "result_refs": list(checkpoint.loop_state.result_refs or ()),
                "output_refs": [],
                "final_outputs": {"final_answer": final_content},
                "diagnostics": {
                    "final_content_chars": len(final_content),
                    "recovered_from_completed_checkpoint": True,
                },
            }
        return project_task_result_from_ledger(
            ledger,
            result_id=f"taskresult:{task_run.task_run_id}",
            status=checkpoint.loop_state.status,
            terminal_reason=checkpoint.loop_state.terminal_reason,
            result_refs=tuple(str(ref) for ref in checkpoint.loop_state.result_refs if str(ref)),
            output_refs=(),
            final_outputs={"final_answer": final_content},
            diagnostics={
                "final_content_chars": len(final_content),
                "recovered_from_completed_checkpoint": True,
            },
        ).to_dict()

    def _recover_task_run_ledger_from_events(self, task_run_id: str):
        from task_system.tasks.run_models import TaskRunLedger

        for event in reversed(self.event_log.list_events(task_run_id)):
            if event.event_type != "task_run_ledger_updated":
                continue
            ledger_payload = dict(event.payload.get("task_run_ledger") or {})
            if not ledger_payload:
                continue
            return _task_run_ledger_from_payload(ledger_payload)
        return None

    def _write_checkpoint_event(self, state: RuntimeLoopState, *, event_offset: int):
        execution_summary = self.execution_store.build_summary(state.task_run_id)
        execution_refs = tuple(str(item) for item in list(execution_summary.get("execution_refs") or []))
        execution_state_ref = str(execution_summary.get("latest_execution_id") or "")
        agent_runs = tuple(self.state_index.list_task_agent_runs(state.task_run_id))
        coordination_runs = tuple(self.state_index.list_task_coordination_runs(state.task_run_id))
        checkpoint = self.checkpoints.write(
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
        return self.event_log.append(
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

    @staticmethod
    def _dedupe_refs(refs: Any) -> list[str]:
        return dedupe_artifact_refs(refs)


def _specific_task_record_for_runtime_ref(flow_registry: TaskFlowRegistry, task_ref: str) -> Any | None:
    raw = str(task_ref or "").strip()
    if not raw:
        return None
    suffix = raw.split(":")[-1].strip()
    if not suffix:
        return None
    for record in flow_registry.list_specific_task_records():
        task_id = str(getattr(record, "task_id", "") or "").strip()
        if task_id == raw or task_id.endswith(f".{suffix}") or task_id.split(".")[-1] == suffix:
            return record
    return None


def _stage_execution_request_for_finalizer(
    *,
    task_run_diagnostics: dict[str, Any] | None,
    current_turn_context: dict[str, Any] | None,
    coordination_run: CoordinationRun | None,
    langgraph_coordination_runtime: LangGraphCoordinationRuntime,
) -> dict[str, Any]:
    diagnostics = dict(task_run_diagnostics or {})
    assembly = dict(diagnostics.get("agent_assembly_contract") or {})
    work_order = dict(assembly.get("work_order") or {})
    if work_order:
        return _stage_request_payload_from_work_order(work_order)
    context_request = dict(dict(current_turn_context or {}).get("stage_execution_request") or {})
    if context_request:
        return context_request
    if coordination_run is not None and langgraph_coordination_runtime.supports(coordination_run):
        state = langgraph_coordination_runtime.checkpoints.get_state(thread_id=coordination_run.coordination_run_id) or {}
        return dict(state.get("stage_execution_request") or {})
    return {}


def _stage_request_payload_from_work_order(work_order: dict[str, Any]) -> dict[str, Any]:
    item = dict(work_order or {})
    if not item:
        return {}
    return {
        "request_id": str(item.get("work_order_id") or ""),
        "coordination_run_id": str(item.get("coordination_run_id") or ""),
        "thread_id": str(item.get("thread_id") or item.get("coordination_run_id") or ""),
        "root_task_run_id": str(item.get("root_task_run_id") or ""),
        "stage_id": str(item.get("stage_id") or ""),
        "node_id": str(item.get("node_id") or item.get("stage_id") or ""),
        "task_ref": str(item.get("task_ref") or ""),
        "agent_id": str(item.get("agent_id") or ""),
        "agent_profile_id": str(item.get("agent_profile_id") or ""),
        "runtime_lane": str(item.get("runtime_lane") or ""),
        "executor_type": str(item.get("executor_type") or "agent"),
        "executor_binding": dict(item.get("executor_binding") or {}),
        "message": str(item.get("message") or ""),
        "explicit_inputs": sanitize_explicit_inputs(item.get("explicit_inputs") or {}),
        "standard_input_package": dict(item.get("input_package") or item.get("standard_input_package") or {}),
        "artifact_policy": dict(item.get("artifact_policy") or {}),
        "stream_policy": dict(item.get("stream_policy") or {}),
        "artifact_root": str(item.get("artifact_root") or ""),
        "artifact_targets": list(item.get("artifact_targets") or []),
        "output_contract_id": str(item.get("output_contract_id") or ""),
        "expected_outputs": list(item.get("expected_outputs") or []),
        "working_memory_refs": list(item.get("working_memory_refs") or []),
        "dispatch_context": dict(item.get("dispatch_context") or {}),
        "memory_snapshot": dict(item.get("memory_snapshot") or {}),
        "artifact_context_packet": dict(item.get("artifact_context_packet") or {}),
        "revision_packet": dict(item.get("revision_packet") or {}),
        "handoff_packet_refs": list(item.get("handoff_packet_refs") or []),
        "timeline_result_policy": dict(item.get("timeline_result_policy") or {}),
        "human_work_packet": dict(item.get("human_work_packet") or {}),
        "a2a_payload": dict(item.get("a2a_payload") or {}),
        "runtime_assembly": dict(item.get("runtime_assembly") or {}),
        "idempotency_key": str(item.get("idempotency_key") or ""),
    }


def _task_run_finalization_suppression_reason(
    *,
    existing_task_run: TaskRun | None,
    terminal_state: RuntimeLoopState,
    events: list[Any],
) -> str:
    incoming_status = str(terminal_state.status or "")
    incoming_terminal_reason = str(terminal_state.terminal_reason or "")
    if incoming_status == "aborted":
        return ""
    if existing_task_run is not None:
        existing_status = str(existing_task_run.status or "")
        existing_terminal_reason = str(existing_task_run.terminal_reason or "")
        if existing_status == "aborted":
            return "task_run_already_aborted"
        if existing_status == "failed" and _has_invalidating_diagnostic(existing_task_run.diagnostics):
            return "task_run_already_invalidated"
        if existing_terminal_reason == "user_aborted" and incoming_terminal_reason != "user_aborted":
            return "task_run_already_stopped"
    if incoming_terminal_reason == "completed" and _has_stop_event(events):
        return "task_run_stop_event_precedes_finalization"
    return ""


def _has_invalidating_diagnostic(diagnostics: dict[str, Any] | None) -> bool:
    payload = dict(diagnostics or {})
    return bool(
        payload.get("invalidated_by_coordination_rewind")
        or payload.get("invalidated_by_stage_scheduler")
        or payload.get("stop_request")
    )


def _has_stop_event(events: list[Any]) -> bool:
    return any(str(getattr(event, "event_type", "") or "") == "task_run_stopped" for event in events)


def _suppressed_agent_run_status(reason: str) -> str:
    if "aborted" in str(reason or "") or "stopped" in str(reason or "") or "stop_event" in str(reason or ""):
        return "killed"
    return "failed"


def _task_run_ledger_from_payload(payload: dict[str, Any]):
    from task_system.tasks.run_models import TaskRunLedger, TaskStepRun

    return TaskRunLedger(
        ledger_id=str(payload.get("ledger_id") or ""),
        task_run_id=str(payload.get("task_run_id") or ""),
        task_id=str(payload.get("task_id") or ""),
        task_spec_ref=str(payload.get("task_spec_ref") or ""),
        template_id=str(payload.get("template_id") or ""),
        status=payload.get("status", "created"),
        current_step_id=str(payload.get("current_step_id") or ""),
        requested_outputs=tuple(str(item) for item in list(payload.get("requested_outputs") or []) if str(item)),
        step_runs=tuple(
            _task_step_run_from_payload(dict(item))
            for item in list(payload.get("step_runs") or [])
            if isinstance(item, dict)
        ),
        refs=dict(payload.get("refs") or {}),
        diagnostics=dict(payload.get("diagnostics") or {}),
    )


def _task_step_run_from_payload(payload: dict[str, Any]):
    from task_system.tasks.run_models import TaskStepRun

    return TaskStepRun(
        step_id=str(payload.get("step_id") or ""),
        title=str(payload.get("title") or ""),
        step_kind=str(payload.get("step_kind") or ""),
        executor_type=str(payload.get("executor_type") or ""),
        status=payload.get("status", "pending"),
        required_operations=tuple(str(item) for item in list(payload.get("required_operations") or []) if str(item)),
        optional_operations=tuple(str(item) for item in list(payload.get("optional_operations") or []) if str(item)),
        input_refs=tuple(str(item) for item in list(payload.get("input_refs") or []) if str(item)),
        output_contract_id=str(payload.get("output_contract_id") or ""),
        stop_policy=str(payload.get("stop_policy") or "on_success"),
        retry_policy=dict(payload.get("retry_policy") or {}),
        observation_refs=tuple(str(item) for item in list(payload.get("observation_refs") or []) if str(item)),
        output_refs=tuple(str(item) for item in list(payload.get("output_refs") or []) if str(item)),
        entered_at=float(payload.get("entered_at") or 0.0),
        completed_at=float(payload.get("completed_at") or 0.0),
        attempt_count=int(payload.get("attempt_count") or 0),
        failure_reason=str(payload.get("failure_reason") or ""),
        step_result_ref=str(payload.get("step_result_ref") or ""),
        executor_ref=str(payload.get("executor_ref") or ""),
        diagnostics=dict(payload.get("diagnostics") or {}),
    )
