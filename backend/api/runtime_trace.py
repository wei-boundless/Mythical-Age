from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from api.deps import require_runtime


router = APIRouter()


@router.get("/runtime/traces")
def list_runtime_traces(
    session_id: str = "",
    task_run_id: str = "",
    graph_run_id: str = "",
    trace_id: str = "",
    limit: int = 50,
) -> dict[str, Any]:
    ledger = _fact_ledger()
    filters = _scope_filters(
        session_id=session_id,
        task_run_id=task_run_id,
        graph_run_id=graph_run_id,
        trace_id=trace_id,
    )
    records = ledger.list_records(fact_type="trace_run", limit=_bounded_limit(limit, default=50, maximum=500), **filters)
    return {
        "authority": "runtime_trace.api.trace_index",
        "filters": filters,
        "count": len(records),
        "traces": [_trace_ref_from_fact(item) for item in records],
    }


@router.get("/runtime/traces/{trace_id:path}")
def get_runtime_trace(
    trace_id: str,
    include_spans: bool = False,
    include_events: bool = False,
    limit: int = 200,
) -> dict[str, Any]:
    normalized_trace_id = str(trace_id or "").strip()
    if not normalized_trace_id:
        raise HTTPException(status_code=400, detail="trace_id is required")
    trace_service = _trace_service()
    summary = dict(trace_service.summarize_trace(normalized_trace_id) or {})
    if summary.get("available") is not True:
        raise HTTPException(status_code=404, detail="Runtime trace not found")
    bounded_limit = _bounded_limit(limit, default=200, maximum=1000)
    payload: dict[str, Any] = {
        "authority": "runtime_trace.api.trace_detail",
        "trace_id": normalized_trace_id,
        "summary": _compact_trace_summary(summary),
    }
    store = getattr(trace_service, "store", None)
    if include_spans:
        reader = getattr(store, "list_spans", None)
        payload["spans"] = [
            _compact_trace_span(item.to_dict() if hasattr(item, "to_dict") else dict(item))
            for item in (list(reader(trace_id=normalized_trace_id, limit=bounded_limit)) if callable(reader) else [])
        ]
    if include_events:
        reader = getattr(store, "list_events", None)
        payload["events"] = [
            _compact_trace_event(item.to_dict() if hasattr(item, "to_dict") else dict(item))
            for item in (list(reader(trace_id=normalized_trace_id, limit=bounded_limit)) if callable(reader) else [])
        ]
    return payload


def _host() -> Any:
    runtime = require_runtime()
    return runtime.harness_runtime.single_agent_runtime_host


def _fact_ledger() -> Any:
    ledger = getattr(_host(), "fact_ledger", None)
    if ledger is None:
        raise HTTPException(status_code=503, detail="RuntimeFactLedger is not available")
    return ledger


def _trace_service() -> Any:
    service = getattr(_host(), "trace_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="RuntimeTraceService is not available")
    return service


def _scope_filters(*, session_id: str, task_run_id: str, graph_run_id: str, trace_id: str) -> dict[str, str]:
    filters: dict[str, str] = {}
    for key, value in {
        "session_id": session_id,
        "task_run_id": task_run_id,
        "graph_run_id": graph_run_id,
        "trace_id": trace_id,
    }.items():
        normalized = str(value or "").strip()
        if normalized:
            filters[key] = normalized
    return filters


def _trace_ref_from_fact(record: Any) -> dict[str, Any]:
    refs = dict(getattr(record, "refs", {}) or {})
    scope = dict(getattr(record, "scope", {}) or {})
    trace_id = str(refs.get("trace_id") or "").strip()
    return {
        "trace_id": trace_id,
        "fact_id": str(getattr(record, "fact_id", "") or ""),
        "run_kind": _run_kind_from_summary(str(getattr(record, "summary", "") or "")),
        "scope": _compact_refs(scope),
        "refs": _compact_refs(refs),
        "summary": _short_text(getattr(record, "summary", ""), limit=240),
        "created_at": float(getattr(record, "created_at", 0.0) or 0.0),
    }


def _compact_trace_summary(summary: dict[str, Any]) -> dict[str, Any]:
    latest_span = dict(summary.get("latest_span") or {})
    return {
        "authority": "runtime_trace.api.summary",
        "trace_id": str(summary.get("trace_id") or ""),
        "available": bool(summary.get("available")),
        "run": _compact_trace_run(dict(summary.get("run") or {})),
        "span_count": int(summary.get("span_count") or 0),
        "event_count": int(summary.get("event_count") or 0),
        "error_span_count": int(summary.get("error_span_count") or 0),
        "latest_span": _compact_trace_span(latest_span) if latest_span else None,
    }


def _compact_trace_run(run: dict[str, Any]) -> dict[str, Any]:
    return {
        "trace_id": str(run.get("trace_id") or ""),
        "run_kind": str(run.get("run_kind") or ""),
        "root_run_id": str(run.get("root_run_id") or ""),
        "status": str(run.get("status") or ""),
        "terminal_reason": str(run.get("terminal_reason") or ""),
        "started_at": float(run.get("started_at") or 0.0),
        "ended_at": float(run.get("ended_at") or 0.0),
        "scope": _compact_refs(dict(run.get("scope") or {})),
        "refs": _compact_refs(dict(run.get("refs") or {})),
    }


def _compact_trace_span(span: dict[str, Any]) -> dict[str, Any]:
    return {
        "trace_id": str(span.get("trace_id") or ""),
        "span_id": str(span.get("span_id") or ""),
        "parent_span_id": str(span.get("parent_span_id") or ""),
        "name": str(span.get("name") or ""),
        "span_kind": str(span.get("span_kind") or ""),
        "status": str(span.get("status") or ""),
        "started_at": float(span.get("started_at") or 0.0),
        "ended_at": float(span.get("ended_at") or 0.0),
        "latency_ms": float(span.get("latency_ms") or 0.0),
        "scope": _compact_refs(dict(span.get("scope") or {})),
        "refs": _compact_refs(dict(span.get("refs") or {})),
    }


def _compact_trace_event(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "trace_id": str(event.get("trace_id") or ""),
        "event_id": str(event.get("event_id") or ""),
        "span_id": str(event.get("span_id") or ""),
        "name": str(event.get("name") or ""),
        "created_at": float(event.get("created_at") or 0.0),
        "scope": _compact_refs(dict(event.get("scope") or {})),
        "refs": _compact_refs(dict(event.get("refs") or {})),
    }


def _compact_refs(payload: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in dict(payload or {}).items():
        if value in (None, "", [], {}):
            continue
        if isinstance(value, (bool, int, float)):
            result[str(key)] = value
        else:
            result[str(key)] = _short_text(value, limit=240)
    return result


def _run_kind_from_summary(summary: str) -> str:
    head, _, _tail = str(summary or "").partition(":")
    return head.strip()


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
