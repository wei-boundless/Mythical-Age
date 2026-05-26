from __future__ import annotations

from pathlib import Path
from typing import Any

from .evidence_models import EvidenceCandidate, RecoveryHandle, TaskGraphRecoveryCandidate
from .evidence_packet_builder import build_evidence_packet
from .evidence_scorer import score_negative_observation, score_runtime_event
from .maintenance.experiments.artifacts import read_json_file


def build_runtime_trace_evidence_packet(
    trace: dict[str, Any] | None,
    *,
    question: str,
    output_limit: int = 8,
    semantic_hint: str = "",
) -> dict[str, Any]:
    trace = dict(trace or {})
    task_run = dict(trace.get("task_run") or {})
    events = [dict(item) for item in list(trace.get("events") or []) if isinstance(item, dict)]
    coordination_runs = [dict(item) for item in list(trace.get("coordination_runs") or []) if isinstance(item, dict)]
    latest_checkpoint = _latest_checkpoint_from_trace(trace, events)
    candidates = _collect_event_candidates(events, task_run_id=str(task_run.get("task_run_id") or ""))
    candidates.extend(_collect_coordination_candidates(coordination_runs, task_run_id=str(task_run.get("task_run_id") or "")))
    if not candidates and latest_checkpoint:
        candidates.append(_checkpoint_candidate(latest_checkpoint, task_run_id=str(task_run.get("task_run_id") or "")))
    recovery_handles = _build_recovery_handles(
        events,
        latest_checkpoint=latest_checkpoint,
        coordination_runs=coordination_runs,
    )
    packet = build_evidence_packet(
        question=question,
        candidates=candidates,
        verdict=_verdict_from_events(events),
        confidence=_confidence_from_events(candidates),
        summary=_summary_from_events(events, semantic_hint=semantic_hint),
        recovery_handles=recovery_handles,
        test_handles=_test_handles_from_trace(trace),
        selected_limit=output_limit,
    )
    return packet.to_dict()


def build_task_graph_recovery_candidates(trace: dict[str, Any] | None) -> list[dict[str, Any]]:
    trace = dict(trace or {})
    coordination_runs = list(trace.get("coordination_runs") or [])
    latest_checkpoint = dict(trace.get("latest_checkpoint") or {})
    candidates: list[TaskGraphRecoveryCandidate] = []
    for run in coordination_runs:
        run_payload = dict(run or {})
        coordination_run_id = str(run_payload.get("coordination_run_id") or "")
        scheduler_state = dict(dict(run_payload.get("diagnostics") or {}).get("task_graph_scheduler_state") or {})
        checkpoint_ref = str(
            dict(run_payload.get("coordination_checkpoint") or {}).get("checkpoint_id")
            or latest_checkpoint.get("checkpoint_id")
            or ""
        )
        node_states = dict(scheduler_state.get("node_statuses") or {})
        failing_nodes = [
            str(node_id)
            for node_id, status in node_states.items()
            if _node_status_value(status) in {"failed", "blocked"}
        ]
        node_ref = failing_nodes[0] if failing_nodes else ""
        candidates.append(
            TaskGraphRecoveryCandidate(
                candidate_id=f"tg-recovery:{coordination_run_id or checkpoint_ref}",
                coordination_run_ref=coordination_run_id,
                checkpoint_ref=checkpoint_ref,
                node_ref=node_ref,
                edge_ref="",
                stage_ref=str(dict(run_payload.get("coordination_flow") or {}).get("current_stage_id") or ""),
                risk="high" if failing_nodes else "medium",
                reason="coordination_run_trace_analysis",
                side_effect_replay_risk="unknown" if not checkpoint_ref else "medium",
            )
        )
    return [item.to_dict() for item in candidates]


def build_turn_artifact_evidence_packet(
    artifact_path: str | Path,
    *,
    question: str,
    output_limit: int = 8,
) -> dict[str, Any]:
    payload = read_json_file(Path(artifact_path), {})
    if not isinstance(payload, dict):
        return build_evidence_packet(question=question, candidates=[], selected_limit=output_limit).to_dict()
    trace = _trace_from_turn_payload(payload)
    return build_runtime_trace_evidence_packet(trace, question=question, output_limit=output_limit)


def runtime_events_from_turn_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    direct = list(payload.get("runtime_loop_events") or [])
    if direct:
        return [dict(item) for item in direct if isinstance(item, dict)]
    events: list[dict[str, Any]] = []
    for item in list(payload.get("events") or []):
        if not isinstance(item, dict):
            continue
        if str(item.get("event") or "") != "runtime_loop_event":
            continue
        data = dict(item.get("data") or {})
        event = dict(data.get("event") or data)
        if event:
            events.append(event)
    return events


