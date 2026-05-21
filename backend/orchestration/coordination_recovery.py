from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from runtime import TaskRun
from runtime.unit_runtime.quality_gates import _stage_business_acceptance

from orchestration.coordination_rewind import _safe_path_component

def _latest_unconsumed_stage_task_result(
    *,
    runtime: Any,
    session_id: str,
    state: dict[str, Any],
    active_stage_id: str,
    coordination_run_id: str,
) -> dict[str, Any]:
    if not active_stage_id:
        return {}
    stage_results = dict(state.get("stage_results") or {})
    already_consumed_task_run_id = str(dict(stage_results.get(active_stage_id) or {}).get("task_run_id") or "")
    contracts = dict(state.get("stage_contracts") or {})
    contract = dict(contracts.get(active_stage_id) or {})
    active_task_ref = str(contract.get("task_ref") or state.get("active_task_ref") or "").strip()
    expected_task_suffix = active_stage_id
    candidates = []
    for task_run in runtime.query_runtime.task_run_loop.state_index.list_session_task_runs(session_id):
        if str(task_run.status or "") != "completed":
            continue
        if str(task_run.task_run_id or "") == already_consumed_task_run_id:
            continue
        pending_inputs = dict(state.get("pending_inputs") or {})
        force_replay_after = float(pending_inputs.get("force_replay_after") or 0.0)
        if force_replay_after and float(task_run.updated_at or task_run.created_at or 0.0) <= force_replay_after:
            continue
        task_id = str(task_run.task_id or "")
        task_contract_ref = str(task_run.task_contract_ref or "")
        exact_task_match = bool(active_task_ref and active_task_ref in {task_id, task_contract_ref})
        stage_suffix_match = bool(
            task_id.endswith(f":{expected_task_suffix}")
            or task_contract_ref.endswith(f":{expected_task_suffix}")
        )
        if not exact_task_match and not stage_suffix_match:
            continue
        diagnostics = dict(task_run.diagnostics or {})
        materialization = dict(diagnostics.get("artifact_materialization") or {})
        artifact_refs = [
            str(item)
            for item in list(materialization.get("artifact_refs") or [])
            if str(item).startswith("artifact:")
        ]
        checkpoint = runtime.query_runtime.task_run_loop.checkpoints.load_latest(task_run.task_run_id)
        task_result = dict(getattr(checkpoint, "commit_state", {}) or {}).get("task_result") if checkpoint is not None else {}
        task_result = dict(task_result or {})
        if artifact_refs:
            task_result["output_refs"] = list(dict.fromkeys([*list(task_result.get("output_refs") or []), *artifact_refs]))
        accepted = bool(str(task_run.status or "") == "completed" and (artifact_refs or not dict(contract.get("artifact_policy") or {}).get("enabled")))
        acceptance_diagnostics: dict[str, Any] = {
            "terminal_reason": str(task_run.terminal_reason or ""),
            "recovered_from_completed_stage_task_run": True,
        }
        if active_stage_id == "chapter_draft" or _is_review_gate_contract(contract):
            artifact_text = _read_first_artifact_text(runtime=runtime, artifact_refs=artifact_refs)
            quality = _recovery_stage_business_acceptance(
                stage_id=active_stage_id,
                contract=contract,
                explicit_inputs=pending_inputs,
                final_content=artifact_text,
                output_refs=artifact_refs,
                terminal_status=str(task_run.status or ""),
            )
            accepted = bool(accepted and quality.get("accepted") is True)
            acceptance_diagnostics.update(quality)
        candidates.append((float(task_run.updated_at or task_run.created_at or 0.0), task_run, task_result, artifact_refs, materialization, accepted, acceptance_diagnostics))
    if not candidates:
        return {}
    _updated_at, task_run, task_result, artifact_refs, materialization, accepted, acceptance_diagnostics = sorted(candidates, key=lambda item: item[0], reverse=True)[0]
    pending_inputs = dict(state.get("pending_inputs") or {})
    artifact_root = str(
        materialization.get("artifact_root")
        or pending_inputs.get("artifact_root")
        or ""
    )
    return {
        "task_run_id": task_run.task_run_id,
        "task_result": task_result,
        "explicit_inputs": pending_inputs,
        "artifact_root": artifact_root,
        "event": {
            "event_type": "task_result_ready",
            "coordination_run_id": coordination_run_id,
            "task_run_id": task_run.task_run_id,
            "stage_id": active_stage_id,
            "task_ref": active_task_ref or task_run.task_id,
            "task_result_ref": str(task_result.get("result_id") or f"taskresult:{task_run.task_run_id}"),
            "artifact_refs": tuple(artifact_refs),
            "accepted": bool(accepted),
            "agent_run_result_ref": "",
            "diagnostics": acceptance_diagnostics,
        },
    }


