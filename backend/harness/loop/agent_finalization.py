from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Callable

from context_system.projection.projection import projection_from_bundle_answer
from orchestration.commit_gate import build_assistant_session_message_commit_decision, build_task_run_final_commit_decision
from task_system.tasks.run_models import (
    TaskRunLedger,
    project_task_result_from_ledger,
    task_run_step_count,
    task_run_terminal_status,
)

from harness.loop.agent_execution.observation_flow import apply_observation_aggregation
from runtime.memory.observation_aggregator import ObservationAggregator
from harness.loop.state import HarnessLoopState
from .agent_lifecycle import AgentRuntimeStartResult


@dataclass(slots=True)
class AgentRunFinalizationInput:
    session_id: str
    task_id: str
    history: list[dict[str, Any]]
    source: str
    start: AgentRuntimeStartResult
    terminal_state: HarnessLoopState
    runtime_task_ledger: TaskRunLedger | None
    result_refs: list[str]
    final_content: str
    final_answer_metadata: dict[str, Any]
    run_outcome: dict[str, Any]
    terminal_reason: str
    final_main_context: dict[str, Any]
    final_task_summary_refs: list[dict[str, Any]]
    final_bundle_summary_refs: list[dict[str, Any]]
    current_bundle_items: list[dict[str, Any]]
    executed_bundle_ordinals: list[int]
    observation_aggregator: ObservationAggregator
    current_turn_context: dict[str, Any]
    selected_recipe_payload: dict[str, Any]
    task_contract_ref: str
    task_spec_payload: dict[str, Any]
    user_message: str
    tool_observation_count: int
    turn_count: int
    assistant_message_committer: Callable[[dict[str, Any]], Any] | None


@dataclass(slots=True)
class AgentRunFinalizationResult:
    done_event: dict[str, Any]
    continuation_payload: dict[str, Any] = field(default_factory=dict)
    terminal_state: HarnessLoopState | None = None
    result_refs: list[str] = field(default_factory=list)


