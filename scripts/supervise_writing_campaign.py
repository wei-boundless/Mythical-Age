from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


GRAPH_ID = "graph.writing.simple_novel"
DEFAULT_BASE_URL = "http://127.0.0.1:8004/api"
DEFAULT_TARGET_WORDS = 1_000_000
DEFAULT_CHAPTER_TARGET_WORDS = 2_000
DEFAULT_CHAPTERS_PER_ROUND = 10
DEFAULT_PROJECT_ID = "project:honghuang-times"
DEFAULT_PROJECT_TITLE = "洪荒时代"
DEFAULT_BRIEF_PATH = Path("output/novel_artifacts/simple_novel/project_brief.md")
SUPERVISION_ROOT = Path("output/novel_artifacts/simple_novel/supervision")
ACTIVE_SUPERVISION_PATH = SUPERVISION_ROOT / "active_codex_supervision.json"
STOP_SUPERVISION_FLAG = SUPERVISION_ROOT / "STOP_SUPERVISION.flag"


DEFAULT_PROJECT_BRIEF = """写作长篇小说《洪荒时代》。

主角是一名来自大泽的少年。创作需要以以下五个角色作为故事背景：

1. 勾芒：东荒众生的指引者。勾芒是洪荒中最繁荣的青木，它携带东风、青烟与万物萌发的记忆。
2. 河伯：中土水府的汇聚者。河伯是洪荒中最神圣的河流，它携带百川、渡口与古老祭辞的记忆。
3. 四岳：西荒诸城的执衡者。四岳是洪荒中最巍然的山脉，它承载地脉、聚落与万城之盟的记忆。
4. 祝融：南荒火庭的开路者。祝融是洪荒中最炽烈的火焰，它携带光焰、锻造与人间烈火的记忆。
5. 玄女：北荒玄宫的守护者。玄女是洪荒中最神秘的夜幕，它携带月辉、星图与渊深通玄的记忆。

作品目标是一百万字左右，每章约两千字。整体风格要更商业化、更网络小说化，强调强钩子、清晰升级线、持续冲突、阶段性爽点、人物关系推进和可连载阅读节奏。
"""


class SupervisorError(RuntimeError):
    pass


