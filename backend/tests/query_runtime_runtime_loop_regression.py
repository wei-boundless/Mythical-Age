from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from query.models import QueryRequest
from api.chat import _project_public_stream_event, _runtime_run_refs_from_event
from runtime.shared.models import AgentRunResult, TaskRun
from harness.loop.model_action_protocol import ModelActionRequest
from harness.loop.task_executor import _tool_call_progress_summary
from harness.loop.task_lifecycle import TaskLifecycleRecord, TaskRunContract
from tests.support.runtime_stubs import (
    NativeToolCallModelRuntimeStub,
    PrimarySettingsStub,
    SingleMessageModelRuntimeStub,
    build_query_runtime,
)
from runtime.prompt_accounting import (
    CanonicalPromptSerializer,
    ModelTokenUsageRecord,
    PromptCachePlanner,
    extract_provider_usage,
)


_VISIBLE_RUNTIME_INTERNAL_MARKERS = (
    "TaskRun",
    "runtime packet",
    "正式任务生命周期",
    "执行器",
    "agent 已返回",
    "agent 动作",
    "等待 agent",
    "回灌给 agent",
)


def _assert_no_visible_runtime_internals(text: str) -> None:
    leaked = [marker for marker in _VISIBLE_RUNTIME_INTERNAL_MARKERS if marker in text]
    assert leaked == []


def _action_request(
    *,
    action_type: str,
    final_answer: str = "",
    public_progress_note: str = "正在处理当前请求。",
    task_contract_seed: dict[str, object] | None = None,
    diagnostics: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "authority": "harness.loop.model_action_request",
        "request_id": f"model-action:test:{action_type}",
        "turn_id": "",
        "action_type": action_type,
        "public_progress_note": public_progress_note,
        "public_action_state": {
            "current_judgment": "测试动作可继续执行。",
            "next_action": public_progress_note,
        },
        "final_answer": final_answer,
        "task_contract_seed": dict(task_contract_seed or {}),
        "completion_contract": {},
        "permission_request": {},
        "diagnostics": {"test_action_request": True, **dict(diagnostics or {})},
    }


