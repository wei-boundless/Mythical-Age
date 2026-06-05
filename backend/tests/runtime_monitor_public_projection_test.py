from __future__ import annotations

import json
from types import SimpleNamespace

from harness.runtime.runtime_monitor_public_projection import (
    PUBLIC_PROJECTION_AUTHORITY,
    project_runtime_monitor_event_public_delta,
)


class EventLogStub:
    def __init__(self, events):
        self.events = list(events)
        self.payload_store = None

    def list_recent_events(self, _run_id, *, limit=80):
        return self.events[-limit:]


class PayloadStoreStub:
    def __init__(self, payload_by_ref):
        self.payload_by_ref = dict(payload_by_ref)

    def hydrate_event_payload(self, event):
        refs = dict(event.get("refs") or {})
        payload_ref = str(refs.get("payload_ref") or dict(event.get("payload") or {}).get("payload_ref") or "")
        if payload_ref not in self.payload_by_ref:
            return event
        return {
            **dict(event),
            "payload": self.payload_by_ref[payload_ref],
            "refs": refs,
        }


def _event(**patch):
    payload = {
        "event_id": "rtevt:test",
        "run_id": "taskrun:turn:session-live:1:abc",
        "event_type": "model_action_request_received",
        "offset": 1,
        "created_at": 1.0,
        "payload": {},
        "refs": {},
        "authority": "orchestration.runtime_event",
    }
    payload.update(patch)
    return payload


def test_runtime_monitor_model_action_request_projects_public_opening_judgment() -> None:
    projection = project_runtime_monitor_event_public_delta(
        _event(
            payload={
                "model_action_request": {
                    "request_id": "act:respond",
                    "action_type": "respond",
                    "public_progress_note": "我已经确认问题在实时监控投影链路，先修后端公开 delta。",
                    "public_action_state": {
                        "current_judgment": "实时监控只发原始事件，主会话缺少公开正文。",
                    },
                },
            },
            refs={"action_request_ref": "act:respond"},
        )
    )

    assert projection["public_projection_authority"] == PUBLIC_PROJECTION_AUTHORITY
    assert projection["public_event_type"] == "model_action_admission"
    assert projection["public_anchor"] == {
        "run_id": "taskrun:turn:session-live:1:abc",
        "task_run_id": "taskrun:turn:session-live:1:abc",
        "anchor_turn_id": "turn:session-live:1",
        "anchor_role": "assistant",
    }
    assert projection["public_timeline_delta"] == [
        {
            "item_id": projection["public_timeline_delta"][0]["item_id"],
            "kind": "opening_judgment",
            "title": "开局判断",
            "text": "实时监控只发原始事件，主会话缺少公开正文。",
            "state": "running",
            "trace_refs": ["rtevt:test"],
        }
    ]


def test_runtime_monitor_admission_checked_recovers_action_request_for_public_delta() -> None:
    action_event = _event(
        event_id="rtevt:action",
        offset=1,
        payload={
            "model_action_request": {
                "request_id": "act:tool",
                "action_type": "tool_call",
                "public_progress_note": "我先读取当前前端 store 的实时事件合并逻辑。",
                "tool_call": {"name": "read_file", "args": {"path": "frontend/src/lib/store/runtime.ts"}},
            },
        },
        refs={"action_request_ref": "act:tool"},
    )
    runtime_host = SimpleNamespace(event_log=EventLogStub([action_event]))

    projection = project_runtime_monitor_event_public_delta(
        _event(
            event_id="rtevt:admission",
            event_type="model_action_admission_checked",
            offset=2,
            payload={"admission": {"decision": "allow"}},
            refs={"action_request_ref": "act:tool"},
        ),
        runtime_host=runtime_host,
    )

    assert projection["public_event_type"] == "model_action_admission"
    kinds = [item["kind"] for item in projection["public_timeline_delta"]]
    assert kinds == ["opening_judgment", "work_action"]
    assert projection["public_timeline_delta"][0]["text"] == "我先读取当前前端 store 的实时事件合并逻辑。"
    assert projection["public_timeline_delta"][1]["subject_label"] == "store/runtime.ts"


def test_runtime_monitor_task_tool_observation_projects_payload_observation_without_raw_bool() -> None:
    projection = project_runtime_monitor_event_public_delta(
        _event(
            event_id="rtevt:obs",
            event_type="task_tool_observation_recorded",
            offset=3,
            payload={
                "observation": {
                    "observation_id": "obs:path",
                    "source": "tool:path_exists",
                    "payload": {
                        "tool_name": "path_exists",
                        "tool_args": {"path": "storage/task_environments/general/workspace/calculator.html"},
                        "result": "false",
                    },
                }
            },
            refs={"observation_ref": "obs:path"},
        )
    )

    item = projection["public_timeline_delta"][0]
    visible = json.dumps(item, ensure_ascii=False).lower()
    assert item["kind"] == "work_action"
    assert item["action_kind"] == "inspect"
    assert item["state"] == "done"
    assert item["observation"] == "目标路径不存在"
    assert "false" not in visible


def test_runtime_monitor_task_tool_observation_keeps_approval_request_running() -> None:
    projection = project_runtime_monitor_event_public_delta(
        _event(
            event_id="rtevt:approval",
            event_type="task_tool_observation_recorded",
            offset=4,
            payload={
                "observation": {
                    "observation_id": "obs:approval",
                    "observation_type": "approval_request",
                    "source": "tool:write_file",
                    "payload": {
                        "tool_name": "write_file",
                        "status": "needs_approval",
                        "tool_args": {"path": "docs/plan.md"},
                        "result_envelope": {"status": "needs_approval"},
                    },
                }
            },
            refs={"observation_ref": "obs:approval"},
        )
    )

    item = projection["public_timeline_delta"][0]
    assert item["kind"] == "work_action"
    assert item["state"] == "running"
    assert item["stream_state"] == "streaming"


def test_runtime_monitor_projection_hydrates_externalized_event_payload() -> None:
    event_log = EventLogStub([])
    event_log.payload_store = PayloadStoreStub({
        "rtpayload:action": {
            "model_action_request": {
                "request_id": "act:external",
                "action_type": "respond",
                "public_progress_note": "外置 payload 已恢复，仍然可以公开投影。",
            },
        },
    })
    runtime_host = SimpleNamespace(event_log=event_log)

    projection = project_runtime_monitor_event_public_delta(
        _event(
            payload={
                "payload_externalized": True,
                "payload_ref": "rtpayload:action",
            },
            refs={"payload_ref": "rtpayload:action"},
        ),
        runtime_host=runtime_host,
    )

    assert projection["public_timeline_delta"][0]["text"] == "外置 payload 已恢复，仍然可以公开投影。"


def test_runtime_monitor_event_without_chat_anchor_does_not_emit_public_delta() -> None:
    projection = project_runtime_monitor_event_public_delta(
        _event(
            run_id="taskrun:background:abc",
            payload={
                "model_action_request": {
                    "request_id": "act:background",
                    "action_type": "respond",
                    "public_progress_note": "这条事件没有会话 turn 锚点。",
                },
            },
        )
    )

    assert projection["public_projection_authority"] == PUBLIC_PROJECTION_AUTHORITY
    assert projection["public_event_type"] == "model_action_admission"
    assert projection["public_projection_skip_reason"] == "missing_public_anchor"
    assert "public_timeline_delta" not in projection
