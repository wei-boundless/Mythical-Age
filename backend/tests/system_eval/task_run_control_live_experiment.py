from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any


BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from harness.loop.task_checkout import checkout_task_run_for_resume
from harness.loop.task_executor import (
    request_task_run_pause,
    resume_paused_task_run,
    stop_task_run,
    task_run_control_state,
)
from harness.loop.task_lifecycle import TaskLifecycleRecord, TaskRunContract
from harness.loop.work_rollout import work_rollout_summary
from runtime.shared.models import TaskRun
from tests.support.runtime_stubs import build_harness_runtime


def _action_request(
    *,
    action_type: str,
    final_answer: str = "",
    blocking_reason: str = "",
    diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "authority": "harness.loop.model_action_request",
        "turn_id": "",
        "action_type": action_type,
        "final_answer": final_answer,
        "blocking_reason": blocking_reason,
        "task_contract_seed": {},
        "completion_contract": {},
        "permission_request": {},
        "diagnostics": dict(diagnostics or {}),
    }


class GateControlledTaskModelRuntime:
    def __init__(self, actions: list[dict[str, Any]]) -> None:
        self.actions = list(actions)
        self.task_invocation_count = 0
        self.started: dict[int, asyncio.Event] = {}
        self.release: dict[int, asyncio.Event] = {}
        self.calls: list[dict[str, Any]] = []

    def started_event(self, invocation: int) -> asyncio.Event:
        return self.started.setdefault(invocation, asyncio.Event())

    def release_event(self, invocation: int) -> asyncio.Event:
        return self.release.setdefault(invocation, asyncio.Event())

    async def invoke_messages(self, messages: Any, **kwargs: Any) -> Any:
        accounting = dict(kwargs.get("accounting_context") or {})
        source = str(accounting.get("source") or "")
        self.calls.append({"source": source, "message_text": json.dumps(messages, ensure_ascii=False, default=str)[:4000]})
        if source != "harness.loop.task_executor.model_action":
            return SimpleNamespace(content=json.dumps(_action_request(action_type="respond", final_answer="unused"), ensure_ascii=False))
        self.task_invocation_count += 1
        invocation = self.task_invocation_count
        self.started_event(invocation).set()
        await asyncio.wait_for(self.release_event(invocation).wait(), timeout=10)
        index = min(invocation - 1, max(len(self.actions) - 1, 0))
        return SimpleNamespace(content=json.dumps(dict(self.actions[index]), ensure_ascii=False))


def _seed_task(runtime: Any, *, task_run_id: str, session_id: str) -> str:
    host = runtime.single_agent_runtime_host
    contract = TaskRunContract(
        contract_id=f"task-contract:{task_run_id.replace(':', '-')}",
        contract_source="task_run_control_system_eval",
        user_visible_goal="验证 TaskRun 控制面。",
        task_run_goal="验证 TaskRun 可以在安全边界暂停、继续、停止和 checkout 恢复。",
        completion_criteria=("控制动作必须保持 TaskRun 状态一致且可观测",),
    )
    contract_ref = host.runtime_objects.put_object("task_run_contract", contract.contract_id, contract.to_dict())
    lifecycle = TaskLifecycleRecord(
        task_run_id=task_run_id,
        contract_ref=contract_ref,
        status="waiting_executor",
        created_at=time.time(),
        updated_at=time.time(),
    )
    host.runtime_objects.put_object("task_lifecycle", task_run_id, lifecycle.to_dict())
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id=task_run_id,
            session_id=session_id,
            task_id=f"task:{task_run_id}",
            task_contract_ref=contract_ref,
            agent_profile_id="main_interactive_agent",
            execution_runtime_kind="single_agent_task",
            status="waiting_executor",
            terminal_reason="waiting_executor",
            latest_checkpoint_ref=f"rtchk:{task_run_id}:seed",
            created_at=time.time(),
            updated_at=time.time(),
            diagnostics={"contract": contract.to_dict(), "latest_step_summary": "TaskRun 控制面实验任务已就绪。"},
        )
    )
    return task_run_id


def _trace(host: Any, task_run_id: str) -> dict[str, Any]:
    return host.get_trace(task_run_id, include_payloads=True, include_model_messages=True)


def _event_types(trace: dict[str, Any] | None) -> list[str]:
    return [str(dict(item).get("event_type") or "") for item in list(dict(trace or {}).get("events") or [])]


