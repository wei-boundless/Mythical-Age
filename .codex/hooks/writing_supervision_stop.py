from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
SUPERVISION_ROOT = REPO_ROOT / "output" / "novel_artifacts" / "simple_novel" / "supervision"
ACTIVE_MARKER = SUPERVISION_ROOT / "active_codex_supervision.json"


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def write_json(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False))
    sys.stdout.flush()


def continuation(reason: str, prompt: str) -> None:
    write_json(
        {
            "decision": "block",
            "reason": prompt,
            "continue": True,
            "systemMessage": reason,
        }
    )


def normalize_state_path(raw_path: str) -> Path:
    state_path = Path(str(raw_path or ""))
    if not state_path.is_absolute():
        state_path = REPO_ROOT / state_path
    return state_path


def state_payload_from_path(state_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    state = read_json(state_path)
    payload = dict(state.get("payload") or {})
    return state, payload


def latest_payload(marker: dict[str, Any]) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    state_path = normalize_state_path(str(marker.get("state_path") or ""))
    state, payload = state_payload_from_path(state_path)
    return state_path, state, payload


def state_recency_score(marker: dict[str, Any], state: dict[str, Any], state_path: Path) -> float:
    return max(
        float(state.get("updated_at") or 0.0),
        float(marker.get("updated_at") or 0.0),
        state_path.stat().st_mtime if state_path.exists() else 0.0,
    )


def latest_supervision_context() -> tuple[dict[str, Any], Path, dict[str, Any], dict[str, Any]]:
    marker = read_json(ACTIVE_MARKER)
    candidates: list[tuple[float, dict[str, Any], Path, dict[str, Any], dict[str, Any]]] = []

    if marker and marker.get("enabled") is True:
        state_path = normalize_state_path(str(marker.get("state_path") or ""))
        state, payload = state_payload_from_path(state_path)
        candidates.append((state_recency_score(marker, state, state_path), marker, state_path, state, payload))

    if SUPERVISION_ROOT.exists():
        for session_dir in SUPERVISION_ROOT.iterdir():
            if not session_dir.is_dir():
                continue
            state_path = session_dir / "state.json"
            if not state_path.exists():
                continue
            state, payload = state_payload_from_path(state_path)
            session_id = str(state.get("session_id") or payload.get("session_id") or session_dir.name)
            derived_marker = {
                "enabled": True,
                "status": "running",
                "session_id": session_id,
                "project_id": str(state.get("project_id") or payload.get("project_id") or ""),
                "target_words": int(payload.get("target_words") or 1_000_000),
                "state_path": str(state_path),
                "log_path": str(session_dir / "supervision.jsonl"),
                "stop_flag": str(SUPERVISION_ROOT / "STOP_SUPERVISION.flag"),
                "updated_at": float(state.get("updated_at") or 0.0),
            }
            candidates.append((state_recency_score(derived_marker, state, state_path), derived_marker, state_path, state, payload))

    if not candidates:
        return {}, Path(), {}, {}

    candidates.sort(key=lambda item: item[0], reverse=True)
    _, resolved_marker, resolved_state_path, resolved_state, resolved_payload = candidates[0]
    return resolved_marker, resolved_state_path, resolved_state, resolved_payload


def is_done(marker: dict[str, Any], payload: dict[str, Any]) -> bool:
    target_words = int(marker.get("target_words") or payload.get("target_words") or 1_000_000)
    completed_words = int(payload.get("completed_words_total") or 0)
    if completed_words < target_words:
        return False
    runtime_status = str(payload.get("runtime_status") or "")
    live_status = str(payload.get("live_status") or "")
    return runtime_status in {"completed", "succeeded"} or live_status in {"completed", "succeeded"}


def blocker_summary(payload: dict[str, Any]) -> str:
    blocker = dict(payload.get("blocker") or {})
    parts = []
    for key in ("kind", "severity", "summary", "message", "reason"):
        value = blocker.get(key)
        if value:
            parts.append(f"{key}={value}")
    return "; ".join(parts) if parts else "none"


def main() -> int:
    try:
        event = json.loads(sys.stdin.read() or "{}")
    except Exception:
        event = {}

    hook_event_name = str(event.get("hook_event_name") or event.get("event") or "")
    if hook_event_name and hook_event_name != "Stop":
        return 0

    marker, state_path, state, payload = latest_supervision_context()
    if not marker or marker.get("enabled") is not True:
        return 0

    stop_flag = Path(str(marker.get("stop_flag") or ""))
    if not stop_flag.is_absolute():
        stop_flag = REPO_ROOT / stop_flag
    if stop_flag.exists():
        return 0

    now = time.time()
    state_age = int(now - float(state.get("updated_at") or marker.get("updated_at") or 0))
    session_id = str(marker.get("session_id") or payload.get("session_id") or "")
    project_id = str(marker.get("project_id") or payload.get("project_id") or "")
    task_run_id = str(payload.get("task_run_id") or marker.get("task_run_id") or "")
    latest_task_run_id = str(payload.get("latest_task_run_id") or "")
    active_task_run_id = latest_task_run_id or task_run_id
    active_node_id = str(payload.get("active_node_id") or "")
    active_task_ref = str(payload.get("active_task_ref") or "")
    coordination_run_id = str(payload.get("coordination_run_id") or marker.get("coordination_run_id") or "")
    completed_words = int(payload.get("completed_words_total") or 0)
    target_words = int(payload.get("target_words") or marker.get("target_words") or 1_000_000)
    remaining_words = max(target_words - completed_words, 0)

    if is_done(marker, payload):
        return 0

    common = (
        "你正在执行《洪荒时代》百万字写作任务的 Codex 持续值守接力。"
        "这不是写作节点，不要替系统伪造章节；你是外部运维、调试、结构修复和值守监督者。"
        f"\n\n当前监督会话: {session_id}"
        f"\n项目: {project_id}"
        f"\nRoot task run: {task_run_id or 'unknown'}"
        f"\n当前活动 task run: {active_task_run_id or 'unknown'}"
        f"\n当前活动节点: {active_node_id or 'unknown'}"
        f"\n当前活动任务: {active_task_ref or 'unknown'}"
        f"\nCoordination run: {coordination_run_id or 'unknown'}"
        f"\n监督状态文件: {state_path}"
        f"\n项目累计已提交字数（跨 run）: {completed_words}/{target_words}，剩余约 {remaining_words}"
        "\n\n你必须读取监督状态、运行监控、trace、产物和记忆回执，判断任务是否真实推进。"
        "如果发现阻塞、失败、假死、产物覆盖、语义污染、记忆污染或监控失真，要追踪根因并修复系统，再恢复或重启任务。"
        "只有通过审核并提交的章节可以计入进度。"
    )

    runtime_status = str(payload.get("runtime_status") or payload.get("live_status") or "")
    terminal_reason = str(payload.get("terminal_reason") or "")
    seconds_since_event_change = int(payload.get("seconds_since_event_change") or 0)
    seconds_since_effective_activity = int(payload.get("seconds_since_effective_activity") or 0)
    seconds_since_progress_change = int(payload.get("seconds_since_progress_change") or 0)
    block = blocker_summary(payload)

    if not state or state_age > 180:
        continuation(
            "writing_supervision_state_stale",
            common
            + f"\n\n监督状态已经 {state_age} 秒没有更新，可能是后台监督器或任务运行断了。"
            "请立即检查进程、端口、后端日志、监督日志和当前 run 状态；必要时重启监督器或修复启动链路。"
            "处理完后继续值守，不要把问题留给用户回来发现。",
        )
        return 0

    if runtime_status in {"failed", "aborted"} or terminal_reason:
        continuation(
            "writing_task_terminal_or_failed",
            common
            + f"\n\n当前运行状态异常: runtime_status={runtime_status}, terminal_reason={terminal_reason or 'none'}。"
            "请定位失败点，检查 debug run report、后端 trace、产物落盘和记忆提交，做结构性修复并恢复运行。",
        )
        return 0

    if block != "none":
        continuation(
            "writing_task_blocker_detected",
            common
            + f"\n\n监督器报告 blocker: {block}。"
            "请不要简单重试糊弄过去；先确认是运行阻塞、状态不一致、图结构问题、记忆污染还是产物异常，再实施修复并验证恢复。",
        )
        return 0

    if (
        seconds_since_event_change >= 180
        and seconds_since_progress_change >= 180
        and seconds_since_effective_activity >= 180
    ):
        continuation(
            "writing_task_event_stalled",
            common
            + (
                f"\n\n事件计数已经 {seconds_since_event_change} 秒没有变化，"
                f"且最近有效推进也已停滞 {seconds_since_progress_change} 秒，可能是假死或后台续推断点。"
            )
            +
            "请检查 live monitor、task graph monitor、current stage request、trace 和产物最新修改时间，必要时修复后续推。",
        )
        return 0

    continuation(
        "writing_supervision_continue_watch",
        common
        + "\n\n当前没有明确故障，但任务还没有达到百万字完成标准。"
        "请等待 60 秒后重新检查监督状态和最新产物；如果仍正常推进，继续值守。"
        "如果出现任何阻塞、异常断点或语义污染，立即追踪并修复。",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