def _trace_from_turn_payload(payload: dict[str, Any]) -> dict[str, Any]:
    result = dict(payload.get("result") or {})
    events = runtime_events_from_turn_payload(payload)
    runtime_trace = dict(payload.get("runtime_trace") or {})
    coordination_runs = list(payload.get("coordination_runs") or [])
    if not coordination_runs:
        coordination_runs = list(runtime_trace.get("coordination_runs") or [])
    if not coordination_runs and int(runtime_trace.get("coordination_run_count") or 0) > 0:
        coordination_flow = dict(runtime_trace.get("coordination_flow") or {})
        coordination_runs = [
            {
                "coordination_run_id": str(runtime_trace.get("coordination_run_id") or ""),
                "status": str(runtime_trace.get("coordination_status") or ""),
                "graph_ref": str(runtime_trace.get("graph_ref") or ""),
                "latest_checkpoint_ref": str(runtime_trace.get("coordination_checkpoint_ref") or ""),
                "diagnostics": {
                    "coordination_flow": coordination_flow,
                    "task_graph_scheduler_state": dict(runtime_trace.get("task_graph_scheduler_state") or {}),
                },
            }
        ]
    task_run_id = str(result.get("task_run_id") or "")
    if not task_run_id:
        task_run_id = _task_run_id_from_events(events)
    return {
        "task_run": {"task_run_id": task_run_id},
        "events": events,
        "latest_checkpoint": _latest_checkpoint_from_turn_payload(payload, events),
        "coordination_runs": coordination_runs,
    }


def _collect_event_candidates(events: list[dict[str, Any]], *, task_run_id: str) -> list[EvidenceCandidate]:
    candidates: list[EvidenceCandidate] = []
    total_events = len(events)
    seen_tool_calls: set[str] = set()
    seen_delegations: set[str] = set()
    for index, event in enumerate(events, start=1):
        event_type = str(event.get("event_type") or "")
        payload = dict(event.get("payload") or {})
        score = score_runtime_event(event, total_events=total_events, index=index)
        tool_name = _tool_name(event) if event_type == "tool_call_requested" else ""
        event_id = str(event.get("event_id") or f"{task_run_id}:{index}")
        summary = _event_summary(event_type, payload)
        source_ref = f"{task_run_id}#{int(event.get('offset') or index)}"
        metadata: dict[str, Any] = {"offset": int(event.get("offset") or index)}
        if tool_name:
            metadata["tool_name"] = tool_name
        if event_type == "agent_delegation_requested":
            request = dict(payload.get("agent_delegation_request") or {})
            request_payload = dict(request.get("payload") or {})
            if request.get("target_agent_id"):
                metadata["target_agent_id"] = str(request.get("target_agent_id") or "")
            if request.get("delegation_kind"):
                metadata["delegation_kind"] = str(request.get("delegation_kind") or "")
            if request_payload.get("source_kind"):
                metadata["source_kind"] = str(request_payload.get("source_kind") or "")
        candidate = EvidenceCandidate(
            candidate_id=f"evcand:{event_id}",
            source_kind="runtime_event",
            source_ref=source_ref,
            subject_type="task_run",
            subject_id=task_run_id,
            event_type=event_type,
            time_index=index,
            summary=summary,
            raw_ref=event_id,
            metadata=metadata,
            score=score,
        )
        if event_type == "tool_call_requested":
            if tool_name and tool_name in seen_tool_calls:
                continue
            if tool_name:
                seen_tool_calls.add(tool_name)
        if event_type == "agent_delegation_requested":
            target_agent_id = str(dict(payload.get("agent_delegation_request") or {}).get("target_agent_id") or "")
            if target_agent_id and target_agent_id in seen_delegations:
                continue
            if target_agent_id:
                seen_delegations.add(target_agent_id)
        candidates.append(candidate)

    delegated = any(item.event_type == "agent_delegation_requested" for item in candidates)
    tool_delegate = any(item.event_type == "tool_call_requested" and _tool_name_from_candidate(item) == "delegate_to_agent" for item in candidates)
    if not delegated and not tool_delegate and events:
        candidates.append(
            EvidenceCandidate(
                candidate_id=f"evcand:{task_run_id}:negative:delegation",
                source_kind="negative_observation",
                source_ref=task_run_id,
                subject_type="task_run",
                subject_id=task_run_id,
                event_type="absent:agent_delegation_requested",
                time_index=total_events + 1,
                summary="未观察到 agent_delegation_requested，说明本轮并未发生子 Agent 委派。",
                raw_ref="negative:agent_delegation_requested",
                metadata={"absence_of": "agent_delegation_requested"},
                score=score_negative_observation(weight=1.0),
            )
        )
    return candidates


