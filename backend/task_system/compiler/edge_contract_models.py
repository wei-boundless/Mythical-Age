from __future__ import annotations

from typing import Any


RESOURCE_READ_TYPES = {"memory_read", "memory_handoff", "artifact_read", "artifact_context", "file_read", "file_context"}
RESOURCE_WRITE_TYPES = {"memory_write", "memory_write_candidate", "artifact_write", "file_write"}
RESOURCE_COMMIT_TYPES = {"memory_commit", "artifact_commit", "file_commit"}
EVENT_TYPES = {"event", "event_emit", "event_subscribe", "event_notify"}
AUDIT_TYPES = {"audit", "audit_report", "audit_observation"}
REVIEW_TYPES = {"revision_request", "review_feedback", "repair_feedback", "conditional_feedback", "repair_route"}
FLOW_PACKET_PROTOCOL_KINDS = {
    "node_handoff",
    "resource_read",
    "resource_write_candidate",
    "resource_commit",
    "review_feedback",
    "conditional_route",
    "event_signal",
    "audit_observation",
}
STATE_ONLY_PROTOCOL_KINDS = {"control_dependency", "barrier_join", "human_gate", "a2a_session"}


def build_edge_contract_index(
    *,
    edges: list[dict[str, Any]],
    edge_protocol_index: dict[str, dict[str, Any]],
    node_contract_index: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    return {
        str(edge.get("edge_id") or ""): build_edge_contract(
            edge=edge,
            edge_protocol=dict(edge_protocol_index.get(str(edge.get("edge_id") or "")) or {}),
            node_contract_index=node_contract_index,
        )
        for edge in edges
        if str(edge.get("edge_id") or "")
    }


def build_edge_contract(
    *,
    edge: dict[str, Any],
    edge_protocol: dict[str, Any],
    node_contract_index: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    edge_id = str(edge.get("edge_id") or "").strip()
    source_node_id = str(edge.get("source_node_id") or "").strip()
    target_node_id = str(edge.get("target_node_id") or "").strip()
    source_contract = dict(node_contract_index.get(source_node_id) or {})
    target_contract = dict(node_contract_index.get(target_node_id) or {})
    protocol_kind = edge_protocol_kind(edge=edge, edge_protocol=edge_protocol)
    scheduler_role = str(edge_protocol.get("scheduler_role") or edge.get("scheduler_role") or "").strip()
    semantic_role = str(edge_protocol.get("semantic_role") or edge.get("semantic_role") or "").strip()
    payload_contract_id = str(edge_protocol.get("payload_contract_id") or edge.get("payload_contract_id") or "").strip()
    packet_contract_id = str(edge_protocol.get("packet_contract_id") or edge.get("packet_contract_id") or payload_contract_id).strip()
    produces_flow_packet = _produces_flow_packet(protocol_kind)
    return _drop_empty(
        {
            "contract_id": f"edge-contract:{edge_id}",
            "edge_id": edge_id,
            "source_node_id": source_node_id,
            "target_node_id": target_node_id,
            "relation": _drop_empty(
                {
                    "relation_id": f"relation:{edge_id}",
                    "meaning": str(dict(edge.get("metadata") or {}).get("meaning") or edge_id),
                    "semantic_role": semantic_role,
                }
            ),
            "protocol": _drop_empty(
                {
                    "kind": protocol_kind,
                    "direction": "bidirectional" if protocol_kind == "a2a_session" else "unidirectional",
                    "interaction_pattern": _interaction_pattern(protocol_kind),
                    "produces_flow_packet": produces_flow_packet,
                    "legacy_edge_type": str(edge_protocol.get("edge_type") or edge.get("edge_type") or ""),
                }
            ),
            "scheduler": _drop_empty(
                {
                    "scheduler_role": scheduler_role,
                    "semantic_role": semantic_role,
                    "wait_policy": str(edge.get("wait_policy") or "wait_required_contracts"),
                    "blocks_target": scheduler_role in {"dependency", "conditional_dependency", "context"},
                }
            ),
            "packet": _drop_empty(
                {
                    "packet_type": f"flow_packet.{protocol_kind}" if produces_flow_packet else "",
                    "payload_contract_id": payload_contract_id,
                    "packet_contract_id": packet_contract_id,
                    "source_output_selector": _first_text(
                        edge_protocol.get("source_output_keys"),
                        edge.get("source_output_selector"),
                    ),
                    "target_context_key": str(edge_protocol.get("target_context_key") or edge.get("target_context_key") or ""),
                    "target_input_slot": str(edge_protocol.get("target_input_slot") or edge.get("target_input_slot") or ""),
                    "visibility": _packet_visibility(edge=edge),
                    "delivery_policy": str(edge_protocol.get("delivery_policy") or edge.get("result_delivery_policy") or "contract_payload_and_refs"),
                }
            ),
            "reliability": _drop_empty(
                {
                    "ack_required": bool(edge_protocol.get("ack_required", edge.get("ack_required", True))),
                    "ack_policy": str(edge_protocol.get("ack_policy") or edge.get("ack_policy") or "explicit_ack"),
                    "timeout_policy": str(edge.get("timeout_policy") or "fail_closed"),
                    "retry_policy": dict(edge.get("retry_policy") or {}),
                }
            ),
            "security": _drop_empty(
                {
                    "source_environment_id": str(dict(source_contract.get("environment_lock") or {}).get("task_environment_id") or ""),
                    "target_environment_id": str(dict(target_contract.get("environment_lock") or {}).get("task_environment_id") or ""),
                    "cross_environment_policy": "packet_only",
                }
            ),
            "failure": {
                "propagation_policy": str(edge.get("failure_propagation_policy") or "fail_downstream"),
            },
            "human_control": _human_control_policy(
                edge=edge,
                edge_protocol=edge_protocol,
                protocol_kind=protocol_kind,
                scheduler_role=scheduler_role,
                semantic_role=semantic_role,
            ),
            "trace": {
                "persist_packet": produces_flow_packet,
                "receipt_required": True,
                "checkpoint_policy": "edge_packet_replayable" if produces_flow_packet else "edge_state_only",
            },
            "legacy_protocol_projection": dict(edge_protocol),
            "authority": "task_system.compiled_edge_contract",
        }
    )


def edge_protocol_kind(*, edge: dict[str, Any], edge_protocol: dict[str, Any]) -> str:
    explicit = str(dict(edge.get("metadata") or {}).get("edge_protocol_kind") or "").strip()
    if explicit:
        return explicit
    edge_type = str(edge_protocol.get("edge_type") or edge.get("edge_type") or "").strip()
    scheduler_role = str(edge_protocol.get("scheduler_role") or edge.get("scheduler_role") or "").strip()
    if edge_type in RESOURCE_READ_TYPES:
        return "resource_read"
    if edge_type in RESOURCE_WRITE_TYPES:
        return "resource_write_candidate"
    if edge_type in RESOURCE_COMMIT_TYPES:
        return "resource_commit"
    if edge_type in REVIEW_TYPES:
        return "review_feedback" if edge_type != "conditional_feedback" else "conditional_route"
    if edge_type in EVENT_TYPES:
        return "event_signal"
    if edge_type in AUDIT_TYPES:
        return "audit_observation"
    if edge_type in {"barrier", "join"}:
        return "barrier_join"
    if edge_type in {"gate", "gate_pass"}:
        return "human_gate"
    if scheduler_role == "dependency" and edge_type == "control":
        return "control_dependency"
    return "node_handoff"


def _produces_flow_packet(protocol_kind: str) -> bool:
    if protocol_kind in STATE_ONLY_PROTOCOL_KINDS:
        return False
    if protocol_kind in FLOW_PACKET_PROTOCOL_KINDS:
        return True
    return protocol_kind.startswith("resource_") or protocol_kind.endswith("_signal") or protocol_kind.endswith("_observation")


def _interaction_pattern(protocol_kind: str) -> str:
    return {
        "node_handoff": "source_result_to_target_context",
        "resource_read": "resource_context_projection",
        "resource_write_candidate": "resource_write_candidate_projection",
        "resource_commit": "resource_commit_receipt_projection",
        "review_feedback": "review_feedback_to_revision_target",
        "conditional_route": "conditional_feedback_route",
        "event_signal": "event_notification",
        "audit_observation": "audit_observation_record",
        "control_dependency": "state_dependency_only",
        "barrier_join": "state_join_only",
        "human_gate": "manual_release_gate",
        "a2a_session": "agent_session_channel",
    }.get(protocol_kind, "source_result_to_target_context")


def _packet_visibility(*, edge: dict[str, Any]) -> dict[str, Any]:
    policy = dict(edge.get("visibility_policy") or {})
    if policy:
        return policy
    return {
        "mode": "bounded_payload_and_refs",
        "context_filter_policy": dict(edge.get("context_filter_policy") or {}),
        "artifact_ref_policy": dict(edge.get("artifact_ref_policy") or {}),
    }


def _human_control_policy(
    *,
    edge: dict[str, Any],
    edge_protocol: dict[str, Any],
    protocol_kind: str,
    scheduler_role: str,
    semantic_role: str,
) -> dict[str, Any]:
    explicit = dict(edge.get("human_control_policy") or {})
    bindings = dict(edge.get("contract_bindings") or {})
    explicit = {
        **explicit,
        **dict(bindings.get("human_control") or {}),
        **dict(dict(edge.get("metadata") or {}).get("human_control_policy") or {}),
        **dict(edge_protocol.get("human_control_policy") or {}),
    }
    if explicit.get("enabled") is False:
        return {"enabled": False, "authority": "task_system.compiled_edge_contract.human_control"}
    allowed = [str(item) for item in list(explicit.get("allowed_decisions") or []) if str(item)]
    reason = str(explicit.get("reason") or "")
    if not allowed:
        if protocol_kind == "node_handoff":
            allowed = ["pass", "replace"]
            reason = "该边是节点交付边，允许人工通过或以项目文件替代上游产物。"
        elif protocol_kind in {"review_feedback", "conditional_route"} or semantic_role == "revision":
            allowed = ["revise"]
            reason = "该边是返修/反馈边，允许人工退稿并回传修改意见。"
        else:
            return {"enabled": False, "authority": "task_system.compiled_edge_contract.human_control"}
    labels = {
        "pass": "通过并传给下游",
        "revise": "退稿并回传上游",
        "replace": "我来替写并继续",
        **dict(explicit.get("decision_labels") or {}),
    }
    policy = {
        "enabled": True,
        "allowed_decisions": allowed,
        "decision_labels": {key: labels[key] for key in allowed if key in labels},
        "default_decision": str(explicit.get("default_decision") or allowed[0]),
        "reason": reason or "该边允许人工控制传播。",
        "pass": {
            "route": "current_edge",
            "requires_source_result": True,
            **dict(explicit.get("pass") or {}),
        },
        "revise": {
            "route": "current_edge",
            "requires_instruction": True,
            "result_index_policy": "replace_if_control_source",
            **dict(explicit.get("revise") or {}),
        },
        "replace": {
            "route": "current_edge",
            "write_policy": {
                "repository_id": "instance",
                "path_template": "working/human-{edge_id}.md",
                "content_kind": "artifact",
                **dict(dict(explicit.get("replace") or {}).get("write_policy") or {}),
            },
            **{key: value for key, value in dict(explicit.get("replace") or {}).items() if key != "write_policy"},
        },
        "scheduler_role": scheduler_role,
        "semantic_role": semantic_role,
        "authority": "task_system.compiled_edge_contract.human_control",
    }
    return _drop_empty(policy)


def _first_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, (list, tuple)):
            for item in value:
                text = str(item or "").strip()
                if text:
                    return text
            continue
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if value not in ("", None, [], {}, ())
    }
