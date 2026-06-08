from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from artifact_system.artifact_authority import artifact_ref_value, dedupe_artifact_refs, normalize_artifact_ref

from .edge_contracts import edge_contract_or_projection
from .models import GraphHarnessConfig, GraphLoopState, NodeResultEnvelope, safe_id, stable_safe_id


FLOW_PACKET_AUTHORITY = "harness.graph_flow_packet"
FLOW_PACKET_STATUSES = {"candidate", "accepted", "committed", "rejected", "failed"}
FLOW_PACKET_EDGE_TYPES = {
    "handoff",
    "structured_handoff",
    "memory_handoff",
    "memory_read",
    "memory_write",
    "memory_write_candidate",
    "memory_commit",
    "artifact_read",
    "artifact_write",
    "artifact_context",
    "artifact_commit",
    "file_read",
    "file_write",
    "file_context",
    "file_commit",
    "revision_request",
    "review_feedback",
    "repair_feedback",
    "conditional_feedback",
    "repair_route",
    "event",
    "event_emit",
    "event_subscribe",
    "event_notify",
    "audit",
    "audit_report",
    "audit_observation",
}
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


@dataclass(frozen=True, slots=True)
class FlowPacket:
    packet_id: str
    packet_type: str
    graph_run_id: str
    task_run_id: str
    source_unit_id: str
    target_unit_id: str
    edge_id: str
    source_port_id: str = ""
    target_port_id: str = ""
    scope_id: str = ""
    contract_id: str = ""
    packet_contract_id: str = ""
    target_context_key: str = ""
    target_input_slot: str = ""
    a2a_message_type: str = ""
    payload_summary: str = ""
    payload_refs: tuple[dict[str, Any], ...] = ()
    artifact_refs: tuple[dict[str, Any], ...] = ()
    memory_refs: tuple[dict[str, Any], ...] = ()
    result_refs: tuple[dict[str, Any], ...] = ()
    receipt_refs: tuple[dict[str, Any], ...] = ()
    visible_payload: dict[str, Any] = field(default_factory=dict)
    visibility: dict[str, Any] = field(default_factory=dict)
    status: str = "accepted"
    lineage: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0
    authority: str = FLOW_PACKET_AUTHORITY

    def __post_init__(self) -> None:
        if self.authority != FLOW_PACKET_AUTHORITY:
            raise ValueError("FlowPacket authority must be harness.graph_flow_packet")
        if not self.packet_id:
            raise ValueError("FlowPacket requires packet_id")
        if not self.packet_type:
            raise ValueError("FlowPacket requires packet_type")
        if not self.graph_run_id:
            raise ValueError("FlowPacket requires graph_run_id")
        if not self.task_run_id:
            raise ValueError("FlowPacket requires task_run_id")
        if not self.source_unit_id:
            raise ValueError("FlowPacket requires source_unit_id")
        if not self.target_unit_id:
            raise ValueError("FlowPacket requires target_unit_id")
        if not self.edge_id:
            raise ValueError("FlowPacket requires edge_id")
        if self.status not in FLOW_PACKET_STATUSES:
            raise ValueError("FlowPacket status is not supported")
        if not self.created_at:
            object.__setattr__(self, "created_at", time.time())

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["payload_refs"] = [dict(item) for item in self.payload_refs]
        payload["artifact_refs"] = [dict(item) for item in self.artifact_refs]
        payload["memory_refs"] = [dict(item) for item in self.memory_refs]
        payload["result_refs"] = [dict(item) for item in self.result_refs]
        payload["receipt_refs"] = [dict(item) for item in self.receipt_refs]
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "FlowPacket":
        return cls(
            packet_id=str(payload.get("packet_id") or ""),
            packet_type=str(payload.get("packet_type") or ""),
            graph_run_id=str(payload.get("graph_run_id") or ""),
            task_run_id=str(payload.get("task_run_id") or ""),
            source_unit_id=str(payload.get("source_unit_id") or ""),
            target_unit_id=str(payload.get("target_unit_id") or ""),
            edge_id=str(payload.get("edge_id") or ""),
            source_port_id=str(payload.get("source_port_id") or ""),
            target_port_id=str(payload.get("target_port_id") or ""),
            scope_id=str(payload.get("scope_id") or ""),
            contract_id=str(payload.get("contract_id") or ""),
            packet_contract_id=str(payload.get("packet_contract_id") or payload.get("contract_id") or ""),
            target_context_key=str(payload.get("target_context_key") or ""),
            target_input_slot=str(payload.get("target_input_slot") or ""),
            a2a_message_type=str(payload.get("a2a_message_type") or ""),
            payload_summary=str(payload.get("payload_summary") or ""),
            payload_refs=tuple(dict(item) for item in list(payload.get("payload_refs") or []) if isinstance(item, dict)),
            artifact_refs=tuple(dict(item) for item in list(payload.get("artifact_refs") or []) if isinstance(item, dict)),
            memory_refs=tuple(dict(item) for item in list(payload.get("memory_refs") or []) if isinstance(item, dict)),
            result_refs=tuple(dict(item) for item in list(payload.get("result_refs") or []) if isinstance(item, dict)),
            receipt_refs=tuple(dict(item) for item in list(payload.get("receipt_refs") or []) if isinstance(item, dict)),
            visible_payload=dict(payload.get("visible_payload") or {}),
            visibility=dict(payload.get("visibility") or {}),
            status=str(payload.get("status") or "accepted"),
            lineage=dict(payload.get("lineage") or {}),
            created_at=float(payload.get("created_at") or 0.0),
            authority=str(payload.get("authority") or FLOW_PACKET_AUTHORITY),
        )


