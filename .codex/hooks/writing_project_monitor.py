from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = REPO_ROOT / "output" / "codex_hook_monitor"
LATEST_PATH = OUTPUT_ROOT / "writing_project_monitor_latest.json"
LOG_PATH = OUTPUT_ROOT / "writing_project_monitor.jsonl"
SUPERVISION_ROOT = REPO_ROOT / "output" / "novel_artifacts" / "simple_novel" / "supervision"
ACTIVE_SUPERVISION_PATH = SUPERVISION_ROOT / "active_codex_supervision.json"

BASE_URL = "http://127.0.0.1:8004/api"
PROJECT_ID = "project:honghuang-times"
SUPERVISION_STALE_SECONDS = 180


def read_stdin_json() -> dict[str, Any]:
    try:
        return json.loads(sys.stdin.read() or "{}")
    except Exception:
        return {}


def write_stdout_json(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False))
    sys.stdout.flush()


def continuation(reason: str, prompt: str) -> None:
    write_stdout_json(
        {
            "decision": "block",
            "reason": prompt,
            "continue": True,
            "systemMessage": reason,
        }
    )


def api_get(path: str) -> dict[str, Any]:
    url = f"{BASE_URL}{path}"
    request = urllib.request.Request(url=url, method="GET")
    with urllib.request.urlopen(request, timeout=20) as response:
        raw = response.read().decode("utf-8")
    return json.loads(raw or "{}")


def safe_api_get(path: str) -> tuple[dict[str, Any], str]:
    try:
        return api_get(path), ""
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="ignore")
        except Exception:
            detail = str(exc)
        return {}, f"http_error:{exc.code}:{detail[:300]}"
    except Exception as exc:
        return {}, f"request_error:{exc}"


def ensure_output_root() -> None:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)


def append_log(payload: dict[str, Any]) -> None:
    ensure_output_root()
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def write_latest(payload: dict[str, Any]) -> None:
    ensure_output_root()
    LATEST_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def quoted(value: str) -> str:
    return urllib.parse.quote(str(value or ""), safe="")


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def normalized_path(raw_path: str) -> Path:
    path = Path(str(raw_path or ""))
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path


def active_supervision_snapshot() -> dict[str, Any]:
    marker = read_json(ACTIVE_SUPERVISION_PATH)
    state_path = normalized_path(str(marker.get("state_path") or ""))
    state = read_json(state_path)
    recency_candidates: list[float] = []
    for value in (marker.get("updated_at"), state.get("updated_at")):
        try:
            timestamp = float(value or 0.0)
        except (TypeError, ValueError):
            timestamp = 0.0
        if timestamp > 0:
            recency_candidates.append(timestamp)
    if state_path.exists():
        recency_candidates.append(state_path.stat().st_mtime)
    last_seen_at = max(recency_candidates) if recency_candidates else 0.0
    age_seconds = int(max(0, time.time() - last_seen_at)) if last_seen_at > 0 else 10**9
    return {
        "marker": marker,
        "state": state,
        "state_path": str(state_path) if str(state_path) else "",
        "status": str(marker.get("status") or state.get("status") or ""),
        "enabled": marker.get("enabled") is True,
        "age_seconds": age_seconds,
        "stale": age_seconds > SUPERVISION_STALE_SECONDS,
    }


