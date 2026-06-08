from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from api.deps import require_runtime


router = APIRouter()


@router.get("/runtime/facts")
def list_runtime_facts(
    session_id: str = "",
    turn_id: str = "",
    turn_run_id: str = "",
    task_run_id: str = "",
    graph_run_id: str = "",
    trace_id: str = "",
    span_id: str = "",
    execution_id: str = "",
    usage_id: str = "",
    memory_ref: str = "",
    fact_type: str = "",
    include_tombstones: bool = False,
    include_attributes: bool = False,
    limit: int = 100,
) -> dict[str, Any]:
    filters = _fact_filters(
        session_id=session_id,
        turn_id=turn_id,
        turn_run_id=turn_run_id,
        task_run_id=task_run_id,
        graph_run_id=graph_run_id,
        trace_id=trace_id,
        span_id=span_id,
        execution_id=execution_id,
        usage_id=usage_id,
        memory_ref=memory_ref,
        fact_type=fact_type,
    )
    ledger = _fact_ledger()
    records = ledger.list_records(
        include_tombstones=bool(include_tombstones),
        limit=_bounded_limit(limit, default=100, maximum=1000),
        **filters,
    )
    return {
        "authority": "runtime_facts.api.fact_index",
        "filters": filters,
        "include_tombstones": bool(include_tombstones),
        "include_attributes": bool(include_attributes),
        "count": len(records),
        "records": [_fact_record_payload(item, include_attributes=include_attributes) for item in records],
    }


@router.get("/runtime/facts/{fact_id:path}")
def get_runtime_fact(fact_id: str, include_tombstones: bool = False, include_attributes: bool = False) -> dict[str, Any]:
    normalized_fact_id = str(fact_id or "").strip()
    if not normalized_fact_id:
        raise HTTPException(status_code=400, detail="fact_id is required")
    record = _fact_ledger().get_record(normalized_fact_id, include_tombstones=bool(include_tombstones))
    if record is None:
        raise HTTPException(status_code=404, detail="Runtime fact not found")
    return {
        "authority": "runtime_facts.api.fact_detail",
        "record": _fact_record_payload(record, include_attributes=include_attributes),
    }


def _fact_ledger() -> Any:
    runtime = require_runtime()
    host = runtime.harness_runtime.single_agent_runtime_host
    ledger = getattr(host, "fact_ledger", None)
    if ledger is None:
        raise HTTPException(status_code=503, detail="RuntimeFactLedger is not available")
    return ledger


def _fact_filters(
    *,
    session_id: str,
    turn_id: str,
    turn_run_id: str,
    task_run_id: str,
    graph_run_id: str,
    trace_id: str,
    span_id: str,
    execution_id: str,
    usage_id: str,
    memory_ref: str,
    fact_type: str,
) -> dict[str, str]:
    filters: dict[str, str] = {}
    for key, value in {
        "session_id": session_id,
        "turn_id": turn_id,
        "turn_run_id": turn_run_id,
        "task_run_id": task_run_id,
        "graph_run_id": graph_run_id,
        "trace_id": trace_id,
        "span_id": span_id,
        "execution_id": execution_id,
        "usage_id": usage_id,
        "memory_ref": memory_ref,
        "fact_type": fact_type,
    }.items():
        normalized = str(value or "").strip()
        if normalized:
            filters[key] = normalized
    return filters


def _fact_record_payload(record: Any, *, include_attributes: bool) -> dict[str, Any]:
    payload = {
        "fact_id": str(getattr(record, "fact_id", "") or ""),
        "fact_type": str(getattr(record, "fact_type", "") or ""),
        "scope": _compact_mapping(dict(getattr(record, "scope", {}) or {})),
        "source": _compact_mapping(dict(getattr(record, "source", {}) or {})),
        "refs": _compact_mapping(dict(getattr(record, "refs", {}) or {})),
        "summary": _short_text(getattr(record, "summary", ""), limit=800),
        "created_at": float(getattr(record, "created_at", 0.0) or 0.0),
        "visibility": str(getattr(record, "visibility", "") or ""),
        "retention_class": str(getattr(record, "retention_class", "") or ""),
        "model_visibility": str(getattr(record, "model_visibility", "") or ""),
        "tombstoned": bool(getattr(record, "tombstoned", False)),
        "deleted_at": float(getattr(record, "deleted_at", 0.0) or 0.0),
        "retention_reason": str(getattr(record, "retention_reason", "") or ""),
        "authority": "runtime_facts.api.fact_record",
    }
    if include_attributes:
        payload["attributes"] = _compact_mapping(dict(getattr(record, "attributes", {}) or {}))
    return payload


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
