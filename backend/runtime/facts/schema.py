from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


FACT_RECORD_AUTHORITY = "runtime.fact_ledger.record"
FACT_EDGE_AUTHORITY = "runtime.fact_ledger.edge"


@dataclass(frozen=True, slots=True)
class RuntimeFactRecord:
    fact_id: str
    fact_type: str
    scope: dict[str, Any] = field(default_factory=dict)
    source: dict[str, Any] = field(default_factory=dict)
    refs: dict[str, Any] = field(default_factory=dict)
    attributes: dict[str, Any] = field(default_factory=dict)
    summary: str = ""
    created_at: float = 0.0
    visibility: str = "internal"
    retention_class: str = "diagnostic_ttl"
    model_visibility: str = "never"
    idempotency_key: str = ""
    tombstoned: bool = False
    deleted_at: float = 0.0
    retention_reason: str = ""
    authority: str = FACT_RECORD_AUTHORITY

    def __post_init__(self) -> None:
        if self.authority != FACT_RECORD_AUTHORITY:
            raise ValueError("RuntimeFactRecord authority must be runtime.fact_ledger.record")
        if not str(self.fact_id or "").strip():
            raise ValueError("RuntimeFactRecord requires fact_id")
        if not str(self.fact_type or "").strip():
            raise ValueError("RuntimeFactRecord requires fact_type")
        if not str(self.idempotency_key or "").strip():
            object.__setattr__(self, "idempotency_key", self.fact_id)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RuntimeFactRecord":
        data = dict(payload or {})
        return cls(
            fact_id=str(data.get("fact_id") or ""),
            fact_type=str(data.get("fact_type") or ""),
            scope=dict(data.get("scope") or {}),
            source=dict(data.get("source") or {}),
            refs=dict(data.get("refs") or {}),
            attributes=dict(data.get("attributes") or {}),
            summary=str(data.get("summary") or ""),
            created_at=float(data.get("created_at") or 0.0),
            visibility=str(data.get("visibility") or "internal"),
            retention_class=str(data.get("retention_class") or "diagnostic_ttl"),
            model_visibility=str(data.get("model_visibility") or "never"),
            idempotency_key=str(data.get("idempotency_key") or data.get("fact_id") or ""),
            tombstoned=bool(data.get("tombstoned", False)),
            deleted_at=float(data.get("deleted_at") or 0.0),
            retention_reason=str(data.get("retention_reason") or ""),
            authority=str(data.get("authority") or FACT_RECORD_AUTHORITY),
        )


@dataclass(frozen=True, slots=True)
class RuntimeFactEdge:
    edge_id: str
    source_fact_id: str
    target_fact_id: str
    relation: str
    confidence: float = 1.0
    created_at: float = 0.0
    attributes: dict[str, Any] = field(default_factory=dict)
    idempotency_key: str = ""
    tombstoned: bool = False
    deleted_at: float = 0.0
    retention_reason: str = ""
    authority: str = FACT_EDGE_AUTHORITY

    def __post_init__(self) -> None:
        if self.authority != FACT_EDGE_AUTHORITY:
            raise ValueError("RuntimeFactEdge authority must be runtime.fact_ledger.edge")
        if not str(self.edge_id or "").strip():
            raise ValueError("RuntimeFactEdge requires edge_id")
        if not str(self.source_fact_id or "").strip():
            raise ValueError("RuntimeFactEdge requires source_fact_id")
        if not str(self.target_fact_id or "").strip():
            raise ValueError("RuntimeFactEdge requires target_fact_id")
        if not str(self.relation or "").strip():
            raise ValueError("RuntimeFactEdge requires relation")
        if not str(self.idempotency_key or "").strip():
            object.__setattr__(self, "idempotency_key", self.edge_id)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RuntimeFactEdge":
        data = dict(payload or {})
        return cls(
            edge_id=str(data.get("edge_id") or ""),
            source_fact_id=str(data.get("source_fact_id") or ""),
            target_fact_id=str(data.get("target_fact_id") or ""),
            relation=str(data.get("relation") or ""),
            confidence=float(data.get("confidence") or 0.0),
            created_at=float(data.get("created_at") or 0.0),
            attributes=dict(data.get("attributes") or {}),
            idempotency_key=str(data.get("idempotency_key") or data.get("edge_id") or ""),
            tombstoned=bool(data.get("tombstoned", False)),
            deleted_at=float(data.get("deleted_at") or 0.0),
            retention_reason=str(data.get("retention_reason") or ""),
            authority=str(data.get("authority") or FACT_EDGE_AUTHORITY),
        )
