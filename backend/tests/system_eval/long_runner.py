from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_DIR.parent
OUTPUT_ROOT = REPO_ROOT / "output" / "test_runs"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import app
from config import get_settings
from harness.contracts import IssueEntry, RunContext, RunResult, ScenarioResult, TimingSnapshot, TraceSpan
from harness.persistence import render_and_persist_run_result
from observability import current_trace_backend, is_langsmith_tracing_enabled, is_trace_capture_enabled
from runtime.app_runtime import app_runtime
from tests.system_eval.execution_core import collect_sse_events, extract_langsmith_trace_reference, final_text, iso_now
from tests.system_eval.long_scenarios import LongScenario, LongScenarioTurn, SCENARIO_SETS, scenario_map


@dataclass(slots=True)
class TurnResult:
    index: int
    session_alias: str
    session_id: str
    message: str
    plan_route: str
    plan_tool: str
    plan_skill: str
    subquery_count: int
    event_types: list[str]
    tool_names: list[str]
    response_text: str
    execution_mode: str = ""
    bundle_item_count: int = 0
    runtime_effective_route: str = ""
    followup_mode: str = ""
    followup_task_id: str = ""
    followup_task_ids: list[str] = field(default_factory=list)
    used_task_summary_refs: list[str] = field(default_factory=list)
    answer_channel: str = ""
    answer_source: str = ""
    answer_fallback_reason: str = ""
    answer_leak_flags: list[str] = field(default_factory=list)
    persisted_assistant_text: str = ""
    persisted_matches_done: bool = False
    active_pdf: str = ""
    active_dataset: str = ""
    session_model_preview: str = ""
    session_debug_preview: str = ""
    model_preview_has_active_rule: bool = False
    model_preview_has_next_step: bool = False
    trace_id: str = ""
    trace_url: str = ""
    trace_available: bool = False
    memory_sync_ms: float = 0.0
    tasks_count: int = 0
    passed: bool = True
    failed_checks: list[str] = field(default_factory=list)
    timing: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _slug(value: str) -> str:
    parts = []
    for char in value:
        if char.isalnum():
            parts.append(char.lower())
        else:
            parts.append("-")
    slug = "".join(parts).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "artifact"