async def finalize_agent_run(
    runtime_host: Any,
    finalization: AgentRunFinalizationInput,
):
    result_refs = list(finalization.result_refs)
    final_content = finalization.final_content
    final_answer_metadata = dict(finalization.final_answer_metadata)
    final_main_context = dict(finalization.final_main_context)
    final_task_summary_refs = [dict(item) for item in finalization.final_task_summary_refs]
    final_bundle_summary_refs = [dict(item) for item in finalization.final_bundle_summary_refs]
    terminal_reason = finalization.terminal_reason
    terminal_state = finalization.terminal_state

    if (
        finalization.current_bundle_items
        and final_content
        and not _suppress_bundle_projection_for_task_graph_node(
            current_turn_context=dict(finalization.current_turn_context or {}),
            selected_recipe_payload=finalization.selected_recipe_payload,
        )
    ):
        bundle_projection = projection_from_bundle_answer(
            content=final_content,
            bundle_items=finalization.current_bundle_items,
            existing_task_summary_refs=final_task_summary_refs,
            existing_main_context=final_main_context,
            executed_ordinals=finalization.executed_bundle_ordinals,
        )
        if bundle_projection.bundle_summary_refs:
            aggregation = finalization.observation_aggregator.add_projection(bundle_projection, tool_name="bundle_answer")
            (
                final_main_context,
                final_task_summary_refs,
                final_bundle_summary_refs,
            ) = apply_observation_aggregation(aggregation)

    context_answer_source = str(final_main_context.get("answer_source") or "").strip()
    if context_answer_source and str(final_answer_metadata.get("answer_source") or "").strip() in {
        "",
        "runtime_directive:model_response",
        "runtime_mcp",
    }:
        final_answer_metadata = {
            **dict(final_answer_metadata),
            "answer_source": context_answer_source,
        }

    assistant_commit = build_assistant_session_message_commit_decision(
        session_id=finalization.session_id,
        task_run_id=terminal_state.task_run_id,
        task_id=finalization.task_id,
        content=final_content,
        **assistant_commit_metadata(final_answer_metadata),
    )
    output_refs = [
        item["task_id"]
        for item in final_task_summary_refs
        if str(item.get("task_id") or "").strip()
    ]
    output_refs.extend(
        item["task_id"]
        for item in final_bundle_summary_refs
        if str(item.get("task_id") or "").strip()
    )
    final_task_run_ledger, ledger_transitions = finalize_runtime_task_run_ledger(
        ledger=finalization.runtime_task_ledger,
        terminal_reason=terminal_reason,
        final_content=final_content,
        output_refs=tuple(dedupe_refs([*result_refs, *output_refs])),
    )
    if final_task_run_ledger is not None:
        for transition in ledger_transitions:
            step_run = transition["step_run"]
            step_diagnostics = dict(transition.get("diagnostics") or {})
            if transition["event_type"] in {"step_completed", "step_failed"} and not str(step_run.step_summary_ref or "").strip():
                status = "completed" if transition["event_type"] == "step_completed" else "failed"
                summary_ref, step_run, final_task_run_ledger, summary_event = runtime_host._record_step_execution_summary(
                    ledger=final_task_run_ledger,
                    step_run=step_run,
                    reason=transition["reason"],
                    status=status,
                    refs={
                        "terminal_reason": terminal_reason,
                        "step_result_ref": str(step_run.step_result_ref or ""),
                    },
                    diagnostics={
                        "transition_reason": transition["reason"],
                        "terminal_reason": terminal_reason,
                        "tool_observation_count": int(finalization.tool_observation_count or 0),
                        **step_diagnostics,
                    },
                )
                step_diagnostics = {**step_diagnostics, "step_summary_ref": summary_ref}
                yield {"type": "harness_loop_event", "event": summary_event.to_dict()}
            step_event = runtime_host._record_task_run_step_event(
                terminal_state.task_run_id,
                event_type=transition["event_type"],
                step_run=step_run,
                ledger=final_task_run_ledger,
                reason=transition["reason"],
                diagnostics=step_diagnostics,
            )
            yield {"type": "harness_loop_event", "event": step_event.to_dict()}
        ledger_event = runtime_host._record_task_run_ledger_updated(
            terminal_state.task_run_id,
            ledger=final_task_run_ledger,
            reason="terminal_projection",
            diagnostics={"terminal_reason": terminal_reason},
        )
        yield {"type": "harness_loop_event", "event": ledger_event.to_dict()}
        terminal_state = runtime_host._state_with_task_run_ledger(
            terminal_state,
            final_task_run_ledger,
            result_refs=result_refs,
            diagnostics={"last_step_transition": "terminal_projection"},
        )
        checkpoint_event = runtime_host._write_checkpoint_event(terminal_state, event_offset=ledger_event.offset)
        yield {"type": "harness_loop_event", "event": checkpoint_event.to_dict()}
    task_result = (
        project_task_result_from_ledger(
            final_task_run_ledger,
            result_id=f"taskresult:{terminal_state.task_run_id}",
            status=task_run_terminal_status(terminal_reason),
            terminal_reason=terminal_reason,
            result_refs=tuple(dedupe_refs(result_refs)),
            output_refs=tuple(dedupe_refs(output_refs)),
            final_outputs={
                "final_answer": final_content,
                "main_context": dict(final_main_context),
                "task_summary_refs": [dict(item) for item in final_task_summary_refs],
                "bundle_summary_refs": [dict(item) for item in final_bundle_summary_refs],
                "answer_metadata": dict(final_answer_metadata),
            },
            completion=finalization.run_outcome,
            diagnostics={
                "tool_observation_count": int(finalization.tool_observation_count or 0),
                "final_content_chars": len(str(final_content or "")),
                "bundle_result_count": len(final_bundle_summary_refs),
                "task_summary_count": len(final_task_summary_refs),
            },
        )
        if final_task_run_ledger is not None
        else None
    )
    if final_task_run_ledger is not None and final_task_run_ledger.ledger_id not in result_refs:
        result_refs.append(final_task_run_ledger.ledger_id)
    if task_result is not None and task_result.result_id not in result_refs:
        result_refs.append(task_result.result_id)

    assistant_commit_applied = False
    assistant_commit_result: Any = None
    if assistant_commit.commit_allowed and finalization.assistant_message_committer is not None:
        assistant_payload = dict(assistant_commit.commit_candidate.payload)
        if final_main_context:
            assistant_payload["main_context"] = dict(final_main_context)
        if final_task_summary_refs:
            assistant_payload["task_summary_refs"] = [dict(item) for item in final_task_summary_refs]
        if final_bundle_summary_refs:
            assistant_payload["bundle_summary_refs"] = [dict(item) for item in final_bundle_summary_refs]
        assistant_commit_result = finalization.assistant_message_committer(assistant_payload)
        if inspect.isawaitable(assistant_commit_result):
            assistant_commit_result = await assistant_commit_result
        assistant_commit_applied = True
    assistant_commit_summary = commit_result_summary(assistant_commit_result)
    memory_commit_state = memory_commit_state_from_assistant_commit_result(assistant_commit_result)
    assistant_commit_event = runtime_host.event_log.append(
        terminal_state.task_run_id,
        "commit_gate_checked",
        payload={
            "commit_decision": assistant_commit.to_dict(),
            "commit_applied": assistant_commit_applied,
            "commit_result": assistant_commit_summary,
            "memory_commit_state": memory_commit_state,
        },
        refs={
            "commit_gate_ref": assistant_commit.gate_id,
            "commit_type": assistant_commit.commit_type,
            "commit_scope": "assistant_final_message_only",
        },
    )
    result_refs.append(f"commit_gate:{assistant_commit.gate_id}")
    yield {"type": "harness_loop_event", "event": assistant_commit_event.to_dict()}
    yield {
        "type": "runtime_assistant_session_commit",
        "commit_gate": assistant_commit.to_dict(),
        "commit_applied": assistant_commit_applied,
    }

    final_commit = build_task_run_final_commit_decision(
        task_run_id=terminal_state.task_run_id,
        task_id=finalization.task_id,
        task_spec_ref=task_result.task_spec_ref if task_result is not None else "",
        template_id=task_result.template_id if task_result is not None else "",
        terminal_reason=terminal_state.terminal_reason,
        final_content_chars=len(final_content),
        task_result=task_result.to_dict() if task_result is not None else None,
    )
    commit_event = runtime_host.event_log.append(
        terminal_state.task_run_id,
        "commit_gate_checked",
        payload={"commit_decision": final_commit.to_dict()},
        refs={
            "commit_gate_ref": final_commit.gate_id,
            "commit_type": final_commit.commit_type,
        },
    )
    result_refs.append(f"commit_gate:{final_commit.gate_id}")
    yield {"type": "harness_loop_event", "event": commit_event.to_dict()}
    yield {"type": "runtime_task_result_commit", "commit_gate": final_commit.to_dict()}

    working_memory_finalization = runtime_host.finalize_working_memory(
        task_run_id=terminal_state.task_run_id,
        actor_id=terminal_state.agent_id or "runloop",
        terminal_reason=terminal_state.terminal_reason or terminal_reason,
    )
    working_memory_finalization_result = dict(working_memory_finalization.get("result") or {})
    result_refs.append(f"working_memory_finalization:{working_memory_finalization_result.get('archive_report_path') or terminal_state.task_run_id}")
    yield {"type": "harness_loop_event", "event": dict(working_memory_finalization.get("event") or {})}
    yield {"type": "working_memory_finalized", "result": working_memory_finalization_result}

    done_event = {
        "type": "done",
        "content": final_content,
        "main_context": dict(final_main_context),
        "task_summary_refs": [dict(item) for item in final_task_summary_refs],
        "bundle_summary_refs": [dict(item) for item in final_bundle_summary_refs],
        "followup_mode": str(final_main_context.get("followup_mode") or ""),
        "followup_target_task_id": str(final_main_context.get("followup_target_task_id") or ""),
        "followup_target_task_ids": list(final_main_context.get("followup_target_task_ids") or []),
        **final_answer_metadata,
        "persist_policy": "committed" if terminal_reason == "completed" else "progress_only",
        "terminal_reason": terminal_reason,
        "commit_gate": assistant_commit.to_dict(),
        "task_result_commit": final_commit.to_dict(),
        "working_memory_finalization": working_memory_finalization_result,
        "task_run_ledger": final_task_run_ledger.to_dict() if final_task_run_ledger is not None else {},
        "task_result": task_result.to_dict() if task_result is not None else {},
        "completion": dict(finalization.run_outcome or {}),
        "output_commit": {
            "state": "committed" if assistant_commit_applied else "not_applied",
            "assistant_commit_applied": assistant_commit_applied,
            "assistant_commit": assistant_commit.to_dict(),
            "task_result_commit": final_commit.to_dict(),
            "working_memory_finalization": working_memory_finalization_result,
            "memory": dict(memory_commit_state),
            "file_work_context_writeback": bool(final_main_context or final_task_summary_refs),
        },
    }
    terminal_state = HarnessLoopState(
        task_run_id=terminal_state.task_run_id,
        status=terminal_state.status,
        turn_count=finalization.turn_count,
        step_count=task_run_step_count(final_task_run_ledger),
        current_step_id=final_task_run_ledger.current_step_id if final_task_run_ledger is not None else terminal_state.current_step_id,
        agent_id=terminal_state.agent_id,
        agent_profile_id=terminal_state.agent_profile_id,
        runtime_lane=terminal_state.runtime_lane,
        task_agent_binding_ref=terminal_state.task_agent_binding_ref,
        task_template_id=final_task_run_ledger.template_id if final_task_run_ledger is not None else terminal_state.task_template_id,
        task_spec_ref=final_task_run_ledger.task_spec_ref if final_task_run_ledger is not None else terminal_state.task_spec_ref,
        task_result_ref=task_result.result_id if task_result is not None else "",
        skill_workflow_ref=terminal_state.skill_workflow_ref,
        health_issue_ref=terminal_state.health_issue_ref,
        transition=terminal_state.transition,
        terminal_reason=terminal_state.terminal_reason,
        messages_ref=terminal_state.messages_ref,
        context_snapshot_ref=terminal_state.context_snapshot_ref,
        memory_state_ref=terminal_state.memory_state_ref,
        prompt_manifest_ref=terminal_state.prompt_manifest_ref,
        pending_action_requests=terminal_state.pending_action_requests,
        pending_approval_state=terminal_state.pending_approval_state,
        denial_tracking_state=terminal_state.denial_tracking_state,
        token_pressure=terminal_state.token_pressure,
        compaction_state=terminal_state.compaction_state,
        result_refs=tuple(result_refs),
        commit_state={
            "assistant_session_message": assistant_commit.to_dict(),
            "assistant_session_write_applied": assistant_commit_applied,
            "task_result_final": final_commit.to_dict(),
            "task_run_ledger": final_task_run_ledger.to_dict() if final_task_run_ledger is not None else {},
            "task_result": task_result.to_dict() if task_result is not None else {},
            "assistant_session_write_allowed": assistant_commit.commit_allowed,
            "working_memory_finalization": working_memory_finalization_result,
            **memory_commit_state,
            "artifact_write_allowed": False,
        },
        diagnostics={
            **dict(terminal_state.diagnostics),
            "result_ref_count": len(result_refs),
            "working_memory_finalized": True,
            "working_memory_finalization": working_memory_finalization_result,
        },
    )
    terminal_event = runtime_host.event_log.append(
        terminal_state.task_run_id,
        "loop_terminal",
        payload={
            "terminal_reason": terminal_state.terminal_reason,
            "status": terminal_state.status,
            "final_content_chars": len(final_content),
            "task_result": task_result.to_dict() if task_result is not None else {},
        },
    )
    yield {"type": "harness_loop_event", "event": terminal_event.to_dict()}
    checkpoint_event = runtime_host._write_checkpoint_event(terminal_state, event_offset=terminal_event.offset)
    yield {"type": "harness_loop_event", "event": checkpoint_event.to_dict()}

    continuation_payload: dict[str, Any] = {}
    try:
        finished = runtime_host.task_run_finalizer.upsert_finished_task_run(
            start_task_run=finalization.start.task_run,
            start_agent_run=finalization.start.agent_run,
            start_coordination_run=finalization.start.coordination_run,
            task_contract_ref=finalization.task_contract_ref,
            terminal_state=terminal_state,
            checkpoint_event=checkpoint_event,
            final_content=final_content,
            task_result=task_result.to_dict() if task_result is not None else {},
            task_spec_payload=finalization.task_spec_payload,
            current_turn_context=finalization.current_turn_context,
            user_message=finalization.user_message,
            diagnostics={"final_content_chars": len(final_content)},
        )
        for runtime_event in finished.events:
            yield {"type": "harness_loop_event", "event": runtime_event.to_dict()}
        continuation_payload = dict(finished.continuation_payload or {})
    except Exception as exc:
        state_index_diagnostics = {
            "degraded": True,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "phase": "finished_task_run_state_write",
        }
        done_event["output_commit"] = {
            **dict(done_event.get("output_commit") or {}),
            "state_index_degraded": True,
            "state_index_error": state_index_diagnostics,
        }
        done_event["runtime_state_index"] = state_index_diagnostics
        try:
            degraded_event = runtime_host.event_log.append(
                terminal_state.task_run_id,
                "runtime_state_index_degraded",
                payload=state_index_diagnostics,
                refs={"checkpoint_ref": str(checkpoint_event.refs.get("checkpoint_ref") or "")},
            )
            yield {"type": "harness_loop_event", "event": degraded_event.to_dict()}
        except Exception:
            pass
    if continuation_payload:
        done_event["coordination_continuation"] = dict(continuation_payload)
        done_event["output_commit"] = {
            **dict(done_event.get("output_commit") or {}),
            "coordination_continuation_ready": True,
        }
    yield AgentRunFinalizationResult(
        done_event=done_event,
        continuation_payload=continuation_payload,
        terminal_state=terminal_state,
        result_refs=result_refs,
    )


