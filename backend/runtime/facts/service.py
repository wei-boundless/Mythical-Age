from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any

from .schema import RuntimeFactEdge, RuntimeFactRecord
from .store import RuntimeFactLedgerStore, safe_fact_id


class RuntimeFactLedger:
    authority = "runtime.fact_ledger"

    def __init__(self, root_dir: str | Path, *, store: RuntimeFactLedgerStore | None = None) -> None:
        self.store = store or RuntimeFactLedgerStore(root_dir)

    def record_fact(
        self,
        *,
        fact_type: str,
        scope: dict[str, Any] | None = None,
        source: dict[str, Any] | None = None,
        refs: dict[str, Any] | None = None,
        attributes: dict[str, Any] | None = None,
        summary: str = "",
        visibility: str = "internal",
        retention_class: str = "diagnostic_ttl",
        model_visibility: str = "never",
        fact_id: str = "",
        idempotency_key: str = "",
        created_at: float | None = None,
    ) -> RuntimeFactRecord:
        normalized_scope = _compact_mapping(scope or {})
        normalized_refs = _compact_mapping(refs or {})
        resolved_idempotency_key = str(idempotency_key or "").strip()
        resolved_fact_id = str(fact_id or "").strip() or _fact_id(
            fact_type=fact_type,
            scope=normalized_scope,
            refs=normalized_refs,
            idempotency_key=resolved_idempotency_key,
        )
        record = RuntimeFactRecord(
            fact_id=resolved_fact_id,
            fact_type=str(fact_type or "").strip(),
            scope=normalized_scope,
            source=_compact_mapping(source or {}),
            refs=normalized_refs,
            attributes=_compact_mapping(attributes or {}),
            summary=_trim(summary, limit=800),
            created_at=time.time() if created_at is None else float(created_at),
            visibility=str(visibility or "internal"),
            retention_class=str(retention_class or "diagnostic_ttl"),
            model_visibility=str(model_visibility or "never"),
            idempotency_key=resolved_idempotency_key or resolved_fact_id,
        )
        return self.store.append_record(record)

    def link_facts(
        self,
        *,
        source_fact_id: str,
        target_fact_id: str,
        relation: str,
        confidence: float = 1.0,
        attributes: dict[str, Any] | None = None,
        edge_id: str = "",
        idempotency_key: str = "",
        created_at: float | None = None,
    ) -> RuntimeFactEdge:
        normalized_source = str(source_fact_id or "").strip()
        normalized_target = str(target_fact_id or "").strip()
        normalized_relation = str(relation or "").strip()
        resolved_idempotency_key = str(idempotency_key or "").strip() or ":".join(
            ["fact-edge", normalized_relation, normalized_source, normalized_target]
        )
        resolved_edge_id = str(edge_id or "").strip() or f"rtfedge:{safe_fact_id(resolved_idempotency_key)}"
        edge = RuntimeFactEdge(
            edge_id=resolved_edge_id,
            source_fact_id=normalized_source,
            target_fact_id=normalized_target,
            relation=normalized_relation,
            confidence=float(confidence),
            created_at=time.time() if created_at is None else float(created_at),
            attributes=_compact_mapping(attributes or {}),
            idempotency_key=resolved_idempotency_key,
        )
        return self.store.append_edge(edge)

    def get_record(self, fact_id: str, *, include_tombstones: bool = False) -> RuntimeFactRecord | None:
        return self.store.get_record(fact_id, include_tombstones=include_tombstones)

    def list_records(self, **kwargs: Any) -> list[RuntimeFactRecord]:
        return self.store.list_records(**kwargs)

    def list_edges(self, **kwargs: Any) -> list[RuntimeFactEdge]:
        return self.store.list_edges(**kwargs)

    def prune_task_runs(self, task_run_ids: set[str] | list[str] | tuple[str, ...]) -> dict[str, Any]:
        return self.store.prune_task_runs(task_run_ids)

    def prune_session(self, session_id: str) -> dict[str, Any]:
        return self.store.prune_session(session_id)

    def summarize_scope(self, *, task_run_id: str = "", session_id: str = "") -> dict[str, Any]:
        return self.store.summarize_scope(task_run_id=task_run_id, session_id=session_id)


def _fact_id(*, fact_type: str, scope: dict[str, Any], refs: dict[str, Any], idempotency_key: str) -> str:
    if idempotency_key:
        return f"rtfact:{safe_fact_id(idempotency_key)}"
    parts = [
        str(fact_type or "fact"),
        str(scope.get("task_run_id") or scope.get("turn_run_id") or scope.get("session_id") or ""),
        str(refs.get("trace_id") or refs.get("execution_id") or refs.get("usage_id") or ""),
        uuid.uuid4().hex[:12],
    ]
    return f"rtfact:{safe_fact_id(':'.join(part for part in parts if part))}"


def _compact_mapping(payload: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in dict(payload or {}).items():
        if value in (None, "", [], {}):
            continue
        if isinstance(value, str):
            result[str(key)] = _trim(value, limit=1200)
        elif isinstance(value, (bool, int, float)):
            result[str(key)] = value
        elif isinstance(value, dict):
            result[str(key)] = _compact_mapping(value)
        elif isinstance(value, (list, tuple)):
            result[str(key)] = [_trim(item, limit=400) if isinstance(item, str) else item for item in list(value)[:20]]
        else:
            result[str(key)] = _trim(value, limit=400)
    return result


def _trim(value: Any, *, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."