def _recover_active_stage_completed_checkpoint(
    *,
    runtime: Any,
    session_id: str,
    state: dict[str, Any],
    active_stage_id: str,
    coordination_run_id: str,
    current_turn_context: dict[str, Any],
) -> dict[str, Any]:
    if not active_stage_id:
        return {}
    stage_results = dict(state.get("stage_results") or {})
    already_consumed_task_run_id = str(dict(stage_results.get(active_stage_id) or {}).get("task_run_id") or "")
    contracts = dict(state.get("stage_contracts") or {})
    contract = dict(contracts.get(active_stage_id) or {})
    active_task_ref = str(contract.get("task_ref") or state.get("active_task_ref") or "").strip()
    candidates = []
    task_run_loop = runtime.query_runtime.task_run_loop
    for task_run in task_run_loop.state_index.list_session_task_runs(session_id):
        if str(task_run.task_run_id or "") == already_consumed_task_run_id:
            continue
        if str(task_run.status or "") in {"completed", "failed", "aborted"}:
            continue
        task_id = str(task_run.task_id or "")
        task_contract_ref = str(task_run.task_contract_ref or "")
        exact_task_match = bool(active_task_ref and active_task_ref in {task_id, task_contract_ref})
        stage_suffix_match = bool(
            task_id.endswith(f":{active_stage_id}")
            or task_contract_ref.endswith(f":{active_stage_id}")
        )
        if not exact_task_match and not stage_suffix_match:
            continue
        checkpoint = task_run_loop.checkpoints.load_latest(task_run.task_run_id)
        if checkpoint is None:
            continue
        if str(checkpoint.loop_state.status or "") != "completed":
            continue
        if str(checkpoint.loop_state.terminal_reason or "") != "completed":
            continue
        candidates.append((float(task_run.updated_at or task_run.created_at or 0.0), task_run))
    if not candidates:
        return {}
    _updated_at, task_run = sorted(candidates, key=lambda item: item[0], reverse=True)[0]
    recovered = task_run_loop.recover_completed_checkpoint_task_run(
        task_run_id=task_run.task_run_id,
        current_turn_context={
            "coordination_run_id": coordination_run_id,
            "task_graph_id": str(state.get("graph_id") or ""),
            "selected_graph_id": str(state.get("graph_id") or ""),
            "stage_execution_request": dict(state.get("stage_execution_request") or {}),
            "explicit_inputs": dict(state.get("pending_inputs") or {}),
            **dict(current_turn_context or {}),
        },
    )
    payload = recovered.to_dict()
    payload["task_run_id"] = task_run.task_run_id
    return payload