def test_conversation_only_capability_uses_plain_conversation_without_turnrun() -> None:
    runtime = build_query_runtime(
        model_runtime=SingleMessageModelRuntimeStub(content="自然对话回复。")
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            QueryRequest(
                session_id="session-plain",
                message="和我随便聊两句。",
                task_selection={"control_capabilities": {"conversation_only": True}},
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    stream_types = [str(event.get("type") or "") for event in events]
    route_events = [dict(event.get("turn_route") or {}) for event in events if event.get("type") == "turn_route_decided"]

    assert any(event.get("type") == "done" and event.get("content") == "自然对话回复。" for event in events)
    assert "runtime_assembly_compiled" in stream_types
    assert "turn_route_decided" in stream_types
    assert route_events and route_events[0].get("route_kind") == "plain_conversation"
    assert "plain_conversation_started" in stream_types
    assert "assistant_message_committed" in stream_types
    assert "runtime_invocation_packet" not in stream_types
    assert "harness_run_started" not in stream_types
    assert "model_action_request" not in stream_types
    assert not any("compilation" in event or "model_messages" in event for event in events)
    assert runtime.single_agent_runtime_host.list_session_traces("session-plain")["task_run_count"] == 0


def test_plain_conversation_receives_compressed_context_from_session_record() -> None:
    class RecordingModelRuntime(SingleMessageModelRuntimeStub):
        def __init__(self) -> None:
            super().__init__(content="自然对话回复。")
            self.last_messages: list[dict[str, object]] = []

        async def invoke_messages(self, messages, **kwargs):
            self.last_messages = [dict(item) for item in list(messages or []) if isinstance(item, dict)]
            return await super().invoke_messages(messages, **kwargs)

    model = RecordingModelRuntime()
    runtime = build_query_runtime(model_runtime=model)
    runtime.session_manager.compressed_context = "此前已经确认项目采用 DeepSeek。"

    async def _collect() -> None:
        async for _event in runtime.astream(
            QueryRequest(
                session_id="session-plain-compressed",
                message="继续。",
                task_selection={"control_capabilities": {"conversation_only": True}},
            )
        ):
            pass

    asyncio.run(_collect())
    payload = "\n".join(str(message.get("content") or "") for message in model.last_messages)

    assert "此前已经确认项目采用 DeepSeek。" in payload
    assert "[Compressed session context]" not in payload


def test_action_capable_turn_routes_to_agent_action_loop() -> None:
    runtime = build_query_runtime(
        model_runtime=SingleMessageModelRuntimeStub(
            agent_turn_action_request=_action_request(
                action_type="respond",
                final_answer="直接回答，不进入任务生命周期。",
            )
        )
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(QueryRequest(session_id="session-direct", message="介绍一下 harness。")):
            events.append(event)
        return events

    events = asyncio.run(_collect())

    assert any(event.get("type") == "done" for event in events)
    assert any(event.get("type") == "runtime_assembly_compiled" for event in events)
    route_events = [dict(event.get("turn_route") or {}) for event in events if event.get("type") == "turn_route_decided"]
    assert route_events and route_events[0].get("route_kind") == "agent_action"
    assert dict(route_events[0].get("monitor_policy") or {}).get("record_task_monitor") is False
    assert dict(route_events[0].get("monitor_policy") or {}).get("record_turn_monitor") is True
    started = [event for event in events if event.get("type") == "harness_run_started"][0]
    assert dict(started.get("turn_run") or {}).get("turn_run_id", "").startswith("turnrun:")
    assert "task_run" not in started
    traces = runtime.single_agent_runtime_host.list_session_traces("session-direct")
    assert traces["task_run_count"] == 0
    assert traces["turn_run_count"] == 1


def test_explicit_contract_task_starts_lifecycle_without_model_action_loop() -> None:
    runtime = build_query_runtime(
        model_runtime=SingleMessageModelRuntimeStub(
            agent_turn_action_request=_action_request(
                action_type="respond",
                final_answer="不应调用模型动作协议。",
            )
        )
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            QueryRequest(
                session_id="session-explicit-contract",
                message="按合同启动任务。",
                task_selection={
                    "task_environment_id": "env.development.sandbox",
                    "task_contract": {
                        "contract_id": "contract:explicit:test",
                        "user_visible_goal": "交付显式合同任务。",
                        "task_run_goal": "根据显式合同创建并执行任务。",
                        "required_artifacts": [{"artifact_kind": "html_app", "user_visible_name": "可运行页面"}],
                        "completion_criteria": ["任务生命周期必须由系统直接启动"],
                    },
                },
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    stream_types = [str(event.get("type") or "") for event in events]
    route = dict(next(event for event in events if event.get("type") == "turn_route_decided").get("turn_route") or {})
    lifecycle = [
        event
        for event in events
        if event.get("type") == "task_run_lifecycle_started"
    ][0]
    task_run_event = dict(lifecycle.get("event") or {})
    payload = dict(task_run_event.get("payload") or {})
    task_run = dict(payload.get("task_run") or {})
    task_run_id = str(task_run.get("task_run_id") or "")
    stored_task = runtime.single_agent_runtime_host.state_index.get_task_run(task_run_id)
    contract = dict(runtime.single_agent_runtime_host.runtime_objects.get_object(str(getattr(stored_task, "task_contract_ref", "") or "")) or {})

    assert route.get("route_kind") == "explicit_contract_task"
    assert route.get("invocation_kind") == "task_execution_start"
    assert "runtime_invocation_packet" not in stream_types
    assert "model_action_request" not in stream_types
    assert "model_action_admission" not in stream_types
    assert "harness_run_started" in stream_types
    assert task_run_id.startswith("taskrun:")
    assert stored_task is not None
    assert contract["contract_source"] == "explicit_contract"
    assert contract["source_contract_ref"] == "contract:explicit:test"
    assert contract["task_environment_id"] == "env.development.sandbox"
    assert dict(getattr(stored_task, "diagnostics", {}) or {}).get("origin_kind") == "explicit_contract"
    assert dict(getattr(stored_task, "diagnostics", {}) or {}).get("origin_authority") == "harness.routing.explicit_contract_task"


def test_chat_public_projection_filters_internal_runtime_payloads() -> None:
    assert _project_public_stream_event(
        "runtime_assembly_compiled",
        {"type": "runtime_assembly_compiled", "runtime_assembly": {"backend_dir": "D:/secret"}},
    ) is None
    assert _project_public_stream_event(
        "runtime_invocation_packet",
        {
            "type": "runtime_invocation_packet",
            "packet_ref": "rtpacket:test",
            "compilation": {"packet": {"model_messages": [{"role": "system", "content": "hidden"}]}},
        },
    ) is None

    projected = _project_public_stream_event(
        "turn_route_decided",
        {
            "type": "turn_route_decided",
            "turn_route": {
                "route_kind": "plain_conversation",
                "invocation_kind": "plain_conversation",
                "dispatch_target": "query_runtime.plain_conversation",
                "reason": "conversation_only_capability",
                "control_capabilities": {"may_call_tools": False},
                "diagnostics": {"backend_dir": "D:/secret"},
            },
            "runtime_assembly": {"backend_dir": "D:/secret"},
            "model_messages": [{"role": "system", "content": "hidden"}],
        },
    )

    assert projected is not None
    public_event_type, data = projected
    assert public_event_type == "turn_route_decided"
    assert "runtime_assembly" not in data
    assert "model_messages" not in data
    route = dict(data.get("turn_route") or {})
    assert route == {
        "route_kind": "plain_conversation",
        "reason": "conversation_only_capability",
    }


def test_chat_public_projection_redacts_internal_packet_fields_from_allowed_events() -> None:
    projected = _project_public_stream_event(
        "agent_turn_terminal",
        {
            "type": "agent_turn_terminal",
            "event": {
                "event_type": "agent_turn_completed",
                "payload": {
                    "status": "completed",
                    "runtime_assembly": {"backend_dir": "D:/secret"},
                    "action_request": {
                        "final_answer": "ok",
                        "model_messages": [{"role": "system", "content": "hidden"}],
                    },
                },
            },
            "compilation": {"packet": {"model_messages": [{"role": "system", "content": "hidden"}]}},
        },
    )

    assert projected is not None
    _event_type, data = projected
    serialized = json.dumps(data, ensure_ascii=False)
    assert "model_messages" not in serialized
    assert "runtime_assembly" not in serialized
    assert "compilation" not in serialized
    assert "D:/secret" not in serialized


def test_chat_stream_runtime_refs_separate_turn_run_from_task_run() -> None:
    refs = _runtime_run_refs_from_event(
        {
            "type": "agent_turn_terminal",
            "event": {
                "run_id": "turnrun:session-a:1",
                "payload": {
                    "turn_run": {"turn_run_id": "turnrun:session-a:1"},
                    "task_run": {"task_run_id": "taskrun:turn:session-a:1:formal"},
                },
            },
        }
    )

    assert refs == {
        "turn_run_id": "turnrun:session-a:1",
        "task_run_id": "taskrun:turn:session-a:1:formal",
    }


def test_chat_public_projection_hides_turn_trace_only_harness_start() -> None:
    assert _project_public_stream_event(
        "harness_run_started",
        {
            "type": "harness_run_started",
            "turn_run": {
                "turn_run_id": "turnrun:session-a:1",
                "execution_runtime_kind": "single_agent_turn",
            },
            "event": {
                "run_id": "turnrun:session-a:1",
                "payload": {
                    "turn_run": {"turn_run_id": "turnrun:session-a:1"},
                },
            },
        },
    ) is None

    projected = _project_public_stream_event(
        "harness_run_started",
        {
            "type": "harness_run_started",
            "task_run": {"task_run_id": "taskrun:session-a:1", "status": "running"},
            "event": {
                "run_id": "taskrun:session-a:1",
                "payload": {"task_run": {"task_run_id": "taskrun:session-a:1"}},
            },
        },
    )
    assert projected is not None
    public_event_type, data = projected
    assert public_event_type == "harness_run_started"
    assert dict(data.get("task_run") or {}).get("task_run_id") == "taskrun:session-a:1"


def test_agent_action_request_launches_task_run_and_initializes_todo() -> None:
    model_selection = {
        "provider": "test-provider",
        "model": "turn-bound-test-model",
        "timeout_seconds": 7,
    }
    runtime = build_query_runtime(
        model_runtime=SingleMessageModelRuntimeStub(
            agent_turn_action_request=_action_request(
                action_type="request_task_run",
                task_contract_seed={
                    "user_visible_goal": "交付一个真实可验证产物。",
                    "task_run_goal": "交付一个真实可验证产物。",
                    "required_artifacts": [{"artifact_kind": "test_artifact", "user_visible_name": "测试交付物"}],
                    "required_verifications": [{"verification_kind": "test_verification"}],
                    "completion_criteria": ["交付物和验证证据都已记录"],
                },
            )
        )
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            QueryRequest(
                session_id="session-taskrun",
                message="请交付产物。",
                model_selection=model_selection,
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())

    started = [
        event
        for event in events
        if event.get("type") == "harness_run_started"
        and str(dict(event.get("task_run") or {}).get("task_run_id") or "").startswith("taskrun:")
    ][0]
    task_run_id = str(dict(started.get("task_run") or {}).get("task_run_id") or "")
    trace = runtime.single_agent_runtime_host.get_trace(task_run_id, include_payloads=True)
    event_types = [
        str(dict(item).get("event_type") or "")
        for item in list(dict(trace or {}).get("events") or [])
    ]
    stream_types = [str(event.get("type") or "") for event in events]
    route_events = [dict(event.get("turn_route") or {}) for event in events if event.get("type") == "turn_route_decided"]

    assert "runtime_assembly_compiled" in stream_types
    assert route_events and route_events[0].get("route_kind") == "agent_action"
    assert "model_action_request" in stream_types
    assert "task_run_lifecycle_started" in stream_types
    assert "task_run_lifecycle_event" in stream_types
    assert "agent_todo_initialized" in event_types
    assert "task_run_executor_scheduled" in event_types
    done_contents = [str(event.get("content") or "") for event in events if event.get("type") == "done"]
    visible_progress = "\n".join(
        str(event.get("summary") or "")
        for event in events
        if event.get("type") == "runtime_step_summary"
    )
    assert any("我会按这个目标继续推进" in content for content in done_contents)
    assert not any("执行器" in content or "TaskRun" in content or "正式任务" in content for content in done_contents)
    _assert_no_visible_runtime_internals("\n".join(done_contents))
    _assert_no_visible_runtime_internals(visible_progress)
    task_run = runtime.single_agent_runtime_host.state_index.get_task_run(task_run_id)
    assert task_run is not None
    assert dict(task_run.diagnostics or {}).get("origin_kind") == "agent_requested"
    assert dict(dict(task_run.diagnostics or {}).get("origin") or {}).get("origin_authority") == "harness.agent_loop"
    assert dict(task_run.diagnostics or {}).get("model_selection") == model_selection
    assert dict(dict(task_run.diagnostics or {}).get("model_selection_binding") or {}).get("scope") == "task_run"
    contract = runtime.single_agent_runtime_host.runtime_objects.get_object(task_run.task_contract_ref)
    assert dict(contract or {}).get("origin", {}).get("origin_kind") == "agent_requested"


def test_global_live_monitor_groups_running_completed_and_failed_runs(monkeypatch) -> None:
    monkeypatch.setattr("harness.runtime.single_agent_host.time.time", lambda: 1000.0)
    runtime = build_query_runtime()
    host = runtime.single_agent_runtime_host
    host.state_index.upsert_task_run(TaskRun(
        task_run_id="taskrun:old-running",
        session_id="session-monitor",
        task_id="task:old",
        status="running",
        created_at=100.0,
        updated_at=200.0,
        execution_runtime_kind="single_agent_task",
    ))
    host.state_index.upsert_task_run(TaskRun(
        task_run_id="taskrun:failed-stale",
        session_id="session-monitor",
        task_id="task:failed",
        status="failed",
        created_at=800.0,
        updated_at=900.0,
        execution_runtime_kind="single_agent_task",
        terminal_reason="internal_error",
    ))
    host.state_index.upsert_task_run(TaskRun(
        task_run_id="taskrun:old-waiting-executor",
        session_id="session-monitor",
        task_id="task:old-waiting-executor",
        status="waiting_executor",
        created_at=300.0,
        updated_at=400.0,
        execution_runtime_kind="single_agent_task",
        terminal_reason="task_executor_rebuild_pending",
    ))
    host.state_index.upsert_task_run(TaskRun(
        task_run_id="taskrun:fresh-waiting-executor",
        session_id="session-monitor",
        task_id="task:fresh-waiting-executor",
        status="waiting_executor",
        created_at=940.0,
        updated_at=980.0,
        execution_runtime_kind="single_agent_task",
        terminal_reason="waiting_executor",
    ))
    host.state_index.upsert_task_run(TaskRun(
        task_run_id="taskrun:waiting-approval",
        session_id="session-monitor",
        task_id="task:waiting-approval",
        status="waiting_approval",
        created_at=300.0,
        updated_at=400.0,
        execution_runtime_kind="single_agent_task",
        terminal_reason="waiting_approval",
    ))

    monitor = host.list_global_live_monitor(limit=20)

    assert {item["task_run_id"] for item in monitor["task_runs"]} == {
        "taskrun:fresh-waiting-executor",
        "taskrun:old-waiting-executor",
        "taskrun:waiting-approval",
        "taskrun:old-running",
    }
    buckets = {item["task_run_id"]: item["bucket"] for item in monitor["task_runs"]}
    assert {item["task_run_id"] for item in monitor["buckets"]["running"]} == {
        "taskrun:fresh-waiting-executor",
    }
    assert {item["task_run_id"] for item in monitor["buckets"]["diagnostics"]} == {
        "taskrun:old-waiting-executor",
        "taskrun:waiting-approval",
        "taskrun:old-running",
    }
    assert monitor["buckets"]["failed"] == []
    assert buckets["taskrun:fresh-waiting-executor"] == "running"
    assert buckets["taskrun:waiting-approval"] == "diagnostics"
    assert buckets["taskrun:old-waiting-executor"] == "diagnostics"
    assert buckets["taskrun:old-running"] == "diagnostics"
    assert monitor["summary"]["total"] == 4
    assert monitor["summary"]["running"] == 1
    assert monitor["summary"]["failed"] == 0
    assert monitor["summary"]["diagnostics"] == 3
    assert monitor["summary"]["action_required"] == 1


def test_task_run_detail_monitor_exposes_step_summary_and_recent_terminal_status(monkeypatch) -> None:
    monkeypatch.setattr("harness.runtime.single_agent_host.time.time", lambda: 1000.0)
    runtime = build_query_runtime()
    host = runtime.single_agent_runtime_host
    task_run = TaskRun(
        task_run_id="taskrun:recent-completed",
        session_id="session-monitor",
        task_id="task:recent-completed",
        status="completed",
        created_at=600.0,
        updated_at=990.0,
        execution_runtime_kind="single_agent_task",
        terminal_reason="completed",
        diagnostics={
            "artifact_refs": [{"path": "storage/task/result.md"}],
            "latest_step": "final_self_review",
            "latest_step_status": "completed",
            "latest_step_summary": "agent 已完成最终自检并确认交付物存在。",
        },
    )
    host.state_index.upsert_task_run(task_run)
    host.event_log.append(
        task_run.task_run_id,
        "step_summary_recorded",
        payload={
            "task_run_id": task_run.task_run_id,
            "step": "final_self_review",
            "status": "completed",
            "summary": "agent 已完成最终自检并确认交付物存在。",
        },
    )

    global_monitor = host.list_global_live_monitor(limit=20)
    item = host.get_task_run_live_monitor(task_run.task_run_id)
    assert item is not None

    assert item["task_run_id"] == task_run.task_run_id
    assert item["bucket"] == "completed"
    assert item["latest_step_name"] == "final_self_review"
    assert item["latest_step_status"] == "completed"
    assert item["latest_step_summary"] == "助手已完成最终自检并确认交付物存在。"
    _assert_no_visible_runtime_internals(item["latest_step_summary"])
    assert item["artifact_count"] == 1
    assert item["resource_class"] == "static"
    assert item["ended_at"] == 990.0
    assert item["duration_seconds"] == 390.0
    assert global_monitor["summary"]["completed"] == 0
    assert task_run.task_run_id not in {entry["task_run_id"] for entry in global_monitor["task_runs"]}


def test_invalid_agent_action_request_reports_error_without_task_run() -> None:
    runtime = build_query_runtime(
        model_runtime=SingleMessageModelRuntimeStub(
            agent_turn_action_request={
                "authority": "harness.loop.model_action_request",
                "request_id": "model-action:test:invalid",
                "turn_id": "",
                "action_type": "request_task_run",
                "task_contract_seed": {},
            }
        )
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(QueryRequest(session_id="session-invalid", message="请执行。")):
            events.append(event)
        return events

    events = asyncio.run(_collect())

    assert any(event.get("type") == "error" for event in events)
    assert any(event.get("type") == "harness_run_started" for event in events)


class _MalformedModelRuntime:
    async def invoke_messages(self, _messages, **_kwargs):
        return SimpleNamespace(content=json.dumps({"authority": "bad"}))


class _FailingModelRuntime:
    async def invoke_messages(self, _messages, **_kwargs):
        raise TimeoutError("model timed out")


class _SlowRespondingModelRuntime:
    async def invoke_messages(self, _messages, **_kwargs):
        await asyncio.sleep(0.02)
        return SimpleNamespace(
            content=json.dumps(
                _action_request(
                    action_type="respond",
                    final_answer="慢模型完成。",
                ),
                ensure_ascii=False,
            )
        )


class _NeverRespondingModelRuntime:
    async def invoke_messages(self, _messages, **_kwargs):
        await asyncio.sleep(60)
        return SimpleNamespace(content="{}")


class _TurnActionSequenceModelRuntime:
    def __init__(self, actions: list[dict[str, object]]) -> None:
        self.actions = list(actions)
        self.invocation_count = 0

    async def invoke_messages(self, _messages, **_kwargs):
        self.invocation_count += 1
        if self.actions:
            action = self.actions.pop(0)
        else:
            action = _action_request(action_type="respond", final_answer="完成。")
        return SimpleNamespace(content=json.dumps(action, ensure_ascii=False))


class _ActiveWorkDecisionModelRuntime:
    def __init__(self, decisions: list[dict[str, object]]) -> None:
        self.decisions = list(decisions)
        self.active_work_decision_count = 0

    async def invoke_messages(self, messages, **_kwargs):
        content = str(messages or "")
        if "harness.loop.active_work_turn_decision.input" in content:
            self.active_work_decision_count += 1
            decision = self.decisions.pop(0) if self.decisions else {
                "authority": "harness.loop.active_work_turn_decision",
                "action": "answer_about_active_work",
                "relation_to_current_work": "current_work",
                "evidence": "测试桩默认指向当前工作",
                "response": "现在是正在处理。",
                "confidence": 0.9,
            }
            if str(decision.get("action") or "") not in {"normal_response", "start_new_work"}:
                decision.setdefault("relation_to_current_work", "current_work")
                decision.setdefault("evidence", "测试桩指向当前工作")
            return SimpleNamespace(content=json.dumps(decision, ensure_ascii=False))
        if "plain_conversation" in content or "Plain conversation" in content:
            return SimpleNamespace(content="普通回复。")
        return SimpleNamespace(content=json.dumps(_action_request(action_type="respond", final_answer="普通回复。"), ensure_ascii=False))


class _TaskExecutorSequenceModelRuntime:
    def __init__(self, task_actions: list[dict[str, object]], *, agent_turn_action_request: dict[str, object]) -> None:
        self.task_actions = list(task_actions)
        self.agent_turn_action_request = dict(agent_turn_action_request)
        self.task_invocation_count = 0

    async def invoke_messages(self, messages, **_kwargs):
        content = str(list(messages or [])[0].get("content") or "")
        if "持续处理流程" in content or "task_execution" in str(messages):
            self.task_invocation_count += 1
            action = self.task_actions.pop(0) if self.task_actions else self.task_actions[-1]
            return SimpleNamespace(content=json.dumps(action, ensure_ascii=False))
        return SimpleNamespace(content=json.dumps(self.agent_turn_action_request, ensure_ascii=False))


class _SlowTaskExecutorModelRuntime:
    async def invoke_messages(self, _messages, **_kwargs):
        await asyncio.sleep(0.1)
        return SimpleNamespace(
            content=json.dumps(
                _action_request(action_type="respond", final_answer="慢任务完成。"),
                ensure_ascii=False,
            )
        )


def test_malformed_agent_action_request_fails_closed() -> None:
    runtime = build_query_runtime(model_runtime=_MalformedModelRuntime())

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(QueryRequest(session_id="session-malformed", message="继续。")):
            events.append(event)
        return events

    events = asyncio.run(_collect())

    assert any(event.get("type") == "error" for event in events)
    assert any(event.get("type") == "harness_run_started" for event in events)


def test_turn_model_wait_is_observable(monkeypatch) -> None:
    monkeypatch.setattr("harness.loop.agent_loop._MODEL_ACTION_WAIT_STATUS_INTERVAL_SECONDS", 0.001)
    runtime = build_query_runtime(model_runtime=_SlowRespondingModelRuntime())

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(QueryRequest(session_id="session-slow-model", message="慢一点回答。")):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    step_summaries = [event for event in events if event.get("type") == "runtime_step_summary"]
    steps = [str(event.get("step") or "") for event in step_summaries]

    assert any(step.startswith("model_action_invocation_started:") for step in steps)
    assert any(step.startswith("model_action_waiting:") for step in steps)
    _assert_no_visible_runtime_internals("\n".join(str(event.get("summary") or "") for event in step_summaries))
    assert any(event.get("type") == "done" for event in events)


def test_turn_stream_cancellation_closes_running_turn(monkeypatch) -> None:
    monkeypatch.setattr("harness.loop.agent_loop._MODEL_ACTION_WAIT_STATUS_INTERVAL_SECONDS", 0.001)
    runtime = build_query_runtime(model_runtime=_NeverRespondingModelRuntime())

    async def _start_and_cancel() -> None:
        stream = runtime.astream(QueryRequest(session_id="session-cancelled-turn", message="保持等待。"))
        async for event in stream:
            if event.get("type") == "runtime_step_summary" and str(event.get("step") or "").startswith("model_action_waiting:"):
                await stream.aclose()
                return

    asyncio.run(_start_and_cancel())

    traces = runtime.single_agent_runtime_host.list_session_traces("session-cancelled-turn")
    turn_runs = [
        item
        for item in list(traces.get("turn_runs") or [])
        if str(dict(item).get("turn_run_id") or "").startswith("turnrun:")
    ]
    assert turn_runs
    turn_run = dict(turn_runs[-1])
    assert turn_run["status"] == "aborted"
    assert turn_run["terminal_reason"] == "stream_cancelled"


def test_turn_protocol_error_is_repaired_by_followup_observation() -> None:
    runtime = build_query_runtime(
        model_runtime=_TurnActionSequenceModelRuntime(
            [
                {"authority": "harness.loop.model_action_request", "action_type": ""},
                _action_request(action_type="respond", final_answer="协议修复后完成。"),
            ]
        )
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(QueryRequest(session_id="session-turn-protocol-repair", message="继续。")):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    event_types = [str(event.get("type") or "") for event in events]
    steps = [str(event.get("step") or "") for event in events if event.get("type") == "runtime_step_summary"]

    assert "bounded_observation" in event_types
    assert any(step.startswith("model_action_protocol_repair_required:") for step in steps)
    assert any(event.get("type") == "done" and "协议修复后完成" in str(event.get("content") or "") for event in events)


def test_task_executor_schedule_missing_callback_blocks_task_run() -> None:
    from harness.loop.agent_loop import _schedule_task_executor

    runtime = build_query_runtime(
        model_runtime=SingleMessageModelRuntimeStub(
            agent_turn_action_request=_action_request(
                action_type="request_task_run",
                task_contract_seed={"user_visible_goal": "需要调度。", "task_run_goal": "需要调度。", "completion_criteria": ["调度必须可观测"]},
            )
        )
    )

    async def _create_task() -> str:
        task_run_id = ""
        async for event in runtime.astream(QueryRequest(session_id="session-missing-scheduler", message="做一个任务。")):
            if event.get("type") == "harness_run_started":
                candidate = str(dict(event.get("task_run") or {}).get("task_run_id") or "")
                if candidate.startswith("taskrun:"):
                    task_run_id = candidate
        return task_run_id

    task_run_id = asyncio.run(_create_task())
    services = runtime.agent_harness._services
    object.__setattr__(services, "execute_task_run_callback", None)

    _schedule_task_executor(services, task_run_id)

    task_run = runtime.single_agent_runtime_host.state_index.get_task_run(task_run_id)
    assert task_run is not None
    assert task_run.status == "blocked"
    assert task_run.terminal_reason == "task_executor_schedule_failed"
    assert dict(dict(task_run.diagnostics or {}).get("recoverable_error") or {}).get("retryable") is True


def test_task_executor_scheduler_auto_continues_waiting_executor() -> None:
    from harness.loop.agent_loop import _schedule_task_executor

    runtime = build_query_runtime(
        model_runtime=SingleMessageModelRuntimeStub(
            agent_turn_action_request=_action_request(
                action_type="request_task_run",
                task_contract_seed={"user_visible_goal": "需要自动续跑。", "task_run_goal": "需要自动续跑。", "completion_criteria": ["最终完成"]},
            )
        )
    )

    async def _create_task() -> str:
        task_run_id = ""
        async for event in runtime.astream(QueryRequest(session_id="session-auto-continue", message="做一个任务。")):
            if event.get("type") == "harness_run_started":
                candidate = str(dict(event.get("task_run") or {}).get("task_run_id") or "")
                if candidate.startswith("taskrun:"):
                    task_run_id = candidate
        return task_run_id

    task_run_id = asyncio.run(_create_task())
    calls = {"count": 0}
    task_run = runtime.single_agent_runtime_host.state_index.get_task_run(task_run_id)
    assert task_run is not None
    runtime.single_agent_runtime_host.state_index.upsert_task_run(
        replace(task_run, status="waiting_executor", terminal_reason="waiting_executor", diagnostics={})
    )

    async def _executor(task_run_id_arg: str):
        calls["count"] += 1
        task_run = runtime.single_agent_runtime_host.state_index.get_task_run(task_run_id_arg)
        assert task_run is not None
        if calls["count"] == 1:
            runtime.single_agent_runtime_host.state_index.upsert_task_run(
                replace(task_run, status="waiting_executor", terminal_reason="waiting_executor")
            )
            return {"ok": False, "error": "task_execution_step_budget_exhausted", "retryable": True}
        runtime.single_agent_runtime_host.state_index.upsert_task_run(
            replace(task_run, status="completed", terminal_reason="completed")
        )
        return {"ok": True}

    services = runtime.agent_harness._services
    object.__setattr__(services, "execute_task_run_callback", _executor)

    async def _run_scheduler() -> None:
        _schedule_task_executor(services, task_run_id)
        for _ in range(20):
            if calls["count"] >= 2:
                return
            await asyncio.sleep(0.01)
        raise AssertionError("scheduler did not auto-continue waiting_executor")

    asyncio.run(_run_scheduler())

    trace = runtime.single_agent_runtime_host.get_trace(task_run_id, include_payloads=False)
    event_types = [str(dict(item).get("event_type") or "") for item in list(dict(trace or {}).get("events") or [])]
    assert calls["count"] == 2
    assert "task_run_executor_rescheduled" in event_types


def test_task_executor_commits_final_answer_to_session_history() -> None:
    runtime = build_query_runtime(
        model_runtime=_TaskExecutorSequenceModelRuntime(
            [
                _action_request(
                    action_type="respond",
                    final_answer="TaskRun 已完成并回写到会话。",
                )
            ],
            agent_turn_action_request=_action_request(action_type="respond", final_answer="unused"),
        )
    )
    host = runtime.single_agent_runtime_host
    contract = TaskRunContract(
        contract_id="task-contract:session-final-commit",
        contract_source="test",
        user_visible_goal="验证 TaskRun final answer 会回写会话。",
        task_run_goal="完成后把 final answer 写回 session history。",
        completion_criteria=("final answer 已提交到会话历史",),
    )
    contract_ref = host.runtime_objects.put_object("task_run_contract", contract.contract_id, contract.to_dict())
    lifecycle = TaskLifecycleRecord(
        task_run_id="taskrun:session-final-commit",
        contract_ref=contract_ref,
        status="waiting_executor",
        created_at=1.0,
        updated_at=1.0,
    )
    host.runtime_objects.put_object("task_lifecycle", lifecycle.task_run_id, lifecycle.to_dict())
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id=lifecycle.task_run_id,
            session_id="session-final-commit",
            task_id="task:session-final-commit",
            task_contract_ref=contract_ref,
            agent_profile_id="main_interactive_agent",
            execution_runtime_kind="single_agent_task",
            status="waiting_executor",
            created_at=1.0,
            updated_at=1.0,
            diagnostics={"contract": contract.to_dict()},
        )
    )

    result = asyncio.run(runtime.execute_task_run(lifecycle.task_run_id, max_steps=2))

    messages = runtime.session_manager.load_session("session-final-commit")
    trace = host.get_trace(lifecycle.task_run_id, include_payloads=False)
    event_types = [str(dict(item).get("event_type") or "") for item in list(dict(trace or {}).get("events") or [])]

    assert result["ok"] is True
    assert any(
        item.get("role") == "assistant" and item.get("content") == "TaskRun 已完成并回写到会话。"
        for item in messages
    )
    assert "task_run_final_message_commit_checked" in event_types


def test_task_executor_wait_heartbeat_does_not_repeat_visible_step_summary(monkeypatch) -> None:
    monkeypatch.setattr("harness.loop.task_executor._TASK_MODEL_ACTION_WAIT_STATUS_INTERVAL_SECONDS", 0.001)
    runtime = build_query_runtime(model_runtime=_SlowTaskExecutorModelRuntime())
    host = runtime.single_agent_runtime_host
    contract = TaskRunContract(
        contract_id="task-contract:slow-task-wait",
        contract_source="test",
        user_visible_goal="验证慢任务等待状态。",
        task_run_goal="慢模型返回后完成。",
        completion_criteria=("慢任务完成",),
    )
    contract_ref = host.runtime_objects.put_object("task_run_contract", contract.contract_id, contract.to_dict())
    lifecycle = TaskLifecycleRecord(
        task_run_id="taskrun:turn:session-slow-task:1:abc",
        contract_ref=contract_ref,
        status="waiting_executor",
        created_at=1.0,
        updated_at=1.0,
    )
    host.runtime_objects.put_object("task_lifecycle", lifecycle.task_run_id, lifecycle.to_dict())
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id=lifecycle.task_run_id,
            session_id="session-slow-task",
            task_id="task:turn:session-slow-task:1",
            task_contract_ref=contract_ref,
            agent_profile_id="main_interactive_agent",
            execution_runtime_kind="single_agent_task",
            status="waiting_executor",
            created_at=1.0,
            updated_at=1.0,
            diagnostics={"turn_id": "turn:session-slow-task:1", "contract": contract.to_dict()},
        )
    )

    result = asyncio.run(runtime.execute_task_run(lifecycle.task_run_id, max_steps=1))

    trace = host.get_trace(lifecycle.task_run_id, include_payloads=True)
    events = list(dict(trace or {}).get("events") or [])
    visible_wait_steps = [
        event
        for event in events
        if str(dict(event).get("event_type") or "") == "step_summary_recorded"
        and str(dict(dict(event).get("payload") or {}).get("step") or "").startswith("task_model_action_waiting:")
    ]
    wait_heartbeats = [
        event
        for event in events
        if str(dict(event).get("event_type") or "") == "task_model_action_wait_heartbeat"
    ]

    assert result["ok"] is True
    assert len(visible_wait_steps) == 1
    assert wait_heartbeats


def test_session_runtime_timeline_keeps_completed_task_attachment() -> None:
    from harness.runtime.session_timeline import build_session_runtime_timeline

    runtime = build_query_runtime(
        model_runtime=_TaskExecutorSequenceModelRuntime(
            [
                _action_request(
                    action_type="respond",
                    final_answer="Timeline final answer.",
                    public_progress_note="我已完成 timeline 验证，正在整理最终回复。",
                )
            ],
            agent_turn_action_request=_action_request(action_type="respond", final_answer="unused"),
        )
    )
    host = runtime.single_agent_runtime_host
    contract = TaskRunContract(
        contract_id="task-contract:timeline",
        contract_source="test",
        user_visible_goal="验证 timeline attachment。",
        task_run_goal="完成后仍保留运行附件。",
        completion_criteria=("final answer 已形成",),
    )
    contract_ref = host.runtime_objects.put_object("task_run_contract", contract.contract_id, contract.to_dict())
    lifecycle = TaskLifecycleRecord(
        task_run_id="taskrun:turn:session-timeline:1:abc",
        contract_ref=contract_ref,
        status="waiting_executor",
        created_at=1.0,
        updated_at=1.0,
    )
    host.runtime_objects.put_object("task_lifecycle", lifecycle.task_run_id, lifecycle.to_dict())
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id=lifecycle.task_run_id,
            session_id="session-timeline",
            task_id="task:turn:session-timeline:1",
            task_contract_ref=contract_ref,
            agent_profile_id="main_interactive_agent",
            execution_runtime_kind="single_agent_task",
            status="waiting_executor",
            created_at=1.0,
            updated_at=1.0,
            diagnostics={"turn_id": "turn:session-timeline:1", "contract": contract.to_dict()},
        )
    )

    result = asyncio.run(runtime.execute_task_run(lifecycle.task_run_id, max_steps=2))
    timeline = build_session_runtime_timeline(
        session_id="session-timeline",
        history={"messages": runtime.session_manager.load_session("session-timeline")},
        runtime_host=host,
    )

    attachment = timeline["runtime_attachments"][0]
    assert result["ok"] is True
    assert attachment["run_id"] == lifecycle.task_run_id
    assert attachment["task_run_id"] == lifecycle.task_run_id
    assert attachment["anchor_turn_id"] == "turn:session-timeline:1"
    assert attachment["status"] == "completed"
    assert attachment["final_answer"] == "Timeline final answer."
    assert attachment["progress_entries"]
    assert any(
        item.get("publicNote") == "我已完成 timeline 验证，正在整理最终回复。"
        for item in attachment["progress_entries"]
    )
    assert any(
        item.get("agentBrief") == "Timeline final answer."
        for item in attachment["progress_entries"]
    )
    visible_attachment_text = json.dumps(
        {
            "summary": attachment["summary"],
            "latest_step_summary": attachment["latest_step_summary"],
            "progress_entries": [
                {"title": item.get("title"), "body": item.get("body"), "publicNote": item.get("publicNote")}
                for item in attachment["progress_entries"]
            ],
        },
        ensure_ascii=False,
    )
    _assert_no_visible_runtime_internals(visible_attachment_text)


def test_session_runtime_timeline_derives_turn_anchor_from_structural_task_run_id() -> None:
    from harness.runtime.session_timeline import build_session_runtime_timeline

    runtime = build_query_runtime()
    host = runtime.single_agent_runtime_host
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id="taskrun:turn:session-anchor:3:abc",
            session_id="session-anchor",
            task_id="task:turn:session-anchor:3",
            agent_profile_id="main_interactive_agent",
            execution_runtime_kind="single_agent_task",
            status="completed",
            terminal_reason="completed",
            created_at=1.0,
            updated_at=2.0,
            diagnostics={},
        )
    )

    timeline = build_session_runtime_timeline(
        session_id="session-anchor",
        history={"messages": []},
        runtime_host=host,
    )

    attachment = timeline["runtime_attachments"][0]
    assert attachment["run_id"] == "taskrun:turn:session-anchor:3:abc"
    assert attachment["anchor_turn_id"] == "turn:session-anchor:3"


def test_session_runtime_timeline_anchors_checkout_to_latest_user_control_turn() -> None:
    from harness.loop.task_checkout import checkout_task_run_for_resume
    from harness.loop.task_executor import append_user_work_instruction
    from harness.runtime.session_timeline import build_session_runtime_timeline

    runtime = build_query_runtime()
    host = runtime.single_agent_runtime_host
    contract = TaskRunContract(
        contract_id="task-contract:timeline-checkout-anchor",
        contract_source="test",
        user_visible_goal="验证续跑进展显示在最新继续消息。",
        task_run_goal="断点续跑后 timeline 必须锚到用户最新控制 turn。",
        completion_criteria=("timeline anchor uses latest control turn",),
    )
    contract_ref = host.runtime_objects.put_object("task_run_contract", contract.contract_id, contract.to_dict())
    source_task_run_id = "taskrun:turn:session-checkout-anchor:8:abc"
    host.runtime_objects.put_object(
        "task_lifecycle",
        source_task_run_id,
        TaskLifecycleRecord(
            task_run_id=source_task_run_id,
            contract_ref=contract_ref,
            status="aborted",
            created_at=1.0,
            updated_at=2.0,
        ).to_dict(),
    )
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id=source_task_run_id,
            session_id="session-checkout-anchor",
            task_id="task:turn:session-checkout-anchor:8",
            task_contract_ref=contract_ref,
            agent_profile_id="main_interactive_agent",
            execution_runtime_kind="single_agent_task",
            status="aborted",
            terminal_reason="user_aborted",
            created_at=1.0,
            updated_at=2.0,
            diagnostics={"turn_id": "turn:session-checkout-anchor:8", "contract": contract.to_dict()},
        )
    )

    checkout = checkout_task_run_for_resume(
        host,
        source_task_run_id,
        user_instruction="继续旧任务。",
        turn_id="turn:session-checkout-anchor:16",
    )
    child = dict(checkout.get("task_run") or {})
    child_task_run_id = str(child.get("task_run_id") or "")
    assert child_task_run_id
    append_user_work_instruction(
        host,
        child_task_run_id,
        content="预算已经调大，请继续完成。",
        turn_id="turn:session-checkout-anchor:18",
        intent="conversation_instruction",
    )

    timeline = build_session_runtime_timeline(
        session_id="session-checkout-anchor",
        history={
            "messages": [
                {"role": "user", "content": "开始任务"},
                {"role": "assistant", "content": "任务已接管"},
                {"role": "user", "content": "继续"},
                {"role": "assistant", "content": "我会继续处理"},
                {"role": "user", "content": "预算已经调大，请继续完成。"},
                {"role": "assistant", "content": "收到，继续执行。"},
            ]
        },
        runtime_host=host,
    )

    checkout_attachment = next(
        item for item in timeline["runtime_attachments"]
        if item["task_run_id"] == child_task_run_id
    )
    assert checkout_attachment["run_id"] == child_task_run_id
    assert checkout_attachment["anchor_turn_id"] == "turn:session-checkout-anchor:18"
    assert any(
        item.get("eventType") == "active_task_steer_recorded"
        for item in checkout_attachment["progress_entries"]
    )