def commit_result_summary(result: Any) -> dict[str, Any]:
    if result is None:
        return {"applied_count": 0}
    if isinstance(result, list):
        return {"applied_count": len(result)}
    if isinstance(result, dict):
        return {"applied_count": 1, "keys": sorted(str(key) for key in result.keys())}
    return {"applied_count": 1, "result_type": type(result).__name__}


def memory_commit_state_from_assistant_commit_result(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {
            "memory_write_allowed": False,
            "session_memory_refresh_applied": False,
            "durable_memory_commit_attempted": False,
            "durable_memory_commit_failed": False,
            "durable_memory_commit_applied": False,
            "memory_maintenance_attempted": False,
            "memory_maintenance_status": "",
            "session_memory_succeeded": False,
            "durable_memory_succeeded": False,
            "durable_write_count": 0,
            "session_memory_chars": 0,
            "durable_saved_count": 0,
        }
    session_memory_chars = _safe_int(result.get("session_memory_chars"))
    durable_saved_count = _safe_int(result.get("durable_write_count", result.get("durable_saved_count")))
    maintenance_attempted = bool(result.get("memory_maintenance_attempted") is True)
    maintenance_status = str(result.get("memory_maintenance_status") or "")
    session_memory_succeeded = bool(result.get("session_memory_succeeded") is True)
    durable_memory_succeeded = bool(result.get("durable_memory_succeeded") is True)
    durable_commit_attempted = maintenance_attempted or bool(result.get("durable_memory_commit_attempted") is True)
    durable_commit_failed = maintenance_status == "failed" or bool(result.get("durable_memory_commit_failed") is True)
    return {
        "memory_write_allowed": True,
        "session_memory_refresh_applied": session_memory_succeeded or session_memory_chars > 0,
        "durable_memory_commit_attempted": durable_commit_attempted,
        "durable_memory_commit_failed": durable_commit_failed,
        "durable_memory_commit_applied": durable_commit_attempted and not durable_commit_failed and durable_saved_count > 0,
        "memory_maintenance_attempted": maintenance_attempted,
        "memory_maintenance_status": maintenance_status,
        "session_memory_succeeded": session_memory_succeeded,
        "durable_memory_succeeded": durable_memory_succeeded,
        "durable_write_count": durable_saved_count,
        "session_memory_chars": session_memory_chars,
        "durable_saved_count": durable_saved_count,
    }


def _safe_int(value: Any, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def assistant_commit_metadata(final_answer_metadata: dict[str, Any] | None) -> dict[str, Any]:
    metadata = dict(final_answer_metadata or {})
    allowed_keys = {
        "answer_channel",
        "answer_source",
        "answer_canonical_state",
        "answer_persist_policy",
        "answer_finalization_policy",
        "answer_fallback_reason",
        "completion_state",
        "terminal_reason",
        "timeout_seconds",
        "partial_delta_count",
    }
    return {
        key: str(metadata.get(key) or "")
        for key in allowed_keys
        if str(metadata.get(key) or "").strip()
    }


def dedupe_refs(values: list[str]) -> list[str]:
    refs: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        refs.append(item)
    return refs


def _suppress_bundle_projection_for_task_graph_node(
    *,
    current_turn_context: dict[str, Any],
    selected_recipe_payload: dict[str, Any],
) -> bool:
    context = dict(current_turn_context or {})
    if context.get("suppress_bundle_projection") is True:
        return True
    if str(context.get("stage_execution_request_ref") or "").strip():
        return True
    if str(context.get("source") or "").startswith("codex_rewind_"):
        return True
    metadata = dict(dict(selected_recipe_payload or {}).get("metadata") or {})
    return bool(metadata.get("task_graph_node_runtime") is True or metadata.get("suppress_bundle_projection") is True)


def finalize_runtime_task_run_ledger(
    *,
    ledger: TaskRunLedger | None,
    terminal_reason: str,
    final_content: str,
    output_refs: tuple[str, ...],
) -> tuple[TaskRunLedger | None, list[dict[str, Any]]]:
    from task_system.tasks.run_models import (
        complete_task_run_step,
        current_task_step_run,
        fail_task_run_step,
        find_task_step_run,
        next_pending_step_run,
        skip_task_run_step,
        start_task_run_step,
        terminalize_task_run_ledger,
    )

    if ledger is None:
        return None, []
    transitions: list[dict[str, Any]] = []
    if terminal_reason == "completed":
        finalized = ledger
        while True:
            current_step = current_task_step_run(finalized)
            if (
                current_step is not None
                and current_step.status == "running"
                and current_step.stop_policy == "allow_unverified_completion"
                and current_step.executor_type in {"tool", "mcp", "agent"}
            ):
                finalized = skip_task_run_step(
                    finalized,
                    step_id=current_step.step_id,
                    completed_at=0.0,
                    diagnostics={"transition_reason": "allow_unverified_completion"},
                )
                skipped_step = find_task_step_run(finalized, current_step.step_id)
                if skipped_step is not None:
                    transitions.append(
                        {
                            "event_type": "step_skipped",
                            "step_run": skipped_step,
                            "reason": "allow_unverified_completion",
                        }
                    )
                    continue
            if current_step is None:
                next_step = next_pending_step_run(finalized)
                if next_step is None:
                    break
                if next_step.stop_policy == "allow_unverified_completion":
                    finalized = skip_task_run_step(
                        finalized,
                        step_id=next_step.step_id,
                        completed_at=0.0,
                        diagnostics={"transition_reason": "allow_unverified_completion"},
                    )
                    skipped_step = find_task_step_run(finalized, next_step.step_id)
                    if skipped_step is not None:
                        transitions.append(
                            {
                                "event_type": "step_skipped",
                                "step_run": skipped_step,
                                "reason": "allow_unverified_completion",
                            }
                        )
                    continue
                if final_content and next_step.executor_type == "model":
                    finalized = start_task_run_step(
                        finalized,
                        step_id=next_step.step_id,
                        started_at=0.0,
                        diagnostics={"transition_reason": "terminal_finalize"},
                    )
                    entered_step = current_task_step_run(finalized)
                    if entered_step is not None:
                        transitions.append(
                            {
                                "event_type": "step_entered",
                                "step_run": entered_step,
                                "reason": "terminal_finalize",
                            }
                        )
                    continue
                break
            if current_step.status == "pending" and final_content and current_step.executor_type == "model":
                finalized = start_task_run_step(
                    finalized,
                    step_id=current_step.step_id,
                    started_at=0.0,
                    diagnostics={"transition_reason": "terminal_finalize"},
                )
                entered_step = current_task_step_run(finalized)
                if entered_step is not None:
                    transitions.append(
                        {
                            "event_type": "step_entered",
                            "step_run": entered_step,
                            "reason": "terminal_finalize",
                            "diagnostics": {"transition_reason": "terminal_finalize"},
                        }
                    )
                continue
            if final_content:
                finalized = complete_task_run_step(
                    finalized,
                    step_id=current_step.step_id,
                    completed_at=0.0,
                    output_refs=output_refs,
                    step_result_ref=output_refs[0] if output_refs else "",
                    executor_ref=current_step.executor_ref,
                    diagnostics={"transition_reason": "terminal_finalize"},
                )
                completed_step = find_task_step_run(finalized, current_step.step_id)
                if completed_step is not None:
                    transitions.append(
                        {
                            "event_type": "step_completed",
                            "step_run": completed_step,
                            "reason": "terminal_finalize",
                        }
                    )
                continue
            break
        finalized = terminalize_task_run_ledger(
            finalized,
            status="completed",
            current_step_id="",
            diagnostics={"terminal_reason": terminal_reason},
        )
        return finalized, transitions

    finalized = ledger
    current_step = current_task_step_run(finalized)
    if current_step is not None and current_step.status == "running":
        finalized = fail_task_run_step(
            finalized,
            step_id=current_step.step_id,
            completed_at=0.0,
            failure_reason=terminal_reason,
            output_refs=output_refs,
            step_result_ref=output_refs[0] if output_refs else "",
            diagnostics={"transition_reason": "terminal_finalize"},
        )
        failed_step = find_task_step_run(finalized, current_step.step_id)
        if failed_step is not None:
            transitions.append(
                {
                    "event_type": "step_failed",
                    "step_run": failed_step,
                    "reason": "terminal_failure",
                }
            )
    finalized = terminalize_task_run_ledger(
        finalized,
        status=task_run_terminal_status(terminal_reason),
        current_step_id=finalized.current_step_id,
        diagnostics={"terminal_reason": terminal_reason},
    )
    return finalized, transitions


