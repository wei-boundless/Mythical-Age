from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable


EligibilityPolicy = Callable[[Any], tuple[bool, str]]


@dataclass(frozen=True, slots=True)
class RuntimeFactMemoryCandidate:
    candidate_id: str
    source_fact_id: str
    fact_type: str
    summary: str
    scope: dict[str, Any] = field(default_factory=dict)
    refs: dict[str, Any] = field(default_factory=dict)
    eligibility_reason: str = ""
    created_at: float = 0.0
    authority: str = "memory_system.runtime_fact_bridge.candidate"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RuntimeFactBridge:
    """MemorySystem-owned bridge from RuntimeFactLedger facts to memory candidates."""

    authority = "memory_system.runtime_fact_bridge"

    def __init__(self, fact_ledger: Any, *, eligibility_policy: EligibilityPolicy | None = None) -> None:
        self.fact_ledger = fact_ledger
        self.eligibility_policy = eligibility_policy or default_memory_fact_eligibility

    def list_candidates(
        self,
        *,
        session_id: str = "",
        task_run_id: str = "",
        graph_run_id: str = "",
        trace_id: str = "",
        memory_ref: str = "",
        fact_type: str = "",
        limit: int = 200,
    ) -> dict[str, Any]:
        filters = _filters(
            session_id=session_id,
            task_run_id=task_run_id,
            graph_run_id=graph_run_id,
            trace_id=trace_id,
            memory_ref=memory_ref,
            fact_type=fact_type,
        )
        records = self.fact_ledger.list_records(limit=_bounded_limit(limit, default=200, maximum=1000), **filters)
        candidates: list[RuntimeFactMemoryCandidate] = []
        rejected_count = 0
        for record in records:
            eligible, reason = self.eligibility_policy(record)
            if not eligible:
                rejected_count += 1
                continue
            candidates.append(_candidate_from_fact(record, eligibility_reason=reason))
        return {
            "authority": self.authority,
            "filters": filters,
            "candidate_count": len(candidates),
            "rejected_count": rejected_count,
            "candidates": [item.to_dict() for item in candidates],
        }

    def record_memory_candidate(
        self,
        *,
        source_fact_id: str,
        memory_record_id: str = "",
        memory_version_id: str = "",
        summary: str = "",
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        source = self._source_fact(source_fact_id)
        fact = self.fact_ledger.record_fact(
            fact_type="memory_candidate",
            scope=dict(getattr(source, "scope", {}) or {}),
            source={
                "system": self.authority,
                "authority": self.authority,
                "source_ref": str(getattr(source, "fact_id", "") or ""),
            },
            refs={
                **_compact_refs(dict(getattr(source, "refs", {}) or {})),
                **_memory_refs(memory_record_id=memory_record_id, memory_version_id=memory_version_id),
                "source_fact_id": str(getattr(source, "fact_id", "") or ""),
            },
            summary=_short_text(summary or getattr(source, "summary", ""), limit=800),
            visibility="internal",
            retention_class="memory_governed",
            model_visibility="governed_memory_only",
            idempotency_key=idempotency_key or f"memory-candidate:{getattr(source, 'fact_id', '')}:{memory_record_id}:{memory_version_id}",
        )
        edge = self.fact_ledger.link_facts(
            source_fact_id=str(getattr(source, "fact_id", "") or ""),
            target_fact_id=fact.fact_id,
            relation="candidate_from_fact",
            attributes={"authority": self.authority},
        )
        return {
            "authority": self.authority,
            "candidate_fact_id": fact.fact_id,
            "source_fact_id": str(getattr(source, "fact_id", "") or ""),
            "edge_id": edge.edge_id,
        }

    def record_memory_commit(
        self,
        *,
        source_fact_id: str,
        memory_record_id: str = "",
        memory_version_id: str,
        summary: str = "",
        attributes: dict[str, Any] | None = None,
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        if not str(memory_version_id or "").strip():
            raise ValueError("record_memory_commit requires memory_version_id")
        source = self._source_fact(source_fact_id)
        fact = self.fact_ledger.record_fact(
            fact_type="memory_commit",
            scope=dict(getattr(source, "scope", {}) or {}),
            source={
                "system": self.authority,
                "authority": self.authority,
                "source_ref": str(getattr(source, "fact_id", "") or ""),
            },
            refs={
                **_compact_refs(dict(getattr(source, "refs", {}) or {})),
                **_memory_refs(memory_record_id=memory_record_id, memory_version_id=memory_version_id),
                "source_fact_id": str(getattr(source, "fact_id", "") or ""),
            },
            attributes=_compact_mapping(dict(attributes or {})),
            summary=_short_text(summary or getattr(source, "summary", ""), limit=800),
            visibility="internal",
            retention_class="memory_governed",
            model_visibility="governed_memory_only",
            idempotency_key=idempotency_key or f"memory-commit:{memory_version_id}:{getattr(source, 'fact_id', '')}",
        )
        edge = self.fact_ledger.link_facts(
            source_fact_id=str(getattr(source, "fact_id", "") or ""),
            target_fact_id=fact.fact_id,
            relation="promoted_to_memory",
            attributes={"authority": self.authority},
        )
        return {
            "authority": self.authority,
            "commit_fact_id": fact.fact_id,
            "source_fact_id": str(getattr(source, "fact_id", "") or ""),
            "memory_record_id": str(memory_record_id or ""),
            "memory_version_id": str(memory_version_id or ""),
            "edge_id": edge.edge_id,
        }

    def _source_fact(self, source_fact_id: str) -> Any:
        source = self.fact_ledger.get_record(str(source_fact_id or ""))
        if source is None:
            raise ValueError("source_fact_id not found")
        return source


def default_memory_fact_eligibility(record: Any) -> tuple[bool, str]:
    fact_type = str(getattr(record, "fact_type", "") or "").strip()
    retention_class = str(getattr(record, "retention_class", "") or "").strip()
    model_visibility = str(getattr(record, "model_visibility", "") or "").strip()
    if fact_type == "memory_candidate":
        return True, "explicit_memory_candidate_fact"
    if retention_class == "memory_governed":
        return True, "memory_governed_retention"
    if model_visibility == "governed_memory_only":
        return True, "governed_memory_visibility"
    return False, "not_memory_eligible"


def _candidate_from_fact(record: Any, *, eligibility_reason: str) -> RuntimeFactMemoryCandidate:
    fact_id = str(getattr(record, "fact_id", "") or "")
    return RuntimeFactMemoryCandidate(
        candidate_id=f"runtime-fact-memory-candidate:{fact_id}",
        source_fact_id=fact_id,
        fact_type=str(getattr(record, "fact_type", "") or ""),
        summary=_short_text(getattr(record, "summary", ""), limit=800),
        scope=_compact_mapping(dict(getattr(record, "scope", {}) or {})),
        refs=_compact_refs(dict(getattr(record, "refs", {}) or {})),
        eligibility_reason=eligibility_reason,
        created_at=float(getattr(record, "created_at", 0.0) or 0.0),
    )


def _filters(**values: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in values.items():
        normalized = str(value or "").strip()
        if normalized:
            result[key] = normalized
    return result


def _memory_refs(*, memory_record_id: str, memory_version_id: str) -> dict[str, str]:
    refs: dict[str, str] = {}
    if str(memory_record_id or "").strip():
        refs["memory_record_id"] = str(memory_record_id or "").strip()
    if str(memory_version_id or "").strip():
        refs["memory_version_id"] = str(memory_version_id or "").strip()
    return refs


def _compact_refs(payload: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "trace_id",
        "span_id",
        "task_run_id",
        "turn_id",
        "turn_run_id",
        "graph_run_id",
        "node_id",
        "work_order_id",
        "execution_id",
        "usage_id",
        "artifact_ref",
        "runtime_event_id",
        "memory_record_id",
        "memory_version_id",
        "source_fact_id",
    }
    return {key: value for key, value in _compact_mapping(payload).items() if key in allowed}


def _compact_mapping(payload: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in dict(payload or {}).items():
        if value in (None, "", [], {}):
            continue
        if isinstance(value, (bool, int, float)):
            result[str(key)] = value
        elif isinstance(value, dict):
            result[str(key)] = _compact_mapping(value)
        elif isinstance(value, (list, tuple)):
            result[str(key)] = [
                item if isinstance(item, (bool, int, float)) else _short_text(item, limit=240)
                for item in list(value)[:20]
            ]
        else:
            result[str(key)] = _short_text(value, limit=400)
    return result


def _bounded_limit(value: int, *, default: int, maximum: int) -> int:
    try:
        raw = int(value or default)
    except (TypeError, ValueError):
        raw = default
    return max(1, min(raw, maximum))


def _short_text(value: Any, *, limit: int) -> str:
    text = str(value or "").replace("\n", " ").strip()
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."