def test_running_task_run_is_not_externally_executable_unless_executor_claimed() -> None:
    from harness.loop.task_executor import is_task_run_executable, is_task_run_executor_claimed

    plain_running = TaskRun(
        task_run_id="taskrun:plain-running",
        session_id="session-executor-lease",
        task_id="task:plain-running",
        execution_runtime_kind="single_agent_task",
        status="running",
        diagnostics={},
    )
    claimed_running = replace(
        plain_running,
        task_run_id="taskrun:claimed-running",
        diagnostics={"executor_status": "scheduled"},
    )
    waiting = replace(
        plain_running,
        task_run_id="taskrun:waiting",
        status="waiting_executor",
        terminal_reason="waiting_executor",
    )

    assert is_task_run_executable(waiting) is True
    assert is_task_run_executable(plain_running) is False
    assert is_task_run_executor_claimed(plain_running) is False
    assert is_task_run_executor_claimed(claimed_running) is True


def test_waiting_executor_with_stale_running_diagnostics_is_resumable_not_running() -> None:
    from harness.loop.active_work import build_active_work_context
    from harness.loop.resume_policy import build_resume_plan
    from harness.loop.task_executor import is_task_run_executable, is_task_run_executor_claimed

    runtime = build_query_runtime()
    task_run_id = _seed_active_work(
        runtime,
        task_run_id="taskrun:stale-running-waiting",
        session_id="session-stale-running-waiting",
    )
    host = runtime.single_agent_runtime_host
    task_run = host.state_index.get_task_run(task_run_id)
    assert task_run is not None
    host.state_index.upsert_task_run(
        replace(
            task_run,
            status="waiting_executor",
            terminal_reason="waiting_executor",
            diagnostics={
                **dict(task_run.diagnostics or {}),
                "executor_status": "running",
                "runtime_control": {"state": "resume_requested", "authority": "orchestration.task_run_control"},
            },
        )
    )

    context = build_active_work_context(host, session_id="session-stale-running-waiting")
    task_run = host.state_index.get_task_run(task_run_id)

    assert task_run is not None
    assert context is not None
    assert context.running is False
    assert context.resumable is True
    assert is_task_run_executor_claimed(task_run) is False
    assert is_task_run_executable(task_run) is True
    assert build_resume_plan(host, context=context, user_message="继续").decision == "same_run_resume"


def test_execute_task_run_rejects_duplicate_running_claim() -> None:
    runtime = build_query_runtime(
        model_runtime=SingleMessageModelRuntimeStub(
            agent_turn_action_request=_action_request(action_type="respond", final_answer="unused")
        )
    )
    host = runtime.single_agent_runtime_host
    contract = TaskRunContract(
        contract_id="task-contract:duplicate-running-claim",
        contract_source="test",
        user_visible_goal="防止重复执行器。",
        task_run_goal="防止重复执行器。",
        completion_criteria=("重复执行器必须被拒绝",),
    )
    contract_ref = host.runtime_objects.put_object("task_run_contract", contract.contract_id, contract.to_dict())
    task_run = TaskRun(
        task_run_id="taskrun:duplicate-running-claim",
        session_id="session-duplicate-running-claim",
        task_id="task:duplicate-running-claim",
        task_contract_ref=contract_ref,
        execution_runtime_kind="single_agent_task",
        status="running",
        diagnostics={"executor_status": "running", "executor_epoch": 1},
    )
    host.state_index.upsert_task_run(task_run)

    result = asyncio.run(runtime.execute_task_run(task_run.task_run_id, max_steps=1))

    assert result["ok"] is False
    assert result["error"] == "task_run_executor_already_running"
    trace = host.get_trace(task_run.task_run_id, include_payloads=True)
    event_types = [str(dict(item).get("event_type") or "") for item in list(dict(trace or {}).get("events") or [])]
    assert "runtime_invocation_packet_compiled" not in event_types


def test_execute_task_run_accepts_scheduled_claim_start() -> None:
    runtime = build_query_runtime(
        model_runtime=_TaskExecutorSequenceModelRuntime(
            [_action_request(action_type="respond", final_answer="调度接管完成。")],
            agent_turn_action_request=_action_request(action_type="respond", final_answer="unused"),
        )
    )
    host = runtime.single_agent_runtime_host
    contract = TaskRunContract(
        contract_id="task-contract:scheduled-claim-start",
        contract_source="test",
        user_visible_goal="允许调度器接管。",
        task_run_goal="允许调度器接管。",
        completion_criteria=("调度器接管后可以执行",),
    )
    contract_ref = host.runtime_objects.put_object("task_run_contract", contract.contract_id, contract.to_dict())
    task_run = TaskRun(
        task_run_id="taskrun:scheduled-claim-start",
        session_id="session-scheduled-claim-start",
        task_id="task:scheduled-claim-start",
        task_contract_ref=contract_ref,
        execution_runtime_kind="single_agent_task",
        status="running",
        diagnostics={"executor_status": "scheduled"},
    )
    host.state_index.upsert_task_run(task_run)

    result = asyncio.run(runtime.execute_task_run(task_run.task_run_id, max_steps=1))

    assert result["ok"] is True


def test_task_executor_uses_task_bound_model_selection_for_runtime_packet_and_invocation(monkeypatch) -> None:
    from harness.loop import task_executor as task_executor_module

    model_selection = {
        "provider": "test-provider",
        "model": "task-bound-test-model",
        "timeout_seconds": 11,
    }
    captured_timeout_selection: dict[str, object] = {}
    original_timeout = task_executor_module.model_action_timeout_seconds

    def _capturing_timeout(model_runtime, *, model_selection):
        captured_timeout_selection.update(dict(model_selection or {}))
        return original_timeout(model_runtime, model_selection=model_selection)

    monkeypatch.setattr(task_executor_module, "model_action_timeout_seconds", _capturing_timeout)

    class _CapturingModelRuntime:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        async def invoke_messages(self, messages, **kwargs):
            self.calls.append({"messages": list(messages or []), "kwargs": dict(kwargs)})
            return SimpleNamespace(
                content=json.dumps(
                    _action_request(action_type="respond", final_answer="绑定模型配置执行完成。"),
                    ensure_ascii=False,
                )
            )

    model_runtime = _CapturingModelRuntime()
    runtime = build_query_runtime(model_runtime=model_runtime)
    host = runtime.single_agent_runtime_host
    contract = TaskRunContract(
        contract_id="task-contract:model-selection-binding",
        contract_source="test",
        user_visible_goal="验证单节点任务绑定模型配置。",
        task_run_goal="执行器必须使用 task 创建时冻结的模型配置。",
        completion_criteria=("执行器使用 task-bound model_selection",),
    )
    contract_ref = host.runtime_objects.put_object("task_run_contract", contract.contract_id, contract.to_dict())
    lifecycle = TaskLifecycleRecord(
        task_run_id="taskrun:model-selection-binding",
        contract_ref=contract_ref,
        status="waiting_executor",
        created_at=1.0,
        updated_at=1.0,
    )
    host.runtime_objects.put_object("task_lifecycle", lifecycle.task_run_id, lifecycle.to_dict())
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id=lifecycle.task_run_id,
            session_id="session-model-selection-binding",
            task_id="task:model-selection-binding",
            task_contract_ref=contract_ref,
            agent_profile_id="main_interactive_agent",
            execution_runtime_kind="single_agent_task",
            status="waiting_executor",
            created_at=1.0,
            updated_at=1.0,
            diagnostics={
                "turn_id": "turn:session-model-selection-binding:1",
                "contract": contract.to_dict(),
                "model_selection": model_selection,
            },
        )
    )

    result = asyncio.run(runtime.execute_task_run(lifecycle.task_run_id, max_steps=1))

    trace = host.get_trace(lifecycle.task_run_id, include_payloads=True)
    events = [dict(item) for item in list(dict(trace or {}).get("events") or [])]
    started_payload = dict(
        next(
            item
            for item in events
            if str(item.get("event_type") or "") == "task_run_executor_started"
        ).get("payload") or {}
    )
    packet_payload = dict(
        next(
            item
            for item in events
            if str(item.get("event_type") or "") == "runtime_invocation_packet_compiled"
        ).get("payload") or {}
    )
    envelope = dict(packet_payload.get("envelope") or {})

    assert result["ok"] is True
    assert model_runtime.calls
    assert dict(dict(model_runtime.calls[0]).get("kwargs") or {}).get("model_spec") == model_selection
    assert captured_timeout_selection == model_selection
    assert dict(dict(started_payload.get("runtime_assembly") or {}).get("model_selection") or {}) == model_selection
    assert dict(dict(envelope.get("diagnostics") or {}).get("model_selection") or {}) == model_selection


def test_execute_task_run_uses_task_bound_agent_profile_for_runtime_assembly() -> None:
    class _CapturingModelRuntime:
        async def invoke_messages(self, messages, **kwargs):
            return SimpleNamespace(
                content=json.dumps(
                    _action_request(action_type="respond", final_answer="绑定 profile 执行完成。"),
                    ensure_ascii=False,
                )
            )

    runtime = build_query_runtime(model_runtime=_CapturingModelRuntime())
    runtime.agent_runtime_registry.upsert_profile(
        agent_id="agent:3",
        agent_profile_id="custom_single_agent_task_profile",
        allowed_operations=("op.model_response",),
        metadata={"work_role_prompt": "你是单 agent 专用执行员。"},
    )
    host = runtime.single_agent_runtime_host
    contract = TaskRunContract(
        contract_id="task-contract:profile-binding",
        contract_source="test",
        user_visible_goal="验证单节点任务绑定 profile。",
        task_run_goal="执行器必须使用 task_run.agent_profile_id 组装 runtime。",
        completion_criteria=("执行器使用 task-bound agent profile",),
    )
    contract_ref = host.runtime_objects.put_object("task_run_contract", contract.contract_id, contract.to_dict())
    lifecycle = TaskLifecycleRecord(
        task_run_id="taskrun:profile-binding",
        contract_ref=contract_ref,
        status="waiting_executor",
        created_at=1.0,
        updated_at=1.0,
    )
    host.runtime_objects.put_object("task_lifecycle", lifecycle.task_run_id, lifecycle.to_dict())
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id=lifecycle.task_run_id,
            session_id="session-profile-binding",
            task_id="task:profile-binding",
            task_contract_ref=contract_ref,
            agent_id="agent:3",
            agent_profile_id="custom_single_agent_task_profile",
            execution_runtime_kind="single_agent_task",
            status="waiting_executor",
            created_at=1.0,
            updated_at=1.0,
            diagnostics={
                "turn_id": "turn:session-profile-binding:1",
                "contract": contract.to_dict(),
            },
        )
    )

    result = asyncio.run(runtime.execute_task_run(lifecycle.task_run_id, max_steps=1))

    trace = host.get_trace(lifecycle.task_run_id, include_payloads=True)
    events = [dict(item) for item in list(dict(trace or {}).get("events") or [])]
    started_payload = dict(
        next(
            item
            for item in events
            if str(item.get("event_type") or "") == "task_run_executor_started"
        ).get("payload") or {}
    )
    assembly = dict(started_payload.get("runtime_assembly") or {})
    agent_runs = host.state_index.list_task_agent_runs(lifecycle.task_run_id)
    agent_run_results = host.state_index.list_task_agent_run_results(lifecycle.task_run_id)

    assert result["ok"] is True
    assert assembly["agent_profile_ref"] == "custom_single_agent_task_profile"
    assert assembly["agent_prompt_refs"] == ["agent.custom_single_agent_task_profile.work_role.v1"]
    assert agent_runs[-1].agent_id == "agent:3"
    assert agent_run_results[-1].agent_id == "agent:3"


def test_schedule_task_run_executor_marks_startup_exception_blocked() -> None:
    runtime = build_query_runtime()
    host = runtime.single_agent_runtime_host
    contract = TaskRunContract(
        contract_id="task-contract:schedule-failure",
        contract_source="test",
        user_visible_goal="验证调度异常落盘。",
        task_run_goal="调度器必须把 executor 启动异常写回 TaskRun。",
        completion_criteria=("启动异常被标记为 blocked",),
    )
    contract_ref = host.runtime_objects.put_object("task_run_contract", contract.contract_id, contract.to_dict())
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id="taskrun:schedule-failure",
            session_id="session-schedule-failure",
            task_id="task:schedule-failure",
            task_contract_ref=contract_ref,
            agent_profile_id="missing_single_agent_profile",
            execution_runtime_kind="single_agent_task",
            status="waiting_executor",
            diagnostics={"contract": contract.to_dict()},
        )
    )

    async def _run() -> dict[str, object]:
        scheduled = runtime.schedule_task_run_executor(
            "taskrun:schedule-failure",
            scheduler="test_schedule_failure",
            max_steps=1,
        )
        for _ in range(10):
            await asyncio.sleep(0)
            current = host.state_index.get_task_run("taskrun:schedule-failure")
            if current is not None and current.status == "blocked":
                break
        return scheduled

    scheduled = asyncio.run(_run())

    task_run = host.state_index.get_task_run("taskrun:schedule-failure")
    diagnostics = dict(task_run.diagnostics or {}) if task_run is not None else {}
    events = [item.event_type for item in host.event_log.list_events("taskrun:schedule-failure")]

    assert scheduled["ok"] is True
    assert scheduled["scheduled"] is True
    assert task_run is not None
    assert task_run.status == "blocked"
    assert diagnostics["latest_step"] == "task_executor_schedule_failed"
    assert diagnostics["recoverable_error"]["retryable"] is True
    assert "missing_single_agent_profile" in diagnostics["recoverable_error"]["detail"]
    assert "task_run_executor_schedule_failed" in events


def test_task_executor_services_include_backend_config_for_runtime_fingerprint() -> None:
    from harness.loop.task_executor import _safe_backend_config

    class _SettingsWithBackendConfig(PrimarySettingsStub):
        def task_executor_backend_config(self) -> dict[str, object]:
            return {
                "soul_image_assets": {
                    "base_url": "https://image.example.test/v1",
                    "model": "image-test-model",
                    "api_key_present": True,
                }
            }

    runtime = build_query_runtime(settings_service=_SettingsWithBackendConfig())

    services = runtime._task_executor_services()
    config = _safe_backend_config(services.backend_config)

    assert config["image_generation"] == {
        "base_url": "https://image.example.test/v1",
        "model": "image-test-model",
        "api_key_present": True,
    }


def test_task_contract_preserves_runtime_fields_without_goal_aliases() -> None:
    from harness.loop.model_action_protocol import ModelActionRequest
    from harness.loop.task_lifecycle import contract_from_action_request

    invalid, errors = contract_from_action_request(
        ModelActionRequest(
            request_id="model-action:contract-fields:invalid",
            turn_id="turn-contract-fields",
            action_type="request_task_run",
            task_contract_seed={
                "goal": "旧字段不能替代正式合同字段",
                "completion_criteria": ["需要真实验收"],
            },
        ),
        packet_ref="rtpacket:contract-fields",
    )

    assert invalid is None
    assert "task_goal_required" in errors
    assert "task_run_goal_required" in errors

    contract, contract_errors = contract_from_action_request(
        ModelActionRequest(
            request_id="model-action:contract-fields:valid",
            turn_id="turn-contract-fields",
            action_type="request_task_run",
            task_contract_seed={
                "user_visible_goal": "交付可运行示例",
                "task_run_goal": "创建并验证可运行示例",
                "completion_criteria": ["示例可以被验证"],
                "task_environment_id": "env.development.sandbox",
                "runtime_profile": {"runtime_policy": {"planning_policy": {"plan_mode": "available"}}},
                "source_contract_ref": "contract.demo",
                "external_plan_ref": "plan.demo",
                "prompt_contract": {"role_prompt": "你是执行者。"},
            },
        ),
        packet_ref="rtpacket:contract-fields",
        task_environment_id="env.creation.writing",
    )

    assert contract_errors == []
    assert contract is not None
    assert contract.user_visible_goal == "交付可运行示例"
    assert contract.task_run_goal == "创建并验证可运行示例"
    assert contract.task_environment_id == "env.creation.writing"
    assert contract.runtime_profile["runtime_policy"]["planning_policy"]["plan_mode"] == "available"
    assert contract.source_contract_ref == "contract.demo"
    assert contract.external_plan_ref == "plan.demo"
    assert contract.prompt_contract["role_prompt"] == "你是执行者。"


def test_agent_requested_task_run_inherits_selected_runtime_environment() -> None:
    runtime = build_query_runtime(
        model_runtime=SingleMessageModelRuntimeStub(
            agent_turn_action_request=_action_request(
                action_type="request_task_run",
                task_contract_seed={
                    "user_visible_goal": "交付开发环境产物。",
                    "task_run_goal": "在用户选择的开发环境中交付产物。",
                    "required_artifacts": [{"artifact_kind": "html_app", "user_visible_name": "可运行页面"}],
                    "completion_criteria": ["产物位于所选任务环境的 artifact 区域"],
                    "task_environment_id": "env.general.workspace",
                },
            )
        )
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            QueryRequest(
                session_id="session-selected-env-taskrun",
                message="开发一个可运行页面。",
                task_selection={"task_environment_id": "env.development.sandbox"},
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    started = [
        event
        for event in events
        if event.get("type") == "harness_run_started"
        and str(dict(event.get("task_run") or {}).get("task_run_id") or "").startswith("taskrun:")
    ][0]
    task_run_id = str(dict(started.get("task_run") or {}).get("task_run_id") or "")
    task_run = runtime.single_agent_runtime_host.state_index.get_task_run(task_run_id)
    assert task_run is not None
    contract = dict(runtime.single_agent_runtime_host.runtime_objects.get_object(task_run.task_contract_ref) or {})
    runtime_task_selection = dict(dict(task_run.diagnostics or {}).get("runtime_task_selection") or {})

    assert contract["task_environment_id"] == "env.development.sandbox"
    assert runtime_task_selection["task_environment_id"] == "env.development.sandbox"


def test_runtime_start_recovers_interrupted_task_executor_lease() -> None:
    from harness.loop.task_executor import recover_interrupted_task_executors

    runtime = build_query_runtime()
    host = runtime.single_agent_runtime_host
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id="taskrun:interrupted-executor",
            session_id="session-interrupted-executor",
            task_id="task:interrupted-executor",
            execution_runtime_kind="single_agent_task",
            status="running",
            diagnostics={"executor_status": "scheduled", "latest_step": "task_executor_scheduled"},
        )
    )

    result = recover_interrupted_task_executors(host)
    task_run = host.state_index.get_task_run("taskrun:interrupted-executor")

    assert result["recovered_count"] == 1
    assert task_run is not None
    assert task_run.status == "waiting_executor"
    assert task_run.terminal_reason == "waiting_executor"
    assert dict(task_run.diagnostics or {}).get("executor_status") == "waiting_executor"