def _latest_unconsumed_graph_module_imported_result(
    *,
    runtime: Any,
    session_id: str,
    state: dict[str, Any],
    active_stage_id: str,
    coordination_run_id: str,
) -> dict[str, Any]:
    if not active_stage_id or not _active_stage_is_graph_module(state=state, active_stage_id=active_stage_id):
        return {}
    stage_results = dict(state.get("stage_results") or {})
    already_consumed_task_run_id = str(dict(stage_results.get(active_stage_id) or {}).get("task_run_id") or "").strip()
    current_stage_payload = dict(state.get("stage_execution_request") or {})
    active_task_ref = str(
        current_stage_payload.get("task_ref")
        or dict(dict(state.get("stage_contracts") or {}).get(active_stage_id) or {}).get("task_ref")
        or state.get("active_task_ref")
        or ""
    ).strip()
    active_request_id = str(current_stage_payload.get("request_id") or "").strip()
    active_idempotency_key = str(current_stage_payload.get("idempotency_key") or "").strip()
    pending_inputs = dict(state.get("pending_inputs") or {})
    candidates: list[tuple[float, TaskRun, dict[str, Any], dict[str, Any]]] = []
    for imported_run in runtime.query_runtime.task_run_loop.state_index.list_session_task_runs(session_id):
        if str(imported_run.task_run_id or "") == already_consumed_task_run_id:
            continue
        diagnostics = dict(imported_run.diagnostics or {})
        if diagnostics.get("graph_module_imported_run") is not True:
            continue
        if str(diagnostics.get("importing_coordination_run_id") or "").strip() != coordination_run_id:
            continue
        if str(diagnostics.get("importing_stage_id") or diagnostics.get("stage_id") or "").strip() != active_stage_id:
            continue
        imported_request_id = str(diagnostics.get("importing_stage_request_id") or "").strip()
        imported_idempotency_key = str(diagnostics.get("importing_stage_idempotency_key") or "").strip()
        if active_request_id and imported_request_id and imported_request_id != active_request_id:
            continue
        if active_idempotency_key and imported_idempotency_key and imported_idempotency_key != active_idempotency_key:
            continue
        committed = dict(
            diagnostics.get("graph_module_output_packet_committed")
            or diagnostics.get("graph_module_failure_packet_committed")
            or {}
        )
        if (
            committed
            and str(committed.get("importing_coordination_run_id") or "").strip() == coordination_run_id
            and str(committed.get("importing_stage_id") or "").strip() == active_stage_id
        ):
            continue
        completion = _graph_module_imported_completion_packet(
            runtime=runtime,
            imported_task_run=imported_run,
            diagnostics=diagnostics,
        )
        if not completion:
            continue
        candidates.append((float(imported_run.updated_at or imported_run.created_at or 0.0), imported_run, completion, diagnostics))
    if not candidates:
        return {}
    _updated_at, imported_run, packet, diagnostics = sorted(candidates, key=lambda item: item[0], reverse=True)[0]
    packet_status = str(packet.get("status") or "").strip()
    packet_collection = "graph_module_failure_packets" if packet_status in {"failed", "blocked", "waiting_for_human"} else "graph_module_output_packets"
    packet_ref = runtime.query_runtime.task_run_loop.runtime_objects.put_object(
        packet_collection,
        _graph_module_output_packet_object_id(
            importing_coordination_run_id=coordination_run_id,
            importing_stage_id=active_stage_id,
            imported_task_run_id=imported_run.task_run_id,
        ),
        packet,
    )
    artifact_refs = [
        str(item)
        for item in list(packet.get("artifact_refs") or [])
        if str(item).startswith("artifact:")
    ]
    task_result = {
        "result_id": packet_ref,
        "task_result_ref": packet_ref,
        "outputs": dict(packet.get("outputs") or {}),
        "final_outputs": {
            **dict(packet.get("outputs") or {}),
            "graph_module_output_packet_ref": packet_ref,
            "graph_module_output_packet": packet,
        },
        "output_refs": list(dict.fromkeys([*list(packet.get("output_refs") or []), *artifact_refs])),
        "result_refs": list(dict.fromkeys([packet_ref, *list(packet.get("result_refs") or [])])),
        "diagnostics": {
            "authority": "orchestration.graph_module_committed_output_packet_result",
            "graph_module_output_packet_ref": packet_ref,
            "graph_module_output_packet": packet,
            "linked_graph_id": str(packet.get("linked_graph_id") or ""),
            "imported_coordination_run_id": str(packet.get("imported_coordination_run_id") or ""),
        },
    }
    return {
        "task_run_id": imported_run.task_run_id,
        "packet": packet,
        "packet_ref": packet_ref,
        "task_result": task_result,
        "explicit_inputs": pending_inputs,
        "artifact_root": str(pending_inputs.get("artifact_root") or ""),
        "event": {
            "event_type": "task_result_ready",
            "coordination_run_id": coordination_run_id,
            "task_run_id": imported_run.task_run_id,
            "stage_id": active_stage_id,
            "task_ref": active_task_ref or str(diagnostics.get("importing_task_ref") or imported_run.task_id or ""),
            "task_result_ref": packet_ref,
            "artifact_refs": tuple(artifact_refs or [packet_ref]),
            "accepted": bool(packet.get("accepted") is True),
            "agent_run_result_ref": "",
            "request_id": active_request_id or str(diagnostics.get("importing_stage_request_id") or ""),
            "dispatch_event_id": str(diagnostics.get("importing_dispatch_event_id") or ""),
            "diagnostics": {
                "authority": "orchestration.graph_module_committed_output_packet" if bool(packet.get("accepted") is True) else "orchestration.graph_module_committed_failure_packet",
                "graph_module_output_packet_ref": packet_ref,
                "graph_module_output_packet": packet,
                "graph_module_imported_run": True,
                "imported_task_run_id": imported_run.task_run_id,
                "imported_coordination_run_id": str(packet.get("imported_coordination_run_id") or ""),
                "linked_graph_id": str(packet.get("linked_graph_id") or ""),
                "terminal_reason": str(imported_run.terminal_reason or "completed"),
            },
        },
    }


