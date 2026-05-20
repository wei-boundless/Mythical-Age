from __future__ import annotations

from collections import Counter
from typing import Any

from health_system.evidence_models import EvidenceCandidate, EvidenceScore, RecoveryHandle
from health_system.evidence_packet_builder import build_evidence_packet


def build_task_graph_health_projection(
    monitor: dict[str, Any],
    *,
    trace: dict[str, Any] | None = None,
    question: str = "",
    selected_evidence_limit: int = 10,
) -> dict[str, Any]:
    """Build a health-system projection from the canonical TaskGraph monitor."""

    monitor_payload = dict(monitor or {})
    trace_payload = dict(trace or {})
    task_run_id = str(monitor_payload.get("task_run_id") or "")
    coordination_run_id = str(monitor_payload.get("coordination_run_id") or "")
    graph = dict(monitor_payload.get("graph") or {})
    runtime = dict(monitor_payload.get("runtime") or {})
    state = dict(monitor_payload.get("state") or {})
    temporal = dict(monitor_payload.get("temporal") or {})
    batch_lifecycle = dict(monitor_payload.get("batch_lifecycle") or {})
    batch_dispatcher = dict(monitor_payload.get("batch_dispatcher") or {})

    issues = _collect_issues(
        monitor=monitor_payload,
        runtime=runtime,
        state=state,
        temporal=temporal,
        batch_lifecycle=batch_lifecycle,
        batch_dispatcher=batch_dispatcher,
    )
    issue_counts = Counter(str(item.get("severity") or "info") for item in issues)
    status = _projection_status(issues)
    recovery_handles = _recovery_handles(
        monitor=monitor_payload,
        runtime=runtime,
        state=state,
        batch_lifecycle=batch_lifecycle,
        issues=issues,
    )
    evidence_candidates = [
        _issue_evidence_candidate(
            issue,
            index=index,
            task_run_id=task_run_id,
            coordination_run_id=coordination_run_id,
        )
        for index, issue in enumerate(issues, start=1)
    ]
    trace_summary = _trace_summary(trace_payload)
    if not evidence_candidates and (task_run_id or coordination_run_id):
        evidence_candidates.append(
            EvidenceCandidate(
                candidate_id=f"tgh:{task_run_id or coordination_run_id}:monitor:healthy",
                source_kind="task_graph_run_monitor",
                source_ref=coordination_run_id or task_run_id,
                subject_type="task_graph",
                subject_id=str(graph.get("graph_id") or graph.get("title") or coordination_run_id or task_run_id),
                event_type="task_graph_monitor_healthy",
                time_index=1,
                summary="TaskGraph monitor did not report blocking health issues.",
                raw_ref=coordination_run_id or task_run_id,
                metadata={"graph": graph, "runtime_status": str(runtime.get("status") or "")},
                score=EvidenceScore(semantic_score=1.0, novelty_score=0.5),
            )
        )

    packet_question = question.strip() or "What TaskGraph runtime health risks are visible in this monitor?"
    evidence_packet = build_evidence_packet(
        question=packet_question,
        candidates=evidence_candidates,
        verdict=status,
        confidence=_confidence(issues, evidence_candidates),
        summary=_projection_summary(status=status, issues=issues, graph=graph, runtime=runtime),
        recovery_handles=recovery_handles,
        test_handles=_test_handles(task_run_id),
        selected_limit=selected_evidence_limit,
    ).to_dict()
    return {
        "authority": "health_system.task_graph_health_projection",
        "task_run_id": task_run_id,
        "coordination_run_id": coordination_run_id,
        "graph": graph,
        "status": status,
        "summary": {
            "issue_count": len(issues),
            "critical_count": int(issue_counts.get("critical", 0)),
            "error_count": int(issue_counts.get("error", 0)),
            "warning_count": int(issue_counts.get("warning", 0)),
            "info_count": int(issue_counts.get("info", 0)),
            "batch_available": bool(batch_lifecycle.get("available") is True),
            "dispatcher_available": bool(batch_dispatcher.get("available") is True),
            "runtime_status": str(runtime.get("status") or ""),
            "terminal_status": str(runtime.get("terminal_status") or ""),
            "trace_event_count": int(trace_summary.get("event_count") or 0),
            "coordination_run_count": int(trace_summary.get("coordination_run_count") or 0),
        },
        "issues": issues,
        "batch_health": _batch_health(batch_lifecycle=batch_lifecycle, batch_dispatcher=batch_dispatcher),
        "recovery_handles": [item.to_dict() for item in recovery_handles],
        "evidence_packet": evidence_packet,
        "source_refs": {
            "monitor": str(monitor_payload.get("authority") or ""),
            "task_run_id": task_run_id,
            "coordination_run_id": coordination_run_id,
            "checkpoint_ref": str(runtime.get("checkpoint_ref") or ""),
            "task_checkpoint_ref": str(runtime.get("task_checkpoint_ref") or ""),
        },
    }


