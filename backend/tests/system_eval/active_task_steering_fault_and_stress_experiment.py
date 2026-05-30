from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any


BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from harness.loop.task_contract_revision import ensure_revision_for_steer
from harness.loop.task_executor import append_user_work_instruction
from harness.loop.task_lifecycle import TaskLifecycleRecord, TaskRunContract
from query.models import QueryRequest
from runtime.shared.models import TaskRun
from tests.support.runtime_stubs import build_query_runtime


def _action_request(
    *,
    request_id: str = "",
    action_type: str,
    final_answer: str = "",
    blocking_reason: str = "",
    public_progress_note: str = "",
    task_contract_seed: dict[str, Any] | None = None,
    diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "authority": "harness.loop.model_action_request",
        **({"request_id": request_id} if request_id else {}),
        "turn_id": "",
        "action_type": action_type,
        "public_progress_note": public_progress_note,
        "final_answer": final_answer,
        "blocking_reason": blocking_reason,
        "task_contract_seed": dict(task_contract_seed or {}),
        "completion_contract": {},
        "permission_request": {},
        "diagnostics": dict(diagnostics or {}),
    }


class SequenceModelRuntime:
    def __init__(self, task_actions: list[dict[str, Any]]) -> None:
        self.task_actions = list(task_actions)
        self.task_invocation_count = 0
        self.calls: list[dict[str, Any]] = []

    async def invoke_messages(self, messages: Any, **kwargs: Any) -> Any:
        accounting = dict(kwargs.get("accounting_context") or {})
        source = str(accounting.get("source") or "")
        self.calls.append({"source": source, "message_text": json.dumps(messages, ensure_ascii=False, default=str)[:4000]})
        if source == "harness.loop.task_executor.model_action":
            index = min(self.task_invocation_count, max(len(self.task_actions) - 1, 0))
            self.task_invocation_count += 1
            return SimpleNamespace(content=json.dumps(dict(self.task_actions[index]), ensure_ascii=False))
        return SimpleNamespace(
            content=json.dumps(
                _action_request(
                    action_type="request_task_run",
                    task_contract_seed={
                        "user_visible_goal": "执行 ActiveTaskSteer 系统实验。",
                        "task_run_goal": "执行 ActiveTaskSteer 系统实验。",
                        "completion_criteria": ["实验链路必须可观测"],
                    },
                ),
                ensure_ascii=False,
            )
        )


class LateSteerStressModelRuntime:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.task_invocation_count = 0
        self.calls: list[dict[str, Any]] = []

    async def invoke_messages(self, messages: Any, **kwargs: Any) -> Any:
        accounting = dict(kwargs.get("accounting_context") or {})
        source = str(accounting.get("source") or "")
        message_text = json.dumps(messages, ensure_ascii=False, default=str)
        self.calls.append({"source": source, "message_text": message_text[:4000]})
        if source == "harness.loop.task_executor.model_action":
            self.task_invocation_count += 1
            if self.task_invocation_count == 1:
                self.started.set()
                await asyncio.wait_for(self.release.wait(), timeout=10)
                return SimpleNamespace(
                    content=json.dumps(
                        _action_request(action_type="respond", final_answer="我忽略了模型等待期间追加的要求，尝试直接完成。"),
                        ensure_ascii=False,
                    )
                )
            return SimpleNamespace(
                content=json.dumps(
                    _action_request(
                        action_type="block",
                        blocking_reason="压力实验在确认补充要求进入下一包后停止。",
                        public_progress_note="实验边界停止。",
                    ),
                    ensure_ascii=False,
                )
            )
        return SimpleNamespace(content=json.dumps(_action_request(action_type="respond", final_answer="unused"), ensure_ascii=False))


def _seed_task(runtime: Any, *, task_run_id: str, session_id: str, status: str = "waiting_executor") -> str:
    host = runtime.single_agent_runtime_host
    contract = TaskRunContract(
        contract_id=f"task-contract:{task_run_id.replace(':', '-')}",
        contract_source="system_eval",
        user_visible_goal="验证运行中用户补充要求不会丢失。",
        task_run_goal="验证 ActiveTaskSteer 注入、消费、完成门禁和监控投影。",
        completion_criteria=("用户补充要求必须被显式处理后才允许完成",),
    )
    contract_ref = host.runtime_objects.put_object("task_run_contract", contract.contract_id, contract.to_dict())
    lifecycle = TaskLifecycleRecord(
        task_run_id=task_run_id,
        contract_ref=contract_ref,
        status=status,
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
            status=status,
            terminal_reason="waiting_executor" if status == "waiting_executor" else "",
            created_at=time.time(),
            updated_at=time.time(),
            diagnostics={"contract": contract.to_dict(), "latest_step_summary": "系统实验任务已就绪。"},
        )
    )
    return task_run_id


