from __future__ import annotations

from copy import deepcopy
from typing import Any


BATCH_RUNTIME_AUTHORITY = "task_system.batch_lifecycle_runtime_state"


def bootstrap_batch_lifecycle_runtime_state(
    *,
    runtime_spec_payload: dict[str, Any],
    mode: str = "active",
) -> dict[str, Any]:
    diagnostics = _record(runtime_spec_payload.get("diagnostics"))
    split_plans = [
        _record(item)
        for item in list(diagnostics.get("split_plans") or [])
        if isinstance(item, dict)
    ]
    plan_states: list[dict[str, Any]] = []
    batch_states: list[dict[str, Any]] = []
    step_states: list[dict[str, Any]] = []
    merge_states: list[dict[str, Any]] = []
    execution_mode_by_plan: dict[str, str] = {}
    concurrency_by_plan: dict[str, int] = {}
    for plan in split_plans:
        plan_id = _string(plan.get("plan_id"))
        node_id = _string(plan.get("node_id"))
        plan_metadata = _record(plan.get("metadata"))
        child_execution_mode = _string(plan_metadata.get("child_execution_mode"), "sequential")
        execution_mode_by_plan[plan_id] = "parallel" if child_execution_mode == "parallel" else "sequential"
        concurrency_by_plan[plan_id] = _parallel_dispatch_limit(plan_metadata, child_execution_mode=child_execution_mode)
        lifecycle_plans = [
            _record(item)
            for item in list(plan.get("batch_lifecycle_plans") or [])
            if isinstance(item, dict)
        ]
        plan_states.append(
            {
                "plan_id": plan_id,
                "node_id": node_id,
                "status": "ready" if lifecycle_plans else "blocked",
                "unit_kind": _string(plan.get("unit_kind"), "unit"),
                "batch_count": len(lifecycle_plans),
                "committed_batch_count": 0,
                "failed_batch_count": 0,
                "active_batch_id": "",
            }
        )
        for lifecycle_plan in lifecycle_plans:
            batch_id = _string(lifecycle_plan.get("batch_id"))
            batch_states.append(
                {
                    "batch_id": batch_id,
                    "plan_id": plan_id,
                    "node_id": node_id,
                    "sequence_index": _int_value(lifecycle_plan.get("sequence_index"), len(batch_states) + 1),
                    "unit_kind": _string(lifecycle_plan.get("unit_kind"), _string(plan.get("unit_kind"), "unit")),
                    "range": _record(lifecycle_plan.get("range")),
                    "status": (
                        "ready"
                        if child_execution_mode == "parallel"
                        or not any(item.get("node_id") == node_id and item.get("status") == "ready" for item in batch_states)
                        else "planned"
                    ),
                    "attempt_index": 0,
                    "repair_round": 0,
                    "accepted": False,
                    "committed": False,
                    "active_execution_id": "",
                    "last_result_ref": "",
                    "last_verdict": "",
                }
            )
            for step in [_record(item) for item in list(lifecycle_plan.get("steps") or []) if isinstance(item, dict)]:
                step_states.append(
                    {
                        "step_id": _string(step.get("step_id")),
                        "batch_id": batch_id,
                        "plan_id": plan_id,
                        "node_id": node_id,
                        "step_type": _string(step.get("step_type"), "step"),
                        "status": "planned",
                        "sequence_index": _int_value(step.get("sequence_index"), 0),
                        "depends_on": list(step.get("depends_on") or []),
                    }
                )
        merge_plan = _record(plan.get("merge_readiness_plan"))
        if merge_plan:
            merge_states.append(
                {
                    "merge_id": _string(merge_plan.get("merge_id")),
                    "plan_id": plan_id,
                    "node_id": node_id,
                    "status": "waiting_for_commits",
                    "mode": _string(merge_plan.get("mode"), "wait_all_committed"),
                    "ready_condition": _string(merge_plan.get("ready_condition"), "all_batches_committed"),
                    "depends_on_batch_ids": list(merge_plan.get("depends_on_batch_ids") or []),
                    "depends_on_commit_step_ids": list(merge_plan.get("depends_on_commit_step_ids") or []),
                }
            )
    policy_index = {
        _string(plan.get("plan_id")): {
            "acceptance_policy": _record(plan.get("acceptance_policy")),
            "merge_policy": _record(plan.get("merge_policy")),
            "metadata": _record(plan.get("metadata")),
        }
        for plan in split_plans
        if _string(plan.get("plan_id"))
    }
    return _summarize(
        {
            "authority": BATCH_RUNTIME_AUTHORITY,
            "mode": mode or "active",
            "graph_id": _string(runtime_spec_payload.get("graph_id") or runtime_spec_payload.get("graph_ref")),
            "plan_states": plan_states,
            "batch_states": batch_states,
            "step_states": step_states,
            "merge_states": merge_states,
            "batch_execution_instances": [],
            "active_batch_by_node": {},
            "active_batches_by_node": {},
            "active_execution_by_node": {},
            "active_executions_by_node": {},
            "active_execution_by_batch": {},
            "execution_mode_by_plan": execution_mode_by_plan,
            "concurrency_by_plan": concurrency_by_plan,
            "diagnostics": {
                "source": "runtime_spec.diagnostics.split_plans",
                "split_plan_count": len(split_plans),
                "split_plan_policy_index": policy_index,
            },
        }
    )