def test_runtime_start_recovery_skips_graph_node_assigned_task_run() -> None:
    from harness.loop.task_executor import recover_interrupted_task_executors

    runtime = build_query_runtime()
    host = runtime.single_agent_runtime_host
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id="gtask:graph:node:work",
            session_id="session-graph-node-recovery",
            task_id="task:graph-node",
            execution_runtime_kind="single_agent_task",
            status="running",
            diagnostics={
                "executor_status": "scheduled",
                "origin_kind": "graph_node_assigned",
                "origin": {
                    "origin_kind": "graph_node_assigned",
                    "origin_authority": "harness.graph_loop",
                    "origin_ref": "gwork:graph:node",
                    "parent_run_ref": "grun:graph",
                },
                "graph_node_id": "draft",
                "graph_work_order_id": "gwork:graph:node",
            },
        )
    )

    result = recover_interrupted_task_executors(host)
    task_run = host.state_index.get_task_run("gtask:graph:node:work")

    assert result["recovered_count"] == 0
    assert result["task_run_ids"] == []
    assert result["skipped_graph_node_task_run_ids"] == ["gtask:graph:node:work"]
    assert task_run is not None
    assert task_run.status == "running"
    assert dict(task_run.diagnostics or {}).get("executor_status") == "scheduled"


def test_task_run_executor_keeps_model_call_failure_recoverable() -> None:
    runtime = build_query_runtime(model_runtime=_FailingModelRuntime())
    task_run_id = _seed_active_work(
        runtime,
        task_run_id="taskrun:recoverable-model-failure",
        session_id="session-recoverable-model-failure",
    )

    result = asyncio.run(runtime.execute_task_run(task_run_id, max_steps=1))
    task_run = runtime.single_agent_runtime_host.state_index.get_task_run(task_run_id)
    monitor = runtime.single_agent_runtime_host.get_task_run_live_monitor(task_run_id)

    assert result["error"] == "model_call_recovery_required"
    assert task_run is not None
    assert task_run.status == "blocked"
    assert task_run.terminal_reason == "model_call_recovery_required"
    assert dict(task_run.diagnostics or {}).get("recovery_action") == "rerun_task_executor"
    assert monitor is not None
    assert monitor["latest_step_status"] == "blocked"
    assert "模型调用失败" in monitor["latest_step_summary"]


def test_task_run_executor_recovers_invalid_model_action_as_observation() -> None:
    runtime = build_query_runtime(
        model_runtime=_TaskExecutorSequenceModelRuntime(
            task_actions=[
                {
                    "authority": "harness.loop.model_action_request",
                    "request_id": "model-action:test:invalid-task-step",
                    "turn_id": "",
                    "action_type": "",
                },
                    _action_request(
                        action_type="respond",
                        public_progress_note="已修正上一步输出格式，正在收口结果。",
                        final_answer="已按合同完成。",
                        diagnostics={"artifacts": []},
                    ),
            ],
            agent_turn_action_request=_action_request(
                action_type="request_task_run",
                task_contract_seed={"user_visible_goal": "协议错误后继续执行。", "task_run_goal": "协议错误后继续执行。", "completion_criteria": ["允许无文件收口"]},
            ),
        )
    )
    task_run_id = _seed_active_work(
        runtime,
        task_run_id="taskrun:protocol-repair",
        session_id="session-protocol-repair",
    )
    result = asyncio.run(runtime.execute_task_run(task_run_id, max_steps=3))
    task_run = runtime.single_agent_runtime_host.state_index.get_task_run(task_run_id)
    trace = runtime.single_agent_runtime_host.get_trace(task_run_id, include_payloads=True)
    event_types = [str(dict(item).get("event_type") or "") for item in list(dict(trace or {}).get("events") or [])]

    assert result["ok"] is True
    assert task_run is not None
    assert task_run.status == "completed"
    assert runtime.model_runtime.task_invocation_count == 2
    assert "task_model_action_protocol_repair_required" in event_types


def test_task_run_executor_blocks_repeated_invalid_model_actions_as_recoverable() -> None:
    runtime = build_query_runtime(
        model_runtime=_TaskExecutorSequenceModelRuntime(
            task_actions=[
                {"authority": "harness.loop.model_action_request", "request_id": "model-action:test:bad-1", "turn_id": "", "action_type": ""},
                {"authority": "harness.loop.model_action_request", "request_id": "model-action:test:bad-2", "turn_id": "", "action_type": ""},
                {"authority": "harness.loop.model_action_request", "request_id": "model-action:test:bad-3", "turn_id": "", "action_type": ""},
            ],
            agent_turn_action_request=_action_request(
                action_type="request_task_run",
                task_contract_seed={"user_visible_goal": "连续协议错误后阻塞。", "task_run_goal": "连续协议错误后阻塞。", "completion_criteria": ["不应完成"]},
            ),
        )
    )
    task_run_id = _seed_active_work(
        runtime,
        task_run_id="taskrun:protocol-block",
        session_id="session-protocol-block",
    )
    result = asyncio.run(runtime.execute_task_run(task_run_id, max_steps=4))
    task_run = runtime.single_agent_runtime_host.state_index.get_task_run(task_run_id)

    assert result["ok"] is False
    assert result["error"] == "model_action_protocol_repair_required"
    assert task_run is not None
    assert task_run.status == "waiting_executor"
    assert task_run.terminal_reason == "model_action_protocol_repair_required"
    assert dict(task_run.diagnostics or {}).get("executor_status") == "waiting_executor"
    assert dict(dict(task_run.diagnostics or {}).get("recoverable_error") or {}).get("retryable") is True


def test_recoverable_terminal_closeout_clears_stale_running_executor_status() -> None:
    runtime = build_query_runtime(
        model_runtime=_TaskExecutorSequenceModelRuntime(
            task_actions=[
                {"authority": "harness.loop.model_action_request", "request_id": "model-action:test:bad-1", "turn_id": "", "action_type": ""},
                {"authority": "harness.loop.model_action_request", "request_id": "model-action:test:bad-2", "turn_id": "", "action_type": ""},
                {"authority": "harness.loop.model_action_request", "request_id": "model-action:test:bad-3", "turn_id": "", "action_type": ""},
            ],
            agent_turn_action_request=_action_request(
                action_type="request_task_run",
                task_contract_seed={"user_visible_goal": "清理运行态。", "task_run_goal": "清理运行态。", "completion_criteria": ["可恢复阻塞不残留 running"]},
            ),
        )
    )
    task_run_id = _seed_active_work(
        runtime,
        task_run_id="taskrun:recoverable-closeout-clears-running",
        session_id="session-recoverable-closeout-clears-running",
    )

    result = asyncio.run(runtime.execute_task_run(task_run_id, max_steps=4))
    task_run = runtime.single_agent_runtime_host.state_index.get_task_run(task_run_id)

    assert result["ok"] is False
    assert task_run is not None
    diagnostics = dict(task_run.diagnostics or {})
    assert task_run.status == "waiting_executor"
    assert diagnostics.get("executor_status") == "waiting_executor"
    assert dict(diagnostics.get("runtime_control") or {}).get("state") != "running"
    assert diagnostics.get("recovery_action") == "rerun_task_executor"


def test_ask_user_blocks_as_waiting_executor_without_running_lease() -> None:
    runtime = build_query_runtime(
        model_runtime=_TaskExecutorSequenceModelRuntime(
            task_actions=[
                _action_request(
                    action_type="ask_user",
                    public_progress_note="需要用户确认下一步。",
                    diagnostics={},
                )
                | {"user_question": "请确认下一步。"},
            ],
            agent_turn_action_request=_action_request(
                action_type="request_task_run",
                task_contract_seed={"user_visible_goal": "等待用户输入。", "task_run_goal": "等待用户输入。", "completion_criteria": ["必须等待用户"]},
            ),
        )
    )
    task_run_id = _seed_active_work(
        runtime,
        task_run_id="taskrun:ask-user-waiting",
        session_id="session-ask-user-waiting",
    )

    result = asyncio.run(runtime.execute_task_run(task_run_id, max_steps=2))
    task_run = runtime.single_agent_runtime_host.state_index.get_task_run(task_run_id)

    assert result["ok"] is False
    assert result["error"] == "user_input_required"
    assert task_run is not None
    diagnostics = dict(task_run.diagnostics or {})
    assert task_run.status == "waiting_executor"
    assert task_run.terminal_reason == "user_input_required"
    assert diagnostics.get("executor_status") == "waiting_executor"
    assert diagnostics.get("recovery_action") == "resume_task_run"


def test_resume_recoverable_blocked_task_preserves_recovery_and_becomes_schedulable() -> None:
    from harness.loop.task_executor import is_task_run_executable, resume_paused_task_run

    runtime = build_query_runtime()
    host = runtime.single_agent_runtime_host
    contract = TaskRunContract(
        contract_id="task-contract:resume-recoverable-blocked",
        contract_source="test",
        user_visible_goal="恢复可恢复阻塞。",
        task_run_goal="恢复可恢复阻塞。",
        completion_criteria=("可恢复阻塞可以被继续调度",),
    )
    contract_ref = host.runtime_objects.put_object("task_run_contract", contract.contract_id, contract.to_dict())
    host.runtime_objects.put_object(
        "task_lifecycle",
        "taskrun:resume-recoverable-blocked",
        TaskLifecycleRecord(
            task_run_id="taskrun:resume-recoverable-blocked",
            contract_ref=contract_ref,
            status="blocked",
            created_at=1.0,
            updated_at=1.0,
            terminal_reason="model_call_recovery_required",
        ).to_dict(),
    )
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id="taskrun:resume-recoverable-blocked",
            session_id="session-resume-recoverable-blocked",
            task_id="task:resume-recoverable-blocked",
            task_contract_ref=contract_ref,
            execution_runtime_kind="single_agent_task",
            status="blocked",
            terminal_reason="model_call_recovery_required",
            diagnostics={
                "contract": contract.to_dict(),
                "executor_status": "blocked",
                "recoverable_error": {"error_code": "model_call_failed", "retryable": True},
                "recovery_action": "rerun_task_executor",
            },
        )
    )

    result = resume_paused_task_run(host, "taskrun:resume-recoverable-blocked", reason="继续")
    task_run = host.state_index.get_task_run("taskrun:resume-recoverable-blocked")

    assert result["ok"] is True
    assert task_run is not None
    diagnostics = dict(task_run.diagnostics or {})
    assert task_run.status == "waiting_executor"
    assert task_run.terminal_reason == "waiting_executor"
    assert diagnostics.get("executor_status") == "waiting_executor"
    assert diagnostics.get("recovery_action") == "rerun_task_executor"
    assert dict(diagnostics.get("recoverable_error") or {}).get("retryable") is True
    assert is_task_run_executable(task_run) is True


def test_task_run_executor_step_budget_exhaustion_waits_for_next_run() -> None:
    runtime = build_query_runtime(
        model_runtime=_TaskExecutorSequenceModelRuntime(
            task_actions=[
                {
                    "authority": "harness.loop.model_action_request",
                    "request_id": "model-action:test:budget-invalid",
                    "turn_id": "",
                    "action_type": "",
                },
            ],
            agent_turn_action_request=_action_request(
                action_type="request_task_run",
                task_contract_seed={"user_visible_goal": "预算耗尽后续跑。", "task_run_goal": "预算耗尽后续跑。", "completion_criteria": ["需要下一轮继续"]},
            ),
        )
    )
    task_run_id = _seed_active_work(
        runtime,
        task_run_id="taskrun:budget-wait",
        session_id="session-budget-wait",
    )
    result = asyncio.run(runtime.execute_task_run(task_run_id, max_steps=1))
    task_run = runtime.single_agent_runtime_host.state_index.get_task_run(task_run_id)

    assert result["error"] == "task_execution_step_budget_exhausted"
    assert result["retryable"] is True
    assert task_run is not None
    assert task_run.status == "waiting_executor"
    assert task_run.terminal_reason == "waiting_executor"
    assert dict(dict(task_run.diagnostics or {}).get("recoverable_error") or {}).get("retryable") is True


def test_task_run_pause_resume_and_stop_control_plane() -> None:
    from harness.loop.task_executor import (
        request_task_run_pause,
        resume_paused_task_run,
        stop_task_run,
        task_run_control_state,
    )

    runtime = build_query_runtime(
        model_runtime=_TaskExecutorSequenceModelRuntime(
            task_actions=[
                _action_request(action_type="respond", final_answer="暂停后继续完成。"),
            ],
            agent_turn_action_request=_action_request(action_type="respond", final_answer="unused"),
        )
    )
    host = runtime.single_agent_runtime_host
    contract = TaskRunContract(
        contract_id="task-contract:pause-resume",
        contract_source="test",
        user_visible_goal="验证暂停继续控制。",
        task_run_goal="验证暂停继续控制。",
        completion_criteria=("可以暂停并从同一个 TaskRun 继续",),
    )
    contract_ref = host.runtime_objects.put_object("task_run_contract", contract.contract_id, contract.to_dict())
    lifecycle = TaskLifecycleRecord(
        task_run_id="taskrun:pause-resume",
        contract_ref=contract_ref,
        status="waiting_executor",
        created_at=1.0,
        updated_at=1.0,
    )
    host.runtime_objects.put_object("task_lifecycle", lifecycle.task_run_id, lifecycle.to_dict())
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id=lifecycle.task_run_id,
            session_id="session-pause-resume",
            task_id="task:pause-resume",
            task_contract_ref=contract_ref,
            agent_profile_id="main_interactive_agent",
            execution_runtime_kind="single_agent_task",
            status="waiting_executor",
            created_at=1.0,
            updated_at=1.0,
            diagnostics={"contract": contract.to_dict()},
        )
    )

    pause_result = request_task_run_pause(host, lifecycle.task_run_id, reason="先暂停")
    paused_task = host.state_index.get_task_run(lifecycle.task_run_id)

    assert pause_result["ok"] is True
    assert paused_task is not None
    assert paused_task.status == "waiting_executor"
    assert task_run_control_state(paused_task) == "paused"

    resume_result = resume_paused_task_run(host, lifecycle.task_run_id, reason="继续")
    resumed_task = host.state_index.get_task_run(lifecycle.task_run_id)

    assert resume_result["ok"] is True
    assert resumed_task is not None
    assert task_run_control_state(resumed_task) == "resume_requested"

    result = asyncio.run(runtime.execute_task_run(lifecycle.task_run_id, max_steps=2))
    completed_task = host.state_index.get_task_run(lifecycle.task_run_id)

    assert result["ok"] is True
    assert completed_task is not None
    assert completed_task.status == "completed"

    stop_result = stop_task_run(host, lifecycle.task_run_id, reason="已完成后停止无效")
    assert stop_result["ok"] is True
    assert stop_result["accepted"] is False


def test_task_run_stop_before_executor_marks_user_aborted() -> None:
    from harness.loop.task_executor import stop_task_run, task_run_control_state

    runtime = build_query_runtime()
    host = runtime.single_agent_runtime_host
    contract = TaskRunContract(
        contract_id="task-contract:stop-before-executor",
        contract_source="test",
        user_visible_goal="验证停止控制。",
        task_run_goal="验证停止控制。",
        completion_criteria=("停止后进入用户终态",),
    )
    contract_ref = host.runtime_objects.put_object("task_run_contract", contract.contract_id, contract.to_dict())
    lifecycle = TaskLifecycleRecord(
        task_run_id="taskrun:stop-before-executor",
        contract_ref=contract_ref,
        status="waiting_executor",
        created_at=1.0,
        updated_at=1.0,
    )
    host.runtime_objects.put_object("task_lifecycle", lifecycle.task_run_id, lifecycle.to_dict())
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id=lifecycle.task_run_id,
            session_id="session-stop-before-executor",
            task_id="task:stop-before-executor",
            task_contract_ref=contract_ref,
            agent_profile_id="main_interactive_agent",
            execution_runtime_kind="single_agent_task",
            status="waiting_executor",
            created_at=1.0,
            updated_at=1.0,
            diagnostics={"contract": contract.to_dict()},
        )
    )

    result = stop_task_run(host, lifecycle.task_run_id, reason="用户停止")
    stopped_task = host.state_index.get_task_run(lifecycle.task_run_id)

    assert result["ok"] is True
    assert stopped_task is not None
    assert stopped_task.status == "aborted"
    assert stopped_task.terminal_reason == "user_aborted"
    assert task_run_control_state(stopped_task) == "stopped"


def test_user_aborted_work_rollout_records_single_breakpoint_and_checkout_inherits_it() -> None:
    from harness.loop.task_checkout import checkout_task_run_for_resume
    from harness.loop.task_executor import stop_task_run
    from harness.loop.work_rollout import work_rollout_summary

    runtime = build_query_runtime()
    host = runtime.single_agent_runtime_host
    contract = TaskRunContract(
        contract_id="task-contract:rollout-breakpoint",
        contract_source="test",
        user_visible_goal="验证 rollout 断点。",
        task_run_goal="停止后 checkout 必须继承 rollout 断点。",
        completion_criteria=("断点可被恢复",),
    )
    contract_ref = host.runtime_objects.put_object("task_run_contract", contract.contract_id, contract.to_dict())
    host.runtime_objects.put_object(
        "task_lifecycle",
        "taskrun:rollout-breakpoint",
        TaskLifecycleRecord(
            task_run_id="taskrun:rollout-breakpoint",
            contract_ref=contract_ref,
            status="waiting_executor",
            created_at=1.0,
            updated_at=1.0,
        ).to_dict(),
    )
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id="taskrun:rollout-breakpoint",
            session_id="session-rollout-breakpoint",
            task_id="task:rollout-breakpoint",
            task_contract_ref=contract_ref,
            agent_profile_id="main_interactive_agent",
            execution_runtime_kind="single_agent_task",
            status="waiting_executor",
            latest_checkpoint_ref="rtchk:source:7",
            created_at=1.0,
            updated_at=1.0,
            diagnostics={"contract": contract.to_dict()},
        )
    )

    stop_result = stop_task_run(host, "taskrun:rollout-breakpoint", reason="用户停止")
    source_summary = work_rollout_summary(host, "taskrun:rollout-breakpoint")
    interrupted_items = [
        item for item in list(source_summary.get("model_visible_history") or [])
        if str(dict(item).get("type") or "") == "interrupted_boundary"
    ]

    assert stop_result["ok"] is True
    assert len(interrupted_items) == 1
    assert int(source_summary["breakpoint"]["event_offset"]) >= 0
    assert source_summary["breakpoint"]["checkpoint_ref"] == "rtchk:source:7"

    checkout_result = checkout_task_run_for_resume(
        host,
        "taskrun:rollout-breakpoint",
        user_instruction="继续刚才的工作",
        turn_id="turn:rollout-breakpoint:2",
    )
    child_task = dict(checkout_result.get("task_run") or {})
    child_summary = work_rollout_summary(host, str(child_task.get("task_run_id") or ""))
    lineage = dict(child_summary.get("lineage") or {})

    assert checkout_result["ok"] is True
    assert lineage["parent_task_run_id"] == "taskrun:rollout-breakpoint"
    assert lineage["forked_from_event_offset"] == source_summary["breakpoint"]["event_offset"]
    assert lineage["forked_from_checkpoint_ref"] == "rtchk:source:7"
    assert child_summary["breakpoint"]["event_offset"] == source_summary["breakpoint"]["event_offset"]


def _seed_active_work(runtime, *, task_run_id: str = "taskrun:active-work", session_id: str = "session-active-work", status: str = "waiting_executor") -> str:
    host = runtime.single_agent_runtime_host
    contract = TaskRunContract(
        contract_id=f"task-contract:{task_run_id.replace(':', '-')}",
        contract_source="test",
        user_visible_goal="继续优化会话体验。",
        task_run_goal="继续优化会话体验。",
        completion_criteria=("同一个当前工作可以被自然语言控制",),
    )
    contract_ref = host.runtime_objects.put_object("task_run_contract", contract.contract_id, contract.to_dict())
    lifecycle = TaskLifecycleRecord(
        task_run_id=task_run_id,
        contract_ref=contract_ref,
        status=status,
        created_at=1.0,
        updated_at=1.0,
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
            created_at=1.0,
            updated_at=1.0,
            diagnostics={"contract": contract.to_dict(), "latest_step_summary": "正在整理上下文，准备继续处理。"},
        )
    )
    return task_run_id


def test_active_work_turn_policy_repairs_control_only_to_reply_then_control() -> None:
    from harness.loop.active_work import active_work_turn_decision_from_payload

    decision = active_work_turn_decision_from_payload(
        {
            "authority": "harness.loop.active_work_turn_decision",
            "action": "continue_active_work",
            "turn_response_policy": "active_work_only",
            "continuation_strategy": "same_run_resume",
            "relation_to_current_work": "current_work",
            "evidence": "用户说继续当前工作",
            "response": "好，我接着处理。",
            "confidence": 0.95,
        },
        user_message="继续当前工作",
    )

    assert decision.action == "continue_active_work"
    assert decision.turn_response_policy == "answer_then_active_work"
    assert decision.answer_obligation == "acknowledgement_only"
    assert decision.continuation_strategy == "same_run_resume"


