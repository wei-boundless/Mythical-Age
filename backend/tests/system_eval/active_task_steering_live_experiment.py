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

from query.models import QueryRequest
from tests.support.runtime_stubs import build_query_runtime


def _action_request(
    *,
    request_id: str,
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


class ActiveTaskSteeringExperimentModelRuntime:
    """Deterministic model adapter that still drives the real runtime loop."""

    def __init__(self) -> None:
        self.executor_first_invocation_started = asyncio.Event()
        self.release_first_executor_action = asyncio.Event()
        self.calls: list[dict[str, Any]] = []
        self.task_invocation_count = 0

    async def invoke_messages(self, messages: Any, **kwargs: Any) -> Any:
        message_text = json.dumps(messages, ensure_ascii=False, default=str)
        accounting = dict(kwargs.get("accounting_context") or {})
        source = str(accounting.get("source") or "")
        self.calls.append({"source": source, "message_text": message_text[:4000]})

        if source == "harness.loop.active_work_turn_decision":
            return SimpleNamespace(
                content=json.dumps(
                    {
                        "authority": "harness.loop.active_work_turn_decision",
                        "action": "append_instruction_to_active_work",
                        "response": "收到，我会按这个补充方向继续处理。",
                        "appended_instruction": _user_message_from_active_work_prompt(messages),
                        "reason": "用户仍在补充当前运行中的工作要求。",
                        "confidence": 0.98,
                    },
                    ensure_ascii=False,
                )
            )

        if source == "harness.loop.task_executor.model_action":
            self.task_invocation_count += 1
            if self.task_invocation_count == 1:
                self.executor_first_invocation_started.set()
                await asyncio.wait_for(self.release_first_executor_action.wait(), timeout=10)
                return SimpleNamespace(
                    content=json.dumps(
                        _action_request(
                            request_id="",
                            action_type="respond",
                            final_answer="我试图在没有处理用户补充要求时直接完成。",
                            public_progress_note="尝试收口。",
                            diagnostics={"experiment": "ignored_pending_steer"},
                        ),
                        ensure_ascii=False,
                    )
                )
            return SimpleNamespace(
                content=json.dumps(
                    _action_request(
                        request_id="",
                        action_type="block",
                        blocking_reason="实验已观察到完成门禁，停止继续执行。",
                        public_progress_note="停止在实验边界。",
                        diagnostics={"experiment": "stop_after_gate_observed"},
                    ),
                    ensure_ascii=False,
                )
            )

        return SimpleNamespace(
            content=json.dumps(
                _action_request(
                    request_id="model-action:experiment:request-task",
                    action_type="request_task_run",
                    public_progress_note="建立可验证任务。",
                    task_contract_seed={
                        "user_visible_goal": "验证运行中用户补充要求不会丢失。",
                        "task_run_goal": "创建一个可观测的 ActiveTaskSteer 实验任务，并验证 completion gate。",
                        "completion_criteria": [
                            "用户补充要求必须进入下一次任务执行上下文",
                            "未消费补充要求时不能完成任务",
                        ],
                    },
                    diagnostics={"experiment": "request_active_task_steering_task"},
                ),
                ensure_ascii=False,
            )
        )


def _user_message_from_active_work_prompt(messages: Any) -> str:
    try:
        payload = json.loads(str(list(messages or [])[-1].get("content") or "{}"))
    except Exception:
        return ""
    return str(payload.get("user_message") or "").strip()


async def _collect_stream(runtime: Any, request: QueryRequest) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    async for event in runtime.astream(request):
        events.append(dict(event))
    return events


async def _wait_for_event(host: Any, task_run_id: str, event_type: str, *, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if event_type in _event_types(host.get_trace(task_run_id, include_payloads=False)):
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"timed out waiting for event: {event_type}")


async def _wait_for_event_count(host: Any, task_run_id: str, event_type: str, *, minimum: int, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        event_types = _event_types(host.get_trace(task_run_id, include_payloads=False))
        if event_types.count(event_type) >= minimum:
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"timed out waiting for {minimum} events: {event_type}")


def _latest_task_run_state(host: Any, task_run_id: str) -> dict[str, Any]:
    task_run = host.state_index.get_task_run(task_run_id)
    return task_run.to_dict() if task_run is not None and hasattr(task_run, "to_dict") else {}


async def _run_experiment(output_root: Path) -> dict[str, Any]:
    run_id = f"active-task-steering-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    output_dir = output_root / run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    model = ActiveTaskSteeringExperimentModelRuntime()
    runtime = build_query_runtime(model_runtime=model)
    host = runtime.single_agent_runtime_host
    session_id = f"session-active-steering-experiment-{uuid.uuid4().hex[:8]}"

    create_events = await _collect_stream(
        runtime,
        QueryRequest(
            session_id=session_id,
            message="请启动一个可验证的长任务，用于检查运行中补充要求是否会被真实处理。",
        ),
    )
    task_run_id = _created_task_run_id(create_events)
    if not task_run_id:
        raise AssertionError("experiment did not create a single_agent_task TaskRun")

    await asyncio.wait_for(model.executor_first_invocation_started.wait(), timeout=10)

    steering_events = await _collect_stream(
        runtime,
        QueryRequest(
            session_id=session_id,
            message="不是直接完成。请先纳入这条运行中补充要求，并说明完成前要检查它。",
        ),
    )
    pre_release_monitor = host.get_task_run_live_monitor(task_run_id)

    model.release_first_executor_action.set()
    await _wait_for_event(host, task_run_id, "task_completion_repair_required", timeout=20)
    await _wait_for_event_count(host, task_run_id, "model_action_request_received", minimum=2, timeout=20)

    trace = host.get_trace(task_run_id, include_payloads=True, include_model_messages=True)
    monitor = host.get_task_run_live_monitor(task_run_id)
    global_monitor = host.list_global_live_monitor(limit=20)
    session_monitor = host.get_session_live_monitor(session_id)

    report = {
        "experiment": "active_task_steering_live",
        "run_id": run_id,
        "session_id": session_id,
        "task_run_id": task_run_id,
        "output_dir": str(output_dir),
        "create_stream_types": [str(item.get("type") or "") for item in create_events],
        "steering_stream_types": [str(item.get("type") or "") for item in steering_events],
        "executor_result": _latest_task_run_state(host, task_run_id),
        "pre_release_monitor": pre_release_monitor,
        "monitor": monitor,
        "global_monitor_summary": dict(global_monitor.get("summary") or {}),
        "session_monitor": session_monitor,
        "event_types": _event_types(trace),
        "packet_ids": _packet_ids(trace),
        "action_request_ids": _action_request_ids(trace),
        "steer_refs": _steer_refs(trace),
        "contract_revision_refs": _contract_revision_refs(trace),
        "model_task_invocation_count": model.task_invocation_count,
        "assertions": {},
        "failures": [],
    }

    _assert_experiment(report, trace=trace)

    _write_json(output_dir / "create_stream.json", create_events)
    _write_json(output_dir / "steering_stream.json", steering_events)
    _write_json(output_dir / "trace.json", trace)
    _write_json(output_dir / "monitor.json", monitor)
    _write_json(output_dir / "global_monitor.json", global_monitor)
    _write_json(output_dir / "session_monitor.json", session_monitor)
    _write_json(output_dir / "model_calls.json", model.calls)
    _write_json(output_dir / "run_result.json", report)
    _write_markdown_report(output_dir / "report.md", report)
    return report


def _created_task_run_id(events: list[dict[str, Any]]) -> str:
    for event in events:
        if event.get("type") != "harness_run_started":
            continue
        task_run_id = str(dict(event.get("task_run") or {}).get("task_run_id") or "")
        if task_run_id.startswith("taskrun:"):
            return task_run_id
    return ""


def _event_types(trace: dict[str, Any] | None) -> list[str]:
    return [str(dict(item).get("event_type") or "") for item in list(dict(trace or {}).get("events") or [])]


def _packet_ids(trace: dict[str, Any] | None) -> list[str]:
    packet_ids: list[str] = []
    for event in list(dict(trace or {}).get("events") or []):
        payload = dict(dict(event).get("payload") or {})
        packet = dict(payload.get("packet") or {})
        packet_id = str(packet.get("packet_id") or "")
        if packet_id:
            packet_ids.append(packet_id)
    return packet_ids


def _action_request_ids(trace: dict[str, Any] | None) -> list[str]:
    request_ids: list[str] = []
    for event in list(dict(trace or {}).get("events") or []):
        payload = dict(dict(event).get("payload") or {})
        request = dict(payload.get("model_action_request") or {})
        request_id = str(request.get("request_id") or "")
        if request_id:
            request_ids.append(request_id)
    return request_ids


def _steer_refs(trace: dict[str, Any] | None) -> list[str]:
    refs: list[str] = []
    for event in list(dict(trace or {}).get("events") or []):
        payload = dict(dict(event).get("payload") or {})
        steer = dict(payload.get("steer") or {})
        steer_id = str(steer.get("steer_id") or "")
        if steer_id:
            refs.append(steer_id)
    return refs


def _contract_revision_refs(trace: dict[str, Any] | None) -> list[str]:
    refs: list[str] = []
    for event in list(dict(trace or {}).get("events") or []):
        payload = dict(dict(event).get("payload") or {})
        revision = dict(payload.get("revision") or {})
        revision_id = str(revision.get("revision_id") or "")
        if revision_id:
            refs.append(revision_id)
    return refs


def _packet_text(trace: dict[str, Any] | None) -> str:
    packets: list[dict[str, Any]] = []
    for event in list(dict(trace or {}).get("events") or []):
        if str(dict(event).get("event_type") or "") != "runtime_invocation_packet_compiled":
            continue
        payload = dict(dict(event).get("payload") or {})
        packet = dict(payload.get("packet") or {})
        if packet:
            packets.append(packet)
    return json.dumps(packets, ensure_ascii=False, default=str)


def _assert_order(event_types: list[str], before: str, after: str) -> None:
    if before not in event_types or after not in event_types:
        raise AssertionError(f"missing event order pair: {before} -> {after}")
    if event_types.index(before) >= event_types.index(after):
        raise AssertionError(f"event order violated: {before} must be before {after}")


def _assert_late_steer_followup_order(event_types: list[str]) -> None:
    repair_index = event_types.index("task_completion_repair_required")
    included_after_repair = [
        index
        for index, event_type in enumerate(event_types)
        if event_type == "active_task_steer_included" and index > repair_index
    ]
    if not included_after_repair:
        raise AssertionError("late steer was not included in a follow-up packet after repair gate")
    followup_action = [
        index
        for index, event_type in enumerate(event_types)
        if event_type == "model_action_request_received" and index > included_after_repair[0]
    ]
    if not followup_action:
        raise AssertionError("no follow-up model action occurred after late steer inclusion")


def _assert_unique(values: list[str], label: str) -> None:
    duplicates = sorted({value for value in values if values.count(value) > 1})
    if duplicates:
        raise AssertionError(f"duplicate {label}: {duplicates}")


def _assert_experiment(report: dict[str, Any], *, trace: dict[str, Any] | None) -> None:
    event_types = list(report["event_types"])
    packet_text = _packet_text(trace)
    monitor = dict(report.get("monitor") or {})
    pre_release_monitor = dict(report.get("pre_release_monitor") or {})

    required_events = {
        "user_submission_recorded",
        "active_task_steer_recorded",
        "active_task_steer_included",
        "runtime_invocation_packet_compiled",
        "model_action_request_received",
        "task_completion_repair_required",
        "task_contract_revision_recorded",
        "task_run_executor_claimed",
    }
    missing = sorted(required_events.difference(event_types))
    if missing:
        raise AssertionError(f"missing required runtime events: {missing}")

    _assert_order(event_types, "user_submission_recorded", "active_task_steer_recorded")
    _assert_order(event_types, "model_action_request_received", "task_completion_repair_required")
    _assert_order(event_types, "task_completion_repair_required", "active_task_steer_included")
    _assert_late_steer_followup_order(event_types)

    if "pending_user_steers" not in packet_text:
        raise AssertionError("RuntimeInvocationPacket did not include pending_user_steers")
    if "active_contract_revisions" not in packet_text:
        raise AssertionError("RuntimeInvocationPacket did not include active_contract_revisions")
    if "不是直接完成" not in packet_text:
        raise AssertionError("RuntimeInvocationPacket did not include the user steering content")

    task_state = dict(report.get("executor_result") or {})
    if str(task_state.get("status") or "") == "completed":
        raise AssertionError("executor unexpectedly completed despite ignored pending steer")

    if int(pre_release_monitor.get("pending_user_steer_count") or 0) < 1:
        raise AssertionError("monitor did not expose pending_user_steer_count before executor release")
    if int(monitor.get("pending_user_steer_count") or 0) < 1:
        raise AssertionError("monitor lost pending_user_steer_count after repair gate")
    if int(monitor.get("active_contract_revision_count") or 0) < 1:
        raise AssertionError("monitor did not expose active contract revision after repair gate")

    _assert_unique(list(report["packet_ids"]), "packet_id")
    _assert_unique(list(report["action_request_ids"]), "action_request_id")
    if not all(":task_execution:" in packet_id for packet_id in report["packet_ids"]):
        raise AssertionError(f"unexpected packet id format: {report['packet_ids']}")
    if not any(":epoch:" in request_id and ":invocation:" in request_id for request_id in report["action_request_ids"]):
        raise AssertionError(f"missing monotonic model action id format: {report['action_request_ids']}")

    report["assertions"] = {
        "required_events_present": True,
        "event_order_valid": True,
        "packet_includes_pending_steers": True,
        "completion_gate_failed_closed": True,
        "monitor_exposes_pending_state": True,
        "ids_unique": True,
    }


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _write_markdown_report(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Active Task Steering Live Experiment",
        "",
        f"- run_id: `{report['run_id']}`",
        f"- session_id: `{report['session_id']}`",
        f"- task_run_id: `{report['task_run_id']}`",
        f"- passed: `{not report.get('failures')}`",
        "",
        "## Event Types",
        "",
        "```text",
        "\n".join(report["event_types"]),
        "```",
        "",
        "## Assertions",
        "",
        "```json",
        json.dumps(report.get("assertions") or {}, ensure_ascii=False, indent=2),
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