async def _collect_stream(runtime: Any, request: QueryRequest) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    async for event in runtime.astream(request):
        events.append(dict(event))
    return events


def _trace(host: Any, task_run_id: str) -> dict[str, Any]:
    return host.get_trace(task_run_id, include_payloads=True, include_model_messages=True)


def _event_types(trace: dict[str, Any] | None) -> list[str]:
    return [str(dict(item).get("event_type") or "") for item in list(dict(trace or {}).get("events") or [])]


def _packet_ids(trace: dict[str, Any] | None) -> list[str]:
    result: list[str] = []
    for event in list(dict(trace or {}).get("events") or []):
        packet = dict(dict(dict(event).get("payload") or {}).get("packet") or {})
        packet_id = str(packet.get("packet_id") or "")
        if packet_id:
            result.append(packet_id)
    return result


def _action_request_ids(trace: dict[str, Any] | None) -> list[str]:
    result: list[str] = []
    for event in list(dict(trace or {}).get("events") or []):
        request = dict(dict(dict(event).get("payload") or {}).get("model_action_request") or {})
        request_id = str(request.get("request_id") or "")
        if request_id:
            result.append(request_id)
    return result


def _packet_text(trace: dict[str, Any] | None) -> str:
    packets: list[dict[str, Any]] = []
    for event in list(dict(trace or {}).get("events") or []):
        if str(dict(event).get("event_type") or "") != "runtime_invocation_packet_compiled":
            continue
        packet = dict(dict(dict(event).get("payload") or {}).get("packet") or {})
        if packet:
            packets.append(packet)
    return json.dumps(packets, ensure_ascii=False, default=str)


def _assert_unique(values: list[str], label: str) -> None:
    duplicates = sorted({value for value in values if values.count(value) > 1})
    if duplicates:
        raise AssertionError(f"duplicate {label}: {duplicates}")


async def _case_wrong_consumed_ref() -> dict[str, Any]:
    model = SequenceModelRuntime(
        [
            _action_request(
                action_type="respond",
                final_answer="错误声明已处理用户补充要求。",
                diagnostics={"consumed_steer_refs": ["steer:missing"]},
            ),
            _action_request(action_type="block", blocking_reason="实验边界停止。"),
        ]
    )
    runtime = build_query_runtime(model_runtime=model)
    host = runtime.single_agent_runtime_host
    task_run_id = _seed_task(runtime, task_run_id=f"taskrun:fault-wrong-consumed-{uuid.uuid4().hex[:6]}", session_id="session-fault-wrong-consumed")
    steer = append_user_work_instruction(host, task_run_id, content="必须真实处理这条补充要求，不能伪造 consumed ref。", turn_id="turn:fault:1")["steer"]

    result = await runtime.execute_task_run(task_run_id, max_steps=2)
    trace = _trace(host, task_run_id)
    event_types = _event_types(trace)
    monitor = host.get_task_run_live_monitor(task_run_id)

    if "task_completion_repair_required" not in event_types:
        raise AssertionError("wrong consumed_steer_refs did not trigger completion repair")
    if "active_task_steer_consumed" in event_types:
        raise AssertionError("nonexistent consumed_steer_refs consumed a valid steer")
    if int(dict(monitor or {}).get("pending_user_steer_count") or 0) < 1:
        raise AssertionError("valid steer was not left pending after wrong consumed ref")
    return {
        "case": "wrong_consumed_ref",
        "passed": True,
        "task_run_id": task_run_id,
        "result": result,
        "steer_id": str(dict(steer).get("steer_id") or ""),
        "event_types": event_types,
        "monitor": monitor,
        "trace": trace,
    }