def _active_stage_is_graph_module(*, state: dict[str, Any], active_stage_id: str) -> bool:
    request_payload = dict(state.get("stage_execution_request") or {})
    if str(request_payload.get("executor_type") or "") == "graph_module":
        return True
    contract = dict(dict(state.get("stage_contracts") or {}).get(active_stage_id) or {})
    if str(contract.get("node_type") or "") == "graph_module":
        return True
    metadata = dict(contract.get("metadata") or {})
    executor_policy = dict(contract.get("executor_policy") or {})
    return bool(metadata.get("graph_module")) or str(executor_policy.get("default_executor") or "") == "graph_module"


def _graph_module_imported_completion_packet(
    *,
    runtime: Any,
    imported_task_run: TaskRun,
    diagnostics: dict[str, Any],
) -> dict[str, Any]:
    task_run_loop = runtime.query_runtime.task_run_loop
    imported_coordination_run_id = str(diagnostics.get("imported_coordination_run_id") or "").strip()
    if not imported_coordination_run_id:
        for coordination_run in task_run_loop.state_index.list_task_coordination_runs(imported_task_run.task_run_id):
            imported_coordination_run_id = coordination_run.coordination_run_id
            break
    imported_coordination_run = (
        task_run_loop.state_index.get_coordination_run(imported_coordination_run_id)
        if imported_coordination_run_id
        else None
    )
    imported_state = (
        task_run_loop.langgraph_coordination_runtime.checkpoints.get_state(thread_id=imported_coordination_run_id)
        if imported_coordination_run_id
        else {}
    )
    merge_result = (
        task_run_loop.state_index.get_latest_coordination_merge_result(imported_coordination_run_id)
        if imported_coordination_run_id
        else None
    )
    imported_terminal_status = _graph_module_imported_terminal_status(
        imported_task_run=imported_task_run,
        imported_coordination_run=imported_coordination_run,
        imported_state=imported_state,
        merge_result=merge_result,
    )
    if imported_terminal_status in {"failed", "blocked", "waiting_for_human"}:
        return _graph_module_imported_failure_packet(
            imported_task_run=imported_task_run,
            diagnostics=diagnostics,
            imported_coordination_run_id=imported_coordination_run_id,
            imported_coordination_run=imported_coordination_run,
            imported_state=imported_state,
            imported_terminal_status=imported_terminal_status,
        )
    if imported_terminal_status != "completed":
        return {}
    checkpoint = task_run_loop.checkpoints.load_latest(imported_task_run.task_run_id)
    checkpoint_task_result = dict(getattr(checkpoint, "commit_state", {}) or {}).get("task_result") if checkpoint is not None else {}
    checkpoint_task_result = dict(checkpoint_task_result or {})
    stage_results = {
        str(key): dict(value)
        for key, value in dict(imported_state.get("stage_results") or {}).items()
        if str(key) and isinstance(value, dict)
    }
    artifact_refs = _dedupe_strings(
        [
            *[
                str(ref)
                for result in stage_results.values()
                for ref in list(result.get("artifact_refs") or [])
                if str(ref)
            ],
            *[
                str(ref)
                for ref in list(checkpoint_task_result.get("output_refs") or [])
                if str(ref).startswith("artifact:")
            ],
        ]
    )
    output_refs = _dedupe_strings(
        [
            *artifact_refs,
            *[str(ref) for result in stage_results.values() for ref in list(dict(result.get("outputs") or {}).get("output_refs") or []) if str(ref)],
            *[str(ref) for ref in list(checkpoint_task_result.get("output_refs") or []) if str(ref)],
        ]
    )
    final_result_ref = str(
        dict(imported_state or {}).get("final_result_ref")
        or getattr(merge_result, "final_result_ref", "")
        or checkpoint_task_result.get("result_id")
        or imported_task_run.latest_checkpoint_ref
        or imported_task_run.task_run_id
        or ""
    )
    result_refs = _dedupe_strings(
        [
            final_result_ref,
            str(getattr(merge_result, "merge_result_id", "") or ""),
            *[str(ref) for ref in list(checkpoint_task_result.get("result_refs") or []) if str(ref)],
        ]
    )
    imported_flow = dict(dict(getattr(imported_coordination_run, "diagnostics", {}) or {}).get("coordination_flow") or {})
    stage_summaries = [
        {
            "stage_id": str(stage_id),
            "task_result_ref": str(result.get("task_result_ref") or ""),
            "artifact_refs": list(result.get("artifact_refs") or []),
            "accepted": bool(result.get("accepted") is True),
        }
        for stage_id, result in stage_results.items()
    ]
    artifact_refs_by_stage = {
        str(stage_id): [
            str(ref)
            for ref in list(result.get("artifact_refs") or [])
            if str(ref).startswith("artifact:")
        ]
        for stage_id, result in stage_results.items()
    }
    core_artifact_refs = _graph_module_core_artifact_refs(
        artifact_refs_by_stage=artifact_refs_by_stage,
        all_artifact_refs=artifact_refs,
    )
    handle = dict(diagnostics.get("importing_graph_module_runtime_handle") or {})
    if not handle:
        handle = {
            key: diagnostics.get(key)
            for key in (
                "graph_module_runtime_handle_id",
                "linked_graph_id",
                "importing_graph_id",
                "importing_coordination_run_id",
                "importing_root_task_run_id",
                "importing_stage_id",
                "importing_node_id",
            )
            if diagnostics.get(key) is not None
        }
    return {
        "authority": "orchestration.graph_module_committed_output_packet",
        "packet_id": f"graph-module-output:{_hash_payload({'importing': diagnostics.get('importing_coordination_run_id'), 'stage': diagnostics.get('importing_stage_id'), 'imported': imported_task_run.task_run_id})}",
        "status": "completed",
        "accepted": True,
        "importing_coordination_run_id": str(diagnostics.get("importing_coordination_run_id") or ""),
        "importing_root_task_run_id": str(diagnostics.get("importing_root_task_run_id") or ""),
        "importing_stage_id": str(diagnostics.get("importing_stage_id") or ""),
        "importing_node_id": str(diagnostics.get("importing_node_id") or ""),
        "importing_stage_request_id": str(diagnostics.get("importing_stage_request_id") or ""),
        "importing_stage_idempotency_key": str(diagnostics.get("importing_stage_idempotency_key") or ""),
        "imported_task_run_id": imported_task_run.task_run_id,
        "imported_coordination_run_id": imported_coordination_run_id,
        "linked_graph_id": str(diagnostics.get("linked_graph_id") or ""),
        "graph_module_runtime_handle_id": str(diagnostics.get("graph_module_runtime_handle_id") or ""),
        "graph_module_runtime_plan_id": str(handle.get("graph_module_runtime_plan_id") or ""),
        "handoff_contract_id": str(handle.get("handoff_contract_id") or ""),
        "input_port_id": str(handle.get("input_port_id") or ""),
        "output_port_id": str(handle.get("output_port_id") or ""),
        "isolation_policy": str(handle.get("isolation_policy") or "isolated_per_graph_module_run"),
        "visibility_policy": str(handle.get("visibility_policy") or "committed_only"),
        "detach_policy": str(handle.get("detach_policy") or "preserve_version_anchor"),
        "final_result_ref": final_result_ref,
        "merge_result_ref": str(getattr(merge_result, "merge_result_id", "") or ""),
        "artifact_refs": artifact_refs,
        "artifact_refs_by_stage": artifact_refs_by_stage,
        "core_artifact_refs": core_artifact_refs,
        "output_refs": output_refs,
        "result_refs": result_refs,
        "outputs": {
            "graph_module_output_packet_id": f"graph-module-output:{_hash_payload({'importing': diagnostics.get('importing_coordination_run_id'), 'stage': diagnostics.get('importing_stage_id'), 'imported': imported_task_run.task_run_id})}",
            "imported_task_run_id": imported_task_run.task_run_id,
            "imported_coordination_run_id": imported_coordination_run_id,
            "linked_graph_id": str(diagnostics.get("linked_graph_id") or ""),
            "final_result_ref": final_result_ref,
            "merge_result_ref": str(getattr(merge_result, "merge_result_id", "") or ""),
            "artifact_refs": artifact_refs,
            "artifact_refs_by_stage": artifact_refs_by_stage,
            "core_artifact_refs": core_artifact_refs,
            "output_refs": output_refs,
        },
        "imported_summary": {
            "task_run_status": str(imported_task_run.status or ""),
            "task_run_terminal_reason": str(imported_task_run.terminal_reason or ""),
            "coordination_status": str(getattr(imported_coordination_run, "status", "") or ""),
            "coordination_terminal_status": str(imported_state.get("terminal_status") or imported_flow.get("terminal_status") or ""),
            "completed_stage_ids": list(imported_flow.get("completed_stage_ids") or imported_state.get("completed_nodes") or []),
            "stage_result_count": len(stage_results),
            "stage_results": stage_summaries,
        },
        "created_at": time.time(),
    }