def _parse_checks(turn: TurnResult, checks: tuple[str, ...]) -> list[str]:
    failures: list[str] = []
    for check in checks:
        if check.startswith("plan.route="):
            expected = check.split("=", 1)[1]
            if turn.plan_route != expected:
                failures.append(f"{check} (actual={turn.plan_route})")
            continue
        if check.startswith("plan.tool="):
            expected = check.split("=", 1)[1]
            if turn.plan_tool != expected:
                failures.append(f"{check} (actual={turn.plan_tool})")
            continue
        if check.startswith("plan.skill="):
            expected = check.split("=", 1)[1]
            if turn.plan_skill != expected:
                failures.append(f"{check} (actual={turn.plan_skill})")
            continue
        if check.startswith("plan.execution_mode="):
            expected = check.split("=", 1)[1]
            if turn.execution_mode != expected:
                failures.append(f"{check} (actual={turn.execution_mode})")
            continue
        if check.startswith("plan.bundle_items="):
            expected = int(check.split("=", 1)[1])
            if turn.bundle_item_count != expected:
                failures.append(f"{check} (actual={turn.bundle_item_count})")
            continue
        if check.startswith("plan.subqueries>="):
            expected = int(check.split(">=", 1)[1])
            if turn.subquery_count < expected:
                failures.append(f"{check} (actual={turn.subquery_count})")
            continue
        if check.startswith("plan.subqueries="):
            expected = int(check.split("=", 1)[1])
            if turn.subquery_count != expected:
                failures.append(f"{check} (actual={turn.subquery_count})")
            continue
        if check.startswith("event.tool="):
            expected = check.split("=", 1)[1]
            if expected not in turn.tool_names:
                failures.append(f"{check} (actual={turn.tool_names})")
            continue
        if check.startswith("event="):
            expected = check.split("=", 1)[1]
            if expected not in turn.event_types:
                failures.append(f"{check} (actual={turn.event_types})")
            continue
        if check == "response.nonempty":
            if not turn.response_text.strip():
                failures.append(check)
            continue
        if check.startswith("response.not_contains_any="):
            variants = [item.strip() for item in check.split("=", 1)[1].split("|") if item.strip()]
            if any(item in turn.response_text for item in variants):
                failures.append(f"{check} (actual={turn.response_text[:160]})")
            continue
        if check == "response.no_leak_flags":
            if turn.answer_leak_flags:
                failures.append(f"{check} (actual={turn.answer_leak_flags})")
            continue
        if check.startswith("response.contains_any="):
            variants = [item.strip() for item in check.split("=", 1)[1].split("|") if item.strip()]
            if not any(item in turn.response_text for item in variants):
                failures.append(f"{check} (actual={turn.response_text[:160]})")
            continue
        if check.startswith("response.contains="):
            expected = check.split("=", 1)[1]
            if expected not in turn.response_text:
                failures.append(f"{check} (actual={turn.response_text[:160]})")
            continue
        if check.startswith("followup.mode="):
            expected = check.split("=", 1)[1]
            if turn.followup_mode != expected:
                failures.append(f"{check} (actual={turn.followup_mode})")
            continue
        if check == "followup.task_id.nonempty":
            if not turn.followup_task_id.strip():
                failures.append(check)
            continue
        if check == "used_task_summary_refs.nonempty":
            if not turn.used_task_summary_refs:
                failures.append(check)
            continue
        if check == "main.active_pdf.nonempty":
            if not turn.active_pdf.strip():
                failures.append(check)
            continue
        if check == "main.active_dataset.nonempty":
            if not turn.active_dataset.strip():
                failures.append(check)
            continue
        if check.startswith("tasks>="):
            expected = int(check.split(">=", 1)[1])
            if turn.tasks_count < expected:
                failures.append(f"{check} (actual={turn.tasks_count})")
            continue
        if check == "trace.available":
            if not turn.trace_available:
                failures.append(check)
            continue
        failures.append(f"unsupported check: {check}")
    return failures


def _ensure_session(client: TestClient, session_ids: dict[str, str], alias: str, *, title: str = "") -> str:
    existing = session_ids.get(alias)
    if existing:
        return existing
    created = client.post("/api/sessions", json={"title": title or alias}).json()
    session_ids[alias] = str(created["id"])
    return session_ids[alias]


def _sync_memory(runtime, session_id: str, *, durable: bool = False) -> dict[str, Any]:
    session_summary = runtime.query_runtime.refresh_session_memory(session_id)
    durable_saved = 0
    if durable:
        durable_saved = runtime.query_runtime.commit_durable_memory_extraction(session_id)
    return {
        "session_summary_chars": len(str(session_summary or "").strip()),
        "durable_saved": durable_saved,
    }


def _resolve_positive_float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if not raw or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _resolve_nonnegative_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value >= 0 else default


def _cap_model_runtime_for_long_eval(runtime) -> tuple[float, int]:
    timeout_cap = _resolve_positive_float_env("SYSTEM_EVAL_LLM_TIMEOUT_SECONDS", 60.0)
    retry_cap = _resolve_nonnegative_int_env("SYSTEM_EVAL_LLM_MAX_RETRIES", 0)
    original = (
        float(runtime.model_runtime.request_timeout_seconds),
        int(runtime.model_runtime.max_retries),
    )
    runtime.model_runtime.request_timeout_seconds = min(original[0], timeout_cap)
    runtime.model_runtime.max_retries = min(original[1], retry_cap)
    return original


def _cleanup_session(runtime, session_id: str) -> bool:
    for _ in range(8):
        try:
            runtime.session_manager.delete_session(session_id)
            return True
        except PermissionError:
            time.sleep(0.5)
        except FileNotFoundError:
            return True
        except Exception:
            time.sleep(0.5)
    return False