def summarize_monitor(task_graph_monitor: dict[str, Any]) -> dict[str, Any]:
    runtime = dict(task_graph_monitor.get("runtime") or {})
    progress = dict(task_graph_monitor.get("progress") or {})
    streaming = dict(task_graph_monitor.get("streaming") or {})
    blocker = dict(task_graph_monitor.get("blocker") or {})
    current_stage = dict(task_graph_monitor.get("current_stage_execution_request") or {})
    return {
        "runtime_status": str(runtime.get("status") or ""),
        "terminal_status": str(runtime.get("terminal_status") or ""),
        "active_node_id": str(runtime.get("active_node_id") or ""),
        "active_task_ref": str(runtime.get("active_task_ref") or ""),
        "latest_event_offset": int(runtime.get("last_event_offset") or 0),
        "completed_words_total": int(progress.get("completed_words_total") or 0),
        "target_words": int(progress.get("target_words") or 0),
        "remaining_words": int(progress.get("remaining_words") or 0),
        "committed_chapter_count": int(progress.get("committed_chapter_count") or 0),
        "stream_enabled": bool(streaming.get("enabled") is True),
        "stream_chunk_count": int(streaming.get("chunk_count") or 0),
        "stream_preview_text": str(streaming.get("preview_text") or ""),
        "blocker": blocker,
        "stage_id": str(current_stage.get("stage_id") or ""),
        "coordination_run_id": str(task_graph_monitor.get("coordination_run_id") or ""),
    }


def build_snapshot(event: dict[str, Any]) -> dict[str, Any]:
    project_view, project_error = safe_api_get(f"/orchestration/projects/{quoted(PROJECT_ID)}/runtime-status")
    project_runtime_status = dict(project_view.get("project_runtime_status") or {})
    project_ledger = dict(project_view.get("project_progress_ledger") or {})
    active_task_run_id = str(project_runtime_status.get("active_task_run_id") or "")

    task_graph_monitor: dict[str, Any] = {}
    task_graph_monitor_error = ""
    live_monitor: dict[str, Any] = {}
    live_monitor_error = ""
    artifacts: dict[str, Any] = {}
    artifacts_error = ""
    memory_receipts: dict[str, Any] = {}
    memory_receipts_error = ""

    if active_task_run_id:
        encoded = quoted(active_task_run_id)
        task_graph_monitor, task_graph_monitor_error = safe_api_get(
            f"/orchestration/runtime-loop/task-runs/{encoded}/task-graph-monitor"
        )
        live_monitor, live_monitor_error = safe_api_get(
            f"/orchestration/runtime-loop/task-runs/{encoded}/live-monitor"
        )
        artifacts, artifacts_error = safe_api_get(
            f"/orchestration/runtime-loop/task-runs/{encoded}/artifacts"
        )
        memory_receipts, memory_receipts_error = safe_api_get(
            f"/orchestration/runtime-loop/task-runs/{encoded}/memory-receipts"
        )

    summary = summarize_monitor(task_graph_monitor) if task_graph_monitor else {}
    payload = {
        "hook_event_name": str(event.get("hook_event_name") or event.get("event") or ""),
        "created_at": time.time(),
        "project_id": PROJECT_ID,
        "project_runtime_status": project_runtime_status,
        "project_progress_ledger": project_ledger,
        "active_task_run_id": active_task_run_id,
        "summary": summary,
        "task_graph_monitor": task_graph_monitor,
        "live_monitor": live_monitor,
        "artifacts": artifacts,
        "memory_receipts": memory_receipts,
        "active_supervision": active_supervision_snapshot(),
        "errors": {
            "project_runtime_status": project_error,
            "task_graph_monitor": task_graph_monitor_error,
            "live_monitor": live_monitor_error,
            "artifacts": artifacts_error,
            "memory_receipts": memory_receipts_error,
        },
        "authority": "codex.hook.writing_project_monitor",
    }
    return payload


