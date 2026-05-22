from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from ..execution.node_handoff_protocol import build_node_executor_binding
from .result_helpers import (
    _contract_has_required_artifact_outputs,
    _contract_requires_file_artifact_refs,
    _node_result_output_bundle,
    _required_artifact_outputs_satisfied,
    _structured_outputs_from_output_bundle,
)
from .runtime_payloads import _safe_id, _safe_int


@dataclass(frozen=True, slots=True)
class NodeResultAcceptanceDraft:
    stage_id: str
    node_id: str
    event: dict[str, Any]
    contract: dict[str, Any]
    request_payload: dict[str, Any]
    result_request_payload: dict[str, Any]
    stage_scope: dict[str, Any]
    dispatch_context: dict[str, Any]
    raw_refs: list[str]
    artifact_refs: list[str]
    trace_refs: list[str]
    mapped_outputs: dict[str, Any]
    output_bundle: dict[str, Any]
    stage_outputs: dict[str, Any]
    output_mappings: list[dict[str, Any]]
    requires_file_artifact_refs: bool
    required_artifact_outputs_satisfied: bool
    accepted: bool
    commit_identity: str = ""
    committed_identities: set[str] = field(default_factory=set)

    def validation_result(self, *, event_accepts_artifacts: bool) -> dict[str, Any]:
        return {
            "required_artifact_outputs_satisfied": self.required_artifact_outputs_satisfied
            if event_accepts_artifacts
            else not _contract_has_required_artifact_outputs(
                self.output_mappings,
                requires_file_artifact_refs=self.requires_file_artifact_refs,
            ),
            "requires_file_artifact_refs": self.requires_file_artifact_refs,
        }


def build_node_result_acceptance_draft(
    *,
    state: dict[str, Any],
    event: dict[str, Any],
    stage_id: str,
    contract: dict[str, Any],
    request_payload: dict[str, Any],
    stage_scope: dict[str, Any],
    event_accepted_by_policy: bool,
    committed_identities: list[str] | set[str] | tuple[str, ...],
) -> NodeResultAcceptanceDraft:
    node_id = str(contract.get("node_id") or stage_id)
    raw_refs = [str(item) for item in list(event.get("artifact_refs") or []) if str(item)]
    requires_file_artifact_refs = _contract_requires_file_artifact_refs(contract)
    if requires_file_artifact_refs:
        artifact_refs = [item for item in raw_refs if _formal_file_artifact_ref(item)]
        trace_refs = [item for item in raw_refs if item not in artifact_refs]
    else:
        artifact_refs = raw_refs
        trace_refs = []
    output_mappings = [dict(item) for item in list(contract.get("output_mappings") or []) if isinstance(item, dict)]
    mapped_outputs = _mapped_outputs_from_artifact_refs(output_mappings, artifact_refs)
    output_bundle = _node_result_output_bundle(
        state=state,
        event=event,
        artifact_refs=artifact_refs,
        mapped_outputs=mapped_outputs,
    )
    stage_outputs = {
        **_structured_outputs_from_output_bundle(output_bundle),
        **mapped_outputs,
    }
    required_artifact_outputs_satisfied = _required_artifact_outputs_satisfied(
        output_mappings,
        artifact_refs,
        requires_file_artifact_refs=requires_file_artifact_refs,
    )
    accepted = bool(event.get("accepted") is True) and required_artifact_outputs_satisfied
    if event_accepted_by_policy:
        accepted = True
    result_request_payload = build_stage_result_request_payload(
        state=state,
        request_payload=request_payload,
        event=event,
        stage_id=stage_id,
        node_id=node_id,
        contract=contract,
        stage_scope=stage_scope,
    )
    result_explicit_inputs = dict(result_request_payload.get("explicit_inputs") or state.get("pending_inputs") or {})
    commit_identity = stage_commit_identity(
        stage_id=stage_id,
        contract=contract,
        explicit_inputs=result_explicit_inputs,
        artifact_refs=artifact_refs,
    )
    return NodeResultAcceptanceDraft(
        stage_id=stage_id,
        node_id=node_id,
        event=dict(event),
        contract=dict(contract),
        request_payload=dict(request_payload),
        result_request_payload=result_request_payload,
        stage_scope=dict(stage_scope),
        dispatch_context=dict(result_request_payload.get("dispatch_context") or request_payload.get("dispatch_context") or {}),
        raw_refs=raw_refs,
        artifact_refs=artifact_refs,
        trace_refs=trace_refs,
        mapped_outputs=mapped_outputs,
        output_bundle=output_bundle,
        stage_outputs=stage_outputs,
        output_mappings=output_mappings,
        requires_file_artifact_refs=requires_file_artifact_refs,
        required_artifact_outputs_satisfied=required_artifact_outputs_satisfied,
        accepted=accepted,
        commit_identity=commit_identity,
        committed_identities={str(item) for item in committed_identities if str(item)},
    )