def _execute_operator_turn(
    *,
    client: TestClient,
    runtime,
    turn: LongScenarioTurn,
    session_ids: dict[str, str],
) -> dict[str, Any]:
    action = str(turn.action or "").strip()
    params = dict(turn.params or {})
    if action == "ensure_session":
        session_id = _ensure_session(client, session_ids, turn.session, title=str(params.get("title", turn.session)))
        return {"action": action, "session_id": session_id, "ok": True}
    if action == "set_rag_mode":
        response = client.put("/api/config/rag-mode", json={"enabled": bool(params.get("enabled", False))})
        return {"action": action, "ok": response.status_code == 200, "payload": response.json()}
    if action == "set_permission_mode":
        response = client.put("/api/config/permission-mode", json={"mode": str(params.get("mode", "default"))})
        return {"action": action, "ok": response.status_code == 200, "payload": response.json()}
    if action == "check_files":
        normalized = [str(item).replace("\\", "/") for item in list(params.get("paths", []) or [])]
        missing = [path for path in normalized if not (BACKEND_DIR / path).exists()]
        return {"action": action, "ok": not missing, "paths": normalized, "missing": missing}
    if action == "sync_memory":
        session_id = _ensure_session(client, session_ids, turn.session)
        _sync_memory(runtime, session_id, durable=bool(params.get("durable", False)))
        return {"action": action, "ok": True, "session_id": session_id}
    raise ValueError(f"Unsupported operator action: {action}")


