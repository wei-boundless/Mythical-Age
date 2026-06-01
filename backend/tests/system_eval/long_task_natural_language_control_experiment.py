from __future__ import annotations

import argparse
import asyncio
import json
import re
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

from harness.entrypoint.models import HarnessRuntimeRequest
from tests.support.runtime_stubs import build_harness_runtime


def _action_request(
    *,
    action_type: str,
    final_answer: str = "",
    blocking_reason: str = "",
    public_progress_note: str = "",
    task_contract_seed: dict[str, Any] | None = None,
    diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "authority": "harness.loop.model_action_request",
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


class LongTaskNaturalLanguageModelRuntime:
    def __init__(self) -> None:
        self.active_work_decisions: list[dict[str, Any]] = [
            {
                "authority": "harness.loop.active_work_turn_decision",
                "action": "pause_active_work",
                "response": "好，我先停在这里。后面你说继续，我会从这里接着做。",
                "confidence": 0.98,
            },
            {
                "authority": "harness.loop.active_work_turn_decision",
                "action": "continue_active_work",
                "response": "好，我接着处理。",
                "confidence": 0.98,
            },
            {
                "authority": "harness.loop.active_work_turn_decision",
                "action": "append_instruction_to_active_work",
                "response": "收到，我会按这个补充方向继续处理。",
                "appended_instruction": "先不要继续做视觉资源，改为优先修复任务执行稳定性和可恢复性。",
                "confidence": 0.98,
            },
            {
                "authority": "harness.loop.active_work_turn_decision",
                "action": "pause_active_work",
                "response": "好，我先停在这里。后面你说继续，我会从这里接着做。",
                "confidence": 0.98,
            },
            {
                "authority": "harness.loop.active_work_turn_decision",
                "action": "append_instruction_to_active_work",
                "response": "收到，我会按这个补充方向继续处理。",
                "appended_instruction": "推翻上一轮方向：不要再以视觉资源为主，改成系统级验证；完成前必须说明如何保证暂停恢复、补充意见、目标推翻都被处理。",
                "confidence": 0.99,
            },
            {
                "authority": "harness.loop.active_work_turn_decision",
                "action": "answer_about_active_work",
                "response": "",
                "confidence": 0.95,
            },
        ]
        self.task_invocation_count = 0
        self.active_work_decision_count = 0
        self.calls: list[dict[str, Any]] = []
        self.started: dict[int, asyncio.Event] = {}
        self.release: dict[int, asyncio.Event] = {}

    def started_event(self, invocation: int) -> asyncio.Event:
        return self.started.setdefault(invocation, asyncio.Event())

    def release_event(self, invocation: int) -> asyncio.Event:
        return self.release.setdefault(invocation, asyncio.Event())

    async def invoke_messages(self, messages: Any, **kwargs: Any) -> Any:
        accounting = dict(kwargs.get("accounting_context") or {})
        source = str(accounting.get("source") or "")
        message_text = json.dumps(messages, ensure_ascii=False, default=str)
        self.calls.append({"source": source, "message_text": message_text[:6000]})
        if source == "harness.loop.active_work_turn_decision" or "harness.loop.active_work_turn_decision.input" in message_text:
            self.active_work_decision_count += 1
            decision = self.active_work_decisions.pop(0) if self.active_work_decisions else {
                "authority": "harness.loop.active_work_turn_decision",
                "action": "answer_about_active_work",
                "response": "",
                "confidence": 0.9,
            }
            return SimpleNamespace(content=json.dumps(decision, ensure_ascii=False))
        if source == "harness.loop.task_executor.model_action" or "task_execution" in message_text:
            self.task_invocation_count += 1
            invocation = self.task_invocation_count
            self.started_event(invocation).set()
            await asyncio.wait_for(self.release_event(invocation).wait(), timeout=15)
            return SimpleNamespace(content=json.dumps(self._task_action_for_invocation(invocation, message_text), ensure_ascii=False))
        return SimpleNamespace(
            content=json.dumps(
                _action_request(
                    action_type="request_task_run",
                    public_progress_note="建立长任务。",
                    task_contract_seed={
                        "user_visible_goal": "完成一个可长期执行、可中断、可恢复、可吸收用户改向的稳定性验证任务。",
                        "task_run_goal": "在长任务过程中处理自然语言暂停、继续、补充意见和推翻方向，并在完成前验证这些要求已被纳入。",
                        "completion_criteria": [
                            "可以被自然语言暂停并恢复",
                            "用户补充意见必须进入后续执行上下文",
                            "用户推翻方向必须被裁决并纳入完成依据",
                            "不能在有 pending steer 或 pending revision 时完成",
                        ],
                    },
                ),
                ensure_ascii=False,
            )
        )

    def _task_action_for_invocation(self, invocation: int, message_text: str) -> dict[str, Any]:
        steer_ids = _steer_ids_from_packet_text(message_text)
        revision_refs = _revision_refs_from_packet_text(message_text)
        if invocation == 1:
            return _action_request(action_type="respond", final_answer="第一段完成，准备等待用户控制。")
        if invocation == 2:
            return _action_request(action_type="respond", final_answer="恢复后继续，但暂不收口。")
        if invocation == 3:
            return _action_request(
                action_type="respond",
                final_answer="我尝试忽略补充意见直接完成，应该被门禁拦截。",
                diagnostics={"consumed_steer_refs": []},
            )
        if invocation == 4:
            return _action_request(
                action_type="respond",
                final_answer="已纳入继续请求和第一条补充意见，但仍等待后续方向确认。",
                diagnostics={
                    "consumed_steer_refs": steer_ids,
                    "contract_revision_decisions": [
                        {"steer_ref": steer_id, "status": "accepted", "reason": "补充意见改变了当前执行优先级。"}
                        for steer_id in steer_ids
                    ],
                },
            )
        if invocation >= 5:
            return _action_request(
                action_type="respond",
                final_answer="已处理推翻方向并完成长任务指引验证。",
                public_progress_note="正在收口长任务验证。",
                diagnostics={
                    "consumed_steer_refs": steer_ids,
                    "contract_revision_decisions": [
                        {
                            "steer_ref": steer_id,
                            "revision_id": revision_refs[index] if index < len(revision_refs) else "",
                            "status": "accepted",
                            "reason": "用户推翻方向作为新的目标约束，覆盖旧优先级。",
                        }
                        for index, steer_id in enumerate(steer_ids)
                    ],
                },
            )
        return _action_request(action_type="respond", final_answer="长任务指引验证完成。")


def _steer_ids_from_packet_text(message_text: str) -> list[str]:
    return _unique_refs(re.findall(r"steer:taskrun:[A-Za-z0-9:\-]+", message_text))


def _revision_refs_from_packet_text(message_text: str) -> list[str]:
    return _unique_refs(re.findall(r"taskrev:taskrun:[A-Za-z0-9:\-]+", message_text))


def _unique_refs(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        normalized = value.strip().rstrip(".;，。")
        if normalized and normalized not in result:
            result.append(normalized)
    return result


async def _collect_stream(runtime: Any, session_id: str, message: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    async for event in runtime.astream(HarnessRuntimeRequest(session_id=session_id, message=message)):
        events.append(dict(event))
    return events


async def _wait_for_invocation(model: LongTaskNaturalLanguageModelRuntime, invocation: int, *, timeout: float = 15.0) -> None:
    await asyncio.wait_for(model.started_event(invocation).wait(), timeout=timeout)


async def _wait_for_status(host: Any, task_run_id: str, status: str, *, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        task_run = host.state_index.get_task_run(task_run_id)
        if task_run is not None and str(task_run.status or "") == status:
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"timed out waiting for status {status}")


async def _wait_for_event_count(host: Any, task_run_id: str, event_type: str, *, minimum: int, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _event_types(_trace(host, task_run_id)).count(event_type) >= minimum:
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"timed out waiting for {minimum} {event_type}")


def _created_task_run_id(events: list[dict[str, Any]]) -> str:
    for event in events:
        if event.get("type") != "harness_run_started":
            continue
        task_run_id = str(dict(event.get("task_run") or {}).get("task_run_id") or "")
        if task_run_id.startswith("taskrun:"):
            return task_run_id
    return ""


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


async def _run_experiment(output_root: Path) -> dict[str, Any]:
    run_id = f"long-task-natural-language-control-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    output_dir = output_root / run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    model = LongTaskNaturalLanguageModelRuntime()
    runtime = build_harness_runtime(model_runtime=model)
    host = runtime.single_agent_runtime_host
    session_id = f"session-long-task-control-{uuid.uuid4().hex[:8]}"

    create_events = await _collect_stream(runtime, session_id, "启动一个长任务，验证自然语言暂停、继续、补充意见和推翻方向都能被稳定处理。")
    task_run_id = _created_task_run_id(create_events)
    if not task_run_id:
        raise AssertionError("long task was not created")

    try:
        await _wait_for_invocation(model, 1)
        pause_1_events = await _collect_stream(runtime, session_id, "先停一下，等我确认方向。")
        model.release_event(1).set()
        await _wait_for_status(host, task_run_id, "waiting_executor")
        paused_1_monitor = host.get_task_run_live_monitor(task_run_id)

        continue_1_events = await _collect_stream(runtime, session_id, "继续，先按原来的长任务验证方向推进。")
        await _wait_for_invocation(model, 2)
        model.release_event(2).set()
        await _wait_for_event_count(host, task_run_id, "task_completion_repair_required", minimum=1)
        await _wait_for_invocation(model, 3)

        steer_1_events = await _collect_stream(runtime, session_id, "补充意见：先不要继续做视觉资源，改为优先修复任务执行稳定性和可恢复性。")
        model.release_event(3).set()
        await _wait_for_event_count(host, task_run_id, "task_completion_repair_required", minimum=2)
        await _wait_for_invocation(model, 4)
        pause_2_events = await _collect_stream(runtime, session_id, "再暂停一下，我要推翻刚才的一部分方向。")
        model.release_event(4).set()
        await _wait_for_status(host, task_run_id, "waiting_executor")
        paused_2_monitor = host.get_task_run_live_monitor(task_run_id)

        overturn_events = await _collect_stream(
            runtime,
            session_id,
            "推翻上一轮方向：不要再以视觉资源为主，改成系统级验证；完成前必须说明如何保证暂停恢复、补充意见、目标推翻都被处理。",
        )
        await _wait_for_invocation(model, 5)
        for invocation in range(5, 9):
            model.release_event(invocation).set()
        await _wait_for_status(host, task_run_id, "completed")

        status_events = await _collect_stream(runtime, session_id, "现在这个长任务到哪了？")
    except Exception:
        _write_json(output_dir / "debug_trace.json", _trace(host, task_run_id))
        _write_json(output_dir / "debug_monitor.json", host.get_task_run_live_monitor(task_run_id))
        _write_json(output_dir / "debug_model_calls.json", model.calls)
        raise
    trace = _trace(host, task_run_id)
    event_types = _event_types(trace)
    packet_ids = _packet_ids(trace)
    action_ids = _action_request_ids(trace)
    monitor = host.get_task_run_live_monitor(task_run_id)
    session_monitor = host.get_session_live_monitor(session_id)
    global_monitor = host.list_global_live_monitor(limit=20)
    packet_text = _packet_text(trace)
    task_run = host.state_index.get_task_run(task_run_id)

    _assert_experiment(
        event_types=event_types,
        packet_text=packet_text,
        packet_ids=packet_ids,
        action_ids=action_ids,
        task_run_status=str(getattr(task_run, "status", "") or ""),
        paused_1_monitor=paused_1_monitor,
        paused_2_monitor=paused_2_monitor,
        monitor=monitor,
    )

    report = {
        "experiment": "long_task_natural_language_control",
        "run_id": run_id,
        "session_id": session_id,
        "task_run_id": task_run_id,
        "output_dir": str(output_dir),
        "model_task_invocation_count": model.task_invocation_count,
        "active_work_decision_count": model.active_work_decision_count,
        "create_stream_types": [str(item.get("type") or "") for item in create_events],
        "pause_1_stream_types": [str(item.get("type") or "") for item in pause_1_events],
        "continue_1_stream_types": [str(item.get("type") or "") for item in continue_1_events],
        "steer_1_stream_types": [str(item.get("type") or "") for item in steer_1_events],
        "pause_2_stream_types": [str(item.get("type") or "") for item in pause_2_events],
        "overturn_stream_types": [str(item.get("type") or "") for item in overturn_events],
        "status_stream_types": [str(item.get("type") or "") for item in status_events],
        "event_types": event_types,
        "packet_ids": packet_ids,
        "action_request_ids": action_ids,
        "paused_1_monitor": paused_1_monitor,
        "paused_2_monitor": paused_2_monitor,
        "monitor": monitor,
        "session_monitor": session_monitor,
        "global_monitor_summary": dict(global_monitor.get("summary") or {}),
        "assertions": {
            "long_task_created": True,
            "natural_language_pause_resume_repeated": True,
            "supplemental_instruction_recorded": True,
            "overturn_instruction_recorded": True,
            "completion_gate_failed_closed": True,
            "pending_steers_injected_into_packets": True,
            "contract_revisions_decided": True,
            "final_completion_after_new_direction": True,
            "ids_unique": True,
        },
    }

    _write_json(output_dir / "create_stream.json", create_events)
    _write_json(output_dir / "pause_1_stream.json", pause_1_events)
    _write_json(output_dir / "continue_1_stream.json", continue_1_events)
    _write_json(output_dir / "steer_1_stream.json", steer_1_events)
    _write_json(output_dir / "pause_2_stream.json", pause_2_events)
    _write_json(output_dir / "overturn_stream.json", overturn_events)
    _write_json(output_dir / "status_stream.json", status_events)
    _write_json(output_dir / "trace.json", trace)
    _write_json(output_dir / "monitor.json", monitor)
    _write_json(output_dir / "session_monitor.json", session_monitor)
    _write_json(output_dir / "global_monitor.json", global_monitor)
    _write_json(output_dir / "model_calls.json", model.calls)
    _write_json(output_dir / "run_result.json", report)
    _write_markdown_report(output_dir / "report.md", report)
    return report


def _assert_experiment(
    *,
    event_types: list[str],
    packet_text: str,
    packet_ids: list[str],
    action_ids: list[str],
    task_run_status: str,
    paused_1_monitor: dict[str, Any],
    paused_2_monitor: dict[str, Any],
    monitor: dict[str, Any],
) -> None:
    required_events = {
        "task_run_pause_requested",
        "task_run_paused",
        "task_run_resume_requested",
        "active_task_steer_recorded",
        "active_task_steer_included",
        "active_task_steer_consumed",
        "task_contract_revision_recorded",
        "task_contract_revision_decided",
        "task_completion_repair_required",
        "task_run_lifecycle_finished",
    }
    missing = sorted(required_events.difference(event_types))
    if missing:
        raise AssertionError(f"missing long-task events: {missing}")
    if event_types.count("task_run_paused") < 2:
        raise AssertionError("long task was not paused twice")
    if event_types.count("task_run_resume_requested") < 2:
        raise AssertionError("long task was not resumed twice")
    if event_types.count("active_task_steer_recorded") < 3:
        raise AssertionError("natural language guidance was not recorded as repeated active steers")
    if event_types.count("task_contract_revision_decided") < 2:
        raise AssertionError("contract revisions were not decided for changed directions")
    if "pending_user_steers" not in packet_text:
        raise AssertionError("pending_user_steers missing from runtime packets")
    if "推翻上一轮方向" not in packet_text:
        raise AssertionError("overturn instruction missing from runtime packets")
    if "系统级验证" not in packet_text:
        raise AssertionError("new direction missing from runtime packets")
    if dict(paused_1_monitor or {}).get("lifecycle") != "paused":
        raise AssertionError("first pause was not visible in monitor")
    if dict(paused_2_monitor or {}).get("lifecycle") != "paused":
        raise AssertionError("second pause was not visible in monitor")
    if task_run_status != "completed":
        raise AssertionError(f"long task did not complete after final direction: {task_run_status}")
    if dict(monitor or {}).get("status") != "completed":
        raise AssertionError("final monitor did not expose completed state")
    _assert_unique(packet_ids, "packet_id")
    _assert_unique(action_ids, "action_request_id")


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _write_markdown_report(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Long Task Natural Language Control Experiment",
        "",
        f"- run_id: `{report['run_id']}`",
        f"- session_id: `{report['session_id']}`",
        f"- task_run_id: `{report['task_run_id']}`",
        f"- passed: `True`",
        f"- model_task_invocation_count: `{report['model_task_invocation_count']}`",
        f"- active_work_decision_count: `{report['active_work_decision_count']}`",
        "",
        "## Assertions",
        "",
        "```json",
        json.dumps(report["assertions"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## Event Types",
        "",
        "```text",
        "\n".join(report["event_types"]),
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
