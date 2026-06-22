from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

from artifact_system.artifact_authority import artifact_ref_value, dedupe_artifact_refs, normalize_artifact_ref
from harness.task_contract_normalization import contract_string_list


_GRAPH_STABLE_INPUT_LIMIT = 4000
_GRAPH_STABLE_PAYLOAD_LIMIT = 12000
_GRAPH_STABLE_ARTIFACT_CONTENT_LIMIT = 16000
_GRAPH_STABLE_ARTIFACT_PAYLOAD_LIMIT = 2
_GRAPH_STABLE_LOOP_ARTIFACT_PAYLOAD_LIMIT = 4


@dataclass(frozen=True, slots=True)
class TaskContractManifest:
    manifest_id: str
    invocation_kind: str
    source_ref: str
    contract_hash: str
    planning_protocol_hash: str
    contract_kind: str = "task_contract"
    task_run_goal: str = ""
    completion_criteria_count: int = 0
    model_visible_contract: dict[str, Any] = field(default_factory=dict)
    planning_protocol: dict[str, Any] = field(default_factory=dict)
    authority: str = "harness.runtime.task_contract_manifest"

    def to_model_visible_payload(self) -> dict[str, Any]:
        return {
            "task_contract": _deepcopy_json_dict(self.model_visible_contract),
            "planning_protocol": _deepcopy_json_dict(self.planning_protocol),
        }

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["model_visible_contract"] = _deepcopy_json_dict(self.model_visible_contract)
        payload["planning_protocol"] = _deepcopy_json_dict(self.planning_protocol)
        return payload


def build_task_contract_manifest(
    *,
    invocation_kind: str,
    model_visible_contract: dict[str, Any],
    planning_protocol: dict[str, Any],
    source_ref: str,
) -> TaskContractManifest:
    contract_payload = _deepcopy_json_dict(model_visible_contract)
    planning_payload = _deepcopy_json_dict(planning_protocol)
    contract_hash = _stable_json_hash(contract_payload)
    planning_hash = _stable_json_hash(planning_payload)
    acceptance_contract = dict(contract_payload.get("acceptance_contract") or {})
    goal_contract = dict(contract_payload.get("goal_contract") or {})
    completion_criteria = contract_string_list(
        acceptance_contract.get("completion_criteria") or contract_payload.get("completion_criteria")
    )
    seed = {
        "invocation_kind": str(invocation_kind or ""),
        "source_ref": str(source_ref or ""),
        "contract_hash": contract_hash,
        "planning_protocol_hash": planning_hash,
    }
    return TaskContractManifest(
        manifest_id="taskcontract:" + _digest(seed),
        invocation_kind=str(invocation_kind or ""),
        source_ref=str(source_ref or ""),
        contract_hash=contract_hash,
        planning_protocol_hash=planning_hash,
        contract_kind=_contract_kind(contract_payload),
        task_run_goal=str(goal_contract.get("task_run_goal") or contract_payload.get("task_run_goal") or ""),
        completion_criteria_count=len(completion_criteria),
        model_visible_contract=contract_payload,
        planning_protocol=planning_payload,
    )


def build_task_contract_manifest_from_contract(
    *,
    invocation_kind: str,
    contract: dict[str, Any],
    planning_protocol: dict[str, Any],
    source_ref: str,
    graph_node_context: dict[str, Any] | None = None,
) -> TaskContractManifest:
    contract_payload = project_task_contract_for_prompt(
        contract,
        graph_node_context=graph_node_context,
    )
    return build_task_contract_manifest(
        invocation_kind=invocation_kind,
        model_visible_contract=contract_payload,
        planning_protocol=planning_protocol,
        source_ref=source_ref,
    )