def _formal_file_artifact_ref(ref: str) -> bool:
    ref_text = str(ref or "")
    if not ref_text.startswith("artifact:"):
        return False
    normalized = ref_text.replace("\\", "/")
    if "/debug/" in normalized or "run_report" in normalized:
        return False
    return True


def stale_result_reason(
    *,
    event: dict[str, Any],
    request_payload: dict[str, Any],
    stage_id: str,
    known_batch_execution: bool = False,
) -> str:
    event_request_id = str(event.get("request_id") or "").strip()
    event_dispatch_id = str(event.get("dispatch_event_id") or "").strip()
    if known_batch_execution:
        return ""
    if not request_payload:
        return "missing_active_stage_execution_request" if event_request_id or event_dispatch_id else ""
    active_stage_id = str(request_payload.get("stage_id") or "").strip()
    if active_stage_id and active_stage_id != stage_id and (event_request_id or event_dispatch_id):
        return "stage_id_does_not_match_active_request"
    active_request_id = str(request_payload.get("request_id") or "").strip()
    if event_request_id and active_request_id and event_request_id != active_request_id:
        return "request_id_does_not_match_active_request"
    active_dispatch_id = str(dict(request_payload.get("dispatch_context") or {}).get("dispatch_event_id") or "").strip()
    if event_dispatch_id and active_dispatch_id and event_dispatch_id != active_dispatch_id:
        return "dispatch_event_id_does_not_match_active_request"
    return ""


def active_execution_request_payload(state: dict[str, Any]) -> dict[str, Any]:
    work_order = dict(state.get("node_work_order") or {})
    if work_order:
        return request_compat_payload_from_work_order(work_order)
    return dict(state.get("node_execution_request") or state.get("stage_execution_request") or {})


def request_compat_payload_from_work_order(work_order: dict[str, Any]) -> dict[str, Any]:
    payload = dict(work_order or {})
    if not payload:
        return {}
    input_package = dict(payload.get("input_package") or payload.get("standard_input_package") or {})
    executor_type = str(payload.get("executor_type") or dict(payload.get("executor_binding") or {}).get("selected_executor") or "agent")
    if executor_type == "subruntime":
        executor_type = str(payload.get("subruntime_kind") or dict(payload.get("executor_binding") or {}).get("selected_executor") or "subruntime")
    return {
        **payload,
        "request_id": str(payload.get("request_id") or payload.get("work_order_id") or ""),
        "standard_input_package": input_package,
        "executor_type": executor_type,
        "authority": "task_graph.node_execution_request",
    }


def committed_stage_identities(state: dict[str, Any]) -> list[str]:
    identities = [
        str(item)
        for item in list(state.get("committed_stage_identities") or [])
        if str(item)
    ]
    if identities:
        return sorted(set(identities))
    diagnostics = dict(state.get("diagnostics") or {})
    return sorted(
        {
            str(item)
            for item in list(diagnostics.get("committed_stage_identities") or [])
            if str(item)
        }
    )


def build_stage_result_request_payload(
    *,
    state: dict[str, Any],
    request_payload: dict[str, Any],
    event: dict[str, Any],
    stage_id: str,
    node_id: str,
    contract: dict[str, Any],
    stage_scope: dict[str, Any],
) -> dict[str, Any]:
    if request_payload:
        return dict(request_payload)
    coordination_run_id = str(state.get("coordination_run_id") or event.get("coordination_run_id") or "")
    task_result_ref = str(event.get("task_result_ref") or event.get("agent_run_result_ref") or event.get("task_run_id") or "")
    identity_seed = f"{coordination_run_id}:{stage_id}:external_result:{task_result_ref}"
    activation_id = f"activation:{_safe_id(identity_seed)}"
    execution_permit_id = f"permit:{_safe_id(identity_seed)}"
    explicit_inputs = dict(state.get("pending_inputs") or {})
    dispatch_context = {
        "dispatch_event_id": str(event.get("dispatch_event_id") or ""),
        "clock_seq": 0,
        "scope_path": list(stage_scope.get("scope_path") or ["run"]),
        "scope_type": str(stage_scope.get("scope_type") or "stage"),
        "phase_id": str(stage_scope.get("phase_id") or ""),
        "dependency_scope_key": str(stage_scope.get("dependency_scope_key") or ""),
        "volume_index": _safe_int(stage_scope.get("volume_index"), 0),
        "batch_start_index": _safe_int(stage_scope.get("batch_start_index"), 0),
        "batch_end_index": _safe_int(stage_scope.get("batch_end_index"), 0),
        "round_index": _safe_int(stage_scope.get("round_index"), 0),
        "iteration_index": _safe_int(stage_scope.get("iteration_index"), 0),
        "node_id": node_id,
        "stage_id": stage_id,
        "thread_id": coordination_run_id,
        "coordination_run_id": coordination_run_id,
        "root_task_run_id": str(state.get("root_task_run_id") or event.get("task_run_id") or ""),
        "activation_id": activation_id,
        "execution_permit_id": execution_permit_id,
    }
    executor_binding = build_node_executor_binding(
        node_id=node_id,
        contract=contract,
        explicit_inputs=explicit_inputs,
        agent_profile_id="",
    )
    return {
        "request_id": str(event.get("request_id") or f"nodeexec:{_safe_id(identity_seed)}"),
        "coordination_run_id": coordination_run_id,
        "thread_id": coordination_run_id,
        "root_task_run_id": str(state.get("root_task_run_id") or event.get("task_run_id") or ""),
        "stage_id": stage_id,
        "node_id": node_id,
        "task_ref": str(contract.get("task_ref") or event.get("task_ref") or ""),
        "agent_id": str(contract.get("agent_id") or ""),
        "runtime_lane": str(contract.get("runtime_lane") or ""),
        "executor_type": executor_binding.selected_executor,
        "executor_binding": executor_binding.to_dict(),
        "explicit_inputs": explicit_inputs,
        "standard_input_package": {
            "coordination_run_id": coordination_run_id,
            "node_id": node_id,
            "stage_id": stage_id,
            "activation_id": activation_id,
            "execution_permit_id": execution_permit_id,
        },
        "dispatch_context": dispatch_context,
    }