async def _case_active_revision_blocks_completion() -> dict[str, Any]:
    model = SequenceModelRuntime(
        [
            _action_request(action_type="respond", final_answer="我只消费 steer，但不裁决 contract revision。"),
            _action_request(action_type="block", blocking_reason="实验边界停止。"),
        ]
    )
    runtime = build_query_runtime(model_runtime=model)
    host = runtime.single_agent_runtime_host
    task_run_id = _seed_task(runtime, task_run_id=f"taskrun:fault-active-revision-{uuid.uuid4().hex[:6]}", session_id="session-fault-active-revision")
    steer = append_user_work_instruction(host, task_run_id, content="把验收标准改成必须检查完成门禁。", turn_id="turn:fault:2")["steer"]
    steer_id = str(dict(steer).get("steer_id") or "")
    revision = ensure_revision_for_steer(host, task_run_id, dict(steer))
    model.task_actions[0]["diagnostics"] = {"consumed_steer_refs": [steer_id]}

    result = await runtime.execute_task_run(task_run_id, max_steps=2)
    trace = _trace(host, task_run_id)
    event_types = _event_types(trace)
    monitor = host.get_task_run_live_monitor(task_run_id)

    if "active_task_steer_consumed" not in event_types:
        raise AssertionError("steer was not consumed before active revision gate")
    if "task_completion_repair_required" not in event_types:
        raise AssertionError("active contract revision did not block completion")
    if int(dict(monitor or {}).get("active_contract_revision_count") or 0) < 1:
        raise AssertionError("monitor did not expose active contract revision")
    return {
        "case": "active_revision_blocks_completion",
        "passed": True,
        "task_run_id": task_run_id,
        "result": result,
        "steer_id": steer_id,
        "revision_id": str(dict(revision or {}).get("revision_id") or ""),
        "event_types": event_types,
        "monitor": monitor,
        "trace": trace,
    }


async def _case_duplicate_executor_guard() -> dict[str, Any]:
    runtime = build_query_runtime(model_runtime=SequenceModelRuntime([_action_request(action_type="respond", final_answer="unused")]))
    host = runtime.single_agent_runtime_host
    task_run_id = _seed_task(runtime, task_run_id=f"taskrun:fault-duplicate-{uuid.uuid4().hex[:6]}", session_id="session-fault-duplicate", status="running")
    task_run = host.state_index.get_task_run(task_run_id)
    host.state_index.upsert_task_run(replace(task_run, diagnostics={**dict(task_run.diagnostics or {}), "executor_status": "running", "executor_epoch": 1}))

    result = await runtime.execute_task_run(task_run_id, max_steps=1)
    trace = _trace(host, task_run_id)
    event_types = _event_types(trace)

    if result.get("error") != "task_run_executor_already_running":
        raise AssertionError(f"duplicate executor was not rejected: {result}")
    if "runtime_invocation_packet_compiled" in event_types:
        raise AssertionError("duplicate executor compiled a packet")
    return {"case": "duplicate_executor_guard", "passed": True, "task_run_id": task_run_id, "result": result, "event_types": event_types, "trace": trace}


async def _case_resume_monotonic_ids() -> dict[str, Any]:
    model = SequenceModelRuntime(
        [
            {"authority": "harness.loop.model_action_request", "request_id": "bad", "turn_id": "", "action_type": ""},
            {"authority": "harness.loop.model_action_request", "request_id": "bad2", "turn_id": "", "action_type": ""},
        ]
    )
    runtime = build_query_runtime(model_runtime=model)
    host = runtime.single_agent_runtime_host
    task_run_id = _seed_task(runtime, task_run_id=f"taskrun:fault-monotonic-{uuid.uuid4().hex[:6]}", session_id="session-fault-monotonic")

    first = await runtime.execute_task_run(task_run_id, max_steps=1)
    second = await runtime.execute_task_run(task_run_id, max_steps=1)
    trace = _trace(host, task_run_id)
    packet_ids = _packet_ids(trace)
    action_ids = _action_request_ids(trace)
    _assert_unique(packet_ids, "packet_id")
    _assert_unique(action_ids, "action_request_id")
    if len(packet_ids) < 2 or packet_ids[0] == packet_ids[-1]:
        raise AssertionError(f"resume did not produce distinct packets: {packet_ids}")
    return {
        "case": "resume_monotonic_ids",
        "passed": True,
        "task_run_id": task_run_id,
        "first": first,
        "second": second,
        "packet_ids": packet_ids,
        "action_request_ids": action_ids,
        "event_types": _event_types(trace),
        "trace": trace,
    }


