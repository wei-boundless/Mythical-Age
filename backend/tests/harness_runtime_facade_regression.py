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

from harness.entrypoint.models import HarnessRuntimeRequest
from api.chat import (
    _project_public_stream_event,
    _runtime_run_refs_for_public_event,
    _runtime_run_refs_from_event,
)
from runtime.shared.models import AgentRunResult, TaskRun, TurnRun
from runtime.tool_runtime import ToolObservation
from harness.loop.model_action_protocol import ModelActionRequest
from memory_system import MemoryFacade
from memory_system.storage.models import MemoryNote
from harness.loop.task_executor import (
    TaskRunExecutorInterrupted,
    _duplicate_read_only_tool_call_observation,
    _matching_model_action_admission_denial_observations,
    _model_action_admission_observation,
    _tool_call_progress_summary,
)
from harness.loop.task_run_execution_control import ExecutorControlSignal
from harness.runtime.tool_batch_planner import ToolBatchGroup

task_executor_module = sys.modules["harness.loop.task_executor"]
from harness.loop.task_lifecycle import TaskLifecycleRecord, TaskRunContract
from sessions import SessionManager
from capability_system.tools.native_tool_catalog import build_tool_instances, get_tool_definitions
from tests.support.runtime_stubs import (
    NativeToolCallSequenceModelRuntimeStub,
    NativeToolCallModelRuntimeStub,
    PrimarySettingsStub,
    SingleMessageModelRuntimeStub,
    build_harness_runtime,
    isolated_backend_root,
)
from runtime.prompt_accounting import (
    CanonicalPromptSerializer,
    ModelTokenUsageRecord,
    PromptCachePlanner,
    extract_provider_usage,
)
from runtime.model_gateway.model_request import ModelRequestBuilder


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


def _packet_payload_after_title(content: str, title: str) -> dict[str, object]:
    marker = title + "\n"
    assert content.startswith(marker)
    return json.loads(content[len(marker):])


def _admission_payloads(events: list[dict[str, object]]) -> list[dict[str, object]]:
    payloads: list[dict[str, object]] = []
    for event in events:
        if event.get("type") != "model_action_admission":
            continue
        runtime_event = dict(event.get("event") or {})
        payload = dict(runtime_event.get("payload") or {})
        if payload:
            payloads.append(payload)
    return payloads


def _action_request(
    *,
    action_type: str,
    final_answer: str = "",
    user_question: str = "",
    blocking_reason: str = "",
    public_progress_note: str = "正在处理当前请求。",
    task_contract_seed: dict[str, object] | None = None,
    tool_call: dict[str, object] | None = None,
    active_work_control: dict[str, object] | None = None,
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
        "user_question": user_question,
        "blocking_reason": blocking_reason,
        "tool_call": dict(tool_call or {}),
        "task_contract_seed": dict(task_contract_seed or {}),
        "completion_contract": {},
        "permission_request": {},
        "active_work_control": dict(active_work_control or {}),
        "diagnostics": {"test_action_request": True, **dict(diagnostics or {})},
    }


def _project_backend_dir() -> Path:
    return Path(__file__).resolve().parents[1]


def _runtime_test_root(tmp_path: Path) -> Path:
    root = tmp_path / "runtime-root"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _tool_runtime_for_names(tool_base_dir: Path, names: set[str]) -> SimpleNamespace:
    selected = {str(name) for name in names if str(name)}
    tool_instances = [tool for tool in build_tool_instances(tool_base_dir) if getattr(tool, "name", "") in selected]
    definitions = [definition for definition in get_tool_definitions() if definition.name in selected]
    return SimpleNamespace(
        base_dir=tool_base_dir,
        definitions=definitions,
        instances=tool_instances,
        get_definition=lambda name: next((definition for definition in definitions if definition.name == name), None),
        get_instance=lambda name: next((tool for tool in tool_instances if getattr(tool, "name", "") == name), None),
    )


def test_explicit_capability_boundary_uses_single_agent_turn_without_task_run() -> None:
    runtime = build_harness_runtime(
        model_runtime=SingleMessageModelRuntimeStub(content="自然对话回复。")
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-plain",
                message="和我随便聊两句。",
                task_selection={
                    "control_capabilities": {
                        "may_call_tools": False,
                        "may_request_task_run": False,
                        "may_control_active_work": False,
                        "may_use_subagents": False,
                    }
                },
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    stream_types = [str(event.get("type") or "") for event in events]
    branch_events = [dict(event.get("runtime_branch") or {}) for event in events if event.get("type") == "runtime_branch_decided"]

    assert any(event.get("type") == "done" and event.get("content") == "自然对话回复。" for event in events)
    assert "runtime_assembly_compiled" in stream_types
    assert "runtime_branch_decided" in stream_types
    assert branch_events and branch_events[0].get("branch_kind") == "single_agent_turn"
    assert "single_agent_turn_started" in stream_types
    assert "assistant_message_committed" in stream_types
    assert "runtime_invocation_packet" not in stream_types
    assert "harness_run_started" in stream_types
    assert "model_action_request" not in stream_types
    assert not any("compilation" in event or "model_messages" in event for event in events)
    assert runtime.single_agent_runtime_host.list_session_traces("session-plain")["task_run_count"] == 0
    assert runtime.single_agent_runtime_host.active_turn_registry.snapshot("session-plain") is None


def test_plain_single_agent_turn_releases_active_turn_before_next_message() -> None:
    runtime = build_harness_runtime(
        model_runtime=SingleMessageModelRuntimeStub(content="自然对话回复。")
    )

    async def _collect(message: str) -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-plain-followup",
                message=message,
                task_selection={
                    "control_capabilities": {
                        "may_call_tools": False,
                        "may_request_task_run": False,
                        "may_control_active_work": False,
                        "may_use_subagents": False,
                    }
                },
            )
        ):
            events.append(event)
        return events

    first_events = asyncio.run(_collect("先随便聊一句。"))
    second_events = asyncio.run(_collect("再回答我一句。"))

    assert any(event.get("type") == "done" and event.get("content") == "自然对话回复。" for event in first_events)
    assert any(event.get("type") == "done" and event.get("content") == "自然对话回复。" for event in second_events)
    assert not any(event.get("type") == "error" and event.get("code") == "expected_turn_id_required" for event in second_events)
    assert runtime.single_agent_runtime_host.active_turn_registry.snapshot("session-plain-followup") is None


def test_single_agent_turn_receives_compressed_context_from_session_record() -> None:
    class RecordingModelRuntime(SingleMessageModelRuntimeStub):
        def __init__(self) -> None:
            super().__init__(content="自然对话回复。")
            self.last_messages: list[dict[str, object]] = []

        async def invoke_messages(self, messages, **kwargs):
            self.last_messages = [dict(item) for item in list(messages or []) if isinstance(item, dict)]
            return await super().invoke_messages(messages, **kwargs)

    model = RecordingModelRuntime()
    runtime = build_harness_runtime(model_runtime=model)
    runtime.session_manager.compressed_context = "此前已经确认项目采用 DeepSeek。"

    async def _collect() -> None:
        async for _event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-plain-compressed",
                message="继续。",
                task_selection={
                    "control_capabilities": {
                        "may_call_tools": False,
                        "may_request_task_run": False,
                        "may_control_active_work": False,
                        "may_use_subagents": False,
                    }
                },
            )
        ):
            pass

    asyncio.run(_collect())
    payload = "\n".join(str(message.get("content") or "") for message in model.last_messages)

    assert "此前已经确认项目采用 DeepSeek。" in payload
    assert "[Compressed session context]" not in payload


def test_single_agent_turn_receives_environment_durable_memory_context() -> None:
    class MemoryAwareRecordingModelRuntime(SingleMessageModelRuntimeStub):
        def __init__(self) -> None:
            super().__init__(content="自然对话回复。")
            self.last_messages: list[dict[str, object]] = []

        async def invoke_messages(self, messages, **kwargs):
            text = "\n".join(str(item.get("content") or "") for item in list(messages or []) if isinstance(item, dict))
            if "durable memory recall selector" in text:
                return SimpleNamespace(
                    content=json.dumps(
                        {
                            "should_recall": True,
                            "selected_note_ids": ["coding-test-policy"],
                            "reason": "coding environment policy is relevant",
                            "confidence": 1.0,
                            "needs_verification": True,
                            "manifest_only": False,
                            "ignore_memory": False,
                        },
                        ensure_ascii=False,
                    )
                )
            if "你是一名记忆管理员" in text:
                return SimpleNamespace(
                    content=json.dumps(
                        {
                            "session_memory": {
                                "session_title": "测试会话",
                                "active_goal": "验证运行时记忆注入",
                                "flow_state": ["已完成主模型轮次"],
                                "current_task_state": ["测试结束"],
                                "next_step": ["无"],
                            },
                            "session_emphasis_actions": [],
                            "durable_memory": {"actions": [], "skipped_reason": "test"},
                        },
                        ensure_ascii=False,
                    )
                )
            if "Single agent turn" in text:
                self.last_messages = [dict(item) for item in list(messages or []) if isinstance(item, dict)]
            return await super().invoke_messages(messages, **kwargs)

    base_dir = isolated_backend_root("runtime-memory-")
    model = MemoryAwareRecordingModelRuntime()
    memory_facade = MemoryFacade(base_dir)
    memory_facade.set_model_invoker(model.invoke_messages)
    memory_facade.resolve_durable_memory_manager({"task_environment_id": "env.coding.vibe_workspace"}).save_note(
        MemoryNote(
            slug="coding-test-policy",
            title="Coding 测试策略",
            summary="coding 环境修改必须真实运行聚焦测试。",
            canonical_statement="coding 环境修改必须真实运行聚焦测试。",
            body="coding 环境修改必须真实运行聚焦测试。",
            memory_type="project",
            memory_class="work",
            confidence="high",
        )
    )
    runtime = build_harness_runtime(
        base_dir=base_dir,
        memory_facade=memory_facade,
        model_runtime=model,
    )

    async def _collect() -> None:
        async for _event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-env-durable-runtime",
                message="继续修复记忆系统。",
                task_selection={
                    "task_environment_id": "env.coding.vibe_workspace",
                    "control_capabilities": {
                        "may_call_tools": False,
                        "may_request_task_run": False,
                        "may_control_active_work": False,
                        "may_use_subagents": False,
                    },
                },
            )
        ):
            pass

    asyncio.run(_collect())
    payload = "\n".join(str(message.get("content") or "") for message in model.last_messages)

    assert "coding 环境修改必须真实运行聚焦测试" in payload
    assert "memory_context" in payload
    assert "env:env.coding.vibe_workspace" in payload


def test_single_agent_turn_receives_recent_terminal_task_outcome_from_state_index() -> None:
    class RecordingModelRuntime(SingleMessageModelRuntimeStub):
        def __init__(self) -> None:
            super().__init__(content="它卡住是因为生图工具未配置。")
            self.last_messages: list[dict[str, object]] = []

        async def invoke_messages(self, messages, **kwargs):
            self.last_messages = [dict(item) for item in list(messages or []) if isinstance(item, dict)]
            return await super().invoke_messages(messages, **kwargs)

    model = RecordingModelRuntime()
    runtime = build_harness_runtime(model_runtime=model)
    runtime.single_agent_runtime_host.state_index.upsert_task_run(
        TaskRun(
            task_run_id="taskrun:turn:session-recent-outcome:1:root:test",
            session_id="session-recent-outcome",
            task_id="task:turn:session-recent-outcome:1",
            agent_profile_id="main_interactive_agent",
            execution_runtime_kind="single_agent_task",
            status="failed",
            terminal_reason="task_executor_schedule_failed",
            created_at=1.0,
            updated_at=2.0,
            diagnostics={
                "goal": "复杂版五层地下塔像素风游戏。",
                "latest_public_progress_note": "生图工具未配置，无法完成合同要求的真实美术资产。",
                "agent_brief_output": "image_generate returned Image generation is not configured.",
            },
        )
    )

    async def _collect() -> None:
        async for _event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-recent-outcome",
                message="刚才为什么卡住了？",
                task_selection={
                    "control_capabilities": {
                        "may_call_tools": False,
                        "may_request_task_run": False,
                        "may_control_active_work": False,
                        "may_use_subagents": False,
                    }
                },
            )
        ):
            pass

    asyncio.run(_collect())
    payload = "\n".join(str(message.get("content") or "") for message in model.last_messages)
    current_request_payload = _packet_payload_after_title(
        str(model.last_messages[-1].get("content") or ""),
        "Single agent turn current request",
    )

    assert "recent_work_outcome" in payload
    assert "task_executor_schedule_failed" in payload
    assert "生图工具未配置，无法完成合同要求的真实美术资产。" in payload
    assert "active_work_context" not in json.dumps(current_request_payload, ensure_ascii=False)
    assert "只读事实" in payload


