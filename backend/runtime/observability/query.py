from __future__ import annotations

from typing import Any

from .sinks import RuntimeFactSink, RuntimeTraceSink


class RuntimeObservabilityQuery:
    authority = "runtime.observability.query"

    def __init__(self, *, trace_sink: RuntimeTraceSink, fact_sink: RuntimeFactSink) -> None:
        self.trace_sink = trace_sink
        self.fact_sink = fact_sink

    def trace_summary(
        self,
        *,
        trace_id: str = "",
        task_run_id: str = "",
        session_id: str = "",
        graph_run_id: str = "",
        hydrate: bool = True,
    ) -> dict[str, Any]:
        resolved_trace_id = str(trace_id or "").strip()
        trace_fact = None
        if not resolved_trace_id:
            trace_fact = self.latest_trace_run_fact(
                task_run_id=task_run_id,
                session_id=session_id,
                graph_run_id=graph_run_id,
            )
            resolved_trace_id = _record_ref(trace_fact, "trace_id") if trace_fact is not None else ""
        base = {
            "authority": "runtime.observability.trace_summary",
            "available": bool(resolved_trace_id),
            "hydrated": False,
            "trace_id": resolved_trace_id,
            "task_run_id": str(task_run_id or ""),
            "session_id": str(session_id or ""),
            "graph_run_id": str(graph_run_id or ""),
            "source_fact_id": _record_field(trace_fact, "fact_id") if trace_fact is not None else "",
            "detail_ref": {"kind": "trace", "trace_id": resolved_trace_id} if resolved_trace_id else {},
        }
        if not resolved_trace_id or not hydrate:
            return base
        raw = self.trace_sink.summarize_trace(resolved_trace_id)
        if raw.get("available") is not True:
            return {**base, "available": False, "hydrated": True}
        return {
            **base,
            "available": True,
            "hydrated": True,
            "run": _compact_trace_run(dict(raw.get("run") or {})),
            "span_count": int(raw.get("span_count") or 0),
            "event_count": int(raw.get("event_count") or 0),
            "error_span_count": int(raw.get("error_span_count") or 0),
            "latest_span": _compact_trace_span(dict(raw.get("latest_span") or {})),
        }

    def diagnostic_refs(
        self,
        *,
        task_run_id: str = "",
        session_id: str = "",
        graph_run_id: str = "",
        limit: int = 12,
    ) -> list[dict[str, Any]]:
        refs: list[dict[str, Any]] = []
        summary = self.trace_summary(
            task_run_id=task_run_id,
            session_id=session_id,
            graph_run_id=graph_run_id,
            hydrate=True,
        )
        trace_id = str(summary.get("trace_id") or "")
        if trace_id:
            refs.append(
                {
                    "kind": "trace",
                    "ref": f"trace:{trace_id}",
                    "trace_id": trace_id,
                    "task_run_id": str(task_run_id or ""),
                    "session_id": str(session_id or ""),
                    "graph_run_id": str(graph_run_id or ""),
                    "error_span_count": int(summary.get("error_span_count") or 0),
                }
            )
        for fact_type in ("monitor_signal", "health_issue"):
            for record in self.fact_records_for_scope(
                task_run_id=task_run_id,
                session_id=session_id,
                graph_run_id=graph_run_id,
                fact_type=fact_type,
                limit=max(1, int(limit or 12)),
            ):
                fact_id = _record_field(record, "fact_id")
                if fact_id:
                    refs.append(
                        {
                            "kind": "fact",
                            "ref": f"fact:{fact_id}",
                            "fact_id": fact_id,
                            "fact_type": fact_type,
                            "summary": str(_record_field(record, "summary") or "")[:240],
                            "created_at": float(_record_field(record, "created_at") or 0.0),
                        }
                    )
        return _dedupe_refs(refs)[: max(1, int(limit or 12))]

    def latest_trace_run_fact(self, *, task_run_id: str = "", session_id: str = "", graph_run_id: str = "") -> Any | None:
        records = [
            item
            for item in self.fact_records_for_scope(
                task_run_id=task_run_id,
                session_id=session_id,
                graph_run_id=graph_run_id,
                fact_type="trace_run",
                limit=50,
            )
            if _record_ref(item, "trace_id")
        ]
        if not records:
            return None
        return sorted(records, key=lambda item: float(_record_field(item, "created_at") or 0.0), reverse=True)[0]

    def fact_records_for_scope(
        self,
        *,
        task_run_id: str = "",
        session_id: str = "",
        graph_run_id: str = "",
        fact_type: str = "",
        limit: int = 200,
    ) -> list[Any]:
        queries: list[dict[str, Any]] = []
        normalized_task_run_id = str(task_run_id or "").strip()
        normalized_session_id = str(session_id or "").strip()
        normalized_graph_run_id = str(graph_run_id or "").strip()
        if normalized_task_run_id:
            queries.append({"task_run_id": normalized_task_run_id})
        if normalized_graph_run_id:
            queries.append({"graph_run_id": normalized_graph_run_id})
        if normalized_session_id:
            queries.append({"session_id": normalized_session_id})
        if not queries:
            return []
        seen: set[str] = set()
        result: list[Any] = []
        for query in queries:
            records = self.fact_sink.list_records(
                fact_type=fact_type,
                limit=max(1, int(limit or 200)),
                **query,
            )
            for record in records:
                fact_id = _record_field(record, "fact_id") or repr(record)
                if fact_id in seen:
                    continue
                seen.add(fact_id)
                result.append(record)
        return result


def _record_field(record: Any, field: str) -> Any:
    if record is None:
        return ""
    if isinstance(record, dict):
        return record.get(field)
    return getattr(record, field, "")


def _record_ref(record: Any, field: str) -> str:
    refs = _record_field(record, "refs")
    if isinstance(refs, dict):
        return str(refs.get(field) or "").strip()
    return ""


def _dedupe_refs(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for ref in refs:
        key = str(ref.get("ref") or ref.get("trace_id") or ref.get("fact_id") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(ref)
    return result


def _compact_trace_run(run: dict[str, Any]) -> dict[str, Any]:
    if not run:
        return {}
    return {
        "trace_id": str(run.get("trace_id") or ""),
        "run_kind": str(run.get("run_kind") or ""),
        "root_run_id": str(run.get("root_run_id") or ""),
        "status": str(run.get("status") or ""),
        "terminal_reason": str(run.get("terminal_reason") or ""),
        "started_at": float(run.get("started_at") or 0.0),
        "ended_at": float(run.get("ended_at") or 0.0),
        "scope": _compact_ref_payload(dict(run.get("scope") or {})),
        "refs": _compact_ref_payload(dict(run.get("refs") or {})),
    }


def _compact_trace_span(span: dict[str, Any]) -> dict[str, Any]:
    if not span:
        return {}
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
        "refs": _compact_ref_payload(dict(span.get("refs") or {})),
    }


def _compact_ref_payload(payload: dict[str, Any]) -> dict[str, Any]:
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
        "runtime_run_id",
        "action_request_ref",
        "observation_ref",
        "runtime_invocation_packet_ref",
        "fact_id",
        "tool_call_id",
        "executor_epoch",
    }
    result: dict[str, Any] = {}
    for key, value in dict(payload or {}).items():
        normalized_key = str(key or "")
        if normalized_key not in allowed or value in (None, "", [], {}):
            continue
        if isinstance(value, (bool, int, float)):
            result[normalized_key] = value
        else:
            result[normalized_key] = str(value)[:240]
    return result
