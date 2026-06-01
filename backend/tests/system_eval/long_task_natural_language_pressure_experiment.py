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
        "task_contract_seed": dict(task_contract_seed or {}),
        "completion_contract": {},
        "permission_request": {},
        "diagnostics": dict(diagnostics or {}),
    }


class PressureModelRuntime:
    def __init__(self, decisions: list[dict[str, Any]], *, premature_every: int) -> None:
        self.decisions = list(decisions)
        self.premature_every = max(2, int(premature_every))
        self.active_work_decision_count = 0
        self.task_invocation_count = 0
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
        self.calls.append({"source": source, "message_text": message_text[:8000]})
        if source == "harness.loop.active_work_turn_decision" or "harness.loop.active_work_turn_decision.input" in message_text:
            self.active_work_decision_count += 1
            if self.decisions:
                return SimpleNamespace(content=json.dumps(self.decisions.pop(0), ensure_ascii=False))
            return SimpleNamespace(
                content=json.dumps(
                    {
                        "authority": "harness.loop.active_work_turn_decision",
                        "action": "answer_about_active_work",
                        "response": "",
                        "confidence": 0.9,
                    },
                    ensure_ascii=False,
                )
            )
        if source == "harness.loop.task_executor.model_action" or "task_execution" in message_text:
            self.task_invocation_count += 1
            invocation = self.task_invocation_count
            self.started_event(invocation).set()
            if invocation == 1:
                await asyncio.wait_for(self.release_event(invocation).wait(), timeout=20)
            return SimpleNamespace(content=json.dumps(self._task_action(message_text), ensure_ascii=False))
        return SimpleNamespace(
            content=json.dumps(
                _action_request(
                    action_type="request_task_run",
                    public_progress_note="建立高压长任务。",
                    task_contract_seed={
                        "user_visible_goal": "完成高压长任务控制实验。",
                        "task_run_goal": "在多轮自然语言暂停、继续、追加、反悔、推翻和状态询问中保持任务指引稳定。",
                        "completion_criteria": [
                            "多轮自然语言控制不丢失",
                            "每条补充意见进入后续执行上下文",
                            "目标推翻必须被裁决",
                            "不能在 pending steer 或 pending revision 存在时完成",
                        ],
                    },
                ),
                ensure_ascii=False,
            )
        )

    def _task_action(self, message_text: str) -> dict[str, Any]:
        steer_ids = _unique_refs(re.findall(r"steer:taskrun:[A-Za-z0-9:\-]+", message_text))
        revision_refs = _unique_refs(re.findall(r"taskrev:taskrun:[A-Za-z0-9:\-]+", message_text))
        final_requested = "最终继续" in message_text or "最终状态如何" in message_text
        if steer_ids and self.task_invocation_count % self.premature_every == 0:
            return _action_request(
                action_type="respond",
                final_answer="压力实验：本轮故意不消费补充要求，完成门禁应拦截。",
                public_progress_note="尝试收口。",
                diagnostics={"consumed_steer_refs": []},
            )
        diagnostics = {
            "consumed_steer_refs": steer_ids,
            "contract_revision_decisions": [
                {
                    "steer_ref": steer_id,
                    "revision_id": revision_refs[index] if index < len(revision_refs) else "",
                    "status": "accepted",
                    "reason": "压力实验中用户控制指令作为当前目标约束纳入。",
                }
                for index, steer_id in enumerate(steer_ids)
            ],
        }
        if final_requested:
            return _action_request(
                action_type="respond",
                final_answer="压力实验：已按最新方向完成，并确认暂停、恢复、补充、反悔和推翻都被纳入。",
                public_progress_note="正在完成高压验证。",
                diagnostics=diagnostics,
            )
        return {
            **_action_request(
                action_type="block",
                final_answer="",
                public_progress_note="已处理当前控制指令，等待下一步。",
                diagnostics={
                    **diagnostics,
                    "recoverable_error": {
                        "error_code": "pressure_checkpoint_waiting_for_next_user_control",
                        "retryable": True,
                    },
                    "recovery_action": "resume_task_run",
                },
            ),
            "blocking_reason": "pressure_checkpoint_waiting_for_next_user_control",
        }