def _execute_user_turn(
    *,
    client: TestClient,
    runtime,
    scenario_dir: Path,
    turn_index: int,
    turn: LongScenarioTurn,
    session_ids: dict[str, str],
) -> TurnResult:
    session_id = _ensure_session(client, session_ids, turn.session, title=turn.session)
    history = runtime.session_manager.load_session_for_agent(
        session_id,
        include_compressed_context=False,
    )
    plan = runtime.query_runtime._planner_build_plan(
        session_id=session_id,
        message=turn.content,
        history=history,
        authority_context=runtime.query_runtime._load_session_authoritative_context(session_id),
    )

    request_started_at = iso_now()
    request_started = time.perf_counter()
    with client.stream(
        "POST",
        "/api/chat",
        json={"message": turn.content, "session_id": session_id, "stream": True},
    ) as response:
        events, timing = collect_sse_events(
            response,
            request_start=request_started,
            request_start_ts=request_started_at,
        )
    sync_details: dict[str, Any] | None = None
    memory_sync_ms = 0.0
    if turn.force_memory_sync:
        sync_started = time.perf_counter()
        sync_details = _sync_memory(runtime, session_id, durable=bool(turn.params.get("durable", False)))
        memory_sync_ms = round((time.perf_counter() - sync_started) * 1000.0, 2)

    trace_ref = extract_langsmith_trace_reference(events)
    response_text = final_text(events)
    memory_payload = next(
        (
            dict(item.get("data") or {}).get("memory", {})
            for item in reversed(events)
            if item.get("event") == "memory_context"
        ),
        {},
    )
    session_memory_payload = dict(memory_payload.get("session_memory") or {})
    model_preview = str(session_memory_payload.get("model_preview", "") or "")
    debug_preview = str(session_memory_payload.get("preview", "") or "")
    done_payload = next(
        (dict(item.get("data") or {}) for item in reversed(events) if item.get("event") == "done"),
        {},
    )
    stored_messages = runtime.session_manager.load_session(session_id)
    persisted_assistant_text = ""
    for stored in reversed(stored_messages):
        if str(stored.get("role", "") or "") == "assistant":
            persisted_assistant_text = str(stored.get("content", "") or "")
            break
    main_context = dict(done_payload.get("main_context") or {})
    task_summary_refs = list(done_payload.get("task_summary_refs") or [])
    active_work_item = str(main_context.get("active_work_item", "") or "")
    active_constraints = dict(main_context.get("active_constraints") or {})
    runtime_effective_route = ""
    if active_work_item.startswith("followup_task_"):
        runtime_effective_route = "followup_direct"
    elif any(item.get("event") == "tool_start" for item in events):
        runtime_effective_route = "tool"
    elif any(item.get("event") == "retrieval" for item in events):
        runtime_effective_route = "rag"
    tool_names = [
        str(dict(item.get("data") or {}).get("tool", "") or "")
        for item in events
        if item.get("event") == "tool_start"
    ]
    task_count = len(runtime.task_coordinator.list_tasks(session_id=session_id))

    turn_result = TurnResult(
        index=turn_index,
        session_alias=turn.session,
        session_id=session_id,
        message=turn.content,
        plan_route=plan.query_understanding.route,
        plan_tool=str(plan.query_understanding.tool_name or ""),
        plan_skill=str((plan.active_skill.name if plan.active_skill is not None else plan.query_understanding.skill_name) or ""),
        execution_mode=str(getattr(plan, "execution_mode", "") or ""),
        bundle_item_count=len(list(getattr(getattr(plan, "bundle_plan", None), "items", []) or [])),
        subquery_count=len(plan.subqueries),
        event_types=[str(item.get("event", "")) for item in events],
        tool_names=[name for name in tool_names if name],
        response_text=response_text,
        runtime_effective_route=runtime_effective_route or plan.query_understanding.route,
        followup_mode=str(done_payload.get("followup_mode", "") or ("direct_task_handle" if active_work_item.startswith("followup_task_") else "")),
        followup_task_id=str(main_context.get("followup_target_task_id", "") or ""),
        followup_task_ids=[
            str(task_id)
            for task_id in list(main_context.get("followup_target_task_ids", []) or [])
            if str(task_id).strip()
        ],
        used_task_summary_refs=[
            str(dict(item or {}).get("task_id", "") or "")
            for item in task_summary_refs
            if str(dict(item or {}).get("task_id", "") or "").strip()
        ],
        answer_channel=str(done_payload.get("answer_channel", "") or ""),
        answer_source=str(done_payload.get("answer_source", "") or ""),
        answer_fallback_reason=str(done_payload.get("answer_fallback_reason", "") or ""),
        answer_leak_flags=[str(item) for item in list(done_payload.get("answer_leak_flags", []) or []) if str(item).strip()],
        persisted_assistant_text=persisted_assistant_text[:400],
        persisted_matches_done=(persisted_assistant_text.strip() == response_text.strip()),
        active_pdf=str(active_constraints.get("active_pdf", "") or ""),
        active_dataset=str(active_constraints.get("active_dataset", "") or ""),
        session_model_preview=model_preview[:300],
        session_debug_preview=debug_preview[:300],
        model_preview_has_active_rule=("当前规则：" in model_preview or "active_rule" in model_preview),
        model_preview_has_next_step=("# Next Step" in model_preview or "当前下一步：" in model_preview),
        trace_id=str(trace_ref["trace_id"]),
        trace_url=str(trace_ref["trace_url"]),
        trace_available=bool(trace_ref["trace_available"]),
        memory_sync_ms=memory_sync_ms,
        tasks_count=task_count,
        timing=timing.to_dict(),
    )
    turn_result.failed_checks = _parse_checks(turn_result, turn.checks)
    turn_result.passed = not turn_result.failed_checks and "error" not in turn_result.event_types

    artifact_path = scenario_dir / f"turn-{turn_index:02d}-{_slug(turn.session)}.json"
    artifact_path.write_text(
        json.dumps(
            {
                "turn": {
                    "session": turn.session,
                    "speaker": turn.speaker,
                    "content": turn.content,
                    "checks": list(turn.checks),
                },
                "plan": {
                "route": turn_result.plan_route,
                "tool": turn_result.plan_tool,
                "skill": turn_result.plan_skill,
                "execution_mode": turn_result.execution_mode,
                "bundle_item_count": turn_result.bundle_item_count,
                "subqueries": list(plan.subqueries),
            },
                "events": events,
                "memory_sync": sync_details or {},
                "result": turn_result.to_dict(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return turn_result


def _execute_scenario(
    *,
    client: TestClient,
    runtime,
    scenario: LongScenario,
    output_dir: Path,
) -> ScenarioResult:
    started_at = iso_now()
    started = time.perf_counter()
    scenario_dir = output_dir / "artifacts" / _slug(scenario.id)
    scenario_dir.mkdir(parents=True, exist_ok=True)

    session_ids: dict[str, str] = {}
    operator_results: list[dict[str, Any]] = []
    turn_results: list[TurnResult] = []
    cleanup: dict[str, bool] = {}
    artifact_paths: list[str] = []

    try:
        for index, turn in enumerate(scenario.turns, start=1):
            if turn.speaker == "operator":
                result = _execute_operator_turn(
                    client=client,
                    runtime=runtime,
                    turn=turn,
                    session_ids=session_ids,
                )
                operator_results.append({"index": index, "session": turn.session, **result})
                continue

            turn_result = _execute_user_turn(
                client=client,
                runtime=runtime,
                scenario_dir=scenario_dir,
                turn_index=index,
                turn=turn,
                session_ids=session_ids,
            )
            turn_results.append(turn_result)
            artifact_paths.append(str(scenario_dir / f"turn-{index:02d}-{_slug(turn.session)}.json"))
    finally:
        time.sleep(1.0)
        for alias, session_id in session_ids.items():
            cleanup[alias] = _cleanup_session(runtime, session_id)

    failed_turns = [turn for turn in turn_results if not turn.passed]
    duration_ms = round((time.perf_counter() - started) * 1000.0, 2)
    request_ms = round(sum(float(turn.timing.get("duration_ms", 0.0) or 0.0) for turn in turn_results), 2)
    memory_sync_ms = round(sum(float(turn.memory_sync_ms or 0.0) for turn in turn_results), 2)
    summary = f"{len(turn_results) - len(failed_turns)}/{len(turn_results)} user turns passed"
    if failed_turns:
        summary += f"; first failure turn={failed_turns[0].index}"

    details = {
        "goal": scenario.goal,
        "coverage": list(scenario.coverage),
        "operator_results": operator_results,
        "turn_results": [turn.to_dict() for turn in turn_results],
        "cleanup": cleanup,
        "trace_id": failed_turns[0].trace_id if failed_turns else "",
        "trace_url": failed_turns[0].trace_url if failed_turns else "",
        "trace_available": any(turn.trace_available for turn in turn_results),
        "scenario_contract_version": "2026-04-long-scenario-v1",
        "timing_breakdown": {
            "scenario_duration_ms": duration_ms,
            "turn_request_ms": request_ms,
            "memory_sync_ms": memory_sync_ms,
            "other_overhead_ms": round(max(duration_ms - request_ms - memory_sync_ms, 0.0), 2),
        },
    }
    return ScenarioResult(
        name=scenario.title,
        category="long_scenario",
        passed=not failed_turns,
        status="passed" if not failed_turns else "failed",
        summary=summary,
        timing=TimingSnapshot(
            started_at=started_at,
            ended_at=iso_now(),
            duration_ms=duration_ms,
            event_count=sum(len(turn.event_types) for turn in turn_results),
            terminal_event="scenario_complete" if not failed_turns else "scenario_failed",
        ),
        command=f"long_scenario::{scenario.id}",
        details=details,
        artifact_paths=artifact_paths,
    )


def _build_context(output_dir: Path) -> RunContext:
    settings = get_settings()
    return RunContext(
        run_id=output_dir.name,
        profile="long",
        mode="inprocess",
        repo_root=str(REPO_ROOT),
        backend_root=str(BACKEND_DIR),
        frontend_root=str(REPO_ROOT / "frontend"),
        output_dir=str(output_dir),
        generated_at=iso_now(),
        python_version=platform.python_version(),
        llm_provider=settings.llm_provider,
        llm_model=settings.llm_model,
        langsmith_enabled=is_langsmith_tracing_enabled(),
        trace_backend=current_trace_backend(),
        trace_enabled=is_trace_capture_enabled(),
    )


def _issue_from_result(index: int, result: ScenarioResult) -> IssueEntry | None:
    if result.passed:
        return None
    return IssueEntry(
        id=f"LONG-{index:03d}",
        title=result.name,
        severity="high",
        category=result.category,
        summary=result.summary,
        command=result.command,
        artifact_paths=list(result.artifact_paths),
        trace_id=str(result.details.get("trace_id", "") or ""),
        trace_url=str(result.details.get("trace_url", "") or ""),
    )


def _trace_from_result(result: ScenarioResult) -> TraceSpan:
    return TraceSpan(
        trace_id=f"long-{_slug(result.name)}",
        stage="long_scenario",
        status=result.status,
        started_at=result.timing.started_at,
        ended_at=result.timing.ended_at,
        latency_ms=result.timing.duration_ms,
        metadata={"name": result.name, "summary": result.summary},
    )


def _resolve_scenarios(args) -> list[LongScenario]:
    scenarios = scenario_map()
    selected_ids: list[str] = []
    if args.scenario_set:
        selected_ids.extend(list(SCENARIO_SETS[args.scenario_set]))
    if args.scenario:
        selected_ids.extend(list(args.scenario))
    if not selected_ids:
        selected_ids.extend(list(SCENARIO_SETS["core"]))

    deduped: list[LongScenario] = []
    seen: set[str] = set()
    for scenario_id in selected_ids:
        if scenario_id in seen:
            continue
        seen.add(scenario_id)
        if scenario_id not in scenarios:
            raise ValueError(f"Unknown long scenario: {scenario_id}")
        deduped.append(scenarios[scenario_id])
    return deduped


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run executable long conversation scenarios.")
    parser.add_argument("--scenario-set", choices=tuple(SCENARIO_SETS), default=None)
    parser.add_argument("--scenario", action="append", default=[])
    parser.add_argument("--output-dir", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    run_id = f"{time.strftime('%Y%m%d-%H%M%S')}-long"
    output_dir = Path(args.output_dir) if str(args.output_dir).strip() else OUTPUT_ROOT / run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    run_result = RunResult(context=_build_context(output_dir))
    selected = _resolve_scenarios(args)

    with TestClient(app) as client:
        runtime = app_runtime.require_ready()
        original_post_turn = runtime.query_runtime._run_post_turn_tasks
        original_timeout, original_retries = _cap_model_runtime_for_long_eval(runtime)

        async def _noop_post_turn(_session_id: str, *, title_seed: str | None = None) -> None:
            return None

        runtime.query_runtime._run_post_turn_tasks = _noop_post_turn  # type: ignore[method-assign]
        try:
            for scenario in selected:
                run_result.results.append(
                    _execute_scenario(
                        client=client,
                        runtime=runtime,
                        scenario=scenario,
                        output_dir=output_dir,
                    )
                )
        finally:
            runtime.query_runtime._run_post_turn_tasks = original_post_turn  # type: ignore[method-assign]
            runtime.model_runtime.request_timeout_seconds = original_timeout
            runtime.model_runtime.max_retries = original_retries

    run_result.issues = [
        issue
        for index, issue in enumerate((_issue_from_result(i + 1, result) for i, result in enumerate(run_result.results)), start=1)
        if issue is not None
    ]
    run_result.traces = [_trace_from_result(result) for result in run_result.results]
    run_result.metadata = {
        "scenario_ids": [scenario.id for scenario in selected],
        "total": len(run_result.results),
        "passed": sum(1 for result in run_result.results if result.passed),
        "failed": sum(1 for result in run_result.results if not result.passed),
        "llm_timeout_seconds": min(original_timeout, _resolve_positive_float_env("SYSTEM_EVAL_LLM_TIMEOUT_SECONDS", 60.0)),
        "llm_max_retries": min(original_retries, _resolve_nonnegative_int_env("SYSTEM_EVAL_LLM_MAX_RETRIES", 0)),
    }

    render_and_persist_run_result(output_dir=output_dir, run_result=run_result)

    print(
        f"[long-runner] total={run_result.metadata['total']} "
        f"passed={run_result.metadata['passed']} failed={run_result.metadata['failed']}"
    )
    print(f"[long-runner] output={output_dir}")
    return 0 if int(run_result.metadata["failed"]) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