def _collect_coordination_candidates(coordination_runs: list[dict[str, Any]], *, task_run_id: str) -> list[EvidenceCandidate]:
    candidates: list[EvidenceCandidate] = []
    for index, run_payload in enumerate(coordination_runs, start=1):
        coordination_run_id = str(run_payload.get("coordination_run_id") or "")
        diagnostics = dict(run_payload.get("diagnostics") or {})
        scheduler_state = _coordination_scheduler_state(run_payload)
        coordination_flow = dict(
            run_payload.get("coordination_flow")
            or diagnostics.get("coordination_flow")
            or {}
        )
        checkpoint_ref = _coordination_checkpoint_ref(run_payload)
        failing_nodes = _coordination_failing_nodes(scheduler_state)
        summary_parts = [
            f"coordination_run={coordination_run_id}",
            f"status={run_payload.get('status') or ''}",
        ]
        if checkpoint_ref:
            summary_parts.append(f"checkpoint={checkpoint_ref}")
        if failing_nodes:
            summary_parts.append(f"failing_nodes={','.join(failing_nodes[:3])}")
        current_stage = str(coordination_flow.get("current_stage_id") or "")
        if current_stage:
            summary_parts.append(f"stage={current_stage}")
        candidates.append(
            EvidenceCandidate(
                candidate_id=f"evcand:{task_run_id or coordination_run_id}:coordination:{index}",
                source_kind="coordination_run",
                source_ref=coordination_run_id,
                subject_type="task_graph",
                subject_id=coordination_run_id or task_run_id,
                event_type="coordination_recovery_boundary",
                time_index=index,
                summary="; ".join(item for item in summary_parts if item),
                raw_ref=coordination_run_id,
                metadata={
                    "coordination_run_id": coordination_run_id,
                    "checkpoint_ref": checkpoint_ref,
                    "current_stage_id": current_stage,
                    "failing_nodes": failing_nodes,
                    "graph_ref": str(run_payload.get("graph_ref") or ""),
                },
                score=score_runtime_event(
                    {"event_type": "scheduler_evaluated", "payload": run_payload},
                    total_events=max(len(coordination_runs), 1),
                    index=index,
                ),
            )
        )
    return candidates


def _checkpoint_candidate(checkpoint: dict[str, Any], *, task_run_id: str) -> EvidenceCandidate:
    loop_state = dict(checkpoint.get("loop_state") or {})
    return EvidenceCandidate(
        candidate_id=f"evcand:{task_run_id}:checkpoint:{checkpoint.get('checkpoint_id') or 'latest'}",
        source_kind="checkpoint",
        source_ref=str(checkpoint.get("checkpoint_id") or ""),
        subject_type="task_run",
        subject_id=task_run_id,
        event_type="checkpoint_written",
        time_index=int(checkpoint.get("event_offset") or 0),
        summary=f"checkpoint={checkpoint.get('checkpoint_id') or ''}; status={loop_state.get('status') or ''}",
        raw_ref=str(checkpoint.get("checkpoint_id") or ""),
        metadata={"event_offset": int(checkpoint.get("event_offset") or 0)},
        score=score_runtime_event({"event_type": "checkpoint_written", "payload": checkpoint}, total_events=1, index=1),
    )