def node_execution_boundary(execution_context: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(execution_context or {})
    dispatch_context = dict(payload.get("dispatch_context") or {})
    standard_input = dict(payload.get("standard_input_package") or {})
    coordination_run_id = _first_non_empty(
        payload.get("coordination_run_id"),
        dispatch_context.get("coordination_run_id"),
        standard_input.get("coordination_run_id"),
    )
    stage_id = _first_non_empty(payload.get("stage_id"), dispatch_context.get("stage_id"), standard_input.get("stage_id"))
    node_id = _first_non_empty(payload.get("node_id"), dispatch_context.get("node_id"), standard_input.get("node_id"), stage_id)
    activation_id = _first_non_empty(
        payload.get("activation_id"),
        dispatch_context.get("activation_id"),
        standard_input.get("activation_id"),
    )
    execution_permit_id = _first_non_empty(
        payload.get("execution_permit_id"),
        dispatch_context.get("execution_permit_id"),
        standard_input.get("execution_permit_id"),
    )
    request_id = _first_non_empty(payload.get("request_id"), standard_input.get("request_id"))
    dispatch_event_id = _first_non_empty(payload.get("dispatch_event_id"), dispatch_context.get("dispatch_event_id"))
    missing = [
        key
        for key, value in {
            "coordination_run_id": coordination_run_id,
            "stage_id": stage_id,
            "node_id": node_id,
            "activation_id": activation_id,
            "execution_permit_id": execution_permit_id,
            "request_id": request_id,
        }.items()
        if not value
    ]
    return {
        "coordination_run_id": coordination_run_id,
        "stage_id": stage_id,
        "node_id": node_id,
        "activation_id": activation_id,
        "execution_permit_id": execution_permit_id,
        "request_id": request_id,
        "dispatch_event_id": dispatch_event_id,
        "clock_seq": _safe_int(dispatch_context.get("clock_seq"), 0),
        "scope_path": [str(item) for item in list(dispatch_context.get("scope_path") or []) if str(item)],
        "valid": not missing,
        "missing": missing,
        "authority": "task_graph.node_execution_boundary",
    }


def stage_commit_identity(
    *,
    stage_id: str,
    contract: dict[str, Any],
    explicit_inputs: dict[str, Any],
    artifact_refs: list[str],
) -> str:
    policy = commit_identity_policy(contract)
    if not policy:
        return ""
    mode = str(policy.get("mode") or "input_keys_and_artifact_refs").strip()
    if mode in {"disabled", "none", "off"}:
        return ""
    namespace = str(policy.get("identity_namespace") or policy.get("namespace") or stage_id or "stage").strip()
    seed: dict[str, Any] = {
        "stage_id": stage_id,
        "namespace": namespace,
        "mode": mode,
    }

    input_keys = [str(item).strip() for item in list(policy.get("input_keys") or []) if str(item).strip()]
    if input_keys:
        seed["inputs"] = {key: explicit_inputs.get(key) for key in input_keys}
    elif mode in {"runtime_scope", "scope_and_artifact_refs"}:
        seed["inputs"] = runtime_scope_coordinate_from_inputs(explicit_inputs)

    source_refs = commit_identity_source_refs(
        policy=policy,
        explicit_inputs=explicit_inputs,
        artifact_refs=artifact_refs,
    )
    if source_refs:
        seed["source_refs"] = source_refs
    if not seed.get("inputs") and not source_refs:
        return ""
    return f"{namespace}:commitid:{short_hash(seed)}"


def commit_identity_policy(contract: dict[str, Any]) -> dict[str, Any]:
    for source in (
        dict(contract.get("memory_writeback_policy") or {}),
        dict(contract.get("artifact_policy") or {}),
        dict(contract.get("executor_policy") or {}),
        dict(contract.get("metadata") or {}),
    ):
        policy = source.get("commit_identity_policy")
        if isinstance(policy, dict) and policy:
            return dict(policy)
    return {}


def commit_identity_source_refs(
    *,
    policy: dict[str, Any],
    explicit_inputs: dict[str, Any],
    artifact_refs: list[str],
) -> list[str]:
    source_refs: list[str] = []
    exact_input_keys = [
        str(item).strip()
        for item in list(policy.get("artifact_ref_input_keys") or policy.get("source_ref_input_keys") or [])
        if str(item).strip()
    ]
    for key in exact_input_keys:
        source_refs.extend(artifact_refs_from_value(explicit_inputs.get(key)))

    suffixes = [
        str(item).strip()
        for item in list(policy.get("artifact_ref_input_suffixes") or [])
        if str(item).strip()
    ]
    prefixes = [
        str(item).strip()
        for item in list(policy.get("artifact_ref_input_prefixes") or [])
        if str(item).strip()
    ]
    contains = [
        str(item).strip()
        for item in list(policy.get("artifact_ref_input_contains") or [])
        if str(item).strip()
    ]
    if suffixes or prefixes or contains:
        for key, value in dict(explicit_inputs or {}).items():
            key_text = str(key or "")
            if (
                any(key_text.endswith(suffix) for suffix in suffixes)
                or any(key_text.startswith(prefix) for prefix in prefixes)
                or any(token in key_text for token in contains)
            ):
                source_refs.extend(artifact_refs_from_value(value))

    if bool(policy.get("include_result_artifact_refs") or policy.get("fallback_to_result_artifact_refs")):
        source_refs.extend(str(item) for item in list(artifact_refs or []) if str(item))
    return sorted({str(item) for item in source_refs if str(item)})


def runtime_scope_coordinate_from_inputs(inputs: dict[str, Any]) -> dict[str, int]:
    batch_start = _safe_int(inputs.get("batch_start_index"), 0)
    batch_end = _safe_int(inputs.get("batch_end_index"), batch_start)
    return {
        "volume_index": _safe_int(inputs.get("volume_index"), 0),
        "batch_start_index": batch_start,
        "batch_end_index": batch_end,
        "round_index": _safe_int(inputs.get("round_index") or inputs.get("revision_round") or inputs.get("attempt_index"), 0),
        "iteration_index": _safe_int(inputs.get("iteration_index"), 0),
    }


def scope_path_segments_from_coordinate(coordinate: dict[str, Any]) -> list[str]:
    volume_index = _safe_int(coordinate.get("volume_index"), 0)
    batch_start = _safe_int(coordinate.get("batch_start_index"), 0)
    batch_end = _safe_int(coordinate.get("batch_end_index"), batch_start)
    round_index = _safe_int(coordinate.get("round_index"), 0)
    parts: list[str] = []
    if volume_index > 0:
        parts.append(f"volume[{volume_index:03d}]")
    if batch_start > 0:
        batch_label = f"batch[{batch_start:03d}"
        if batch_end and batch_end != batch_start:
            batch_label += f"-{batch_end:03d}"
        batch_label += "]"
        parts.append(batch_label)
    if round_index > 0:
        parts.append(f"round[{round_index:03d}]")
    return parts


def dependency_scope_key_from_inputs(inputs: dict[str, Any]) -> str:
    coordinate = runtime_scope_coordinate_from_inputs(inputs)
    iteration_index = int(coordinate.get("iteration_index") or 0)
    parts = ["run"]
    parts.extend(scope_path_segments_from_coordinate(coordinate))
    if iteration_index > 0:
        parts.append(f"iteration[{iteration_index}]")
    return "/".join(parts)


def artifact_refs_from_value(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value.startswith("artifact:") else []
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if str(item).startswith("artifact:")]
    return []


def short_hash(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def _mapped_outputs_from_artifact_refs(output_mappings: list[dict[str, Any]], artifact_refs: list[str]) -> dict[str, Any]:
    mapped_outputs: dict[str, Any] = {}
    for mapping in output_mappings:
        output_key = str(mapping.get("output_key") or "").strip()
        if not output_key:
            continue
        mapped_outputs[output_key] = artifact_refs if mapping.get("single") is False else (artifact_refs[0] if artifact_refs else "")
    return mapped_outputs


def _first_non_empty(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""
