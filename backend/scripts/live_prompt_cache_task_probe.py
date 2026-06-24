from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any


BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from bootstrap.app_runtime import AppRuntime
from harness.entrypoint.models import HarnessRuntimeRequest
from harness.loop.task_executor import stop_task_run
from scripts.live_five_floor_dungeon_prompt_cache_e2e import (
    _cache_record_projection,
    _cache_summary,
    _code_review_runtime_contract,
    _packet_summary,
    _stability_projection,
    _usage_projection,
    _write_json,
)


TERMINAL_STATUSES = {"completed", "failed", "blocked", "aborted"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Start a real task_run and stop after a small provider-usage sample.")
    parser.add_argument("--provider", default="deepseek")
    parser.add_argument("--model", default="deepseek-v4-pro")
    parser.add_argument("--thinking-mode", default="enabled")
    parser.add_argument("--reasoning-effort", default="")
    parser.add_argument("--max-output-tokens", type=int, default=8192)
    parser.add_argument("--min-provider-calls", type=int, default=2)
    parser.add_argument("--stop-after-provider-calls", type=int, default=2)
    parser.add_argument("--stream-timeout-seconds", type=float, default=90.0)
    parser.add_argument("--task-timeout-seconds", type=float, default=240.0)
    parser.add_argument(
        "--independent-dynamic-tail",
        action="store_true",
        help="Probe the static/context/dynamic-tail physical model instead of folding the tail into append-only context.",
    )
    parser.add_argument(
        "--output-root",
        default=str(PROJECT_ROOT / "storage" / "runtime_state" / "prompt_cache_live_tests"),
    )
    args = parser.parse_args()
    try:
        report = asyncio.run(_run(args))
    except Exception as exc:
        print(f"LIVE TASK PROBE FAILED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(_summary(report), ensure_ascii=False, indent=2))
    return 0 if report.get("measurement_ok") and report.get("cache_contract_ok") else 2


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    run_id = f"task_probe_code_review_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    report_dir = Path(args.output_root).resolve() / run_id
    report_dir.mkdir(parents=True, exist_ok=True)

    runtime = AppRuntime()
    runtime.initialize(BACKEND_DIR)
    app = runtime.require_ready()
    settings = app.settings.static
    session = app.session_manager.create_session(
        title=f"Prompt cache task probe {run_id}",
        scope={"workspace_view": "task_environment", "task_environment_id": "env.coding.vibe_workspace"},
    )
    session_id = str(session["id"])
    model_selection = {
        "provider": str(args.provider or "deepseek"),
        "model": str(args.model or "deepseek-v4-pro"),
        "credential_ref": f"provider:{str(args.provider or 'deepseek')}:primary",
        "max_output_tokens": max(1, int(args.max_output_tokens or 8192)),
        "timeout_seconds": float(getattr(settings, "llm_timeout_seconds", 45.0) or 45.0),
        "long_output_timeout_seconds": float(getattr(settings, "llm_long_output_timeout_seconds", 180.0) or 180.0),
        "max_retries": 0,
        "temperature": 0,
        "thinking_mode": str(args.thinking_mode or "enabled"),
        "reasoning_effort": str(args.reasoning_effort or ""),
    }
    if bool(getattr(args, "independent_dynamic_tail", False)):
        model_selection["provider_extensions"] = {
            "context_cache_policy": {
                "context_physical_model": "static_context_dynamic_tail",
                "dynamic_tail_supported": True,
                "reason": "live_prompt_cache_task_probe_independent_dynamic_tail",
            }
        }
    runtime_contract = _code_review_runtime_contract(run_id=run_id, model_selection=model_selection)
    request = HarnessRuntimeRequest(
        session_id=session_id,
        message="启动真实只读代码审核任务，用于测量 task_execution prompt cache。按显式合同执行，不要修改文件。",
        runtime_contract=runtime_contract,
        model_selection=model_selection,
    )

    stream_events, task_run_id = await _start_task_run(
        app.harness_runtime,
        request,
        timeout_seconds=max(1.0, float(args.stream_timeout_seconds or 90.0)),
    )
    if not task_run_id:
        _write_json(report_dir / "stream_events.json", stream_events)
        raise RuntimeError("task_run was not created before stream timeout")

    wait_report = await _wait_for_provider_sample(
        app.harness_runtime,
        task_run_id=task_run_id,
        min_provider_calls=max(1, int(args.min_provider_calls or 1)),
        stop_after_provider_calls=max(0, int(args.stop_after_provider_calls or 0)),
        timeout_seconds=max(1.0, float(args.task_timeout_seconds or 240.0)),
    )
    host = app.harness_runtime.single_agent_runtime_host
    await _drain_background_tasks(host, timeout_seconds=10.0)

    task = host.state_index.get_task_run(task_run_id)
    ledger = host.prompt_accounting_ledger
    usage_rows = [item.to_dict() for item in ledger.list_token_usage(task_run_id=task_run_id)]
    provider_usage = [row for row in usage_rows if str(row.get("source") or "") == "provider_usage"]
    cache_records = [item.to_dict() for item in ledger.list_prompt_cache(task_run_id=task_run_id)]
    segment_maps = ledger.list_segment_maps(task_run_id=task_run_id)
    stability_reports = [item.to_dict() for item in ledger.list_prompt_stability(task_run_id=task_run_id)]
    cache_breaks = [item.to_dict() for item in ledger.list_prompt_cache_breaks(task_run_id=task_run_id)]
    trace = host.get_trace(task_run_id, include_payloads=True, include_model_messages=False)

    must_hit_cache_audit = _must_hit_cache_audit(
        provider_usage=provider_usage,
        cache_records=cache_records,
        segment_maps=segment_maps,
    )
    report = {
        "measurement_ok": bool(provider_usage) and bool(segment_maps),
        "cache_contract_ok": bool(must_hit_cache_audit.get("ok")),
        "authority": "backend.scripts.live_prompt_cache_task_probe",
        "run_id": run_id,
        "report_dir": str(report_dir),
        "session_id": session_id,
        "task_run_id": task_run_id,
        "task_status": str(getattr(task, "status", "") or ""),
        "task_terminal_reason": str(getattr(task, "terminal_reason", "") or ""),
        "model_selection": model_selection,
        "wait_report": wait_report,
        "summary": _cache_summary(provider_usage),
        "packet_summary": _packet_summary(segment_maps),
        "provider_usage": _usage_projection(provider_usage),
        "cache_records": _cache_record_projection(cache_records),
        "must_hit_cache_audit": must_hit_cache_audit,
        "cache_breaks": cache_breaks,
        "stability_reports": _stability_projection(stability_reports),
        "trace_event_types": _trace_event_counts(trace),
        "stream_event_types": [str(item.get("type") or "") for item in stream_events],
    }
    _write_json(report_dir / "stream_events.json", stream_events)
    _write_json(report_dir / "trace.json", trace)
    _write_json(report_dir / "provider_usage.json", provider_usage)
    _write_json(report_dir / "prompt_cache.json", cache_records)
    _write_json(report_dir / "segment_maps.json", segment_maps)
    _write_json(report_dir / "must_hit_cache_audit.json", must_hit_cache_audit)
    _write_json(report_dir / "prompt_stability.json", stability_reports)
    _write_json(report_dir / "prompt_cache_breaks.json", cache_breaks)
    _write_json(report_dir / "report.json", report)
    await runtime.shutdown()
    return report


async def _start_task_run(runtime_facade: Any, request: HarnessRuntimeRequest, *, timeout_seconds: float) -> tuple[list[dict[str, Any]], str]:
    events: list[dict[str, Any]] = []
    task_run_id = ""
    agen = runtime_facade.astream(request)
    deadline = time.monotonic() + timeout_seconds
    try:
        while time.monotonic() < deadline:
            try:
                event = await asyncio.wait_for(anext(agen), timeout=min(10.0, max(0.1, deadline - time.monotonic())))
            except StopAsyncIteration:
                break
            payload = dict(event)
            events.append(payload)
            task_run_id = _event_task_run_id(payload) or task_run_id
            if _is_start_stream_terminal(payload):
                break
    finally:
        await agen.aclose()
    return events, task_run_id


async def _wait_for_provider_sample(
    runtime_facade: Any,
    *,
    task_run_id: str,
    min_provider_calls: int,
    stop_after_provider_calls: int,
    timeout_seconds: float,
) -> dict[str, Any]:
    host = runtime_facade.single_agent_runtime_host
    ledger = host.prompt_accounting_ledger
    deadline = time.monotonic() + timeout_seconds
    stop_requested = False
    stop_requested_at = 0.0
    samples: list[dict[str, Any]] = []
    while time.monotonic() < deadline:
        task = host.state_index.get_task_run(task_run_id)
        usage = [item for item in ledger.list_token_usage(task_run_id=task_run_id) if item.source == "provider_usage"]
        status = str(getattr(task, "status", "") or "")
        samples.append({"t": round(time.time(), 3), "status": status, "provider_usage_records": len(usage)})
        if stop_after_provider_calls and len(usage) >= stop_after_provider_calls and not stop_requested and status not in TERMINAL_STATUSES:
            stop_task_run(host, task_run_id, reason="live_prompt_cache_task_probe_stop_after_provider_calls", requested_by="system")
            stop_requested = True
            stop_requested_at = time.monotonic()
        if stop_requested and len(usage) >= min_provider_calls and time.monotonic() - stop_requested_at >= 5.0:
            return _wait_result(task, usage, samples, stop_requested=stop_requested, timeout=False, min_provider_calls=min_provider_calls)
        if status in TERMINAL_STATUSES:
            return _wait_result(task, usage, samples, stop_requested=stop_requested, timeout=False, min_provider_calls=min_provider_calls)
        await asyncio.sleep(1.0)
    task = host.state_index.get_task_run(task_run_id)
    usage = [item for item in ledger.list_token_usage(task_run_id=task_run_id) if item.source == "provider_usage"]
    if str(getattr(task, "status", "") or "") not in TERMINAL_STATUSES and not stop_requested:
        stop_task_run(host, task_run_id, reason="live_prompt_cache_task_probe_timeout", requested_by="system")
        stop_requested = True
    return _wait_result(task, usage, samples, stop_requested=stop_requested, timeout=True, min_provider_calls=min_provider_calls)


async def _drain_background_tasks(host: Any, *, timeout_seconds: float) -> None:
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    while time.monotonic() < deadline:
        tasks = [
            task
            for task in list(getattr(host, "background_tasks", {}).values())
            if not task.done()
        ]
        if not tasks:
            return
        await asyncio.sleep(0.5)


def _wait_result(task: Any, usage: list[Any], samples: list[dict[str, Any]], *, stop_requested: bool, timeout: bool, min_provider_calls: int) -> dict[str, Any]:
    status = str(getattr(task, "status", "") or "")
    return {
        "finished": status == "completed" and len(usage) >= min_provider_calls,
        "terminal_reached": status in TERMINAL_STATUSES,
        "timeout": timeout,
        "stop_requested": stop_requested,
        "provider_usage_records": len(usage),
        "min_provider_calls": min_provider_calls,
        "provider_usage_sufficient": len(usage) >= min_provider_calls,
        "status": status,
        "terminal_reason": str(getattr(task, "terminal_reason", "") or ""),
        "samples": samples[-20:],
    }


def _event_task_run_id(event: dict[str, Any]) -> str:
    candidates = [
        dict(event.get("task_run") or {}).get("task_run_id"),
        dict(event.get("data") or {}).get("task_run_id"),
        dict(event.get("public_data") or {}).get("task_run_id"),
    ]
    runtime_event = dict(event.get("event") or {})
    payload = dict(runtime_event.get("payload") or {})
    refs = dict(runtime_event.get("refs") or {})
    candidates.extend(
        [
            payload.get("task_run_id"),
            refs.get("task_run_ref"),
            dict(payload.get("task_run") or {}).get("task_run_id"),
            dict(payload.get("lifecycle") or {}).get("task_run_id"),
        ]
    )
    for candidate in candidates:
        task_run_id = str(candidate or "").strip()
        if task_run_id.startswith("taskrun:"):
            return task_run_id
    return ""


def _is_start_stream_terminal(event: dict[str, Any]) -> bool:
    event_type = str(event.get("type") or "").strip()
    if event_type in {"turn_completed", "done", "error", "stopped"}:
        return True
    runtime_event = dict(event.get("event") or {})
    runtime_type = str(runtime_event.get("event_type") or "").strip()
    payload = dict(runtime_event.get("payload") or {})
    return runtime_type == "step_summary_recorded" and str(payload.get("step") or "").strip() == "task_executor_scheduled"


def _trace_event_counts(trace: dict[str, Any] | None) -> dict[str, int]:
    counts: dict[str, int] = {}
    for event in list(dict(trace or {}).get("events") or []):
        event_type = str(dict(event).get("event_type") or "")
        counts[event_type] = counts.get(event_type, 0) + 1
    return dict(sorted(counts.items()))


def _must_hit_cache_audit(
    *,
    provider_usage: list[dict[str, Any]],
    cache_records: list[dict[str, Any]],
    segment_maps: list[dict[str, Any]],
) -> dict[str, Any]:
    usage_by_request = {
        str(dict(row).get("request_id") or ""): dict(row)
        for row in list(provider_usage or [])
        if str(dict(row).get("request_id") or "")
    }
    cache_by_request = {
        str(dict(row).get("request_id") or ""): dict(row)
        for row in list(cache_records or [])
        if str(dict(row).get("request_id") or "")
    }
    segment_by_request = {
        str(_row_request_id(row) or ""): _as_dict(row)
        for row in list(segment_maps or [])
        if str(_row_request_id(row) or "")
    }
    ordered_request_ids: list[str] = []
    for row in list(provider_usage or []):
        request_id = str(dict(row).get("request_id") or "")
        if request_id and request_id in segment_by_request and request_id not in ordered_request_ids:
            ordered_request_ids.append(request_id)
    pairs: list[dict[str, Any]] = []
    total_must_hit_violation_count = 0
    total_must_hit_violation_tokens = 0
    total_order_violation_count = 0
    for index in range(1, len(ordered_request_ids)):
        previous_request_id = ordered_request_ids[index - 1]
        current_request_id = ordered_request_ids[index]
        pair = _audit_request_pair(
            previous_request_id=previous_request_id,
            current_request_id=current_request_id,
            previous_map=segment_by_request.get(previous_request_id) or {},
            current_map=segment_by_request.get(current_request_id) or {},
            current_cache=cache_by_request.get(current_request_id) or {},
            current_usage=usage_by_request.get(current_request_id) or {},
        )
        total_must_hit_violation_count += int(pair.get("must_hit_violation_count") or 0)
        total_must_hit_violation_tokens += int(pair.get("must_hit_violation_tokens") or 0)
        total_order_violation_count += int(pair.get("order_violation_count") or 0)
        pairs.append(pair)
    ok = bool(pairs) and total_must_hit_violation_count == 0 and total_order_violation_count == 0
    return {
        "ok": ok,
        "authority": "backend.scripts.live_prompt_cache_task_probe.must_hit_cache_audit",
        "rule": "static + append-only accumulated_context + dynamic_tail; unchanged cacheable prefix segments must remain byte/order stable and be covered by provider cache reads",
        "provider_call_count": len(ordered_request_ids),
        "compared_pair_count": len(pairs),
        "must_hit_violation_count": total_must_hit_violation_count,
        "must_hit_violation_tokens": total_must_hit_violation_tokens,
        "order_violation_count": total_order_violation_count,
        "pairs": pairs,
    }


def _audit_request_pair(
    *,
    previous_request_id: str,
    current_request_id: str,
    previous_map: dict[str, Any],
    current_map: dict[str, Any],
    current_cache: dict[str, Any],
    current_usage: dict[str, Any],
) -> dict[str, Any]:
    previous_segments = [_as_dict(item) for item in list(dict(previous_map).get("segments") or [])]
    current_segments = [_as_dict(item) for item in list(dict(current_map).get("segments") or [])]
    previous_by_ordinal = {_segment_ordinal(item): item for item in previous_segments if _segment_ordinal(item) >= 0}
    current_stable_by_identity: dict[tuple[str, str], list[int]] = {}
    for segment in current_segments:
        if not _is_cacheable_prefix_segment(segment):
            continue
        current_stable_by_identity.setdefault(_segment_identity(segment), []).append(_segment_ordinal(segment))
    coverage_by_ordinal = _coverage_by_ordinal(current_cache)
    must_hit_segments: list[dict[str, Any]] = []
    must_hit_violations: list[dict[str, Any]] = []
    allowed_new_stable_segments: list[dict[str, Any]] = []
    stable_slot_changes: list[dict[str, Any]] = []
    stable_reorders: list[dict[str, Any]] = []
    dynamic_tail_segments: list[dict[str, Any]] = []
    for segment in current_segments:
        ordinal = _segment_ordinal(segment)
        if not _is_cacheable_prefix_segment(segment):
            dynamic_tail_segments.append(_segment_projection(segment))
            continue
        previous_segment = previous_by_ordinal.get(ordinal)
        if previous_segment and _segment_identity(previous_segment) == _segment_identity(segment):
            covered = _coverage_is_hit(coverage_by_ordinal.get(ordinal) or {})
            projected = {
                **_segment_projection(segment),
                "covered_by_provider_cache": covered,
            }
            must_hit_segments.append(projected)
            if not covered:
                must_hit_violations.append(
                    {
                        **projected,
                        "violation": "unchanged_stable_segment_not_covered",
                    }
                )
            continue
        if previous_segment and _is_cacheable_prefix_segment(previous_segment):
            stable_slot_changes.append(
                {
                    "violation": "stable_ordinal_changed",
                    "ordinal": ordinal,
                    "previous": _segment_projection(previous_segment),
                    "current": _segment_projection(segment),
                }
            )
        allowed_new_stable_segments.append(_segment_projection(segment))
    for previous_segment in previous_segments:
        if not _is_cacheable_prefix_segment(previous_segment):
            continue
        previous_ordinal = _segment_ordinal(previous_segment)
        current_ordinals = current_stable_by_identity.get(_segment_identity(previous_segment), [])
        if current_ordinals and previous_ordinal not in current_ordinals:
            stable_reorders.append(
                {
                    "violation": "previous_stable_segment_reordered",
                    "previous_ordinal": previous_ordinal,
                    "current_ordinals": current_ordinals[:8],
                    "segment": _segment_projection(previous_segment),
                }
            )
    order_violations = [
        *_cacheable_after_dynamic_tail_violations(current_segments),
        *stable_slot_changes,
        *stable_reorders,
    ]
    diagnostics = dict(current_cache.get("diagnostics") or {})
    prompt_tokens = int(current_usage.get("prompt_tokens") or diagnostics.get("provider_prompt_tokens") or 0)
    cached_tokens = max(
        int(current_usage.get("cached_tokens") or 0),
        int(current_usage.get("cache_read_tokens") or 0),
        int(current_cache.get("cached_tokens") or 0),
        int(current_cache.get("cache_read_tokens") or 0),
        int(diagnostics.get("provider_cached_tokens") or 0),
    )
    return {
        "previous_request_id": previous_request_id,
        "current_request_id": current_request_id,
        "provider_prompt_tokens": prompt_tokens,
        "provider_cached_tokens": cached_tokens,
        "provider_cache_hit_rate": round(cached_tokens / prompt_tokens, 4) if prompt_tokens else 0.0,
        "provider_first_uncovered_stable_segment": dict(diagnostics.get("provider_cache_read_first_uncovered_stable_segment") or {}),
        "must_hit_segment_count": len(must_hit_segments),
        "must_hit_violation_count": len(must_hit_violations),
        "must_hit_violation_tokens": sum(int(item.get("predicted_tokens") or 0) for item in must_hit_violations),
        "allowed_new_stable_segment_count": len(allowed_new_stable_segments),
        "allowed_new_stable_tokens": sum(int(item.get("predicted_tokens") or 0) for item in allowed_new_stable_segments),
        "dynamic_tail_segment_count": len(dynamic_tail_segments),
        "dynamic_tail_tokens": sum(int(item.get("predicted_tokens") or 0) for item in dynamic_tail_segments),
        "order_violation_count": len(order_violations),
        "first_must_hit_violation": must_hit_violations[0] if must_hit_violations else {},
        "must_hit_violations": must_hit_violations[:40],
        "order_violations": order_violations[:40],
        "allowed_new_stable_segments": allowed_new_stable_segments[:40],
        "dynamic_tail_segments": dynamic_tail_segments[:40],
    }


def _cacheable_after_dynamic_tail_violations(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    first_dynamic: dict[str, Any] | None = None
    for segment in segments:
        if not _is_cacheable_prefix_segment(segment):
            first_dynamic = first_dynamic or segment
            continue
        if first_dynamic is not None:
            violations.append(
                {
                    "violation": "cacheable_segment_after_dynamic_tail_started",
                    "first_dynamic": _segment_projection(first_dynamic),
                    "current": _segment_projection(segment),
                }
            )
    return violations


def _coverage_by_ordinal(cache_record: dict[str, Any]) -> dict[int, dict[str, Any]]:
    diagnostics = dict(cache_record.get("diagnostics") or {})
    result: dict[int, dict[str, Any]] = {}
    for key in (
        "provider_cache_read_stable_segment_coverage",
        "provider_cache_read_required_segment_coverage",
    ):
        for item in list(diagnostics.get(key) or []):
            payload = _as_dict(item)
            ordinal = _segment_ordinal(payload)
            if ordinal >= 0:
                result[ordinal] = payload
    return result


def _coverage_is_hit(coverage: dict[str, Any]) -> bool:
    return any(
        bool(coverage.get(key))
        for key in (
            "covered_by_provider_scaled_boundary_estimate",
            "covered_by_provider_scaled_boundary",
            "covered_by_raw_predicted_boundary",
        )
    )


def _is_cacheable_prefix_segment(segment: dict[str, Any]) -> bool:
    cache_role = str(segment.get("cache_role") or "")
    prefix_tier = str(segment.get("prefix_tier") or "")
    return cache_role in {"cacheable_prefix", "session_stable"} and prefix_tier not in {"", "none", "volatile"}


def _segment_identity(segment: dict[str, Any]) -> tuple[str, str]:
    return (str(segment.get("kind") or ""), str(segment.get("content_hash") or ""))


def _segment_projection(segment: dict[str, Any]) -> dict[str, Any]:
    return {
        "ordinal": _segment_ordinal(segment),
        "kind": str(segment.get("kind") or ""),
        "predicted_tokens": int(segment.get("predicted_tokens") or 0),
        "cache_role": str(segment.get("cache_role") or ""),
        "prefix_tier": str(segment.get("prefix_tier") or ""),
        "source": str(segment.get("source") or ""),
        "content_hash": str(segment.get("content_hash") or ""),
    }


def _segment_ordinal(segment: dict[str, Any]) -> int:
    try:
        return int(dict(segment or {}).get("ordinal"))
    except (TypeError, ValueError):
        return -1


def _row_request_id(row: Any) -> str:
    payload = _as_dict(row)
    request_id = str(payload.get("request_id") or "")
    if request_id:
        return request_id
    metadata = dict(payload.get("metadata") or {})
    return str(metadata.get("model_request_ref") or "")


def _as_dict(value: Any) -> dict[str, Any]:
    if hasattr(value, "to_dict"):
        try:
            return dict(value.to_dict())
        except Exception:
            return {}
    if isinstance(value, dict):
        return dict(value)
    return {}


def _summary(report: dict[str, Any]) -> dict[str, Any]:
    summary = dict(report.get("summary") or {})
    wait = dict(report.get("wait_report") or {})
    packet = dict(report.get("packet_summary") or {})
    audit = dict(report.get("must_hit_cache_audit") or {})
    return {
        "measurement_ok": bool(report.get("measurement_ok")),
        "cache_contract_ok": bool(report.get("cache_contract_ok")),
        "task_run_id": str(report.get("task_run_id") or ""),
        "task_status": str(report.get("task_status") or ""),
        "terminal_reason": str(report.get("task_terminal_reason") or ""),
        "provider_usage_records": int(summary.get("provider_usage_record_count") or 0),
        "prompt_tokens": int(summary.get("prompt_tokens") or 0),
        "cached_tokens": int(summary.get("cached_tokens") or 0),
        "cache_hit_rate": float(summary.get("cache_hit_rate") or 0.0),
        "post_warm_cache_hit_rate": float(summary.get("post_warm_cache_hit_rate") or 0.0),
        "provider_global_prefix_all_equal": bool(packet.get("provider_global_prefix_all_equal")),
        "session_prefix_all_equal": bool(packet.get("session_prefix_all_equal")),
        "task_prefix_all_equal": bool(packet.get("task_prefix_all_equal")),
        "must_hit_violation_count": int(audit.get("must_hit_violation_count") or 0),
        "must_hit_violation_tokens": int(audit.get("must_hit_violation_tokens") or 0),
        "order_violation_count": int(audit.get("order_violation_count") or 0),
        "stop_requested": bool(wait.get("stop_requested")),
        "report_dir": str(report.get("report_dir") or ""),
    }


if __name__ == "__main__":
    raise SystemExit(main())
