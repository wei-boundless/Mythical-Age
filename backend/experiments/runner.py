from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from experiments.artifacts import load_run_artifacts, read_json_file, read_text_tail, summarize_run_result
from experiments.catalog import get_profile, list_profiles
from experiments.memory_trace import get_turn_memory_trace
from experiments.orchestration_trace import build_turn_orchestration_snapshot
from experiments.prompt_manifest import get_turn_prompt_manifest
from experiments.task_operation_preview_trace import build_task_operation_preview_snapshots
from experiments.trace_graph import build_run_overlay, build_turn_overlay, list_turns


REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"
OUTPUT_ROOT = REPO_ROOT / "output" / "test_runs"


@dataclass(slots=True)
class ExperimentRun:
    run_id: str
    profile: str
    status: str
    command: list[str]
    output_dir: str
    log_path: str
    started_at: float
    ended_at: float = 0.0
    returncode: int | None = None
    pid: int | None = None
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["duration_ms"] = self.duration_ms()
        payload["command_preview"] = " ".join(self.command)
        return payload

    def duration_ms(self) -> float:
        end = self.ended_at or time.time()
        return round(max(end - self.started_at, 0.0) * 1000.0, 2)


class ExperimentRunner:
    def __init__(self) -> None:
        self._processes: dict[str, subprocess.Popen[str]] = {}

    def profiles(self) -> list[dict[str, object]]:
        return [profile.to_dict() for profile in list_profiles()]

    def start(self, profile_id: str) -> dict[str, Any]:
        profile = get_profile(profile_id)
        if profile is None:
            raise ValueError(f"Unsupported experiment profile: {profile_id}")
        self._refresh_active_processes()
        if any(run.get("status") == "running" for run in self.list_runs(limit=50)):
            raise RuntimeError("已有实验正在运行，请等待结束或先取消。")

        run_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{profile.id}"
        output_dir = OUTPUT_ROOT / run_id
        output_dir.mkdir(parents=True, exist_ok=True)
        log_path = output_dir / "runner.log"
        command = [
            sys.executable,
            "-m",
            "harness.run",
            "--profile",
            profile.harness_profile or profile.id,
            *list(profile.extra_args),
            "--output-dir",
            str(output_dir),
        ]
        log_file = log_path.open("w", encoding="utf-8", errors="replace")
        process = subprocess.Popen(
            command,
            cwd=str(BACKEND_DIR),
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
        )
        log_file.close()
        run = ExperimentRun(
            run_id=run_id,
            profile=profile.id,
            status="running",
            command=command,
            output_dir=str(output_dir),
            log_path=str(log_path),
            started_at=time.time(),
            pid=process.pid,
            summary={"total": 0, "passed": 0, "failed": 0, "first_failure": ""},
        )
        self._processes[run_id] = process
        self._write_state(run)
        return self.get_run(run_id)

    def list_runs(self, *, limit: int = 20) -> list[dict[str, Any]]:
        OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
        runs: list[dict[str, Any]] = []
        for path in sorted((item for item in OUTPUT_ROOT.iterdir() if item.is_dir()), key=lambda item: item.name, reverse=True):
            state = self._load_state(path)
            if state is None:
                state = self._state_from_artifacts(path)
            runs.append(state)
            if len(runs) >= limit:
                break
        return runs

    def get_run(self, run_id: str) -> dict[str, Any]:
        output_dir = self._safe_output_dir(run_id)
        state = self._load_state(output_dir) or self._state_from_artifacts(output_dir)
        state = self._refresh_run_state(state)
        state["duration_ms"] = self._duration_ms_from_state(state)
        state["log_tail"] = read_text_tail(Path(str(state.get("log_path") or "")), limit=12000)
        return state

    def get_artifacts(self, run_id: str) -> dict[str, Any]:
        output_dir = self._safe_output_dir(run_id)
        return load_run_artifacts(output_dir)

    def get_turns(self, run_id: str) -> list[dict[str, Any]]:
        output_dir = self._safe_output_dir(run_id)
        return list_turns(output_dir)

    def get_graph_overlay(self, run_id: str) -> dict[str, Any]:
        output_dir = self._safe_output_dir(run_id)
        return build_run_overlay(output_dir)

    def get_turn_graph_overlay(self, run_id: str, turn_id: str) -> dict[str, Any]:
        output_dir = self._safe_output_dir(run_id)
        return build_turn_overlay(output_dir, turn_id)

    def get_turn_prompt_manifest(self, run_id: str, turn_id: str) -> dict[str, Any]:
        output_dir = self._safe_output_dir(run_id)
        return get_turn_prompt_manifest(output_dir, turn_id)

    def get_turn_memory_trace(self, run_id: str, turn_id: str) -> dict[str, Any]:
        output_dir = self._safe_output_dir(run_id)
        return get_turn_memory_trace(output_dir, turn_id)

    def get_turn_orchestration_snapshot(self, run_id: str, turn_id: str, *, artifact_path: str = "") -> dict[str, Any]:
        output_dir = self._safe_output_dir(run_id)
        return build_turn_orchestration_snapshot(output_dir, turn_id, artifact_path=artifact_path)

    def get_task_operation_preview_snapshots(self) -> dict[str, Any]:
        return build_task_operation_preview_snapshots()

    def cancel(self, run_id: str) -> dict[str, Any]:
        state = self.get_run(run_id)
        process = self._processes.get(run_id)
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        state["status"] = "cancelled"
        state["ended_at"] = time.time()
        state["returncode"] = -15
        self._write_state_dict(state)
        self._processes.pop(run_id, None)
        return self.get_run(run_id)

    def _refresh_active_processes(self) -> None:
        for run_id in list(self._processes):
            try:
                self.get_run(run_id)
            except Exception:
                self._processes.pop(run_id, None)

    def _refresh_run_state(self, state: dict[str, Any]) -> dict[str, Any]:
        run_id = str(state.get("run_id") or "")
        process = self._processes.get(run_id)
        if process is None:
            if str(state.get("status") or "") == "running":
                output_dir = Path(str(state.get("output_dir") or ""))
                run_result_path = output_dir / "run_result.json"
                if run_result_path.exists():
                    artifacts = read_json_file(run_result_path, {})
                    summary = summarize_run_result(artifacts if isinstance(artifacts, dict) else {})
                    failed = int(summary.get("failed", 0) or 0)
                    state["status"] = "failed" if failed else "passed"
                    state["returncode"] = 1 if failed else 0
                    state["ended_at"] = run_result_path.stat().st_mtime
                    state["summary"] = summary
                    state["duration_ms"] = self._duration_ms_from_state(state)
                    self._write_state_dict(state)
                elif self._recorded_process_is_gone(state):
                    reason = self._stale_running_reason(output_dir)
                    state["status"] = "failed"
                    state["returncode"] = -1
                    state["ended_at"] = max(
                        self._latest_mtime(output_dir),
                        float(state.get("started_at") or 0.0),
                    ) or time.time()
                    state["summary"] = {
                        "total": int(dict(state.get("summary") or {}).get("total", 0) or 0),
                        "passed": int(dict(state.get("summary") or {}).get("passed", 0) or 0),
                        "failed": 1,
                        "first_failure": reason,
                    }
                    state["duration_ms"] = self._duration_ms_from_state(state)
                    self._write_state_dict(state)
            return state
        returncode = process.poll()
        if returncode is None:
            return state
        output_dir = Path(str(state.get("output_dir") or ""))
        artifacts = read_json_file(output_dir / "run_result.json", {})
        summary = summarize_run_result(artifacts if isinstance(artifacts, dict) else {})
        state["status"] = "passed" if returncode == 0 else "failed"
        state["returncode"] = returncode
        state["ended_at"] = state.get("ended_at") or time.time()
        state["summary"] = summary
        state["duration_ms"] = self._duration_ms_from_state(state)
        self._write_state_dict(state)
        self._processes.pop(run_id, None)
        return state

    def _duration_ms_from_state(self, state: dict[str, Any]) -> float:
        try:
            started_at = float(state.get("started_at") or 0.0)
            ended_at = float(state.get("ended_at") or 0.0)
        except (TypeError, ValueError):
            return 0.0
        if started_at <= 0:
            return 0.0
        end = ended_at if ended_at > 0 else time.time()
        return round(max(end - started_at, 0.0) * 1000.0, 2)

    def _recorded_process_is_gone(self, state: dict[str, Any]) -> bool:
        try:
            pid = int(state.get("pid") or 0)
        except (TypeError, ValueError):
            pid = 0
        if pid <= 0:
            return False
        if os.name == "nt":
            return not _windows_pid_exists(pid)
        try:
            os.kill(pid, 0)
        except OSError:
            return True
        return False

    def _stale_running_reason(self, output_dir: Path) -> str:
        log_tail = read_text_tail(output_dir / "runner.log", limit=4000)
        if "KeyboardInterrupt" in log_tail:
            return "测试进程被 KeyboardInterrupt 中断，未生成 run_result.json。"
        if "Traceback" in log_tail:
            return "测试进程异常退出，未生成 run_result.json。"
        return "测试进程已不存在，但 run_state 仍停留在 running。"

    def _latest_mtime(self, output_dir: Path) -> float:
        latest = 0.0
        if not output_dir.exists():
            return latest
        for path in output_dir.rglob("*"):
            try:
                latest = max(latest, path.stat().st_mtime)
            except OSError:
                continue
        return latest

    def _safe_output_dir(self, run_id: str) -> Path:
        normalized = str(run_id or "").strip()
        if not normalized or "/" in normalized or "\\" in normalized or normalized.startswith("."):
            raise ValueError("Invalid run_id")
        output_dir = OUTPUT_ROOT / normalized
        resolved = output_dir.resolve()
        if not str(resolved).startswith(str(OUTPUT_ROOT.resolve())):
            raise ValueError("Invalid run_id")
        return output_dir

    def _state_path(self, output_dir: Path) -> Path:
        return output_dir / "run_state.json"

    def _load_state(self, output_dir: Path) -> dict[str, Any] | None:
        payload = read_json_file(self._state_path(output_dir), None)
        return payload if isinstance(payload, dict) else None

    def _write_state(self, run: ExperimentRun) -> None:
        self._write_state_dict(run.to_dict())

    def _write_state_dict(self, state: dict[str, Any]) -> None:
        output_dir = Path(str(state.get("output_dir") or ""))
        output_dir.mkdir(parents=True, exist_ok=True)
        state["duration_ms"] = self._duration_ms_from_state(state)
        (output_dir / "run_state.json").write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _state_from_artifacts(self, output_dir: Path) -> dict[str, Any]:
        run_result = read_json_file(output_dir / "run_result.json", {})
        context = dict(run_result.get("context") or {}) if isinstance(run_result, dict) else {}
        summary = summarize_run_result(run_result if isinstance(run_result, dict) else {})
        profile = str(context.get("profile") or output_dir.name.rsplit("-", 1)[-1] or "unknown")
        status = "failed" if int(summary.get("failed", 0) or 0) else "passed"
        if not (output_dir / "run_result.json").exists():
            status = "unknown"
        log_path = output_dir / "runner.log"
        return {
            "run_id": output_dir.name,
            "profile": profile,
            "status": status,
            "command": [],
            "command_preview": str(context.get("command") or ""),
            "output_dir": str(output_dir),
            "log_path": str(log_path),
            "started_at": 0,
            "ended_at": 0,
            "duration_ms": 0,
            "returncode": 0 if status == "passed" else None,
            "pid": None,
            "summary": summary,
        }


experiment_runner = ExperimentRunner()


def _windows_pid_exists(pid: int) -> bool:
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return False

    process_query_limited_information = 0x1000
    handle = ctypes.windll.kernel32.OpenProcess(process_query_limited_information, False, wintypes.DWORD(pid))
    if not handle:
        return False
    ctypes.windll.kernel32.CloseHandle(handle)
    return True