def test_active_work_router_requires_current_work_relation_before_intercepting_turn() -> None:
    class LegacyShapeActiveWorkModelRuntime:
        def __init__(self) -> None:
            self.active_work_decision_count = 0

        async def invoke_messages(self, messages, **_kwargs):
            content = str(messages or "")
            if "harness.loop.active_work_turn_decision.input" in content:
                self.active_work_decision_count += 1
                return SimpleNamespace(
                    content=json.dumps(
                        {
                            "authority": "harness.loop.active_work_turn_decision",
                            "action": "answer_about_active_work",
                            "response": "现在是正在处理。",
                            "confidence": 0.95,
                        },
                        ensure_ascii=False,
                    )
                )
            return SimpleNamespace(content=json.dumps(_action_request(action_type="respond", final_answer="普通回复。"), ensure_ascii=False))

    model = LegacyShapeActiveWorkModelRuntime()
    runtime = build_query_runtime(model_runtime=model)
    task_run_id = _seed_active_work(runtime, task_run_id="taskrun:active-work-route-gate")

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(QueryRequest(session_id="session-active-work", message="解释一下 LangGraph 的 checkpoint 机制")):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    trace = runtime.single_agent_runtime_host.get_trace(task_run_id, include_payloads=True)
    event_types = [str(dict(item).get("event_type") or "") for item in list(dict(trace or {}).get("events") or [])]

    assert model.active_work_decision_count == 1
    assert any(event.get("type") == "done" and str(event.get("content") or "") == "普通回复。" for event in events)
    assert any(event.get("type") == "runtime_assembly_compiled" for event in events)
    assert "task_run_resume_requested" not in event_types
    assert "active_task_steer_recorded" not in event_types


def test_conversation_only_capability_bypasses_active_work_router() -> None:
    model = _ActiveWorkDecisionModelRuntime([
        {
            "authority": "harness.loop.active_work_turn_decision",
            "action": "continue_active_work",
            "relation_to_current_work": "current_work",
            "evidence": "用户说继续当前工作",
            "response": "不应该进入当前工作。",
            "confidence": 0.99,
        }
    ])
    runtime = build_query_runtime(model_runtime=model)
    task_run_id = _seed_active_work(runtime, task_run_id="taskrun:conversation-only-active-work")

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            QueryRequest(
                session_id="session-active-work",
                message="修复了吗",
                soul_id="hebo",
                task_selection={"control_capabilities": {"conversation_only": True}},
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    trace = runtime.single_agent_runtime_host.get_trace(task_run_id, include_payloads=True)
    event_types = [str(dict(item).get("event_type") or "") for item in list(dict(trace or {}).get("events") or [])]

    assert model.active_work_decision_count == 0
    assert any(event.get("type") == "runtime_assembly_compiled" for event in events)
    assert any(event.get("type") == "done" and str(event.get("content") or "") == "普通回复。" for event in events)
    assert "task_run_resume_requested" not in event_types
    assert "active_task_steer_recorded" not in event_types
    assert "task_run_executor_scheduled" not in event_types


def test_active_work_router_is_gated_by_runtime_assembly_context_policy() -> None:
    model = _ActiveWorkDecisionModelRuntime([
        {
            "authority": "harness.loop.active_work_turn_decision",
            "action": "continue_active_work",
            "relation_to_current_work": "current_work",
            "evidence": "用户说继续当前工作",
            "response": "不应该进入当前工作。",
            "confidence": 0.99,
        }
    ])
    runtime = build_query_runtime(model_runtime=model)
    task_run_id = _seed_active_work(runtime, task_run_id="taskrun:active-work-context-disabled")

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            QueryRequest(
                session_id="session-active-work",
                message="继续当前工作",
                task_selection={
                    "runtime_policy": {
                        "task_lifecycle_policy": {"request_task_run": True},
                        "context_policy": {"task_context": "available", "active_work_context": "disabled"},
                    },
                },
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    assembly = dict(next(event for event in events if event.get("type") == "runtime_assembly_compiled").get("runtime_assembly") or {})
    profile = dict(assembly.get("profile") or {})
    trace = runtime.single_agent_runtime_host.get_trace(task_run_id, include_payloads=True)
    event_types = [str(dict(item).get("event_type") or "") for item in list(dict(trace or {}).get("events") or [])]

    assert dict(profile.get("context_policy") or {}).get("active_work_context") == "disabled"
    assert model.active_work_decision_count == 0
    assert any(event.get("type") == "done" and str(event.get("content") or "") == "普通回复。" for event in events)
    assert "task_run_resume_requested" not in event_types
    assert "active_task_steer_recorded" not in event_types
    assert "task_run_executor_scheduled" not in event_types


def test_active_work_router_coerces_question_turns_to_status_answer() -> None:
    model = _ActiveWorkDecisionModelRuntime([
        {
            "authority": "harness.loop.active_work_turn_decision",
            "action": "continue_active_work",
            "turn_response_policy": "active_work_only",
            "user_turn_kind": "question",
            "answer_obligation": "direct_answer_required",
            "relation_to_current_work": "current_work",
            "evidence": "用户在问当前工作是否已经完成",
            "response": "我会继续推进。",
            "confidence": 0.98,
        }
    ])
    runtime = build_query_runtime(model_runtime=model)
    task_run_id = _seed_active_work(runtime, task_run_id="taskrun:question-coerced-to-status")

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(QueryRequest(session_id="session-active-work", message="到底修复了没有")):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    trace = runtime.single_agent_runtime_host.get_trace(task_run_id, include_payloads=True)
    event_types = [str(dict(item).get("event_type") or "") for item in list(dict(trace or {}).get("events") or [])]
    task_run = runtime.single_agent_runtime_host.state_index.get_task_run(task_run_id)

    assert model.active_work_decision_count == 1
    assert any(event.get("type") == "done" and "现在是" in str(event.get("content") or "") for event in events)
    assert any(event.get("type") == "done" and "我会继续推进" not in str(event.get("content") or "") for event in events)
    assert "task_run_resume_requested" not in event_types
    assert "task_run_executor_scheduled" not in event_types
    assert task_run is not None
    assert task_run.status == "waiting_executor"


def test_active_work_router_coerces_complaint_turns_to_status_answer() -> None:
    model = _ActiveWorkDecisionModelRuntime([
        {
            "authority": "harness.loop.active_work_turn_decision",
            "action": "continue_active_work",
            "turn_response_policy": "active_work_only",
            "user_turn_kind": "complaint",
            "answer_obligation": "direct_answer_required",
            "relation_to_current_work": "current_work",
            "evidence": "用户质疑为什么这么简单的任务耗时很久",
            "response": "我会继续处理。",
            "confidence": 0.98,
        }
    ])
    runtime = build_query_runtime(model_runtime=model)
    task_run_id = _seed_active_work(runtime, task_run_id="taskrun:complaint-coerced-to-status")

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(QueryRequest(session_id="session-active-work", message="还没做完吗。这么简单的修复任务为什么你改这么长时间")):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    trace = runtime.single_agent_runtime_host.get_trace(task_run_id, include_payloads=True)
    event_types = [str(dict(item).get("event_type") or "") for item in list(dict(trace or {}).get("events") or [])]
    task_run = runtime.single_agent_runtime_host.state_index.get_task_run(task_run_id)

    assert model.active_work_decision_count == 1
    assert any(event.get("type") == "done" and "现在是" in str(event.get("content") or "") for event in events)
    assert "task_run_resume_requested" not in event_types
    assert "task_run_executor_scheduled" not in event_types
    assert task_run is not None
    assert task_run.status == "waiting_executor"


def test_active_work_router_can_answer_user_first_then_continue_task() -> None:
    model = _ActiveWorkDecisionModelRuntime([
        {
            "authority": "harness.loop.active_work_turn_decision",
            "action": "answer_then_continue_active_work",
            "turn_response_policy": "answer_then_active_work",
            "continuation_strategy": "same_run_resume",
            "relation_to_current_work": "current_work",
            "evidence": "用户问当前修复是否完成，并希望任务继续推进",
            "response": "回答后继续处理。",
            "confidence": 0.96,
        }
    ])
    runtime = build_query_runtime(model_runtime=model)
    task_run_id = _seed_active_work(runtime, task_run_id="taskrun:answer-then-continue")

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(QueryRequest(session_id="session-active-work", message="先说下修复了吗，然后继续处理")):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    trace = runtime.single_agent_runtime_host.get_trace(task_run_id, include_payloads=True)
    event_types = [str(dict(item).get("event_type") or "") for item in list(dict(trace or {}).get("events") or [])]
    task_run = runtime.single_agent_runtime_host.state_index.get_task_run(task_run_id)

    assert model.active_work_decision_count == 1
    assert any(event.get("type") == "runtime_assembly_compiled" for event in events)
    assert not any(event.get("type") == "harness_run_started" for event in events)
    assert any(event.get("type") == "done" and str(event.get("content") or "") == "回答后继续处理。" for event in events)
    assert "task_run_resume_requested" in event_types
    assert "task_run_executor_scheduled" in event_types
    assert task_run is not None
    assert task_run.status == "running"


def test_interrupted_work_candidate_does_not_checkout_without_context_match() -> None:
    from harness.loop.task_executor import stop_task_run

    model = _ActiveWorkDecisionModelRuntime([
        {
            "authority": "harness.loop.active_work_turn_decision",
            "action": "normal_response",
            "turn_response_policy": "answer_only",
            "relation_to_current_work": "independent_turn",
            "evidence": "",
            "response": "",
            "confidence": 0.9,
        }
    ])
    runtime = build_query_runtime(model_runtime=model)
    host = runtime.single_agent_runtime_host
    source_task_run_id = _seed_active_work(
        runtime,
        task_run_id="taskrun:interrupted-unrelated-turn",
        session_id="session-interrupted-unrelated-turn",
    )
    stop_task_run(host, source_task_run_id, reason="用户停止")

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(QueryRequest(session_id="session-interrupted-unrelated-turn", message="解释一下模型配置有什么区别")):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    source_task = host.state_index.get_task_run(source_task_run_id)
    source_events = [
        str(dict(item).get("event_type") or "")
        for item in list(dict(host.get_trace(source_task_run_id, include_payloads=False) or {}).get("events") or [])
    ]
    child_runs = [
        item
        for item in host.state_index.list_session_task_runs("session-interrupted-unrelated-turn")
        if str(item.task_run_id).startswith(f"{source_task_run_id}:checkout:")
    ]

    assert model.active_work_decision_count == 1
    assert any(event.get("type") == "done" and str(event.get("content") or "") == "普通回复。" for event in events)
    assert source_task is not None
    assert source_task.status == "aborted"
    assert child_runs == []
    assert "task_run_checkout_created" not in source_events
    assert "task_run_executor_scheduled" not in source_events


def test_active_work_continue_emits_user_feedback_and_schedules_executor() -> None:
    model = _ActiveWorkDecisionModelRuntime([
        {
            "authority": "harness.loop.active_work_turn_decision",
            "action": "continue_active_work",
            "turn_response_policy": "active_work_only",
            "continuation_strategy": "same_run_resume",
            "relation_to_current_work": "current_work",
            "evidence": "用户明确要求继续当前工作",
            "response": "我会继续处理当前工作。",
            "confidence": 0.96,
        }
    ])
    runtime = build_query_runtime(model_runtime=model)
    task_run_id = _seed_active_work(runtime, task_run_id="taskrun:feedback-before-schedule")

    async def _run_incrementally() -> tuple[list[dict[str, object]], str, str]:
        events: list[dict[str, object]] = []
        stream = runtime.astream(QueryRequest(session_id="session-active-work", message="继续当前工作"))
        status_when_done = ""
        while True:
            event = await stream.__anext__()
            events.append(event)
            if event.get("type") == "done":
                task_run = runtime.single_agent_runtime_host.state_index.get_task_run(task_run_id)
                status_when_done = str(getattr(task_run, "status", "") or "")
                break
        try:
            await stream.__anext__()
        except StopAsyncIteration:
            pass
        task_run = runtime.single_agent_runtime_host.state_index.get_task_run(task_run_id)
        return events, status_when_done, str(getattr(task_run, "status", "") or "")

    events, status_when_done, final_status = asyncio.run(_run_incrementally())
    monitor = runtime.single_agent_runtime_host.get_task_run_live_monitor(task_run_id)
    step_events = [
        dict(getattr(item, "payload", {}) or {})
        for item in runtime.single_agent_runtime_host.event_log.list_events(task_run_id)
        if getattr(item, "event_type", "") == "step_summary_recorded"
    ]

    assert any(event.get("type") == "done" and str(event.get("content") or "") == "我会继续处理当前工作。" for event in events)
    assert status_when_done == "running"
    assert final_status == "running"
    assert monitor is not None
    assert monitor["latest_interaction_turn_id"] == "turn:session-active-work:1"
    assert any("持续汇报" in str(item.get("summary") or "") for item in step_events)


def test_active_work_continue_reuses_current_task_run_without_new_task() -> None:
    model = _ActiveWorkDecisionModelRuntime([
        {
            "authority": "harness.loop.active_work_turn_decision",
            "action": "continue_active_work",
            "continuation_strategy": "same_run_resume",
            "response": "好，我接着处理。",
            "confidence": 0.94,
        }
    ])
    runtime = build_query_runtime(model_runtime=model)
    task_run_id = _seed_active_work(runtime)

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(QueryRequest(session_id="session-active-work", message="继续")):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    task_runs = runtime.single_agent_runtime_host.list_session_traces("session-active-work")["task_run_count"]
    task_run = runtime.single_agent_runtime_host.state_index.get_task_run(task_run_id)
    event_types = [
        str(dict(item).get("event_type") or "")
        for item in list(dict(runtime.single_agent_runtime_host.get_trace(task_run_id, include_payloads=False) or {}).get("events") or [])
    ]

    assert model.active_work_decision_count == 1
    assert any(event.get("type") == "done" and "接着处理" in str(event.get("content") or "") for event in events)
    assert not any(event.get("type") == "harness_run_started" for event in events)
    assert task_runs == 1
    assert task_run is not None
    assert task_run.status == "running"
    assert "task_run_resume_requested" in event_types
    assert "task_run_executor_scheduled" in event_types


def test_active_work_continue_user_aborted_creates_checkout_without_reviving_source() -> None:
    from harness.loop.task_executor import stop_task_run
    from harness.loop.work_rollout import work_rollout_summary

    model = _ActiveWorkDecisionModelRuntime([
        {
            "authority": "harness.loop.active_work_turn_decision",
            "action": "continue_active_work",
            "continuation_strategy": "checkout_fork",
            "response": "好，我会先检查上次中断处的现状，再接着处理。",
            "confidence": 0.95,
        }
    ])
    runtime = build_query_runtime(model_runtime=model)
    host = runtime.single_agent_runtime_host
    source_task_run_id = _seed_active_work(
        runtime,
        task_run_id="taskrun:active-work-aborted",
        session_id="session-active-work-aborted",
    )
    stop_result = stop_task_run(host, source_task_run_id, reason="用户停止")

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(QueryRequest(session_id="session-active-work-aborted", message="继续刚才那个任务")):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    source_task = host.state_index.get_task_run(source_task_run_id)
    task_runs = host.state_index.list_session_task_runs("session-active-work-aborted")
    child_runs = [
        item
        for item in task_runs
        if str(item.task_run_id).startswith(f"{source_task_run_id}:checkout:")
    ]
    child_task = child_runs[0] if child_runs else None
    source_events = [
        str(dict(item).get("event_type") or "")
        for item in list(dict(host.get_trace(source_task_run_id, include_payloads=False) or {}).get("events") or [])
    ]
    child_events = [
        str(dict(item).get("event_type") or "")
        for item in list(dict(host.get_trace(child_task.task_run_id, include_payloads=False) or {}).get("events") or [])
    ] if child_task is not None else []
    child_summary = work_rollout_summary(host, child_task.task_run_id if child_task is not None else "")

    assert stop_result["ok"] is True
    assert model.active_work_decision_count == 1
    assert any(event.get("type") == "done" and "检查上次中断处" in str(event.get("content") or "") for event in events)
    assert source_task is not None
    assert source_task.status == "aborted"
    assert source_task.terminal_reason == "user_aborted"
    assert "task_run_resume_requested" not in source_events
    assert child_task is not None
    assert dict(child_task.diagnostics or {}).get("origin_kind") == "checkout_resume"
    assert dict(dict(child_task.diagnostics or {}).get("lineage") or {}).get("parent_task_run_id") == source_task_run_id
    assert "task_run_checkout_created" in child_events
    assert "task_run_executor_scheduled" in child_events
    assert dict(child_summary.get("lineage") or {}).get("parent_task_run_id") == source_task_run_id


def test_interrupted_continue_requires_model_checkout_strategy() -> None:
    from harness.loop.task_executor import stop_task_run

    model = _ActiveWorkDecisionModelRuntime([
        {
            "authority": "harness.loop.active_work_turn_decision",
            "action": "continue_active_work",
            "response": "好，我接着处理。",
            "confidence": 0.95,
        }
    ])
    runtime = build_query_runtime(model_runtime=model)
    host = runtime.single_agent_runtime_host
    source_task_run_id = _seed_active_work(
        runtime,
        task_run_id="taskrun:interrupted-missing-strategy",
        session_id="session-interrupted-missing-strategy",
    )
    stop_task_run(host, source_task_run_id, reason="用户停止")

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(QueryRequest(session_id="session-interrupted-missing-strategy", message="继续刚才那个任务")):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    source_task = host.state_index.get_task_run(source_task_run_id)
    child_runs = [
        item
        for item in host.state_index.list_session_task_runs("session-interrupted-missing-strategy")
        if str(item.task_run_id).startswith(f"{source_task_run_id}:checkout:")
    ]
    source_events = [
        str(dict(item).get("event_type") or "")
        for item in list(dict(host.get_trace(source_task_run_id, include_payloads=False) or {}).get("events") or [])
    ]

    assert model.active_work_decision_count == 1
    assert any(event.get("type") == "done" and "已中断，可继续" in str(event.get("content") or "") for event in events)
    assert source_task is not None
    assert source_task.status == "aborted"
    assert child_runs == []
    assert "task_run_checkout_created" not in source_events
    assert "task_run_executor_scheduled" not in source_events


def test_active_work_continue_prefers_interrupted_task_over_stale_completed_executor_status() -> None:
    from harness.loop.task_executor import stop_task_run
    from harness.loop.work_rollout import work_rollout_summary

    model = _ActiveWorkDecisionModelRuntime([
        {
            "authority": "harness.loop.active_work_turn_decision",
            "action": "continue_active_work",
            "continuation_strategy": "checkout_fork",
            "response": "好，我会先检查上次中断处的现状，再接着处理。",
            "confidence": 0.95,
        }
    ])
    runtime = build_query_runtime(model_runtime=model)
    host = runtime.single_agent_runtime_host
    session_id = "session-active-work-stale-completed"
    completed_task_run_id = _seed_active_work(
        runtime,
        task_run_id="taskrun:active-work-stale-completed",
        session_id=session_id,
        status="completed",
    )
    completed_task = host.state_index.get_task_run(completed_task_run_id)
    assert completed_task is not None
    host.state_index.upsert_task_run(
        replace(
            completed_task,
            terminal_reason="completed",
            updated_at=1.0,
            diagnostics={
                **dict(completed_task.diagnostics or {}),
                "executor_status": "scheduled",
                "latest_step": "task_run_completed",
                "latest_step_summary": "任务合同已满足，处理流程已完成收尾并记录真实交付物证据。",
            },
        )
    )
    source_task_run_id = _seed_active_work(
        runtime,
        task_run_id="taskrun:active-work-interrupted-after-stale-completed",
        session_id=session_id,
    )
    stop_task_run(host, source_task_run_id, reason="用户停止")

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(QueryRequest(session_id=session_id, message="继续刚才那个任务")):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    task_runs = host.state_index.list_session_task_runs(session_id)
    child_runs = [
        item
        for item in task_runs
        if str(item.task_run_id).startswith(f"{source_task_run_id}:checkout:")
    ]
    source_task = host.state_index.get_task_run(source_task_run_id)
    completed_after = host.state_index.get_task_run(completed_task_run_id)
    child_task = child_runs[0] if child_runs else None
    child_summary = work_rollout_summary(host, child_task.task_run_id if child_task is not None else "")

    assert model.active_work_decision_count == 1
    assert any(event.get("type") == "done" and "检查上次中断处" in str(event.get("content") or "") for event in events)
    assert source_task is not None
    assert source_task.status == "aborted"
    assert source_task.terminal_reason == "user_aborted"
    assert completed_after is not None
    assert completed_after.status == "completed"
    assert child_task is not None
    assert dict(child_task.diagnostics or {}).get("origin_kind") == "checkout_resume"
    assert dict(dict(child_task.diagnostics or {}).get("lineage") or {}).get("parent_task_run_id") == source_task_run_id
    assert dict(child_summary.get("lineage") or {}).get("parent_task_run_id") == source_task_run_id


def test_active_work_append_instruction_to_user_aborted_creates_checkout_with_instruction() -> None:
    from harness.loop.task_executor import stop_task_run
    from harness.loop.work_rollout import work_rollout_summary

    model = _ActiveWorkDecisionModelRuntime([
        {
            "authority": "harness.loop.active_work_turn_decision",
            "action": "append_instruction_to_active_work",
            "continuation_strategy": "checkout_fork",
            "response": "收到，我会按这个补充方向继续处理。",
            "appended_instruction": "恢复后先检查当前文件状态，再继续实现。",
            "confidence": 0.95,
        }
    ])
    runtime = build_query_runtime(model_runtime=model)
    host = runtime.single_agent_runtime_host
    source_task_run_id = _seed_active_work(
        runtime,
        task_run_id="taskrun:active-work-aborted-instruction",
        session_id="session-active-work-aborted-instruction",
    )
    stop_task_run(host, source_task_run_id, reason="用户停止")

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(QueryRequest(session_id="session-active-work-aborted-instruction", message="继续，但是先检查文件状态")):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    source_task = host.state_index.get_task_run(source_task_run_id)
    child_runs = [
        item
        for item in host.state_index.list_session_task_runs("session-active-work-aborted-instruction")
        if str(item.task_run_id).startswith(f"{source_task_run_id}:checkout:")
    ]
    child_task = child_runs[0] if child_runs else None
    child_summary = work_rollout_summary(host, child_task.task_run_id if child_task is not None else "")
    child_contract = host.runtime_objects.get_object(child_task.task_contract_ref) if child_task is not None else {}
    resume_context = dict(dict(child_contract.get("prompt_contract") or {}).get("resume_context") or {})
    current_revision = dict(child_contract.get("current_user_revision") or {})

    assert any(event.get("type") == "done" and "补充方向" in str(event.get("content") or "") for event in events)
    assert source_task is not None
    assert source_task.status == "aborted"
    assert source_task.terminal_reason == "user_aborted"
    assert child_task is not None
    assert dict(child_task.diagnostics or {}).get("origin_kind") == "checkout_resume"
    assert "user_instruction" not in resume_context
    assert child_contract.get("current_user_instruction") == "恢复后先检查当前文件状态，再继续实现。"
    assert current_revision.get("user_instruction") == "恢复后先检查当前文件状态，再继续实现。"
    assert current_revision.get("status") == "pending_agent_triage"
    assert child_summary["agent_brief_output"] == "恢复后先检查当前文件状态，再继续实现。"


def test_active_work_pause_and_status_are_natural_language_controls() -> None:
    model = _ActiveWorkDecisionModelRuntime([
        {
            "authority": "harness.loop.active_work_turn_decision",
            "action": "pause_active_work",
            "response": "好，我先停在这里。",
            "confidence": 0.93,
        },
        {
            "authority": "harness.loop.active_work_turn_decision",
            "action": "answer_about_active_work",
            "response": "",
            "confidence": 0.92,
        },
    ])
    runtime = build_query_runtime(model_runtime=model)
    task_run_id = _seed_active_work(runtime, task_run_id="taskrun:active-work-pause")

    async def _send(message: str) -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(QueryRequest(session_id="session-active-work", message=message)):
            events.append(event)
        return events

    pause_events = asyncio.run(_send("先停一下"))
    status_events = asyncio.run(_send("现在到哪了"))
    paused_task = runtime.single_agent_runtime_host.state_index.get_task_run(task_run_id)
    done_text = "\n".join(str(event.get("content") or "") for event in [*pause_events, *status_events] if event.get("type") == "done")

    assert model.active_work_decision_count == 2
    assert paused_task is not None
    assert str(dict(dict(paused_task.diagnostics or {}).get("runtime_control") or {}).get("state") or "") == "paused"
    assert "先停在这里" in done_text
    assert "现在是已暂停" in done_text
    assert "TaskRun" not in done_text
    assert "执行器" not in done_text
    assert "正式任务" not in done_text


def test_active_work_appends_user_instruction_to_current_task_run() -> None:
    model = _ActiveWorkDecisionModelRuntime([
        {
            "authority": "harness.loop.active_work_turn_decision",
            "action": "append_instruction_to_active_work",
            "continuation_strategy": "same_run_resume",
            "response": "收到，我会按这个补充方向继续处理。",
            "appended_instruction": "把界面改得更自然，少一点开发痕迹。",
            "confidence": 0.95,
        }
    ])
    runtime = build_query_runtime(model_runtime=model)
    task_run_id = _seed_active_work(runtime, task_run_id="taskrun:active-work-instruction")

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(QueryRequest(session_id="session-active-work", message="按刚才方向改，别露出开发细节")):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    trace = runtime.single_agent_runtime_host.get_trace(task_run_id, include_payloads=True)
    instruction_events = [
        dict(item)
        for item in list(dict(trace or {}).get("events") or [])
        if str(dict(item).get("event_type") or "") == "active_task_steer_recorded"
    ]
    payload = dict(instruction_events[0].get("payload") or {}) if instruction_events else {}
    steer = dict(payload.get("steer") or {})

    assert any(event.get("type") == "done" and "补充方向" in str(event.get("content") or "") for event in events)
    assert len(instruction_events) == 1
    assert steer.get("content") == "把界面改得更自然，少一点开发痕迹。"
    assert steer.get("consumption_state") == "pending"


def test_active_work_running_continue_records_steer_without_duplicate_executor() -> None:
    model = _ActiveWorkDecisionModelRuntime([
        {
            "authority": "harness.loop.active_work_turn_decision",
            "action": "continue_active_work",
            "continuation_strategy": "already_running",
            "response": "我正在接着处理，新的进展会继续更新在这里。",
            "appended_instruction": "优先修美术资源加载",
            "confidence": 0.95,
        }
    ])
    runtime = build_query_runtime(model_runtime=model)
    task_run_id = _seed_active_work(runtime, task_run_id="taskrun:active-work-running-steer", status="running")
    task_run = runtime.single_agent_runtime_host.state_index.get_task_run(task_run_id)
    runtime.single_agent_runtime_host.state_index.upsert_task_run(
        replace(task_run, diagnostics={**dict(task_run.diagnostics or {}), "executor_status": "running"})
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(QueryRequest(session_id="session-active-work", message="继续，但优先修美术资源加载")):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    trace = runtime.single_agent_runtime_host.get_trace(task_run_id, include_payloads=True)
    event_types = [str(dict(item).get("event_type") or "") for item in list(dict(trace or {}).get("events") or [])]
    steer_events = [
        dict(item)
        for item in list(dict(trace or {}).get("events") or [])
        if str(dict(item).get("event_type") or "") == "active_task_steer_recorded"
    ]
    steer = dict(dict(steer_events[0].get("payload") or {}).get("steer") or {}) if steer_events else {}

    assert any(event.get("type") == "done" and "进展" in str(event.get("content") or "") for event in events)
    assert "active_task_steer_recorded" in event_types
    assert "task_run_executor_scheduled" not in event_types
    assert steer.get("content") == "优先修美术资源加载"


def test_active_work_running_plain_continue_does_not_create_work_instruction() -> None:
    model = _ActiveWorkDecisionModelRuntime([
        {
            "authority": "harness.loop.active_work_turn_decision",
            "action": "continue_active_work",
            "continuation_strategy": "already_running",
            "response": "我正在接着处理，新的进展会继续更新在这里。",
            "confidence": 0.95,
        }
    ])
    runtime = build_query_runtime(model_runtime=model)
    task_run_id = _seed_active_work(runtime, task_run_id="taskrun:active-work-running-plain-continue", status="running")
    task_run = runtime.single_agent_runtime_host.state_index.get_task_run(task_run_id)
    runtime.single_agent_runtime_host.state_index.upsert_task_run(
        replace(task_run, diagnostics={**dict(task_run.diagnostics or {}), "executor_status": "running"})
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(QueryRequest(session_id="session-active-work", message="继续")):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    trace = runtime.single_agent_runtime_host.get_trace(task_run_id, include_payloads=True)
    event_types = [str(dict(item).get("event_type") or "") for item in list(dict(trace or {}).get("events") or [])]

    assert any(event.get("type") == "done" and "进展" in str(event.get("content") or "") for event in events)
    assert "active_task_steer_recorded" not in event_types
    assert "task_run_executor_scheduled" not in event_types


def test_pending_active_task_steer_is_injected_into_task_execution_packet() -> None:
    from harness.loop.task_executor import append_user_work_instruction

    model = _TaskExecutorSequenceModelRuntime(
        [
            _action_request(
                action_type="respond",
                final_answer="第一次不能完成。",
            ),
            _action_request(
                action_type="respond",
                final_answer="已按补充要求完成。",
                diagnostics={"consumed_steer_refs": []},
            ),
        ],
        agent_turn_action_request=_action_request(action_type="respond", final_answer="unused"),
    )
    runtime = build_query_runtime(model_runtime=model)
    host = runtime.single_agent_runtime_host
    task_run_id = _seed_active_work(runtime, task_run_id="taskrun:active-work-steer-packet")
    steer_result = append_user_work_instruction(
        host,
        task_run_id,
        content="优先修复美术资源加载。",
        turn_id="turn:session-active-work:22",
        intent="conversation_instruction",
    )
    steer_id = str(dict(steer_result.get("steer") or {}).get("steer_id") or "")
    model.task_actions[1]["diagnostics"] = {
        "test_action_request": True,
        "consumed_steer_refs": [steer_id],
        "contract_revision_decisions": [
            {
                "steer_ref": steer_id,
                "status": "accepted",
                "reason": "补充要求作为当前修复优先级纳入执行。",
            }
        ],
    }

    result = asyncio.run(runtime.execute_task_run(task_run_id, max_steps=2))
    trace = host.get_trace(task_run_id, include_payloads=True)
    packet_events = [
        dict(item)
        for item in list(dict(trace or {}).get("events") or [])
        if str(dict(item).get("event_type") or "") == "runtime_invocation_packet_compiled"
    ]
    steer_events = [
        dict(item)
        for item in list(dict(trace or {}).get("events") or [])
        if str(dict(item).get("event_type") or "") == "active_task_steer_consumed"
    ]
    repair_events = [
        dict(item)
        for item in list(dict(trace or {}).get("events") or [])
        if str(dict(item).get("event_type") or "") == "task_completion_repair_required"
    ]
    payload = dict(packet_events[0].get("payload") or {})
    packet = dict(payload.get("packet") or {})
    messages = list(packet.get("model_messages") or [])
    message_text = json.dumps(messages, ensure_ascii=False)
    revision_events = [
        dict(item)
        for item in list(dict(trace or {}).get("events") or [])
        if str(dict(item).get("event_type") or "") == "task_contract_revision_recorded"
    ]
    revision_decision_events = [
        dict(item)
        for item in list(dict(trace or {}).get("events") or [])
        if str(dict(item).get("event_type") or "") == "task_contract_revision_decided"
    ]

    assert result["ok"] is True
    assert packet["packet_id"].startswith(f"rtpacket:{task_run_id}:task_execution:1:")
    assert "pending_user_steers" in message_text
    assert "active_contract_revisions" in message_text
    assert "优先修复美术资源加载。" in message_text
    assert repair_events
    assert revision_events
    assert revision_decision_events
    assert steer_events


def test_late_active_task_steer_blocks_completion_before_next_packet() -> None:
    from harness.loop.task_executor import append_user_work_instruction

    class LateSteerModelRuntime:
        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.release = asyncio.Event()
            self.cancelled = asyncio.Event()

        async def invoke_messages(self, messages, **kwargs):
            source = str(dict(kwargs.get("accounting_context") or {}).get("source") or "")
            if source == "harness.loop.task_executor.model_action":
                self.started.set()
                try:
                    await asyncio.wait_for(self.release.wait(), timeout=5)
                except asyncio.CancelledError:
                    self.cancelled.set()
                    raise
                return SimpleNamespace(
                    content=json.dumps(
                        _action_request(
                            action_type="respond",
                            final_answer="不应直接完成。",
                        ),
                        ensure_ascii=False,
                    )
                )
            return SimpleNamespace(content=json.dumps(_action_request(action_type="respond", final_answer="unused")))

    model = LateSteerModelRuntime()
    runtime = build_query_runtime(model_runtime=model)
    host = runtime.single_agent_runtime_host
    task_run_id = _seed_active_work(runtime, task_run_id="taskrun:late-steer-before-completion")

    async def _run() -> dict[str, object]:
        executor_task = asyncio.create_task(runtime.execute_task_run(task_run_id, max_steps=1))
        await asyncio.wait_for(model.started.wait(), timeout=5)
        append_user_work_instruction(
            host,
            task_run_id,
            content="模型调用等待期间追加的要求也必须阻断完成。",
            turn_id="turn:late-steer:1",
            intent="conversation_steer_while_model_waiting",
        )
        model.release.set()
        result = await asyncio.wait_for(executor_task, timeout=10)
        await asyncio.wait_for(model.cancelled.wait(), timeout=1)
        return result

    result = asyncio.run(_run())
    trace = host.get_trace(task_run_id, include_payloads=True)
    event_types = [str(dict(item).get("event_type") or "") for item in list(dict(trace or {}).get("events") or [])]
    task_run = host.state_index.get_task_run(task_run_id)

    assert result["ok"] is False
    assert result["error"] == "user_interrupt_replan_required"
    assert "active_task_steer_recorded" in event_types
    assert "task_run_replan_requested" in event_types
    assert "task_run_interrupted_for_replan" in event_types
    assert task_run is not None
    assert task_run.status == "waiting_executor"


def test_running_task_steer_cancels_inflight_model_call_and_replans() -> None:
    from harness.loop.task_executor import append_user_work_instruction

    class InterruptibleModelRuntime:
        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.cancelled = asyncio.Event()

        async def invoke_messages(self, messages, **kwargs):
            source = str(dict(kwargs.get("accounting_context") or {}).get("source") or "")
            if source == "harness.loop.task_executor.model_action":
                self.started.set()
                try:
                    await asyncio.sleep(60)
                except asyncio.CancelledError:
                    self.cancelled.set()
                    raise
            return SimpleNamespace(content=json.dumps(_action_request(action_type="respond", final_answer="unused")))

    model = InterruptibleModelRuntime()
    runtime = build_query_runtime(model_runtime=model)
    host = runtime.single_agent_runtime_host
    task_run_id = _seed_active_work(runtime, task_run_id="taskrun:running-steer-replan")

    async def _run() -> dict[str, object]:
        executor_task = asyncio.create_task(runtime.execute_task_run(task_run_id, max_steps=2))
        await asyncio.wait_for(model.started.wait(), timeout=5)
        append_user_work_instruction(
            host,
            task_run_id,
            content="推翻之前方向，先重新规划并优先处理新要求。",
            turn_id="turn:running-steer-replan:1",
            intent="conversation_steer_while_running",
        )
        result = await asyncio.wait_for(executor_task, timeout=5)
        await asyncio.wait_for(model.cancelled.wait(), timeout=1)
        return result

    result = asyncio.run(_run())
    task_run = host.state_index.get_task_run(task_run_id)
    trace = host.get_trace(task_run_id, include_payloads=True)
    event_types = [str(dict(item).get("event_type") or "") for item in list(dict(trace or {}).get("events") or [])]
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})

    assert result["ok"] is False
    assert result["error"] == "user_interrupt_replan_required"
    assert task_run is not None
    assert task_run.status == "waiting_executor"
    assert diagnostics["executor_status"] == "waiting_executor"
    assert diagnostics["recovery_action"] == "resume_task_run"
    assert dict(diagnostics.get("runtime_control") or {}).get("state") == "interrupted_for_replan"
    assert "task_run_replan_requested" in event_types
    assert "task_run_interrupted_for_replan" in event_types


def test_running_task_pause_cancels_inflight_model_call_without_auto_replan() -> None:
    from harness.loop.task_executor import request_task_run_pause

    class InterruptibleModelRuntime:
        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.cancelled = asyncio.Event()

        async def invoke_messages(self, messages, **kwargs):
            source = str(dict(kwargs.get("accounting_context") or {}).get("source") or "")
            if source == "harness.loop.task_executor.model_action":
                self.started.set()
                try:
                    await asyncio.sleep(60)
                except asyncio.CancelledError:
                    self.cancelled.set()
                    raise
            return SimpleNamespace(content=json.dumps(_action_request(action_type="respond", final_answer="unused")))

    model = InterruptibleModelRuntime()
    runtime = build_query_runtime(model_runtime=model)
    host = runtime.single_agent_runtime_host
    task_run_id = _seed_active_work(runtime, task_run_id="taskrun:running-pause")

    async def _run() -> dict[str, object]:
        executor_task = asyncio.create_task(runtime.execute_task_run(task_run_id, max_steps=2))
        await asyncio.wait_for(model.started.wait(), timeout=5)
        request_task_run_pause(host, task_run_id, reason="test_pause", requested_by="user")
        result = await asyncio.wait_for(executor_task, timeout=5)
        await asyncio.wait_for(model.cancelled.wait(), timeout=1)
        return result

    result = asyncio.run(_run())
    task_run = host.state_index.get_task_run(task_run_id)
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})

    assert result["ok"] is False
    assert result["error"] == "task_run_paused"
    assert task_run is not None
    assert task_run.status == "waiting_executor"
    assert diagnostics["executor_status"] == "waiting_executor"
    assert dict(diagnostics.get("runtime_control") or {}).get("state") == "paused"