def _graph_module_imported_failure_packet(
    *,
    imported_task_run: TaskRun,
    diagnostics: dict[str, Any],
    imported_coordination_run_id: str,
    imported_coordination_run: Any,
    imported_state: dict[str, Any],
    imported_terminal_status: str,
) -> dict[str, Any]:
    imported_flow = dict(dict(getattr(imported_coordination_run, "diagnostics", {}) or {}).get("coordination_flow") or {})
    handle = dict(diagnostics.get("importing_graph_module_runtime_handle") or {})
    if not handle:
        handle = {
            key: diagnostics.get(key)
            for key in (
                "graph_module_runtime_handle_id",
                "linked_graph_id",
                "importing_graph_id",
                "importing_coordination_run_id",
                "importing_root_task_run_id",
                "importing_stage_id",
                "importing_node_id",
            )
            if diagnostics.get(key) is not None
        }
    failed_stage_ids = _dedupe_strings(
        [
            *list(imported_state.get("failed_nodes") or []),
            *list(imported_flow.get("failed_stage_ids") or []),
        ]
    )
    blocked_stage_ids = _dedupe_strings(
        [
            *list(imported_state.get("blocked_nodes") or []),
            *list(imported_flow.get("blocked_stage_ids") or []),
        ]
    )
    packet_id = f"graph-module-failure:{_hash_payload({'importing': diagnostics.get('importing_coordination_run_id'), 'stage': diagnostics.get('importing_stage_id'), 'imported': imported_task_run.task_run_id, 'status': imported_terminal_status})}"
    return {
        "authority": "orchestration.graph_module_committed_failure_packet",
        "packet_id": packet_id,
        "status": imported_terminal_status or "failed",
        "accepted": False,
        "importing_coordination_run_id": str(diagnostics.get("importing_coordination_run_id") or ""),
        "importing_root_task_run_id": str(diagnostics.get("importing_root_task_run_id") or ""),
        "importing_stage_id": str(diagnostics.get("importing_stage_id") or ""),
        "importing_node_id": str(diagnostics.get("importing_node_id") or ""),
        "importing_stage_request_id": str(diagnostics.get("importing_stage_request_id") or ""),
        "importing_stage_idempotency_key": str(diagnostics.get("importing_stage_idempotency_key") or ""),
        "imported_task_run_id": imported_task_run.task_run_id,
        "imported_coordination_run_id": imported_coordination_run_id,
        "linked_graph_id": str(diagnostics.get("linked_graph_id") or ""),
        "graph_module_runtime_handle_id": str(diagnostics.get("graph_module_runtime_handle_id") or ""),
        "graph_module_runtime_plan_id": str(handle.get("graph_module_runtime_plan_id") or ""),
        "handoff_contract_id": str(handle.get("handoff_contract_id") or ""),
        "input_port_id": str(handle.get("input_port_id") or ""),
        "output_port_id": str(handle.get("output_port_id") or ""),
        "isolation_policy": str(handle.get("isolation_policy") or "isolated_per_graph_module_run"),
        "visibility_policy": str(handle.get("visibility_policy") or "committed_only"),
        "detach_policy": str(handle.get("detach_policy") or "preserve_version_anchor"),
        "final_result_ref": str(imported_state.get("final_result_ref") or imported_task_run.latest_checkpoint_ref or imported_task_run.task_run_id or ""),
        "artifact_refs": [],
        "output_refs": [],
        "result_refs": _dedupe_strings([str(imported_state.get("final_result_ref") or ""), imported_task_run.latest_checkpoint_ref, imported_task_run.task_run_id]),
        "outputs": {
            "graph_module_failure_packet_id": packet_id,
            "imported_task_run_id": imported_task_run.task_run_id,
            "imported_coordination_run_id": imported_coordination_run_id,
            "linked_graph_id": str(diagnostics.get("linked_graph_id") or ""),
            "terminal_status": imported_terminal_status or "failed",
            "failed_stage_ids": failed_stage_ids,
            "blocked_stage_ids": blocked_stage_ids,
        },
        "imported_summary": {
            "task_run_status": str(imported_task_run.status or ""),
            "task_run_terminal_reason": str(imported_task_run.terminal_reason or ""),
            "coordination_status": str(getattr(imported_coordination_run, "status", "") or ""),
            "coordination_terminal_status": str(imported_state.get("terminal_status") or imported_flow.get("terminal_status") or imported_terminal_status),
            "failed_stage_ids": failed_stage_ids,
            "blocked_stage_ids": blocked_stage_ids,
        },
        "created_at": time.time(),
    }


