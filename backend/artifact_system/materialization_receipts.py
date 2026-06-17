from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any
import hashlib


@dataclass(frozen=True, slots=True)
class ArtifactMaterializationReceipt:
    receipt_id: str
    source_kind: str
    source_ref: str
    target_namespace_id: str
    artifact_ids: tuple[str, ...] = ()
    content_hashes: dict[str, str] = field(default_factory=dict)
    producer_task_run_id: str = ""
    producer_graph_run_id: str = ""
    producer_node_id: str = ""
    output_contract_id: str = ""
    status: str = "accepted"
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
    authority: str = "artifact_system.materializer"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["artifact_ids"] = list(self.artifact_ids)
        payload["content_hashes"] = dict(self.content_hashes)
        return payload


def build_materialization_receipt_id(*parts: Any) -> str:
    raw = "|".join(str(part or "").strip() for part in parts)
    return f"artifact-receipt:{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:24]}"