def batch_runtime_state_from_diagnostics(diagnostics: dict[str, Any]) -> dict[str, Any]:
    state = _record(diagnostics.get("batch_lifecycle_runtime_state"))
    if state.get("authority") == BATCH_RUNTIME_AUTHORITY:
        return _summarize(state)
    graph_spec = _record(diagnostics.get("coordination_graph_spec"))
    if graph_spec:
        return bootstrap_batch_lifecycle_runtime_state(runtime_spec_payload=graph_spec, mode="active")
    return {}


def summarize_batch_lifecycle_runtime_state(runtime_state: dict[str, Any]) -> dict[str, Any]:
    if _record(runtime_state).get("authority") != BATCH_RUNTIME_AUTHORITY:
        return {}
    return _summarize(runtime_state)


def apply_batch_to_pending_inputs(
    *,
    pending_inputs: dict[str, Any],
    batch_state: dict[str, Any],
) -> dict[str, Any]:
    if not batch_state:
        return dict(pending_inputs or {})
    batch_range = _record(batch_state.get("range"))
    start = _int_value(batch_range.get("start"), 0)
    end = _int_value(batch_range.get("end"), start)
    unit_kind = _string(batch_state.get("unit_kind"), "unit")
    return {
        **dict(pending_inputs or {}),
        "unit_kind": unit_kind,
        "unit_batch_id": _string(batch_state.get("batch_id")),
        "unit_batch_execution_id": _string(batch_state.get("active_execution_id")),
        "unit_batch_plan_id": _string(batch_state.get("plan_id")),
        "unit_batch_sequence_index": _int_value(batch_state.get("sequence_index"), 0),
        "unit_batch_label": _string(batch_range.get("label")),
        "batch_start_index": start,
        "batch_end_index": end,
        "batch_range": {"start": start, "end": end, "label": _string(batch_range.get("label"))},
    }


def select_batch_for_stage(
    *,
    runtime_state: dict[str, Any],
    stage_id: str,
    node_id: str = "",
) -> tuple[dict[str, Any], dict[str, Any]]:
    state = _summarize(runtime_state)
    target_ids = {_string(stage_id), _string(node_id)}
    target_ids.discard("")
    if not target_ids:
        return state, {}
    batch_states = [_record(item) for item in list(state.get("batch_states") or []) if isinstance(item, dict)]
    active_by_node = _record(state.get("active_batch_by_node"))
    active_batches_by_node = _list_map(state.get("active_batches_by_node"))
    active_execution_by_node = _record(state.get("active_execution_by_node"))
    active_executions_by_node = _list_map(state.get("active_executions_by_node"))
    active_execution_by_batch = _record(state.get("active_execution_by_batch"))
    execution_instances = [
        _record(item)
        for item in list(state.get("batch_execution_instances") or [])
        if isinstance(item, dict)
    ]
    candidates = [
        item
        for item in batch_states
        if _string(item.get("node_id")) in target_ids and _string(item.get("status")) in {"ready", "repair_ready"}
    ]
    active_batch_ids = _target_active_batch_ids(active_batches_by_node, active_by_node, target_ids)
    parallel_capacity = _target_parallel_capacity(state, batch_states=batch_states, candidates=candidates, target_ids=target_ids)
    if active_batch_ids and (parallel_capacity <= len(active_batch_ids) or not candidates):
        active = next(
            (
                item
                for item in batch_states
                if _string(item.get("batch_id")) in active_batch_ids
                and _string(item.get("status")) in {"running", "repairing"}
            ),
            {},
        )
        if active and parallel_capacity <= 1:
            return state, dict(active)
        if active:
            return state, {}
    if not candidates:
        return state, {}
    selected = sorted(candidates, key=lambda item: _int_value(item.get("sequence_index"), 0))[0]
    selected_id = _string(selected.get("batch_id"))
    execution_id = _execution_instance_id(
        state,
        batch_id=selected_id,
        plan_id=_string(selected.get("plan_id")),
        attempt_index=_int_value(selected.get("attempt_index"), 0) + 1,
    )
    next_batches: list[dict[str, Any]] = []
    for item in batch_states:
        next_item = dict(item)
        if _string(item.get("batch_id")) == selected_id:
            next_item["status"] = "repairing" if _string(item.get("status")) == "repair_ready" else "running"
            next_item["attempt_index"] = _int_value(item.get("attempt_index"), 0) + 1
            next_item["active_execution_id"] = execution_id
        next_batches.append(next_item)
    for target in target_ids:
        active_by_node[target] = selected_id
        active_batches_by_node[target] = _append_unique(active_batches_by_node.get(target, []), selected_id)
        active_execution_by_node[target] = execution_id
        active_executions_by_node[target] = _append_unique(active_executions_by_node.get(target, []), execution_id)
    active_execution_by_batch[selected_id] = execution_id
    execution_instances.append(
        {
            "execution_id": execution_id,
            "batch_id": selected_id,
            "plan_id": _string(selected.get("plan_id")),
            "node_id": _string(selected.get("node_id")),
            "unit_kind": _string(selected.get("unit_kind"), "unit"),
            "range": _record(selected.get("range")),
            "status": "running",
            "sequence_index": _int_value(selected.get("sequence_index"), 0),
            "attempt_index": _int_value(selected.get("attempt_index"), 0) + 1,
            "repair_round": _int_value(selected.get("repair_round"), 0),
            "request_id": "",
            "dispatch_event_id": "",
            "request_payload": {},
            "result_ref": "",
            "verdict": "",
        }
    )
    state["batch_states"] = next_batches
    state["batch_execution_instances"] = execution_instances
    state["active_batch_by_node"] = active_by_node
    state["active_batches_by_node"] = active_batches_by_node
    state["active_execution_by_node"] = active_execution_by_node
    state["active_executions_by_node"] = active_executions_by_node
    state["active_execution_by_batch"] = active_execution_by_batch
    state = _mark_step(state, batch_id=selected_id, step_type="execute", status="running")
    return _summarize(state), next(item for item in next_batches if _string(item.get("batch_id")) == selected_id)