def _graph_module_imported_terminal_status(
    *,
    imported_task_run: TaskRun,
    imported_coordination_run: Any,
    imported_state: dict[str, Any],
    merge_result: Any,
) -> str:
    if merge_result is not None and getattr(merge_result, "accepted", False) is True:
        return "completed"
    state_terminal = str(imported_state.get("terminal_status") or "").strip()
    if state_terminal in {"completed", "failed", "blocked", "waiting_for_human"}:
        return state_terminal
    coordination_status = str(getattr(imported_coordination_run, "status", "") or "").strip()
    if coordination_status in {"completed", "failed", "blocked", "waiting"}:
        return "completed" if coordination_status == "completed" else coordination_status
    return ""


def _mark_graph_module_imported_output_packet_committed(
    *,
    task_run_loop: Any,
    imported_task_run_id: str,
    packet_ref: str,
    packet: dict[str, Any],
) -> None:
    if not imported_task_run_id or not packet_ref:
        return
    imported_run = task_run_loop.state_index.get_task_run(imported_task_run_id)
    if imported_run is None:
        return
    diagnostics = dict(imported_run.diagnostics or {})
    committed_key = "graph_module_output_packet_committed" if bool(packet.get("accepted") is True) else "graph_module_failure_packet_committed"
    diagnostics[committed_key] = {
        "packet_ref": packet_ref,
        "packet_id": str(packet.get("packet_id") or ""),
        "status": str(packet.get("status") or ""),
        "accepted": bool(packet.get("accepted") is True),
        "importing_coordination_run_id": str(packet.get("importing_coordination_run_id") or ""),
        "importing_stage_id": str(packet.get("importing_stage_id") or ""),
        "imported_coordination_run_id": str(packet.get("imported_coordination_run_id") or ""),
        "linked_graph_id": str(packet.get("linked_graph_id") or ""),
        "committed_at": time.time(),
    }
    task_run_loop.state_index.upsert_task_run(
        TaskRun(
            task_run_id=imported_run.task_run_id,
            session_id=imported_run.session_id,
            task_id=imported_run.task_id,
            task_contract_ref=imported_run.task_contract_ref,
            owner_agent_seat_id=imported_run.owner_agent_seat_id,
            agent_id=imported_run.agent_id,
            agent_profile_id=imported_run.agent_profile_id,
            runtime_lane=imported_run.runtime_lane,
            status=imported_run.status,
            created_at=imported_run.created_at,
            updated_at=time.time(),
            latest_event_offset=imported_run.latest_event_offset,
            latest_checkpoint_ref=imported_run.latest_checkpoint_ref,
            terminal_reason=imported_run.terminal_reason,
            diagnostics=diagnostics,
        )
    )