def _packet_ids(trace: dict[str, Any] | None) -> list[str]:
    packet_ids: list[str] = []
    for event in list(dict(trace or {}).get("events") or []):
        packet = dict(dict(dict(event).get("payload") or {}).get("packet") or {})
        packet_id = str(packet.get("packet_id") or "")
        if packet_id:
            packet_ids.append(packet_id)
    return packet_ids


def _action_request_ids(trace: dict[str, Any] | None) -> list[str]:
    request_ids: list[str] = []
    for event in list(dict(trace or {}).get("events") or []):
        request = dict(dict(dict(event).get("payload") or {}).get("model_action_request") or {})
        request_id = str(request.get("request_id") or "")
        if request_id:
            request_ids.append(request_id)
    return request_ids


def _assert_unique(values: list[str], label: str) -> None:
    duplicates = sorted({value for value in values if values.count(value) > 1})
    if duplicates:
        raise AssertionError(f"duplicate {label}: {duplicates}")


async def _case_pause_resume_same_task_run() -> dict[str, Any]:
    model = GateControlledTaskModelRuntime(
        [
            _action_request(action_type="respond", final_answer="这次调用会被 pause 边界拦截。"),
            _action_request(action_type="respond", final_answer="resume 后同一个 TaskRun 完成。"),
        ]
    )
    runtime = build_harness_runtime(model_runtime=model)
    host = runtime.single_agent_runtime_host
    task_run_id = _seed_task(runtime, task_run_id=f"taskrun:control-pause-resume-{uuid.uuid4().hex[:6]}", session_id="session-control-pause-resume")

    first_executor = asyncio.create_task(runtime.execute_task_run(task_run_id, max_steps=3))
    await asyncio.wait_for(model.started_event(1).wait(), timeout=10)
    pause_result = request_task_run_pause(host, task_run_id, reason="系统实验：模型调用中暂停")
    pause_requested_task = host.state_index.get_task_run(task_run_id)
    model.release_event(1).set()
    paused_result = await asyncio.wait_for(first_executor, timeout=20)
    paused_task = host.state_index.get_task_run(task_run_id)
    paused_monitor = host.get_task_run_live_monitor(task_run_id)

    if pause_result.get("ok") is not True:
        raise AssertionError(f"pause request rejected: {pause_result}")
    if task_run_control_state(pause_requested_task) != "pause_requested":
        raise AssertionError("pause request did not mark pause_requested while executor was running")
    if paused_result.get("error") != "task_run_paused":
        raise AssertionError(f"executor did not stop at pause boundary: {paused_result}")
    if paused_task is None or paused_task.status != "waiting_executor" or task_run_control_state(paused_task) != "paused":
        raise AssertionError("paused task state is not waiting_executor + paused")
    if dict(paused_monitor or {}).get("lifecycle") != "paused":
        raise AssertionError(f"monitor did not expose paused lifecycle: {paused_monitor}")

    resume_result = resume_paused_task_run(host, task_run_id, reason="系统实验：继续")
    resumed_task = host.state_index.get_task_run(task_run_id)
    if resume_result.get("ok") is not True or task_run_control_state(resumed_task) != "resume_requested":
        raise AssertionError(f"resume request did not mark resume_requested: {resume_result}")

    second_executor = asyncio.create_task(runtime.execute_task_run(task_run_id, max_steps=3))
    await asyncio.wait_for(model.started_event(2).wait(), timeout=10)
    duplicate_result = await runtime.execute_task_run(task_run_id, max_steps=1)
    model.release_event(2).set()
    completed_result = await asyncio.wait_for(second_executor, timeout=20)
    completed_task = host.state_index.get_task_run(task_run_id)
    completed_monitor = host.get_task_run_live_monitor(task_run_id)
    trace = _trace(host, task_run_id)
    event_types = _event_types(trace)
    packet_ids = _packet_ids(trace)
    action_ids = _action_request_ids(trace)
    _assert_unique(packet_ids, "pause/resume packet_id")
    _assert_unique(action_ids, "pause/resume action_request_id")

    if duplicate_result.get("error") != "task_run_executor_already_running":
        raise AssertionError(f"duplicate resume executor was not rejected: {duplicate_result}")
    if completed_result.get("ok") is not True:
        raise AssertionError(f"resumed executor did not complete: {completed_result}")
    if completed_task is None or completed_task.status != "completed":
        raise AssertionError("same TaskRun did not complete after resume")
    for required_event in ("task_run_pause_requested", "task_run_paused", "task_run_resume_requested", "task_run_executor_claimed", "task_run_lifecycle_finished"):
        if required_event not in event_types:
            raise AssertionError(f"missing event after pause/resume: {required_event}")
    return {
        "case": "pause_resume_same_task_run",
        "passed": True,
        "task_run_id": task_run_id,
        "pause_result": pause_result,
        "paused_result": paused_result,
        "resume_result": resume_result,
        "duplicate_result": duplicate_result,
        "completed_result": completed_result,
        "paused_monitor": paused_monitor,
        "completed_monitor": completed_monitor,
        "event_types": event_types,
        "packet_ids": packet_ids,
        "action_request_ids": action_ids,
        "trace": trace,
    }


