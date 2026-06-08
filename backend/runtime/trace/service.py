from __future__ import annotations

import time
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any

from runtime.facts import RuntimeFactLedger

from .schema import RuntimeTraceEvent, RuntimeTraceRun, RuntimeTraceSpan, TraceContext
from .store import RuntimeTraceStore, _safe_id


class RuntimeTraceService:
    authority = "runtime.trace.service"

    def __init__(
        self,
        root_dir: str | Path,
        *,
        store: RuntimeTraceStore | None = None,
        fact_ledger: RuntimeFactLedger | None = None,
    ) -> None:
        self.store = store or RuntimeTraceStore(root_dir)
        self.fact_ledger = fact_ledger

    def start_trace(
        self,
        *,
        run_kind: str,
        root_run_id: str = "",
        scope: dict[str, Any] | None = None,
        refs: dict[str, Any] | None = None,
        attributes: dict[str, Any] | None = None,
        trace_id: str = "",
        idempotency_key: str = "",
        started_at: float | None = None,
    ) -> TraceContext:
        resolved_trace_id = str(trace_id or "").strip() or f"trace:{_safe_id(idempotency_key or root_run_id or uuid.uuid4().hex)}"
        resolved_idempotency_key = str(idempotency_key or "").strip() or resolved_trace_id
        existing = self.store.get_run_by_id_or_key(
            trace_id=resolved_trace_id,
            idempotency_key=resolved_idempotency_key,
            include_tombstones=True,
        )
        if existing is not None:
            return TraceContext(trace_id=existing.trace_id, scope=existing.scope, refs=existing.refs)
        run = RuntimeTraceRun(
            trace_id=resolved_trace_id,
            run_kind=str(run_kind or "").strip(),
            root_run_id=str(root_run_id or ""),
            scope=_compact(scope or {}),
            refs=_compact(refs or {}),
            attributes=_compact(attributes or {}),
            status="running",
            started_at=time.time() if started_at is None else float(started_at),
            idempotency_key=resolved_idempotency_key,
        )
        fact_id = ""
        if self.fact_ledger is not None:
            fact = self.fact_ledger.record_fact(
                fact_type="trace_run",
                scope=run.scope,
                source={"system": "runtime_trace", "authority": run.authority, "source_ref": run.trace_id},
                refs={"trace_id": run.trace_id, **run.refs},
                attributes=run.attributes,
                summary=f"{run.run_kind}:{run.root_run_id}",
                retention_class="diagnostic_ttl",
                idempotency_key=f"trace-run:{run.trace_id}",
                created_at=run.started_at,
            )
            fact_id = fact.fact_id
            run = replace(run, refs={**run.refs, "fact_id": fact_id})
        saved = self.store.upsert_run(run)
        return TraceContext(trace_id=saved.trace_id, scope=saved.scope, refs=saved.refs)

    def finish_trace(
        self,
        context: TraceContext,
        *,
        status: str,
        terminal_reason: str = "",
        ended_at: float | None = None,
    ) -> RuntimeTraceRun | None:
        run = self.store.get_run(context.trace_id, include_tombstones=True)
        if run is None:
            return None
        updated = replace(
            run,
            status=str(status or "completed"),
            terminal_reason=str(terminal_reason or ""),
            ended_at=time.time() if ended_at is None else float(ended_at),
        )
        return self.store.upsert_run(updated)

    def start_span(
        self,
        context: TraceContext,
        *,
        name: str,
        span_kind: str = "internal",
        refs: dict[str, Any] | None = None,
        attributes: dict[str, Any] | None = None,
        span_id: str = "",
        idempotency_key: str = "",
        started_at: float | None = None,
    ) -> TraceContext:
        normalized_idempotency_key = str(idempotency_key or "").strip()
        resolved_idempotency_key = _scoped_idempotency_key(
            "trace-span",
            context.trace_id,
            normalized_idempotency_key or str(span_id or "").strip() or uuid.uuid4().hex,
        )
        resolved_span_id = str(span_id or "").strip() or f"span:{_safe_id(resolved_idempotency_key)}"
        existing = self.store.get_span_by_id_or_key(
            span_id=resolved_span_id,
            idempotency_key=resolved_idempotency_key,
            include_tombstones=True,
        )
        if existing is not None:
            return context.child(span_id=existing.span_id, refs=existing.refs)
        merged_refs = {**dict(context.refs or {}), **_compact(refs or {})}
        span = RuntimeTraceSpan(
            trace_id=context.trace_id,
            span_id=resolved_span_id,
            parent_span_id=context.span_id,
            name=str(name or "").strip(),
            span_kind=str(span_kind or "internal"),
            scope=dict(context.scope or {}),
            refs=merged_refs,
            attributes=_compact(attributes or {}),
            status="running",
            started_at=time.time() if started_at is None else float(started_at),
            idempotency_key=resolved_idempotency_key,
        )
        if self.fact_ledger is not None:
            fact = self.fact_ledger.record_fact(
                fact_type="trace_span",
                scope=span.scope,
                source={"system": "runtime_trace", "authority": span.authority, "source_ref": span.span_id},
                refs={"trace_id": span.trace_id, "span_id": span.span_id, **span.refs},
                attributes=span.attributes,
                summary=span.name,
                retention_class="diagnostic_ttl",
                idempotency_key=f"trace-span:{span.span_id}",
                created_at=span.started_at,
            )
            span = replace(span, refs={**span.refs, "fact_id": fact.fact_id})
        saved = self.store.upsert_span(span)
        return context.child(span_id=saved.span_id, refs=saved.refs)

    def finish_span(
        self,
        span_context: TraceContext,
        *,
        status: str = "ok",
        error: dict[str, Any] | Exception | None = None,
        attributes: dict[str, Any] | None = None,
        ended_at: float | None = None,
    ) -> RuntimeTraceSpan | None:
        spans = self.store.list_spans(trace_id=span_context.trace_id, include_tombstones=True, limit=10000)
        current = next((item for item in spans if item.span_id == span_context.span_id), None)
        if current is None:
            return None
        error_payload = _error_payload(error)
        updated = replace(
            current,
            status=str(status or ("error" if error_payload else "ok")),
            error=error_payload,
            attributes={**dict(current.attributes or {}), **_compact(attributes or {})},
            ended_at=time.time() if ended_at is None else float(ended_at),
        )
        return self.store.upsert_span(updated)

    def record_event(
        self,
        context: TraceContext,
        *,
        name: str,
        refs: dict[str, Any] | None = None,
        attributes: dict[str, Any] | None = None,
        event_id: str = "",
        idempotency_key: str = "",
        created_at: float | None = None,
    ) -> RuntimeTraceEvent:
        normalized_idempotency_key = str(idempotency_key or "").strip()
        resolved_idempotency_key = _scoped_idempotency_key(
            "trace-event",
            context.trace_id,
            normalized_idempotency_key or str(event_id or "").strip() or uuid.uuid4().hex,
        )
        resolved_event_id = str(event_id or "").strip() or f"traceevt:{_safe_id(resolved_idempotency_key)}"
        event = RuntimeTraceEvent(
            trace_id=context.trace_id,
            event_id=resolved_event_id,
            name=str(name or "").strip(),
            span_id=context.span_id,
            scope=dict(context.scope or {}),
            refs={**dict(context.refs or {}), **_compact(refs or {})},
            attributes=_compact(attributes or {}),
            created_at=time.time() if created_at is None else float(created_at),
            idempotency_key=resolved_idempotency_key,
        )
        return self.store.append_event(event)

    def summarize_trace(self, trace_id: str) -> dict[str, Any]:
        return self.store.summarize_trace(trace_id)

    def prune_task_runs(self, task_run_ids: set[str] | list[str] | tuple[str, ...]) -> dict[str, Any]:
        return self.store.prune_task_runs(task_run_ids)

    def prune_session(self, session_id: str) -> dict[str, Any]:
        return self.store.prune_session(session_id)


def _compact(payload: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in dict(payload or {}).items():
        if value in (None, "", [], {}):
            continue
        if isinstance(value, str):
            result[str(key)] = value[:1200]
        elif isinstance(value, (bool, int, float)):
            result[str(key)] = value
        elif isinstance(value, dict):
            result[str(key)] = _compact(value)
        elif isinstance(value, (list, tuple)):
            result[str(key)] = list(value)[:20]
        else:
            result[str(key)] = str(value)[:400]
    return result


def _scoped_idempotency_key(prefix: str, trace_id: str, key: str) -> str:
    return ":".join(
        part
        for part in (str(prefix or "").strip(), str(trace_id or "").strip(), str(key or "").strip())
        if part
    )


def _error_payload(error: dict[str, Any] | Exception | None) -> dict[str, Any]:
    if error is None:
        return {}
    if isinstance(error, dict):
        return _compact(error)
    return {
        "type": error.__class__.__name__,
        "message": str(error)[:800],
    }