def edge_delivers_flow_packet(edge: dict[str, Any], *, graph_config: GraphHarnessConfig | None = None) -> bool:
    if graph_config is not None:
        edge_contract = edge_contract_or_projection(graph_config, edge)
        trace = dict(edge_contract.get("trace") or {})
        if "persist_packet" in trace:
            return bool(trace.get("persist_packet"))
        protocol = dict(edge_contract.get("protocol") or {})
        produces_flow_packet = protocol.get("produces_flow_packet")
        if produces_flow_packet is not None:
            return bool(produces_flow_packet)
        protocol_kind = str(protocol.get("kind") or "").strip()
        if protocol_kind:
            return _protocol_delivers_flow_packet(protocol_kind)
    return _legacy_edge_delivers_flow_packet(edge)


def _protocol_delivers_flow_packet(protocol_kind: str) -> bool:
    if protocol_kind in STATE_ONLY_PROTOCOL_KINDS:
        return False
    if protocol_kind in FLOW_PACKET_PROTOCOL_KINDS or protocol_kind in FLOW_PACKET_EDGE_TYPES:
        return True
    return protocol_kind.startswith("resource_") or protocol_kind.endswith("_signal") or protocol_kind.endswith("_observation")


def _legacy_edge_delivers_flow_packet(edge: dict[str, Any]) -> bool:
    edge_type = str(edge.get("edge_type") or "").strip()
    semantic_role = str(edge.get("semantic_role") or "").strip()
    scheduler_role = str(edge.get("scheduler_role") or "").strip()
    if edge_type in FLOW_PACKET_EDGE_TYPES:
        return True
    if scheduler_role == "context":
        return True
    if semantic_role in {"memory", "artifact", "file", "revision"} and scheduler_role != "commit":
        return True
    if str(edge.get("payload_contract_id") or "").strip() and scheduler_role in {"dependency", "conditional_dependency", "context"}:
        return True
    return False


