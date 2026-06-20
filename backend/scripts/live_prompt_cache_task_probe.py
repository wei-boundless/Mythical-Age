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
    return 0 if report.get("measurement_ok") else 2


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

    report = {
        "measurement_ok": bool(provider_usage) and bool(segment_maps),
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


def _summary(report: dict[str, Any]) -> dict[str, Any]:
    summary = dict(report.get("summary") or {})
    wait = dict(report.get("wait_report") or {})
    packet = dict(report.get("packet_summary") or {})
    return {
        "measurement_ok": bool(report.get("measurement_ok")),
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
        "stop_requested": bool(wait.get("stop_requested")),
        "report_dir": str(report.get("report_dir") or ""),
    }


if __name__ == "__main__":
    raise SystemExit(main())
