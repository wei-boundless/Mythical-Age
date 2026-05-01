from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_DIR.parent
FRONTEND_DIR = REPO_ROOT / "frontend"
OUTPUT_ROOT = REPO_ROOT / "output" / "test_runs"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import app
from config import get_settings
from harness.contracts import IssueEntry, RunContext, RunResult, ScenarioResult, TimingSnapshot, TraceSpan
from harness.persistence import render_and_persist_run_result
from harness.regression_gate import run_profile
from observability import current_trace_backend, is_langsmith_tracing_enabled, is_trace_capture_enabled
from runtime.app_runtime import app_runtime

from execution_core import collect_sse_events, extract_langsmith_trace_reference, final_text, has_event, iso_now


async def _fake_invoke_messages(_messages: list[dict[str, str]]):
    return SimpleNamespace(content="smoke token")


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


def _tail(text: str, *, limit: int = 800) -> str:
    normalized = str(text or "").strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[-limit:]


def _latest_event_payload(events: list[dict[str, Any]], event_name: str) -> dict[str, Any]:
    for item in reversed(events):
        if str(item.get("event") or "") != event_name:
            continue
        data = item.get("data")
        return dict(data) if isinstance(data, dict) else {}
    return {}


def _orchestration_diff_mismatches(diff: dict[str, Any]) -> list[str]:
    mismatches: list[str] = []
    for item in list(diff.get("items") or []):
        if not isinstance(item, dict) or str(item.get("status") or "") != "mismatch":
            continue
        field = str(item.get("field") or "unknown")
        expected = item.get("expected")
        actual = item.get("actual")
        reason = str(item.get("reason") or "")
        suffix = f" / {reason}" if reason else ""
        mismatches.append(f"{field}: expected={expected!r}, actual={actual!r}{suffix}")
    return mismatches


def _build_context(profile: str, output_dir: Path) -> RunContext:
    settings = get_settings()
    return RunContext(
        run_id=output_dir.name,
        profile=profile,
        mode="inprocess",
        repo_root=str(REPO_ROOT),
        backend_root=str(BACKEND_DIR),
        frontend_root=str(FRONTEND_DIR),
        output_dir=str(output_dir),
        generated_at=iso_now(),
        python_version=platform.python_version(),
        llm_provider=settings.llm_provider,
        llm_model=settings.llm_model,
        langsmith_enabled=is_langsmith_tracing_enabled(),
        trace_backend=current_trace_backend(),
        trace_enabled=is_trace_capture_enabled(),
    )


def _result_to_issue(index: int, result: ScenarioResult) -> IssueEntry | None:
    if result.passed:
        return None
    summary = result.summary
    if str(result.details.get("orchestration_diff_status") or "") == "mismatch":
        mismatches = [str(item) for item in list(result.details.get("orchestration_diff_mismatches") or [])]
        summary += "; 编排计划偏移 " + ("; ".join(mismatches[:3]) or str(result.details.get("orchestration_diff_summary") or ""))
    return IssueEntry(
        id=f"ISSUE-{index:03d}",
        title=result.name,
        severity="high",
        category=result.category,
        summary=summary,
        command=result.command,
        artifact_paths=list(result.artifact_paths),
        trace_id=str(result.details.get("trace_id", "") or ""),
        trace_url=str(result.details.get("trace_url", "") or ""),
    )


def _trace_for_result(result: ScenarioResult) -> TraceSpan:
    return TraceSpan(
        trace_id=f"{_slug(result.category)}-{_slug(result.name)}",
        stage=result.category,
        status=result.status,
        started_at=result.timing.started_at,
        ended_at=result.timing.ended_at,
        latency_ms=result.timing.duration_ms,
        metadata={
            "name": result.name,
            "command": result.command,
            "trace_url": result.details.get("trace_url", ""),
        },
    )


def _run_command(
    *,
    name: str,
    category: str,
    command: list[str],
    cwd: Path,
    artifact_dir: Path,
) -> ScenarioResult:
    started_at = iso_now()
    started = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    duration_ms = round((time.perf_counter() - started) * 1000.0, 2)
    ended_at = iso_now()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    log_path = artifact_dir / f"{_slug(name)}.log"
    log_path.write_text(
        "\n".join(
            [
                f"$ {' '.join(command)}",
                "",
                "[stdout]",
                completed.stdout,
                "",
                "[stderr]",
                completed.stderr,
            ]
        ),
        encoding="utf-8",
    )
    summary = _tail(completed.stderr or completed.stdout or ("ok" if completed.returncode == 0 else "failed"))
    return ScenarioResult(
        name=name,
        category=category,
        passed=completed.returncode == 0,
        status="passed" if completed.returncode == 0 else "failed",
        summary=summary,
        command=" ".join(command),
        timing=TimingSnapshot(
            started_at=started_at,
            ended_at=ended_at,
            duration_ms=duration_ms,
            terminal_event="process_exit",
        ),
        details={
            "returncode": completed.returncode,
            "stdout_tail": _tail(completed.stdout),
            "stderr_tail": _tail(completed.stderr),
        },
        artifact_paths=[str(log_path)],
    )