class ApiClient:
    def __init__(self, base_url: str, timeout: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def get(self, path: str) -> dict[str, Any]:
        return self._request("GET", path)

    def post(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._request("POST", path, payload or {})

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise SupervisorError(f"{method} {url} failed: HTTP {exc.code} {detail}") from exc
        except urllib.error.URLError as exc:
            raise SupervisorError(f"{method} {url} failed: {exc.reason}") from exc
        if not raw.strip():
            return {}
        return json.loads(raw)


class WritingCampaignSupervisor:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.client = ApiClient(args.base_url, args.timeout)
        self.session_id = args.session_id
        self.project_id = args.project_id
        self.supervision_dir = SUPERVISION_ROOT / self.session_id
        self.supervision_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.supervision_dir / "supervision.jsonl"
        self.state_path = self.supervision_dir / "state.json"
        self.task_run_id = str(args.task_run_id or "")
        self.coordination_run_id = str(args.coordination_run_id or "")
        self.last_event_count = -1
        self.last_event_change_at = time.time()
        self.last_effective_activity_at = time.time()
        self.last_progress_marker: str = ""
        self.last_progress_change_at = time.time()
        self.last_latest_task_run_id: str = ""
        self.last_latest_task_run_change_at = time.time()
        self.last_running_child_seen_at = time.time()
        self.last_action_at_by_key: dict[str, float] = {}
        self.repair_counts: dict[str, int] = {}

    def run(self) -> int:
        self.log("supervisor_started", {"session_id": self.session_id, "project_id": self.project_id})
        self.write_active_supervision("running", "supervisor_started")
        if self.args.start and not self.task_run_id:
            self.start_formal_run()
        iteration = 0
        while True:
            iteration += 1
            try:
                done = self.supervise_once(iteration)
            except SupervisorError as exc:
                self.log("supervisor_api_error", {"error": str(exc), "iteration": iteration})
                if self.args.fail_on_api_error:
                    raise
                done = False
            except Exception as exc:
                self.log("supervisor_internal_error", {"error": str(exc), "type": exc.__class__.__name__, "iteration": iteration})
                if self.args.fail_on_api_error:
                    raise
                done = False
            if done:
                self.log("supervisor_completed", {"reason": "target_words_reached_and_delivery_ready"})
                self.write_active_supervision("completed", "target_words_reached_and_delivery_ready")
                return 0
            if self.args.max_iterations and iteration >= self.args.max_iterations:
                self.log("supervisor_stopped", {"reason": "max_iterations", "max_iterations": self.args.max_iterations})
                self.write_active_supervision("stopped", "max_iterations")
                return 0
            time.sleep(self.args.interval)

    def start_formal_run(self) -> None:
        initial_inputs = self.initial_inputs()
        payload = {
            "session_id": self.session_id,
            "task_id": self.args.task_id,
            "initial_inputs": initial_inputs,
            "require_published": True,
            "include_trace": True,
            "execute_initial_stage": True,
        }
        result = self.client.post(f"/orchestration/runtime-loop/task-graphs/{urllib.parse.quote(self.args.graph_id, safe='')}/start", payload)
        self.task_run_id = str(result.get("task_run_id") or "")
        self.coordination_run_id = str(result.get("coordination_run_id") or "")
        if not self.task_run_id or not self.coordination_run_id:
            raise SupervisorError("TaskGraph start did not return task_run_id and coordination_run_id")
        self.log(
            "formal_run_started",
            {
                "task_run_id": self.task_run_id,
                "coordination_run_id": self.coordination_run_id,
                "initial_stage_execution_background": bool(result.get("initial_stage_execution_background")),
            },
        )
        self.write_state({"task_run_id": self.task_run_id, "coordination_run_id": self.coordination_run_id})

    def supervise_once(self, iteration: int) -> bool:
        live = self.client.get(f"/orchestration/runtime-loop/sessions/{urllib.parse.quote(self.session_id, safe='')}/live-monitor")
        monitor_payload = dict(live.get("monitor") or {})
        latest_task_run_id = str(live.get("latest_task_run_id") or "")
        if latest_task_run_id != self.last_latest_task_run_id:
            self.last_latest_task_run_id = latest_task_run_id
            now = time.time()
            self.last_latest_task_run_change_at = now
            self.last_running_child_seen_at = now
            self.last_effective_activity_at = now
        if not self.task_run_id:
            self.task_run_id = latest_task_run_id
        if not self.task_run_id and not self.args.start:
            self.log("no_active_task_run", {"iteration": iteration})
            return False
        if self.task_run_id:
            graph_monitor = self.client.get(f"/orchestration/runtime-loop/task-runs/{urllib.parse.quote(self.task_run_id, safe='')}/task-graph-monitor")
        else:
            graph_monitor = {}
        self.coordination_run_id = str(graph_monitor.get("coordination_run_id") or self.coordination_run_id)
        project_status = self.try_get_project_status()
        progress_marker = self.progress_marker(live, monitor_payload, graph_monitor)
        if progress_marker != self.last_progress_marker:
            self.last_progress_marker = progress_marker
            marker_timestamp = self.progress_marker_timestamp(live, monitor_payload, graph_monitor) or time.time()
            self.last_progress_change_at = marker_timestamp
            self.last_effective_activity_at = marker_timestamp
        snapshot = self.snapshot(iteration, live, monitor_payload, graph_monitor, project_status)
        self.write_state(snapshot)
        self.log("supervision_observed", snapshot)
        if self.is_complete(project_status, graph_monitor):
            return True
        action = self.decide_action(monitor_payload, graph_monitor, project_status)
        if action:
            self.apply_action(action, graph_monitor)
        return False

    def initial_inputs(self) -> dict[str, Any]:
        project_brief = self.read_project_brief()
        artifact_root = self.args.artifact_root or f"output/novel_artifacts/simple_novel/runs/{self.session_id}"
        return {
            "project_id": self.project_id,
            "project_title": self.args.project_title,
            "title": self.args.project_title,
            "project_brief": project_brief,
            "metric_label": "words",
            "target_metric_total": self.args.target_words,
            "target_words": self.args.target_words,
            "target_length": str(self.args.target_words),
            "chapter_target_words": self.args.chapter_target_words,
            "chapters_per_round": self.args.chapters_per_round,
            "chapter_batch_size": self.args.chapters_per_round,
            "requested_batch": f"每轮连续创作 {self.args.chapters_per_round} 章，每章约 {self.args.chapter_target_words} 字；审核和记忆提交也按同一批次处理。",
            "artifact_root": artifact_root,
            "human_gate_mode": "auto_continue",
            "supervision_mode": "codex_local_supervisor",
            "source": "scripts.supervise_writing_campaign",
        }

    def read_project_brief(self) -> str:
        path = Path(self.args.project_brief_file)
        if path.exists():
            text = path.read_text(encoding="utf-8").strip()
            if text:
                return text
        if self.args.allow_default_brief:
            return DEFAULT_PROJECT_BRIEF.strip()
        raise SupervisorError(f"Project brief file is missing or empty: {path}")

    def try_get_project_status(self) -> dict[str, Any]:
        try:
            return self.client.get(f"/orchestration/projects/{urllib.parse.quote(self.project_id, safe='')}/runtime-status")
        except SupervisorError as exc:
            self.log("project_status_unavailable", {"error": str(exc)})
            return {}

    def snapshot(
        self,
        iteration: int,
        live: dict[str, Any],
        monitor_payload: dict[str, Any],
        graph_monitor: dict[str, Any],
        project_status: dict[str, Any],
    ) -> dict[str, Any]:
        runtime = dict(graph_monitor.get("runtime") or {})
        progress = dict(graph_monitor.get("progress") or {})
        blocker = dict(graph_monitor.get("blocker") or {})
        event_count = int(runtime.get("event_count") or 0)
        now = time.time()
        if event_count != self.last_event_count:
            self.last_event_count = event_count
            self.last_event_change_at = now
            self.last_effective_activity_at = now
        marker_activity_at = self.progress_marker_timestamp(live, monitor_payload, graph_monitor)
        if marker_activity_at > self.last_effective_activity_at:
            self.last_effective_activity_at = marker_activity_at
        return {
            "iteration": iteration,
            "observed_at": now,
            "session_id": self.session_id,
            "task_run_id": self.task_run_id,
            "coordination_run_id": self.coordination_run_id,
            "latest_task_run_id": self.last_latest_task_run_id,
            "live_status": str(monitor_payload.get("status") or ""),
            "runtime_status": str(runtime.get("status") or ""),
            "terminal_reason": str(runtime.get("terminal_reason") or ""),
            "active_node_id": str(runtime.get("active_node_id") or ""),
            "active_task_ref": str(runtime.get("active_task_ref") or ""),
            "event_count": event_count,
            "seconds_since_event_change": int(now - self.last_event_change_at),
            "seconds_since_effective_activity": int(now - self.last_effective_activity_at),
            "seconds_since_progress_change": int(now - self.last_progress_change_at),
            "progress_marker": self.last_progress_marker,
            "metric_label": str(progress.get("metric_label") or "words"),
            "target_metric_total": int(progress.get("target_metric_total") or self.args.target_words),
            "completed_metric_total": int(progress.get("completed_metric_total") or 0),
            "remaining_metric_total": int(progress.get("remaining_metric_total") or self.args.target_words),
            "committed_unit_count": int(progress.get("committed_unit_count") or 0),
            "last_committed_unit_index": int(progress.get("last_committed_unit_index") or 0),
            "blocker": blocker,
            "health": dict(graph_monitor.get("health") or {}),
            "project_status_available": bool(project_status),
        }

    def decide_action(
        self,
        monitor_payload: dict[str, Any],
        graph_monitor: dict[str, Any],
        project_status: dict[str, Any],
    ) -> dict[str, Any]:
        runtime = dict(graph_monitor.get("runtime") or {})
        health = dict(graph_monitor.get("health") or {})
        current_stage = dict(graph_monitor.get("current_stage_execution_request") or {})
        blocker = dict(graph_monitor.get("blocker") or {})
        status = str(runtime.get("status") or monitor_payload.get("status") or "")
        live_status = str(monitor_payload.get("status") or "")
        active_node_id = str(runtime.get("active_node_id") or "")
        active_task_ref = str(runtime.get("active_task_ref") or "")
        latest_task_run_id = self.last_latest_task_run_id
        seconds_since_progress_change = int(time.time() - self.last_progress_change_at)
        seconds_since_latest_task_run_change = int(time.time() - self.last_latest_task_run_change_at)
        requested_stage_id = str(current_stage.get("stage_id") or current_stage.get("node_id") or "").strip()
        requested_task_ref = str(current_stage.get("task_ref") or "").strip()
        live_task_run = dict((dict(monitor_payload.get("task_run") or {}) if isinstance(monitor_payload, dict) else {}) or {})
        live_loop_state = dict((dict(monitor_payload.get("loop_state") or {}) if isinstance(monitor_payload, dict) else {}) or {})
        latest_is_requested_stage = bool(
            requested_stage_id
            and latest_task_run_id
            and f":{requested_stage_id}:" in latest_task_run_id
        )
        child_is_running_requested_stage = bool(
            live_status == "running"
            and latest_is_requested_stage
            and (not requested_task_ref or requested_task_ref == active_task_ref)
        )
        if child_is_running_requested_stage:
            self.last_running_child_seen_at = time.time()
            child_step_count = int(live_loop_state.get("step_count") or 0)
            child_current_step_id = str(live_loop_state.get("current_step_id") or "")
            child_updated_at = float(live_task_run.get("updated_at") or monitor_payload.get("updated_at") or 0.0)
            child_checkpoint_at = float(dict(monitor_payload.get("latest_checkpoint") or {}).get("created_at") or 0.0)
            child_last_activity_at = max(child_updated_at, child_checkpoint_at, self.last_progress_change_at)
            child_seconds_since_activity = int(time.time() - child_last_activity_at) if child_last_activity_at > 0 else seconds_since_progress_change
            if (
                child_step_count == 0
                and child_current_step_id == "understand_request"
                and child_seconds_since_activity >= max(45, int(self.args.interval * 4))
            ):
                return {
                    "kind": "stop_stale_child_task",
                    "reason": "running_child_task_stuck_at_understand_request",
                    "task_run_id": latest_task_run_id,
                    "seconds_since_child_activity": child_seconds_since_activity,
                }
            if (
                seconds_since_progress_change >= self.args.running_child_stall_seconds
                and seconds_since_latest_task_run_change >= self.args.running_child_stall_seconds
            ):
                return {
                    "kind": "stop_stale_child_task",
                    "reason": "running_child_task_checkpoint_stalled",
                    "task_run_id": latest_task_run_id,
                    "seconds_since_progress_change": seconds_since_progress_change,
                }
        if current_stage and status in {"running", "failed", "blocked"} and seconds_since_progress_change < max(20, self.args.interval * 3):
            return {}
        if current_stage and status in {"running", "failed", "blocked"} and not (
            child_is_running_requested_stage
        ):
            return {"kind": "continue_current_stage", "reason": "active_stage_request_without_running_child_task"}
        if health.get("valid") is False and any(dict(item).get("severity") == "error" for item in list(health.get("issues") or [])):
            return {"kind": "structural_stop", "reason": "monitor_health_error", "health": health}
        if status == "failed" and str(runtime.get("terminal_status") or "") == "blocked" and not dict(runtime.get("failure") or {}):
            return {"kind": "continue_current_stage", "reason": "blocked_checkpoint_with_resumable_task_result"}
        if status in {"failed", "aborted"}:
            return {"kind": "structural_stop", "reason": "run_terminal_failed", "runtime": runtime}
        if blocker.get("kind") in {"missing_stage_execution_request", "run_failed"}:
            return {"kind": "continue_current_stage", "reason": str(blocker.get("kind") or "blocker")}
        if active_node_id and not current_stage and status in {"running", "blocked"}:
            return {"kind": "continue_current_stage", "reason": "active_node_without_stage_request"}
        if (
            seconds_since_progress_change >= self.args.stall_seconds
            and status in {"running", "blocked"}
            and not child_is_running_requested_stage
        ):
            return {"kind": "continue_current_stage", "reason": "event_count_stalled"}
        return {}

    def apply_action(self, action: dict[str, Any], graph_monitor: dict[str, Any]) -> None:
        kind = str(action.get("kind") or "")
        runtime = dict(graph_monitor.get("runtime") or {})
        checkpoint_ref = str(runtime.get("checkpoint_ref") or "")
        active_node_id = str(runtime.get("active_node_id") or "")
        active_task_ref = str(runtime.get("active_task_ref") or "")
        key = f"{kind}:{action.get('reason') or ''}:{active_node_id}:{active_task_ref}:{checkpoint_ref}"
        cooldown_seconds = 20 if kind == "continue_current_stage" else max(30, min(self.args.stall_seconds, 180))
        last_action_at = self.last_action_at_by_key.get(key, 0.0)
        now = time.time()
        if now - last_action_at < cooldown_seconds:
            self.log("repair_throttled", {"action": action, "cooldown_seconds": cooldown_seconds, "last_action_at": last_action_at})
            return
        self.last_action_at_by_key[key] = now
        if kind == "structural_stop":
            self.repair_counts[key] = self.repair_counts.get(key, 0) + 1
            if self.repair_counts[key] > self.args.max_repairs_per_reason:
                self.log("repair_limit_reached", {"action": action, "count": self.repair_counts[key]})
                return
            self.log("structural_stop_required", {"action": action})
            if self.args.stop_on_structural_fault:
                raise SupervisorError(f"Structural fault requires Codex repair: {action}")
            return
        if kind == "continue_current_stage":
            self.repair_counts[key] = self.repair_counts.get(key, 0) + 1
            if self.repair_counts[key] > self.args.max_repairs_per_reason:
                self.log("repair_limit_reached", {"action": action, "count": self.repair_counts[key], "key": key})
                if self.args.stop_on_structural_fault:
                    raise SupervisorError(f"Repeated continuation failed for the same runtime checkpoint: {action}")
                return
            if not self.coordination_run_id:
                self.log("repair_skipped", {"reason": "missing_coordination_run_id", "action": action})
                return
            payload = {
                "source": "scripts.supervise_writing_campaign",
                "current_turn_context": {
                    "authority": "supervisor.repair.continue_current_stage",
                    "repair_reason": str(action.get("reason") or ""),
                    "project_id": self.project_id,
                },
            }
            result = self.client.post(
                f"/orchestration/coordination-runs/{urllib.parse.quote(self.coordination_run_id, safe='')}/continue-current-stage",
                payload,
            )
            self.log("repair_continue_current_stage", {"action": action, "result": result})
        if kind == "stop_stale_child_task":
            task_run_id = str(action.get("task_run_id") or "")
            if not task_run_id:
                self.log("repair_skipped", {"reason": "missing_child_task_run_id", "action": action})
                return
            result = self.client.post(
                f"/orchestration/runtime-loop/task-runs/{urllib.parse.quote(task_run_id, safe='')}/stop",
                {
                    "reason": "supervisor_stale_child_task",
                    "message": (
                        "Codex supervisor stopped a child task that remained running without "
                        "checkpoint/artifact progress beyond the configured stall threshold."
                    ),
                },
            )
            self.log("repair_stop_stale_child_task", {"action": action, "result": result})

    def progress_marker(self, live: dict[str, Any], monitor_payload: dict[str, Any], graph_monitor: dict[str, Any]) -> str:
        runtime = dict(graph_monitor.get("runtime") or {})
        live_monitor = dict(live.get("monitor") or {})
        checkpoint = runtime.get("checkpoint_ref") or live_monitor.get("latest_checkpoint", {}).get("checkpoint_id") or ""
        checkpoint_updated_at = runtime.get("checkpoint_updated_at") or live_monitor.get("latest_checkpoint", {}).get("created_at") or ""
        latest_task_run_id = live.get("latest_task_run_id") or self.task_run_id or ""
        active_node_id = runtime.get("active_node_id") or ""
        active_task_ref = runtime.get("active_task_ref") or ""
        runtime_status = runtime.get("status") or ""
        live_status = monitor_payload.get("status") or ""
        return "|".join(
            str(part)
            for part in (
                latest_task_run_id,
                active_node_id,
                active_task_ref,
                checkpoint,
                checkpoint_updated_at,
                runtime_status,
                live_status,
            )
        )

    def progress_marker_timestamp(
        self,
        live: dict[str, Any],
        monitor_payload: dict[str, Any],
        graph_monitor: dict[str, Any],
    ) -> float:
        runtime = dict(graph_monitor.get("runtime") or {})
        live_monitor = dict(live.get("monitor") or {})
        checkpoint = dict(live_monitor.get("latest_checkpoint") or {})
        candidates = (
            checkpoint.get("created_at"),
            monitor_payload.get("updated_at"),
            runtime.get("updated_at"),
            runtime.get("checkpoint_updated_at"),
        )
        for value in candidates:
            try:
                timestamp = float(value or 0.0)
            except (TypeError, ValueError):
                continue
            if timestamp > 0:
                return timestamp
        return 0.0

    def is_complete(self, project_status: dict[str, Any], graph_monitor: dict[str, Any]) -> bool:
        progress = dict(graph_monitor.get("progress") or {})
        supervision = dict(graph_monitor.get("supervision") or {})
        completed = int(progress.get("completed_metric_total") or 0)
        target = int(progress.get("target_metric_total") or self.args.target_words)
        delivery_state = str(supervision.get("project_runtime_status") or "")
        if completed >= target and delivery_state == "completed":
            return True
        runtime_status = str(dict(dict(project_status.get("project_runtime_status") or {})).get("project_runtime_status") or "")
        ledger = dict(project_status.get("project_progress_ledger") or {})
        return int(ledger.get("committed_metric_total") or 0) >= int(ledger.get("target_metric_total") or target) and runtime_status == "completed"

    def log(self, event_type: str, payload: dict[str, Any]) -> None:
        event = {
            "event_type": event_type,
            "created_at": time.time(),
            "payload": payload,
            "authority": "scripts.supervise_writing_campaign",
        }
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        if not self.args.quiet:
            print(json.dumps(event, ensure_ascii=False), flush=True)

    def write_state(self, payload: dict[str, Any]) -> None:
        state = {
            "updated_at": time.time(),
            "session_id": self.session_id,
            "project_id": self.project_id,
            "task_run_id": self.task_run_id,
            "coordination_run_id": self.coordination_run_id,
            "payload": payload,
            "log_path": str(self.log_path),
            "authority": "scripts.supervise_writing_campaign.state",
        }
        self._atomic_write_json(self.state_path, state)
        self.write_active_supervision("running", "state_updated")

    def write_active_supervision(self, status: str, reason: str) -> None:
        SUPERVISION_ROOT.mkdir(parents=True, exist_ok=True)
        payload = {
            "enabled": status not in {"completed", "stopped"},
            "status": status,
            "reason": reason,
            "updated_at": time.time(),
            "session_id": self.session_id,
            "project_id": self.project_id,
            "project_title": self.args.project_title,
            "metric_label": "words",
            "target_metric_total": self.args.target_words,
            "target_words": self.args.target_words,
            "state_path": str(self.state_path),
            "log_path": str(self.log_path),
            "stop_flag": str(STOP_SUPERVISION_FLAG),
            "authority": "scripts.supervise_writing_campaign.active_marker",
        }
        self._atomic_write_json(ACTIVE_SUPERVISION_PATH, payload)

    def _atomic_write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        serialized = json.dumps(payload, ensure_ascii=False, indent=2)
        last_error: Exception | None = None
        for attempt in range(6):
            tmp = path.with_name(f"{path.stem}.{os.getpid()}.{int(time.time() * 1000)}.{attempt}.{random.randint(1000, 9999)}.tmp")
            try:
                tmp.write_text(serialized, encoding="utf-8")
                os.replace(tmp, path)
                return
            except PermissionError as exc:
                last_error = exc
                time.sleep(0.2 * (attempt + 1))
                try:
                    if tmp.exists():
                        tmp.unlink()
                except OSError:
                    pass
            except OSError as exc:
                last_error = exc
                time.sleep(0.2 * (attempt + 1))
                try:
                    if tmp.exists():
                        tmp.unlink()
                except OSError:
                    pass
        if last_error is not None:
            try:
                path.write_text(serialized, encoding="utf-8")
                return
            except Exception as fallback_error:
                raise SupervisorError(f"Failed to write {path}: {fallback_error}") from fallback_error


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Persistent supervisor for the simple novel writing campaign.")
    parser.add_argument("--base-url", default=os.environ.get("WRITING_SUPERVISOR_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--graph-id", default=GRAPH_ID)
    parser.add_argument("--session-id", default=f"writing-simple-novel-honghuang-supervised-{time.strftime('%Y%m%d-%H%M%S')}")
    parser.add_argument("--task-id", default="task.writing.simple_novel.formal_million_word_run")
    parser.add_argument("--project-id", default=DEFAULT_PROJECT_ID)
    parser.add_argument("--project-title", default=DEFAULT_PROJECT_TITLE)
    parser.add_argument("--project-brief-file", default=str(DEFAULT_BRIEF_PATH))
    parser.add_argument("--artifact-root", default="")
    parser.add_argument("--target-words", type=int, default=DEFAULT_TARGET_WORDS)
    parser.add_argument("--chapter-target-words", type=int, default=DEFAULT_CHAPTER_TARGET_WORDS)
    parser.add_argument("--chapters-per-round", type=int, default=DEFAULT_CHAPTERS_PER_ROUND)
    parser.add_argument("--task-run-id", default="")
    parser.add_argument("--coordination-run-id", default="")
    parser.add_argument("--interval", type=float, default=8.0)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--stall-seconds", type=int, default=180)
    parser.add_argument("--running-child-stall-seconds", type=int, default=300)
    parser.add_argument("--max-repairs-per-reason", type=int, default=5)
    parser.add_argument("--max-iterations", type=int, default=0)
    parser.add_argument("--start", action="store_true")
    parser.add_argument("--allow-default-brief", action="store_true", default=True)
    parser.add_argument("--require-project-brief-file", dest="allow_default_brief", action="store_false")
    parser.add_argument("--fail-on-api-error", action="store_true")
    parser.add_argument("--stop-on-structural-fault", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    supervisor = WritingCampaignSupervisor(args)
    return supervisor.run()


if __name__ == "__main__":
    raise SystemExit(main())