def build_flow_packet(
    *,
    graph_config: GraphHarnessConfig,
    state: GraphLoopState,
    edge: dict[str, Any],
    result: NodeResultEnvelope,
    result_ref: str,
    created_at: float | None = None,
) -> FlowPacket:
    edge_id = str(edge.get("edge_id") or "")
    target_node_id = str(edge.get("target_node_id") or "")
    result_payload = result.to_dict()
    visible_payload = _visible_payload_for_edge(edge=edge, result=result_payload)
    artifact_refs = tuple(_artifact_ref_summaries(list(result_payload.get("artifact_refs") or []), edge=edge))
    receipt_refs = tuple(_receipt_ref_summaries(result_payload))
    result_refs = (
        {
            "ref_kind": "node_result",
            "result_ref": result_ref,
            "result_id": result.result_id,
            "node_id": result.node_id,
            "status": result.status,
        },
    )
    metadata = dict(edge.get("metadata") or {})
    delivery_policy = _delivery_policy(edge)
    edge_contract = edge_contract_or_projection(graph_config, edge)
    contract_packet = dict(edge_contract.get("packet") or {})
    contract_reliability = dict(edge_contract.get("reliability") or {})
    contract_protocol = dict(edge_contract.get("protocol") or {})
    contract_delivery_policy = str(contract_packet.get("delivery_policy") or delivery_policy)
    return FlowPacket(
        packet_id=f"flowpkt:{stable_safe_id(state.graph_run_id)}:{stable_safe_id(edge_id)}:{stable_safe_id(result.result_id)}",
        packet_type=str(contract_packet.get("packet_type") or _packet_type(edge, protocol_kind=str(contract_protocol.get("kind") or ""))),
        graph_run_id=state.graph_run_id,
        task_run_id=state.task_run_id,
        source_unit_id=result.node_id,
        target_unit_id=target_node_id,
        source_port_id=str(edge.get("source_port_id") or metadata.get("source_port_id") or ""),
        target_port_id=str(edge.get("target_port_id") or metadata.get("target_port_id") or ""),
        edge_id=edge_id,
        scope_id=str(edge.get("scope_id") or metadata.get("scope_id") or ""),
        contract_id=str(contract_packet.get("payload_contract_id") or _contract_id(edge)),
        packet_contract_id=str(contract_packet.get("packet_contract_id") or _packet_contract_id(edge)),
        target_context_key=str(contract_packet.get("target_context_key") or _target_context_key(edge)),
        target_input_slot=str(contract_packet.get("target_input_slot") or _target_input_slot(edge)),
        a2a_message_type=str(edge.get("a2a_message_type") or ""),
        payload_summary=str(result.handoff_summary or "")[:1200],
        payload_refs=(
            {
                "ref_kind": "node_result_payload",
                "result_ref": result_ref,
                "node_id": result.node_id,
            },
        ),
        artifact_refs=artifact_refs,
        memory_refs=tuple(_memory_ref_summaries(result_payload)),
        result_refs=result_refs,
        receipt_refs=receipt_refs,
        visible_payload=visible_payload,
        visibility={
            "delivery_policy": contract_delivery_policy,
            "ack_required": bool(contract_reliability.get("ack_required", edge.get("ack_required", True))),
            "include_output_keys": sorted(_included_output_keys(dict(edge.get("context_filter_policy") or {}))),
            "max_chars": _int_value(dict(edge.get("context_filter_policy") or {}).get("max_chars") or dict(edge.get("context_filter_policy") or {}).get("max_output_chars"), 0),
            "artifact_ref_policy": dict(edge.get("artifact_ref_policy") or {}),
            "edge_contract_id": str(edge_contract.get("contract_id") or ""),
            "protocol_kind": str(contract_protocol.get("kind") or ""),
        },
        status="accepted",
        lineage={
            "source_authority": "harness.graph_node_result_envelope",
            "graph_config_id": graph_config.config_id,
            "graph_config_hash": graph_config.content_hash,
            "result_id": result.result_id,
            "result_ref": result_ref,
            "work_order_id": result.work_order_id,
            "edge_id": edge_id,
            "source_node_id": result.node_id,
            "target_node_id": target_node_id,
        },
        created_at=float(created_at or time.time()),
    )