def _npm_executable() -> str:
    return "npm.cmd" if os.name == "nt" else "npm"


def _run_frontend_events_test(artifact_dir: Path) -> ScenarioResult:
    return _run_command(
        name="frontend-events-reducer",
        category="frontend",
        command=[_npm_executable(), "run", "test", "--", "src/lib/store/events.test.ts"],
        cwd=FRONTEND_DIR,
        artifact_dir=artifact_dir,
    )


def _run_frontend_build(artifact_dir: Path) -> ScenarioResult:
    return _run_command(
        name="frontend-build",
        category="frontend",
        command=[_npm_executable(), "run", "build"],
        cwd=FRONTEND_DIR,
        artifact_dir=artifact_dir,
    )


def _run_experiment(name: str, relative_path: str, artifact_dir: Path) -> ScenarioResult:
    return _run_command(
        name=name,
        category="experiments",
        command=[sys.executable, str(BACKEND_DIR / relative_path)],
        cwd=BACKEND_DIR,
        artifact_dir=artifact_dir,
    )


def _run_inprocess_sse_smoke(artifact_dir: Path) -> ScenarioResult:
    started_at = iso_now()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    runtime = None
    created_session_id = ""

    async def _noop_post_turn(_session_id: str, *, title_seed: str | None = None) -> None:
        return None

    with TestClient(app) as client:
        runtime = app_runtime.require_ready()
        original_invoke_messages = runtime.model_runtime.invoke_messages
        original_post_turn = runtime.query_runtime._run_post_turn_tasks

        runtime.model_runtime.invoke_messages = _fake_invoke_messages  # type: ignore[method-assign]
        runtime.query_runtime._run_post_turn_tasks = _noop_post_turn  # type: ignore[method-assign]
        try:
            created = client.post("/api/sessions", json={"title": "System Eval Smoke"})
            created.raise_for_status()
            created_session_id = created.json()["id"]

            request_started_at = iso_now()
            request_started = time.perf_counter()
            with client.stream(
                "POST",
                "/api/chat",
                json={"message": "hello smoke", "session_id": created_session_id, "stream": True},
            ) as response:
                events, timing = collect_sse_events(
                    response,
                    request_start=request_started,
                    request_start_ts=request_started_at,
                )
        finally:
            runtime.model_runtime.invoke_messages = original_invoke_messages  # type: ignore[method-assign]
            runtime.query_runtime._run_post_turn_tasks = original_post_turn  # type: ignore[method-assign]
            if created_session_id:
                client.delete(f"/api/sessions/{created_session_id}")

    event_path = artifact_dir / "inprocess-sse-smoke.events.json"
    event_path.write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")

    trace_ref = extract_langsmith_trace_reference(events)
    orchestration_plan = dict(_latest_event_payload(events, "orchestration_plan").get("plan") or {})
    orchestration_diff = dict(_latest_event_payload(events, "orchestration_diff").get("diff") or {})
    orchestration_diff_status = str(orchestration_diff.get("status") or "")
    orchestration_mismatches = _orchestration_diff_mismatches(orchestration_diff)
    orchestration_path = artifact_dir / "inprocess-sse-smoke.orchestration.json"
    orchestration_path.write_text(
        json.dumps(
            {
                "orchestration_plan": orchestration_plan,
                "orchestration_diff": orchestration_diff,
                "mismatches": orchestration_mismatches,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    passed = (
        (has_event(events, "token") or has_event(events, "answer_candidate"))
        and has_event(events, "done")
        and not has_event(events, "error")
        and orchestration_diff_status != "mismatch"
    )
    summary = final_text(events) or "missing final answer"
    if orchestration_diff_status == "mismatch":
        summary = "编排计划偏移：" + ("; ".join(orchestration_mismatches[:3]) or str(orchestration_diff.get("summary") or ""))
    result = ScenarioResult(
        name="inprocess-sse-smoke",
        category="system_eval",
        passed=passed,
        status="passed" if passed else "failed",
        summary=summary,
        command="inprocess::POST /api/chat",
        timing=timing,
        details={
            "event_types": [item["event"] for item in events],
            "response_text": summary,
            "orchestration_plan_id": str(orchestration_plan.get("plan_id") or orchestration_diff.get("plan_id") or ""),
            "orchestration_diff_status": orchestration_diff_status,
            "orchestration_diff_summary": str(orchestration_diff.get("summary") or ""),
            "orchestration_diff_mismatches": orchestration_mismatches,
            **trace_ref,
        },
        artifact_paths=[str(event_path), str(orchestration_path)],
    )
    return result


def _results_from_regression_profile(profile: str, artifact_dir: Path) -> list[ScenarioResult]:
    outcomes = run_profile(profile, artifact_dir=artifact_dir)
    results: list[ScenarioResult] = []
    for outcome in outcomes:
        summary = outcome.stderr_tail or outcome.stdout_tail or ("ok" if outcome.passed else "failed")
        results.append(
            ScenarioResult(
                name=outcome.name,
                category=f"regression/{outcome.group}",
                passed=outcome.passed,
                status="passed" if outcome.passed else "failed",
                summary=summary,
                command=" ".join(outcome.command),
                timing=TimingSnapshot(
                    started_at=outcome.started_at,
                    ended_at=outcome.ended_at,
                    duration_ms=outcome.duration_ms,
                    terminal_event="process_exit",
                ),
                details={
                    "runner": outcome.runner,
                    "path": outcome.path,
                    "returncode": outcome.returncode,
                    "stdout_tail": outcome.stdout_tail,
                    "stderr_tail": outcome.stderr_tail,
                },
                artifact_paths=[outcome.artifact_path] if outcome.artifact_path else [],
            )
        )
    return results


def _collect_profile_results(profile: str, artifact_root: Path) -> list[ScenarioResult]:
    results: list[ScenarioResult] = []
    if profile == "smoke":
        results.append(_run_inprocess_sse_smoke(artifact_root / "artifacts"))
        results.append(_run_frontend_events_test(artifact_root / "artifacts"))
        return results

    if profile == "stable":
        results.extend(_collect_profile_results("smoke", artifact_root))
        results.extend(_results_from_regression_profile("core", artifact_root / "artifacts" / "core"))
        results.append(_run_frontend_build(artifact_root / "artifacts"))
        return results

    if profile in {"full", "benchmark"}:
        results.extend(_collect_profile_results("stable", artifact_root))
        results.extend(_results_from_regression_profile("full", artifact_root / "artifacts" / "full"))
        results.append(_run_frontend_build(artifact_root / "artifacts"))
        return results

    if profile == "deep":
        results.extend(_collect_profile_results("full", artifact_root))
        results.append(
            _run_experiment(
                "context-memory-experiment",
                "tests/context_memory_experiment.py",
                artifact_root / "artifacts",
            )
        )
        results.append(
            _run_experiment(
                "memory-rag-stability-experiment",
                "tests/memory_rag_stability_experiment.py",
                artifact_root / "artifacts",
            )
        )
        return results

    raise ValueError(f"Unsupported profile: {profile}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="System eval runner.")
    parser.add_argument(
        "--profile",
        choices=("smoke", "stable", "full", "deep", "benchmark"),
        required=True,
    )
    parser.add_argument("--output-dir", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    run_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{args.profile}"
    output_dir = Path(args.output_dir) if str(args.output_dir).strip() else OUTPUT_ROOT / run_id
    context = _build_context(args.profile, output_dir)

    run_result = RunResult(context=context)
    run_result.results = _collect_profile_results(args.profile, output_dir)
    run_result.issues = [
        issue
        for index, issue in enumerate((_result_to_issue(idx + 1, result) for idx, result in enumerate(run_result.results)), start=1)
        if issue is not None
    ]
    run_result.traces = [_trace_for_result(result) for result in run_result.results]
    run_result.metadata = {
        "total": len(run_result.results),
        "passed": sum(1 for result in run_result.results if result.passed),
        "failed": sum(1 for result in run_result.results if not result.passed),
    }

    render_and_persist_run_result(output_dir=output_dir, run_result=run_result)

    print(
        f"[system-eval] profile={args.profile} total={run_result.metadata['total']} "
        f"passed={run_result.metadata['passed']} failed={run_result.metadata['failed']}"
    )
    print(f"[system-eval] output={output_dir}")
    return 0 if int(run_result.metadata["failed"]) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