def _collect_issues(
    *,
    monitor: dict[str, Any],
    runtime: dict[str, Any],
    state: dict[str, Any],
    temporal: dict[str, Any],
    batch_lifecycle: dict[str, Any],
    batch_dispatcher: dict[str, Any],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    for raw in list(dict(monitor.get("health") or {}).get("issues") or []):
        item = dict(raw or {})
        code = str(item.get("code") or "monitor_health_issue")
        target_id = str(item.get("target_id") or "")
        _append_issue(
            issues,
            seen,
            severity=_normalize_severity(str(item.get("severity") or "warning")),
            code=code,
            subject_type=_subject_type_for_monitor_issue(code, target_id),
            subject_id=target_id or str(dict(monitor.get("graph") or {}).get("graph_id") or ""),
            summary=str(item.get("message") or code),
            evidence_refs=[target_id] if target_id else [],
            recommended_action=_recommended_action_for_code(code),
            metadata={"source": "monitor.health.issues", "raw_issue": item},
        )

    failure = dict(runtime.get("failure") or {})
    runtime_status = str(runtime.get("status") or "")
    terminal_status = str(runtime.get("terminal_status") or "")
    if failure or runtime_status in {"failed", "aborted", "killed"} or terminal_status in {"failed", "aborted", "killed"}:
        _append_issue(
            issues,
            seen,
            severity="critical",
            code="runtime_failure",
            subject_type="task_graph_node" if str(failure.get("stage_id") or "") else "task_graph_run",
            subject_id=str(failure.get("stage_id") or runtime.get("active_node_id") or monitor.get("task_run_id") or ""),
            summary=str(failure.get("message") or "TaskGraph runtime failed."),
            evidence_refs=[str(ref) for ref in (failure.get("observation_ref"), failure.get("step_id")) if str(ref or "")],
            recommended_action="Inspect failed node diagnostics and decide whether to retry, rewind, or rebuild the request.",
            metadata={"failure": failure, "runtime_status": runtime_status, "terminal_status": terminal_status},
        )

    for violation in [dict(item) for item in list(temporal.get("violations") or []) if isinstance(item, dict)]:
        code = str(violation.get("code") or "timeline_violation")
        _append_issue(
            issues,
            seen,
            severity="critical",
            code=code,
            subject_type="task_graph_timeline",
            subject_id=str(violation.get("target_id") or temporal.get("active_node_id") or ""),
            summary=str(violation.get("message") or "TaskGraph temporal boundary is invalid."),
            evidence_refs=[str(temporal.get("active_request_id") or ""), str(temporal.get("active_execution_permit_id") or "")],
            recommended_action="Pause automatic progression and verify the active execution permit before resuming.",
            metadata={"temporal": temporal, "violation": violation},
        )

    running_nodes = [str(item) for item in list(state.get("running_node_ids") or []) if str(item)]
    active_node_id = str(runtime.get("active_node_id") or temporal.get("active_node_id") or "")
    current_request = dict(monitor.get("current_node_execution_request") or monitor.get("current_stage_execution_request") or {})
    if (running_nodes or active_node_id) and not current_request and runtime_status in {"running", "waiting", ""}:
        _append_issue(
            issues,
            seen,
            severity="warning",
            code="missing_runtime_request",
            subject_type="task_graph_node",
            subject_id=active_node_id or ",".join(running_nodes),
            summary="A running TaskGraph node has no visible standard execution request.",
            evidence_refs=running_nodes,
            recommended_action="Rebuild or inspect the node execution request before dispatching more work.",
            metadata={"running_node_ids": running_nodes, "active_node_id": active_node_id},
        )

    _collect_batch_issues(
        issues=issues,
        seen=seen,
        batch_lifecycle=batch_lifecycle,
        batch_dispatcher=batch_dispatcher,
    )
    return sorted(issues, key=_issue_sort_key)


def _collect_batch_issues(
    *,
    issues: list[dict[str, Any]],
    seen: set[tuple[str, str, str]],
    batch_lifecycle: dict[str, Any],
    batch_dispatcher: dict[str, Any],
) -> None:
    if batch_lifecycle.get("available") is not True:
        return
    summary = dict(batch_lifecycle.get("summary") or {})
    diagnostics = dict(batch_lifecycle.get("diagnostics") or {})
    failed_count = _int(summary.get("failed_batch_count"))
    if failed_count > 0:
        _append_issue(
            issues,
            seen,
            severity="critical",
            code="batch_failed",
            subject_type="task_graph_batch",
            subject_id=str(batch_lifecycle.get("graph_id") or ""),
            summary=f"{failed_count} TaskGraph batch item(s) failed.",
            evidence_refs=list(batch_lifecycle.get("failed_batch_ids") or []),
            recommended_action="Inspect failed batch verdicts and decide whether to rewind, repair, or stop the run.",
            metadata={"summary": summary},
        )

    last_ignored = dict(diagnostics.get("last_transition_ignored") or {})
    if str(last_ignored.get("reason") or "") == "batch_execution_identity_not_found":
        _append_issue(
            issues,
            seen,
            severity="error",
            code="batch_execution_identity_ignored",
            subject_type="task_graph_execution",
            subject_id=str(
                last_ignored.get("batch_execution_id")
                or last_ignored.get("request_id")
                or last_ignored.get("dispatch_event_id")
                or "unknown"
            ),
            summary="A batch result was ignored because its execution identity did not match any active batch execution.",
            evidence_refs=[
                str(item)
                for item in (
                    last_ignored.get("request_id"),
                    last_ignored.get("dispatch_event_id"),
                    last_ignored.get("batch_execution_id"),
                )
                if str(item or "")
            ],
            recommended_action="Reject the stale result and inspect the dispatch identity before accepting any batch output.",
            metadata={"last_transition_ignored": last_ignored},
        )

    running_batch_count = _int(summary.get("running_batch_count"))
    running_execution_count = _int(summary.get("running_execution_instance_count"))
    if running_batch_count != running_execution_count:
        _append_issue(
            issues,
            seen,
            severity="error",
            code="batch_execution_inconsistent",
            subject_type="task_graph_batch",
            subject_id=str(batch_lifecycle.get("graph_id") or ""),
            summary="Running batch count does not match running batch execution instance count.",
            evidence_refs=list(batch_lifecycle.get("running_batch_ids") or []),
            recommended_action="Inspect batch lifecycle state before dispatching or committing more batch results.",
            metadata={"summary": summary},
        )

    if batch_dispatcher.get("available") is True:
        for node in [dict(item) for item in list(batch_dispatcher.get("nodes") or []) if isinstance(item, dict)]:
            ready_ids = [str(item) for item in list(node.get("ready_batch_ids") or []) if str(item)]
            available_slots = _int(node.get("available_slot_count"))
            active_count = _int(node.get("active_execution_count"))
            max_parallel = _int(node.get("max_parallel_batches"), fallback=1)
            active_execution_ids = [str(item) for item in list(node.get("active_execution_ids") or []) if str(item)]
            if ready_ids and available_slots == 0 and active_count >= max_parallel:
                _append_issue(
                    issues,
                    seen,
                    severity="info",
                    code="batch_dispatch_at_capacity",
                    subject_type="task_graph_node",
                    subject_id=str(node.get("node_id") or ""),
                    summary="Ready batches exist, but the node is currently at its configured parallel dispatch capacity.",
                    evidence_refs=ready_ids,
                    recommended_action="Wait for running batch executions to finish or raise the node concurrency policy.",
                    metadata={"dispatcher_node": node},
                )
            if active_count != len(active_execution_ids):
                _append_issue(
                    issues,
                    seen,
                    severity="warning",
                    code="batch_dispatcher_execution_count_mismatch",
                    subject_type="task_graph_node",
                    subject_id=str(node.get("node_id") or ""),
                    summary="Batch dispatcher active execution count does not match visible active execution ids.",
                    evidence_refs=active_execution_ids,
                    recommended_action="Refresh the monitor and inspect batch execution instance attachment.",
                    metadata={"dispatcher_node": node},
                )


def _append_issue(
    issues: list[dict[str, Any]],
    seen: set[tuple[str, str, str]],
    *,
    severity: str,
    code: str,
    subject_type: str,
    subject_id: str,
    summary: str,
    evidence_refs: list[str] | None = None,
    recommended_action: str = "",
    metadata: dict[str, Any] | None = None,
) -> None:
    normalized = {
        "severity": _normalize_severity(severity),
        "code": code or "task_graph_health_issue",
        "subject_type": subject_type or "task_graph",
        "subject_id": subject_id or "unknown",
    }
    key = (normalized["code"], normalized["subject_type"], normalized["subject_id"])
    if key in seen:
        return
    seen.add(key)
    issue_id = "tgh:{subject_type}:{subject_id}:{code}".format(**normalized)
    issues.append(
        {
            "issue_id": _safe_issue_id(issue_id),
            **normalized,
            "summary": summary or normalized["code"],
            "evidence_refs": [str(item) for item in list(evidence_refs or []) if str(item)],
            "recommended_action": recommended_action,
            "metadata": dict(metadata or {}),
            "authority": "health_system.task_graph_health_issue",
        }
    )


def _issue_evidence_candidate(
    issue: dict[str, Any],
    *,
    index: int,
    task_run_id: str,
    coordination_run_id: str,
) -> EvidenceCandidate:
    subject_type = str(issue.get("subject_type") or "task_graph")
    subject_id = str(issue.get("subject_id") or "unknown")
    code = str(issue.get("code") or "task_graph_health_issue")
    return EvidenceCandidate(
        candidate_id=f"evcand:tgh:{index}:{_safe_issue_id(subject_type)}:{_safe_issue_id(subject_id)}:{_safe_issue_id(code)}",
        source_kind="task_graph_run_monitor",
        source_ref=coordination_run_id or task_run_id,
        subject_type=subject_type,
        subject_id=subject_id,
        event_type=code,
        time_index=index,
        summary=str(issue.get("summary") or code),
        raw_ref=str(issue.get("issue_id") or ""),
        metadata={
            "severity": str(issue.get("severity") or ""),
            "recommended_action": str(issue.get("recommended_action") or ""),
            "evidence_refs": list(issue.get("evidence_refs") or []),
            **dict(issue.get("metadata") or {}),
        },
        score=_issue_score(issue),
    )


def _issue_score(issue: dict[str, Any]) -> EvidenceScore:
    severity = str(issue.get("severity") or "info")
    if severity == "critical":
        return EvidenceScore(causal_score=3.0, decision_score=2.0, recovery_score=2.0, temporal_score=1.5)
    if severity == "error":
        return EvidenceScore(causal_score=2.5, decision_score=1.5, recovery_score=1.5, temporal_score=1.0)
    if severity == "warning":
        return EvidenceScore(causal_score=1.5, decision_score=1.0, recovery_score=0.5, temporal_score=0.5)
    return EvidenceScore(semantic_score=1.0, novelty_score=0.5)


def _recovery_handles(
    *,
    monitor: dict[str, Any],
    runtime: dict[str, Any],
    state: dict[str, Any],
    batch_lifecycle: dict[str, Any],
    issues: list[dict[str, Any]],
) -> list[RecoveryHandle]:
    handles: list[RecoveryHandle] = []
    has_critical = any(str(item.get("severity") or "") == "critical" for item in issues)
    runtime_status = str(runtime.get("status") or "")
    safe_runtime_status = runtime_status in {"running", "waiting", "blocked"}
    checkpoint_ref = str(runtime.get("checkpoint_ref") or "")
    if checkpoint_ref:
        handles.append(
            RecoveryHandle(
                kind="coordination_checkpoint",
                ref=checkpoint_ref,
                safe_to_resume=bool(safe_runtime_status and not has_critical),
                side_effect_replay_risk="medium",
                metadata={
                    "task_run_id": str(monitor.get("task_run_id") or ""),
                    "coordination_run_id": str(monitor.get("coordination_run_id") or ""),
                    "active_node_id": str(runtime.get("active_node_id") or ""),
                },
            )
        )
    task_checkpoint_ref = str(runtime.get("task_checkpoint_ref") or "")
    if task_checkpoint_ref:
        handles.append(
            RecoveryHandle(
                kind="checkpoint",
                ref=task_checkpoint_ref,
                safe_to_resume=bool(safe_runtime_status and not has_critical),
                side_effect_replay_risk="low" if not has_critical else "medium",
                metadata={"task_run_id": str(monitor.get("task_run_id") or "")},
            )
        )
    for node_id in _unique_strings(
        [
            *list(state.get("failed_node_ids") or []),
            *list(state.get("blocked_node_ids") or []),
            str(runtime.get("active_node_id") or ""),
        ]
    )[:6]:
        handles.append(
            RecoveryHandle(
                kind="task_graph_node_resume_candidate",
                ref=node_id,
                safe_to_resume=False,
                side_effect_replay_risk="high" if node_id in set(state.get("failed_node_ids") or []) else "medium",
                metadata={
                    "coordination_run_id": str(monitor.get("coordination_run_id") or ""),
                    "checkpoint_ref": checkpoint_ref,
                },
            )
        )
    if batch_lifecycle.get("available") is True:
        for instance in [dict(item) for item in list(batch_lifecycle.get("execution_instances") or []) if isinstance(item, dict)]:
            if str(instance.get("status") or "") not in {"running", "repairing"}:
                continue
            execution_id = str(instance.get("execution_id") or "")
            if not execution_id:
                continue
            handles.append(
                RecoveryHandle(
                    kind="task_graph_batch_execution_boundary",
                    ref=execution_id,
                    safe_to_resume=False,
                    side_effect_replay_risk="medium",
                    metadata={
                        "batch_id": str(instance.get("batch_id") or ""),
                        "node_id": str(instance.get("node_id") or ""),
                        "request_id": str(instance.get("request_id") or ""),
                    },
                )
            )
    return _dedupe_handles(handles)


def _batch_health(*, batch_lifecycle: dict[str, Any], batch_dispatcher: dict[str, Any]) -> dict[str, Any]:
    lifecycle_summary = dict(batch_lifecycle.get("summary") or {})
    dispatcher_summary = dict(batch_dispatcher.get("summary") or {})
    return {
        "available": bool(batch_lifecycle.get("available") is True),
        "graph_id": str(batch_lifecycle.get("graph_id") or batch_dispatcher.get("graph_id") or ""),
        "lifecycle_summary": lifecycle_summary,
        "dispatcher_summary": dispatcher_summary,
        "ready_batch_ids": list(batch_lifecycle.get("ready_batch_ids") or []),
        "running_batch_ids": list(batch_lifecycle.get("running_batch_ids") or []),
        "committed_batch_ids": list(batch_lifecycle.get("committed_batch_ids") or []),
        "failed_batch_ids": list(batch_lifecycle.get("failed_batch_ids") or []),
        "dispatcher_nodes": [dict(item) for item in list(batch_dispatcher.get("nodes") or []) if isinstance(item, dict)],
        "diagnostics": dict(batch_lifecycle.get("diagnostics") or {}),
        "authority": "health_system.task_graph_batch_health",
    }


def _projection_status(issues: list[dict[str, Any]]) -> str:
    severities = {str(item.get("severity") or "") for item in issues}
    if severities.intersection({"critical", "error"}):
        return "failed"
    if "warning" in severities:
        return "degraded"
    if issues:
        return "observed"
    return "healthy"


def _projection_summary(
    *,
    status: str,
    issues: list[dict[str, Any]],
    graph: dict[str, Any],
    runtime: dict[str, Any],
) -> str:
    graph_label = str(graph.get("title") or graph.get("graph_id") or "TaskGraph")
    if not issues:
        return f"{graph_label} is healthy according to the current TaskGraph monitor."
    first = issues[0]
    return (
        f"{graph_label} health is {status}; "
        f"{len(issues)} issue(s) found; "
        f"top issue={first.get('code')}; "
        f"runtime_status={runtime.get('status') or 'unknown'}."
    )


def _confidence(issues: list[dict[str, Any]], candidates: list[EvidenceCandidate]) -> float:
    if not candidates:
        return 0.0
    if any(str(item.get("severity") or "") in {"critical", "error"} for item in issues):
        return 0.9
    if issues:
        return 0.75
    return 0.6


def _test_handles(task_run_id: str) -> list[dict[str, Any]]:
    if not task_run_id:
        return []
    return [
        {
            "kind": "task_graph_health_regression",
            "ref": task_run_id,
            "recommended_assertions": [
                "task_graph.monitor.available",
                "task_graph.health.no_critical_issues",
                "task_graph.batch.identity_consistent",
            ],
        }
    ]


def _trace_summary(trace: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_count": len(list(trace.get("events") or [])),
        "coordination_run_count": len(list(trace.get("coordination_runs") or [])),
    }


def _subject_type_for_monitor_issue(code: str, target_id: str) -> str:
    normalized = f"{code} {target_id}".lower()
    if "edge" in normalized:
        return "task_graph_edge"
    if "timeline" in normalized or "temporal" in normalized or "permit" in normalized:
        return "task_graph_timeline"
    if "node" in normalized or target_id:
        return "task_graph_node"
    return "task_graph"


def _recommended_action_for_code(code: str) -> str:
    normalized = str(code or "").lower()
    if "permit" in normalized or "temporal" in normalized or "timeline" in normalized:
        return "Pause progression and verify the timeline boundary before resuming."
    if "missing" in normalized:
        return "Rebuild the missing runtime object or inspect the compiler output."
    if "edge" in normalized:
        return "Fix the graph topology or edge endpoint binding before publishing or resuming."
    return "Inspect the TaskGraph monitor evidence and decide whether to retry, rewind, or stop."


def _normalize_severity(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"critical", "fatal"}:
        return "critical"
    if normalized in {"error", "failed", "failure"}:
        return "error"
    if normalized in {"warning", "warn"}:
        return "warning"
    return "info"


def _issue_sort_key(issue: dict[str, Any]) -> tuple[int, str, str]:
    priority = {"critical": 0, "error": 1, "warning": 2, "info": 3}.get(str(issue.get("severity") or ""), 4)
    return (priority, str(issue.get("code") or ""), str(issue.get("subject_id") or ""))


def _dedupe_handles(handles: list[RecoveryHandle]) -> list[RecoveryHandle]:
    result: list[RecoveryHandle] = []
    seen: set[tuple[str, str]] = set()
    for handle in handles:
        key = (handle.kind, handle.ref)
        if not handle.ref or key in seen:
            continue
        seen.add(key)
        result.append(handle)
    return result


def _unique_strings(values: list[Any]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _int(value: Any, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _safe_issue_id(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_", ".", ":"} else "_" for char in str(value or ""))[:220]