async def _case_stop_checkout_resume() -> dict[str, Any]:
    model = GateControlledTaskModelRuntime(
        [
            _action_request(action_type="respond", final_answer="这次调用会被 stop 边界拦截。"),
            _action_request(action_type="respond", final_answer="checkout child 完成。"),
        ]
    )
    runtime = build_harness_runtime(model_runtime=model)
    host = runtime.single_agent_runtime_host
    source_task_run_id = _seed_task(runtime, task_run_id=f"taskrun:control-stop-checkout-{uuid.uuid4().hex[:6]}", session_id="session-control-stop-checkout")

    source_executor = asyncio.create_task(runtime.execute_task_run(source_task_run_id, max_steps=3))
    await asyncio.wait_for(model.started_event(1).wait(), timeout=10)
    stop_result = stop_task_run(host, source_task_run_id, reason="系统实验：停止并 checkout")
    stop_requested_task = host.state_index.get_task_run(source_task_run_id)
    model.release_event(1).set()
    stopped_result = await asyncio.wait_for(source_executor, timeout=20)
    source_task = host.state_index.get_task_run(source_task_run_id)
    source_monitor = host.get_task_run_live_monitor(source_task_run_id)
    source_rollout = work_rollout_summary(host, source_task_run_id)

    if stop_result.get("ok") is not True:
        raise AssertionError(f"stop request rejected: {stop_result}")
    if task_run_control_state(stop_requested_task) != "stop_requested":
        raise AssertionError("stop request did not mark stop_requested while executor was running")
    if stopped_result.get("error") != "user_aborted":
        raise AssertionError(f"executor did not stop at stop boundary: {stopped_result}")
    if source_task is None or source_task.status != "aborted" or source_task.terminal_reason != "user_aborted":
        raise AssertionError("source task did not end as user_aborted")
    if dict(source_monitor or {}).get("status") != "aborted":
        raise AssertionError(f"source monitor did not expose aborted state: {source_monitor}")

    checkout_result = checkout_task_run_for_resume(
        host,
        source_task_run_id,
        user_instruction="从停止处恢复前先检查现有结果。",
        turn_id="turn:control-checkout",
    )
    child_task = dict(checkout_result.get("task_run") or {})
    child_task_run_id = str(child_task.get("task_run_id") or "")
    if checkout_result.get("ok") is not True or not child_task_run_id:
        raise AssertionError(f"checkout resume failed: {checkout_result}")
    if not child_task_run_id.startswith(f"{source_task_run_id}:checkout:"):
        raise AssertionError(f"checkout child id does not preserve source lineage: {child_task_run_id}")

    child_executor = asyncio.create_task(runtime.execute_task_run(child_task_run_id, max_steps=3))
    await asyncio.wait_for(model.started_event(2).wait(), timeout=10)
    model.release_event(2).set()
    child_completed_result = await asyncio.wait_for(child_executor, timeout=20)
    child_after = host.state_index.get_task_run(child_task_run_id)
    child_monitor = host.get_task_run_live_monitor(child_task_run_id)
    child_rollout = work_rollout_summary(host, child_task_run_id)
    source_trace = _trace(host, source_task_run_id)
    child_trace = _trace(host, child_task_run_id)
    aggregate_packet_ids = [*_packet_ids(source_trace), *_packet_ids(child_trace)]
    aggregate_action_ids = [*_action_request_ids(source_trace), *_action_request_ids(child_trace)]
    _assert_unique(aggregate_packet_ids, "stop/checkout packet_id")
    _assert_unique(aggregate_action_ids, "stop/checkout action_request_id")

    if child_completed_result.get("ok") is not True:
        raise AssertionError(f"checkout child did not complete: {child_completed_result}")
    if child_after is None or child_after.status != "completed":
        raise AssertionError("checkout child did not reach completed")
    lineage = dict(child_task.get("diagnostics") or {}).get("lineage") or {}
    if dict(lineage).get("parent_task_run_id") != source_task_run_id:
        raise AssertionError(f"checkout lineage missing parent: {lineage}")
    if dict(child_rollout.get("lineage") or {}).get("parent_task_run_id") != source_task_run_id:
        raise AssertionError("checkout rollout did not preserve parent lineage")
    if int(dict(child_rollout.get("lineage") or {}).get("forked_from_event_offset") or -1) < 0:
        raise AssertionError("checkout rollout did not preserve a fork event offset")
    return {
        "case": "stop_checkout_resume",
        "passed": True,
        "source_task_run_id": source_task_run_id,
        "child_task_run_id": child_task_run_id,
        "stop_result": stop_result,
        "stopped_result": stopped_result,
        "checkout_result": checkout_result,
        "child_completed_result": child_completed_result,
        "source_monitor": source_monitor,
        "child_monitor": child_monitor,
        "source_rollout": source_rollout,
        "child_rollout": child_rollout,
        "source_event_types": _event_types(source_trace),
        "child_event_types": _event_types(child_trace),
        "packet_ids": aggregate_packet_ids,
        "action_request_ids": aggregate_action_ids,
        "source_trace": source_trace,
        "child_trace": child_trace,
    }


