from __future__ import annotations

from pathlib import Path
from typing import Callable

from task_system.registry.flow_models import TaskCommunicationProtocol
from task_system.repositories.common import merge_authoritative_defaults_by_key
from task_system.storage import TaskSystemStorage


class TaskCommunicationProtocolRepository:
    def __init__(
        self,
        base_dir: Path,
        *,
        default_protocols: Callable[[], tuple[TaskCommunicationProtocol, ...]],
    ) -> None:
        self.storage = TaskSystemStorage(base_dir)
        self.default_protocols = default_protocols

    def list(self) -> list[TaskCommunicationProtocol]:
        default_payload = [item.to_dict() for item in self.default_protocols()]
        payload = self.storage.read_object(
            "task_communication_protocols.json",
            {"communication_protocols": default_payload},
        )
        merged_payload = merge_authoritative_defaults_by_key(
            default_payload,
            [item for item in list(payload.get("communication_protocols") or []) if isinstance(item, dict)],
            key="protocol_id",
        )
        protocols: list[TaskCommunicationProtocol] = []
        for item in merged_payload:
            protocols.append(
                TaskCommunicationProtocol(
                    protocol_id=str(item.get("protocol_id") or ""),
                    title=str(item.get("title") or ""),
                    message_types=tuple(str(value).strip() for value in list(item.get("message_types") or []) if str(value).strip()),
                    payload_contracts=tuple(str(value).strip() for value in list(item.get("payload_contracts") or []) if str(value).strip()),
                    signal_rules=tuple(str(value).strip() for value in list(item.get("signal_rules") or []) if str(value).strip()),
                    handoff_rules=tuple(str(value).strip() for value in list(item.get("handoff_rules") or []) if str(value).strip()),
                    ack_policy=str(item.get("ack_policy") or "explicit_ack"),
                    timeout_policy=str(item.get("timeout_policy") or "fail_closed"),
                    error_signal_policy=str(item.get("error_signal_policy") or "raise_to_coordinator"),
                    enabled=bool(item.get("enabled", False)),
                    metadata=dict(item.get("metadata") or {}),
                )
            )
        normalized = [item.to_dict() for item in protocols]
        if payload.get("communication_protocols") != normalized:
            self.storage.write_object("task_communication_protocols.json", {"communication_protocols": normalized})
        return protocols

    def get(self, protocol_id: str) -> TaskCommunicationProtocol | None:
        target = str(protocol_id or "").strip()
        return next((item for item in self.list() if item.protocol_id == target), None)

    def upsert(
        self,
        *,
        protocol_id: str,
        title: str,
        message_types: tuple[str, ...] = (),
        payload_contracts: tuple[str, ...] = (),
        signal_rules: tuple[str, ...] = (),
        handoff_rules: tuple[str, ...] = (),
        ack_policy: str = "explicit_ack",
        timeout_policy: str = "fail_closed",
        error_signal_policy: str = "raise_to_coordinator",
        enabled: bool = False,
        metadata: dict[str, object] | None = None,
    ) -> TaskCommunicationProtocol:
        target = str(protocol_id or "").strip()
        if not target.startswith("protocol."):
            raise ValueError("protocol_id must start with protocol.")
        protocol = TaskCommunicationProtocol(
            protocol_id=target,
            title=str(title or target).strip(),
            message_types=tuple(str(value).strip() for value in message_types if str(value).strip()),
            payload_contracts=tuple(str(value).strip() for value in payload_contracts if str(value).strip()),
            signal_rules=tuple(str(value).strip() for value in signal_rules if str(value).strip()),
            handoff_rules=tuple(str(value).strip() for value in handoff_rules if str(value).strip()),
            ack_policy=str(ack_policy or "explicit_ack").strip(),
            timeout_policy=str(timeout_policy or "fail_closed").strip(),
            error_signal_policy=str(error_signal_policy or "raise_to_coordinator").strip(),
            enabled=bool(enabled),
            metadata=dict(metadata or {}),
        )
        protocols = [item for item in self.list() if item.protocol_id != target]
        protocols.append(protocol)
        self.storage.write_object(
            "task_communication_protocols.json",
            {"communication_protocols": [item.to_dict() for item in protocols]},
        )
        return protocol