def test_default_runtime_branches_to_single_agent_turn_without_task_run() -> None:
    runtime = build_harness_runtime(
        model_runtime=SingleMessageModelRuntimeStub(content="直接回答，不进入任务生命周期。")
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(HarnessRuntimeRequest(session_id="session-direct", message="介绍一下 harness。")):
            events.append(event)
        return events

    events = asyncio.run(_collect())

    assert any(event.get("type") == "done" for event in events)
    assert any(event.get("type") == "runtime_assembly_compiled" for event in events)
    branch_events = [dict(event.get("runtime_branch") or {}) for event in events if event.get("type") == "runtime_branch_decided"]
    assert branch_events and branch_events[0].get("branch_kind") == "single_agent_turn"
    assert dict(branch_events[0].get("monitor_policy") or {}).get("record_task_monitor") is False
    assert dict(branch_events[0].get("monitor_policy") or {}).get("record_turn_monitor") is False
    assert "single_agent_turn_started" in [str(event.get("type") or "") for event in events]
    traces = runtime.single_agent_runtime_host.list_session_traces("session-direct")
    assert traces["task_run_count"] == 0


def test_public_stream_projection_emits_public_timeline_delta_for_tool_progress() -> None:
    projected = _project_public_stream_event(
        "runtime_step_summary",
        {
            "type": "runtime_step_summary",
            "step": "task_tool_executed",
            "status": "running",
            "public_progress_note": "正在写入 docs/plan.md",
            "event": {
                "event_id": "rtevt:tool-progress",
                "payload": {
                    "tool_name": "write_file",
                    "tool_target": "docs/plan.md",
                },
            },
        },
    )

    assert projected is not None
    _, data = projected
    assert data["public_timeline_delta"][0]["kind"] == "tool_activity"
    assert data["public_timeline_delta"][0]["title"] == "正在写入 docs/plan.md"


def test_public_stream_projection_emits_handoff_status_delta() -> None:
    projected = _project_public_stream_event(
        "done",
        {
            "type": "done",
            "terminal_reason": "task_executor_scheduled",
            "answer_channel": "task_control",
            "runtime_task_run_id": "taskrun:test:handoff",
        },
    )

    assert projected is not None
    _, data = projected
    assert data["public_timeline_delta"][0]["kind"] == "status_update"
    assert data["public_timeline_delta"][0]["title"] == "后台任务已接管"


def test_public_stream_projection_uses_inspection_language_for_path_exists() -> None:
    projected = _project_public_stream_event(
        "runtime_step_summary",
        {
            "type": "runtime_step_summary",
            "step": "task_tool_executed",
            "status": "running",
            "public_progress_note": "已发起工具调用，正在等待工具返回：path_exists。",
            "event": {
                "event_id": "rtevt:path-exists",
                "payload": {
                    "tool_name": "path_exists",
                    "tool_target": "storage/task_environments/general/workspace/artifacts/mythical_sphere.html",
                },
            },
        },
    )

    assert projected is not None
    _, data = projected
    item = data["public_timeline_delta"][0]
    assert item["kind"] == "tool_activity"
    assert item["title"] == "正在检查 storage/task_environments/general/workspace/artifacts/mythical_sphere.html"
    assert item["detail"] == "storage/task_environments/general/workspace/artifacts/mythical_sphere.html"


def test_public_stream_projection_emits_live_tool_admission_delta() -> None:
    projected = _project_public_stream_event(
        "model_action_admission",
        {
            "type": "model_action_admission",
            "event": {
                "event_id": "rtevt:tool-admission",
                "payload": {
                    "model_action_request": {
                        "action_type": "tool_call",
                        "public_progress_note": "已发起工具调用，正在等待工具返回：write_file。",
                        "tool_call": {
                            "name": "write_file",
                            "args": {
                                "path": "storage/task_environments/general/workspace/artifacts/football.html",
                            },
                        },
                    },
                },
            },
        },
    )

    assert projected is not None
    _, data = projected
    item = data["public_timeline_delta"][0]
    assert item["kind"] == "tool_activity"
    assert item["title"] == "正在写入 storage/task_environments/general/workspace/artifacts/football.html"


def test_public_stream_projection_emits_live_tool_result_delta() -> None:
    projected = _project_public_stream_event(
        "turn_tool_observation_recorded",
        {
            "type": "turn_tool_observation_recorded",
            "event": {
                "event_id": "rtevt:tool-result",
                "payload": {
                    "tool_observation": {
                        "tool_name": "path_exists",
                        "status": "ok",
                        "text": "true",
                        "result_envelope": {
                            "tool_args": {
                                "path": "storage/task_environments/general/workspace/artifacts/football.html",
                            },
                            "structured_payload": {
                                "tool_result": {
                                    "kind": "path_exists",
                                    "path": "storage/task_environments/general/workspace/artifacts/football.html",
                                    "exists": True,
                                },
                            },
                        },
                    },
                },
            },
        },
    )

    assert projected is not None
    _, data = projected
    item = data["public_timeline_delta"][0]
    assert item["kind"] == "tool_activity"
    assert item["title"] == "检查完成 storage/task_environments/general/workspace/artifacts/football.html"
    assert item["detail"] == "目标路径存在"


def test_public_stream_projection_hides_sandbox_boundary_command_failures() -> None:
    projected = _project_public_stream_event(
        "turn_tool_observation_recorded",
        {
            "type": "turn_tool_observation_recorded",
            "event": {
                "event_id": "rtevt:sandbox-boundary",
                "payload": {
                    "tool_observation": {
                        "tool_name": "terminal",
                        "status": "error",
                        "error": "Blocked: command references an absolute path outside the sandbox workspace.",
                        "text": "Blocked: command references an absolute path outside the sandbox workspace.",
                        "result_envelope": {
                            "tool_args": {
                                "command": 'cd "D:\\AI应用\\langchain-agent"; python -m pytest backend/tests/',
                            },
                            "structured_error": {
                                "message": "Blocked: command references an absolute path outside the sandbox workspace.",
                            },
                        },
                    },
                },
            },
        },
    )

    assert projected is not None
    _, data = projected
    assert "public_timeline_delta" not in data


def test_single_agent_turn_projection_only_exposes_executable_native_actions(tmp_path: Path) -> None:
    class RecordingNativeTurnModelRuntime(NativeToolCallModelRuntimeStub):
        def __init__(self) -> None:
            super().__init__(content="直接回答。")
            self.last_messages: list[dict[str, object]] = []

        async def invoke_messages_with_tools(self, messages, tools, **kwargs):
            self.last_messages = [dict(item) for item in list(messages or []) if isinstance(item, dict)]
            return await super().invoke_messages_with_tools(messages, tools, **kwargs)

    model = RecordingNativeTurnModelRuntime()
    tool_base_dir = _project_backend_dir()
    runtime = build_harness_runtime(
        base_dir=_runtime_test_root(tmp_path),
        model_runtime=model,
        tool_runtime=_tool_runtime_for_names(tool_base_dir, {"read_file"}),
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(HarnessRuntimeRequest(session_id="session-native-boundary", message="介绍一下项目。")):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    assembly = dict(next(event for event in events if event.get("type") == "runtime_assembly_compiled").get("runtime_assembly") or {})
    start = dict(next(event for event in events if event.get("type") == "single_agent_turn_started"))
    packet_tools = [str(dict(tool).get("name") or "") for tool in list(model.seen_tools[0] or [])]
    stable_payload = _packet_payload_after_title(
        str(model.last_messages[1].get("content") or ""),
        "Single agent turn stable boundary",
    )
    effective_capabilities = dict(stable_payload.get("control_capabilities") or {})
    model_input = "\n".join(str(message.get("content") or "") for message in model.last_messages)
    output_contract = dict(stable_payload.get("output_contract") or {})
    action_protocol = dict(output_contract.get("action_protocol") or {})
    ordinary_tool_contract = dict(action_protocol.get("ordinary_tool_calls") or {})
    native_tool_contract = dict(action_protocol.get("native_tool_calls") or {})

    assert dict(assembly.get("control_capabilities") or {}).get("may_call_tools") is True
    assert packet_tools == ["read_file"]
    assert start.get("allowed_action_types") == ["respond", "ask_user", "block", "request_task_run", "tool_call"]
    assert effective_capabilities.get("may_call_tools") is True
    assert effective_capabilities.get("may_use_subagents") is False
    assert effective_capabilities.get("supports_json_action_protocol") is True
    assert effective_capabilities.get("requires_json_action_protocol") is False
    assert ordinary_tool_contract.get("multi_tool_calls_allowed") is True
    assert ordinary_tool_contract.get("runtime_execution_policy") == "tool_batch_plan_scheduled_by_safety_and_resource_locks"
    assert "parallel_allowed" not in ordinary_tool_contract
    assert native_tool_contract.get("provider_multi_tool_calls_allowed") is True
    assert native_tool_contract.get("runtime_execution_policy") == "tool_batch_plan_scheduled_by_safety_and_resource_locks"
    assert dict(action_protocol.get("control_actions") or {}).get("native_tool_transport_enabled") is False
    assert "single_action_per_turn" not in json.dumps(output_contract, ensure_ascii=False)
    assert "调用本次可见工具" in model_input
    assert "运行时会按工具安全声明、资源冲突和审批状态决定并发或串行" in model_input
    assert "控制裁决，不是普通 native 工具" in model_input
    assert "子 agent 协作" not in model_input
    assert getattr(model.seen_tool_call_options[0], "parallel_tool_calls", None) is False
    assert any(event.get("type") == "done" and str(event.get("content") or "") == "直接回答。" for event in events)


def test_single_agent_turn_read_only_tool_executes_through_control_plane_and_followup_answers(tmp_path: Path) -> None:
    model = NativeToolCallSequenceModelRuntimeStub(
        [
            {
                "additional_kwargs": {"reasoning_content": "I should read requirements before answering."},
                "tool_calls": [
                    {
                        "id": "call-read-requirements",
                        "name": "read_file",
                        "args": {"path": "requirements.txt", "line_count": 120},
                    }
                ]
            },
            {
                "content": "已经读取 requirements.txt。",
                "additional_kwargs": {"reasoning_content": "The file result is enough to answer."},
            },
            {"content": "第二轮继续回答。"},
        ]
    )
    tool_base_dir = _project_backend_dir()
    runtime = build_harness_runtime(
        base_dir=_runtime_test_root(tmp_path),
        model_runtime=model,
        tool_runtime=_tool_runtime_for_names(tool_base_dir, {"read_file"}),
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(HarnessRuntimeRequest(session_id="session-single-turn-read-tool", message="看看依赖文件。")):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    tool_observations = [dict(event.get("tool_observation") or {}) for event in events if event.get("type") == "tool_observation"]
    followup_messages = [dict(item) for item in list(model.seen_messages[-1] or []) if isinstance(item, dict)]
    assistant_tool_message = next(item for item in followup_messages if item.get("role") == "assistant" and item.get("tool_calls"))
    tool_message = next(item for item in followup_messages if item.get("role") == "tool")
    followup_context = dict(model.seen_accounting_contexts[-1])
    followup_segment_plan = dict(followup_context.get("segment_plan") or {})
    followup_request = ModelRequestBuilder().build(
        request_id="modelreq:single-agent-followup-test",
        messages=followup_messages,
        tools=list(model.seen_tools[-1] or []),
        provider="deepseek",
        model="deepseek-v4-pro",
        segment_plan=followup_segment_plan,
    )
    followup_kinds = [str(item.get("kind") or "") for item in list(followup_segment_plan.get("segments") or [])]

    assert model.calls == 2
    assert tool_observations and tool_observations[0]["status"] == "ok"
    assert tool_observations[0]["caller_kind"] == "agent_turn"
    assert tool_observations[0]["tool_name"] == "read_file"
    assert dict(tool_observations[0].get("diagnostics") or {}).get("stage") == "tool_runtime_executor_dispatch"
    assert str(tool_observations[0].get("caller_ref") or "").startswith("turnrun:")
    assert "task_run_id" not in dict(tool_observations[0].get("result_envelope") or {})
    assert dict(list(assistant_tool_message["tool_calls"])[0]).get("id") == "call-read-requirements"
    assert tool_message["tool_call_id"] == "call-read-requirements"
    assert followup_context["source"] == "harness.single_agent_turn.tool_followup"
    assert followup_request.diagnostics["unplanned_message_count"] == 0
    assert followup_request.diagnostics["segment_bindings_match_planned_messages"] is True
    assert "single_agent_turn_tool_call" in followup_kinds
    assert "single_agent_turn_tool_observation" in followup_kinds
    assert any(event.get("type") == "turn_tool_observation_recorded" for event in events)
    assert any(event.get("type") == "done" and str(event.get("content") or "") == "已经读取 requirements.txt。" for event in events)
    assert runtime.single_agent_runtime_host.list_session_traces("session-single-turn-read-tool")["task_run_count"] == 0

    async def _collect_second_turn() -> None:
        async for _event in runtime.astream(HarnessRuntimeRequest(session_id="session-single-turn-read-tool", message="继续说明。")):
            pass

    asyncio.run(_collect_second_turn())
    second_turn_messages = [dict(item) for item in list(model.seen_messages[-1] or []) if isinstance(item, dict)]
    replayed_tool_call = next(item for item in second_turn_messages if item.get("role") == "assistant" and item.get("tool_calls"))
    replayed_tool_result = next(item for item in second_turn_messages if item.get("role") == "tool")

    assert replayed_tool_call["reasoning_content"] == "I should read requirements before answering."
    assert dict(list(replayed_tool_call["tool_calls"])[0]).get("id") == "call-read-requirements"
    assert replayed_tool_result["tool_call_id"] == "call-read-requirements"


def test_single_agent_turn_batches_multiple_read_only_tools_before_followup_answers(tmp_path: Path) -> None:
    model = NativeToolCallSequenceModelRuntimeStub(
        [
            {
                "tool_calls": [
                    {"id": "call-read-requirements", "name": "read_file", "args": {"path": "requirements.txt", "line_count": 20}},
                    {"id": "call-path-exists", "name": "path_exists", "args": {"path": "requirements.txt"}},
                ]
            },
            {"content": "已经完成两个检查。"},
        ]
    )
    tool_base_dir = _project_backend_dir()
    runtime = build_harness_runtime(
        base_dir=_runtime_test_root(tmp_path),
        model_runtime=model,
        tool_runtime=_tool_runtime_for_names(tool_base_dir, {"read_file", "path_exists"}),
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(HarnessRuntimeRequest(session_id="session-single-turn-multi-tool", message="检查依赖文件。")):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    tool_observations = [dict(event.get("tool_observation") or {}) for event in events if event.get("type") == "tool_observation"]
    followup_messages = [dict(item) for item in list(model.seen_messages[-1] or []) if isinstance(item, dict)]
    assistant_tool_message = next(item for item in followup_messages if item.get("role") == "assistant" and item.get("tool_calls"))
    tool_messages = [item for item in followup_messages if item.get("role") == "tool"]
    admitted_actions = [dict(payload.get("model_action_request") or {}) for payload in _admission_payloads(events)]
    batch_plan_event = next(event for event in events if event.get("type") == "tool_batch_planned")
    batch_plan = dict(batch_plan_event.get("tool_batch_plan") or {})
    batch_groups = [dict(item) for item in list(batch_plan.get("groups") or [])]

    assert model.calls == 2
    assert getattr(model.seen_tool_call_options[0], "parallel_tool_calls", None) is True
    assert batch_groups and batch_groups[0]["parallel"] is True
    assert batch_groups[0]["execution_class"] == "parallel_read"
    assert batch_groups[0]["item_indexes"] == [0, 1]
    assert [item["tool_name"] for item in tool_observations] == ["read_file", "path_exists"]
    assert all(item["status"] == "ok" for item in tool_observations)
    assert [dict(item).get("action_type") for item in admitted_actions] == ["tool_call", "tool_call"]
    assert len(list(assistant_tool_message["tool_calls"])) == 2
    assert [item["tool_call_id"] for item in tool_messages] == ["call-read-requirements", "call-path-exists"]
    assert any(event.get("type") == "done" and str(event.get("content") or "") == "已经完成两个检查。" for event in events)


def test_single_agent_turn_side_effect_tool_runs_inside_development_sandbox(tmp_path: Path) -> None:
    sandbox_path = ".tmp/single_turn_write_tool_ok.txt"
    model = NativeToolCallSequenceModelRuntimeStub(
        [
            {
                "tool_calls": [
                    {
                        "id": "call-write",
                        "name": "write_file",
                        "args": {"path": sandbox_path, "content": "ok"},
                    }
                ]
            },
            {"content": "已在开发沙箱内写入文件，真实工作区没有被直接改写。"},
        ]
    )
    tool_base_dir = _project_backend_dir()
    runtime = build_harness_runtime(
        base_dir=_runtime_test_root(tmp_path),
        model_runtime=model,
        tool_runtime=_tool_runtime_for_names(tool_base_dir, {"write_file", "read_file"}),
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-single-turn-write-tool",
                message="写一个文件。",
                task_selection={"task_environment_id": "env.development.sandbox"},
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    admissions = _admission_payloads(events)
    tool_observations = [dict(event.get("tool_observation") or {}) for event in events if event.get("type") == "tool_observation"]
    followup_messages = [dict(item) for item in list(model.seen_messages[-1] or []) if isinstance(item, dict)]
    tool_message = next(item for item in followup_messages if item.get("role") == "tool")
    batch_plan_event = next(event for event in events if event.get("type") == "tool_batch_planned")
    batch_plan = dict(batch_plan_event.get("tool_batch_plan") or {})
    batch_groups = [dict(item) for item in list(batch_plan.get("groups") or [])]

    assert model.calls == 2
    assert batch_groups and batch_groups[0]["execution_class"] == "exclusive"
    assert batch_groups[0]["parallel"] is False
    assert admissions
    assert dict(admissions[0].get("admission") or {}).get("decision") == "allow"
    assert tool_observations and tool_observations[0]["status"] == "ok"
    assert dict(tool_observations[0].get("diagnostics") or {}).get("stage") == "tool_runtime_executor_dispatch"
    assert tool_message.get("name") == "write_file"
    assert not (tool_base_dir / sandbox_path).exists()
    assert any(event.get("type") == "done" and "开发沙箱" in str(event.get("content") or "") for event in events)
    assert not any(
        event.get("type") == "done" and dict(event).get("terminal_reason") == "tool_denied"
        for event in events
    )


def test_single_agent_turn_publishes_environment_artifact_write_before_reporting_success(tmp_path: Path) -> None:
    artifact_path = "storage/task_environments/development/sandbox/artifacts/single_turn_artifact.html"
    model = NativeToolCallSequenceModelRuntimeStub(
        [
            {
                "tool_calls": [
                    {
                        "id": "call-write-artifact",
                        "name": "write_file",
                        "args": {"path": artifact_path, "content": "<!doctype html><title>published</title>"},
                    }
                ]
            },
            {"content": "已写入 artifact。"},
            {
                "tool_calls": [
                    {
                        "id": "call-path-exists-artifact",
                        "name": "path_exists",
                        "args": {"path": artifact_path},
                    }
                ]
            },
            {"content": "artifact 可见。"},
        ]
    )
    tool_base_dir = _project_backend_dir()
    runtime_root = _runtime_test_root(tmp_path)
    runtime = build_harness_runtime(
        base_dir=runtime_root,
        model_runtime=model,
        tool_runtime=_tool_runtime_for_names(tool_base_dir, {"write_file", "path_exists"}),
    )

    async def _collect(message: str) -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-single-turn-artifact-publish",
                message=message,
                task_selection={"task_environment_id": "env.development.sandbox"},
            )
        ):
            events.append(event)
        return events

    write_events = asyncio.run(_collect("写一个 artifact 文件。"))
    published_file = runtime_root / artifact_path
    write_observation = next(dict(event.get("tool_observation") or {}) for event in write_events if event.get("type") == "tool_observation")
    artifact_refs = [dict(item) for item in list(write_observation.get("artifact_refs") or [])]
    envelope_refs = [
        dict(item)
        for item in list(dict(write_observation.get("result_envelope") or {}).get("artifact_refs") or [])
    ]

    assert write_observation["status"] == "ok"
    assert published_file.exists()
    assert published_file.read_text(encoding="utf-8") == "<!doctype html><title>published</title>"
    assert artifact_refs and artifact_refs[0]["path"] == artifact_path
    assert artifact_refs[0]["absolute_path"] == str(published_file.resolve())
    assert artifact_refs[0]["published"] is True
    assert envelope_refs and envelope_refs[0]["absolute_path"] == str(published_file.resolve())
    assert dict(write_observation.get("diagnostics") or {}).get("sandbox_artifact_publish", {}).get("status") == "published"

    exists_events = asyncio.run(_collect("确认刚才的 artifact 是否存在。"))
    exists_observation = next(dict(event.get("tool_observation") or {}) for event in exists_events if event.get("type") == "tool_observation")

    assert model.calls == 4
    assert exists_observation["status"] == "ok"
    assert exists_observation["text"] == "true"
    assert any(event.get("type") == "done" and str(event.get("content") or "") == "artifact 可见。" for event in exists_events)


def test_vibe_coding_artifact_write_creates_environment_dirs_and_publishes(tmp_path: Path) -> None:
    artifact_path = "storage/task_environments/coding/vibe-workspace/artifacts/vibe_index.html"
    model = NativeToolCallSequenceModelRuntimeStub(
        [
            {
                "tool_calls": [
                    {
                        "id": "call-write-vibe-artifact",
                        "name": "write_file",
                        "args": {"path": artifact_path, "content": "<!doctype html><title>vibe</title>"},
                    }
                ]
            },
            {"content": "vibe artifact 已写入。"},
            {
                "tool_calls": [
                    {
                        "id": "call-path-exists-vibe-artifact",
                        "name": "path_exists",
                        "args": {"path": artifact_path},
                    }
                ]
            },
            {"content": "vibe artifact 可见。"},
        ]
    )
    tool_base_dir = _project_backend_dir()
    runtime_root = _runtime_test_root(tmp_path)
    runtime = build_harness_runtime(
        base_dir=runtime_root,
        model_runtime=model,
        tool_runtime=_tool_runtime_for_names(tool_base_dir, {"write_file", "path_exists"}),
    )

    async def _collect(message: str) -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-vibe-coding-artifact-publish",
                message=message,
                task_selection={"task_environment_id": "env.coding.vibe_workspace"},
            )
        ):
            events.append(event)
        return events

    write_events = asyncio.run(_collect("写一个 vibe coding artifact。"))
    storage_root = runtime_root / "storage/task_environments/coding/vibe-workspace"
    artifact_root = storage_root / "artifacts"
    published_file = runtime_root / artifact_path
    write_observation = next(dict(event.get("tool_observation") or {}) for event in write_events if event.get("type") == "tool_observation")
    artifact_refs = [dict(item) for item in list(write_observation.get("artifact_refs") or [])]

    assert storage_root.exists()
    assert artifact_root.exists()
    assert write_observation["status"] == "ok"
    assert published_file.exists()
    assert published_file.read_text(encoding="utf-8") == "<!doctype html><title>vibe</title>"
    assert artifact_refs and artifact_refs[0]["published"] is True
    assert artifact_refs[0]["absolute_path"] == str(published_file.resolve())

    exists_events = asyncio.run(_collect("确认 vibe coding artifact 是否存在。"))
    exists_observation = next(dict(event.get("tool_observation") or {}) for event in exists_events if event.get("type") == "tool_observation")

    assert model.calls == 4
    assert exists_observation["status"] == "ok"
    assert exists_observation["text"] == "true"
    assert any(event.get("type") == "done" and str(event.get("content") or "") == "vibe artifact 可见。" for event in exists_events)


def test_vibe_coding_default_mode_writes_project_path_to_sandbox_workspace(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    (project_root / "frontend" / "src").mkdir(parents=True)
    project_file = project_root / "frontend" / "src" / "vibe_probe.txt"
    model = NativeToolCallSequenceModelRuntimeStub(
        [
            {
                "tool_calls": [
                    {
                        "id": "call-write-vibe-project",
                        "name": "write_file",
                        "args": {"path": "frontend/src/vibe_probe.txt", "content": "sandbox project edit"},
                    }
                ]
            },
            {"content": "sandbox project edit 已写入。"},
        ]
    )
    runtime = build_harness_runtime(
        base_dir=_runtime_test_root(tmp_path),
        model_runtime=model,
        tool_runtime=_tool_runtime_for_names(project_root, {"write_file"}),
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-vibe-coding-project-sandbox-write",
                message="写一个项目文件。",
                task_selection={"task_environment_id": "env.coding.vibe_workspace"},
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    observation = next(dict(event.get("tool_observation") or {}) for event in events if event.get("type") == "tool_observation")
    artifact_refs = [dict(item) for item in list(observation.get("artifact_refs") or [])]
    sandbox_file = Path(artifact_refs[0]["absolute_path"])

    assert observation["status"] == "ok"
    assert not project_file.exists()
    assert sandbox_file.exists()
    assert sandbox_file.read_text(encoding="utf-8") == "sandbox project edit"
    assert "sandbox_path" in artifact_refs[0]


def test_vibe_coding_full_access_writes_project_path_to_real_workspace(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    (project_root / "frontend" / "src").mkdir(parents=True)
    project_file = project_root / "frontend" / "src" / "vibe_probe.txt"
    permission = SimpleNamespace(current_mode=lambda: "full_access", supported_modes=lambda: ["default", "full_access"])
    model = NativeToolCallSequenceModelRuntimeStub(
        [
            {
                "tool_calls": [
                    {
                        "id": "call-write-vibe-project-full-access",
                        "name": "write_file",
                        "args": {"path": "frontend/src/vibe_probe.txt", "content": "real project edit"},
                    }
                ]
            },
            {"content": "real project edit 已写入。"},
        ]
    )
    runtime = build_harness_runtime(
        base_dir=_runtime_test_root(tmp_path),
        permission_service=permission,
        model_runtime=model,
        tool_runtime=_tool_runtime_for_names(project_root, {"write_file"}),
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-vibe-coding-project-real-write",
                message="写一个真实项目文件。",
                task_selection={"task_environment_id": "env.coding.vibe_workspace"},
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    observation = next(dict(event.get("tool_observation") or {}) for event in events if event.get("type") == "tool_observation")
    artifact_refs = [dict(item) for item in list(observation.get("artifact_refs") or [])]

    assert observation["status"] == "ok"
    assert project_file.exists()
    assert project_file.read_text(encoding="utf-8") == "real project edit"
    assert artifact_refs[0]["absolute_path"] == str(project_file.resolve())
    assert artifact_refs[0]["repository_id"] == "repo.managed_project.project_workspace"


def test_vibe_coding_uses_session_bound_full_access_when_request_omits_permission_mode(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    (project_root / "frontend" / "src").mkdir(parents=True)
    project_file = project_root / "frontend" / "src" / "session_permission_probe.txt"
    runtime_root = _runtime_test_root(tmp_path)
    session_manager = SessionManager(runtime_root)
    session = session_manager.create_session(title="Session permission")
    session_id = str(session["id"])
    model = NativeToolCallSequenceModelRuntimeStub(
        [
            {
                "tool_calls": [
                    {
                        "id": "call-write-vibe-session-permission",
                        "name": "write_file",
                        "args": {"path": "frontend/src/session_permission_probe.txt", "content": "session full access"},
                    }
                ]
            },
            {"content": "session full access 已写入。"},
        ]
    )
    runtime = build_harness_runtime(
        base_dir=runtime_root,
        session_manager=session_manager,
        model_runtime=model,
        tool_runtime=_tool_runtime_for_names(project_root, {"write_file"}),
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id=session_id,
                message="按当前会话权限写项目文件。",
                task_selection={"task_environment_id": "env.coding.vibe_workspace"},
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    observation = next(dict(event.get("tool_observation") or {}) for event in events if event.get("type") == "tool_observation")
    artifact_refs = [dict(item) for item in list(observation.get("artifact_refs") or [])]

    assert session["conversation_state"]["permission_mode"] == "full_access"
    assert observation["status"] == "ok"
    assert project_file.exists()
    assert project_file.read_text(encoding="utf-8") == "session full access"
    assert artifact_refs[0]["absolute_path"] == str(project_file.resolve())
    assert artifact_refs[0]["repository_id"] == "repo.managed_project.project_workspace"


def test_vibe_coding_full_access_project_write_creates_missing_parent_directories(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir(parents=True)
    project_file = project_root / "frontend" / "generated" / "vibe" / "auto_created.txt"
    permission = SimpleNamespace(current_mode=lambda: "full_access", supported_modes=lambda: ["default", "full_access"])
    model = NativeToolCallSequenceModelRuntimeStub(
        [
            {
                "tool_calls": [
                    {
                        "id": "call-write-vibe-missing-parent",
                        "name": "write_file",
                        "args": {
                            "path": "frontend/generated/vibe/auto_created.txt",
                            "content": "created through full access gateway",
                        },
                    }
                ]
            },
            {"content": "缺失目录已自动创建。"},
        ]
    )
    runtime = build_harness_runtime(
        base_dir=_runtime_test_root(tmp_path),
        permission_service=permission,
        model_runtime=model,
        tool_runtime=_tool_runtime_for_names(project_root, {"write_file"}),
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-vibe-coding-missing-parent",
                message="写入一个父目录不存在的项目文件。",
                task_selection={"task_environment_id": "env.coding.vibe_workspace"},
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    observation = next(dict(event.get("tool_observation") or {}) for event in events if event.get("type") == "tool_observation")
    artifact_refs = [dict(item) for item in list(observation.get("artifact_refs") or [])]

    assert observation["status"] == "ok"
    assert project_file.exists()
    assert project_file.read_text(encoding="utf-8") == "created through full access gateway"
    assert artifact_refs[0]["absolute_path"] == str(project_file.resolve())
    assert artifact_refs[0]["repository_id"] == "repo.managed_project.project_workspace"


def test_single_agent_turn_converts_unresumable_approval_to_model_visible_denial(tmp_path: Path) -> None:
    class ApprovalMixControlPlane:
        async def invoke(self, request, *, tool_plan):
            tool_name = str(getattr(request, "tool_name", "") or "")
            status = "needs_approval" if tool_name == "write_file" else "ok"
            text = "write_file waiting approval" if status == "needs_approval" else "read_file ok"
            return ToolObservation(
                observation_id=f"toolobs:{getattr(request, 'invocation_id', 'fake')}:test",
                invocation_id=str(getattr(request, "invocation_id", "") or ""),
                caller_kind=str(getattr(request, "caller_kind", "") or "agent_turn"),
                caller_ref=str(getattr(request, "caller_ref", "") or ""),
                tool_name=tool_name,
                operation_id=str(getattr(request, "operation_id", "") or tool_name),
                status=status,
                text=text,
                result_envelope={"status": status, "text": text},
                operation_gate={"decision": "requires_approval" if status == "needs_approval" else "allow"},
                diagnostics={"stage": "test_control_plane"},
            )

    model = NativeToolCallSequenceModelRuntimeStub(
        [
            {
                "tool_calls": [
                    {"id": "call-read", "name": "read_file", "args": {"path": "requirements.txt"}},
                    {"id": "call-write", "name": "write_file", "args": {"path": ".tmp/approval.txt", "content": "pending"}},
                ]
            },
            {"content": "写入操作需要进入可恢复任务后执行。"},
        ]
    )
    tool_base_dir = _project_backend_dir()
    runtime = build_harness_runtime(
        base_dir=_runtime_test_root(tmp_path),
        model_runtime=model,
        tool_runtime=_tool_runtime_for_names(tool_base_dir, {"read_file", "write_file"}),
    )
    runtime.single_agent_runtime_host.tool_control_plane = ApprovalMixControlPlane()

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(HarnessRuntimeRequest(session_id="session-single-turn-approval-mix", message="先读再写。")):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    stream_types = [str(event.get("type") or "") for event in events]
    observations = [dict(event.get("tool_observation") or {}) for event in events if event.get("type") == "tool_observation"]
    api_messages = [dict(item) for item in runtime.session_manager.api_transcript if isinstance(item, dict)]
    assistant_tool_messages = [item for item in api_messages if item.get("role") == "assistant" and item.get("tool_calls")]
    tool_messages = [item for item in api_messages if item.get("role") == "tool"]
    batch_plan = dict(next(event for event in events if event.get("type") == "tool_batch_planned").get("tool_batch_plan") or {})
    batch_groups = [dict(item) for item in list(batch_plan.get("groups") or [])]

    assert model.calls == 2
    assert "approval_waiting" not in stream_types
    assert [item["status"] for item in observations] == ["ok", "denied"]
    assert [item["tool_name"] for item in observations] == ["read_file", "write_file"]
    assert dict(observations[1].get("operation_gate") or {}).get("pipeline_stage") == "task_run_required_for_tool_approval"
    assert dict(observations[1].get("diagnostics") or {}).get("model_visible_recovery_observation") is True
    assert [group["execution_class"] for group in batch_groups] == ["parallel_read", "exclusive"]
    assert assistant_tool_messages
    assert [dict(item).get("id") for item in list(assistant_tool_messages[-1].get("tool_calls") or [])] == ["call-read", "call-write"]
    assert [item.get("tool_call_id") for item in tool_messages] == ["call-read", "call-write"]
    assert any(event.get("type") == "done" and str(event.get("content") or "") == "写入操作需要进入可恢复任务后执行。" for event in events)
    assert not any(
        str(item.get("answer_source") or "") == "harness.single_agent_turn.approval_waiting"
        for item in runtime.session_manager.messages
    )


def test_single_agent_turn_tool_loop_synthesizes_answer_without_ninth_tool_call(tmp_path: Path) -> None:
    class SynthesizingLoopModel(NativeToolCallSequenceModelRuntimeStub):
        def __init__(self) -> None:
            super().__init__(
                [
                    {
                        "tool_calls": [
                            {"id": f"call-exists-{index}", "name": "path_exists", "args": {"path": "requirements.txt"}},
                        ]
                    }
                    for index in range(1, 10)
                ]
            )
            self.synthesis_messages: list[dict[str, object]] = []

        async def invoke_messages(self, messages, **_kwargs):
            self.synthesis_messages = [dict(item) for item in list(messages or []) if isinstance(item, dict)]
            return SimpleNamespace(content="我已经连续核查 requirements.txt，当前应停止重复检查并基于已有结果回答。")

    model = SynthesizingLoopModel()
    tool_base_dir = _project_backend_dir()
    runtime = build_harness_runtime(
        base_dir=_runtime_test_root(tmp_path),
        model_runtime=model,
        tool_runtime=_tool_runtime_for_names(tool_base_dir, {"path_exists"}),
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(HarnessRuntimeRequest(session_id="session-single-turn-loop-limit", message="反复检查文件。")):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    observations = [event for event in events if event.get("type") == "tool_observation"]

    assert model.calls == 9
    assert len(observations) == 8
    assert any(
        event.get("type") == "done"
        and dict(event).get("terminal_reason") == "single_turn_tool_iteration_limit"
        and "停止重复检查" in str(event.get("content") or "")
        for event in events
    )
    assert model.synthesis_messages[-1]["role"] == "user"
    assert "禁止继续调用工具" in str(model.synthesis_messages[-1]["content"])
    assert not any("本轮工具观察次数已达到上限" in str(item.get("content") or "") for item in runtime.session_manager.messages)


def test_task_executor_guards_duplicate_read_only_tool_call_without_rerunning_tool() -> None:
    action = ModelActionRequest(
        request_id="model-action:duplicate-read",
        turn_id="taskrun:duplicate-read",
        action_type="tool_call",
        tool_call={"tool_name": "read_file", "args": {"path": "artifacts/demo.html"}},
    )
    previous = [
        {
            "observation_id": "toolobs:read:1",
            "payload": {
                "result_envelope": {
                    "tool_name": "read_file",
                    "tool_args": {"path": "artifacts/demo.html"},
                    "status": "ok",
                    "text": "<html></html>",
                }
            },
        }
    ]

    duplicate = _duplicate_read_only_tool_call_observation(
        task_run_id="taskrun:duplicate-read",
        packet_ref="packet:duplicate-read",
        action_request=action,
        previous_observations=previous,
    )
    same_default_window = _duplicate_read_only_tool_call_observation(
        task_run_id="taskrun:duplicate-read",
        packet_ref="packet:duplicate-read",
        action_request=ModelActionRequest(
            request_id="model-action:same-default-read-window",
            turn_id="taskrun:duplicate-read",
            action_type="tool_call",
            tool_call={"tool_name": "read_file", "args": {"path": "artifacts/demo.html", "start_line": 1}},
        ),
        previous_observations=previous,
    )
    old_window_args = _duplicate_read_only_tool_call_observation(
        task_run_id="taskrun:duplicate-read",
        packet_ref="packet:duplicate-read",
        action_request=ModelActionRequest(
            request_id="model-action:old-read-window-args",
            turn_id="taskrun:duplicate-read",
            action_type="tool_call",
            tool_call={"tool_name": "read_file", "args": {"path": "artifacts/demo.html", "offset": 0}},
        ),
        previous_observations=previous,
    )
    changed_args = _duplicate_read_only_tool_call_observation(
        task_run_id="taskrun:duplicate-read",
        packet_ref="packet:duplicate-read",
        action_request=ModelActionRequest(
            request_id="model-action:changed-read",
            turn_id="taskrun:duplicate-read",
            action_type="tool_call",
            tool_call={"tool_name": "read_file", "args": {"path": "artifacts/other.html"}},
        ),
        previous_observations=previous,
    )
    unsupported_arg = _duplicate_read_only_tool_call_observation(
        task_run_id="taskrun:duplicate-read",
        packet_ref="packet:duplicate-read",
        action_request=ModelActionRequest(
            request_id="model-action:unsupported-read-arg",
            turn_id="taskrun:duplicate-read",
            action_type="tool_call",
            tool_call={"tool_name": "read_file", "args": {"path": "artifacts/demo.html", "max_chars": 200}},
        ),
        previous_observations=previous,
    )
    repeated_failed_search = _duplicate_read_only_tool_call_observation(
        task_run_id="taskrun:duplicate-read",
        packet_ref="packet:duplicate-read",
        action_request=ModelActionRequest(
            request_id="model-action:repeated-failed-search",
            turn_id="taskrun:duplicate-read",
            action_type="tool_call",
            tool_call={"tool_name": "search_text", "args": {"query": "needle", "roots": ["docs/plan.md"]}},
        ),
        previous_observations=[
            {
                "observation_id": "toolobs:search:failed:1",
                "source": "tool:search_text",
                "payload": {
                    "tool_name": "search_text",
                    "tool_args": {"query": "needle", "roots": ["docs/plan.md"]},
                    "error": "Search failed: roots accepts directories only.",
                },
                "error": "Search failed: roots accepts directories only.",
            }
        ],
    )

    assert duplicate is not None
    assert same_default_window is not None
    assert repeated_failed_search is not None
    assert duplicate["source"] == "system:duplicate_tool_call_guard"
    assert duplicate["payload"]["error_code"] == "duplicate_read_only_tool_call"
    assert duplicate["payload"]["previous_observation_refs"] == ["toolobs:read:1"]
    assert repeated_failed_search["payload"]["error_code"] == "duplicate_failed_read_only_tool_call"
    assert repeated_failed_search["payload"]["previous_observation_refs"] == ["toolobs:search:failed:1"]
    assert changed_args is None
    assert old_window_args is None
    assert unsupported_arg is None


def test_task_executor_repeated_admission_denial_fingerprint_is_runtime_scoped() -> None:
    action = ModelActionRequest(
        request_id="model-action:admission-repeat",
        turn_id="taskrun:admission-repeat",
        action_type="tool_call",
        tool_call={"tool_name": "missing_tool", "args": {"path": "tmp/demo.txt"}},
    )
    admission = {
        "decision": "deny",
        "system_reason": "tool_not_in_runtime_assembly",
        "user_visible_reason": "工具不在当前运行边界内。",
    }
    runtime_fingerprint = {
        "runtime_assembly_id": "rtasm:taskrun:admission-repeat",
        "agent_profile_id": "main_interactive_agent",
        "runtime_profile_ref": "runtime:default",
        "task_environment_id": "coding",
        "tool_registry_hash": "tools-a",
        "tool_config_hash": "config-a",
        "sandbox_policy_hash": "sandbox-a",
        "permission_policy_hash": "permission-a",
        "backend_config_hash": "backend-a",
        "permission_mode": "default",
    }
    previous = _model_action_admission_observation(
        task_run_id="taskrun:admission-repeat",
        packet_ref="packet:admission-repeat",
        action_request=action,
        admission=admission,
        runtime_fingerprint=runtime_fingerprint,
        step_index=1,
    )
    changed_args = ModelActionRequest(
        request_id="model-action:admission-repeat-args",
        turn_id="taskrun:admission-repeat",
        action_type="tool_call",
        tool_call={"tool_name": "missing_tool", "args": {"path": "tmp/other.txt"}},
    )
    changed_environment = {**runtime_fingerprint, "task_environment_id": "writing"}

    same = _matching_model_action_admission_denial_observations(
        [previous],
        action_request=action,
        admission=admission,
        runtime_fingerprint=runtime_fingerprint,
    )
    different_args = _matching_model_action_admission_denial_observations(
        [previous],
        action_request=changed_args,
        admission=admission,
        runtime_fingerprint=runtime_fingerprint,
    )
    different_environment = _matching_model_action_admission_denial_observations(
        [previous],
        action_request=action,
        admission=admission,
        runtime_fingerprint=changed_environment,
    )
    legacy_previous = {
        **previous,
        "payload": {
            key: value
            for key, value in dict(previous.get("payload") or {}).items()
            if key != "admission_denial_fingerprint"
        },
    }
    legacy_without_fingerprint = _matching_model_action_admission_denial_observations(
        [legacy_previous],
        action_request=action,
        admission=admission,
        runtime_fingerprint=runtime_fingerprint,
    )

    assert len(same) == 1
    assert different_args == []
    assert different_environment == []
    assert legacy_without_fingerprint == []


def test_explicit_contract_task_starts_lifecycle_without_model_action_loop() -> None:
    runtime = build_harness_runtime(
        model_runtime=SingleMessageModelRuntimeStub(
            content="单轮收口回答",
            agent_turn_action_request=_action_request(
                action_type="respond",
                final_answer="不应调用模型动作协议。",
            )
        )
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-explicit-contract",
                message="按合同启动任务。",
                task_selection={
                    "task_environment_id": "env.development.sandbox",
                    "allowed_operations": ["op.model_response", "op.read_file"],
                    "system_issued_contract": True,
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
    branch = dict(next(event for event in events if event.get("type") == "runtime_branch_decided").get("runtime_branch") or {})
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

    assert branch.get("branch_kind") == "explicit_contract_task"
    assert branch.get("invocation_kind") == "task_execution_start"
    assert "runtime_invocation_packet" not in stream_types
    assert "model_action_request" not in stream_types
    assert "model_action_admission" not in stream_types
    assert "harness_run_started" in stream_types
    assert task_run_id.startswith("taskrun:")
    assert stored_task is not None
    assert contract["contract_source"] == "explicit_contract"
    assert contract["source_contract_ref"] == "contract:explicit:test"
    assert contract["task_environment_id"] == "env.development.sandbox"
    assert contract["runtime_profile"]["execution_permit"]["allowed_operations"] == ["op.model_response", "op.read_file"]
    runtime_task_selection = dict(dict(getattr(stored_task, "diagnostics", {}) or {}).get("runtime_task_selection") or {})
    assert runtime_task_selection["allowed_operations"] == ["op.model_response", "op.read_file"]
    assert dict(runtime_task_selection["runtime_profile"])["execution_permit"]["allowed_operations"] == ["op.model_response", "op.read_file"]
    assert dict(getattr(stored_task, "diagnostics", {}) or {}).get("origin_kind") == "explicit_contract"
    assert dict(getattr(stored_task, "diagnostics", {}) or {}).get("origin_authority") == "harness.explicit_contract_task"


def test_plain_task_contract_selection_does_not_bypass_agent_turn() -> None:
    runtime = build_harness_runtime(
        model_runtime=SingleMessageModelRuntimeStub(
            content="我会先判断是否需要启动任务。",
            agent_turn_action_request=_action_request(
                action_type="respond",
                final_answer="我会先判断是否需要启动任务。",
            )
        )
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-plain-contract-selection",
                message="这个只是普通会话输入，不能直接启动任务。",
                task_selection={
                    "task_environment_id": "env.development.sandbox",
                    "task_contract": {
                        "contract_id": "contract:plain:test",
                        "user_visible_goal": "普通输入里的合同片段。",
                        "task_run_goal": "不应由路由直接启动。",
                    },
                },
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    stream_types = [str(event.get("type") or "") for event in events]
    branch = dict(next(event for event in events if event.get("type") == "runtime_branch_decided").get("runtime_branch") or {})

    assert branch.get("branch_kind") == "single_agent_turn"
    assert "single_agent_turn_started" in stream_types
    assert "task_run_lifecycle_started" not in stream_types


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
        "runtime_branch_decided",
        {
            "type": "runtime_branch_decided",
            "runtime_branch": {
                "branch_kind": "single_agent_turn",
                "invocation_kind": "single_agent_turn",
                "dispatch_target": "harness_runtime.single_agent_turn",
                "reason": "default_agent_runtime_turn",
                "control_capabilities": {"may_call_tools": False},
                "diagnostics": {"backend_dir": "D:/secret"},
            },
            "runtime_assembly": {"backend_dir": "D:/secret"},
            "model_messages": [{"role": "system", "content": "hidden"}],
        },
    )

    assert projected is not None
    public_event_type, data = projected
    assert public_event_type == "runtime_branch_decided"
    assert "runtime_assembly" not in data
    assert "model_messages" not in data
    branch = dict(data.get("runtime_branch") or {})
    assert branch == {
        "branch_kind": "single_agent_turn",
        "reason": "default_agent_runtime_turn",
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


def test_chat_stream_runtime_refs_expose_active_turn_from_task_lifecycle_refs() -> None:
    refs = _runtime_run_refs_from_event(
        {
            "type": "task_run_lifecycle_started",
            "event": {
                "run_id": "taskrun:turn:session-a:1:formal",
                "refs": {
                    "turn_ref": "turn:session-a:1",
                },
                "payload": {
                    "task_run": {"task_run_id": "taskrun:turn:session-a:1:formal"},
                },
            },
        }
    )

    assert refs == {
        "turn_run_id": "",
        "task_run_id": "taskrun:turn:session-a:1:formal",
        "active_turn_id": "turn:session-a:1",
    }


def test_chat_stream_runtime_refs_do_not_treat_bare_turn_ref_as_active_task_turn() -> None:
    refs = _runtime_run_refs_from_event(
        {
            "type": "agent_turn_terminal",
            "event": {
                "run_id": "turnrun:session-a:2",
                "refs": {
                    "turn_ref": "turn:session-a:2",
                },
                "payload": {
                    "turn_run": {"turn_run_id": "turnrun:session-a:2"},
                },
            },
        }
    )

    assert refs == {
        "turn_run_id": "turnrun:session-a:2",
        "task_run_id": "",
    }


def test_chat_stream_runtime_refs_supplement_bound_active_task_for_control_done() -> None:
    runtime = build_harness_runtime()
    task_run_id = _seed_active_work(
        runtime,
        task_run_id="taskrun:active-control-public-ref",
        session_id="session-active-control-public-ref",
    )
    host = runtime.single_agent_runtime_host
    host.active_turn_registry.start(
        session_id="session-active-control-public-ref",
        turn_id="turn:active-control-public-ref:1",
        turn_run_id="turnrun:active-control-public-ref:1",
    )
    host.active_turn_registry.bind_task_run(
        session_id="session-active-control-public-ref",
        turn_id="turn:active-control-public-ref:1",
        task_run_id=task_run_id,
        state="waiting_executor",
    )

    refs = _runtime_run_refs_for_public_event(
        SimpleNamespace(harness_runtime=runtime),
        "session-active-control-public-ref",
        {
            "type": "done",
            "answer_channel": "active_work_control",
            "completion_state": "task_steer_accepted",
        },
    )

    assert refs == {
        "turn_run_id": "turnrun:active-control-public-ref:1",
        "task_run_id": "taskrun:active-control-public-ref",
        "active_turn_id": "turn:active-control-public-ref:1",
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
    runtime = build_harness_runtime(
        model_runtime=NativeToolCallModelRuntimeStub(
            content="",
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
            HarnessRuntimeRequest(
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
    branch_events = [dict(event.get("runtime_branch") or {}) for event in events if event.get("type") == "runtime_branch_decided"]

    assert "runtime_assembly_compiled" in stream_types
    assert branch_events and branch_events[0].get("branch_kind") == "single_agent_turn"
    assert "single_agent_turn_started" in stream_types
    assert "model_action_request" not in stream_types
    admissions = _admission_payloads(events)
    assert admissions
    assert dict(admissions[0].get("admission") or {}).get("decision") == "allow"
    assert dict(admissions[0].get("model_action_request") or {}).get("action_type") == "request_task_run"
    task_control_opening_index = next(
        index
        for index, event in enumerate(events)
        if event.get("type") == "assistant_text"
        and event.get("answer_channel") == "task_control"
        and "我会开始处理：交付一个真实可验证产物。" in str(event.get("content") or "")
    )
    assert "task_run_lifecycle_started" in stream_types
    assert "task_run_lifecycle_event" in stream_types
    assert task_control_opening_index < stream_types.index("task_run_lifecycle_started")
    assert "agent_todo_initialized" in event_types
    assert "task_run_executor_scheduled" in event_types
    done_contents = [str(event.get("content") or "") for event in events if event.get("type") == "done"]
    visible_progress = "\n".join(
        str(event.get("summary") or "")
        for event in events
        if event.get("type") == "runtime_step_summary"
    )
    assert any("我会开始处理：交付一个真实可验证产物。" in content for content in done_contents)
    assert any(
        event.get("type") == "assistant_text"
        and "我会开始处理：交付一个真实可验证产物。" in str(event.get("content") or "")
        for event in events
    )
    assert not any("我会按这个目标推进" in content for content in done_contents)
    assert not any("执行器" in content or "TaskRun" in content or "正式任务" in content for content in done_contents)
    _assert_no_visible_runtime_internals("\n".join(done_contents))
    _assert_no_visible_runtime_internals(visible_progress)
    task_run = runtime.single_agent_runtime_host.state_index.get_task_run(task_run_id)
    assert task_run is not None
    assert dict(task_run.diagnostics or {}).get("origin_kind") == "single_agent_turn_json_action"
    assert dict(dict(task_run.diagnostics or {}).get("origin") or {}).get("origin_authority") == "harness.loop.single_agent_turn"
    assert dict(task_run.diagnostics or {}).get("model_selection") == model_selection
    assert dict(dict(task_run.diagnostics or {}).get("model_selection_binding") or {}).get("scope") == "task_run"
    contract = runtime.single_agent_runtime_host.runtime_objects.get_object(task_run.task_contract_ref)
    assert dict(contract or {}).get("origin", {}).get("origin_kind") == "single_agent_turn_json_action"


def test_global_live_monitor_groups_waiting_completed_and_failed_runs(monkeypatch) -> None:
    monkeypatch.setattr("harness.runtime.single_agent_host.time.time", lambda: 1000.0)
    runtime = build_harness_runtime()
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
    }
    buckets = {item["task_run_id"]: item["bucket"] for item in monitor["task_runs"]}
    assert {item["task_run_id"] for item in monitor["buckets"]["waiting"]} == {
        "taskrun:fresh-waiting-executor",
    }
    assert monitor["buckets"]["diagnostics"] == []
    assert monitor["buckets"]["failed"] == []
    assert buckets["taskrun:fresh-waiting-executor"] == "waiting"
    assert monitor["summary"]["total"] == 1
    assert monitor["summary"]["running"] == 0
    assert monitor["summary"]["waiting"] == 1
    assert monitor["summary"]["failed"] == 0
    assert monitor["summary"]["diagnostics"] == 0
    assert monitor["summary"]["action_required"] == 0


def test_task_run_detail_monitor_exposes_step_summary_and_recent_terminal_status(monkeypatch) -> None:
    monkeypatch.setattr("harness.runtime.single_agent_host.time.time", lambda: 1000.0)
    runtime = build_harness_runtime()
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
    assert task_run.task_run_id not in {item["task_run_id"] for item in global_monitor["task_runs"]}
    assert global_monitor["buckets"]["completed"] == []


def test_invalid_single_agent_task_request_reports_error_without_task_run() -> None:
    runtime = build_harness_runtime(
        model_runtime=NativeToolCallModelRuntimeStub(
            tool_calls=[
                {
                    "id": "invalid-request-task-run",
                    "name": "request_task_run",
                    "args": {},
                }
            ]
        )
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(HarnessRuntimeRequest(session_id="session-invalid", message="请执行。")):
            events.append(event)
        return events

    events = asyncio.run(_collect())

    assert any(event.get("type") == "error" for event in events)
    assert any(event.get("type") == "single_agent_turn_started" for event in events)


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


class _UnexpectedNativeToolCallModelRuntime:
    def __init__(self, tool_calls: list[dict[str, object]], *, repair_action: dict[str, object] | None = None) -> None:
        self.tool_calls = [dict(item) for item in tool_calls]
        self.repair_action = dict(repair_action or {})
        self.invocation_count = 0

    async def invoke_messages(self, _messages, **_kwargs):
        self.invocation_count += 1
        if self.invocation_count == 1:
            return SimpleNamespace(content="", tool_calls=[dict(item) for item in self.tool_calls])
        if self.repair_action:
            return SimpleNamespace(content=json.dumps(self.repair_action, ensure_ascii=False))
        return SimpleNamespace(content="")


class _ActiveWorkDecisionModelRuntime:
    def __init__(self, decisions: list[dict[str, object]]) -> None:
        self.decisions = list(decisions)
        self.active_work_decision_count = 0

    async def invoke_messages_with_tools(self, _messages, tools, **_kwargs):
        del tools
        return await self._active_work_response(_messages)

    async def _active_work_response(self, messages):
        if self._allows_active_work_control(messages):
            self.active_work_decision_count += 1
            decision = dict(self.decisions.pop(0) if self.decisions else {
                "action": "answer_about_active_work",
                "relation_to_current_work": "current_work",
                "evidence": "测试桩默认指向当前工作",
                "response": "现在是正在处理。",
                "confidence": 0.9,
            })
            decision.pop("authority", None)
            if str(decision.get("action") or "") in {"normal_response", "start_new_work"}:
                return SimpleNamespace(content="普通回复。", tool_calls=[])
            return SimpleNamespace(
                content=json.dumps(
                    _action_request(
                        action_type="active_work_control",
                        public_progress_note="正在处理当前工作控制请求。",
                        active_work_control=decision,
                    ),
                    ensure_ascii=False,
                ),
                tool_calls=[],
            )
        return SimpleNamespace(content="普通回复。", tool_calls=[])

    def _allows_active_work_control(self, messages) -> bool:
        marker = "Single agent turn stable boundary\n"
        for message in list(messages or []):
            if not isinstance(message, dict):
                continue
            content = str(message.get("content") or "")
            if not content.startswith(marker):
                continue
            try:
                payload = json.loads(content[len(marker):])
            except Exception:
                return False
            output_contract = dict(payload.get("output_contract") or {})
            allowed = {str(item) for item in list(output_contract.get("allowed_actions") or []) if str(item)}
            return "active_work_control" in allowed
        return False

    async def invoke_messages(self, messages, **_kwargs):
        response = await self._active_work_response(messages)
        if str(getattr(response, "content", "") or "") == "普通回复。":
            return SimpleNamespace(content=json.dumps(_action_request(action_type="respond", final_answer="普通回复。"), ensure_ascii=False))
        return response


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


class _ProtocolRepairPromptProbeModelRuntime:
    def __init__(self) -> None:
        self.task_invocation_count = 0
        self.task_inputs: list[str] = []

    async def invoke_messages(self, messages, **_kwargs):
        model_input = "\n\n".join(str(dict(message).get("content") or "") for message in list(messages or []) if isinstance(message, dict))
        if "持续任务生命周期" not in model_input:
            return SimpleNamespace(
                content=json.dumps(
                    _action_request(
                        action_type="request_task_run",
                        task_contract_seed={"user_visible_goal": "协议恢复。", "task_run_goal": "协议恢复。", "completion_criteria": ["完成"]},
                    ),
                    ensure_ascii=False,
                )
            )
        self.task_invocation_count += 1
        self.task_inputs.append(model_input)
        if self.task_invocation_count == 1:
            return SimpleNamespace(
                content='{"action_type":"tool_call","tool_call":{"tool_name":"write_file","args":{"path":"artifacts/large.html","content":"<html>',
                response_metadata={"finish_reason": "length"},
                usage_metadata={"output_tokens": 2048},
            )
        assert "上一轮输出疑似达到模型输出上限并被截断" in model_input
        assert "系统没有执行上一轮动作" in model_input
        assert "改用 action_type=tool_call" in model_input
        assert "在 tool_calls 数组中调用 write_file 或 terminal" in model_input
        assert "tool_calls[0].args" in model_input
        return SimpleNamespace(
            content=json.dumps(
                _action_request(action_type="respond", final_answer="已按恢复协议收口。"),
                ensure_ascii=False,
            )
        )


def _tool_action_request(
    *,
    tool_name: str,
    args: dict[str, object],
    public_progress_note: str = "准备调用工具。",
) -> dict[str, object]:
    payload = _action_request(action_type="tool_call", public_progress_note=public_progress_note)
    payload["tool_call"] = {"tool_name": tool_name, "args": dict(args)}
    return payload


def _tool_calls_action_request(
    *,
    tool_calls: list[dict[str, object]],
    public_progress_note: str = "准备调用工具。",
) -> dict[str, object]:
    payload = _action_request(action_type="tool_call", public_progress_note=public_progress_note)
    payload.pop("tool_call", None)
    payload["tool_calls"] = [dict(item) for item in tool_calls]
    return payload


class _SlowTaskExecutorModelRuntime:
    async def invoke_messages(self, _messages, **_kwargs):
        await asyncio.sleep(0.1)
        return SimpleNamespace(
            content=json.dumps(
                _action_request(action_type="respond", final_answer="慢任务完成。"),
                ensure_ascii=False,
            )
        )


def test_task_tool_batch_group_returns_completed_results_before_interrupt(monkeypatch) -> None:
    signal = ExecutorControlSignal(
        kind="pause",
        task_run_id="taskrun:batch-interrupt",
        executor_epoch=1,
        reason="test pause",
        requested_by="test",
        requested_at=1.0,
    )

    async def _fake_execute_task_tool_call(_runtime_host, **kwargs):
        action_request = kwargs["action_request"]
        if action_request.request_id == "act:pause":
            raise TaskRunExecutorInterrupted(signal)
        return {
            "observation_id": "obs:completed-before-pause",
            "task_run_id": "taskrun:batch-interrupt",
            "observation_type": "tool_result",
            "source": "tool:read_file",
            "request_ref": action_request.request_id,
            "payload": {
                "tool_name": "read_file",
                "tool_args": {"path": "README.md"},
                "result": "ok",
            },
            "authority": "orchestration.runtime_observation",
        }

    monkeypatch.setattr(task_executor_module, "_execute_task_tool_call", _fake_execute_task_tool_call)
    group = ToolBatchGroup(
        group_index=0,
        execution_class="exclusive",
        item_indexes=(0, 1),
        parallel=False,
    )
    invocation_rows = [
        {
            "action_request": SimpleNamespace(
                request_id="act:completed",
                tool_call={"tool_name": "read_file", "args": {"path": "README.md"}},
            ),
            "admission": SimpleNamespace(decision="allow"),
            "tool_call": {"tool_name": "read_file", "args": {"path": "README.md"}},
        },
        {
            "action_request": SimpleNamespace(
                request_id="act:pause",
                tool_call={"tool_name": "read_file", "args": {"path": "pyproject.toml"}},
            ),
            "admission": SimpleNamespace(decision="allow"),
            "tool_call": {"tool_name": "read_file", "args": {"path": "pyproject.toml"}},
        },
    ]

    result = asyncio.run(
        task_executor_module._execute_task_tool_batch_group(
            group,
            invocation_rows=invocation_rows,
            runtime_host=SimpleNamespace(),
            services=SimpleNamespace(),
            task_run=SimpleNamespace(task_run_id="taskrun:batch-interrupt", task_id="task:batch-interrupt", session_id="session:batch-interrupt", diagnostics={}),
            packet_ref="packet:batch-interrupt",
            runtime_assembly={},
            runtime_tool_plan=SimpleNamespace(),
        )
    )

    assert [observation["observation_id"] for _row, observation in result["results"]] == ["obs:completed-before-pause"]
    assert result["interrupt"].signal.kind == "pause"


def test_malformed_agent_action_request_fails_closed() -> None:
    runtime = build_harness_runtime(model_runtime=_MalformedModelRuntime())

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(HarnessRuntimeRequest(session_id="session-malformed", message="继续。")):
            events.append(event)
        return events

    events = asyncio.run(_collect())

    assert any(event.get("type") == "done" and "系统动作格式无效" in str(event.get("content") or "") for event in events)
    assert any(
        event.get("type") == "done"
        and dict(event).get("terminal_reason") == "single_agent_turn_protocol_repair_failed"
        and dict(event).get("answer_channel") == "blocked"
        for event in events
    )
    assert not any(event.get("type") == "done" and "authority" in str(event.get("content") or "") for event in events)
    assert any(event.get("type") == "single_agent_turn_started" for event in events)


def test_single_turn_does_not_emit_synthetic_model_wait_progress() -> None:
    runtime = build_harness_runtime(model_runtime=_SlowRespondingModelRuntime())

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(HarnessRuntimeRequest(session_id="session-slow-model", message="慢一点回答。")):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    step_summaries = [event for event in events if event.get("type") == "runtime_step_summary"]
    steps = [str(event.get("step") or "") for event in step_summaries]

    assert "model_turn_invocation_started" not in steps
    assert "model_turn_output_received" not in steps
    _assert_no_visible_runtime_internals("\n".join(str(event.get("summary") or "") for event in step_summaries))
    assert any(event.get("type") == "done" for event in events)


def test_turn_stream_cancellation_closes_running_turn() -> None:
    runtime = build_harness_runtime(model_runtime=_NeverRespondingModelRuntime())

    async def _start_and_cancel() -> None:
        stream = runtime.astream(HarnessRuntimeRequest(session_id="session-cancelled-turn", message="保持等待。"))
        async for event in stream:
            if event.get("type") == "single_agent_turn_started":
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


def test_invalid_json_action_text_repairs_without_leaking_protocol() -> None:
    runtime = build_harness_runtime(
        model_runtime=_TurnActionSequenceModelRuntime(
            [
                {"authority": "harness.loop.model_action_request", "action_type": ""},
                _action_request(action_type="respond", final_answer="协议修复后完成。"),
            ]
        )
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(HarnessRuntimeRequest(session_id="session-turn-protocol-repair", message="继续。")):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    event_types = [str(event.get("type") or "") for event in events]
    admissions = _admission_payloads(events)

    assert "bounded_observation" not in event_types
    assert admissions
    assert dict(dict(admissions[0].get("model_action_request") or {}).get("diagnostics") or {}).get("protocol_repair", {}).get("original_error_code") == "single_agent_turn_invalid_json_action"
    assert any(event.get("type") == "done" and "协议修复后完成" in str(event.get("content") or "") for event in events)
    assert not any(event.get("type") == "done" and "harness.loop.model_action_request" in str(event.get("content") or "") for event in events)


def test_task_executor_schedule_missing_callback_blocks_task_run() -> None:
    runtime = build_harness_runtime()
    task_run_id = _seed_active_work(runtime, task_run_id="taskrun:missing-scheduler")

    async def _missing_executor(*_args, **_kwargs):
        raise RuntimeError("task_executor_callback_unavailable")

    runtime.execute_task_run = _missing_executor  # type: ignore[method-assign]

    async def _run_scheduler() -> None:
        runtime.schedule_task_run_executor(task_run_id, scheduler="test_missing_callback")
        for _ in range(50):
            task_run = runtime.single_agent_runtime_host.state_index.get_task_run(task_run_id)
            if task_run is not None and task_run.status == "blocked":
                return
            await asyncio.sleep(0.01)
        raise AssertionError("scheduler failure was not recorded")

    asyncio.run(_run_scheduler())

    task_run = runtime.single_agent_runtime_host.state_index.get_task_run(task_run_id)
    assert task_run is not None
    assert task_run.status == "blocked"
    assert task_run.terminal_reason == "task_executor_schedule_failed"
    assert dict(dict(task_run.diagnostics or {}).get("recoverable_error") or {}).get("retryable") is True


def test_task_executor_scheduler_auto_continues_waiting_executor() -> None:
    runtime = build_harness_runtime()
    task_run_id = _seed_active_work(runtime, task_run_id="taskrun:auto-continue")
    calls = {"count": 0}

    async def _executor(task_run_id_arg: str, **_kwargs):
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

    runtime.execute_task_run = _executor  # type: ignore[method-assign]

    async def _run_scheduler() -> None:
        runtime.schedule_task_run_executor(task_run_id, scheduler="test_auto_continue")
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
    runtime = build_harness_runtime(
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


def test_task_executor_admission_denial_becomes_model_visible_observation_and_continues() -> None:
    runtime = build_harness_runtime(
        model_runtime=_TaskExecutorSequenceModelRuntime(
            [
                _tool_action_request(
                    tool_name="missing_tool_for_admission",
                    args={"path": "tmp/not-allowed.txt"},
                    public_progress_note="尝试调用未开放工具。",
                ),
                _action_request(action_type="respond", final_answer="已根据运行边界改为直接收口。"),
            ],
            agent_turn_action_request=_action_request(action_type="respond", final_answer="unused"),
        )
    )
    host = runtime.single_agent_runtime_host
    contract = TaskRunContract(
        contract_id="task-contract:executor-admission-observation",
        contract_source="test",
        user_visible_goal="验证 admission deny 不会阻塞 executor。",
        task_run_goal="executor 应把 admission deny 作为观察回灌给模型。",
        completion_criteria=("模型收到 admission observation 后可以继续收口",),
    )
    contract_ref = host.runtime_objects.put_object("task_run_contract", contract.contract_id, contract.to_dict())
    lifecycle = TaskLifecycleRecord(
        task_run_id="taskrun:executor-admission-observation",
        contract_ref=contract_ref,
        status="waiting_executor",
        created_at=1.0,
        updated_at=1.0,
    )
    host.runtime_objects.put_object("task_lifecycle", lifecycle.task_run_id, lifecycle.to_dict())
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id=lifecycle.task_run_id,
            session_id="session-executor-admission-observation",
            task_id="task:executor-admission-observation",
            task_contract_ref=contract_ref,
            agent_profile_id="main_interactive_agent",
            execution_runtime_kind="single_agent_task",
            status="waiting_executor",
            created_at=1.0,
            updated_at=1.0,
            diagnostics={"contract": contract.to_dict()},
        )
    )

    result = asyncio.run(runtime.execute_task_run(lifecycle.task_run_id, max_steps=3))

    trace = host.get_trace(lifecycle.task_run_id, include_payloads=True)
    events = [dict(item) for item in list(dict(trace or {}).get("events") or [])]
    event_types = [str(item.get("event_type") or "") for item in events]
    admission_observation_events = [
        dict(item.get("payload") or {})
        for item in events
        if str(item.get("event_type") or "") == "task_model_action_admission_observation_recorded"
    ]

    assert result["ok"] is True
    assert runtime.model_runtime.task_invocation_count == 2
    assert "task_model_action_admission_observation_recorded" in event_types
    assert "task_run_blocked" not in event_types
    observation = dict(admission_observation_events[0].get("observation") or {})
    assert observation["source"] == "system:model_action_admission"
    assert observation["needs_model_followup"] is True
    assert dict(observation.get("payload") or {}).get("error_code") == "tool_not_in_runtime_assembly"


def test_task_executor_executes_task_execution_tool_calls_batch() -> None:
    batch_action = _tool_calls_action_request(
        tool_calls=[
            {"tool_name": "read_file", "args": {"path": "harness/loop/model_action_protocol.py", "start_line": 1, "line_count": 8}},
            {"tool_name": "read_file", "args": {"path": "harness/runtime/compiler.py", "start_line": 1, "line_count": 8}},
        ],
        public_progress_note="准备并行读取两个文件。",
    )
    runtime = build_harness_runtime(
        model_runtime=_TaskExecutorSequenceModelRuntime(
            [
                batch_action,
                _action_request(action_type="respond", final_answer="两个文件都已读取。"),
            ],
            agent_turn_action_request=_action_request(action_type="respond", final_answer="unused"),
        ),
        tool_runtime=_tool_runtime_for_names(_project_backend_dir(), {"read_file"}),
    )
    host = runtime.single_agent_runtime_host
    task_run_id = _seed_active_work(
        runtime,
        task_run_id="taskrun:executor-tool-calls-batch",
        session_id="session-executor-tool-calls-batch",
    )

    result = asyncio.run(runtime.execute_task_run(task_run_id, max_steps=3))

    trace = host.get_trace(task_run_id, include_payloads=True)
    events = [dict(item) for item in list(dict(trace or {}).get("events") or [])]
    batch_plans = [
        dict(dict(item.get("payload") or {}).get("tool_batch_plan") or {})
        for item in events
        if str(item.get("event_type") or "") == "task_tool_batch_planned"
    ]
    observations = [
        dict(dict(item.get("payload") or {}).get("observation") or {})
        for item in events
        if str(item.get("event_type") or "") == "task_tool_observation_recorded"
    ]

    assert result["ok"] is True
    assert batch_plans
    assert batch_plans[0]["diagnostics"]["item_count"] == 2
    assert len(observations) == 2
    assert {dict(item.get("payload") or {}).get("tool_name") for item in observations} == {"read_file"}
    assert runtime.model_runtime.task_invocation_count == 2


def test_task_executor_guards_duplicate_task_execution_tool_calls_batch_child() -> None:
    read_action = _tool_calls_action_request(
        tool_calls=[
            {"tool_name": "path_exists", "args": {"path": "artifacts/not-created-yet.txt"}},
        ],
        public_progress_note="检查目标路径是否存在。",
    )
    runtime = build_harness_runtime(
        model_runtime=_TaskExecutorSequenceModelRuntime(
            [
                read_action,
                read_action,
                _action_request(action_type="respond", final_answer="已避免重复读取。"),
            ],
            agent_turn_action_request=_action_request(action_type="respond", final_answer="unused"),
        ),
        tool_runtime=_tool_runtime_for_names(_project_backend_dir(), {"path_exists"}),
    )
    host = runtime.single_agent_runtime_host
    task_run_id = _seed_active_work(
        runtime,
        task_run_id="taskrun:executor-duplicate-tool-call-batch-child",
        session_id="session-executor-duplicate-tool-call-batch-child",
    )

    result = asyncio.run(runtime.execute_task_run(task_run_id, max_steps=4))

    trace = host.get_trace(task_run_id, include_payloads=True)
    events = [dict(item) for item in list(dict(trace or {}).get("events") or [])]
    tool_observations = [
        dict(dict(item.get("payload") or {}).get("observation") or {})
        for item in events
        if str(item.get("event_type") or "") == "task_tool_observation_recorded"
    ]
    duplicate_events = [
        dict(item.get("payload") or {})
        for item in events
        if str(item.get("event_type") or "") == "task_duplicate_tool_call_guarded"
    ]

    assert result["ok"] is True
    assert runtime.model_runtime.task_invocation_count == 3
    assert len(tool_observations) == 1
    assert len(duplicate_events) == 1
    duplicate_payload = dict(dict(duplicate_events[0].get("observation") or {}).get("payload") or {})
    assert duplicate_payload.get("error_code") == "duplicate_read_only_tool_call"
    assert dict(duplicate_payload.get("tool_args") or {}).get("tool_name") == "path_exists"


def test_task_executor_blocks_repeated_tool_failure_after_guard_observation() -> None:
    failing_terminal = _tool_calls_action_request(
        tool_calls=[
            {
                "tool_name": "terminal",
                "args": {"command": "Write-Output 'repeat failure'; exit 7"},
            }
        ],
        public_progress_note="运行会失败的验证命令。",
    )
    runtime = build_harness_runtime(
        model_runtime=_TaskExecutorSequenceModelRuntime(
            [failing_terminal, failing_terminal, failing_terminal, failing_terminal],
            agent_turn_action_request=_action_request(action_type="respond", final_answer="unused"),
        ),
        permission_service=SimpleNamespace(
            current_mode=lambda: "full_access",
            supported_modes=lambda: ["default", "full_access"],
        ),
        tool_runtime=_tool_runtime_for_names(_project_backend_dir(), {"terminal"}),
    )
    task_run_id = _seed_active_work(
        runtime,
        task_run_id="taskrun:repeated-tool-failure",
        session_id="session-repeated-tool-failure",
    )

    result = asyncio.run(runtime.execute_task_run(task_run_id, max_steps=8))

    host = runtime.single_agent_runtime_host
    task_run = host.state_index.get_task_run(task_run_id)
    trace = host.get_trace(task_run_id, include_payloads=True)
    events = [dict(item) for item in list(dict(trace or {}).get("events") or [])]
    guard_events = [
        dict(item.get("payload") or {})
        for item in events
        if str(item.get("event_type") or "") == "task_repeated_tool_failure_guarded"
    ]
    tool_observations = [
        dict(dict(item.get("payload") or {}).get("observation") or {})
        for item in events
        if str(item.get("event_type") or "") == "task_tool_observation_recorded"
    ]

    assert result["error"] == "repeated_failure_limit_exceeded"
    assert runtime.model_runtime.task_invocation_count == 4
    assert task_run is not None
    assert task_run.status == "blocked"
    assert task_run.terminal_reason == "repeated_failure_limit_exceeded"
    recoverable = dict(dict(task_run.diagnostics or {}).get("recoverable_error") or {})
    assert recoverable.get("error_code") == "repeated_failure_limit_exceeded"
    assert recoverable.get("repeat_count") == 4
    assert len(tool_observations) == 4
    assert [payload.get("repeat_count") for payload in guard_events] == [3]
    guard_payload = dict(dict(guard_events[0].get("observation") or {}).get("payload") or {})
    assert guard_payload.get("failure_fingerprint") == recoverable.get("failure_fingerprint")
    assert guard_payload.get("repeat_count") == 3


def test_task_executor_repeated_admission_denial_pauses_before_step_budget() -> None:
    denied_action = _tool_action_request(
        tool_name="missing_tool_for_repeated_admission",
        args={"path": "tmp/not-allowed.txt"},
        public_progress_note="尝试调用未开放工具。",
    )
    runtime = build_harness_runtime(
        model_runtime=_TaskExecutorSequenceModelRuntime(
            [denied_action, denied_action, denied_action],
            agent_turn_action_request=_action_request(action_type="respond", final_answer="unused"),
        )
    )
    task_run_id = _seed_active_work(
        runtime,
        task_run_id="taskrun:repeated-admission-denial",
        session_id="session-repeated-admission-denial",
    )

    result = asyncio.run(runtime.execute_task_run(task_run_id, max_steps=8))

    host = runtime.single_agent_runtime_host
    task_run = host.state_index.get_task_run(task_run_id)
    trace = host.get_trace(task_run_id, include_payloads=True)
    events = [dict(item) for item in list(dict(trace or {}).get("events") or [])]
    event_types = [str(item.get("event_type") or "") for item in events]
    normal_admission_events = [
        dict(item.get("payload") or {})
        for item in events
        if str(item.get("event_type") or "") == "task_model_action_admission_observation_recorded"
    ]
    guard_events = [
        dict(item.get("payload") or {})
        for item in events
        if str(item.get("event_type") or "") == "task_repeated_model_action_admission_guarded"
    ]

    assert result["error"] == "repeated_admission_denial"
    assert result["retryable"] is True
    assert runtime.model_runtime.task_invocation_count == 3
    assert task_run is not None
    assert task_run.status == "waiting_executor"
    recoverable = dict(dict(task_run.diagnostics or {}).get("recoverable_error") or {})
    assert recoverable.get("error_code") == "repeated_admission_denial"
    assert recoverable.get("repeat_count") == 3
    assert len(normal_admission_events) == 1
    assert [payload.get("repeat_count") for payload in guard_events] == [2, 3]
    assert dict(dict(guard_events[-1].get("observation") or {}).get("payload") or {}).get("pause_after_observation") is True
    assert "task_executor_repeated_admission_denial_paused" in event_types
    assert "task_executor_step_budget_exhausted" not in event_types


def test_task_executor_wait_heartbeat_does_not_repeat_visible_step_summary(monkeypatch) -> None:
    monkeypatch.setattr("harness.loop.task_executor._TASK_MODEL_ACTION_WAIT_STATUS_INTERVAL_SECONDS", 0.001)
    runtime = build_harness_runtime(model_runtime=_SlowTaskExecutorModelRuntime())
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

    visible_invocation_steps = [
        event
        for event in events
        if str(dict(event).get("event_type") or "") == "step_summary_recorded"
        and str(dict(dict(event).get("payload") or {}).get("step") or "").startswith("task_model_action_invocation_started:")
    ]
    summaries = "\n".join(
        str(dict(dict(event).get("payload") or {}).get("summary") or "")
        for event in events
        if str(dict(event).get("event_type") or "") == "step_summary_recorded"
    )

    assert result["ok"] is True
    assert visible_invocation_steps == []
    assert visible_wait_steps == []
    assert wait_heartbeats
    assert "正在根据最新进展" not in summaries
    assert "思考下一步处理方式" not in summaries


def test_session_runtime_timeline_keeps_completed_task_attachment() -> None:
    from harness.runtime.session_timeline import build_session_runtime_timeline

    runtime = build_harness_runtime(
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
    assert attachment["anchor_role"] == "assistant"
    assert attachment["debug_trace_ref"] == lifecycle.task_run_id
    assert "public_timeline" in attachment
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


def test_session_runtime_timeline_projects_tool_observation_as_agent_visible_observation() -> None:
    from harness.runtime.session_timeline import build_session_runtime_timeline

    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    task_run_id = "taskrun:turn:session-observation:1:abc"
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id=task_run_id,
            session_id="session-observation",
            task_id="task:turn:session-observation:1",
            execution_runtime_kind="single_agent_task",
            status="running",
            created_at=1.0,
            updated_at=2.0,
            diagnostics={"turn_id": "turn:session-observation:1"},
        )
    )
    host.event_log.append(
        task_run_id,
        "task_tool_observation_recorded",
        payload={
            "observation": {
                "observation_id": "rtobs:session-observation:image",
                "source": "tool:image_generate",
                "payload": {
                    "tool_name": "image_generate",
                    "result": json.dumps(
                        {
                            "ok": False,
                            "error": "Image API request timed out",
                            "retryable": True,
                        },
                        ensure_ascii=False,
                    ),
                },
            }
        },
    )
    host.event_log.append(
        task_run_id,
        "step_summary_recorded",
        payload={
            "task_run_id": task_run_id,
            "step": "task_tool_observation_recorded:3",
            "status": "running",
            "summary": "工具调用已完成，正在根据结果继续。",
            "agent_brief_output": json.dumps(
                {
                    "ok": False,
                    "error": "Image API request timed out",
                    "retryable": True,
                },
                ensure_ascii=False,
            ),
        },
        refs={
            "turn_ref": "turn:session-observation:1",
            "observation_ref": "rtobs:session-observation:image",
            "tool_name": "image_generate",
        },
    )
    host.event_log.append(
        task_run_id,
        "step_summary_recorded",
        payload={
            "task_run_id": task_run_id,
            "step": "model_action_received:4",
            "status": "running",
            "summary": "重试生成主角美术图片，调整参数避免超时。",
            "public_progress_note": "重试生成主角美术图片，调整参数避免超时。",
            "public_action_state": {
                "current_judgment": "远程生图超时，但可以重试。",
                "next_action": "降低并发后继续生成资源。",
            },
        },
        refs={"turn_ref": "turn:session-observation:1"},
    )

    timeline = build_session_runtime_timeline(
        session_id="session-observation",
        history={"messages": []},
        runtime_host=host,
    )

    entries = timeline["runtime_attachments"][0]["progress_entries"]
    public_timeline = timeline["runtime_attachments"][0]["public_timeline"]
    assert [item["kind"] for item in entries] == ["observation", "model"]
    assert entries[0]["kind"] == "observation"
    assert entries[0]["title"] == "工具观察：image_generate"
    assert entries[0]["level"] == "error"
    assert entries[0]["body"] == "工具返回失败：Image API request timed out"
    assert entries[1]["kind"] == "model"
    assert entries[0]["toolName"] == "image_generate"
    assert entries[1]["body"] == "重试生成主角美术图片，调整参数避免超时。"
    assert entries[1]["meta"] == [
        {"label": "模型说明", "value": "远程生图超时，但可以重试。"},
        {"label": "计划动作", "value": "降低并发后继续生成资源。"},
    ]
    assert any(
        item.get("kind") == "assistant_text"
        and item.get("title") == "重试生成主角美术图片，调整参数避免超时。"
        for item in public_timeline
    )
    assert any(
        item.get("kind") == "blocked"
        and item.get("text") == "工具返回失败：Image API request timed out"
        for item in public_timeline
    )


def test_session_runtime_timeline_projects_turn_run_tool_progress() -> None:
    from harness.runtime.session_timeline import build_session_runtime_timeline

    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    session_id = "session-turn-timeline"
    turn_id = "turn:session-turn-timeline:7"
    turn_run_id = f"turnrun:{turn_id}"
    host.state_index.upsert_turn_run(
        TurnRun(
            turn_run_id=turn_run_id,
            session_id=session_id,
            turn_id=turn_id,
            status="completed",
            created_at=1.0,
            updated_at=3.0,
        )
    )
    host.event_log.append(
        turn_run_id,
        "model_action_admission_checked",
        payload={
            "turn_id": turn_id,
            "model_action_request": {
                "request_id": "model-action:turn-timeline:write",
                "turn_id": turn_id,
                "action_type": "tool_call",
                "public_progress_note": "已发起工具调用，正在等待工具返回：write_file。",
                "tool_call": {"tool_name": "write_file", "args": {"path": "docs/turn.md"}},
            },
            "admission": {"decision": "allow"},
        },
        refs={"turn_ref": turn_id, "turn_run_ref": turn_run_id},
    )
    host.event_log.append(
        turn_run_id,
        "turn_tool_observation_recorded",
        payload={
            "turn_id": turn_id,
            "tool_observation": {
                "observation_id": "toolobs:turn",
                "invocation_id": "toolinv:turn",
                "caller_kind": "turn_run",
                "caller_ref": turn_run_id,
                "tool_name": "write_file",
                "operation_id": "op:write",
                "status": "ok",
                "text": "Write succeeded: docs/turn.md",
                "result_envelope": {"tool_args": {"path": "docs/turn.md"}},
                "artifact_refs": [{"path": "docs/turn.md", "kind": "file"}],
            },
        },
        refs={"turn_ref": turn_id, "turn_run_ref": turn_run_id},
    )

    timeline = build_session_runtime_timeline(
        session_id=session_id,
        history={
            "messages": [
                {"role": "user", "content": "写文件", "turn_id": turn_id},
                {"role": "assistant", "content": "完成", "turn_id": turn_id, "id": "message:assistant"},
            ]
        },
        runtime_host=host,
    )

    attachment = timeline["runtime_attachments"][0]
    entries = attachment["progress_entries"]
    assert attachment["run_id"] == turn_run_id
    assert attachment["turn_run_id"] == turn_run_id
    assert attachment["task_run_id"] == ""
    assert attachment["anchor_turn_id"] == turn_id
    assert attachment["anchor_message_id"] == "message:assistant"
    assert attachment["debug_trace_ref"] == turn_run_id
    assert [item["title"] for item in entries] == [
        "正在写入 docs/turn.md",
        "写入完成 docs/turn.md",
    ]
    assert entries[1]["kind"] == "tool"
    assert entries[1]["toolName"] == "write_file"
    assert entries[1]["statusText"] == "已完成"
    assert entries[1]["artifacts"] == [{"label": "产物", "path": "docs/turn.md"}]
    assert any(item.get("kind") == "tool_activity" and item.get("title") == "写入完成 docs/turn.md" for item in attachment["public_timeline"])


def test_session_runtime_timeline_derives_turn_anchor_from_structural_task_run_id() -> None:
    from harness.runtime.session_timeline import build_session_runtime_timeline

    runtime = build_harness_runtime()
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


def test_session_runtime_timeline_emits_stable_anchor_message_id_for_original_assistant_turn() -> None:
    from harness.runtime.session_timeline import build_session_runtime_timeline

    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id="taskrun:turn:session-anchor-message:1:abc",
            session_id="session-anchor-message",
            task_id="task:turn:session-anchor-message:1",
            agent_profile_id="main_interactive_agent",
            execution_runtime_kind="single_agent_task",
            status="completed",
            terminal_reason="completed",
            created_at=1.0,
            updated_at=2.0,
            diagnostics={"turn_id": "turn:session-anchor-message:1"},
        )
    )

    timeline = build_session_runtime_timeline(
        session_id="session-anchor-message",
        history={
            "messages": [
                {"role": "user", "content": "开始旧任务"},
                {"role": "assistant", "content": "旧任务已接管", "id": "message:old-assistant"},
                {"role": "user", "content": "新的继续"},
                {"role": "assistant", "content": "新的回复", "id": "message:new-assistant"},
            ]
        },
        runtime_host=host,
    )

    attachment = timeline["runtime_attachments"][0]
    assert attachment["anchor_turn_id"] == "turn:session-anchor-message:1"
    assert attachment["anchor_message_id"] == "message:old-assistant"
    assert attachment["anchor_role"] == "assistant"


def test_session_runtime_timeline_ignores_legacy_child_event_as_control_anchor() -> None:
    from harness.runtime.session_timeline import build_session_runtime_timeline

    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    task_run_id = "taskrun:turn:session-child-anchor:8:abc"
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id=task_run_id,
            session_id="session-child-anchor",
            task_id="task:turn:session-child-anchor:8",
            agent_profile_id="main_interactive_agent",
            execution_runtime_kind="single_agent_task",
            status="aborted",
            terminal_reason="user_aborted",
            created_at=1.0,
            updated_at=2.0,
            diagnostics={"turn_id": "turn:session-child-anchor:8"},
        )
    )
    host.event_log.append(
        task_run_id,
        "legacy_task_run_child_created",
        payload={"lineage": {"turn_id": "turn:session-child-anchor:16"}},
        refs={"turn_ref": "turn:session-child-anchor:16"},
    )

    timeline = build_session_runtime_timeline(
        session_id="session-child-anchor",
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

    attachment = next(
        item for item in timeline["runtime_attachments"]
        if item["task_run_id"] == task_run_id
    )
    assert attachment["run_id"] == task_run_id
    assert attachment["anchor_turn_id"] == "turn:session-child-anchor:8"
    assert not any(item.get("eventType") == "legacy_task_run_child_created" for item in attachment["progress_entries"])


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
    from harness.loop.task_executor import is_task_run_executable, is_task_run_executor_claimed

    runtime = build_harness_runtime()
    session_id = "session-stale-running-waiting"
    task_run_id = _seed_active_work(
        runtime,
        task_run_id="taskrun:stale-running-waiting",
        session_id=session_id,
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

    host.active_turn_registry.start(session_id=session_id, turn_id="turn:session-stale-running-waiting:1")
    host.active_turn_registry.bind_task_run(
        session_id=session_id,
        turn_id="turn:session-stale-running-waiting:1",
        task_run_id=task_run_id,
        state="waiting_executor",
    )
    context = runtime._active_work_context_from_active_turn(session_id)
    task_run = host.state_index.get_task_run(task_run_id)

    assert task_run is not None
    assert context is not None
    assert context.running is False
    assert context.resumable is True
    assert context.same_run_allowed is True
    assert is_task_run_executor_claimed(task_run) is False
    assert is_task_run_executable(task_run) is True


def test_latest_waiting_executor_without_active_turn_is_projected_as_current_work_context() -> None:
    runtime = build_harness_runtime()
    session_id = "session-latest-waiting-context"
    task_run_id = _seed_active_work(
        runtime,
        task_run_id="taskrun:turn:session-latest-waiting-context:1:abc",
        session_id=session_id,
    )

    assert runtime._active_work_context_from_active_turn(session_id) is None
    context = runtime._current_work_context_from_latest_task(session_id)

    assert context is not None
    assert context.task_run_id == task_run_id
    assert context.resumable is True
    assert context.same_run_allowed is True
    assert context.running is False
    assert context.continuation_kind == "waiting"
    assert context.authority == "harness.runtime.current_session_task_context"


def test_terminal_latest_task_without_active_turn_is_not_projected_as_current_work_context() -> None:
    runtime = build_harness_runtime()
    session_id = "session-terminal-not-resumable-context"
    _seed_active_work(
        runtime,
        task_run_id="taskrun:turn:session-terminal-not-resumable-context:1:abc",
        session_id=session_id,
        status="failed",
    )

    assert runtime._active_work_context_from_active_turn(session_id) is None
    assert runtime._current_work_context_from_latest_task(session_id) is None


def test_request_task_run_reuses_current_session_task_after_active_turn_is_lost() -> None:
    session_id = "session-current-task-guard"
    existing_task_run_id = "taskrun:turn:session-current-task-guard:1:old"
    model = NativeToolCallModelRuntimeStub(
        agent_turn_action_request=_action_request(
            action_type="request_task_run",
            task_contract_seed={
                "user_visible_goal": "重新启动一个重复任务。",
                "task_run_goal": "这不应该创建第二个 TaskRun。",
                "completion_criteria": ["同一会话未完成任务只能有一个"],
            },
        )
    )
    runtime = build_harness_runtime(model_runtime=model)
    host = runtime.single_agent_runtime_host
    _seed_active_work(
        runtime,
        task_run_id=existing_task_run_id,
        session_id=session_id,
        status="running",
    )
    existing = host.state_index.get_task_run(existing_task_run_id)
    assert existing is not None
    host.state_index.upsert_task_run(
        replace(
            existing,
            updated_at=2.0,
            diagnostics={
                **dict(existing.diagnostics or {}),
                "executor_status": "scheduled",
                "latest_step_summary": "旧任务仍是当前会话的进行中任务。",
            },
        )
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(HarnessRuntimeRequest(session_id=session_id, message="继续")):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    stream_types = [str(event.get("type") or "") for event in events]
    session_task_runs = host.state_index.list_session_task_runs(session_id)
    terminal_events = [event for event in events if event.get("type") == "agent_turn_terminal"]

    assert "task_run_lifecycle_reused_current" in stream_types
    assert "task_run_lifecycle_started" not in stream_types
    assert [task.task_run_id for task in session_task_runs] == [existing_task_run_id]
    assert any(event.get("type") == "done" and event.get("terminal_reason") == "session_active_task_exists" for event in events)
    assert terminal_events
    assert dict(dict(terminal_events[-1].get("event") or {}).get("payload") or {}).get("terminal_reason") == "session_active_task_exists"


def test_request_task_run_resumes_blocked_current_session_task_without_creating_second_task() -> None:
    session_id = "session-current-task-blocked-resume"
    existing_task_run_id = "taskrun:turn:session-current-task-blocked-resume:1:old"
    model = NativeToolCallModelRuntimeStub(
        agent_turn_action_request=_action_request(
            action_type="request_task_run",
            task_contract_seed={
                "user_visible_goal": "继续当前被阻塞的任务。",
                "task_run_goal": "这应该复用同一个 TaskRun 并恢复运行态。",
                "completion_criteria": ["同一会话仍然只有一个任务"],
            },
        )
    )
    runtime = build_harness_runtime(model_runtime=model)
    host = runtime.single_agent_runtime_host
    _seed_active_work(
        runtime,
        task_run_id=existing_task_run_id,
        session_id=session_id,
        status="blocked",
    )
    existing = host.state_index.get_task_run(existing_task_run_id)
    assert existing is not None
    host.state_index.upsert_task_run(
        replace(
            existing,
            terminal_reason="model_call_recovery_required",
            diagnostics={
                **dict(existing.diagnostics or {}),
                "executor_status": "blocked",
                "latest_step": "task_executor_blocked",
                "latest_step_status": "blocked",
                "latest_step_summary": "旧阻塞信息不应该继续占据监控当前态。",
            },
        )
    )

    spawned: list[str] = []

    def _capture_background_task(coro, *, name: str = ""):
        spawned.append(name)
        coro.close()
        return SimpleNamespace()

    host.spawn_background_task = _capture_background_task

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(HarnessRuntimeRequest(session_id=session_id, message="继续")):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    stream_types = [str(event.get("type") or "") for event in events]
    session_task_runs = host.state_index.list_session_task_runs(session_id)
    task_run = host.state_index.get_task_run(existing_task_run_id)
    monitor = host.monitor_projector.build_global_monitor(host.state_index.list_task_runs(), now=10.0, limit=20)
    visible = {item["task_run_id"]: item for item in monitor["task_runs"]}

    assert "task_run_lifecycle_resumed_current" in stream_types
    assert "task_run_lifecycle_started" not in stream_types
    assert [task.task_run_id for task in session_task_runs] == [existing_task_run_id]
    assert spawned
    assert task_run is not None
    assert task_run.status == "running"
    assert task_run.terminal_reason == ""
    diagnostics = dict(task_run.diagnostics or {})
    assert diagnostics["latest_step"] == "task_executor_scheduled"
    assert diagnostics["latest_step_status"] == "running"
    assert diagnostics["latest_step_summary"] != "旧阻塞信息不应该继续占据监控当前态。"
    assert diagnostics["recovery_action"] == "resume_task_run"
    assert dict(diagnostics["recoverable_error"])["retryable"] is True
    assert visible[existing_task_run_id]["status"] == "running"
    assert visible[existing_task_run_id]["bucket"] == "running"
    assert visible[existing_task_run_id]["summary"] != "旧阻塞信息不应该继续占据监控当前态。"


def test_terminal_bound_active_turn_is_cleared_and_continue_starts_new_task_run() -> None:
    session_id = "session-terminal-bound-active-turn"
    old_task_run_id = "taskrun:terminal-bound-active-turn:old"
    model = NativeToolCallModelRuntimeStub(
        agent_turn_action_request=_action_request(
            action_type="request_task_run",
            task_contract_seed={
                "user_visible_goal": "继续完成新的交付任务。",
                "task_run_goal": "基于当前用户请求建立新的 TaskRun。",
                "completion_criteria": ["新任务必须独立于 terminal 旧任务"],
            },
        )
    )
    runtime = build_harness_runtime(model_runtime=model)
    host = runtime.single_agent_runtime_host
    _seed_active_work(runtime, task_run_id=old_task_run_id, session_id=session_id, status="aborted")
    old_task = host.state_index.get_task_run(old_task_run_id)
    assert old_task is not None
    host.state_index.upsert_task_run(replace(old_task, terminal_reason="user_aborted"))
    host.active_turn_registry.start(session_id=session_id, turn_id="turn:terminal-bound-active-turn:old")
    host.active_turn_registry.bind_task_run(
        session_id=session_id,
        turn_id="turn:terminal-bound-active-turn:old",
        task_run_id=old_task_run_id,
        state="waiting_executor",
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(HarnessRuntimeRequest(session_id=session_id, message="继续")):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    stream_types = [str(event.get("type") or "") for event in events]
    admissions = _admission_payloads(events)
    session_task_runs = host.state_index.list_session_task_runs(session_id)
    new_task_runs = [task for task in session_task_runs if task.task_run_id != old_task_run_id]
    old_trace = host.get_trace(old_task_run_id, include_payloads=True)
    old_event_types = [str(dict(item).get("event_type") or "") for item in list(dict(old_trace or {}).get("events") or [])]

    assert "active_task_steer_accepted" not in stream_types
    assert "task_run_lifecycle_started" in stream_types
    assert admissions
    assert dict(admissions[0].get("model_action_request") or {}).get("action_type") == "request_task_run"
    assert len(new_task_runs) == 1
    new_task = new_task_runs[0]
    diagnostics = dict(new_task.diagnostics or {})
    assert diagnostics.get("origin_kind") == "single_agent_turn_json_action"
    assert diagnostics.get("parent_task_run_id") in {None, ""}
    assert "lineage" not in diagnostics
    assert "task_run_resume_requested" not in old_event_types


def test_execute_task_run_rejects_duplicate_running_claim() -> None:
    runtime = build_harness_runtime(
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
    runtime = build_harness_runtime(
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
    runtime = build_harness_runtime(model_runtime=model_runtime)
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

    runtime = build_harness_runtime(model_runtime=_CapturingModelRuntime())
    runtime.agent_runtime_registry.upsert_profile(
        agent_id="agent:3",
        agent_profile_id="custom_single_agent_task_profile",
        allowed_operations=("op.model_response",),
        metadata={},
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
    assert assembly["agent_prompt_refs"] == []
    assert assembly["agent_prompt_refs_by_invocation"] == {}
    assert agent_runs[-1].agent_id == "agent:3"
    assert agent_run_results[-1].agent_id == "agent:3"


def test_schedule_task_run_executor_marks_startup_exception_blocked() -> None:
    runtime = build_harness_runtime()
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
                "image_assets": {
                    "base_url": "https://image.example.test/v1",
                    "model": "image-test-model",
                    "api_key_present": True,
                }
            }

    runtime = build_harness_runtime(settings_service=_SettingsWithBackendConfig())

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
    runtime = build_harness_runtime(
        model_runtime=NativeToolCallModelRuntimeStub(
            content="",
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
            HarnessRuntimeRequest(
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
    from harness.loop.task_executor_controller import TaskExecutorController

    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id="taskrun:interrupted-executor",
            session_id="session-interrupted-executor",
            task_id="task:interrupted-executor",
            execution_runtime_kind="single_agent_task",
            status="running",
            diagnostics={
                "executor_status": "scheduled",
                "latest_step": "task_executor_scheduled",
                "latest_step_summary": "正在根据最新进展思考下一步处理方式。",
                "latest_public_progress_note": "正在根据最新进展思考下一步处理方式。",
            },
        )
    )

    result = TaskExecutorController(runtime_host=host, execute_task_run_callback=runtime.execute_task_run).recover_interrupted_executor_leases()
    task_run = host.state_index.get_task_run("taskrun:interrupted-executor")

    assert result["recovered_count"] == 1
    assert result["authority"] == "harness.loop.task_executor_controller.runtime_start_recovery"
    assert task_run is not None
    assert task_run.status == "waiting_executor"
    assert task_run.terminal_reason == "waiting_executor"
    diagnostics = dict(task_run.diagnostics or {})
    assert diagnostics.get("executor_status") == "waiting_executor"
    assert diagnostics.get("latest_step_summary") == "后端运行时已重启，当前工作已恢复为可继续状态。"
    assert diagnostics.get("latest_public_progress_note") == "后端运行时已重启，当前工作已恢复为可继续状态。"


def test_runtime_start_recovery_skips_graph_node_assigned_task_run() -> None:
    from harness.loop.task_executor_controller import TaskExecutorController

    runtime = build_harness_runtime()
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

    result = TaskExecutorController(runtime_host=host, execute_task_run_callback=runtime.execute_task_run).recover_interrupted_executor_leases()
    task_run = host.state_index.get_task_run("gtask:graph:node:work")

    assert result["recovered_count"] == 0
    assert result["task_run_ids"] == []
    assert result["skipped_graph_node_task_run_ids"] == ["gtask:graph:node:work"]
    assert task_run is not None
    assert task_run.status == "running"
    assert dict(task_run.diagnostics or {}).get("executor_status") == "scheduled"


def test_task_run_executor_keeps_model_call_failure_recoverable() -> None:
    runtime = build_harness_runtime(model_runtime=_FailingModelRuntime())
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
    runtime = build_harness_runtime(
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
    runtime = build_harness_runtime(
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
    runtime = build_harness_runtime(
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
    runtime = build_harness_runtime(
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

    runtime = build_harness_runtime()
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


def test_waiting_approval_task_run_requires_bound_grant_before_resume() -> None:
    from harness.loop.task_executor import (
        approve_task_run_tool_call,
        is_task_run_executable,
        resume_paused_task_run,
    )
    from harness.loop.task_tool_approval import tool_args_hash

    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    task_run_id = "taskrun:resume-tool-approval"
    contract = TaskRunContract(
        contract_id="task-contract:resume-tool-approval",
        contract_source="test",
        user_visible_goal="恢复等待审批的工具调用。",
        task_run_goal="恢复等待审批的工具调用。",
        completion_criteria=("审批后同一个 TaskRun 可以继续调度",),
    )
    contract_ref = host.runtime_objects.put_object("task_run_contract", contract.contract_id, contract.to_dict())
    host.runtime_objects.put_object(
        "task_lifecycle",
        task_run_id,
        TaskLifecycleRecord(
            task_run_id=task_run_id,
            contract_ref=contract_ref,
            status="waiting_approval",
            created_at=1.0,
            updated_at=1.0,
            terminal_reason="waiting_approval",
        ).to_dict(),
    )
    pending_approval = {
        "status": "pending",
        "task_run_id": task_run_id,
        "action_request_ref": "model-action:test:browser",
        "approval_request_id": "approval-request:test:browser",
        "tool_call_id": "call:browser",
        "tool_name": "browser_control",
        "operation_id": "op.browser_control",
        "directive_ref": f"runtime-directive:{task_run_id}:tool:model-action:test:browser",
        "approval_risk_fingerprint": "risk:browser:approved-url",
        "tool_args_hash": tool_args_hash({"action": "open", "url": "https://example.com"}),
        "action_request": {
            "request_id": "model-action:test:browser",
            "action_type": "tool_call",
            "tool_call": {
                "tool_name": "browser_control",
                "operation_id": "op.browser_control",
                "args": {"action": "open", "url": "https://example.com"},
            },
        },
    }
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id=task_run_id,
            session_id="session-resume-tool-approval",
            task_id="task:resume-tool-approval",
            task_contract_ref=contract_ref,
            execution_runtime_kind="single_agent_task",
            status="waiting_approval",
            terminal_reason="waiting_approval",
            diagnostics={
                "contract": contract.to_dict(),
                "executor_status": "waiting_approval",
                "pending_approval": pending_approval,
            },
        )
    )

    initial_task = host.state_index.get_task_run(task_run_id)
    denied_resume = resume_paused_task_run(host, task_run_id, reason="未审批直接继续")

    assert initial_task is not None
    assert is_task_run_executable(initial_task) is False
    assert denied_resume["ok"] is False
    assert denied_resume["error"] == "task_run_waiting_approval_requires_grant"

    approval_result = approve_task_run_tool_call(host, task_run_id, reason="允许打开此 URL")
    approved_task = host.state_index.get_task_run(task_run_id)

    assert approval_result["ok"] is True
    assert approved_task is not None
    assert approved_task.status == "waiting_approval"
    assert dict(dict(approved_task.diagnostics or {}).get("pending_approval") or {}).get("status") == "approved"
    assert is_task_run_executable(approved_task) is True

    resume_result = resume_paused_task_run(host, task_run_id, reason="审批后继续")
    resumed_task = host.state_index.get_task_run(task_run_id)

    assert resume_result["ok"] is True
    assert resumed_task is not None
    assert resumed_task.status == "waiting_executor"
    assert resumed_task.terminal_reason == "waiting_executor"
    assert dict(resumed_task.diagnostics or {}).get("executor_status") == "waiting_executor"
    assert dict(dict(resumed_task.diagnostics or {}).get("runtime_control") or {}).get("state") == "resume_requested"
    assert dict(dict(resumed_task.diagnostics or {}).get("pending_approval") or {}).get("status") == "approved"
    assert dict(dict(resumed_task.diagnostics or {}).get("approval_state") or {}).get("status") == "approved"
    assert is_task_run_executable(resumed_task) is True


def test_task_run_executor_step_budget_exhaustion_waits_for_next_run() -> None:
    runtime = build_harness_runtime(
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

    runtime = build_harness_runtime(
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

    runtime = build_harness_runtime()
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


def test_user_aborted_work_rollout_records_breakpoint_but_not_active_work_context() -> None:
    from harness.loop.task_executor import stop_task_run
    from harness.loop.work_rollout import work_rollout_summary

    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    contract = TaskRunContract(
        contract_id="task-contract:rollout-breakpoint",
        contract_source="test",
        user_visible_goal="验证 rollout 断点。",
        task_run_goal="停止后只保留审计断点，不形成当前工作。",
        completion_criteria=("断点只作为历史事实",),
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

    host.active_turn_registry.start(session_id="session-rollout-breakpoint", turn_id="turn:rollout-breakpoint:2")
    host.active_turn_registry.bind_task_run(
        session_id="session-rollout-breakpoint",
        turn_id="turn:rollout-breakpoint:2",
        task_run_id="taskrun:rollout-breakpoint",
        state="waiting_executor",
    )

    assert host.active_turn_registry.resolve_current("session-rollout-breakpoint") is None
    assert runtime._active_work_context_from_active_turn("session-rollout-breakpoint") is None


def _seed_active_work(
    runtime,
    *,
    task_run_id: str = "taskrun:active-work",
    session_id: str = "session-active-work",
    status: str = "waiting_executor",
    runtime_profile: dict[str, object] | None = None,
) -> str:
    host = runtime.single_agent_runtime_host
    contract = TaskRunContract(
        contract_id=f"task-contract:{task_run_id.replace(':', '-')}",
        contract_source="test",
        user_visible_goal="继续优化会话体验。",
        task_run_goal="继续优化会话体验。",
        completion_criteria=("同一个当前工作可以被自然语言控制",),
        runtime_profile=dict(runtime_profile or {}),
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
            diagnostics={
                "contract": contract.to_dict(),
                "latest_step_summary": "正在整理上下文，准备继续处理。",
                "runtime_task_selection": {"runtime_profile": dict(runtime_profile or {})},
            },
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


def test_active_work_turn_policy_does_not_rewrite_direct_answer_action() -> None:
    from harness.loop.active_work import active_work_turn_decision_from_payload

    decision = active_work_turn_decision_from_payload(
        {
            "authority": "harness.loop.active_work_turn_decision",
            "action": "continue_active_work",
            "answer_obligation": "direct_answer_required",
            "continuation_strategy": "same_run_resume",
            "relation_to_current_work": "current_work",
            "evidence": "用户既问状态又要求继续",
            "response": "当前工作还在等待继续，我会接着处理。",
            "confidence": 0.95,
        },
        user_message="现在做到哪了？继续",
    )

    assert decision.accepted is True
    assert decision.action == "continue_active_work"
    assert decision.answer_obligation == "direct_answer_required"
    assert decision.continuation_strategy == "same_run_resume"
    assert decision.denied_reason == ""


def test_active_work_turn_policy_rejects_non_control_subaction() -> None:
    from harness.loop.active_work import active_work_turn_decision_from_payload

    decision = active_work_turn_decision_from_payload(
        {
            "authority": "harness.loop.active_work_turn_decision",
            "action": "normal_response",
            "relation_to_current_work": "independent_turn",
            "response": "这应该作为普通回复，而不是当前工作控制。",
        },
        user_message="解释一下 checkpoint",
    )

    assert decision.accepted is False
    assert decision.denied_reason == "active_work_control_action_not_allowed"


def test_active_work_relation_mismatch_blocks_without_control_side_effects() -> None:
    model = _ActiveWorkDecisionModelRuntime([
        {
            "action": "continue_active_work",
            "relation_to_current_work": "independent_turn",
            "evidence": "模型调用当前工作控制但声明独立请求",
            "response": "这不应该控制当前工作。",
            "confidence": 0.7,
        }
    ])
    runtime = build_harness_runtime(model_runtime=model)
    task_run_id = _seed_active_work(runtime, task_run_id="taskrun:active-work-relation-mismatch")

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-active-work",
                message="解释一下 checkpoint",
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    trace = runtime.single_agent_runtime_host.get_trace(task_run_id, include_payloads=True)
    event_types = [str(dict(item).get("event_type") or "") for item in list(dict(trace or {}).get("events") or [])]

    assert model.active_work_decision_count == 1
    assert not any(event.get("type") == "active_task_steer_accepted" for event in events)
    assert any(
        event.get("type") == "done"
        and event.get("answer_channel") == "blocked"
        and event.get("terminal_reason") == "active_work_relation_declared_independent"
        and "没有控制当前工作" in str(event.get("content") or "")
        for event in events
    )
    assert any(
        event.get("type") == "agent_turn_terminal"
        and dict(dict(event.get("event") or {}).get("payload") or {}).get("terminal_reason") == "active_work_relation_declared_independent"
        for event in events
    )
    assert "active_task_steer_recorded" not in event_types
    assert "task_run_resume_requested" not in event_types


def test_active_turn_input_goes_through_model_turn_instead_of_registry_steer() -> None:
    model = _ActiveWorkDecisionModelRuntime([
        {
            "action": "answer_about_active_work",
            "relation_to_current_work": "current_work",
            "evidence": "用户询问当前工作状态",
            "response": "当前工作还在等待继续执行。",
            "confidence": 0.9,
        }
    ])
    runtime = build_harness_runtime(model_runtime=model)
    task_run_id = _seed_active_work(runtime, task_run_id="taskrun:active-turn-model-decision")

    host = runtime.single_agent_runtime_host
    host.active_turn_registry.start(session_id="session-active-work", turn_id="turn:active:current")
    host.active_turn_registry.bind_task_run(
        session_id="session-active-work",
        turn_id="turn:active:current",
        task_run_id=task_run_id,
        state="waiting_executor",
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-active-work",
                message="现在做到哪了？",
                expected_active_turn_id="turn:active:current",
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    event_types = [str(event.get("type") or "") for event in events]
    updated_task = host.state_index.get_task_run(task_run_id)

    assert "single_agent_turn_started" in event_types
    assert "active_task_steer_accepted" not in event_types
    assert model.active_work_decision_count == 1
    assert updated_task is not None
    assert int(dict(updated_task.diagnostics or {}).get("pending_user_steer_count") or 0) == 0
    assert any(event.get("type") == "done" and "当前工作还在等待继续执行" in str(event.get("content") or "") for event in events)


def test_running_active_turn_input_is_queued_without_model_turn() -> None:
    model = _ActiveWorkDecisionModelRuntime([
        {
            "action": "answer_about_active_work",
            "relation_to_current_work": "current_work",
            "evidence": "不应调用模型",
            "response": "不应出现。",
            "confidence": 0.9,
        }
    ])
    runtime = build_harness_runtime(model_runtime=model)
    task_run_id = _seed_active_work(
        runtime,
        task_run_id="taskrun:active-turn-running-queue",
        status="running",
    )

    host = runtime.single_agent_runtime_host
    host.active_turn_registry.start(session_id="session-active-work", turn_id="turn:active:current")
    host.active_turn_registry.bind_task_run(
        session_id="session-active-work",
        turn_id="turn:active:current",
        task_run_id=task_run_id,
        state="running_task",
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-active-work",
                message="新增一个限制：不要生成临时假数据。",
                expected_active_turn_id="turn:active:current",
                active_turn_input_policy="steer",
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    event_types = [str(event.get("type") or "") for event in events]
    updated_task = host.state_index.get_task_run(task_run_id)
    trace = host.get_trace(task_run_id, include_payloads=True)
    trace_event_types = [str(dict(item).get("event_type") or "") for item in list(dict(trace or {}).get("events") or [])]
    session_messages = runtime.session_manager.load_session("session-active-work")

    assert "single_agent_turn_started" not in event_types
    assert "active_task_steer_accepted" in event_types
    assert model.active_work_decision_count == 0
    assert updated_task is not None
    assert int(dict(updated_task.diagnostics or {}).get("pending_user_steer_count") or 0) == 1
    assert "active_task_steer_recorded" in trace_event_types
    assert any(
        event.get("type") == "done"
        and event.get("completion_state") == "task_steer_accepted"
        and "已加入当前任务队列" in str(event.get("content") or "")
        for event in events
    )
    assert [str(item.get("role") or "") for item in session_messages] == ["user"]


def test_active_turn_preserves_user_granted_new_turn_capabilities(tmp_path: Path) -> None:
    class RecordingCapabilityModelRuntime(NativeToolCallModelRuntimeStub):
        def __init__(self) -> None:
            super().__init__(content="普通回复。")
            self.last_messages: list[dict[str, object]] = []

        async def invoke_messages_with_tools(self, messages, tools, **kwargs):
            self.last_messages = [dict(item) for item in list(messages or []) if isinstance(item, dict)]
            return await super().invoke_messages_with_tools(messages, tools, **kwargs)

    model = RecordingCapabilityModelRuntime()
    tool_base_dir = _project_backend_dir()
    runtime = build_harness_runtime(
        base_dir=_runtime_test_root(tmp_path),
        model_runtime=model,
        tool_runtime=_tool_runtime_for_names(tool_base_dir, {"read_file", "write_file", "terminal"}),
    )
    task_run_id = _seed_active_work(runtime, task_run_id="taskrun:active-turn-preserve-capabilities", session_id="session-active-preserve")
    host = runtime.single_agent_runtime_host
    host.active_turn_registry.start(session_id="session-active-preserve", turn_id="turn:active-preserve:current")
    host.active_turn_registry.bind_task_run(
        session_id="session-active-preserve",
        turn_id="turn:active-preserve:current",
        task_run_id=task_run_id,
        state="waiting_executor",
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-active-preserve",
                message="这个先放着，检查一下项目文件。",
                task_selection={
                    "task_environment_id": "env.development.sandbox",
                    "control_capabilities": {
                        "may_call_tools": True,
                        "may_request_task_run": True,
                        "may_control_active_work": True,
                    },
                },
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    assembly = dict(next(event for event in events if event.get("type") == "runtime_assembly_compiled").get("runtime_assembly") or {})
    start = dict(next(event for event in events if event.get("type") == "single_agent_turn_started"))
    stable_payload = _packet_payload_after_title(
        str(model.last_messages[1].get("content") or ""),
        "Single agent turn stable boundary",
    )
    packet_tools = {str(dict(tool).get("name") or "") for tool in list(model.seen_tools[0] or [])}
    capabilities = dict(assembly.get("control_capabilities") or {})
    effective_capabilities = dict(stable_payload.get("control_capabilities") or {})

    assert capabilities.get("may_call_tools") is True
    assert capabilities.get("may_request_task_run") is True
    assert "tool_call" in start.get("allowed_action_types")
    assert "request_task_run" in start.get("allowed_action_types")
    assert {"read_file", "write_file", "terminal"} <= packet_tools
    assert effective_capabilities.get("may_call_tools") is True
    assert effective_capabilities.get("may_request_task_run") is True
    assert dict(dict(assembly.get("task_selection") or {}).get("runtime_facts") or {}).get("active_turn_capability_policy") == "preserve_user_granted_capabilities"


def test_active_work_control_requires_expected_active_turn_id_for_bound_active_turn() -> None:
    model = _ActiveWorkDecisionModelRuntime([
        {
            "action": "continue_active_work",
            "relation_to_current_work": "current_work",
            "evidence": "用户说继续当前工作",
            "response": "不应继续。",
            "confidence": 0.9,
        }
    ])
    runtime = build_harness_runtime(model_runtime=model)
    task_run_id = _seed_active_work(runtime, task_run_id="taskrun:active-turn-expected-required")

    host = runtime.single_agent_runtime_host
    host.active_turn_registry.start(session_id="session-active-work", turn_id="turn:active:current")
    host.active_turn_registry.bind_task_run(
        session_id="session-active-work",
        turn_id="turn:active:current",
        task_run_id=task_run_id,
        state="waiting_executor",
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-active-work",
                message="继续当前工作",
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    trace = runtime.single_agent_runtime_host.get_trace(task_run_id, include_payloads=True)
    event_types = [str(dict(item).get("event_type") or "") for item in list(dict(trace or {}).get("events") or [])]

    assert model.active_work_decision_count == 1
    assert any(event.get("type") == "done" and "需要刷新会话状态" in str(event.get("content") or "") for event in events)
    assert any(
        event.get("type") == "agent_turn_terminal"
        and dict(dict(event.get("event") or {}).get("payload") or {}).get("terminal_reason") == "expected_active_turn_id_required"
        for event in events
    )
    assert "active_task_steer_recorded" not in event_types
    assert "task_run_resume_requested" not in event_types


def test_active_work_control_rejects_stale_expected_active_turn_id() -> None:
    model = _ActiveWorkDecisionModelRuntime([
        {
            "action": "continue_active_work",
            "relation_to_current_work": "current_work",
            "evidence": "用户说继续当前工作",
            "response": "不应继续。",
            "confidence": 0.9,
        }
    ])
    runtime = build_harness_runtime(model_runtime=model)
    task_run_id = _seed_active_work(runtime, task_run_id="taskrun:active-turn-expected-stale")

    host = runtime.single_agent_runtime_host
    host.active_turn_registry.start(session_id="session-active-work", turn_id="turn:active:current")
    host.active_turn_registry.bind_task_run(
        session_id="session-active-work",
        turn_id="turn:active:current",
        task_run_id=task_run_id,
        state="waiting_executor",
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-active-work",
                message="继续当前工作",
                expected_active_turn_id="turn:active:stale",
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    trace = runtime.single_agent_runtime_host.get_trace(task_run_id, include_payloads=True)
    event_types = [str(dict(item).get("event_type") or "") for item in list(dict(trace or {}).get("events") or [])]

    assert model.active_work_decision_count == 1
    assert any(event.get("type") == "done" and "当前任务状态已变化" in str(event.get("content") or "") for event in events)
    assert any(
        event.get("type") == "agent_turn_terminal"
        and dict(dict(event.get("event") or {}).get("payload") or {}).get("terminal_reason") == "expected_active_turn_mismatch"
        for event in events
    )
    assert "active_task_steer_recorded" not in event_types
    assert "task_run_resume_requested" not in event_types


def test_single_agent_turn_does_not_control_active_work_without_native_action() -> None:
    class NoActiveWorkToolModelRuntime:
        def __init__(self) -> None:
            self.active_work_decision_count = 0

        async def invoke_messages_with_tools(self, _messages, tools, **_kwargs):
            return SimpleNamespace(content="普通回复。", tool_calls=[])

        async def invoke_messages(self, _messages, **_kwargs):
            return SimpleNamespace(content="普通回复。")

    model = NoActiveWorkToolModelRuntime()
    runtime = build_harness_runtime(model_runtime=model)
    task_run_id = _seed_active_work(runtime, task_run_id="taskrun:active-work-route-gate")

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(HarnessRuntimeRequest(session_id="session-active-work", message="解释一下 LangGraph 的 checkpoint 机制")):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    trace = runtime.single_agent_runtime_host.get_trace(task_run_id, include_payloads=True)
    event_types = [str(dict(item).get("event_type") or "") for item in list(dict(trace or {}).get("events") or [])]

    assert model.active_work_decision_count == 0
    assert any(event.get("type") == "done" and str(event.get("content") or "") == "普通回复。" for event in events)
    assert any(event.get("type") == "runtime_assembly_compiled" for event in events)
    assert "task_run_resume_requested" not in event_types
    assert "active_task_steer_recorded" not in event_types


def test_capability_boundary_bypasses_active_work_control() -> None:
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
    runtime = build_harness_runtime(model_runtime=model)
    task_run_id = _seed_active_work(runtime, task_run_id="taskrun:capability-boundary-active-work")

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-active-work",
                message="修复了吗",
                task_selection={
                    "control_capabilities": {
                        "may_call_tools": False,
                        "may_request_task_run": False,
                        "may_control_active_work": False,
                        "may_use_subagents": False,
                    }
                },
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
    runtime = build_harness_runtime(model_runtime=model)
    task_run_id = _seed_active_work(runtime, task_run_id="taskrun:active-work-context-disabled")

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
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
    runtime = build_harness_runtime(model_runtime=model)
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
    runtime = build_harness_runtime(model_runtime=model)
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
    runtime = build_harness_runtime(model_runtime=model)
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
    runtime = build_harness_runtime(model_runtime=model)
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
    runtime = build_harness_runtime(model_runtime=model)
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


def test_stopped_task_cannot_be_revived_by_stale_executor_or_write_tool() -> None:
    from harness.loop.task_executor import stop_task_run

    runtime = build_harness_runtime(
        model_runtime=_TaskExecutorSequenceModelRuntime(
            [
                _tool_action_request(
                    tool_name="write_file",
                    args={"path": "storage/task_environments/general/workspace/artifacts/should_not_exist.txt", "content": "bad"},
                    public_progress_note="准备写入测试文件。",
                )
            ],
            agent_turn_action_request=_action_request(action_type="respond", final_answer="unused"),
        )
    )
    task_run_id = _seed_active_work(runtime, task_run_id="taskrun:stopped-no-write")
    host = runtime.single_agent_runtime_host
    stop_task_run(host, task_run_id, reason="user_stop", requested_by="user")

    result = asyncio.run(runtime.execute_task_run(task_run_id, max_steps=1))
    task_run = host.state_index.get_task_run(task_run_id)
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
    written_path = Path(runtime.base_dir) / "storage/task_environments/general/workspace/artifacts/should_not_exist.txt"

    assert result["ok"] is False
    assert result["error"] == "user_aborted"
    assert task_run is not None
    assert task_run.status == "aborted"
    assert task_run.terminal_reason == "user_aborted"
    assert diagnostics["executor_status"] == "stopped"
    assert not written_path.exists()
    assert not any(
        dict(event.payload or {}).get("model_action_request")
        for event in host.event_log.list_events(task_run_id)
        if event.event_type == "model_action_request_received"
    )


def test_task_executor_records_task_action_without_cross_context_fields() -> None:
    runtime = build_harness_runtime(
        model_runtime=_TaskExecutorSequenceModelRuntime(
            [_action_request(action_type="respond", final_answer="已完成当前任务。")],
            agent_turn_action_request=_action_request(action_type="respond", final_answer="unused"),
        )
    )
    task_run_id = _seed_active_work(runtime, task_run_id="taskrun:slim-task-action")
    host = runtime.single_agent_runtime_host

    asyncio.run(runtime.execute_task_run(task_run_id, max_steps=1))
    event = next(
        event
        for event in host.event_log.list_events(task_run_id)
        if event.event_type == "model_action_request_received"
    )
    action_payload = dict(dict(event.payload or {}).get("model_action_request") or {})

    assert action_payload["action_type"] == "respond"
    assert "task_contract_seed" not in action_payload
    assert "completion_contract" not in action_payload
    assert "permission_request" not in action_payload
    assert "engagement_request" not in action_payload
    assert "active_work_control" not in action_payload
    assert "selected_skill_ids" not in action_payload


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
    runtime = build_harness_runtime(model_runtime=model)
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


def test_explicit_capability_boundary_uses_single_agent_turn() -> None:
    runtime = build_harness_runtime(
        model_runtime=SingleMessageModelRuntimeStub(content="单轮收口回答")
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-role",
                message="保持角色对话。",
                task_selection={
                    "control_capabilities": {
                        "may_call_tools": False,
                        "may_request_task_run": False,
                        "may_control_active_work": False,
                        "may_use_subagents": False,
                    },
                },
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    assembly = dict(next(event for event in events if event.get("type") == "runtime_assembly_compiled").get("runtime_assembly") or {})
    profile = dict(assembly.get("profile") or {})
    branch = dict(next(event for event in events if event.get("type") == "runtime_branch_decided").get("runtime_branch") or {})
    capabilities = dict(assembly.get("control_capabilities") or {})

    assert profile["profile_ref"] == "main_interactive_agent"
    assert "conversation_only" not in capabilities
    assert capabilities.get("may_call_tools") is False
    assert capabilities.get("may_request_task_run") is False
    assert capabilities.get("may_control_active_work") is False
    assert branch.get("branch_kind") == "single_agent_turn"
    assert not any(event.get("type") == "model_action_admission" for event in events)
    assert any(event.get("type") == "done" and str(event.get("content") or "") == "单轮收口回答" for event in events)
    assert not any(
        event.get("type") == "task_run_lifecycle_started"
        for event in events
    )


def test_task_run_permission_without_tools_uses_single_agent_turn_for_direct_answer() -> None:
    runtime = build_harness_runtime(model_runtime=SingleMessageModelRuntimeStub(content="可以直接回答。"))

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
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
    branch = dict(next(event for event in events if event.get("type") == "runtime_branch_decided").get("runtime_branch") or {})

    assert branch.get("branch_kind") == "single_agent_turn"
    assert "single_agent_turn_started" in stream_types
    assert "runtime_invocation_packet" not in stream_types
    assert "model_action_request" not in stream_types
    assert "task_run_lifecycle_started" not in stream_types
    assert any(event.get("type") == "done" and str(event.get("content") or "") == "可以直接回答。" for event in events)


def test_single_agent_turn_request_task_run_tool_starts_real_task_lifecycle() -> None:
    model = _UnexpectedNativeToolCallModelRuntime(
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
                    "public_progress_note": "我先把页面目标转成可执行任务，然后推进实现和文件验证。",
                },
            }
        ]
    )
    runtime = build_harness_runtime(model_runtime=model)

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
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
    branch = dict(next(event for event in events if event.get("type") == "runtime_branch_decided").get("runtime_branch") or {})
    lifecycle = [event for event in events if event.get("type") == "task_run_lifecycle_started"][0]
    task_run_event = dict(lifecycle.get("event") or {})
    payload = dict(task_run_event.get("payload") or {})
    task_run = dict(payload.get("task_run") or {})
    task_run_id = str(task_run.get("task_run_id") or "")
    stored_task = runtime.single_agent_runtime_host.state_index.get_task_run(task_run_id)

    assert branch.get("branch_kind") == "single_agent_turn"
    admissions = _admission_payloads(events)
    assert admissions
    assert dict(admissions[0].get("admission") or {}).get("decision") == "allow"
    assert dict(admissions[0].get("model_action_request") or {}).get("action_type") == "request_task_run"
    assert "runtime_invocation_packet" not in stream_types
    assert "model_action_request" not in stream_types
    task_control_opening_index = next(
        index
        for index, event in enumerate(events)
        if event.get("type") == "assistant_text"
        and event.get("answer_channel") == "task_control"
        and "页面目标转成可执行任务" in str(event.get("content") or "")
    )
    assert "task_run_lifecycle_started" in stream_types
    assert task_control_opening_index < stream_types.index("task_run_lifecycle_started")
    assert task_run_id.startswith("taskrun:")
    assert stored_task is not None
    assert dict(getattr(stored_task, "diagnostics", {}) or {}).get("origin_kind") == "single_agent_turn_native_action"
    assert any(event.get("type") == "assistant_text" and "页面目标转成可执行任务" in str(event.get("content") or "") for event in events)
    assert any(event.get("type") == "done" and "页面目标转成可执行任务" in str(event.get("content") or "") for event in events)
    assert not any(event.get("type") == "done" and "我会按这个目标推进" in str(event.get("content") or "") for event in events)


def test_single_agent_turn_json_request_task_run_starts_real_task_lifecycle() -> None:
    runtime = build_harness_runtime(
        model_runtime=_TurnActionSequenceModelRuntime(
            [
                _action_request(
                    action_type="request_task_run",
                    public_progress_note="我先把 JSON 页面目标转成持续任务，然后推进实现和验证。",
                    task_contract_seed={
                        "user_visible_goal": "交付一个 JSON 协议页面。",
                        "task_run_goal": "通过 JSON action 创建页面任务。",
                        "required_artifacts": [{"artifact_kind": "html_app", "user_visible_name": "页面"}],
                        "required_verifications": [{"verification_kind": "file_exists"}],
                        "completion_criteria": ["页面文件真实存在"],
                    },
                )
            ]
        )
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-json-taskrun",
                message="帮我做一个页面。",
                task_selection={
                    "allowed_operations": ["op.model_response"],
                    "control_capabilities": {
                        "may_request_task_run": True,
                        "requires_json_action_protocol": True,
                        "may_use_subagents": False,
                    },
                },
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    stream_types = [str(event.get("type") or "") for event in events]
    lifecycle = [event for event in events if event.get("type") == "task_run_lifecycle_started"][0]
    task_run_event = dict(lifecycle.get("event") or {})
    payload = dict(task_run_event.get("payload") or {})
    task_run = dict(payload.get("task_run") or {})
    task_run_id = str(task_run.get("task_run_id") or "")
    stored_task = runtime.single_agent_runtime_host.state_index.get_task_run(task_run_id)
    admissions = _admission_payloads(events)

    task_control_opening_index = next(
        index
        for index, event in enumerate(events)
        if event.get("type") == "assistant_text"
        and event.get("answer_channel") == "task_control"
        and "JSON 页面目标转成持续任务" in str(event.get("content") or "")
    )
    assert "task_run_lifecycle_started" in stream_types
    assert task_control_opening_index < stream_types.index("task_run_lifecycle_started")
    assert admissions
    assert dict(admissions[0].get("model_action_request") or {}).get("action_type") == "request_task_run"
    assert task_run_id.startswith("taskrun:")
    assert stored_task is not None
    assert dict(getattr(stored_task, "diagnostics", {}) or {}).get("origin_kind") == "single_agent_turn_json_action"
    messages = runtime.session_manager.load_session("session-json-taskrun")
    assert any(
        item.get("role") == "assistant"
        and item.get("content") == "我先把 JSON 页面目标转成持续任务，然后推进实现和验证。"
        for item in messages
    )
    assert any(event.get("type") == "assistant_text" and "JSON 页面目标转成持续任务" in str(event.get("content") or "") for event in events)
    assert any(event.get("type") == "done" and "JSON 页面目标转成持续任务" in str(event.get("content") or "") for event in events)
    assert not any(event.get("type") == "done" and "harness.loop.model_action_request" in str(event.get("content") or "") for event in events)
    assert not any(event.get("type") == "done" and "我会按这个目标推进" in str(event.get("content") or "") for event in events)


def test_single_agent_turn_multiple_native_control_actions_repair_to_single_control_action() -> None:
    model = _UnexpectedNativeToolCallModelRuntime(
        tool_calls=[
            {
                "id": "call-ask-user",
                "name": "ask_user",
                "args": {"question": "请补充目标平台。"},
            },
            {
                "id": "call-block",
                "name": "block",
                "args": {"reason": "当前环境缺少必要授权。"},
            },
        ],
        repair_action=_action_request(
            action_type="ask_user",
            user_question="请补充目标平台。",
            public_progress_note="需要用户补充目标平台后才能继续。",
        ),
    )
    runtime = build_harness_runtime(model_runtime=model)

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(HarnessRuntimeRequest(session_id="session-multiple-native-actions", message="帮我做适配。")):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    admissions = _admission_payloads(events)

    assert len(admissions) == 1
    assert dict(admissions[0].get("admission") or {}).get("decision") == "allow"
    admitted_action = dict(admissions[0].get("model_action_request") or {})
    assert admitted_action.get("action_type") == "ask_user"
    assert dict(admitted_action.get("diagnostics") or {}).get("protocol_repair", {}).get("original_error_code") == "single_agent_turn_multiple_native_actions"
    assert not any(dict(payload.get("model_action_request") or {}).get("action_type") == "block" for payload in admissions)
    assert any(event.get("type") == "done" and "请补充目标平台" in str(event.get("content") or "") for event in events)


def test_single_agent_turn_multiple_native_control_actions_do_not_execute_original_when_repair_fails() -> None:
    model = _UnexpectedNativeToolCallModelRuntime(
        tool_calls=[
            {
                "id": "call-ask-user",
                "name": "ask_user",
                "args": {"question": "请补充目标平台。"},
            },
            {
                "id": "call-block",
                "name": "block",
                "args": {"reason": "当前环境缺少必要授权。"},
            },
        ]
    )
    runtime = build_harness_runtime(model_runtime=model)

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(HarnessRuntimeRequest(session_id="session-multiple-native-actions-repair-fails", message="帮我做适配。")):
            events.append(event)
        return events

    events = asyncio.run(_collect())

    assert not _admission_payloads(events)
    assert not any(event.get("type") == "done" and "当前环境缺少必要授权" in str(event.get("content") or "") for event in events)
    assert any(
        event.get("type") == "agent_turn_terminal"
        and dict(dict(event.get("event") or {}).get("payload") or {}).get("terminal_reason") == "single_agent_turn_protocol_repair_failed"
        for event in events
    )


def test_single_agent_turn_json_ask_user_goes_through_admission() -> None:
    model = _TurnActionSequenceModelRuntime(
        [
            _action_request(
                action_type="ask_user",
                user_question="请补充目标平台。",
                public_progress_note="需要用户补充目标平台后才能继续。",
            )
        ]
    )
    runtime = build_harness_runtime(model_runtime=model)

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(HarnessRuntimeRequest(session_id="session-native-ask", message="帮我做适配。")):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    admissions = _admission_payloads(events)

    assert admissions
    assert dict(admissions[0].get("admission") or {}).get("decision") == "allow"
    assert dict(admissions[0].get("model_action_request") or {}).get("action_type") == "ask_user"
    assert any(event.get("type") == "done" and "请补充目标平台" in str(event.get("content") or "") for event in events)


def test_single_agent_turn_json_block_goes_through_admission() -> None:
    model = _TurnActionSequenceModelRuntime(
        [
            _action_request(
                action_type="block",
                blocking_reason="当前环境缺少必要授权。",
                public_progress_note="当前请求无法继续执行。",
            )
        ]
    )
    runtime = build_harness_runtime(model_runtime=model)

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(HarnessRuntimeRequest(session_id="session-native-block", message="执行受限操作。")):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    admissions = _admission_payloads(events)

    assert admissions
    assert dict(admissions[0].get("admission") or {}).get("decision") == "allow"
    assert dict(admissions[0].get("model_action_request") or {}).get("action_type") == "block"
    assert any(event.get("type") == "done" and "当前环境缺少必要授权" in str(event.get("content") or "") for event in events)


def test_default_runtime_policy_uses_main_profile_for_standard_chat() -> None:
    runtime = build_harness_runtime()

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-standard-chat",
                message="普通对话。",
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    assembly = dict(next(event for event in events if event.get("type") == "runtime_assembly_compiled").get("runtime_assembly") or {})

    assert dict(assembly.get("profile") or {}).get("profile_ref") == "main_interactive_agent"


def test_default_runtime_policy_exposes_plan_policy() -> None:
    runtime = build_harness_runtime()

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-default-policy",
                message="执行需要真实产物的任务。",
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


def test_runtime_policy_can_override_default_runtime_assembly() -> None:
    runtime = build_harness_runtime()

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
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
    runtime = build_harness_runtime()

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-custom-mode-policy",
                message="按显式运行策略执行。",
                task_selection={"task_environment_id": "env.development.sandbox"},
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
    assert dict(assembly.get("task_environment") or {}).get("environment_id") == "env.development.sandbox"


def test_turn_packet_does_not_expose_legacy_task_goal_type_from_selection() -> None:
    class CaptureModelRuntime:
        def __init__(self) -> None:
            self.messages: list[object] = []

        async def invoke_messages(self, messages, **_kwargs):
            self.messages = list(messages)
            return SimpleNamespace(content=json.dumps(_action_request(action_type="respond", final_answer="ok")))

    model = CaptureModelRuntime()
    runtime = build_harness_runtime(model_runtime=model)

    async def _collect() -> None:
        async for _event in runtime.astream(
            HarnessRuntimeRequest(
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

    runtime = build_harness_runtime(model_runtime=AccountingModelRuntime())

    async def _collect() -> None:
        async for _event in runtime.astream(HarnessRuntimeRequest(session_id="session-accounting", message="hello")):
            pass

    asyncio.run(_collect())
    turn_run_id = runtime.single_agent_runtime_host.list_session_traces("session-accounting")["turn_runs"][0]["turn_run_id"]
    summary = runtime.single_agent_runtime_host.prompt_accounting_ledger.summarize_run(turn_run_id)

    assert summary["exact_total_tokens"] == 15
    assert summary["provider_usage_record_count"] == 1
    assert summary["local_prediction_record_count"] == 1


def test_required_artifact_completion_requires_existing_file() -> None:
    from harness.loop.task_executor import _verify_completion

    runtime = build_harness_runtime()
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

    runtime = build_harness_runtime()
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

    runtime = build_harness_runtime()
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

    runtime = build_harness_runtime()
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

    runtime = build_harness_runtime()
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


def test_task_model_action_request_rejects_action_outside_packet_contract() -> None:
    from harness.loop.model_action_protocol import model_action_request_from_payload

    action, diagnostics = model_action_request_from_payload(
        {
            "authority": "harness.loop.model_action_request",
            "request_id": "model-action:test:not-allowed",
            "turn_id": "taskrun:test:not-allowed",
            "action_type": "request_task_run",
            "public_progress_note": "准备重新开任务。",
            "public_action_state": {
                "current_judgment": "当前任务需要重新建任务。",
                "next_action": "请求新的任务运行。",
            },
            "task_contract_seed": {"user_visible_goal": "不应被允许。"},
        },
        turn_id="taskrun:test:not-allowed",
        require_public_progress_note=True,
        require_public_action_state=True,
        allowed_action_types=("respond", "ask_user", "tool_call", "block"),
    )

    assert action is None
    assert diagnostics["status"] == "invalid"
    assert "action_type_not_allowed_for_context:request_task_run" in diagnostics["validation_errors"]


def test_task_execution_action_request_omits_empty_cross_context_fields() -> None:
    from harness.loop.model_action_protocol import task_execution_action_request_from_payload

    action, diagnostics = task_execution_action_request_from_payload(
        {
            "authority": "harness.loop.model_action_request",
            "request_id": "model-action:test:task-tool",
            "turn_id": "taskrun:test:task-tool",
            "action_type": "tool_call",
            "public_progress_note": "准备读取文件。",
            "public_action_state": {
                "current_judgment": "需要读取文件确认状态。",
                "next_action": "调用 read_file。",
            },
            "tool_call": {"tool_name": "read_file", "args": {"path": "README.md"}},
            "selected_skill_ids": [],
            "task_contract_seed": {},
            "completion_contract": {},
            "permission_request": {},
            "engagement_request": {},
            "active_work_control": {},
        },
        turn_id="taskrun:test:task-tool",
        allowed_action_types=("respond", "ask_user", "tool_call", "block"),
    )

    assert diagnostics["status"] == "accepted"
    assert action is not None
    payload = action.to_dict()
    assert payload["action_type"] == "tool_call"
    assert "task_contract_seed" not in payload
    assert "completion_contract" not in payload
    assert "permission_request" not in payload
    assert "engagement_request" not in payload
    assert "active_work_control" not in payload
    assert "selected_skill_ids" not in payload


def test_task_execution_action_request_rejects_non_empty_cross_context_fields() -> None:
    from harness.loop.model_action_protocol import task_execution_action_request_from_payload

    action, diagnostics = task_execution_action_request_from_payload(
        {
            "authority": "harness.loop.model_action_request",
            "request_id": "model-action:test:task-cross-context",
            "turn_id": "taskrun:test:task-cross-context",
            "action_type": "tool_call",
            "public_progress_note": "准备读取文件。",
            "public_action_state": {
                "current_judgment": "需要读取文件确认状态。",
                "next_action": "调用 read_file。",
            },
            "tool_call": {"tool_name": "read_file", "args": {"path": "README.md"}},
            "task_contract_seed": {"user_visible_goal": "不应出现在 task_execution。"},
        },
        turn_id="taskrun:test:task-cross-context",
        allowed_action_types=("respond", "ask_user", "tool_call", "block"),
    )

    assert action is None
    assert diagnostics["status"] == "invalid"
    assert "field_not_allowed_for_task_execution:task_contract_seed" in diagnostics["validation_errors"]


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

    assert summary == "读取文件：index.html。"
    assert "我看到缺少入口文件" not in summary


def test_public_runtime_progress_preserves_user_level_task_wording() -> None:
    from harness.runtime.public_progress import public_runtime_progress_summary

    assert public_runtime_progress_summary("不需要开启正式任务。") == "不需要开启正式任务。"
    assert public_runtime_progress_summary("正式任务生命周期已完成。") == "正式任务生命周期已完成。"


def test_task_sandbox_workspace_root_is_project_root() -> None:
    from harness.loop.task_executor import _task_sandbox_policy

    runtime = build_harness_runtime()
    project_root = Path(runtime.base_dir).resolve().parent
    policy = _task_sandbox_policy(
        {"task_environment": {"storage_space": {}, "sandbox_policy": {}}},
        runtime_host=runtime.single_agent_runtime_host,
        task_run_id="taskrun:test:workspace-root",
    )

    assert Path(str(policy["workspace_root"])).resolve() == project_root


def test_task_sandbox_grants_environment_scratch_without_publishing_it() -> None:
    from harness.loop.task_executor import _task_sandbox_policy, _verify_completion

    runtime = build_harness_runtime()
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
    runtime = build_harness_runtime()
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
    runtime = build_harness_runtime()
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


def test_artifact_view_prefers_published_path_over_sandbox_absolute_path() -> None:
    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    project_root = Path(runtime.base_dir).resolve().parent
    logical_path = "storage/task_environments/general/workspace/artifacts/calculator.html"
    published_artifact = project_root / logical_path
    published_artifact.parent.mkdir(parents=True, exist_ok=True)
    published_artifact.write_text("<!doctype html><title>published</title>", encoding="utf-8")
    sandbox_artifact = (
        project_root
        / "storage/runtime_state/sandboxes/taskrun_test_calculator/storage/task_environments/general/workspace/artifacts/calculator.html"
    )
    sandbox_artifact.parent.mkdir(parents=True, exist_ok=True)
    sandbox_artifact.write_text("<!doctype html><title>sandbox</title>", encoding="utf-8")
    task_run_id = "taskrun:test:calculator-artifact-index"
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id=task_run_id,
            session_id="session-calculator-artifact-index",
            task_id="task:calculator-artifact-index",
            status="running",
            created_at=100.0,
            updated_at=110.0,
            execution_runtime_kind="single_agent_task",
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
                                "path": logical_path,
                                "absolute_path": str(sandbox_artifact),
                                "sandbox_path": logical_path,
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

    assert view["created_files"] == [logical_path]
    assert view["artifact_refs"][0]["absolute_path"] == str(published_artifact.resolve())
    assert Path(view["artifact_refs"][0]["absolute_path"]).read_text(encoding="utf-8") == "<!doctype html><title>published</title>"


def test_task_observation_projection_separates_stale_and_active_failures() -> None:
    from harness.loop.task_executor import _observations_for_packet

    runtime = build_harness_runtime()
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

    runtime = build_harness_runtime()
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

    runtime = build_harness_runtime()
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


def test_task_observation_projection_does_not_classify_historical_success_as_failure() -> None:
    from harness.loop.task_executor import _observations_for_packet

    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    task_run_id = "taskrun:test:historical-success"
    host.event_log.append(
        task_run_id,
        "task_tool_observation_recorded",
        payload={
            "observation": {
                "observation_id": "obs:todo-init",
                "task_run_id": task_run_id,
                "observation_type": "tool_result",
                "source": "system:agent_todo",
                "payload": {
                    "tool_name": "system",
                    "result": json.dumps({"status": "ok", "items": []}),
                },
            }
        },
    )

    context = _observations_for_packet(host, task_run_id, current_fingerprint={"tool_config_hash": "current"})
    projection = context["execution_state"]["system_projection"]

    assert projection["active_failures"] == []
    assert projection["historical_failures"] == []
    assert projection["last_action_receipts"][0]["status"] == "ok"
    assert projection["last_action_receipts"][0]["visibility"] == "historical"


def test_task_observation_projection_marks_superseded_success_as_historical() -> None:
    from harness.loop.task_executor import _observations_for_packet

    runtime = build_harness_runtime()
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

    runtime = build_harness_runtime()
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
                        "artifact_refs": [{"path": "frontend/public/generated/images/hero.png", "kind": "image"}],
                        "structured_payload": {
                            "artifact_refs": [{"path": "frontend/public/generated/images/hero.png", "kind": "image"}]
                        },
                    },
                },
            }
        },
    )

    context = _observations_for_packet(host, task_run_id, current_fingerprint=fingerprint)
    projection = context["execution_state"]["system_projection"]

    assert projection["current_facts"][0]["tool_name"] == "image_generate"
    assert projection["artifact_evidence"][0]["path"] == "frontend/public/generated/images/hero.png"
    assert context["artifact_refs"][0]["kind"] == "image"


def test_task_observation_projection_ignores_already_projected_records() -> None:
    from harness.loop.task_executor import _observations_for_packet

    runtime = build_harness_runtime()
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