async def _run_experiment(output_root: Path) -> dict[str, Any]:
    run_id = f"task-run-control-live-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    output_dir = output_root / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    cases = [
        await _case_pause_resume_same_task_run(),
        await _case_stop_checkout_resume(),
    ]
    aggregate_packet_ids = [packet_id for case in cases for packet_id in list(case.get("packet_ids") or [])]
    aggregate_action_ids = [action_id for case in cases for action_id in list(case.get("action_request_ids") or [])]
    _assert_unique(aggregate_packet_ids, "aggregate packet_id")
    _assert_unique(aggregate_action_ids, "aggregate action_request_id")
    report = {
        "experiment": "task_run_control_live",
        "run_id": run_id,
        "output_dir": str(output_dir),
        "case_count": len(cases),
        "assertions": {
            "running_pause_reaches_safe_boundary": True,
            "paused_monitor_is_actionable": True,
            "resume_continues_same_task_run": True,
            "duplicate_resume_executor_rejected": True,
            "running_stop_reaches_user_aborted_boundary": True,
            "checkout_resume_preserves_lineage": True,
            "checkout_child_can_complete": True,
            "packet_and_action_ids_unique": True,
        },
        "summary": {
            "aggregate_packet_id_count": len(aggregate_packet_ids),
            "aggregate_action_request_id_count": len(aggregate_action_ids),
            "duplicate_packet_id_count": 0,
            "duplicate_action_request_id_count": 0,
        },
        "cases": [_case_summary(case) for case in cases],
    }
    for case in cases:
        case_dir = output_dir / "cases" / str(case["case"])
        case_dir.mkdir(parents=True, exist_ok=True)
        _write_json(case_dir / "case_result.json", case)
        for trace_key in ("trace", "source_trace", "child_trace"):
            if case.get(trace_key):
                _write_json(case_dir / f"{trace_key}.json", case[trace_key])
    _write_json(output_dir / "run_result.json", report)
    _write_markdown_report(output_dir / "report.md", report)
    return report


def _case_summary(case: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in case.items()
        if key
        in {
            "case",
            "passed",
            "task_run_id",
            "source_task_run_id",
            "child_task_run_id",
            "packet_ids",
            "action_request_ids",
            "event_types",
            "source_event_types",
            "child_event_types",
        }
    }


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _write_markdown_report(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Task Run Control Live Experiment",
        "",
        f"- run_id: `{report['run_id']}`",
        f"- passed: `True`",
        f"- case_count: `{report['case_count']}`",
        "",
        "## Assertions",
        "",
        "```json",
        json.dumps(report["assertions"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## Summary",
        "",
        "```json",
        json.dumps(report["summary"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## Cases",
        "",
        "```json",
        json.dumps(report["cases"], ensure_ascii=False, indent=2, default=str),
        "```",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", default=str(PROJECT_ROOT / "output" / "test_runs"))
    args = parser.parse_args()
    try:
        report = asyncio.run(_run_experiment(Path(args.output_root)))
    except Exception as exc:
        print(f"EXPERIMENT FAILED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"passed": True, "run_result": report["output_dir"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
