from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class TaskContractDescriptor:
    contract_id: str
    title: str
    contract_kind: str
    summary: str = ""
    source_refs: tuple[str, ...] = ()
    usage_refs: tuple[str, ...] = ()
    editable: bool = False
    status: str = "derived"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["source_refs"] = list(self.source_refs)
        payload["usage_refs"] = list(self.usage_refs)
        return payload