def _unique_refs(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        normalized = value.strip().rstrip(".;，。")
        if normalized and normalized not in result:
            result.append(normalized)
    return result


def _decision(action: str, *, instruction: str = "", response: str = "") -> dict[str, Any]:
    payload = {
        "authority": "harness.loop.active_work_turn_decision",
        "action": action,
        "response": response or _default_response(action),
        "confidence": 0.98,
    }
    if instruction:
        payload["appended_instruction"] = instruction
    return payload


def _default_response(action: str) -> str:
    if action == "pause_active_work":
        return "好，我先停在这里。后面你说继续，我会从这里接着做。"
    if action == "continue_active_work":
        return "好，我接着处理。"
    if action == "append_instruction_to_active_work":
        return "收到，我会按这个补充方向继续处理。"
    return ""


def _scenario(rounds: int) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    operations: list[dict[str, str]] = []
    decisions: list[dict[str, Any]] = []
    for index in range(2, rounds + 1):
        mod = index % 4
        if mod == 1:
            message = f"第 {index} 轮：先暂停，我要检查方向。"
            operations.append({"kind": "pause", "message": message})
            decisions.append(_decision("pause_active_work"))
        elif mod == 2:
            message = f"第 {index} 轮：继续，但保留当前已验证的暂停恢复要求。"
            operations.append({"kind": "continue", "message": message})
            decisions.append(_decision("continue_active_work"))
        elif mod == 3:
            instruction = f"第 {index} 轮补充：优先保证 executor 不重复、packet id 不重复、monitor 状态准确。"
            operations.append({"kind": "append", "message": instruction})
            decisions.append(_decision("append_instruction_to_active_work", instruction=instruction))
            follow = f"第 {index} 轮补充后继续：请立刻处理刚才补充意见。"
            operations.append({"kind": "continue_after_append", "message": follow})
            decisions.append(_decision("continue_active_work"))
        else:
            instruction = f"第 {index} 轮推翻：取消上一轮局部优先级，改成以系统级恢复稳定性为最高标准。"
            operations.append({"kind": "overturn", "message": instruction})
            decisions.append(_decision("append_instruction_to_active_work", instruction=instruction))
            follow = f"第 {index} 轮推翻后继续：按新方向推进，不要回到旧方向。"
            operations.append({"kind": "continue_after_overturn", "message": follow})
            decisions.append(_decision("continue_active_work"))
        if index % 8 == 0:
            message = f"第 {index} 轮状态询问：现在进展到哪里了？不要改任务，只说状态。"
            operations.append({"kind": "status", "message": message})
            decisions.append(_decision("answer_about_active_work"))
    operations.append({"kind": "final_continue", "message": "最终继续：按最新方向完成，并确认所有暂停、恢复、补充、推翻都被纳入。"})
    decisions.append(_decision("continue_active_work"))
    operations.append({"kind": "final_status", "message": "最终状态如何？"})
    decisions.append(_decision("answer_about_active_work"))
    return decisions, operations


async def _collect_stream(runtime: Any, session_id: str, message: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    async for event in runtime.astream(HarnessRuntimeRequest(session_id=session_id, message=message)):
        events.append(dict(event))
    return events


async def _wait_until_quiet(host: Any, task_run_id: str, *, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    last_event_count = -1
    stable_since = time.monotonic()
    while time.monotonic() < deadline:
        monitor = host.get_task_run_live_monitor(task_run_id)
        event_count = int(dict(monitor or {}).get("event_count") or 0)
        status = str(dict(monitor or {}).get("status") or "")
        if event_count != last_event_count:
            last_event_count = event_count
            stable_since = time.monotonic()
        if status in {"completed", "aborted", "failed", "blocked", "waiting_executor"} and time.monotonic() - stable_since > 0.15:
            return
        await asyncio.sleep(0.05)


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


def _count_duplicates(values: list[str]) -> int:
    return len([value for value in set(values) if values.count(value) > 1])


async def _run_experiment(output_root: Path, *, rounds: int, premature_every: int) -> dict[str, Any]:
    run_id = f"long-task-pressure-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    output_dir = output_root / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    decisions, operations = _scenario(rounds)
    decisions.insert(0, _decision("pause_active_work"))
    model = PressureModelRuntime(decisions, premature_every=premature_every)
    runtime = build_harness_runtime(model_runtime=model)
    host = runtime.single_agent_runtime_host
    session_id = f"session-long-task-pressure-{uuid.uuid4().hex[:8]}"

    streams: list[dict[str, Any]] = []
    create_events = await _collect_stream(runtime, session_id, "启动高压长任务：我要反复暂停、继续、追加、反悔、推翻方向，最后检查你是否还能按最新要求完成。")
    task_run_id = _created_task_run_id(create_events)
    if not task_run_id:
        raise AssertionError("pressure task was not created")
    streams.append({"kind": "create", "events": create_events})

    await asyncio.wait_for(model.started_event(1).wait(), timeout=15)
    first_pause_events = await _collect_stream(runtime, session_id, "第 1 轮：先暂停，我要检查方向。")
    model.release_event(1).set()
    await _wait_until_quiet(host, task_run_id)
    streams.append({"kind": "pause", "message": "第 1 轮：先暂停，我要检查方向。", "events": first_pause_events})

    try:
        for operation in operations:
            events = await _collect_stream(runtime, session_id, operation["message"])
            await _wait_until_quiet(host, task_run_id)
            streams.append({"kind": operation["kind"], "message": operation["message"], "events": events})

        trace = _trace(host, task_run_id)
        monitor = host.get_task_run_live_monitor(task_run_id)
        session_monitor = host.get_session_live_monitor(session_id)
        global_monitor = host.list_global_live_monitor(limit=20)
        event_types = _event_types(trace)
        packet_ids = _packet_ids(trace)
        action_ids = _action_request_ids(trace)
        task_run = host.state_index.get_task_run(task_run_id)
        summary = {
            "pause_request_count": event_types.count("task_run_pause_requested"),
            "paused_count": event_types.count("task_run_paused"),
            "resume_request_count": event_types.count("task_run_resume_requested"),
            "steer_recorded_count": event_types.count("active_task_steer_recorded"),
            "steer_included_count": event_types.count("active_task_steer_included"),
            "steer_consumed_count": event_types.count("active_task_steer_consumed"),
            "revision_recorded_count": event_types.count("task_contract_revision_recorded"),
            "revision_decided_count": event_types.count("task_contract_revision_decided"),
            "completion_repair_count": event_types.count("task_completion_repair_required"),
            "executor_claim_count": event_types.count("task_run_executor_claimed"),
            "packet_count": len(packet_ids),
            "action_request_count": len(action_ids),
            "duplicate_packet_id_count": _count_duplicates(packet_ids),
            "duplicate_action_request_id_count": _count_duplicates(action_ids),
            "final_status": str(getattr(task_run, "status", "") or ""),
            "final_pending_user_steer_count": int(dict(monitor or {}).get("pending_user_steer_count") or 0),
            "final_active_contract_revision_count": int(dict(monitor or {}).get("active_contract_revision_count") or 0),
        }
        _assert_pressure(summary, rounds=rounds, monitor=monitor)
    except Exception:
        _write_json(output_dir / "debug_streams.json", streams)
        _write_json(output_dir / "debug_trace.json", _trace(host, task_run_id))
        _write_json(output_dir / "debug_monitor.json", host.get_task_run_live_monitor(task_run_id))
        _write_json(output_dir / "debug_model_calls.json", model.calls)
        raise
    report = {
        "experiment": "long_task_natural_language_pressure",
        "run_id": run_id,
        "session_id": session_id,
        "task_run_id": task_run_id,
        "output_dir": str(output_dir),
        "rounds": rounds,
        "operation_count": len(operations),
        "model_task_invocation_count": model.task_invocation_count,
        "active_work_decision_count": model.active_work_decision_count,
        "summary": summary,
        "assertions": {
            "repeated_natural_language_control": True,
            "pause_resume_repeated": True,
            "steers_recorded_included_and_consumed": True,
            "revisions_recorded_and_decided": True,
            "completion_gate_failed_closed_under_pressure": True,
            "final_completion_has_no_pending_control": True,
            "ids_unique": True,
        },
    }
    _write_json(output_dir / "operations.json", operations)
    _write_json(output_dir / "streams.json", streams)
    _write_json(output_dir / "trace.json", trace)
    _write_json(output_dir / "monitor.json", monitor)
    _write_json(output_dir / "session_monitor.json", session_monitor)
    _write_json(output_dir / "global_monitor.json", global_monitor)
    _write_json(output_dir / "model_calls.json", model.calls)
    _write_json(output_dir / "run_result.json", report)
    _write_markdown_report(output_dir / "report.md", report)
    return report


def _assert_pressure(summary: dict[str, Any], *, rounds: int, monitor: dict[str, Any]) -> None:
    if int(summary["pause_request_count"]) < max(2, rounds // 6):
        raise AssertionError(f"not enough pause requests: {summary}")
    if int(summary["resume_request_count"]) < max(2, rounds // 6):
        raise AssertionError(f"not enough resume requests: {summary}")
    if int(summary["steer_recorded_count"]) < max(6, rounds // 2):
        raise AssertionError(f"not enough steers recorded: {summary}")
    if int(summary["steer_included_count"]) < int(summary["steer_recorded_count"]):
        raise AssertionError(f"some steers were not included: {summary}")
    if int(summary["steer_consumed_count"]) < int(summary["steer_recorded_count"]):
        raise AssertionError(f"some steers were not consumed: {summary}")
    if int(summary["revision_decided_count"]) < int(summary["revision_recorded_count"]):
        raise AssertionError(f"some revisions were not decided: {summary}")
    if int(summary["completion_repair_count"]) < 2:
        raise AssertionError(f"completion gate was not stressed: {summary}")
    if int(summary["duplicate_packet_id_count"]) or int(summary["duplicate_action_request_id_count"]):
        raise AssertionError(f"duplicate ids found: {summary}")
    if str(summary["final_status"]) != "completed":
        raise AssertionError(f"pressure task did not complete: {summary}")
    if int(summary["final_pending_user_steer_count"]) or int(summary["final_active_contract_revision_count"]):
        raise AssertionError(f"final monitor still has pending control state: {summary}")
    if str(dict(monitor or {}).get("status") or "") != "completed":
        raise AssertionError(f"monitor did not expose completed status: {monitor}")


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _write_markdown_report(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Long Task Natural Language Pressure Experiment",
        "",
        f"- run_id: `{report['run_id']}`",
        f"- task_run_id: `{report['task_run_id']}`",
        f"- rounds: `{report['rounds']}`",
        f"- operation_count: `{report['operation_count']}`",
        f"- passed: `True`",
        "",
        "## Summary",
        "",
        "```json",
        json.dumps(report["summary"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## Assertions",
        "",
        "```json",
        json.dumps(report["assertions"], ensure_ascii=False, indent=2),
        "```",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", default=str(PROJECT_ROOT / "output" / "test_runs"))
    parser.add_argument("--rounds", type=int, default=24)
    parser.add_argument("--premature-every", type=int, default=4)
    args = parser.parse_args()
    try:
        report = asyncio.run(
            _run_experiment(
                Path(args.output_root),
                rounds=max(6, int(args.rounds)),
                premature_every=max(2, int(args.premature_every)),
            )
        )
    except Exception as exc:
        print(f"EXPERIMENT FAILED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"passed": True, "run_result": report["output_dir"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
