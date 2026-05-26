from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from ..shared.models import TaskRun
from .models import GraphModuleResultPacketCandidate


def latest_unconsumed_graph_module_imported_result(
    *,
    runtime: Any,
    session_id: str,
    state: dict[str, Any],
    active_stage_id: str,
    coordination_run_id: str,
) -> dict[str, Any]:
    graph_task_runtime = runtime.query_runtime.graph_task_runtime
    if not active_stage_id or not active_stage_is_graph_module(state=state, active_stage_id=active_stage_id):
        return {}
    stage_results = dict(state.get("stage_results") or {})
    already_consumed_task_run_id = str(dict(stage_results.get(active_stage_id) or {}).get("task_run_id") or "").strip()
    current_stage_payload = dict(state.get("node_work_order") or state.get("stage_execution_request") or {})
    active_task_ref = str(
        current_stage_payload.get("task_ref")
        or dict(dict(state.get("stage_contracts") or {}).get(active_stage_id) or {}).get("task_ref")
        or state.get("active_task_ref")
        or ""
    ).strip()
    active_request_id = str(current_stage_payload.get("request_id") or current_stage_payload.get("work_order_id") or "").strip()
    active_idempotency_key = str(current_stage_payload.get("idempotency_key") or "").strip()
    pending_inputs = dict(state.get("pending_inputs") or {})
    candidates: list[tuple[float, TaskRun, dict[str, Any], dict[str, Any]]] = []
    for imported_run in graph_task_runtime.list_session_task_runs(session_id):
        if str(imported_run.task_run_id or "") == already_consumed_task_run_id:
            continue
        diagnostics = dict(imported_run.diagnostics or {})
        if diagnostics.get("graph_module_imported_run") is not True:
            continue
        if str(diagnostics.get("importing_coordination_run_id") or "").strip() != coordination_run_id:
            continue
        if str(diagnostics.get("importing_stage_id") or diagnostics.get("stage_id") or "").strip() != active_stage_id:
            continue
        imported_request_id = str(diagnostics.get("importing_work_order_id") or "").strip()
        imported_idempotency_key = str(diagnostics.get("importing_stage_request_ref") or "").strip()
        if active_request_id and imported_request_id and imported_request_id != active_request_id:
            continue
        if (
            active_idempotency_key
            and imported_idempotency_key
            and imported_idempotency_key not in {active_idempotency_key, active_request_id}
        ):
            continue
        committed = graph_module_imported_packet_consumption(
            graph_task_runtime=graph_task_runtime,
            importing_coordination_run_id=coordination_run_id,
            importing_stage_id=active_stage_id,
            imported_task_run_id=imported_run.task_run_id,
        )
        if committed and str(committed.get("packet_ref") or "").strip():
            continue
        completion = graph_module_imported_completion_packet(
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
    packet_ref = graph_task_runtime.put_runtime_object(
        packet_collection,
        graph_module_output_packet_object_id(
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
            "authority": "runtime.subruntime.graph_module_output_packet_result",
            "graph_module_output_packet_ref": packet_ref,
            "graph_module_output_packet": packet,
            "linked_graph_id": str(packet.get("linked_graph_id") or ""),
            "imported_coordination_run_id": str(packet.get("imported_coordination_run_id") or ""),
        },
    }
    return GraphModuleResultPacketCandidate(
        imported_task_run_id=imported_run.task_run_id,
        packet=packet,
        packet_ref=packet_ref,
        task_result=task_result,
        explicit_inputs=pending_inputs,
        artifact_root=str(pending_inputs.get("artifact_root") or ""),
        event={
            "event_type": "task_result_ready",
            "coordination_run_id": coordination_run_id,
            "task_run_id": imported_run.task_run_id,
            "stage_id": active_stage_id,
            "task_ref": active_task_ref or str(diagnostics.get("importing_task_ref") or imported_run.task_id or ""),
            "task_result_ref": packet_ref,
            "artifact_refs": tuple(artifact_refs or [packet_ref]),
            "accepted": bool(packet.get("accepted") is True),
            "agent_run_result_ref": "",
            "request_id": active_request_id or str(diagnostics.get("importing_work_order_id") or ""),
            "dispatch_event_id": str(diagnostics.get("importing_dispatch_event_id") or ""),
            "diagnostics": {
                "authority": "runtime.subruntime.graph_module_committed_output_packet" if bool(packet.get("accepted") is True) else "runtime.subruntime.graph_module_committed_failure_packet",
                "graph_module_output_packet_ref": packet_ref,
                "graph_module_output_packet": packet,
                "graph_module_imported_run": True,
                "imported_task_run_id": imported_run.task_run_id,
                "imported_coordination_run_id": str(packet.get("imported_coordination_run_id") or ""),
                "linked_graph_id": str(packet.get("linked_graph_id") or ""),
                "terminal_reason": str(imported_run.terminal_reason or "completed"),
            },
        },
    ).to_dict()


def active_stage_is_graph_module(*, state: dict[str, Any], active_stage_id: str) -> bool:
    work_order_payload = dict(state.get("node_work_order") or {})
    request_payload = dict(state.get("stage_execution_request") or {})
    if str(work_order_payload.get("work_kind") or "") == "subruntime":
        return True
    if str(work_order_payload.get("subruntime_kind") or "") == "graph_module":
        return True
    if str(request_payload.get("executor_type") or "") == "graph_module":
        return True
    contract = dict(dict(state.get("stage_contracts") or {}).get(active_stage_id) or {})
    if str(contract.get("node_type") or "") == "graph_module":
        return True
    metadata = dict(contract.get("metadata") or {})
    executor_policy = dict(contract.get("executor_policy") or {})
    return bool(metadata.get("graph_module")) or str(executor_policy.get("default_executor") or "") == "graph_module"


def graph_module_imported_completion_packet(
    *,
    runtime: Any,
    imported_task_run: TaskRun,
    diagnostics: dict[str, Any],
) -> dict[str, Any]:
    graph_task_runtime = runtime.query_runtime.graph_task_runtime
    imported_coordination_run_id = str(diagnostics.get("imported_coordination_run_id") or "").strip()
    if not imported_coordination_run_id:
        for coordination_run in graph_task_runtime.list_task_coordination_runs(imported_task_run.task_run_id):
            imported_coordination_run_id = coordination_run.coordination_run_id
            break
    imported_coordination_run = (
        graph_task_runtime.get_coordination_run(imported_coordination_run_id)
        if imported_coordination_run_id
        else None
    )
    imported_state = (
        graph_task_runtime.get_checkpoint_state(imported_coordination_run_id)
        if imported_coordination_run_id
        else {}
    )
    merge_result = (
        graph_task_runtime.get_latest_coordination_merge_result(imported_coordination_run_id)
        if imported_coordination_run_id
        else None
    )
    imported_terminal_status = graph_module_imported_terminal_status(
        imported_task_run=imported_task_run,
        imported_coordination_run=imported_coordination_run,
        imported_state=imported_state,
        merge_result=merge_result,
    )
    if imported_terminal_status in {"failed", "blocked", "waiting_for_human"}:
        return graph_module_imported_failure_packet(
            imported_task_run=imported_task_run,
            diagnostics=diagnostics,
            imported_coordination_run_id=imported_coordination_run_id,
            imported_coordination_run=imported_coordination_run,
            imported_state=imported_state,
            imported_terminal_status=imported_terminal_status,
        )
    if imported_terminal_status != "completed":
        return {}
    checkpoint = graph_task_runtime.load_latest_task_checkpoint(imported_task_run.task_run_id)
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
    core_artifact_refs = graph_module_core_artifact_refs(
        artifact_refs_by_stage=artifact_refs_by_stage,
        all_artifact_refs=artifact_refs,
        stage_order=list(stage_results.keys()),
    )
    handle = _graph_module_handle_from_diagnostics(diagnostics)
    packet_id = f"graph-module-output:{_hash_payload({'importing': diagnostics.get('importing_coordination_run_id'), 'stage': diagnostics.get('importing_stage_id'), 'imported': imported_task_run.task_run_id})}"
    return {
        "authority": "runtime.subruntime.graph_module_output_packet",
        "packet_id": packet_id,
        "status": "completed",
        "accepted": True,
        "importing_coordination_run_id": str(diagnostics.get("importing_coordination_run_id") or ""),
        "importing_root_task_run_id": str(diagnostics.get("importing_root_task_run_id") or ""),
        "importing_stage_id": str(diagnostics.get("importing_stage_id") or ""),
        "importing_node_id": str(diagnostics.get("importing_node_id") or ""),
        "importing_work_order_id": str(diagnostics.get("importing_work_order_id") or ""),
        "importing_stage_request_ref": str(diagnostics.get("importing_stage_request_ref") or ""),
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
            "graph_module_output_packet_id": packet_id,
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


def graph_module_imported_failure_packet(
    *,
    imported_task_run: TaskRun,
    diagnostics: dict[str, Any],
    imported_coordination_run_id: str,
    imported_coordination_run: Any,
    imported_state: dict[str, Any],
    imported_terminal_status: str,
) -> dict[str, Any]:
    imported_flow = dict(dict(getattr(imported_coordination_run, "diagnostics", {}) or {}).get("coordination_flow") or {})
    handle = _graph_module_handle_from_diagnostics(diagnostics)
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
        "authority": "runtime.subruntime.graph_module_failure_packet",
        "packet_id": packet_id,
        "status": imported_terminal_status or "failed",
        "accepted": False,
        "importing_coordination_run_id": str(diagnostics.get("importing_coordination_run_id") or ""),
        "importing_root_task_run_id": str(diagnostics.get("importing_root_task_run_id") or ""),
        "importing_stage_id": str(diagnostics.get("importing_stage_id") or ""),
        "importing_node_id": str(diagnostics.get("importing_node_id") or ""),
        "importing_work_order_id": str(diagnostics.get("importing_work_order_id") or ""),
        "importing_stage_request_ref": str(diagnostics.get("importing_stage_request_ref") or ""),
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


def graph_module_imported_terminal_status(
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


def mark_graph_module_imported_output_packet_committed(
    *,
    graph_task_runtime: Any,
    imported_task_run_id: str,
    packet_ref: str,
    packet: dict[str, Any],
) -> dict[str, Any]:
    if not imported_task_run_id or not packet_ref:
        return {}
    record = {
        "packet_ref": packet_ref,
        "packet_id": str(packet.get("packet_id") or ""),
        "status": str(packet.get("status") or ""),
        "accepted": bool(packet.get("accepted") is True),
        "importing_coordination_run_id": str(packet.get("importing_coordination_run_id") or ""),
        "importing_stage_id": str(packet.get("importing_stage_id") or ""),
        "imported_coordination_run_id": str(packet.get("imported_coordination_run_id") or ""),
        "linked_graph_id": str(packet.get("linked_graph_id") or ""),
        "committed_at": time.time(),
        "authority": "runtime.subruntime.graph_module_packet_consumption",
    }
    object_id = graph_module_packet_consumption_object_id(
        importing_coordination_run_id=record["importing_coordination_run_id"],
        importing_stage_id=record["importing_stage_id"],
        imported_task_run_id=imported_task_run_id,
    )
    record["consumption_ref"] = graph_task_runtime.put_runtime_object(
        "graph_module_packet_consumptions",
        object_id,
        record,
    )
    return record


def graph_module_imported_packet_consumption(
    *,
    graph_task_runtime: Any,
    importing_coordination_run_id: str,
    importing_stage_id: str,
    imported_task_run_id: str,
) -> dict[str, Any]:
    if not importing_coordination_run_id or not importing_stage_id or not imported_task_run_id:
        return {}
    object_id = graph_module_packet_consumption_object_id(
        importing_coordination_run_id=importing_coordination_run_id,
        importing_stage_id=importing_stage_id,
        imported_task_run_id=imported_task_run_id,
    )
    try:
        return graph_task_runtime.get_runtime_object(f"rtobj:graph_module_packet_consumptions:{object_id}")
    except (OSError, ValueError):
        return {}


def graph_module_output_packet_object_id(
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


def graph_module_packet_consumption_object_id(
    *,
    importing_coordination_run_id: str,
    importing_stage_id: str,
    imported_task_run_id: str,
) -> str:
    return _safe_path_component(
        "graph-module-packet-consumption-"
        + _hash_payload(
            {
                "importing_coordination_run_id": importing_coordination_run_id,
                "importing_stage_id": importing_stage_id,
                "imported_task_run_id": imported_task_run_id,
            }
        )
    )


def graph_module_core_artifact_refs(
    *,
    artifact_refs_by_stage: dict[str, list[str]],
    all_artifact_refs: list[str],
    stage_order: list[str] | tuple[str, ...] = (),
) -> list[str]:
    priority_stage_ids = [str(item) for item in list(stage_order or artifact_refs_by_stage.keys()) if str(item)]
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


def _graph_module_handle_from_diagnostics(diagnostics: dict[str, Any]) -> dict[str, Any]:
    handle = dict(diagnostics.get("importing_graph_module_runtime_handle") or {})
    if handle:
        return handle
    return {
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


def _safe_path_component(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in str(value or ""))[:180]