def should_continue(snapshot: dict[str, Any]) -> tuple[bool, str, str]:
    summary = dict(snapshot.get("summary") or {})
    project_runtime_status = dict(snapshot.get("project_runtime_status") or {})
    errors = dict(snapshot.get("errors") or {})
    project_error = str(errors.get("project_runtime_status") or "")

    if project_error:
        prompt = (
            "写作项目监测钩子发现后端项目状态读取失败。"
            f"\nproject_id={PROJECT_ID}"
            f"\nerror={project_error}"
            "\n请先检查 8004 后端是否可用、项目运行状态接口是否正常，再继续监督。"
        )
        return True, "writing_project_monitor_backend_unavailable", prompt

    active_task_run_id = str(snapshot.get("active_task_run_id") or "")
    if not active_task_run_id:
        return False, "", ""

    active_run_status = str(project_runtime_status.get("active_run_status") or "")
    runtime_status = str(summary.get("runtime_status") or active_run_status)
    terminal_status = str(summary.get("terminal_status") or "")
    completed_words_total = int(summary.get("completed_words_total") or project_runtime_status.get("completed_words_total") or 0)
    target_words = int(summary.get("target_words") or project_runtime_status.get("target_words") or 1000000)
    blocker = dict(summary.get("blocker") or project_runtime_status.get("active_blocker") or {})
    blocker_text = " / ".join(str(blocker.get(key) or "") for key in ("kind", "summary", "message", "reason") if str(blocker.get(key) or ""))
    active_node_id = str(summary.get("active_node_id") or "")
    active_task_ref = str(summary.get("active_task_ref") or "")
    chunk_count = int(summary.get("stream_chunk_count") or 0)
    stream_preview_text = str(summary.get("stream_preview_text") or "")
    active_supervision = dict(snapshot.get("active_supervision") or {})

    common = (
        "你正在值守《洪荒时代》项目自运行写作任务。"
        "你的职责是监测、追踪、修复，不是替系统伪造产物。"
        f"\n当前 task_run: {active_task_run_id}"
        f"\n当前节点: {active_node_id or 'unknown'}"
        f"\n当前任务: {active_task_ref or 'unknown'}"
        f"\n累计已提交字数: {completed_words_total}/{target_words}"
    )

    if blocker_text:
        return (
            True,
            "writing_project_monitor_blocker",
            common
            + f"\n\n监测钩子发现 blocker: {blocker_text}"
            + "\n请立即检查 task graph monitor、trace、产物和记忆回执，定位根因并修复后继续监督。",
        )

    if runtime_status in {"failed", "aborted"} or terminal_status in {"failed", "aborted"}:
        return (
            True,
            "writing_project_monitor_failed",
            common
            + f"\n\n运行状态异常: runtime_status={runtime_status}, terminal_status={terminal_status}。"
            + "\n请追踪失败节点和 debug 产物，修复系统后恢复运行。",
        )

    if completed_words_total >= target_words and runtime_status in {"completed", "succeeded"}:
        return False, "", ""

    supervision_enabled = bool(active_supervision.get("enabled") is True)
    supervision_status = str(active_supervision.get("status") or "")
    supervision_age = int(active_supervision.get("age_seconds") or 0)
    supervision_stale = bool(active_supervision.get("stale") is True)
    if active_task_run_id and (not supervision_enabled or supervision_status not in {"running", "starting"} or supervision_stale):
        return (
            True,
            "writing_project_monitor_supervision_paused",
            common
            + "\n\n后台监督链路看起来没有稳定运行。"
            + f"\nsupervision_enabled={supervision_enabled}, supervision_status={supervision_status or 'unknown'}, state_age_seconds={supervision_age}"
            + "\n请检查 active supervision、watchdog 和 supervisor 进程；必要时重新挂载监督器，然后继续监测产物和记忆提交。",
        )

    return False, "", ""


def main() -> int:
    event = read_stdin_json()
    hook_event_name = str(event.get("hook_event_name") or event.get("event") or "")
    if hook_event_name and hook_event_name != "Stop":
        return 0

    snapshot = build_snapshot(event)
    write_latest(snapshot)
    append_log(
        {
            "created_at": snapshot.get("created_at"),
            "project_id": snapshot.get("project_id"),
            "active_task_run_id": snapshot.get("active_task_run_id"),
            "summary": snapshot.get("summary"),
            "errors": snapshot.get("errors"),
            "authority": snapshot.get("authority"),
        }
    )

    should_block, reason, prompt = should_continue(snapshot)
    if should_block:
        continuation(reason, prompt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