def attach_batch_execution_request(
    *,
    runtime_state: dict[str, Any],
    batch_execution_id: str,
    request_id: str = "",
    dispatch_event_id: str = "",
    request_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state = _summarize(runtime_state)
    target = _string(batch_execution_id)
    if not target:
        return state
    instances: list[dict[str, Any]] = []
    for item in [_record(raw) for raw in list(state.get("batch_execution_instances") or []) if isinstance(raw, dict)]:
        if _string(item.get("execution_id")) == target:
            if request_id:
                item["request_id"] = request_id
            if dispatch_event_id:
                item["dispatch_event_id"] = dispatch_event_id
            if request_payload:
                item["request_payload"] = dict(request_payload)
        instances.append(item)
    state["batch_execution_instances"] = instances
    return _summarize(state)


def transition_batch_after_stage_result(
    *,
    runtime_state: dict[str, Any],
    stage_id: str,
    node_id: str,
    accepted: bool,
    task_result_ref: str = "",
    agent_run_result_ref: str = "",
    request_id: str = "",
    dispatch_event_id: str = "",
    batch_execution_id: str = "",
    event_diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state = _summarize(runtime_state)
    target_ids = {_string(stage_id), _string(node_id)}
    target_ids.discard("")
    if not target_ids:
        return state
    batch_states = [_record(item) for item in list(state.get("batch_states") or []) if isinstance(item, dict)]
    active_by_node = _record(state.get("active_batch_by_node"))
    active_batches_by_node = _list_map(state.get("active_batches_by_node"))
    active_execution_by_node = _record(state.get("active_execution_by_node"))
    active_executions_by_node = _list_map(state.get("active_executions_by_node"))
    active_execution_by_batch = _record(state.get("active_execution_by_batch"))
    execution_instances = [
        _record(item)
        for item in list(state.get("batch_execution_instances") or [])
        if isinstance(item, dict)
    ]
    identity_provided = any(
        _string(value)
        for value in (
            request_id,
            dispatch_event_id,
            batch_execution_id,
            _record(event_diagnostics).get("unit_batch_execution_id"),
        )
    )
    active_execution_id = _resolve_execution_id_for_result(
        execution_instances=execution_instances,
        request_id=request_id,
        dispatch_event_id=dispatch_event_id,
        batch_execution_id=batch_execution_id or _string(_record(event_diagnostics).get("unit_batch_execution_id")),
    )
    if identity_provided and not active_execution_id and execution_instances:
        diagnostics = _record(state.get("diagnostics"))
        diagnostics["last_transition_ignored"] = {
            "stage_id": _string(stage_id),
            "node_id": _string(node_id),
            "request_id": _string(request_id),
            "dispatch_event_id": _string(dispatch_event_id),
            "batch_execution_id": _string(batch_execution_id or _record(event_diagnostics).get("unit_batch_execution_id")),
            "reason": "batch_execution_identity_not_found",
        }
        state["diagnostics"] = diagnostics
        return _summarize(state)
    active_batch_id = ""
    if active_execution_id:
        active_batch_id = _string(
            next(
                (
                    item.get("batch_id")
                    for item in execution_instances
                    if _string(item.get("execution_id")) == active_execution_id
                ),
                "",
            )
        )
    for target in target_ids:
        if active_batch_id:
            break
        active_batch_id = _string(active_by_node.get(target))
        if active_batch_id:
            break
    if not active_batch_id:
        active = next(
            (
                item
                for item in batch_states
                if _string(item.get("node_id")) in target_ids and _string(item.get("status")) in {"running", "repairing"}
            ),
            {},
        )
        active_batch_id = _string(active.get("batch_id"))
    if not active_batch_id:
        return state
    active_execution_id = active_execution_id or _string(active_execution_by_batch.get(active_batch_id))
    plans_by_id = _policy_index_from_runtime_state(state)
    result_ref = task_result_ref or agent_run_result_ref
    next_batches: list[dict[str, Any]] = []
    active_plan_id = ""
    active_sequence = 0
    next_status = ""
    for item in batch_states:
        next_item = dict(item)
        if _string(item.get("batch_id")) == active_batch_id:
            active_plan_id = _string(item.get("plan_id"))
            active_sequence = _int_value(item.get("sequence_index"), 0)
            policy = _record(plans_by_id.get(active_plan_id))
            max_repair_rounds = _int_value(_record(policy.get("acceptance_policy")).get("max_repair_rounds"), 3)
            if accepted:
                next_item.update(
                    {
                        "status": "committed",
                        "accepted": True,
                        "committed": True,
                        "active_execution_id": "",
                        "last_result_ref": result_ref,
                        "last_verdict": "accepted",
                    }
                )
                next_status = "committed"
            else:
                repair_round = _int_value(item.get("repair_round"), 0) + 1
                if repair_round <= max_repair_rounds:
                    next_item.update(
                        {
                            "status": "repair_ready",
                            "accepted": False,
                            "active_execution_id": "",
                            "repair_round": repair_round,
                            "last_result_ref": result_ref,
                            "last_verdict": "revise",
                        }
                    )
                    next_status = "repair_ready"
                else:
                    next_item.update(
                        {
                            "status": "failed",
                            "accepted": False,
                            "active_execution_id": "",
                            "repair_round": repair_round,
                            "last_result_ref": result_ref,
                            "last_verdict": "repair_rounds_exhausted",
                        }
                    )
                    next_status = "failed"
        next_batches.append(next_item)
    if next_status == "committed":
        for item in next_batches:
            if _string(item.get("plan_id")) == active_plan_id and _int_value(item.get("sequence_index"), 0) == active_sequence + 1 and _string(item.get("status")) == "planned":
                item["status"] = "ready"
                break
        state = _mark_step(state, batch_id=active_batch_id, step_type="execute", status="completed")
        state = _mark_step(state, batch_id=active_batch_id, step_type="review", status="completed")
        state = _mark_step(state, batch_id=active_batch_id, step_type="repair_loop", status="skipped_or_completed")
        state = _mark_step(state, batch_id=active_batch_id, step_type="commit", status="completed")
    elif next_status == "repair_ready":
        state = _mark_step(state, batch_id=active_batch_id, step_type="execute", status="completed")
        state = _mark_step(state, batch_id=active_batch_id, step_type="review", status="revision_requested")
        state = _mark_step(state, batch_id=active_batch_id, step_type="repair_loop", status="ready")
    elif next_status == "failed":
        state = _mark_step(state, batch_id=active_batch_id, step_type="review", status="failed")
        state = _mark_step(state, batch_id=active_batch_id, step_type="repair_loop", status="failed")
    for target in target_ids:
        if _string(active_by_node.get(target)) == active_batch_id:
            active_by_node.pop(target, None)
        active_batches_by_node[target] = [
            item
            for item in list(active_batches_by_node.get(target) or [])
            if _string(item) != active_batch_id
        ]
        if active_execution_id and _string(active_execution_by_node.get(target)) == active_execution_id:
            active_execution_by_node.pop(target, None)
        if active_execution_id:
            active_executions_by_node[target] = [
                item
                for item in list(active_executions_by_node.get(target) or [])
                if _string(item) != active_execution_id
            ]
    if active_execution_id:
        active_execution_by_batch.pop(active_batch_id, None)
    next_instances: list[dict[str, Any]] = []
    for item in execution_instances:
        if active_execution_id and _string(item.get("execution_id")) == active_execution_id:
            item["status"] = next_status or item.get("status") or ""
            item["result_ref"] = result_ref
            item["verdict"] = "accepted" if accepted else "revise"
            if next_status == "failed":
                item["verdict"] = "repair_rounds_exhausted"
        next_instances.append(item)
    state["batch_states"] = next_batches
    state["batch_execution_instances"] = next_instances
    state["active_batch_by_node"] = active_by_node
    state["active_batches_by_node"] = active_batches_by_node
    state["active_execution_by_node"] = active_execution_by_node
    state["active_executions_by_node"] = active_executions_by_node
    state["active_execution_by_batch"] = active_execution_by_batch
    diagnostics = _record(state.get("diagnostics"))
    diagnostics["last_transition"] = {
        "stage_id": _string(stage_id),
        "node_id": _string(node_id),
        "batch_id": active_batch_id,
        "execution_id": active_execution_id,
        "request_id": _string(request_id),
        "dispatch_event_id": _string(dispatch_event_id),
        "accepted": bool(accepted),
        "next_status": next_status,
        "result_ref": result_ref,
        "event_diagnostics": _record(event_diagnostics),
    }
    state["diagnostics"] = diagnostics
    return _summarize(state)


def batch_execution_instance_for_result(
    *,
    runtime_state: dict[str, Any],
    stage_id: str,
    node_id: str = "",
    request_id: str = "",
    dispatch_event_id: str = "",
    batch_execution_id: str = "",
    event_diagnostics: dict[str, Any] | None = None,
    active_only: bool = True,
) -> dict[str, Any]:
    state = _summarize(runtime_state)
    target_ids = {_string(stage_id), _string(node_id)}
    target_ids.discard("")
    if not target_ids:
        return {}
    instances = [
        _record(item)
        for item in list(state.get("batch_execution_instances") or [])
        if isinstance(item, dict)
    ]
    execution_id = _resolve_execution_id_for_result(
        execution_instances=instances,
        request_id=request_id,
        dispatch_event_id=dispatch_event_id,
        batch_execution_id=batch_execution_id or _string(_record(event_diagnostics).get("unit_batch_execution_id")),
    )
    if not execution_id:
        return {}
    allowed_statuses = {"running", "repairing"} if active_only else {"running", "repairing", "committed", "repair_ready", "failed"}
    return next(
        (
            dict(item)
            for item in instances
            if _string(item.get("execution_id")) == execution_id
            and _string(item.get("node_id")) in target_ids
            and _string(item.get("status")) in allowed_statuses
        ),
        {},
    )


def node_has_batch_plan(*, runtime_state: dict[str, Any], stage_id: str, node_id: str = "") -> bool:
    target_ids = {_string(stage_id), _string(node_id)}
    target_ids.discard("")
    return any(
        _string(item.get("node_id")) in target_ids
        for item in [_record(raw) for raw in list(runtime_state.get("batch_states") or []) if isinstance(raw, dict)]
    )


def node_batches_finished(*, runtime_state: dict[str, Any], stage_id: str, node_id: str = "") -> bool:
    target_ids = {_string(stage_id), _string(node_id)}
    target_ids.discard("")
    batches = [
        _record(raw)
        for raw in list(runtime_state.get("batch_states") or [])
        if isinstance(raw, dict) and _string(_record(raw).get("node_id")) in target_ids
    ]
    return bool(batches) and all(_string(item.get("status")) in {"committed", "failed"} for item in batches)


def node_has_more_batch_work(*, runtime_state: dict[str, Any], stage_id: str, node_id: str = "") -> bool:
    target_ids = {_string(stage_id), _string(node_id)}
    target_ids.discard("")
    batches = [
        _record(raw)
        for raw in list(runtime_state.get("batch_states") or [])
        if isinstance(raw, dict) and _string(_record(raw).get("node_id")) in target_ids
    ]
    if any(_string(item.get("status")) == "failed" for item in batches):
        return False
    return any(_string(item.get("status")) in {"planned", "ready", "repair_ready", "running", "repairing"} for item in batches)


def node_has_dispatchable_batch_work(*, runtime_state: dict[str, Any], stage_id: str, node_id: str = "") -> bool:
    target_ids = {_string(stage_id), _string(node_id)}
    target_ids.discard("")
    return any(
        _string(item.get("node_id")) in target_ids and _string(item.get("status")) in {"ready", "repair_ready"}
        for item in [_record(raw) for raw in list(runtime_state.get("batch_states") or []) if isinstance(raw, dict)]
    )


def node_has_active_batch_work(*, runtime_state: dict[str, Any], stage_id: str, node_id: str = "") -> bool:
    target_ids = {_string(stage_id), _string(node_id)}
    target_ids.discard("")
    return any(
        _string(item.get("node_id")) in target_ids and _string(item.get("status")) in {"running", "repairing"}
        for item in [_record(raw) for raw in list(runtime_state.get("batch_states") or []) if isinstance(raw, dict)]
    )


def node_has_failed_batch(*, runtime_state: dict[str, Any], stage_id: str, node_id: str = "") -> bool:
    target_ids = {_string(stage_id), _string(node_id)}
    target_ids.discard("")
    return any(
        _string(item.get("node_id")) in target_ids and _string(item.get("status")) == "failed"
        for item in [_record(raw) for raw in list(runtime_state.get("batch_states") or []) if isinstance(raw, dict)]
    )


def node_all_batches_committed(*, runtime_state: dict[str, Any], stage_id: str, node_id: str = "") -> bool:
    target_ids = {_string(stage_id), _string(node_id)}
    target_ids.discard("")
    batches = [
        _record(raw)
        for raw in list(runtime_state.get("batch_states") or [])
        if isinstance(raw, dict) and _string(_record(raw).get("node_id")) in target_ids
    ]
    return bool(batches) and all(_string(item.get("status")) == "committed" for item in batches)


def node_committed_batch_refs(*, runtime_state: dict[str, Any], stage_id: str, node_id: str = "") -> list[dict[str, Any]]:
    target_ids = {_string(stage_id), _string(node_id)}
    target_ids.discard("")
    return [
        {
            "batch_id": _string(item.get("batch_id")),
            "plan_id": _string(item.get("plan_id")),
            "sequence_index": _int_value(item.get("sequence_index"), 0),
            "unit_kind": _string(item.get("unit_kind"), "unit"),
            "range": _record(item.get("range")),
            "result_ref": _string(item.get("last_result_ref")),
            "status": _string(item.get("status")),
        }
        for item in [_record(raw) for raw in list(runtime_state.get("batch_states") or []) if isinstance(raw, dict)]
        if _string(item.get("node_id")) in target_ids and _string(item.get("status")) == "committed"
    ]


def batch_dispatcher_view(runtime_state: dict[str, Any]) -> dict[str, Any]:
    state = _summarize(runtime_state)
    if _record(state).get("authority") != BATCH_RUNTIME_AUTHORITY:
        return {
            "available": False,
            "nodes": [],
            "summary": {
                "dispatchable_batch_count": 0,
                "active_execution_count": 0,
                "available_slot_count": 0,
            },
        }
    batch_states = [_record(item) for item in list(state.get("batch_states") or []) if isinstance(item, dict)]
    instances = [_record(item) for item in list(state.get("batch_execution_instances") or []) if isinstance(item, dict)]
    execution_modes = _record(state.get("execution_mode_by_plan"))
    concurrency = _record(state.get("concurrency_by_plan"))
    node_ids = sorted({_string(item.get("node_id")) for item in batch_states if _string(item.get("node_id"))})
    nodes: list[dict[str, Any]] = []
    for node_id in node_ids:
        node_batches = [item for item in batch_states if _string(item.get("node_id")) == node_id]
        plan_ids = sorted({_string(item.get("plan_id")) for item in node_batches if _string(item.get("plan_id"))})
        active_batches = [item for item in node_batches if _string(item.get("status")) in {"running", "repairing"}]
        ready_batches = [item for item in node_batches if _string(item.get("status")) in {"ready", "repair_ready"}]
        max_parallel = max(
            [
                max(1, _int_value(concurrency.get(plan_id), 2))
                if _string(execution_modes.get(plan_id), "sequential") == "parallel"
                else 1
                for plan_id in plan_ids
            ]
            or [1]
        )
        available_slots = max(max_parallel - len(active_batches), 0)
        dispatchable_batches = sorted(
            ready_batches[:available_slots],
            key=lambda item: _int_value(item.get("sequence_index"), 0),
        )
        active_execution_ids = [
            _string(instance.get("execution_id"))
            for instance in instances
            if _string(instance.get("node_id")) == node_id and _string(instance.get("status")) in {"running", "repairing"}
        ]
        nodes.append(
            {
                "node_id": node_id,
                "plan_ids": plan_ids,
                "execution_mode": "parallel" if any(_string(execution_modes.get(plan_id)) == "parallel" for plan_id in plan_ids) else "sequential",
                "max_parallel_batches": max_parallel,
                "active_execution_count": len(active_batches),
                "available_slot_count": available_slots,
                "ready_batch_ids": [_string(item.get("batch_id")) for item in ready_batches if _string(item.get("batch_id"))],
                "dispatchable_batch_ids": [_string(item.get("batch_id")) for item in dispatchable_batches if _string(item.get("batch_id"))],
                "active_batch_ids": [_string(item.get("batch_id")) for item in active_batches if _string(item.get("batch_id"))],
                "active_execution_ids": [item for item in active_execution_ids if item],
                "running_batch_count": len(active_batches),
                "committed_batch_count": sum(1 for item in node_batches if _string(item.get("status")) == "committed"),
                "failed_batch_count": sum(1 for item in node_batches if _string(item.get("status")) == "failed"),
            }
        )
    return {
        "available": True,
        "authority": "task_system.batch_dispatcher_view",
        "graph_id": _string(state.get("graph_id")),
        "nodes": nodes,
        "summary": {
            "dispatchable_batch_count": sum(len(item.get("dispatchable_batch_ids") or []) for item in nodes),
            "active_execution_count": sum(_int_value(item.get("active_execution_count"), 0) for item in nodes),
            "available_slot_count": sum(_int_value(item.get("available_slot_count"), 0) for item in nodes),
        },
    }


def _summarize(state: dict[str, Any]) -> dict[str, Any]:
    payload = deepcopy(dict(state or {}))
    batch_states = [_record(item) for item in list(payload.get("batch_states") or []) if isinstance(item, dict)]
    plan_states = [_record(item) for item in list(payload.get("plan_states") or []) if isinstance(item, dict)]
    merge_states = [_record(item) for item in list(payload.get("merge_states") or []) if isinstance(item, dict)]
    execution_instances = [
        _record(item)
        for item in list(payload.get("batch_execution_instances") or [])
        if isinstance(item, dict)
    ]
    active_batches_by_node = _list_map(payload.get("active_batches_by_node"))
    active_executions_by_node = _list_map(payload.get("active_executions_by_node"))
    active_by_node = _record(payload.get("active_batch_by_node"))
    active_execution_by_node = _record(payload.get("active_execution_by_node"))
    active_execution_by_batch = _record(payload.get("active_execution_by_batch"))
    running_batch_ids = {
        _string(item.get("batch_id"))
        for item in batch_states
        if _string(item.get("status")) in {"running", "repairing"}
    }
    running_execution_ids = {
        _string(item.get("execution_id"))
        for item in execution_instances
        if _string(item.get("status")) in {"running", "repairing"}
    }
    active_batches_by_node = {
        key: [item for item in values if item in running_batch_ids]
        for key, values in active_batches_by_node.items()
    }
    active_executions_by_node = {
        key: [item for item in values if item in running_execution_ids]
        for key, values in active_executions_by_node.items()
    }
    for item in batch_states:
        if _string(item.get("status")) not in {"running", "repairing"}:
            continue
        node_id = _string(item.get("node_id"))
        batch_id = _string(item.get("batch_id"))
        execution_id = _string(item.get("active_execution_id")) or _string(active_execution_by_batch.get(batch_id))
        if node_id and batch_id:
            active_batches_by_node[node_id] = _append_unique(active_batches_by_node.get(node_id, []), batch_id)
            active_by_node.setdefault(node_id, batch_id)
        if node_id and execution_id:
            active_executions_by_node[node_id] = _append_unique(active_executions_by_node.get(node_id, []), execution_id)
            active_execution_by_node.setdefault(node_id, execution_id)
        if batch_id and execution_id:
            active_execution_by_batch[batch_id] = execution_id
    committed = [_string(item.get("batch_id")) for item in batch_states if _string(item.get("status")) == "committed"]
    failed = [_string(item.get("batch_id")) for item in batch_states if _string(item.get("status")) == "failed"]
    ready = [_string(item.get("batch_id")) for item in batch_states if _string(item.get("status")) in {"ready", "repair_ready"}]
    running = [_string(item.get("batch_id")) for item in batch_states if _string(item.get("status")) in {"running", "repairing"}]
    for plan in plan_states:
        plan_id = _string(plan.get("plan_id"))
        plan_batches = [item for item in batch_states if _string(item.get("plan_id")) == plan_id]
        plan["committed_batch_count"] = sum(1 for item in plan_batches if _string(item.get("status")) == "committed")
        plan["failed_batch_count"] = sum(1 for item in plan_batches if _string(item.get("status")) == "failed")
        plan["active_batch_id"] = next((_string(item.get("batch_id")) for item in plan_batches if _string(item.get("status")) in {"running", "repairing"}), "")
        if plan_batches and all(_string(item.get("status")) == "committed" for item in plan_batches):
            plan["status"] = "committed"
        elif any(_string(item.get("status")) == "failed" for item in plan_batches):
            plan["status"] = "failed"
        elif any(_string(item.get("status")) in {"running", "repairing"} for item in plan_batches):
            plan["status"] = "running"
        elif any(_string(item.get("status")) in {"ready", "repair_ready"} for item in plan_batches):
            plan["status"] = "ready"
        else:
            plan["status"] = "planned"
    for merge in merge_states:
        depends = {_string(item) for item in list(merge.get("depends_on_batch_ids") or []) if _string(item)}
        if depends and depends.issubset(set(committed)):
            merge["status"] = "ready"
        elif _string(merge.get("status")) != "completed":
            merge["status"] = "waiting_for_commits"
    payload["plan_states"] = plan_states
    payload["batch_states"] = batch_states
    payload["merge_states"] = merge_states
    payload["batch_execution_instances"] = execution_instances
    payload["active_batch_by_node"] = {key: (values[0] if values else "") for key, values in active_batches_by_node.items()}
    payload["active_batches_by_node"] = {key: values for key, values in active_batches_by_node.items() if values}
    payload["active_execution_by_node"] = {key: (values[0] if values else "") for key, values in active_executions_by_node.items()}
    payload["active_executions_by_node"] = {key: values for key, values in active_executions_by_node.items() if values}
    payload["active_execution_by_batch"] = {
        key: value
        for key, value in active_execution_by_batch.items()
        if key in running_batch_ids and value in running_execution_ids
    }
    payload["ready_batch_ids"] = [item for item in ready if item]
    payload["running_batch_ids"] = [item for item in running if item]
    payload["committed_batch_ids"] = [item for item in committed if item]
    payload["failed_batch_ids"] = [item for item in failed if item]
    payload["summary"] = {
        "plan_count": len(plan_states),
        "batch_count": len(batch_states),
        "ready_batch_count": len(ready),
        "running_batch_count": len(running),
        "committed_batch_count": len(committed),
        "failed_batch_count": len(failed),
        "merge_ready_count": sum(1 for item in merge_states if _string(item.get("status")) == "ready"),
        "execution_instance_count": len(execution_instances),
        "running_execution_instance_count": sum(1 for item in execution_instances if _string(item.get("status")) in {"running", "repairing"}),
        "committed_execution_instance_count": sum(1 for item in execution_instances if _string(item.get("status")) == "committed"),
        "failed_execution_instance_count": sum(1 for item in execution_instances if _string(item.get("status")) == "failed"),
        "active_execution_count": len(payload["active_execution_by_batch"]),
    }
    return payload


def _mark_step(state: dict[str, Any], *, batch_id: str, step_type: str, status: str) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []
    for item in [_record(raw) for raw in list(state.get("step_states") or []) if isinstance(raw, dict)]:
        if _string(item.get("batch_id")) == batch_id and _string(item.get("step_type")) == step_type:
            item["status"] = status
        steps.append(item)
    state["step_states"] = steps
    return state


def _policy_index_from_runtime_state(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    diagnostics = _record(state.get("diagnostics"))
    policy_index = _record(diagnostics.get("split_plan_policy_index"))
    return {str(key): _record(value) for key, value in policy_index.items() if isinstance(value, dict)}


def _execution_instance_id(state: dict[str, Any], *, batch_id: str, plan_id: str, attempt_index: int) -> str:
    graph_id = _string(state.get("graph_id"), "graph")
    return f"batchrun:{_safe_identifier(graph_id)}:{_safe_identifier(plan_id)}:{_safe_identifier(batch_id)}:attempt_{max(attempt_index, 1)}"


def _target_parallel_capacity(
    state: dict[str, Any],
    *,
    batch_states: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    target_ids: set[str],
) -> int:
    plans = {_string(item.get("plan_id")) for item in [*batch_states, *candidates] if _string(item.get("node_id")) in target_ids}
    execution_modes = _record(state.get("execution_mode_by_plan"))
    concurrency = _record(state.get("concurrency_by_plan"))
    limits: list[int] = []
    for plan_id in plans:
        mode = _string(execution_modes.get(plan_id), "sequential")
        if mode != "parallel":
            limits.append(1)
            continue
        limits.append(max(1, _int_value(concurrency.get(plan_id), 2)))
    return max(limits or [1])


def _target_active_batch_ids(
    active_batches_by_node: dict[str, list[str]],
    active_by_node: dict[str, Any],
    target_ids: set[str],
) -> list[str]:
    values: list[str] = []
    for target in target_ids:
        values.extend(_string(item) for item in list(active_batches_by_node.get(target) or []) if _string(item))
        if _string(active_by_node.get(target)):
            values.append(_string(active_by_node.get(target)))
    return list(dict.fromkeys(values))


def _resolve_execution_id_for_result(
    *,
    execution_instances: list[dict[str, Any]],
    request_id: str,
    dispatch_event_id: str,
    batch_execution_id: str,
) -> str:
    target_execution_id = _string(batch_execution_id)
    if target_execution_id:
        matched = next(
            (
                _string(item.get("execution_id"))
                for item in execution_instances
                if _string(item.get("execution_id")) == target_execution_id
            ),
            "",
        )
        return matched
    target_request_id = _string(request_id)
    if target_request_id:
        matched = next(
            (
                _string(item.get("execution_id"))
                for item in execution_instances
                if _string(item.get("request_id")) == target_request_id
            ),
            "",
        )
        if matched:
            return matched
    target_dispatch_id = _string(dispatch_event_id)
    if target_dispatch_id:
        matched = next(
            (
                _string(item.get("execution_id"))
                for item in execution_instances
                if _string(item.get("dispatch_event_id")) == target_dispatch_id
            ),
            "",
        )
        if matched:
            return matched
    return ""


def _parallel_dispatch_limit(plan_metadata: dict[str, Any], *, child_execution_mode: str) -> int:
    if child_execution_mode != "parallel":
        return 1
    for key in ("max_parallel_batches", "max_concurrency", "parallelism"):
        value = _int_value(plan_metadata.get(key), 0)
        if value > 0:
            return value
    return 2


def _append_unique(values: list[str], value: str) -> list[str]:
    clean = [_string(item) for item in list(values or []) if _string(item)]
    if _string(value):
        clean.append(_string(value))
    return list(dict.fromkeys(clean))


def _list_map(value: Any) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for key, raw in dict(value or {}).items():
        if isinstance(raw, list):
            items = [_string(item) for item in raw if _string(item)]
        elif _string(raw):
            items = [_string(raw)]
        else:
            items = []
        if _string(key) and items:
            result[_string(key)] = list(dict.fromkeys(items))
    return result


def _record(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _string(value: Any, fallback: str = "") -> str:
    text = str(value or "").strip()
    return text or fallback


def _int_value(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _safe_identifier(value: str) -> str:
    text = _string(value, "item")
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in text)
    return safe[:160] or "item"