def project_task_contract_for_prompt(
    contract: dict[str, Any],
    *,
    graph_node_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = dict(contract or {})
    graph_slot = _graph_slot_from_contract(payload)
    if graph_slot:
        return _drop_empty_payload(
            {
                "contract_id": "graph_node_contract",
                "contract_source": str(payload.get("contract_source") or "graph_node_work_order"),
                "task_environment_id": str(payload.get("task_environment_id") or ""),
                "origin": _graph_task_contract_origin_model_visible(dict(payload.get("origin") or {})),
                "graph_node_context": dict(graph_node_context or {}),
                "completion_criteria": _string_list(payload.get("completion_criteria")),
                "authority": "harness.runtime.graph_node_contract.model_visible",
            }
        )
    layered = _layered_task_contract_payload(payload)
    return _drop_empty_payload(
        {
            "contract_id": str(payload.get("contract_id") or "").strip(),
            "contract_source": str(payload.get("contract_source") or "").strip(),
            "task_environment_id": str(payload.get("task_environment_id") or "").strip(),
            **layered,
            "authority": "harness.runtime.task_contract.model_visible",
        }
    )


def _layered_task_contract_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return _drop_empty_payload(
        {
            "goal_contract": _goal_contract_model_visible(payload),
            "plan_contract": _plan_contract_model_visible(payload),
            "lifecycle_contract": _lifecycle_contract_model_visible(payload),
            "environment_contract": _environment_contract_model_visible(payload),
            "feedback_contract": _feedback_contract_model_visible(payload),
            "acceptance_contract": _acceptance_contract_model_visible(payload),
        }
    )


def _goal_contract_model_visible(payload: dict[str, Any]) -> dict[str, Any]:
    raw = dict(payload.get("goal_contract") or {})
    return _drop_empty_payload(
        {
            "user_visible_goal": str(raw.get("user_visible_goal") or payload.get("user_visible_goal") or "").strip(),
            "task_run_goal": str(raw.get("task_run_goal") or raw.get("agent_goal") or payload.get("task_run_goal") or "").strip(),
            "agent_goal": str(raw.get("agent_goal") or raw.get("task_run_goal") or payload.get("task_run_goal") or "").strip(),
            "non_goals": _string_list(raw.get("non_goals") or payload.get("non_goals")),
            "success_definition": str(raw.get("success_definition") or payload.get("success_definition") or "").strip(),
            "completion_evidence": _string_list(raw.get("completion_evidence") or payload.get("completion_evidence")),
            "authority": "harness.runtime.task_contract.goal_contract.model_visible",
        }
    )


def _plan_contract_model_visible(payload: dict[str, Any]) -> dict[str, Any]:
    raw = dict(payload.get("plan_contract") or {})
    plan_ref = str(raw.get("plan_id") or payload.get("plan_ref") or payload.get("approved_plan_ref") or payload.get("external_plan_ref") or "").strip()
    return _drop_empty_payload(
        {
            "plan_id": plan_ref,
            "plan_version": str(raw.get("plan_version") or "").strip(),
            "plan_status": str(raw.get("plan_status") or raw.get("approval_state") or "agent_managed").strip(),
            "strategy_summary": str(raw.get("strategy_summary") or "").strip(),
            "major_steps": _string_list(raw.get("major_steps") or raw.get("steps")),
            "decision_points": _string_list(raw.get("decision_points")),
            "allowed_plan_operations": _string_list(raw.get("allowed_plan_operations") or raw.get("allowed_operations")),
            "replan_policy": dict(raw.get("replan_policy") or {}) if isinstance(raw.get("replan_policy"), dict) else {},
            "plan_requirements": dict(payload.get("plan_requirements") or {}) if isinstance(payload.get("plan_requirements"), dict) else {},
            "implementation_lock": dict(payload.get("implementation_lock") or {}) if isinstance(payload.get("implementation_lock"), dict) else {},
            "authority": "harness.runtime.task_contract.plan_contract.model_visible",
        }
    )


def _lifecycle_contract_model_visible(payload: dict[str, Any]) -> dict[str, Any]:
    raw = dict(payload.get("lifecycle_contract") or {})
    return _drop_empty_payload(
        {
            "allowed_states": _string_list(raw.get("allowed_states")),
            "pause_policy": dict(raw.get("pause_policy") or {}) if isinstance(raw.get("pause_policy"), dict) else {},
            "resume_policy": dict(raw.get("resume_policy") or {}) if isinstance(raw.get("resume_policy"), dict) else {},
            "stop_policy": dict(raw.get("stop_policy") or {}) if isinstance(raw.get("stop_policy"), dict) else {},
            "replan_policy": dict(raw.get("replan_policy") or {}) if isinstance(raw.get("replan_policy"), dict) else {},
            "tool_limit_closeout_policy": dict(raw.get("tool_limit_closeout_policy") or {}) if isinstance(raw.get("tool_limit_closeout_policy"), dict) else {},
            "failure_recovery_policy": dict(raw.get("failure_recovery_policy") or payload.get("recovery_policy") or {}) if isinstance(raw.get("failure_recovery_policy") or payload.get("recovery_policy"), dict) else {},
            "terminal_policy": dict(raw.get("terminal_policy") or {}) if isinstance(raw.get("terminal_policy"), dict) else {},
            "authority": "harness.runtime.task_contract.lifecycle_contract.model_visible",
        }
    )


def _environment_contract_model_visible(payload: dict[str, Any]) -> dict[str, Any]:
    raw = dict(payload.get("environment_contract") or {})
    working_scope = _working_scope_stable_payload(raw.get("working_scope") or payload.get("working_scope"))
    resource_requirements = dict(raw.get("resource_requirements") or payload.get("resource_requirements") or {})
    return _drop_empty_payload(
        {
            "task_environment_id": str(raw.get("task_environment_id") or payload.get("task_environment_id") or "").strip(),
            "working_scope": working_scope,
            "capability_intent": dict(raw.get("capability_intent") or payload.get("capability_intent") or {}),
            "skill_intent": dict(raw.get("skill_intent") or payload.get("skill_intent") or {}),
            "permission_requirements": dict(raw.get("permission_requirements") or payload.get("permission_requirements") or {}),
            "resource_requirements": _resource_requirements_stable_payload(resource_requirements) if resource_requirements else {},
            "safety_boundaries": _string_list(raw.get("safety_boundaries") or payload.get("safety_boundaries")),
            "authority": "harness.runtime.task_contract.environment_contract.model_visible",
        }
    )


def _feedback_contract_model_visible(payload: dict[str, Any]) -> dict[str, Any]:
    raw = dict(payload.get("feedback_contract") or {})
    observation_policy = raw.get("observation_policy") or raw.get("observation_contract") or payload.get("observation_contract")
    return _drop_empty_payload(
        {
            "feedback_sources": _string_list(raw.get("feedback_sources")),
            "dynamic_context_slots": _string_list(raw.get("dynamic_context_slots")),
            "steer_policy": dict(raw.get("steer_policy") or {}) if isinstance(raw.get("steer_policy"), dict) else {},
            "observation_policy": dict(observation_policy or {}) if isinstance(observation_policy, dict) else {},
            "verification_feedback_policy": dict(raw.get("verification_feedback_policy") or {}) if isinstance(raw.get("verification_feedback_policy"), dict) else {},
            "budget_feedback_policy": dict(raw.get("budget_feedback_policy") or {}) if isinstance(raw.get("budget_feedback_policy"), dict) else {},
            "feedback_priority": _string_list(raw.get("feedback_priority")),
            "feedback_identity_binding": str(raw.get("feedback_identity_binding") or "").strip(),
            "authority": "harness.runtime.task_contract.feedback_contract.model_visible",
        }
    )


def _acceptance_contract_model_visible(payload: dict[str, Any]) -> dict[str, Any]:
    raw = dict(payload.get("acceptance_contract") or {})
    return _drop_empty_payload(
        {
            "completion_criteria": _string_list(raw.get("completion_criteria") or payload.get("completion_criteria")),
            "required_artifacts": [
                dict(item) for item in list(raw.get("required_artifacts") or payload.get("required_artifacts") or []) if isinstance(item, dict)
            ],
            "required_verifications": [
                dict(item) for item in list(raw.get("required_verifications") or payload.get("required_verifications") or []) if isinstance(item, dict)
            ],
            "verification_gate": dict(raw.get("verification_gate") or {}) if isinstance(raw.get("verification_gate"), dict) else {},
            "final_answer_requirements": _string_list(raw.get("final_answer_requirements")),
            "evidence_refs_required": raw.get("evidence_refs_required") if isinstance(raw.get("evidence_refs_required"), bool) else None,
            "acceptance_policy": dict(raw.get("acceptance_policy") or payload.get("acceptance_policy") or {}),
            "authority": "harness.runtime.task_contract.acceptance_contract.model_visible",
        }
    )


def _working_scope_stable_payload(value: Any) -> dict[str, Any]:
    raw = dict(value or {}) if isinstance(value, dict) else {}
    target_objects = _object_ref_list(raw.get("target_objects"))
    source_refs = _string_list(raw.get("source_refs"))
    workspace_refs = _string_list(raw.get("workspace_refs"))
    body = _drop_empty_payload(
        {
            "target_objects": target_objects,
            "workspace_refs": workspace_refs,
            "source_refs": source_refs,
            "excluded_scope": _string_list(raw.get("excluded_scope")),
            "known_constraints": _string_list(raw.get("known_constraints")),
            "target_object_policy": _target_object_policy(
                target_objects=target_objects,
                source_refs=source_refs,
                workspace_refs=workspace_refs,
            ),
        }
    )
    if not body:
        return {}
    return {**body, "authority": "harness.runtime.task_contract.working_scope.model_visible"}


def _target_object_policy(
    *,
    target_objects: list[Any],
    source_refs: list[str],
    workspace_refs: list[str],
) -> dict[str, Any]:
    known_path_refs = [
        text
        for text in (
            *(_path_like_texts(target_objects)),
            *(_path_like_texts(source_refs)),
            *(_path_like_texts(workspace_refs)),
        )
        if text
    ]
    if not known_path_refs:
        return {}
    return {
        "file_like_refs_are_known_paths": True,
        "known_path_refs": known_path_refs,
        "preferred_first_tools": ["path_exists", "read_file"],
        "avoid_tools_for_known_paths": ["search_files", "search_text"],
        "search_tools_scope": "unknown_location_only",
        "authority": "harness.runtime.task_contract.working_scope.target_object_policy",
    }


def _path_like_texts(value: Any) -> list[str]:
    raw_values = value if isinstance(value, (list, tuple)) else ([value] if value else [])
    result: list[str] = []
    for item in raw_values:
        if isinstance(item, dict):
            for key in ("path", "file", "target", "ref", "href", "source_ref", "target_object"):
                text = str(item.get(key) or "").strip()
                if _is_path_like_ref(text):
                    result.append(text)
            continue
        text = str(item or "").strip()
        if _is_path_like_ref(text):
            result.append(text)
    return _dedupe_strings(result)


def _is_path_like_ref(value: str) -> bool:
    text = str(value or "").strip()
    if not text or text.startswith(("http://", "https://")):
        return False
    if "\\" in text or "/" in text:
        return True
    suffix = text.rsplit(".", 1)[-1].lower() if "." in text else ""
    return suffix in {
        "py",
        "ts",
        "tsx",
        "js",
        "jsx",
        "html",
        "css",
        "json",
        "md",
        "toml",
        "yaml",
        "yml",
        "txt",
        "csv",
        "xml",
        "sql",
    }


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _object_ref_list(value: Any) -> list[Any]:
    raw_values = value if isinstance(value, (list, tuple)) else ([value] if value else [])
    result: list[Any] = []
    for item in raw_values:
        if isinstance(item, dict):
            cleaned = {
                str(key): val
                for key, val in item.items()
                if str(key).strip() and val not in (None, "", [], {})
            }
            if cleaned:
                result.append(cleaned)
            continue
        text = str(item or "").strip()
        if text:
            result.append(text)
    return result


def _graph_slot_from_contract(contract: dict[str, Any]) -> dict[str, Any]:
    graph_slot = dict(dict(contract or {}).get("graph_slot") or {})
    if graph_slot:
        return graph_slot
    diagnostics = dict(dict(contract or {}).get("diagnostics") or {})
    return dict(diagnostics.get("graph_slot") or {})


def _graph_task_contract_origin_model_visible(origin: dict[str, Any]) -> dict[str, Any]:
    return {
        "origin_kind": str(origin.get("origin_kind") or ""),
        "origin_authority": str(origin.get("origin_authority") or ""),
        "node_id": str(origin.get("node_id") or ""),
        "authority": "harness.runtime.graph_task_contract_origin.model_visible_projection",
    }


def _resource_requirements_stable_payload(resource_requirements: dict[str, Any]) -> dict[str, Any]:
    return {
        "graph_state": _graph_state_model_visible_payload(dict(resource_requirements.get("graph_state") or {})),
        "input_package": _input_package_stable_payload(dict(resource_requirements.get("input_package") or {})),
        "context_refs": dict(resource_requirements.get("context_refs") or {}),
        "artifact_space_ref": str(resource_requirements.get("artifact_space_ref") or ""),
        "memory_space_ref": str(resource_requirements.get("memory_space_ref") or ""),
        "file_access_table_refs": [str(item) for item in list(resource_requirements.get("file_access_table_refs") or []) if str(item)],
        "artifact_repository_targets": [
            dict(item) for item in list(resource_requirements.get("artifact_repository_targets") or []) if isinstance(item, dict)
        ],
        "memory_repository_targets": [
            dict(item) for item in list(resource_requirements.get("memory_repository_targets") or []) if isinstance(item, dict)
        ],
    }


def _graph_state_model_visible_payload(graph_state: dict[str, Any]) -> dict[str, Any]:
    return {
        "completed_node_ids": [str(item) for item in list(graph_state.get("completed_node_ids") or []) if str(item)],
        "failed_node_ids": [str(item) for item in list(graph_state.get("failed_node_ids") or []) if str(item)],
        "upstream_node_ids": [str(item) for item in list(graph_state.get("upstream_node_ids") or []) if str(item)],
        "available_result_node_ids": [str(item) for item in list(graph_state.get("available_result_node_ids") or []) if str(item)],
        "authority": "harness.runtime.graph_state.model_visible_projection",
    }


def _input_package_stable_payload(input_package: dict[str, Any]) -> dict[str, Any]:
    payload = dict(input_package or {})
    payload["inbound_context"] = _inbound_context_stable_payload(payload.get("inbound_context"))
    payload.pop("upstream_results", None)
    payload.pop("upstream_handoff_packets", None)
    payload.pop("handoff_packets", None)
    if "task_environment" in payload:
        payload["task_environment"] = {
            "environment_id": str(dict(payload.get("task_environment") or {}).get("environment_id") or ""),
            "task_environment_id": str(dict(payload.get("task_environment") or {}).get("task_environment_id") or ""),
            "storage_space": dict(dict(payload.get("task_environment") or {}).get("storage_space") or {}),
            "authority": str(dict(payload.get("task_environment") or {}).get("authority") or ""),
        }
    for key in ("memory_view", "artifact_view", "file_view"):
        if isinstance(payload.get(key), dict):
            payload[key] = _bounded_view_payload(dict(payload.get(key) or {}))
    payload.pop("hidden_control_refs", None)
    return payload


def _inbound_context_stable_payload(value: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for item in list(value or []):
        if not isinstance(item, dict):
            continue
        payload = dict(item.get("payload") or {})
        items.append(
            {
                "packet_type": str(item.get("packet_type") or ""),
                "source_node_id": str(item.get("source_node_id") or ""),
                "target_node_id": str(item.get("target_node_id") or ""),
                "edge_id": str(item.get("edge_id") or item.get("source_edge_id") or ""),
                "payload_contract_id": str(item.get("payload_contract_id") or ""),
                "packet_contract_id": str(item.get("packet_contract_id") or item.get("payload_contract_id") or ""),
                "target_context_key": str(item.get("target_context_key") or ""),
                "target_input_slot": str(item.get("target_input_slot") or ""),
                "delivery_policy": str(item.get("delivery_policy") or ""),
                "payload": _bounded_graph_payload(payload),
                "artifact_refs": _bounded_dict_list(item.get("artifact_refs"), limit=12),
                "memory_refs": _bounded_dict_list(item.get("memory_refs"), limit=12),
                "result_refs": _bounded_dict_list(item.get("result_refs"), limit=8),
                "receipt_refs": _bounded_dict_list(item.get("receipt_refs"), limit=12),
                "visibility": dict(item.get("visibility") or {}),
                "authority": "harness.graph.inbound_context.model_visible",
            }
        )
    return items


def _bounded_graph_payload(payload: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if isinstance(payload.get("initial_inputs"), dict):
        result["initial_inputs"] = _truncate_value(dict(payload.get("initial_inputs") or {}), max_chars=_GRAPH_STABLE_INPUT_LIMIT)
    if payload.get("graph_id"):
        result["graph_id"] = str(payload.get("graph_id") or "")
    if payload.get("project_id"):
        result["project_id"] = str(payload.get("project_id") or "")
    if "handoff_summary" in payload:
        result["handoff_summary"] = str(payload.get("handoff_summary") or "")[:1200]
    if isinstance(payload.get("source_error"), dict):
        result["source_error"] = _truncate_value(dict(payload.get("source_error") or {}), max_chars=4000)
    if isinstance(payload.get("quality_acceptance"), dict):
        result["quality_acceptance"] = _truncate_value(dict(payload.get("quality_acceptance") or {}), max_chars=4000)
    if payload.get("quality_issue_summary"):
        result["quality_issue_summary"] = str(payload.get("quality_issue_summary") or "")[:4000]
    if isinstance(payload.get("issues"), list):
        result["issues"] = [str(item) for item in list(payload.get("issues") or [])[:32] if str(item)]
    if isinstance(payload.get("artifact_refs"), list):
        result["artifact_refs"] = [
            artifact_ref_value(item)
            for item in dedupe_artifact_refs([normalize_artifact_ref(ref) for ref in list(payload.get("artifact_refs") or [])])
            if artifact_ref_value(item)
        ][:12]
    if isinstance(payload.get("receipt_refs"), list):
        result["receipt_refs"] = _bounded_dict_list(payload.get("receipt_refs"), limit=12)
    if isinstance(payload.get("bounded_outputs"), dict):
        result["bounded_outputs"] = _truncate_value(dict(payload.get("bounded_outputs") or {}), max_chars=8000)
    if isinstance(payload.get("loop_iteration_results"), list):
        result["loop_iteration_results"] = _truncate_value(list(payload.get("loop_iteration_results") or [])[:10], max_chars=6000)
    if isinstance(payload.get("batch_chapter_ledger"), dict):
        result["batch_chapter_ledger"] = _truncate_value(dict(payload.get("batch_chapter_ledger") or {}), max_chars=6000)
    if isinstance(payload.get("artifact_payloads"), list):
        artifact_payload_limit = _GRAPH_STABLE_LOOP_ARTIFACT_PAYLOAD_LIMIT if isinstance(payload.get("loop_iteration_results"), list) else _GRAPH_STABLE_ARTIFACT_PAYLOAD_LIMIT
        result["artifact_payloads"] = [
            _bounded_artifact_payload(dict(item))
            for item in list(payload.get("artifact_payloads") or [])[:artifact_payload_limit]
            if isinstance(item, dict)
        ]
    return result


def _bounded_artifact_payload(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "artifact_ref": str(item.get("artifact_ref") or ""),
        "path": str(item.get("path") or ""),
        "kind": str(item.get("kind") or item.get("artifact_kind") or ""),
        "summary": str(item.get("summary") or "")[:2000],
        "content": str(item.get("content") or "")[:_GRAPH_STABLE_ARTIFACT_CONTENT_LIMIT],
        "truncated": bool(item.get("truncated") is True),
        "max_chars": min(_safe_int(item.get("max_chars")) or _GRAPH_STABLE_ARTIFACT_CONTENT_LIMIT, _GRAPH_STABLE_ARTIFACT_CONTENT_LIMIT),
        "authority": str(item.get("authority") or "harness.graph.flow_packet.artifact_text_projection"),
    }


def _truncate_value(value: Any, *, max_chars: int) -> Any:
    if isinstance(value, str):
        return value[:max_chars]
    if isinstance(value, dict):
        return {str(key): _truncate_value(item, max_chars=max_chars) for key, item in value.items()}
    if isinstance(value, list):
        return [_truncate_value(item, max_chars=max_chars) for item in value]
    return value


def _bounded_view_payload(view: dict[str, Any]) -> dict[str, Any]:
    payload = dict(view or {})
    if isinstance(payload.get("graph_memory_policy"), dict):
        policy = dict(payload.get("graph_memory_policy") or {})
        policy["read_rules"] = _bounded_dict_list(policy.get("read_rules"), limit=16)
        payload["graph_memory_policy"] = policy
    if isinstance(payload.get("graph_artifact_policy"), dict):
        policy = dict(payload.get("graph_artifact_policy") or {})
        policy["context_edges"] = _bounded_dict_list(policy.get("context_edges"), limit=16)
        payload["graph_artifact_policy"] = policy
    if isinstance(payload.get("graph_resource_policy"), dict):
        policy = dict(payload.get("graph_resource_policy") or {})
        policy["resource_nodes"] = _bounded_dict_list(policy.get("resource_nodes"), limit=24)
        payload["graph_resource_policy"] = policy
    return payload


def _bounded_dict_list(value: Any, *, limit: int) -> list[dict[str, Any]]:
    return [dict(item) for item in list(value or [])[:limit] if isinstance(item, dict)]


def _safe_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _string_list(value: Any) -> list[str]:
    return contract_string_list(value)


def _drop_empty_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if value not in ("", None, [], {})
    }


def _contract_kind(contract_payload: dict[str, Any]) -> str:
    authority = str(contract_payload.get("authority") or "")
    if "graph_node_contract" in authority or contract_payload.get("graph_node_context"):
        return "graph_node_contract"
    return "task_contract"


def _stable_json_hash(value: Any) -> str:
    payload = json.dumps(_json_stable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()


def _digest(value: Any) -> str:
    payload = json.dumps(_json_stable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _json_stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_stable(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_json_stable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def _deepcopy_json_dict(value: dict[str, Any]) -> dict[str, Any]:
    return dict(_json_stable(dict(value or {})))