def flow_packet_inbound_projection(packet: FlowPacket, *, packet_ref: str = "") -> dict[str, Any]:
    return {
        "authority": "harness.graph.inbound_context",
        "packet_authority": packet.authority,
        "context_id": f"ginctx:{stable_safe_id(packet.graph_run_id)}:{stable_safe_id(packet.edge_id)}:{stable_safe_id(packet.packet_id)}",
        "packet_id": packet.packet_id,
        "packet_ref": packet_ref,
        "packet_type": packet.packet_type,
        "source_node_id": packet.source_unit_id,
        "target_node_id": packet.target_unit_id,
        "source_edge_id": packet.edge_id,
        "edge_id": packet.edge_id,
        "payload_contract_id": packet.contract_id,
        "packet_contract_id": packet.packet_contract_id,
        "target_context_key": packet.target_context_key,
        "target_input_slot": packet.target_input_slot,
        "payload": dict(packet.visible_payload or {}),
        "delivery_policy": str(dict(packet.visibility or {}).get("delivery_policy") or ""),
        "ack_required": bool(dict(packet.visibility or {}).get("ack_required", True)),
        "result_refs": [dict(item) for item in packet.result_refs],
        "artifact_refs": [dict(item) for item in packet.artifact_refs],
        "memory_refs": [dict(item) for item in packet.memory_refs],
        "receipt_refs": [dict(item) for item in packet.receipt_refs],
        "visibility": dict(packet.visibility or {}),
        "lineage": dict(packet.lineage or {}),
    }


def _packet_type(edge: dict[str, Any], *, protocol_kind: str = "") -> str:
    explicit = str(edge.get("packet_type") or "").strip()
    if explicit:
        return explicit
    if protocol_kind:
        return f"flow_packet.{protocol_kind}"
    edge_type = str(edge.get("edge_type") or "handoff").strip() or "handoff"
    return f"flow_packet.{edge_type}"


def _contract_id(edge: dict[str, Any]) -> str:
    bindings = dict(edge.get("contract_bindings") or {})
    schema = dict(bindings.get("schema") or {})
    handoff = dict(bindings.get("handoff") or {})
    return str(edge.get("payload_contract_id") or schema.get("payload_contract_id") or handoff.get("packet_contract_id") or "").strip()


def _packet_contract_id(edge: dict[str, Any]) -> str:
    bindings = dict(edge.get("contract_bindings") or {})
    handoff = dict(bindings.get("handoff") or {})
    return str(edge.get("packet_contract_id") or handoff.get("packet_contract_id") or _contract_id(edge)).strip()


def _target_context_key(edge: dict[str, Any]) -> str:
    metadata = dict(edge.get("metadata") or {})
    artifact_policy = dict(edge.get("artifact_ref_policy") or {})
    bindings = dict(edge.get("contract_bindings") or {})
    handoff = dict(bindings.get("handoff") or {})
    return str(
        edge.get("target_context_key")
        or handoff.get("target_context_key")
        or metadata.get("target_context_key")
        or metadata.get("target_input_key")
        or artifact_policy.get("target_input_key")
        or ""
    ).strip()


def _target_input_slot(edge: dict[str, Any]) -> str:
    metadata = dict(edge.get("metadata") or {})
    bindings = dict(edge.get("contract_bindings") or {})
    handoff = dict(bindings.get("handoff") or {})
    return str(edge.get("target_input_slot") or handoff.get("target_input_slot") or metadata.get("target_input_slot") or metadata.get("input_alias") or "").strip()


def _delivery_policy(edge: dict[str, Any]) -> str:
    return str(edge.get("result_delivery_policy") or "summary_and_refs").strip() or "summary_and_refs"