def _build_recovery_handles(
    events: list[dict[str, Any]],
    *,
    latest_checkpoint: dict[str, Any],
    coordination_runs: list[dict[str, Any]],
) -> list[RecoveryHandle]:
    handles: list[RecoveryHandle] = []
    if latest_checkpoint.get("checkpoint_id"):
        loop_state = dict(latest_checkpoint.get("loop_state") or {})
        status = str(loop_state.get("status") or latest_checkpoint.get("status") or "")
        handles.append(
            RecoveryHandle(
                kind="checkpoint",
                ref=str(latest_checkpoint.get("checkpoint_id") or ""),
                safe_to_resume=bool(status in {"running", "blocked"}),
                side_effect_replay_risk="low",
                metadata={
                    "event_offset": int(latest_checkpoint.get("event_offset") or 0),
                    "status": status,
                    "source": str(latest_checkpoint.get("source") or "runtime_checkpoint"),
                },
            )
        )
    for run_payload in coordination_runs:
        coordination_run_id = str(run_payload.get("coordination_run_id") or "")
        checkpoint_ref = _coordination_checkpoint_ref(run_payload)
        scheduler_state = _coordination_scheduler_state(run_payload)
        diagnostics = dict(run_payload.get("diagnostics") or {})
        coordination_flow = dict(run_payload.get("coordination_flow") or diagnostics.get("coordination_flow") or {})
        failing_nodes = _coordination_failing_nodes(scheduler_state)
        active_node_id = _first_nonempty(
            scheduler_state.get("active_node_id"),
            dict(run_payload.get("langgraph_runtime_state") or {}).get("active_node_id"),
            dict(diagnostics.get("langgraph_runtime_state") or {}).get("active_node_id"),
            coordination_flow.get("current_stage_id"),
        )
        if checkpoint_ref:
            handles.append(
                RecoveryHandle(
                    kind="coordination_checkpoint",
                    ref=checkpoint_ref,
                    safe_to_resume=bool(str(run_payload.get("status") or "") in {"running", "blocked"}),
                    side_effect_replay_risk="medium",
                    metadata={
                        "coordination_run_id": coordination_run_id,
                        "graph_ref": str(run_payload.get("graph_ref") or ""),
                        "current_stage_id": str(coordination_flow.get("current_stage_id") or ""),
                        "active_node_id": str(active_node_id or ""),
                    },
                )
            )
        for node_id in failing_nodes[:3]:
            handles.append(
                RecoveryHandle(
                    kind="task_graph_node_resume_candidate",
                    ref=str(node_id),
                    safe_to_resume=False,
                    side_effect_replay_risk="high",
                    metadata={
                        "coordination_run_id": coordination_run_id,
                        "checkpoint_ref": checkpoint_ref,
                        "reason": "node_failed_or_blocked",
                    },
                )
            )
    last_tool = next((item for item in reversed(events) if str(item.get("event_type") or "") == "tool_result_received"), None)
    if last_tool is not None:
        handles.append(
            RecoveryHandle(
                kind="tool_result_boundary",
                ref=str(last_tool.get("event_id") or ""),
                safe_to_resume=False,
                side_effect_replay_risk="medium",
            )
        )
    return handles


