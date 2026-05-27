from __future__ import annotations

from typing import Any

from runtime import TaskRun
from task_system.runtime_semantics.quality_gates import stage_business_acceptance

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
    graph_harness = runtime.query_runtime.graph_harness
    stage_results = dict(state.get("stage_results") or {})
    already_consumed_task_run_id = str(dict(stage_results.get(active_stage_id) or {}).get("task_run_id") or "")
    contracts = dict(state.get("stage_contracts") or {})
    contract = dict(contracts.get(active_stage_id) or {})
    active_task_ref = str(contract.get("task_ref") or state.get("active_task_ref") or "").strip()
    expected_task_suffix = active_stage_id
    candidates = []
    for task_run in graph_harness.list_session_task_runs(session_id):
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
        checkpoint = graph_harness.load_latest_task_checkpoint(task_run.task_run_id)
        task_result = dict(getattr(checkpoint, "commit_state", {}) or {}).get("task_result") if checkpoint is not None else {}
        task_result = dict(task_result or {})
        if artifact_refs:
            task_result["output_refs"] = list(dict.fromkeys([*list(task_result.get("output_refs") or []), *artifact_refs]))
        accepted = bool(str(task_run.status or "") == "completed" and (artifact_refs or not dict(contract.get("artifact_policy") or {}).get("enabled")))
        acceptance_diagnostics: dict[str, Any] = {
            "terminal_reason": str(task_run.terminal_reason or ""),
            "recovered_from_completed_stage_task_run": True,
        }
        if _stage_has_recovery_acceptance_policy(contract) or _is_review_gate_contract(contract):
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
    graph_harness = runtime.query_runtime.graph_harness
    stage_results = dict(state.get("stage_results") or {})
    already_consumed_task_run_id = str(dict(stage_results.get(active_stage_id) or {}).get("task_run_id") or "")
    contracts = dict(state.get("stage_contracts") or {})
    contract = dict(contracts.get(active_stage_id) or {})
    active_task_ref = str(contract.get("task_ref") or state.get("active_task_ref") or "").strip()
    candidates = []
    for task_run in graph_harness.list_session_task_runs(session_id):
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
        checkpoint = graph_harness.load_latest_task_checkpoint(task_run.task_run_id)
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
    recovered = graph_harness.recover_completed_checkpoint_task_run(
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


def _read_first_artifact_text(*, runtime: Any, artifact_refs: list[str]) -> str:
    root_dir = getattr(runtime.query_runtime.graph_harness, "root_dir", None)
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


def _stage_has_recovery_acceptance_policy(contract: dict[str, Any]) -> bool:
    policy = dict(contract.get("quality_retry_policy") or {})
    return bool(policy.get("acceptance_policies") or policy.get("recovery_acceptance_enabled"))


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
    acceptance = stage_business_acceptance(
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
        "content_metric_total": int(acceptance.get("content_metric_total") or acceptance.get("raw_content_metric_total") or 0),
        "expected_unit_indexes": list(acceptance.get("expected_unit_indexes") or []),
        "found_unit_indexes": list(acceptance.get("found_unit_indexes") or []),
        "missing_unit_indexes": missing_indexes,
        "recovered_from_completed_stage_task_run": True,
    }


def _recovery_acceptance_contract(*, stage_id: str, contract: dict[str, Any]) -> dict[str, Any]:
    _ = stage_id
    quality_policy = dict(dict(contract or {}).get("quality_retry_policy") or {})
    if not quality_policy:
        return dict(contract or {})
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