def _visible_payload_for_edge(*, edge: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    delivery_policy = _delivery_policy(edge)
    handoff_summary = str(result.get("handoff_summary") or "")
    artifact_refs = _filter_artifact_ref_values(
        list(result.get("artifact_refs") or []),
        artifact_ref_policy=dict(edge.get("artifact_ref_policy") or {}),
    )
    base_refs = {
        "artifact_refs": artifact_refs,
        "receipt_refs": _receipt_ref_summaries(result),
        "handoff_summary": handoff_summary,
        **_source_quality_payload(result),
    }
    if delivery_policy in {"notification_only", "status_only", "summary_only"}:
        return {"handoff_summary": handoff_summary}
    if delivery_policy in {"refs_only", "artifact_refs_only"}:
        return base_refs
    if delivery_policy in {"summary_and_refs", "contract_payload_and_refs"}:
        output_payload = _filter_outputs(
            dict(result.get("outputs") or {}),
            context_filter_policy=dict(edge.get("context_filter_policy") or {}),
        )
        artifact_payload = _artifact_text_payload(artifact_refs, edge=edge)
        if artifact_payload:
            base_refs = {**base_refs, "artifact_payloads": artifact_payload}
        if output_payload:
            return {**base_refs, "bounded_outputs": output_payload}
        return base_refs
    return {"handoff_summary": handoff_summary}


def _source_quality_payload(result: dict[str, Any]) -> dict[str, Any]:
    error = dict(result.get("error") or {})
    diagnostics = dict(result.get("diagnostics") or {})
    quality_acceptance = dict(diagnostics.get("quality_acceptance") or {})
    if not error and not quality_acceptance:
        return {}
    payload: dict[str, Any] = {}
    if error:
        payload["source_error"] = error
    if quality_acceptance:
        payload["quality_acceptance"] = quality_acceptance
        if not str(error.get("quality_issue_summary") or "").strip() and str(quality_acceptance.get("quality_issue_summary") or "").strip():
            payload.setdefault("source_error", {})["quality_issue_summary"] = str(quality_acceptance.get("quality_issue_summary") or "")
    return payload


def _artifact_text_payload(refs: list[str], *, edge: dict[str, Any]) -> list[dict[str, Any]]:
    policy = dict(edge.get("artifact_ref_policy") or {})
    if policy.get("include_text") is False or policy.get("expand_text") is False:
        return []
    if str(edge.get("result_delivery_policy") or "") == "refs_only":
        return []
    max_refs = _int_value(policy.get("max_text_refs") or policy.get("max_refs") or 2, 2)
    max_chars = _int_value(policy.get("max_text_chars") or policy.get("max_chars") or 30000, 30000)
    if max_refs <= 0 or max_chars <= 0:
        return []
    payloads: list[dict[str, Any]] = []
    for ref in refs[:max_refs]:
        text, truncated = _read_artifact_text(ref, max_chars=max_chars)
        if not text:
            continue
        payloads.append(
            {
                "artifact_ref": ref,
                "content": text,
                "truncated": truncated,
                "max_chars": max_chars,
                "authority": "harness.graph.flow_packet.artifact_text_projection",
            }
        )
    return payloads


def _read_artifact_text(ref: str, *, max_chars: int) -> tuple[str, bool]:
    raw = Path(str(ref or "")).expanduser()
    candidates = [raw] if raw.is_absolute() else [
        Path.cwd() / raw,
        Path.cwd().parent / raw,
        Path(__file__).resolve().parents[3] / raw,
    ]
    for path in candidates:
        try:
            resolved = path.resolve()
        except OSError:
            continue
        try:
            if resolved.is_file():
                content = resolved.read_text(encoding="utf-8", errors="replace")
                return content[:max_chars].rstrip(), len(content) > max_chars
        except OSError:
            continue
    return "", False


def _filter_outputs(outputs: dict[str, Any], *, context_filter_policy: dict[str, Any]) -> dict[str, Any]:
    include_keys = _included_output_keys(context_filter_policy)
    if not include_keys:
        return {}
    filtered = {key: value for key, value in outputs.items() if str(key) in include_keys}
    for key in _string_set(
        context_filter_policy.get("exclude_output_keys")
        or context_filter_policy.get("blocked_output_keys")
        or context_filter_policy.get("exclude_keys")
        or context_filter_policy.get("deny")
    ):
        filtered.pop(key, None)
    max_chars = _int_value(context_filter_policy.get("max_chars") or context_filter_policy.get("max_output_chars"), 0)
    if max_chars <= 0:
        return {}
    return {key: _truncate_value(value, max_chars=max_chars) for key, value in filtered.items()}


def _included_output_keys(context_filter_policy: dict[str, Any]) -> set[str]:
    return _string_set(
        context_filter_policy.get("include_output_keys")
        or context_filter_policy.get("allowed_output_keys")
        or context_filter_policy.get("include_keys")
        or context_filter_policy.get("allow")
    )


def _filter_artifact_ref_values(refs: list[Any], *, artifact_ref_policy: dict[str, Any]) -> list[str]:
    if artifact_ref_policy.get("include") is False or artifact_ref_policy.get("enabled") is False:
        return []
    max_refs = _int_value(artifact_ref_policy.get("max_refs") or artifact_ref_policy.get("limit"), 0)
    normalized_refs = dedupe_artifact_refs([normalize_artifact_ref(item) for item in refs])
    result = [artifact_ref_value(item) for item in normalized_refs if artifact_ref_value(item)]
    if max_refs > 0:
        result = result[:max_refs]
    return result


def _artifact_ref_summaries(refs: list[Any], *, edge: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"ref_kind": "artifact", "artifact_ref": ref}
        for ref in _filter_artifact_ref_values(refs, artifact_ref_policy=dict(edge.get("artifact_ref_policy") or {}))
    ]


