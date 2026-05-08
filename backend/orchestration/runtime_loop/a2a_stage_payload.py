from __future__ import annotations

from typing import Any

from agents.a2a_official_adapter import build_a2a_preview_for_coordination


OFFICIAL_A2A_PROTOCOL_VERSION = "0.3.0"
OFFICIAL_A2A_TRANSPORT = "JSONRPC"
DEFAULT_A2A_MESSAGE_TYPE = "message/send"


def build_stage_execution_a2a_payload(
    *,
    coordination_run_id: str,
    root_task_run_id: str,
    stage_id: str,
    node_id: str,
    task_ref: str,
    agent_id: str,
    source_stage_id: str = "",
    source_agent_id: str = "",
    protocol_id: str = "",
    message_type: str = DEFAULT_A2A_MESSAGE_TYPE,
    explicit_inputs: dict[str, Any] | None = None,
    payload_contracts: list[str] | tuple[str, ...] = (),
    handoff_packets: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
    runtime_assembly_ref: str = "",
    contract_manifest_ref: str = "",
    ack_policy: str = "explicit_ack",
    handoff_policy: str = "",
) -> dict[str, Any]:
    payload = build_a2a_preview_for_coordination(
        coordination_task_id=coordination_run_id,
        protocol_id=protocol_id or f"a2a:{coordination_run_id}",
        source_agent_id=source_agent_id or "agent:0",
        target_agent_id=agent_id,
        message_type=message_type or DEFAULT_A2A_MESSAGE_TYPE,
        payload_contracts=payload_contracts,
        ack_policy=ack_policy,
        handoff_policy=handoff_policy,
    )
    message = dict(payload.get("message") or {})
    metadata = dict(message.get("metadata") or {})
    metadata.update(
        {
            "coordination_run_id": coordination_run_id,
            "root_task_run_id": root_task_run_id,
            "source_stage_id": source_stage_id,
            "target_stage_id": stage_id,
            "target_node_id": node_id,
            "target_task_ref": task_ref,
            "runtime_assembly_ref": runtime_assembly_ref,
            "contract_manifest_ref": contract_manifest_ref,
        }
    )
    message["metadata"] = metadata
    parts = list(message.get("parts") or [])
    parts.append(
        {
            "kind": "data",
            "data": {
                "explicit_inputs": dict(explicit_inputs or {}),
                "stage_id": stage_id,
                "node_id": node_id,
                "task_ref": task_ref,
                "handoff_packets": [dict(item) for item in handoff_packets],
                "runtime_assembly_ref": runtime_assembly_ref,
                "contract_manifest_ref": contract_manifest_ref,
            },
        }
    )
    message["parts"] = parts
    payload["message"] = message
    payload["authority"] = "orchestration.runtime_loop.official_a2a_stage_payload"
    payload["source_stage_id"] = source_stage_id
    payload["target_stage_id"] = stage_id
    payload["target_node_id"] = node_id
    payload["target_task_ref"] = task_ref
    return payload