def _latest_checkpoint_from_trace(trace: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    explicit = dict(trace.get("latest_checkpoint") or {})
    return _latest_checkpoint_from_events(events, explicit=explicit)


def _latest_checkpoint_from_turn_payload(payload: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    explicit = (
        dict(payload.get("latest_checkpoint") or {})
        or dict(payload.get("checkpoint") or {})
        or dict(dict(payload.get("result") or {}).get("latest_checkpoint") or {})
        or dict(dict(payload.get("result") or {}).get("checkpoint") or {})
    )
    return _latest_checkpoint_from_events(events, explicit=explicit)


def _latest_checkpoint_from_events(events: list[dict[str, Any]], *, explicit: dict[str, Any]) -> dict[str, Any]:
    if explicit.get("checkpoint_id"):
        return explicit
    for event in reversed(events):
        if str(event.get("event_type") or "") != "checkpoint_written":
            continue
        payload = dict(event.get("payload") or {})
        if not payload.get("checkpoint_id"):
            continue
        result = dict(payload)
        result.setdefault("event_offset", int(event.get("offset") or payload.get("event_offset") or 0))
        result.setdefault("source", "runtime_event.checkpoint_written")
        return result
    return explicit


def _task_run_id_from_events(events: list[dict[str, Any]]) -> str:
    for event in events:
        task_run_id = str(event.get("task_run_id") or "")
        if task_run_id:
            return task_run_id
    return ""


def _coordination_checkpoint_ref(run_payload: dict[str, Any]) -> str:
    diagnostics = dict(run_payload.get("diagnostics") or {})
    checkpoint = dict(
        run_payload.get("coordination_checkpoint")
        or diagnostics.get("coordination_checkpoint")
        or {}
    )
    return str(
        checkpoint.get("checkpoint_id")
        or run_payload.get("latest_checkpoint_ref")
        or diagnostics.get("langgraph_checkpoint_ref")
        or diagnostics.get("coordination_checkpoint_ref")
        or ""
    )


def _coordination_scheduler_state(run_payload: dict[str, Any]) -> dict[str, Any]:
    diagnostics = dict(run_payload.get("diagnostics") or {})
    langgraph_state = dict(run_payload.get("langgraph_runtime_state") or diagnostics.get("langgraph_runtime_state") or {})
    return dict(
        run_payload.get("task_graph_scheduler_state")
        or diagnostics.get("task_graph_scheduler_state")
        or langgraph_state.get("task_graph_scheduler_state")
        or {}
    )


def _coordination_failing_nodes(scheduler_state: dict[str, Any]) -> list[str]:
    nodes: list[str] = []
    nodes.extend(str(item) for item in list(scheduler_state.get("failed_nodes") or []) if str(item))
    nodes.extend(str(item) for item in list(scheduler_state.get("blocked_nodes") or []) if str(item))
    node_statuses = dict(scheduler_state.get("node_statuses") or {})
    for node_id, status in node_statuses.items():
        if isinstance(status, dict):
            node_status = str(status.get("status") or "")
        else:
            node_status = str(status or "")
        if node_status in {"failed", "blocked"}:
            nodes.append(str(node_id))
    return list(dict.fromkeys(nodes))


def _node_status_value(status: Any) -> str:
    if isinstance(status, dict):
        return str(status.get("status") or "")
    return str(status or "")


def _first_nonempty(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _test_handles_from_trace(trace: dict[str, Any]) -> list[dict[str, Any]]:
    task_run = dict(trace.get("task_run") or {})
    task_run_id = str(task_run.get("task_run_id") or "")
    if not task_run_id:
        return []
    return [
        {
            "kind": "targeted_regression",
            "ref": task_run_id,
            "recommended_assertions": ["loop.completed", "tool.pairing_ok"],
        }
    ]


def _verdict_from_events(events: list[dict[str, Any]]) -> str:
    if any(str(item.get("event_type") or "") == "loop_error" for item in events):
        return "failed"
    terminal = next((item for item in reversed(events) if str(item.get("event_type") or "") == "loop_terminal"), {})
    return str(dict(terminal.get("payload") or {}).get("status") or "unknown")


def _confidence_from_events(candidates: list[EvidenceCandidate]) -> float:
    if not candidates:
        return 0.0
    top = max(item.score.total for item in candidates)
    return round(min(1.0, top / 8.0), 4)


def _summary_from_events(events: list[dict[str, Any]], *, semantic_hint: str = "") -> str:
    if semantic_hint.strip():
        return semantic_hint.strip()
    last = next((item for item in reversed(events) if str(item.get("event_type") or "") in {"loop_error", "loop_terminal", "checkpoint_written"}), None)
    if last is None:
        return "已抽取运行证据。"
    return _event_summary(str(last.get("event_type") or ""), dict(last.get("payload") or {}))


def _event_summary(event_type: str, payload: dict[str, Any]) -> str:
    if event_type == "operation_gate_checked":
        gate = dict(payload.get("gate") or {})
        return f"operation={gate.get('operation_id') or ''}; allowed={gate.get('allowed') is True}; reason={gate.get('reason') or ''}"
    if event_type == "commit_gate_checked":
        gate = dict(payload.get("commit_decision") or payload.get("commit_gate") or {})
        return f"commit={gate.get('commit_type') or ''}; allowed={gate.get('commit_allowed') is True}; reason={gate.get('reason') or ''}"
    if event_type == "tool_call_requested":
        action = dict(payload.get("action_request") or {})
        action_payload = dict(action.get("payload") or {})
        return f"tool={action_payload.get('tool_name') or ''}"
    if event_type == "tool_result_received":
        observation = dict(payload.get("observation") or {})
        return f"tool_result={observation.get('observation_type') or 'tool_result'}; chars={payload.get('content_chars') or 0}"
    if event_type == "agent_delegation_requested":
        request = dict(payload.get("agent_delegation_request") or {})
        return f"delegate={request.get('target_agent_id') or ''}; kind={request.get('delegation_kind') or ''}"
    if event_type == "agent_delegation_result_created":
        result = dict(payload.get("agent_delegation_result") or {})
        return f"delegation_result={result.get('status') or ''}; target={result.get('target_agent_id') or ''}"
    if event_type == "checkpoint_written":
        return f"checkpoint={payload.get('checkpoint_id') or ''}; offset={payload.get('event_offset') or 0}"
    if event_type == "loop_error":
        return str(payload.get("error") or payload.get("message") or "loop error")
    if event_type == "loop_terminal":
        return f"status={payload.get('status') or ''}; reason={payload.get('terminal_reason') or ''}"
    return event_type


def _tool_name(event: dict[str, Any]) -> str:
    action_request = dict(event.get("payload") or {}).get("action_request") or {}
    action_payload = dict(action_request.get("payload") or {})
    return str(action_payload.get("tool_name") or "")


def _tool_name_from_candidate(candidate: EvidenceCandidate) -> str:
    if candidate.event_type != "tool_call_requested":
        return ""
    return str(candidate.metadata.get("tool_name") or "")