def test_running_task_stop_cancels_inflight_model_call_and_finishes_aborted() -> None:
    from harness.loop.task_executor import stop_task_run

    class InterruptibleModelRuntime:
        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.cancelled = asyncio.Event()

        async def invoke_messages(self, messages, **kwargs):
            source = str(dict(kwargs.get("accounting_context") or {}).get("source") or "")
            if source == "harness.loop.task_executor.model_action":
                self.started.set()
                try:
                    await asyncio.sleep(60)
                except asyncio.CancelledError:
                    self.cancelled.set()
                    raise
            return SimpleNamespace(content=json.dumps(_action_request(action_type="respond", final_answer="unused")))

    model = InterruptibleModelRuntime()
    runtime = build_query_runtime(model_runtime=model)
    host = runtime.single_agent_runtime_host
    task_run_id = _seed_active_work(runtime, task_run_id="taskrun:running-stop")

    async def _run() -> dict[str, object]:
        executor_task = asyncio.create_task(runtime.execute_task_run(task_run_id, max_steps=2))
        await asyncio.wait_for(model.started.wait(), timeout=5)
        stop_task_run(host, task_run_id, reason="test_stop", requested_by="user")
        result = await asyncio.wait_for(executor_task, timeout=5)
        await asyncio.wait_for(model.cancelled.wait(), timeout=1)
        return result

    result = asyncio.run(_run())
    task_run = host.state_index.get_task_run(task_run_id)
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})

    assert result["ok"] is False
    assert result["error"] == "user_aborted"
    assert task_run is not None
    assert task_run.status == "aborted"
    assert diagnostics["executor_status"] == "stopped"
    assert dict(diagnostics.get("runtime_control") or {}).get("state") == "stopped"
    assert "recovery_action" not in diagnostics
    assert "recoverable_error" not in diagnostics
    assert "pending_user_steer_count" not in diagnostics
    assert "active_contract_revision_count" not in diagnostics