async def _case_monitor_reconnect_snapshot() -> dict[str, Any]:
    runtime = build_query_runtime(model_runtime=SequenceModelRuntime([_action_request(action_type="respond", final_answer="unused")]))
    host = runtime.single_agent_runtime_host
    task_run_id = _seed_task(runtime, task_run_id=f"taskrun:fault-monitor-{uuid.uuid4().hex[:6]}", session_id="session-fault-monitor", status="running")
    task_run = host.state_index.get_task_run(task_run_id)
    host.state_index.upsert_task_run(replace(task_run, diagnostics={**dict(task_run.diagnostics or {}), "executor_status": "running", "executor_epoch": 1}))
    append_user_work_instruction(host, task_run_id, content="监控重连后仍应看到 pending steer。", turn_id="turn:fault:monitor")

    first = host.get_task_run_live_monitor(task_run_id)
    global_first = host.list_global_live_monitor(limit=10)
    second = host.get_task_run_live_monitor(task_run_id)
    global_second = host.list_global_live_monitor(limit=10)
    duplicate_result = await runtime.execute_task_run(task_run_id, max_steps=1)

    if int(dict(first or {}).get("pending_user_steer_count") or 0) < 1:
        raise AssertionError("first monitor snapshot missed pending steer")
    if dict(first or {}).get("pending_user_steer_count") != dict(second or {}).get("pending_user_steer_count"):
        raise AssertionError("monitor reconnect snapshot changed pending steer count without runtime progress")
    if duplicate_result.get("error") != "task_run_executor_already_running":
        raise AssertionError("monitor reconnect scenario did not preserve duplicate executor guard")
    return {
        "case": "monitor_reconnect_snapshot",
        "passed": True,
        "task_run_id": task_run_id,
        "first_monitor": first,
        "second_monitor": second,
        "global_first_summary": dict(global_first.get("summary") or {}),
        "global_second_summary": dict(global_second.get("summary") or {}),
        "duplicate_result": duplicate_result,
        "trace": _trace(host, task_run_id),
    }


async def _late_steer_iteration(index: int) -> dict[str, Any]:
    model = LateSteerStressModelRuntime()
    runtime = build_query_runtime(model_runtime=model)
    host = runtime.single_agent_runtime_host
    task_run_id = _seed_task(
        runtime,
        task_run_id=f"taskrun:stress-late-steer-{index:02d}-{uuid.uuid4().hex[:6]}",
        session_id=f"session-stress-late-steer-{index:02d}",
    )

    executor_task = asyncio.create_task(runtime.execute_task_run(task_run_id, max_steps=2))
    await asyncio.wait_for(model.started.wait(), timeout=10)
    steer_content = f"第 {index} 轮 late steer：模型等待期间追加的要求也必须进入下一次执行上下文。"
    append_user_work_instruction(host, task_run_id, content=steer_content, turn_id=f"turn:stress:{index}")
    pre_release_monitor = host.get_task_run_live_monitor(task_run_id)
    model.release.set()
    result = await asyncio.wait_for(executor_task, timeout=20)
    trace = _trace(host, task_run_id)
    event_types = _event_types(trace)
    packet_text = _packet_text(trace)
    task_run = host.state_index.get_task_run(task_run_id)

    if "task_completion_repair_required" not in event_types:
        raise AssertionError(f"iteration {index}: late steer did not trigger repair gate")
    repair_index = event_types.index("task_completion_repair_required")
    included_after_repair = any(
        event_type == "active_task_steer_included" and event_index > repair_index
        for event_index, event_type in enumerate(event_types)
    )
    if not included_after_repair:
        raise AssertionError(f"iteration {index}: late steer was not included after repair")
    if steer_content not in packet_text:
        raise AssertionError(f"iteration {index}: steer content missing from packet text")
    if task_run is not None and str(task_run.status or "") == "completed":
        raise AssertionError(f"iteration {index}: task completed with pending late steer")
    packet_ids = _packet_ids(trace)
    action_ids = _action_request_ids(trace)
    _assert_unique(packet_ids, "packet_id")
    _assert_unique(action_ids, "action_request_id")
    return {
        "iteration": index,
        "passed": True,
        "task_run_id": task_run_id,
        "result": result,
        "pre_release_pending_user_steer_count": int(dict(pre_release_monitor or {}).get("pending_user_steer_count") or 0),
        "event_types": event_types,
        "packet_ids": packet_ids,
        "action_request_ids": action_ids,
        "model_task_invocation_count": model.task_invocation_count,
        "trace": trace,
    }


