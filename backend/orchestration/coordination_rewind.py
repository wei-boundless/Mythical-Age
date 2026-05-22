from __future__ import annotations

import re
import shutil
import time
from pathlib import Path
from typing import Any

from runtime import TaskRun
from runtime.shared.models import AgentRun, CoordinationRun
from task_system.runtime_semantics.review_gate_verdict import review_verdict_blocks_downstream_invalidation

def _mark_rewound_task_run_running(
    *,
    task_run_loop: Any,
    task_run: TaskRun,
    coordination_run: CoordinationRun,
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
    coordination_run: CoordinationRun,
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
    if review_verdict_blocks_downstream_invalidation(verdict):
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