def _memory_ref_summaries(result: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for receipt in list(result.get("memory_commit_receipts") or []):
        if not isinstance(receipt, dict):
            continue
        item = {
            "ref_kind": "memory",
            "repository_id": str(receipt.get("repository_id") or ""),
            "collection_id": str(receipt.get("collection_id") or receipt.get("collection") or ""),
            "record_key": str(receipt.get("record_key") or ""),
            "memory_ref": str(receipt.get("memory_ref") or receipt.get("record_ref") or ""),
        }
        refs.append({key: value for key, value in item.items() if value})
    return refs


def _receipt_ref_summaries(result: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for receipt_key, receipt_kind in (
        ("progress_receipts", "progress"),
        ("artifact_materialization_receipts", "artifact_materialization"),
        ("memory_commit_receipts", "memory_commit"),
    ):
        for receipt in list(result.get(receipt_key) or []):
            if not isinstance(receipt, dict):
                continue
            item = {
                "receipt_kind": receipt_kind,
                "receipt_id": str(receipt.get("receipt_id") or receipt.get("id") or ""),
                "status": str(receipt.get("status") or ""),
                "artifact_ref": str(receipt.get("artifact_ref") or ""),
                "memory_ref": str(receipt.get("memory_ref") or receipt.get("record_ref") or ""),
                "repository_id": str(receipt.get("repository_id") or ""),
                "record_key": str(receipt.get("record_key") or ""),
            }
            refs.append({key: value for key, value in item.items() if value})
    return refs


def _truncate_value(value: Any, *, max_chars: int) -> Any:
    if isinstance(value, str) and len(value) > max_chars:
        return value[:max_chars].rstrip()
    if isinstance(value, dict):
        return {key: _truncate_value(item, max_chars=max_chars) for key, item in value.items()}
    if isinstance(value, list):
        return [_truncate_value(item, max_chars=max_chars) for item in value]
    return value


def _string_set(value: Any) -> set[str]:
    if isinstance(value, str):
        return {value.strip()} if value.strip() else set()
    return {str(item).strip() for item in list(value or []) if str(item).strip()}


def _int_value(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