def _graph_module_output_packet_object_id(
    *,
    importing_coordination_run_id: str,
    importing_stage_id: str,
    imported_task_run_id: str,
) -> str:
    return _safe_path_component(
        "graph-module-output-"
        + _hash_payload(
            {
                "importing_coordination_run_id": importing_coordination_run_id,
                "importing_stage_id": importing_stage_id,
                "imported_task_run_id": imported_task_run_id,
            }
        )
    )


def _dedupe_strings(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in values:
        value = str(item or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _graph_module_core_artifact_refs(
    *,
    artifact_refs_by_stage: dict[str, list[str]],
    all_artifact_refs: list[str],
) -> list[str]:
    priority_stage_ids = [
        "project_brief",
        "world_design",
        "world_review",
        "memory_commit_world",
        "character_design",
        "plot_design",
        "design_sync",
        "outline_design",
        "outline_review",
        "baseline_memory_seed",
        "volume_plan",
        "chapter_outline",
        "chapter_draft",
        "chapter_review",
        "memory_commit_chapter",
        "volume_review",
        "volume_commit",
    ]
    selected: list[str] = []
    for stage_id in priority_stage_ids:
        selected.extend(
            ref
            for ref in list(artifact_refs_by_stage.get(stage_id) or [])
            if _graph_module_core_artifact_ref(ref)
        )
    if not selected:
        selected.extend(ref for ref in all_artifact_refs if _graph_module_core_artifact_ref(ref))
    return _dedupe_strings(selected)


def _graph_module_core_artifact_ref(ref: str) -> bool:
    normalized = str(ref or "").replace("\\", "/").lower()
    if not normalized.startswith("artifact:"):
        return False
    if "/debug/" in normalized or "run_report_" in normalized:
        return False
    return normalized.endswith(".md")


def _hash_payload(payload: Any) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def _read_first_artifact_text(*, runtime: Any, artifact_refs: list[str]) -> str:
    root_dir = getattr(runtime.query_runtime.task_run_loop, "root_dir", None)
    if root_dir is None:
        return ""
    root_path = root_dir if hasattr(root_dir, "exists") else None
    candidate_roots = []
    if root_path is not None:
        candidate_roots.extend([root_path, root_path.parent, root_path.parent.parent])
    for ref in artifact_refs:
        raw = str(ref or "")
        if not raw.startswith("artifact:"):
            continue
        rel = raw[len("artifact:") :]
        paths = []
        try:
            paths.append(__import__("pathlib").Path(rel))
        except Exception:
            paths = []
        for base in candidate_roots:
            try:
                paths.append(base / rel)
            except TypeError:
                continue
        for path in paths:
            try:
                if path.exists() and path.is_file():
                    return path.read_text(encoding="utf-8")
            except OSError:
                continue
    return ""


def _is_review_gate_contract(contract: dict[str, Any]) -> bool:
    node_type = str(contract.get("node_type") or "").strip()
    gate_policy = str(contract.get("gate_policy") or "").strip()
    return node_type == "review_gate" or gate_policy == "review_gate" or bool(dict(contract.get("review_gate_policy") or {}))


def _recovery_stage_business_acceptance(
    *,
    stage_id: str,
    contract: dict[str, Any],
    explicit_inputs: dict[str, Any],
    final_content: str,
    output_refs: list[str],
    terminal_status: str,
) -> dict[str, Any]:
    merged_contract = _recovery_acceptance_contract(stage_id=stage_id, contract=contract)
    acceptance = _stage_business_acceptance(
        stage_id=stage_id,
        contract=merged_contract,
        explicit_inputs=explicit_inputs,
        final_content=final_content,
        output_refs=output_refs,
        terminal_status=terminal_status,
        requires_file_artifact_refs=bool(dict(merged_contract.get("artifact_policy") or {}).get("enabled")),
    )
    issues = [str(item) for item in list(acceptance.get("issues") or []) if str(item)]
    missing_indexes = list(acceptance.get("missing_unit_indexes") or [])
    return {
        **acceptance,
        "stage_business_acceptance": acceptance,
        "review_verdict": str(acceptance.get("verdict") or ""),
        "accepted_by_recovery_quality_gate": bool(acceptance.get("accepted") is True),
        "recovery_quality_issues": issues,
        "chapter_words": int(acceptance.get("content_metric_total") or acceptance.get("raw_content_metric_total") or 0),
        "expected_chapter_indexes": list(acceptance.get("expected_unit_indexes") or []),
        "found_chapter_indexes": list(acceptance.get("found_unit_indexes") or []),
        "missing_chapter_indexes": missing_indexes,
        "recovered_from_completed_stage_task_run": True,
    }


def _recovery_acceptance_contract(*, stage_id: str, contract: dict[str, Any]) -> dict[str, Any]:
    if str(stage_id or "").strip() != "chapter_draft":
        return dict(contract or {})
    quality_policy = {
        "acceptance_policies": ["sectioned_text_batch_quality"],
        "unit_count_key": "chapters_per_round",
        "unit_start_key": "batch_start_index",
        "unit_end_key": "batch_end_index",
        "unit_index_key": "chapter_index",
        "target_metric_key": "batch_target_words",
        "unit_target_metric_key": "chapter_target_words",
        "minimum_metric_ratio": 0.55,
        "minimum_metric_per_unit": 1200,
        "required_heading_patterns": [r"第\s*(?P<index>[0-9一二三四五六七八九十百零〇两]+)\s*[章节回]"],
        "heading_match_scope": "anywhere",
    }
    existing_policy = dict(dict(contract or {}).get("quality_retry_policy") or {})
    return {
        **dict(contract or {}),
        "quality_retry_policy": {
            **quality_policy,
            **existing_policy,
            "acceptance_policies": list(
                dict.fromkeys(
                    [
                        "sectioned_text_batch_quality",
                        *[
                            str(item)
                            for item in list(existing_policy.get("acceptance_policies") or [])
                            if str(item)
                        ],
                    ]
                )
            ),
        },
    }