async def _run_experiment(output_root: Path, *, stress_iterations: int) -> dict[str, Any]:
    run_id = f"active-task-steering-fault-stress-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    output_dir = output_root / run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    fault_cases = [
        await _case_wrong_consumed_ref(),
        await _case_active_revision_blocks_completion(),
        await _case_duplicate_executor_guard(),
        await _case_resume_monotonic_ids(),
        await _case_monitor_reconnect_snapshot(),
    ]
    stress_cases = [await _late_steer_iteration(index) for index in range(1, stress_iterations + 1)]
    aggregate_packet_ids = [packet_id for case in [*fault_cases, *stress_cases] for packet_id in list(case.get("packet_ids") or _packet_ids(case.get("trace")))]
    aggregate_action_ids = [action_id for case in [*fault_cases, *stress_cases] for action_id in list(case.get("action_request_ids") or _action_request_ids(case.get("trace")))]
    _assert_unique(aggregate_packet_ids, "aggregate packet_id")
    _assert_unique(aggregate_action_ids, "aggregate action_request_id")

    report = {
        "experiment": "active_task_steering_fault_and_stress",
        "run_id": run_id,
        "output_dir": str(output_dir),
        "stress_iterations": stress_iterations,
        "fault_case_count": len(fault_cases),
        "stress_case_count": len(stress_cases),
        "assertions": {
            "wrong_consumed_ref_fails_closed": True,
            "active_revision_blocks_completion": True,
            "duplicate_executor_rejected_before_packet": True,
            "resume_packet_ids_monotonic_unique": True,
            "monitor_reconnect_snapshot_stable": True,
            "late_steer_stress_no_duplicate_ids": True,
            "late_steer_stress_no_completion_with_pending": True,
        },
        "summary": {
            "aggregate_packet_id_count": len(aggregate_packet_ids),
            "aggregate_action_request_id_count": len(aggregate_action_ids),
            "duplicate_packet_id_count": 0,
            "duplicate_action_request_id_count": 0,
            "missing_steer_packet_count": 0,
            "completed_with_pending_count": 0,
        },
        "fault_cases": [_case_summary(case) for case in fault_cases],
        "stress_cases": [_case_summary(case) for case in stress_cases],
    }

    for case in fault_cases:
        case_dir = output_dir / "fault_cases" / str(case["case"])
        case_dir.mkdir(parents=True, exist_ok=True)
        _write_json(case_dir / "case_result.json", case)
        _write_json(case_dir / "trace.json", case.get("trace") or {})
    for case in stress_cases:
        case_dir = output_dir / "stress_cases" / f"iteration-{int(case['iteration']):02d}"
        case_dir.mkdir(parents=True, exist_ok=True)
        _write_json(case_dir / "case_result.json", case)
        _write_json(case_dir / "trace.json", case.get("trace") or {})
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
            "iteration",
            "passed",
            "task_run_id",
            "result",
            "packet_ids",
            "action_request_ids",
            "model_task_invocation_count",
            "pre_release_pending_user_steer_count",
        }
    }


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _write_markdown_report(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Active Task Steering Fault And Stress Experiment",
        "",
        f"- run_id: `{report['run_id']}`",
        f"- passed: `True`",
        f"- fault_case_count: `{report['fault_case_count']}`",
        f"- stress_case_count: `{report['stress_case_count']}`",
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
        "## Fault Cases",
        "",
        "```json",
        json.dumps(report["fault_cases"], ensure_ascii=False, indent=2, default=str),
        "```",
        "",
        "## Stress Cases",
        "",
        "```json",
        json.dumps(report["stress_cases"], ensure_ascii=False, indent=2, default=str),
        "```",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", default=str(PROJECT_ROOT / "output" / "test_runs"))
    parser.add_argument("--stress-iterations", type=int, default=8)
    args = parser.parse_args()
    try:
        report = asyncio.run(_run_experiment(Path(args.output_root), stress_iterations=max(1, int(args.stress_iterations))))
    except Exception as exc:
        print(f"EXPERIMENT FAILED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"passed": True, "run_result": report["output_dir"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
