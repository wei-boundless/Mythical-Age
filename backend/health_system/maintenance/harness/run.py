from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

from .contracts import (
    HarnessPartialResult,
    HarnessProgressEvent,
    HarnessRunContract,
    HarnessRunState,
    IssueEntry,
    RunContext,
    RunResult,
    ScenarioResult,
    TimingSnapshot,
    TraceSpan,
)
from .persistence import (
    append_harness_progress_event,
    render_and_persist_run_result,
    write_harness_artifact_manifest,
    write_harness_heartbeat,
    write_harness_partial_result,
    write_harness_run_contract,
    write_harness_run_state,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Unified test harness entrypoint.")
    parser.add_argument(
        "--profile",
        choices=(
            "smoke",
            "stable",
            "full",
            "deep",
            "benchmark",
            "regression",
            "chain",
            "functional",
            "system",
            "scenario",
            "long",
        ),
        required=True,
    )
    parser.add_argument("--output-dir", default="")
    return parser


def main() -> int:
    parser = _build_parser()
    args, extra_args = parser.parse_known_args()
    backend_dir = Path(__file__).resolve().parents[3]
    output_dir = _output_dir_from_args(extra_args, explicit=args.output_dir)

    if args.profile == "regression":
        target = backend_dir / "tests" / "run_regression_gate.py"
        cmd = [sys.executable, str(target), "--profile", "full"]
    elif args.profile in {"chain", "functional", "system", "scenario"}:
        target = backend_dir / "tests" / "run_regression_gate.py"
        cmd = [sys.executable, str(target), "--profile", args.profile]
    elif args.profile == "long":
        target = backend_dir / "tests" / "system_eval" / "long_runner.py"
        cmd = [sys.executable, str(target)]
    else:
        target = backend_dir / "tests" / "system_eval" / "runner.py"
        cmd = [sys.executable, str(target), "--profile", args.profile]

    passthrough_args = _without_wrapper_output_dir(list(extra_args or []))
    cmd.extend(passthrough_args)
    if _runner_accepts_output_dir(args.profile) and output_dir is not None:
        cmd.extend(["--output-dir", str(output_dir)])
    if args.profile in {"regression", "chain", "functional", "system", "scenario"} and output_dir is not None:
        cmd.extend(["--artifact-dir", str(output_dir / "artifacts" / "regression")])

    if output_dir is not None:
        _write_start_artifacts(
            profile=args.profile,
            command=cmd,
            output_dir=output_dir,
            backend_dir=backend_dir,
            scenario_refs=_scenario_refs_from_args(passthrough_args),
        )

    completed = subprocess.run(cmd, cwd=str(backend_dir), check=False)
    returncode = int(completed.returncode)
    if output_dir is not None:
        _write_finish_artifacts(
            profile=args.profile,
            command=cmd,
            output_dir=output_dir,
            returncode=returncode,
        )
    return returncode


def _output_dir_from_args(extra_args: list[str], *, explicit: str = "") -> Path | None:
    if str(explicit or "").strip():
        return Path(explicit)
    for index, arg in enumerate(extra_args):
        if arg == "--output-dir" and index + 1 < len(extra_args):
            return Path(extra_args[index + 1])
        if arg.startswith("--output-dir="):
            return Path(arg.split("=", 1)[1])
    return None


def _without_wrapper_output_dir(extra_args: list[str]) -> list[str]:
    cleaned: list[str] = []
    skip_next = False
    for arg in extra_args:
        if skip_next:
            skip_next = False
            continue
        if arg == "--output-dir":
            skip_next = True
            continue
        if arg.startswith("--output-dir="):
            continue
        cleaned.append(arg)
    return cleaned


def _runner_accepts_output_dir(profile: str) -> bool:
    return profile in {"smoke", "stable", "full", "deep", "benchmark", "long"}


def _scenario_refs_from_args(extra_args: list[str]) -> list[str]:
    refs: list[str] = []
    skip_next = False
    for index, arg in enumerate(extra_args):
        if skip_next:
            skip_next = False
            continue
        if arg in {"--scenario", "--scenario-set"} and index + 1 < len(extra_args):
            refs.append(str(extra_args[index + 1]))
            skip_next = True
        elif arg.startswith("--scenario=") or arg.startswith("--scenario-set="):
            refs.append(arg.split("=", 1)[1])
    return refs


def _event(*, output_dir: Path, run_id: str, event_type: str, status: str, message: str = "", metadata: dict[str, object] | None = None) -> HarnessProgressEvent:
    return HarnessProgressEvent(
        event_id=f"harness-progress:{run_id}:{event_type}:{uuid4().hex[:8]}",
        event_type=event_type,
        run_id=run_id,
        status=status,
        created_at=time.time(),
        message=message,
        metadata=dict(metadata or {}),
    )


def _write_start_artifacts(
    *,
    profile: str,
    command: list[str],
    output_dir: Path,
    backend_dir: Path,
    scenario_refs: list[str],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = output_dir.name
    now = time.time()
    process_token = f"harness:{run_id}:{uuid4().hex}"
    contract = HarnessRunContract(
        run_id=run_id,
        profile=profile,
        command=list(command),
        output_dir=str(output_dir),
        backend_root=str(backend_dir),
        scenario_refs=list(scenario_refs),
    )
    event = _event(output_dir=output_dir, run_id=run_id, event_type="started", status="running", message="Harness wrapper started.")
    state = HarnessRunState(
        run_id=run_id,
        profile=profile,
        status="running",
        pid=os.getpid(),
        process_token=process_token,
        command=list(command),
        output_dir=str(output_dir),
        started_at=now,
        updated_at=now,
        heartbeat_at=now,
        last_progress_at=event.created_at,
        last_progress_event_id=event.event_id,
        last_artifact_mtime=_latest_mtime(output_dir),
        summary={"total": 0, "passed": 0, "failed": 0, "first_failure": ""},
    )
    partial = HarnessPartialResult(
        run_id=run_id,
        profile=profile,
        status="running",
        summary=dict(state.summary),
        latest_progress_event_id=event.event_id,
        updated_at=now,
    )
    write_harness_run_contract(output_dir=output_dir, contract=contract)
    append_harness_progress_event(output_dir=output_dir, event=event)
    write_harness_run_state(output_dir=output_dir, state=state)
    write_harness_heartbeat(output_dir=output_dir, state=state)
    write_harness_partial_result(output_dir=output_dir, partial=partial)
    write_harness_artifact_manifest(output_dir=output_dir, run_id=run_id)


def _write_finish_artifacts(
    *,
    profile: str,
    command: list[str],
    output_dir: Path,
    returncode: int,
) -> None:
    run_id = output_dir.name
    now = time.time()
    if not (output_dir / "run_result.json").exists():
        _persist_fallback_run_result(
            profile=profile,
            command=command,
            output_dir=output_dir,
            returncode=returncode,
            finished_at=now,
        )
    summary = _summary_from_run_result(output_dir)
    status = "passed" if returncode == 0 and int(summary.get("failed") or 0) == 0 else "failed"
    event = _event(
        output_dir=output_dir,
        run_id=run_id,
        event_type="finished",
        status=status,
        message=f"Harness wrapper finished with returncode={returncode}.",
        metadata={"returncode": returncode},
    )
    append_harness_progress_event(output_dir=output_dir, event=event)
    state = HarnessRunState(
        run_id=run_id,
        profile=profile,
        status=status,
        pid=os.getpid(),
        process_token=f"harness:{run_id}",
        command=list(command),
        output_dir=str(output_dir),
        started_at=_started_at_from_existing_state(output_dir) or now,
        updated_at=now,
        ended_at=now,
        returncode=returncode,
        heartbeat_at=now,
        last_progress_at=event.created_at,
        last_progress_event_id=event.event_id,
        last_artifact_mtime=_latest_mtime(output_dir),
        summary=summary,
    )
    partial = HarnessPartialResult(
        run_id=run_id,
        profile=profile,
        status=status,
        summary=summary,
        completed_scenarios=int(summary.get("total") or 0),
        failed_scenarios=int(summary.get("failed") or 0),
        latest_artifact_ref=_latest_artifact_ref(output_dir),
        latest_progress_event_id=event.event_id,
        updated_at=now,
    )
    write_harness_run_state(output_dir=output_dir, state=state)
    write_harness_heartbeat(output_dir=output_dir, state=state)
    write_harness_partial_result(output_dir=output_dir, partial=partial)
    write_harness_artifact_manifest(output_dir=output_dir, run_id=run_id)


def _summary_from_run_result(output_dir: Path) -> dict[str, object]:
    run_result_path = output_dir / "run_result.json"
    if not run_result_path.exists():
        return {"total": 0, "passed": 0, "failed": 1, "first_failure": "run_result.json missing"}
    try:
        payload = json.loads(run_result_path.read_text(encoding="utf-8"))
    except Exception:
        return {"total": 0, "passed": 0, "failed": 1, "first_failure": "run_result.json invalid"}
    metadata = dict(payload.get("metadata") or {}) if isinstance(payload, dict) else {}
    results = list(payload.get("results") or []) if isinstance(payload, dict) else []
    total = int(metadata.get("total") or len(results) or 0)
    passed = int(metadata.get("passed") or sum(1 for item in results if isinstance(item, dict) and item.get("passed")) or 0)
    failed = int(metadata.get("failed") or max(total - passed, 0) or 0)
    first_failure = ""
    for item in results:
        if isinstance(item, dict) and not bool(item.get("passed", False)):
            first_failure = str(item.get("name") or item.get("summary") or "")
            break
    return {"total": total, "passed": passed, "failed": failed, "first_failure": first_failure}


def _started_at_from_existing_state(output_dir: Path) -> float:
    try:
        payload = json.loads((output_dir / "harness_state.json").read_text(encoding="utf-8"))
    except Exception:
        return 0.0
    return float(dict(payload or {}).get("started_at") or 0.0)


def _latest_mtime(output_dir: Path) -> float:
    latest = 0.0
    for path in output_dir.rglob("*") if output_dir.exists() else []:
        try:
            latest = max(latest, path.stat().st_mtime)
        except OSError:
            continue
    return latest


def _latest_artifact_ref(output_dir: Path) -> str:
    latest_path = None
    latest_mtime = 0.0
    for path in output_dir.rglob("*") if output_dir.exists() else []:
        if not path.is_file():
            continue
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if mtime >= latest_mtime:
            latest_path = path
            latest_mtime = mtime
    if latest_path is None:
        return ""
    try:
        return str(latest_path.resolve().relative_to(output_dir.resolve())).replace("\\", "/")
    except Exception:
        return str(latest_path)


def _persist_fallback_run_result(
    *,
    profile: str,
    command: list[str],
    output_dir: Path,
    returncode: int,
    finished_at: float,
) -> None:
    started_at = _started_at_from_existing_state(output_dir) or finished_at
    passed = returncode == 0
    started_text = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(started_at))
    ended_text = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(finished_at))
    log_tail = _read_tail(output_dir / "runner.log", limit=2000)
    summary = "底层 runner 未生成 run_result.json，harness wrapper 按子进程退出码记录最小结果。"
    if log_tail:
        summary = f"{summary} runner.log tail: {log_tail[-500:]}"
    context = RunContext(
        run_id=output_dir.name,
        profile=profile,
        mode="subprocess-wrapper",
        repo_root=str(Path(__file__).resolve().parents[4]),
        backend_root=str(Path(__file__).resolve().parents[3]),
        frontend_root=str(Path(__file__).resolve().parents[4] / "frontend"),
        output_dir=str(output_dir),
        generated_at=ended_text,
        python_version=platform.python_version(),
    )
    result = ScenarioResult(
        name="harness-subprocess",
        category=f"harness/{profile}",
        passed=passed,
        status="passed" if passed else "failed",
        summary=summary,
        timing=TimingSnapshot(
            started_at=started_text,
            ended_at=ended_text,
            duration_ms=round(max(finished_at - started_at, 0.0) * 1000.0, 2),
            terminal_event="process_exit",
        ),
        command=" ".join(command),
        details={"returncode": returncode, "fallback_result": True},
        artifact_paths=[str(output_dir / "runner.log")] if (output_dir / "runner.log").exists() else [],
    )
    run_result = RunResult(
        context=context,
        results=[result],
        issues=[],
        traces=[
            TraceSpan(
                trace_id=f"harness-{profile}",
                stage="harness-subprocess",
                status=result.status,
                started_at=started_text,
                ended_at=ended_text,
                latency_ms=result.timing.duration_ms,
                metadata={"returncode": returncode},
            )
        ],
        metadata={"total": 1, "passed": 1 if passed else 0, "failed": 0 if passed else 1},
    )
    if not passed:
        run_result.issues = [
            IssueEntry(
                id="ISSUE-001",
                title="harness subprocess did not produce run_result",
                severity="high",
                category=f"harness/{profile}",
                summary=summary,
                command=" ".join(command),
                artifact_paths=result.artifact_paths,
            )
        ]
    render_and_persist_run_result(output_dir=output_dir, run_result=run_result)


def _read_tail(path: Path, *, limit: int = 12000) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")[-limit:]
    except OSError:
        return ""


if __name__ == "__main__":
    raise SystemExit(main())