def test_scheduler_restarts_after_running_steer_and_next_packet_contains_instruction() -> None:
    from harness.loop.task_executor import append_user_work_instruction

    class ReplanningModelRuntime:
        def __init__(self) -> None:
            self.first_started = asyncio.Event()
            self.first_cancelled = asyncio.Event()
            self.second_started = asyncio.Event()
            self.messages_by_call: list[str] = []
            self.host = None
            self.task_run_id = ""

        async def invoke_messages(self, messages, **kwargs):
            source = str(dict(kwargs.get("accounting_context") or {}).get("source") or "")
            if source != "harness.loop.task_executor.model_action":
                return SimpleNamespace(content=json.dumps(_action_request(action_type="respond", final_answer="unused")))
            self.messages_by_call.append(json.dumps(messages, ensure_ascii=False))
            if len(self.messages_by_call) == 1:
                self.first_started.set()
                try:
                    await asyncio.sleep(60)
                except asyncio.CancelledError:
                    self.first_cancelled.set()
                    raise
            self.second_started.set()
            steer_refs: list[str] = []
            if self.host is not None:
                from harness.loop.task_steering import list_pending_task_steers
                from harness.loop.task_contract_revision import list_active_task_contract_revisions

                steer_refs = [
                    str(item.get("steer_id") or "")
                    for item in list_pending_task_steers(self.host, self.task_run_id)
                    if str(item.get("steer_id") or "")
                ]
                revision_decisions = [
                    {"revision_id": str(item.get("revision_id") or ""), "status": "accepted"}
                    for item in list_active_task_contract_revisions(self.host, self.task_run_id)
                    if str(item.get("revision_id") or "")
                ]
            else:
                revision_decisions = []
            return SimpleNamespace(
                content=json.dumps(
                    _action_request(
                        action_type="respond",
                        final_answer="已按新要求完成。",
                        diagnostics={
                            "consumed_steer_refs": list(dict.fromkeys(steer_refs)),
                            "contract_revision_decisions": revision_decisions,
                        },
                    ),
                    ensure_ascii=False,
                )
            )

    model = ReplanningModelRuntime()
    runtime = build_query_runtime(model_runtime=model)
    host = runtime.single_agent_runtime_host
    task_run_id = _seed_active_work(runtime, task_run_id="taskrun:scheduler-replan")
    model.host = host
    model.task_run_id = task_run_id

    async def _run() -> None:
        schedule_result = runtime._schedule_active_task_run_executor(task_run_id, scheduler="test_scheduler_replan", max_steps=2)
        assert schedule_result["scheduled"] is True
        await asyncio.wait_for(model.first_started.wait(), timeout=5)
        append_user_work_instruction(
            host,
            task_run_id,
            content="自然语言改方向：先做稳定性高压验证。",
            turn_id="turn:scheduler-replan:1",
            intent="conversation_steer_while_running",
        )
        await asyncio.wait_for(model.first_cancelled.wait(), timeout=5)
        await asyncio.wait_for(model.second_started.wait(), timeout=5)
        for _ in range(100):
            task_run = host.state_index.get_task_run(task_run_id)
            if task_run is not None and task_run.status == "completed":
                return
            await asyncio.sleep(0.02)
        raise AssertionError("scheduler did not complete restarted task run")

    asyncio.run(_run())
    task_run = host.state_index.get_task_run(task_run_id)
    trace = host.get_trace(task_run_id, include_payloads=True)
    event_types = [str(dict(item).get("event_type") or "") for item in list(dict(trace or {}).get("events") or [])]

    assert task_run is not None
    assert task_run.status == "completed"
    assert model.first_cancelled.is_set()
    assert len(model.messages_by_call) >= 2
    assert "自然语言改方向：先做稳定性高压验证。" in model.messages_by_call[1]
    assert "task_run_interrupted_for_replan" in event_types
    assert "task_run_executor_rescheduled" in event_types
    assert "active_task_steer_consumed" in event_types


