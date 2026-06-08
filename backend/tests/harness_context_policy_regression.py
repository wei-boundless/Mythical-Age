from __future__ import annotations

from tests.support.harness_runtime_facade_support import *
import harness.entrypoint.runtime_facade as runtime_facade_module


class _BlockedRuntimeAssembly:
    def to_dict(self) -> dict[str, object]:
        return {
            "status": "blocked",
            "diagnostics": {"blocked_runtime": True},
            "control_capabilities": {},
        }


def test_blocked_runtime_commits_visible_fail_closed_message(monkeypatch) -> None:
    runtime = build_harness_runtime(
        model_runtime=SingleMessageModelRuntimeStub(content="不应调用模型。")
    )
    monkeypatch.setattr(
        runtime_facade_module,
        "assemble_runtime",
        lambda **_kwargs: _BlockedRuntimeAssembly(),
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-blocked-runtime",
                message="测试被阻断的运行时。",
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    messages = runtime.session_manager.load_session("session-blocked-runtime")
    api_messages = runtime.session_manager.load_session_for_api("session-blocked-runtime")

    assert any(event.get("type") == "error" and event.get("code") == "blocked_runtime" for event in events)
    assert messages[-1]["role"] == "assistant"
    assert messages[-1]["turn_id"] == "turn:session-blocked-runtime:1"
    assert "当前运行环境未能完成装配" in messages[-1]["content"]
    assert api_messages[-1]["role"] == "assistant"
    assert api_messages[-1]["turn_id"] == "turn:session-blocked-runtime:1"
    assert runtime.single_agent_runtime_host.active_turn_registry.snapshot("session-blocked-runtime") is None

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
                runtime_contract={
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
                runtime_contract={
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

def test_single_agent_turn_auto_compacts_session_before_model_turn(tmp_path: Path) -> None:
    class RecordingModelRuntime(SingleMessageModelRuntimeStub):
        def __init__(self) -> None:
            super().__init__(content="继续完成。")
            self.last_messages: list[dict[str, object]] = []

        async def invoke_messages(self, messages, **kwargs):
            self.last_messages = [dict(item) for item in list(messages or []) if isinstance(item, dict)]
            return await super().invoke_messages(messages, **kwargs)

    runtime_root = _runtime_test_root(tmp_path)
    session_manager = SessionManager(runtime_root)
    session = session_manager.create_session(title="Auto compact")
    session_id = str(session["id"])
    old_context = "旧的大段过程性上下文，应被自动压缩替换，不应继续进入模型原始历史。 " * 160
    messages = [{"role": "user", "content": "历史起点"}, {"role": "assistant", "content": old_context}]
    for index in range(10):
        messages.append({"role": "user" if index % 2 == 0 else "assistant", "content": f"最近短消息 {index}"})
    session_manager.append_messages(session_id, messages)

    model = RecordingModelRuntime()
    runtime = build_harness_runtime(
        base_dir=runtime_root,
        session_manager=session_manager,
        memory_facade=MemoryFacade(runtime_root),
        model_runtime=model,
    )
    runtime.single_agent_runtime_host.prompt_accounting_ledger.record_token_usage(
        ModelTokenUsageRecord(
            usage_id="usage:auto-compact",
            request_id="request:auto-compact",
            session_id=session_id,
            provider="local",
            model="auto-compact-test",
            source="provider_usage",
            prompt_tokens=125_000,
            total_tokens=125_000,
            created_at=1.0,
        )
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id=session_id,
                message="继续。",
                runtime_contract={
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
    record = session_manager.get_history(session_id)
    payload = "\n".join(str(message.get("content") or "") for message in model.last_messages)

    assert any(event.get("type") == "done" for event in events)
    assert "Conversation history was compacted into a checkpoint" in record["compressed_context"]
    assert old_context not in [str(item.get("content") or "") for item in record["messages"]]
    assert old_context not in payload
    assert "Conversation history was compacted into a checkpoint" in payload
    assert session_manager.load_session_for_api(session_id)[1]["content"] == old_context

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
                runtime_contract={
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
                runtime_contract={
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
                runtime_contract={
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