def test_runtime_policy_can_enable_conversation_only_with_soul_prompt() -> None:
    runtime = build_query_runtime(
        model_runtime=SingleMessageModelRuntimeStub(
            agent_turn_action_request=_action_request(
                action_type="request_task_run",
                task_contract_seed={
                    "user_visible_goal": "会话专用 turn 不应开启任务。",
                    "task_run_goal": "会话专用 turn 不应开启任务。",
                    "completion_criteria": ["不应执行"],
                },
            )
        )
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            QueryRequest(
                session_id="session-role",
                message="保持角色对话。",
                soul_id="hebo",
                task_selection={
                    "control_capabilities": {"conversation_only": True},
                    "runtime_policy": {"soul_prompt_policy": {"enabled": True}},
                },
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    assembly = dict(next(event for event in events if event.get("type") == "runtime_assembly_compiled").get("runtime_assembly") or {})
    profile = dict(assembly.get("profile") or {})
    route = dict(next(event for event in events if event.get("type") == "turn_route_decided").get("turn_route") or {})
    capabilities = dict(assembly.get("control_capabilities") or {})

    assert profile["profile_ref"] == "main_interactive_agent"
    assert dict(assembly.get("soul_role_prompt") or {}).get("content")
    assert capabilities.get("conversation_only") is True
    assert capabilities.get("may_request_task_run") is False
    assert route.get("route_kind") == "plain_conversation"
    assert not any(event.get("type") == "model_action_admission" for event in events)
    assert any(event.get("type") == "done" and str(event.get("content") or "") == "单轮收口回答" for event in events)
    assert not any(
        event.get("type") == "task_run_lifecycle_started"
        for event in events
    )


def test_task_run_permission_without_tools_uses_native_turn_for_direct_answer() -> None:
    runtime = build_query_runtime(model_runtime=SingleMessageModelRuntimeStub(content="可以直接回答。"))

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            QueryRequest(
                session_id="session-native-direct",
                message="这个问题可以直接回答。",
                task_selection={
                    "allowed_operations": ["op.model_response"],
                    "control_capabilities": {"may_request_task_run": True, "may_use_subagents": False},
                },
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    stream_types = [str(event.get("type") or "") for event in events]
    route = dict(next(event for event in events if event.get("type") == "turn_route_decided").get("turn_route") or {})

    assert route.get("route_kind") == "agent_native_turn"
    assert "agent_native_turn_started" in stream_types
    assert "runtime_invocation_packet" not in stream_types
    assert "model_action_request" not in stream_types
    assert "task_run_lifecycle_started" not in stream_types
    assert any(event.get("type") == "done" and str(event.get("content") or "") == "可以直接回答。" for event in events)


def test_native_turn_request_task_run_tool_starts_real_task_lifecycle() -> None:
    model = NativeToolCallModelRuntimeStub(
        tool_calls=[
            {
                "id": "call-request-task-run",
                "name": "request_task_run",
                "args": {
                    "user_visible_goal": "交付一个真实页面。",
                    "task_run_goal": "创建并验证一个真实 HTML 页面。",
                    "required_artifacts": [{"artifact_kind": "html_app", "user_visible_name": "页面"}],
                    "required_verifications": [{"verification_kind": "file_exists"}],
                    "completion_criteria": ["页面文件真实存在"],
                },
            }
        ]
    )
    runtime = build_query_runtime(model_runtime=model)

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            QueryRequest(
                session_id="session-native-taskrun",
                message="帮我做一个页面。",
                task_selection={
                    "allowed_operations": ["op.model_response"],
                    "control_capabilities": {"may_request_task_run": True, "may_use_subagents": False},
                },
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    stream_types = [str(event.get("type") or "") for event in events]
    route = dict(next(event for event in events if event.get("type") == "turn_route_decided").get("turn_route") or {})
    lifecycle = [event for event in events if event.get("type") == "task_run_lifecycle_started"][0]
    task_run_event = dict(lifecycle.get("event") or {})
    payload = dict(task_run_event.get("payload") or {})
    task_run = dict(payload.get("task_run") or {})
    task_run_id = str(task_run.get("task_run_id") or "")
    stored_task = runtime.single_agent_runtime_host.state_index.get_task_run(task_run_id)

    assert route.get("route_kind") == "agent_native_turn"
    assert model.seen_tools and any(dict(tool).get("name") == "request_task_run" for tool in list(model.seen_tools[0] or []))
    assert "runtime_invocation_packet" not in stream_types
    assert "model_action_request" not in stream_types
    assert "task_run_lifecycle_started" in stream_types
    assert task_run_id.startswith("taskrun:")
    assert stored_task is not None
    assert dict(getattr(stored_task, "diagnostics", {}) or {}).get("origin_kind") == "agent_native_tool_call"
    assert any(event.get("type") == "done" and "交付一个真实页面" in str(event.get("content") or "") for event in events)


def test_default_runtime_policy_rejects_soul_prompt_without_persona_leakage() -> None:
    runtime = build_query_runtime()

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            QueryRequest(
                session_id="session-standard-soul",
                message="普通对话。",
                soul_id="hebo",
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    assembly = dict(next(event for event in events if event.get("type") == "runtime_assembly_compiled").get("runtime_assembly") or {})

    assert dict(assembly.get("profile") or {}).get("profile_ref") == "main_interactive_agent"
    assert dict(assembly.get("soul_role_prompt") or {}) == {}
    assert {"capability": "soul_role_prompt", "reason": "soul_prompt_disabled_by_agent_profile"} in list(
        assembly.get("rejected_capabilities") or []
    )


def test_default_runtime_policy_exposes_plan_policy_without_soul_prompt() -> None:
    runtime = build_query_runtime()

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            QueryRequest(
                session_id="session-default-policy",
                message="执行需要真实产物的任务。",
                soul_id="hebo",
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    assembly = dict(next(event for event in events if event.get("type") == "runtime_assembly_compiled").get("runtime_assembly") or {})
    profile = dict(assembly.get("profile") or {})

    assert profile["profile_ref"] == "main_interactive_agent"
    assert dict(profile.get("planning_policy") or {}).get("specified_plan_allowed") is True
    assert dict(assembly.get("task_environment") or {}).get("environment_id") == "env.general.workspace"
    assert dict(profile.get("soul_prompt_policy") or {}).get("enabled") is False
    assert dict(assembly.get("soul_role_prompt") or {}) == {}


def test_runtime_policy_can_override_default_runtime_assembly() -> None:
    runtime = build_query_runtime()

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            QueryRequest(
                session_id="session-specific-mode-policy",
                message="按特定任务配置运行。",
                task_selection={
                    "task_environment_id": "env.creation.writing",
                    "runtime_policy": {
                        "planning_policy": {"plan_mode": "disabled", "specified_plan_allowed": False},
                        "task_lifecycle_policy": {"request_task_run": True, "requires_completion_evidence": True},
                        "self_review_policy": {"enabled": True, "checkpoints": ["before_final"]},
                    },
                },
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    assembly = dict(next(event for event in events if event.get("type") == "runtime_assembly_compiled").get("runtime_assembly") or {})
    profile = dict(assembly.get("profile") or {})

    assert profile["profile_ref"] == "main_interactive_agent"
    assert dict(profile.get("planning_policy") or {}).get("specified_plan_allowed") is False
    assert dict(profile.get("self_review_policy") or {}).get("checkpoints") == ["before_final"]
    assert dict(assembly.get("task_environment") or {}).get("environment_id") == "env.creation.writing"


def test_runtime_profile_uses_explicit_runtime_policy_and_environment() -> None:
    runtime = build_query_runtime()

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            QueryRequest(
                session_id="session-custom-mode-policy",
                message="按显式运行策略执行。",
                task_selection={"task_environment_id": "env.development.readonly"},
                runtime_profile={
                    "runtime_policy": {
                        "interaction_policy": {"style": "custom_review"},
                        "planning_policy": {"plan_mode": "disabled"},
                        "task_lifecycle_policy": {"request_task_run": False},
                        "tool_exposure_policy": {
                            "read_only_tools_only": True,
                            "operation_ceiling": ["op.model_response", "op.read_file"],
                        },
                        "self_review_policy": {"enabled": True, "before_final": "strict_review"},
                    },
                },
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    assembly = dict(next(event for event in events if event.get("type") == "runtime_assembly_compiled").get("runtime_assembly") or {})
    profile = dict(assembly.get("profile") or {})

    assert profile["profile_ref"] == "main_interactive_agent"
    assert dict(profile.get("interaction_policy") or {}).get("style") == "custom_review"
    assert dict(profile.get("task_lifecycle_policy") or {}).get("request_task_run") is False
    assert dict(profile.get("self_review_policy") or {}).get("before_final") == "strict_review"
    assert dict(assembly.get("task_environment") or {}).get("environment_id") == "env.development.readonly"


def test_turn_packet_does_not_expose_legacy_task_goal_type_from_selection() -> None:
    class CaptureModelRuntime:
        def __init__(self) -> None:
            self.messages: list[object] = []

        async def invoke_messages(self, messages, **_kwargs):
            self.messages = list(messages)
            return SimpleNamespace(content=json.dumps(_action_request(action_type="respond", final_answer="ok")))

    model = CaptureModelRuntime()
    runtime = build_query_runtime(model_runtime=model)

    async def _collect() -> None:
        async for _event in runtime.astream(
            QueryRequest(
                session_id="session-no-legacy-goal-type",
                message="做一个小游戏。",
                task_selection={"task_goal_type": "code_fix_execution", "selected_task_id": "legacy"},
            )
        ):
            pass

    asyncio.run(_collect())
    packet_payload = json.dumps(model.messages, ensure_ascii=False)

    assert "task_selection" not in packet_payload
    assert "code_fix_execution" not in packet_payload


def test_main_session_model_action_writes_prompt_accounting_ledger() -> None:
    class AccountingModelRuntime(SingleMessageModelRuntimeStub):
        def __init__(self) -> None:
            super().__init__(
                agent_turn_action_request=_action_request(
                    action_type="respond",
                    final_answer="ok",
                )
            )
            self.ledger = None
            self.serializer = CanonicalPromptSerializer()
            self.cache_planner = PromptCachePlanner()

        def attach_prompt_accounting_ledger(self, ledger):
            self.ledger = ledger

        async def invoke_messages(self, messages, **kwargs):
            response = await super().invoke_messages(messages, **kwargs)
            context = dict(kwargs.get("accounting_context") or {})
            if self.ledger is not None and context:
                request_id = str(context.get("request_id") or "modelreq:test")
                run_id = str(context.get("run_id") or context.get("task_run_id") or "")
                task_run_id = str(context.get("task_run_id") or "")
                segment_map = self.serializer.build_segment_map(
                    request_id=request_id,
                    messages=list(messages),
                    run_id=run_id,
                    task_run_id=task_run_id,
                    session_id=str(context.get("session_id") or ""),
                    provider="stub",
                    model="stub-model",
                )
                self.ledger.record_segment_map(segment_map)
                self.ledger.record_token_usage(
                    ModelTokenUsageRecord(
                        usage_id=f"tokuse:{request_id}:local_prediction",
                        request_id=request_id,
                        run_id=run_id,
                        task_run_id=task_run_id,
                        session_id=str(context.get("session_id") or ""),
                        provider="stub",
                        model="stub-model",
                        source="local_prediction",
                        prompt_tokens=segment_map.predicted_prompt_tokens,
                        total_tokens=segment_map.predicted_prompt_tokens,
                        created_at=1.0,
                    )
                )
                provider_response = SimpleNamespace(
                    content=response.content,
                    usage_metadata={"input_tokens": 12, "output_tokens": 3},
                )
                provider_usage = extract_provider_usage(
                    provider_response,
                    request_id=request_id,
                    run_id=run_id,
                    task_run_id=task_run_id,
                    session_id=str(context.get("session_id") or ""),
                    provider="stub",
                    model="stub-model",
                    created_at=2.0,
                )
                self.ledger.record_token_usage(provider_usage)
                self.ledger.record_prompt_cache(
                    self.cache_planner.with_provider_usage(self.cache_planner.plan(segment_map), provider_usage)
                )
            return response

    runtime = build_query_runtime(model_runtime=AccountingModelRuntime())

    async def _collect() -> None:
        async for _event in runtime.astream(QueryRequest(session_id="session-accounting", message="hello")):
            pass

    asyncio.run(_collect())
    turn_run_id = runtime.single_agent_runtime_host.list_session_traces("session-accounting")["turn_runs"][0]["turn_run_id"]
    summary = runtime.single_agent_runtime_host.prompt_accounting_ledger.summarize_run(turn_run_id)

    assert summary["exact_total_tokens"] == 15
    assert summary["provider_usage_record_count"] == 1
    assert summary["local_prediction_record_count"] == 1


def test_required_artifact_completion_requires_existing_file() -> None:
    from harness.loop.task_executor import _verify_completion

    runtime = build_query_runtime()
    project_root = Path(runtime.base_dir).resolve().parent
    contract = {"required_artifacts": [{"artifact_kind": "html_game", "user_visible_name": "游戏"}]}
    runtime_assembly = {
        "task_environment": {
            "storage_space": {"artifact_root": "storage/task_environments/development/sandbox/artifacts"},
            "sandbox_policy": {},
        }
    }

    missing = _verify_completion(
        runtime_host=runtime.single_agent_runtime_host,
        runtime_assembly=runtime_assembly,
        task_run_id="taskrun:test:missing",
        contract=contract,
        artifact_refs=[{"path": "storage/task_environments/development/sandbox/artifacts/game.html"}],
    )

    real_path = project_root / "storage/task_environments/development/sandbox/artifacts/game.html"
    real_path.parent.mkdir(parents=True, exist_ok=True)
    real_path.write_text("<!doctype html><title>game</title>", encoding="utf-8")
    present = _verify_completion(
        runtime_host=runtime.single_agent_runtime_host,
        runtime_assembly=runtime_assembly,
        task_run_id="taskrun:test:present",
        contract=contract,
        artifact_refs=[{"path": "storage/task_environments/development/sandbox/artifacts/game.html"}],
    )

    assert missing["ok"] is False
    assert missing["missing"] == ["required_artifacts"]
    assert present["ok"] is True
    assert present["verified_artifacts"][0]["exists"] is True


def test_sandbox_artifact_is_published_before_completion() -> None:
    from harness.loop.task_executor import _task_sandbox_policy, _verify_completion

    runtime = build_query_runtime()
    project_root = Path(runtime.base_dir).resolve().parent
    task_run_id = "taskrun:test:publish"
    runtime_assembly = {
        "task_environment": {
            "storage_space": {"artifact_root": "storage/task_environments/development/sandbox/artifacts"},
            "sandbox_policy": {},
        }
    }
    policy = _task_sandbox_policy(runtime_assembly, runtime_host=runtime.single_agent_runtime_host, task_run_id=task_run_id)
    sandbox_file = Path(str(policy["sandbox_root"])) / "storage/task_environments/development/sandbox/artifacts/game.html"
    sandbox_file.parent.mkdir(parents=True, exist_ok=True)
    sandbox_file.write_text("<!doctype html><canvas></canvas>", encoding="utf-8")
    published_file = project_root / "storage/task_environments/development/sandbox/artifacts/game.html"

    verdict = _verify_completion(
        runtime_host=runtime.single_agent_runtime_host,
        runtime_assembly=runtime_assembly,
        task_run_id=task_run_id,
        contract={"required_artifacts": [{"artifact_kind": "html_game"}]},
        artifact_refs=[
            {
                "path": "storage/task_environments/development/sandbox/artifacts/game.html",
                "absolute_path": str(sandbox_file),
                "sandbox_path": "storage/task_environments/development/sandbox/artifacts/game.html",
            }
        ],
    )

    assert verdict["ok"] is True
    assert published_file.exists()
    assert published_file.read_text(encoding="utf-8") == "<!doctype html><canvas></canvas>"
    assert verdict["verified_artifacts"][0]["path"] == "storage/task_environments/development/sandbox/artifacts/game.html"


def test_sandbox_artifact_publish_overwrites_stale_workspace_file() -> None:
    from harness.loop.task_executor import _task_sandbox_policy, _verify_completion

    runtime = build_query_runtime()
    project_root = Path(runtime.base_dir).resolve().parent
    task_run_id = "taskrun:test:publish-overwrite-stale"
    runtime_assembly = {
        "task_environment": {
            "storage_space": {"artifact_root": "storage/task_environments/development/sandbox/artifacts"},
            "sandbox_policy": {},
        }
    }
    logical_path = "storage/task_environments/development/sandbox/artifacts/stale-game.html"
    published_file = project_root / logical_path
    published_file.parent.mkdir(parents=True, exist_ok=True)
    published_file.write_text("<!doctype html><title>stale</title>", encoding="utf-8")
    policy = _task_sandbox_policy(runtime_assembly, runtime_host=runtime.single_agent_runtime_host, task_run_id=task_run_id)
    sandbox_file = Path(str(policy["sandbox_root"])) / logical_path
    sandbox_file.parent.mkdir(parents=True, exist_ok=True)
    sandbox_file.write_text("<!doctype html><title>fresh</title><canvas></canvas>", encoding="utf-8")

    verdict = _verify_completion(
        runtime_host=runtime.single_agent_runtime_host,
        runtime_assembly=runtime_assembly,
        task_run_id=task_run_id,
        contract={"required_artifacts": [{"artifact_kind": "html_game"}]},
        artifact_refs=[{"path": logical_path, "absolute_path": str(sandbox_file), "sandbox_path": logical_path}],
    )

    assert verdict["ok"] is True
    assert published_file.read_text(encoding="utf-8") == "<!doctype html><title>fresh</title><canvas></canvas>"
    assert verdict["verified_artifacts"][0]["size_bytes"] == published_file.stat().st_size


def test_completion_discovers_sandbox_artifacts_not_returned_by_tool_refs() -> None:
    from harness.loop.task_executor import _task_sandbox_policy, _verify_completion

    runtime = build_query_runtime()
    project_root = Path(runtime.base_dir).resolve().parent
    task_run_id = "taskrun:test:discover-sandbox-artifacts"
    runtime_assembly = {
        "task_environment": {
            "storage_space": {"artifact_root": "storage/task_environments/development/sandbox/artifacts"},
            "sandbox_policy": {},
        }
    }
    policy = _task_sandbox_policy(runtime_assembly, runtime_host=runtime.single_agent_runtime_host, task_run_id=task_run_id)
    sandbox_asset = Path(str(policy["sandbox_root"])) / "storage/task_environments/development/sandbox/artifacts/assets/player.png"
    sandbox_asset.parent.mkdir(parents=True, exist_ok=True)
    sandbox_asset.write_bytes(b"\x89PNG\r\n\x1a\nsandbox-player")
    unrelated = sandbox_asset.parent / "scratch.txt"
    unrelated.write_text("scratch", encoding="utf-8")
    published_asset = project_root / "storage/task_environments/development/sandbox/artifacts/assets/player.png"
    unrelated_published = project_root / "storage/task_environments/development/sandbox/artifacts/assets/scratch.txt"

    verdict = _verify_completion(
        runtime_host=runtime.single_agent_runtime_host,
        runtime_assembly=runtime_assembly,
        task_run_id=task_run_id,
        contract={"required_artifacts": [{"artifact_kind": "image_file", "path": "storage/task_environments/development/sandbox/artifacts/assets/player.png"}]},
        artifact_refs=[],
    )

    assert verdict["ok"] is True
    assert published_asset.exists()
    assert published_asset.read_bytes() == b"\x89PNG\r\n\x1a\nsandbox-player"
    assert any(item["path"].endswith("assets/player.png") for item in verdict["verified_artifacts"])
    assert not unrelated_published.exists()
    assert not any(item["path"].endswith("scratch.txt") for item in verdict["verified_artifacts"])


def test_completion_discovery_ignores_free_text_artifact_names() -> None:
    from harness.loop.task_executor import _task_sandbox_policy, _verify_completion

    runtime = build_query_runtime()
    task_run_id = "taskrun:test:discover-structured-only"
    runtime_assembly = {
        "task_environment": {
            "storage_space": {"artifact_root": "storage/task_environments/development/sandbox/artifacts"},
            "sandbox_policy": {},
        }
    }
    policy = _task_sandbox_policy(runtime_assembly, runtime_host=runtime.single_agent_runtime_host, task_run_id=task_run_id)
    sandbox_asset = Path(str(policy["sandbox_root"])) / "storage/task_environments/development/sandbox/artifacts/assets/free-text-player.png"
    sandbox_asset.parent.mkdir(parents=True, exist_ok=True)
    sandbox_asset.write_bytes(b"\x89PNG\r\n\x1a\nfree-text-player")

    verdict = _verify_completion(
        runtime_host=runtime.single_agent_runtime_host,
        runtime_assembly=runtime_assembly,
        task_run_id=task_run_id,
        contract={"required_artifacts": [{"artifact_kind": "image_file", "user_visible_name": "free-text-player.png"}]},
        artifact_refs=[],
    )

    assert verdict["ok"] is False
    assert verdict["verified_artifacts"] == []


def test_model_action_request_accepts_public_progress_note() -> None:
    from harness.loop.model_action_protocol import model_action_request_from_payload

    action, diagnostics = model_action_request_from_payload(
        {
            "authority": "harness.loop.model_action_request",
            "request_id": "model-action:test:progress",
            "turn_id": "turn:test:1",
            "action_type": "tool_call",
            "public_progress_note": "我先检查现有文件，确认下一步修改范围。",
            "public_action_state": {
                "current_judgment": "读取 README 可以降低误改风险。",
                "next_action": "调用 read_file 读取 README.md。",
            },
            "tool_call": {"tool_name": "read_file", "args": {"path": "README.md"}},
        },
        turn_id="turn:test:1",
    )

    assert diagnostics["status"] == "accepted"
    assert action is not None
    assert action.public_progress_note == "我先检查现有文件，确认下一步修改范围。"
    assert action.public_action_state["next_action"] == "调用 read_file 读取 README.md。"


def test_task_model_action_request_requires_public_progress_note() -> None:
    from harness.loop.model_action_protocol import model_action_request_from_payload

    action, diagnostics = model_action_request_from_payload(
        {
            "authority": "harness.loop.model_action_request",
            "request_id": "model-action:test:missing-progress",
            "turn_id": "taskrun:test:progress-required",
            "action_type": "tool_call",
            "tool_call": {"tool_name": "read_file", "args": {"path": "README.md"}},
        },
        turn_id="taskrun:test:progress-required",
        require_public_progress_note=True,
    )

    assert action is None
    assert diagnostics["status"] == "invalid"
    assert "public_progress_note_required" in diagnostics["validation_errors"]


def test_task_model_action_request_requires_public_action_state_when_enabled() -> None:
    from harness.loop.model_action_protocol import model_action_request_from_payload

    action, diagnostics = model_action_request_from_payload(
        {
            "authority": "harness.loop.model_action_request",
            "request_id": "model-action:test:missing-report",
            "turn_id": "taskrun:test:progress-report-required",
            "action_type": "tool_call",
            "public_progress_note": "我准备读取文件。",
            "tool_call": {"tool_name": "read_file", "args": {"path": "README.md"}},
        },
        turn_id="taskrun:test:progress-report-required",
        require_public_progress_note=True,
        require_public_action_state=True,
    )

    assert action is None
    assert diagnostics["status"] == "invalid"
    assert "public_action_state_required" in diagnostics["validation_errors"]


def test_tool_call_status_does_not_replace_agent_public_judgment() -> None:
    action = ModelActionRequest(
        request_id="model-action:test:tool",
        turn_id="taskrun:test",
        action_type="tool_call",
        public_progress_note="我看到缺少入口文件，下一步先读取目录确认项目结构。",
        public_action_state={
            "current_judgment": "需要先读文件确认结构。",
            "next_action": "读取 index.html。",
        },
        tool_call={"tool_name": "read_file", "args": {"path": "index.html"}},
    )

    summary = _tool_call_progress_summary(action)

    assert summary == "正在使用文件读取工具处理 index.html。"
    assert "我看到缺少入口文件" not in summary


def test_public_runtime_progress_preserves_user_level_task_wording() -> None:
    from harness.runtime.public_progress import public_runtime_progress_summary

    assert public_runtime_progress_summary("不需要开启正式任务。") == "不需要开启正式任务。"
    assert public_runtime_progress_summary("正式任务生命周期已完成。") == "正式任务生命周期已完成。"


def test_task_sandbox_workspace_root_is_project_root() -> None:
    from harness.loop.task_executor import _task_sandbox_policy

    runtime = build_query_runtime()
    project_root = Path(runtime.base_dir).resolve().parent
    policy = _task_sandbox_policy(
        {"task_environment": {"storage_space": {}, "sandbox_policy": {}}},
        runtime_host=runtime.single_agent_runtime_host,
        task_run_id="taskrun:test:workspace-root",
    )

    assert Path(str(policy["workspace_root"])).resolve() == project_root


def test_task_sandbox_grants_environment_scratch_without_publishing_it() -> None:
    from harness.loop.task_executor import _task_sandbox_policy, _verify_completion

    runtime = build_query_runtime()
    task_run_id = "taskrun:test:scratch-scope"
    runtime_assembly = {
        "task_environment": {
            "storage_space": {
                "environment_storage_root": "storage/task_environments/development/sandbox",
                "runtime_state_root": "storage/task_environments/development/sandbox/runtime_state",
                "artifact_root": "storage/task_environments/development/sandbox/artifacts",
                "cache_root": "storage/task_environments/development/sandbox/cache",
            },
            "sandbox_policy": {},
        }
    }
    policy = _task_sandbox_policy(runtime_assembly, runtime_host=runtime.single_agent_runtime_host, task_run_id=task_run_id)

    assert "storage/task_environments/development/sandbox/tmp" in policy["write_scopes"]
    assert "storage/task_environments/development/sandbox/cache" in policy["write_scopes"]
    assert "storage/task_environments/development/sandbox/runtime_state" in policy["write_scopes"]
    assert "storage/task_environments/development/sandbox/tmp" not in policy["publish_scopes"]
    assert "." not in policy["write_scopes"]

    scratch_file = Path(str(policy["sandbox_root"])) / "storage/task_environments/development/sandbox/tmp/debug-note.html"
    scratch_file.parent.mkdir(parents=True, exist_ok=True)
    scratch_file.write_text("<!doctype html><title>scratch</title>", encoding="utf-8")

    verdict = _verify_completion(
        runtime_host=runtime.single_agent_runtime_host,
        runtime_assembly=runtime_assembly,
        task_run_id=task_run_id,
        contract={"required_artifacts": [{"artifact_kind": "html_game", "user_visible_name": "debug-note.html"}]},
        artifact_refs=[{"path": "storage/task_environments/development/sandbox/tmp/debug-note.html", "absolute_path": str(scratch_file)}],
    )

    assert verdict["ok"] is False
    assert verdict["missing"] == ["required_artifacts"]


def test_task_run_artifact_view_returns_only_existing_files() -> None:
    runtime = build_query_runtime()
    project_root = Path(runtime.base_dir).resolve().parent
    existing = project_root / "storage/task_environments/development/sandbox/artifacts/final.html"
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_text("<!doctype html><title>final</title>", encoding="utf-8")
    runtime.single_agent_runtime_host.state_index.upsert_agent_run_result(
        AgentRunResult(
            agent_run_result_id="agresult:test-artifacts",
            agent_run_id="agrun:test-artifacts",
            task_run_id="taskrun:test-artifacts",
            agent_id="agent:0",
            status="completed",
            artifact_refs=(
                "storage/task_environments/development/sandbox/artifacts/final.html",
                "storage/task_environments/development/sandbox/artifacts/missing.html",
            ),
        )
    )

    view = runtime.single_agent_runtime_host.get_task_run_artifacts("taskrun:test-artifacts")

    assert view["created_files"] == ["storage/task_environments/development/sandbox/artifacts/final.html"]
    assert view["artifact_refs"][0]["exists"] is True


def test_running_task_artifact_view_includes_tool_observation_refs() -> None:
    runtime = build_query_runtime()
    host = runtime.single_agent_runtime_host
    project_root = Path(runtime.base_dir).resolve().parent
    canonical_artifact = project_root / "storage/task_environments/general/workspace/artifacts/plan.md"
    canonical_artifact.parent.mkdir(parents=True, exist_ok=True)
    canonical_artifact.write_text("# canonical plan", encoding="utf-8")
    sandbox_artifact = project_root / "storage/runtime_state/sandboxes/taskrun_test_running_artifacts/storage/task_environments/general/workspace/artifacts/plan.md"
    sandbox_artifact.parent.mkdir(parents=True, exist_ok=True)
    sandbox_artifact.write_text("# sandbox plan", encoding="utf-8")
    task_run_id = "taskrun:test:running-artifacts"
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id=task_run_id,
            session_id="session-running-artifacts",
            task_id="task:running-artifacts",
            status="running",
            created_at=100.0,
            updated_at=110.0,
            execution_runtime_kind="single_agent_task",
            diagnostics={
                "artifact_refs": [
                    {
                        "path": "storage/task_environments/general/workspace/artifacts/plan.md",
                        "absolute_path": str(canonical_artifact),
                        "kind": "file",
                        "source": "write_file",
                    }
                ]
            },
        )
    )
    host.event_log.append(
        task_run_id,
        "task_tool_observation_recorded",
        payload={
            "observation": {
                "payload": {
                    "tool_name": "write_file",
                    "result_envelope": {
                        "artifact_refs": [
                            {
                                "path": "storage/task_environments/general/workspace/artifacts/plan.md",
                                "absolute_path": str(sandbox_artifact),
                                "kind": "file",
                                "source": "write_file",
                            }
                        ],
                    },
                },
            },
        },
    )

    view = host.get_task_run_artifacts(task_run_id)
    monitor = host.get_task_run_live_monitor(task_run_id)

    assert view["created_files"] == [
        "storage/task_environments/general/workspace/artifacts/plan.md"
    ]
    assert view["artifact_refs"][0]["exists"] is True
    assert monitor is not None
    assert monitor["artifact_count"] == 1
    assert monitor["artifact_refs"][0]["source"] == "write_file"


def test_task_observation_projection_separates_stale_and_active_failures() -> None:
    from harness.loop.task_executor import _observations_for_packet

    runtime = build_query_runtime()
    host = runtime.single_agent_runtime_host
    task_run_id = "taskrun:test:observation-projection"
    stale_fingerprint = {
        "tool_registry_hash": "tools-v1",
        "tool_config_hash": "image-config-v1",
        "sandbox_policy_hash": "sandbox-v1",
        "permission_policy_hash": "permission-v1",
        "backend_config_hash": "backend-v1",
    }
    current_fingerprint = {
        **stale_fingerprint,
        "tool_config_hash": "image-config-v2",
        "backend_config_hash": "backend-v2",
    }
    host.event_log.append(
        task_run_id,
        "task_tool_observation_recorded",
        payload={
            "observation": {
                "observation_id": "obs:stale-image",
                "task_run_id": task_run_id,
                "observation_type": "executor_error",
                "source": "tool:image_generate",
                "payload": {
                    "tool_name": "image_generate",
                    "tool_args": {"prompt": "hero"},
                    "error": "old config failure",
                    "runtime_fingerprint": stale_fingerprint,
                },
                "error": "old config failure",
            }
        },
    )
    host.event_log.append(
        task_run_id,
        "task_tool_observation_recorded",
        payload={
            "observation": {
                "observation_id": "obs:active-read",
                "task_run_id": task_run_id,
                "observation_type": "executor_error",
                "source": "tool:read_file",
                "payload": {
                    "tool_name": "read_file",
                    "tool_args": {"path": "missing.md"},
                    "error": "file missing",
                    "runtime_fingerprint": current_fingerprint,
                },
                "error": "file missing",
            }
        },
    )

    context = _observations_for_packet(host, task_run_id, current_fingerprint=current_fingerprint)
    projection = context["execution_state"]["system_projection"]

    assert projection["historical_failures"][0]["tool_name"] == "image_generate"
    assert projection["historical_failures"][0]["current_runtime_fact"] is False
    assert projection["active_failures"][0]["tool_name"] == "read_file"
    assert projection["active_failures"][0]["error"]["message"] == "file missing"


def test_task_observation_projection_extracts_structured_error_from_tool_json_result() -> None:
    from harness.loop.task_executor import _observations_for_packet

    runtime = build_query_runtime()
    host = runtime.single_agent_runtime_host
    task_run_id = "taskrun:test:image-json-error"
    fingerprint = {
        "tool_registry_hash": "tools-v1",
        "tool_config_hash": "image-config-v1",
        "sandbox_policy_hash": "sandbox-v1",
        "permission_policy_hash": "permission-v1",
        "backend_config_hash": "backend-v1",
    }
    host.event_log.append(
        task_run_id,
        "task_tool_observation_recorded",
        payload={
            "observation": {
                "observation_id": "obs:image-json-error",
                "task_run_id": task_run_id,
                "observation_type": "tool_result",
                "source": "tool:image_generate",
                "payload": {
                    "tool_name": "image_generate",
                    "tool_args": {"prompt": "mine", "quality": "low"},
                    "result": json.dumps(
                        {
                            "ok": False,
                            "error": "gateway timeout",
                            "structured_error": {
                                "code": "image_provider_transient_error",
                                "message": "Image API failed with status 504",
                                "retryable": True,
                                "origin": "image_provider",
                            },
                        }
                    ),
                    "runtime_fingerprint": fingerprint,
                },
            }
        },
    )

    context = _observations_for_packet(host, task_run_id, current_fingerprint=fingerprint)
    projection = context["execution_state"]["system_projection"]

    assert projection["current_facts"] == []
    assert projection["active_failures"][0]["tool_name"] == "image_generate"
    assert projection["active_failures"][0]["error"]["code"] == "image_provider_transient_error"
    assert projection["active_failures"][0]["error"]["origin"] == "image_provider"


def test_task_observation_projection_treats_missing_fingerprint_failure_as_historical() -> None:
    from harness.loop.task_executor import _observations_for_packet

    runtime = build_query_runtime()
    host = runtime.single_agent_runtime_host
    task_run_id = "taskrun:test:missing-fingerprint"
    host.event_log.append(
        task_run_id,
        "task_tool_observation_recorded",
        payload={
            "observation": {
                "observation_id": "obs:legacy-error",
                "task_run_id": task_run_id,
                "observation_type": "executor_error",
                "source": "tool:image_generate",
                "payload": {
                    "tool_name": "image_generate",
                    "tool_args": {"prompt": "hero"},
                    "error": "legacy failure without runtime fingerprint",
                },
                "error": "legacy failure without runtime fingerprint",
            }
        },
    )

    context = _observations_for_packet(host, task_run_id, current_fingerprint={"tool_config_hash": "current"})
    projection = context["execution_state"]["system_projection"]

    assert projection["active_failures"] == []
    assert projection["historical_failures"][0]["tool_name"] == "image_generate"
    assert projection["historical_failures"][0]["reason"] == "missing_runtime_fingerprint"


def test_task_observation_projection_marks_superseded_success_as_historical() -> None:
    from harness.loop.task_executor import _observations_for_packet

    runtime = build_query_runtime()
    host = runtime.single_agent_runtime_host
    task_run_id = "taskrun:test:superseded-success"
    stale_fingerprint = {
        "tool_registry_hash": "tools-v1",
        "tool_config_hash": "config-v1",
        "sandbox_policy_hash": "sandbox-v1",
        "permission_policy_hash": "perm-v1",
        "backend_config_hash": "backend-v1",
    }
    current_fingerprint = {
        **stale_fingerprint,
        "sandbox_policy_hash": "sandbox-v2",
    }
    host.event_log.append(
        task_run_id,
        "task_tool_observation_recorded",
        payload={
            "observation": {
                "observation_id": "obs:stale-glob",
                "task_run_id": task_run_id,
                "observation_type": "tool_result",
                "source": "tool:glob_paths",
                "payload": {
                    "tool_name": "glob_paths",
                    "tool_args": {"pattern": "**/*roguelike*/**/*"},
                    "result": "docs/experiments/roguelike_long_task/assets/test.txt",
                    "runtime_fingerprint": stale_fingerprint,
                },
            }
        },
    )

    context = _observations_for_packet(host, task_run_id, current_fingerprint=current_fingerprint)
    projection = context["execution_state"]["system_projection"]

    assert projection["current_facts"] == []
    historical = context["packet_observations"][0]
    assert historical["tool_name"] == "glob_paths"
    assert dict(historical["runtime_freshness"])["reason"] == "superseded_by_runtime_change"


def test_terminal_diagnostics_are_stripped_before_task_resume_packet() -> None:
    from harness.loop.task_executor import _strip_terminal_diagnostics

    cleaned = _strip_terminal_diagnostics(
        {
            "contract": {"user_visible_goal": "继续任务"},
            "action_request": {"action_type": "block", "blocking_reason": "old blocker"},
            "terminal_reason": "old blocker",
            "recoverable_error": {"detail": "old model error"},
            "recovery_action": "rerun_task_executor",
            "latest_step_summary": "old blocked summary",
        }
    )

    assert cleaned == {"contract": {"user_visible_goal": "继续任务"}}


def test_task_observation_projection_keeps_success_artifact_evidence() -> None:
    from harness.loop.task_executor import _observations_for_packet

    runtime = build_query_runtime()
    host = runtime.single_agent_runtime_host
    task_run_id = "taskrun:test:observation-artifact"
    fingerprint = {"tool_config_hash": "current"}
    host.event_log.append(
        task_run_id,
        "task_tool_observation_recorded",
        payload={
            "observation": {
                "observation_id": "obs:image-ok",
                "task_run_id": task_run_id,
                "observation_type": "tool_result",
                "source": "tool:image_generate",
                "payload": {
                    "tool_name": "image_generate",
                    "runtime_fingerprint": fingerprint,
                    "result_envelope": {
                        "tool_name": "image_generate",
                        "tool_args": {"prompt": "hero"},
                        "status": "ok",
                        "text": "generated",
                        "artifact_refs": [{"path": "frontend/public/souls/generated/hero.png", "kind": "image"}],
                        "structured_payload": {
                            "artifact_refs": [{"path": "frontend/public/souls/generated/hero.png", "kind": "image"}]
                        },
                    },
                },
            }
        },
    )

    context = _observations_for_packet(host, task_run_id, current_fingerprint=fingerprint)
    projection = context["execution_state"]["system_projection"]

    assert projection["current_facts"][0]["tool_name"] == "image_generate"
    assert projection["artifact_evidence"][0]["path"] == "frontend/public/souls/generated/hero.png"
    assert context["artifact_refs"][0]["kind"] == "image"


def test_task_observation_projection_ignores_already_projected_records() -> None:
    from harness.loop.task_executor import _observations_for_packet

    runtime = build_query_runtime()
    host = runtime.single_agent_runtime_host
    context = _observations_for_packet(
        host,
        "taskrun:test:projected-record",
        current_fingerprint={"tool_config_hash": "current"},
        pending_observations=[
            {
                "observation_ref": "rtobs:already-projected",
                "tool_name": "read_file",
                "status": "ok",
                "runtime_freshness": {"visibility": "active"},
                "authority": "orchestration.tool_observation_record",
            }
        ],
    )

    assert context["raw_observations"] == []
    assert context["packet_observations"] == []
