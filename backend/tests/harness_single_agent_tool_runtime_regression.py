from __future__ import annotations

from tests.support.harness_runtime_facade_support import *

def test_native_tool_call_action_keeps_agent_text_out_of_tool_projection() -> None:
    from harness.loop.single_agent_turn import _tool_action_request_from_native_tool_calls

    request = _tool_action_request_from_native_tool_calls(
        [
            {
                "id": "call-search-animation-loop",
                "name": "search_text",
                "args": {"query": "requestAnimationFrame"},
            }
        ],
        turn_id="turn:public-native-intent:1",
        packet_ref="packet:public-native-intent",
        iteration=1,
    )

    assert request is not None
    assert request.action_type == "tool_call"
    assert request.public_progress_note == ""
    assert request.public_action_state == {"completion_status": "waiting_for_tool"}
    assert request.tool_call == {
        "tool_name": "search_text",
        "name": "search_text",
        "id": "call-search-animation-loop",
        "args": {"query": "requestAnimationFrame"},
    }

def test_single_agent_turn_projection_requires_json_action_and_hides_native_control_transport(tmp_path: Path) -> None:
    class RecordingTurnModelRuntime:
        def __init__(self) -> None:
            self.last_messages: list[dict[str, object]] = []
            self.seen_tool_call_options: list[object] = []

        async def invoke_messages_with_tools(self, messages, tools, **kwargs):
            del tools
            return await self.invoke_messages(messages, **kwargs)

        async def invoke_messages(self, messages, **kwargs):
            self.last_messages = [dict(item) for item in list(messages or []) if isinstance(item, dict)]
            self.seen_tool_call_options.append(kwargs.get("tool_call_options"))
            return SimpleNamespace(
                content=json.dumps(
                    _action_request(action_type="respond", final_answer="直接回答。"),
                    ensure_ascii=False,
                )
            )

    model = RecordingTurnModelRuntime()
    tool_base_dir = _project_backend_dir()
    runtime = build_harness_runtime(
        base_dir=_runtime_test_root(tmp_path),
        model_runtime=model,
        tool_runtime=_tool_runtime_for_names(
            tool_base_dir,
            {
                "read_file",
                "search_text",
                "stat_path",
                "path_exists",
                "write_file",
                "edit_file",
                "terminal",
                "python_repl",
                "git_status",
                "git_commit",
            },
        ),
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(HarnessRuntimeRequest(session_id="session-native-boundary", message="介绍一下项目。")):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    assembly = dict(next(event for event in events if event.get("type") == "runtime_assembly_compiled").get("runtime_assembly") or {})
    start = dict(next(event for event in events if event.get("type") == "single_agent_turn_started"))
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
    assert set(start.get("allowed_action_types") or []) == {"respond", "ask_user", "block", "request_task_run", "tool_call"}
    assert effective_capabilities.get("may_call_tools") is True
    assert effective_capabilities.get("may_use_subagents") is False
    assert effective_capabilities.get("supports_json_action_protocol") is True
    assert effective_capabilities.get("requires_json_action_protocol") is True
    assert ordinary_tool_contract.get("multi_tool_calls_allowed") is True
    assert ordinary_tool_contract.get("runtime_execution_policy") == "tool_batch_plan_scheduled_by_safety_and_resource_locks"
    assert "parallel_allowed" not in ordinary_tool_contract
    assert native_tool_contract.get("enabled") is True
    assert native_tool_contract.get("provider_multi_tool_calls_allowed") is True
    assert native_tool_contract.get("runtime_execution_policy") == "tool_batch_plan_scheduled_by_safety_and_resource_locks"
    assert dict(action_protocol.get("control_actions") or {}).get("native_tool_transport_enabled") is False
    assert "single_action_per_turn" not in json.dumps(output_contract, ensure_ascii=False)
    assert getattr(model.seen_tool_call_options[0], "parallel_tool_calls", None) is True

def test_single_agent_turn_read_only_tool_executes_through_control_plane_and_followup_answers(tmp_path: Path) -> None:
    from runtime.memory.file_evidence_scope import session_file_evidence_scope

    model = NativeToolCallSequenceModelRuntimeStub(
        [
            {
                "content": "我先读取 requirements.txt，再回答依赖状态。",
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
                "content": json.dumps(
                    _action_request(action_type="respond", final_answer="已经读取 requirements.txt。"),
                    ensure_ascii=False,
                ),
                "additional_kwargs": {"reasoning_content": "The file result is enough to answer."},
            },
            {
                "content": json.dumps(
                    _action_request(action_type="respond", final_answer="第二轮继续回答。"),
                    ensure_ascii=False,
                )
            },
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
    assert runtime.single_agent_runtime_host.list_session_traces("session-single-turn-read-tool")["task_run_count"] == 0
    scope = session_file_evidence_scope("session-single-turn-read-tool")
    file_state = runtime.single_agent_runtime_host.file_state_store.snapshot_scope(scope)
    assert file_state[0]["path"] == "requirements.txt"
    assert file_state[0]["read_ranges"][0]["observation_ref"].startswith("toolobs:")

    async def _collect_second_turn() -> None:
        async for _event in runtime.astream(HarnessRuntimeRequest(session_id="session-single-turn-read-tool", message="继续说明。")):
            pass

    asyncio.run(_collect_second_turn())
    second_turn_messages = [dict(item) for item in list(model.seen_messages[-1] or []) if isinstance(item, dict)]
    replayed_tool_call = next(item for item in second_turn_messages if item.get("role") == "assistant" and item.get("tool_calls"))
    replayed_tool_result = next(item for item in second_turn_messages if item.get("role") == "tool")

    assert dict(list(replayed_tool_call["tool_calls"])[0]).get("id") == "call-read-requirements"
    assert replayed_tool_result["tool_call_id"] == "call-read-requirements"
    dynamic_marker = "Single agent turn dynamic runtime\n"
    dynamic_content = next(str(item.get("content") or "") for item in second_turn_messages if dynamic_marker in str(item.get("content") or ""))
    second_dynamic_payload = json.loads(dynamic_content[dynamic_content.index(dynamic_marker) + len(dynamic_marker):])
    assert second_dynamic_payload["file_evidence_scope"] == scope
    assert second_dynamic_payload["file_evidence_decisions"]["files"][0]["path"] == "requirements.txt"
    assert "do_not_repeat_read_ranges" not in second_dynamic_payload["read_resource_state"]
    evidence_marker = "Task current exact read evidence\n"
    evidence_content = next(str(item.get("content") or "") for item in second_turn_messages if evidence_marker in str(item.get("content") or ""))
    evidence_payload = json.loads(evidence_content[evidence_content.index(evidence_marker) + len(evidence_marker):])
    assert evidence_payload["read_evidence_injections"][0]["path"] == "requirements.txt"
    assert evidence_payload["read_evidence_injections"][0]["visible_exact_in_packet"] is True

def test_single_agent_turn_stream_policy_does_not_emit_json_action_delta(tmp_path: Path) -> None:
    action = json.dumps(
        _action_request(
            action_type="respond",
            final_answer="流式安全收口。",
        ),
        ensure_ascii=False,
    )
    model = StreamingMessageModelRuntimeStub(chunks=[action[:24], action[24:]])
    runtime = build_harness_runtime(
        base_dir=_runtime_test_root(tmp_path),
        model_runtime=model,
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-single-turn-stream-json",
                message="直接回答。",
                model_selection={
                    "stream_policy": {
                        "enabled": True,
                        "emit_assistant_text_delta": True,
                    }
                },
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())

    assert [event for event in events if event.get("type") == "assistant_text_delta"] == []

def test_single_agent_turn_mid_turn_context_replacement_persists_recovery_package_and_recompiles_followup(tmp_path: Path) -> None:
    runtime_root = _runtime_test_root(tmp_path)
    session_manager = SessionManager(runtime_root)
    session = session_manager.create_session(title="Mid turn context replacement")
    session_id = str(session["id"])
    old_messages: list[dict[str, object]] = []
    for index in range(12):
        role = "user" if index % 2 == 0 else "assistant"
        content = f"历史消息 {index}: 压缩系统背景 " + ("背景 " * 30)
        if index == 1:
            content = "VERY_OLD_RAW_PAYLOAD_SENTINEL " + ("旧工具原文 " * 380)
        old_messages.append(
            {
                "role": role,
                "content": content,
                "message_id": f"msg:old:{index}",
            }
        )
    session_manager.append_messages(session_id, old_messages)
    memory_facade = MemoryFacade(
        runtime_root,
        context_budget_provider=lambda: {
            "available_context_tokens": 220,
            "compaction_threshold_tokens": {"warning": 120, "ready": 160, "replacement": 200},
        },
    )
    session_summary = "\n".join(
        [
            "# Active Goal",
            "- 升级上下文压缩恢复系统",
            "",
            "# Key User Requests",
            "- 摘要必须服务下一轮上下文恢复，不能只是展示文本",
            "",
            "# Files and Functions",
            "- backend/harness/loop/single_agent_turn.py",
            "- backend/harness/entrypoint/runtime_facade.py",
            "",
            "# Next Step",
            "- 工具观察后如达到阈值，先压缩 session，再重新编译 follow-up 包",
        ]
    )
    manager = memory_facade.session_memory.manager(session_id)
    manager.overwrite(session_summary)
    manager.write_compaction_state(
        messages=list(session_manager.get_history(session_id)["messages"]),
        run_id="memory-maintenance:mid-turn-context-replacement",
        source="agent:1",
        summary_content=session_summary,
        covered_event_run_id="turnrun:previous",
        covered_event_offset_start=0,
        covered_event_offset_end=12,
    )
    model = NativeToolCallSequenceModelRuntimeStub(
        [
            {
                "content": "我先读取依赖文件，确认恢复后的上下文没有丢。",
                "tool_calls": [
                    {
                        "id": "call-read-requirements",
                        "name": "read_file",
                        "args": {"path": "requirements.txt", "line_count": 20},
                    }
                ]
            },
            {
                "content": json.dumps(
                    _action_request(action_type="respond", final_answer="已经基于恢复包和工具结果继续。"),
                    ensure_ascii=False,
                )
            },
        ]
    )
    runtime = build_harness_runtime(
        base_dir=runtime_root,
        session_manager=session_manager,
        memory_facade=memory_facade,
        model_runtime=model,
        tool_runtime=_tool_runtime_for_names(_project_backend_dir(), {"read_file"}),
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id=session_id,
                message="当前用户要求不能丢，请先看依赖文件。",
                model_selection={
                    "context_window_tokens": 1200,
                    "reserved_output_tokens": 0,
                },
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    compacted_event = next(event for event in events if event.get("type") == "context_compacted")
    compacted_payload = dict(dict(compacted_event.get("event") or {}).get("payload") or {})
    record = session_manager.get_history(session_id)
    followup_messages = [dict(item) for item in list(model.seen_messages[-1] or []) if isinstance(item, dict)]
    followup_text = "\n".join(str(item.get("content") or "") for item in followup_messages)
    followup_history_payload = _packet_payload_after_title(
        next(
            str(item.get("content") or "")
            for item in followup_messages
            if "Observation followup session history" in str(item.get("content") or "")
        ),
        "Observation followup session history",
    )
    followup_active_history = [
        dict(item)
        for item in list(followup_history_payload.get("active_history") or [])
        if isinstance(item, dict)
    ]

    assert compacted_payload["applied"] is True
    assert compacted_payload["strategy"] == "full_compact"
    assert compacted_payload["context_recovery_package_present"] is True
    assert compacted_payload["context_recovery_package_source"] == "agent:1"
    assert record["provider_protocol_compaction_created_at"] > 0
    assert len(record["messages"]) < len(old_messages) + 2

def test_single_agent_turn_batches_multiple_read_only_tools_before_followup_answers(tmp_path: Path) -> None:
    model = NativeToolCallSequenceModelRuntimeStub(
        [
            {
                "content": "我先并行检查依赖文件和路径存在性。",
                "tool_calls": [
                    {"id": "call-read-requirements", "name": "read_file", "args": {"path": "requirements.txt", "line_count": 20}},
                    {"id": "call-path-exists", "name": "path_exists", "args": {"path": "requirements.txt"}},
                ]
            },
            {
                "content": json.dumps(
                    _action_request(action_type="respond", final_answer="已经完成两个检查。"),
                    ensure_ascii=False,
                )
            },
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
    assert [dict(item).get("action_type") for item in admitted_actions] == ["tool_call", "tool_call", "respond"]
    assert len(list(assistant_tool_message["tool_calls"])) == 2
    assert [item["tool_call_id"] for item in tool_messages] == ["call-read-requirements", "call-path-exists"]

def test_single_agent_turn_tool_loop_hands_budget_closeout_to_agent_without_ninth_tool_call(tmp_path: Path) -> None:
    class SynthesizingLoopModel(NativeToolCallSequenceModelRuntimeStub):
        def __init__(self) -> None:
            super().__init__(
                [
                    {
                        **({"content": "我先检查文件是否存在，再判断是否需要继续。"} if index == 1 else {}),
                        "tool_calls": [
                            {"id": f"call-exists-{index}", "name": "path_exists", "args": {"path": "requirements.txt"}},
                        ]
                    }
                    for index in range(1, 10)
                ]
            )
            self.closeout_messages: list[dict[str, object]] = []
            self.closeout_accounting: dict[str, object] = {}

        async def invoke_messages(self, messages, **_kwargs):
            self.closeout_messages = [dict(item) for item in list(messages or []) if isinstance(item, dict)]
            self.closeout_accounting = dict(_kwargs.get("accounting_context") or {})
            return SimpleNamespace(
                content=json.dumps(
                    _action_request(
                        action_type="respond",
                        final_answer="agent closeout final",
                    ),
                    ensure_ascii=False,
                )
            )

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
    done = next(event for event in events if event.get("type") == "done")

    assert model.calls == 9
    assert len(observations) == 8
    assert done["terminal_reason"] == "single_turn_tool_iteration_limit"
    assert done["answer_source"] == "harness.single_agent_turn.tool_limit_closeout"
    assert done["completion_state"] == "tool_limit_agent_responded"
    assert done["content"] == "agent closeout final"
    assert any(event.get("type") == "turn_runtime_control_signal_observed" for event in events)
    assert model.closeout_accounting["source"] == "harness.single_agent_turn.tool_limit_closeout"
    assert model.closeout_accounting["prompt_manifest"]["invocation_kind"] == "single_agent_turn_tool_limit_closeout"
    assert model.closeout_accounting["prompt_manifest"]["allowed_action_types"] == ["respond", "ask_user", "block"]
    assert model.closeout_messages[-1]["role"] == "system"
    closeout_content = str(model.closeout_messages[-1].get("content") or "")
    assert "runtime_control_signal" in closeout_content
    assert '"allowed_action_types": ["respond", "ask_user", "block"]' in closeout_content
    assert '"tool_call_allowed": false' in closeout_content
    assert '"tool_calls_allowed_after_signal": false' in closeout_content
    assert "你现在是本轮收口负责人" in closeout_content
    assert not any("single_turn_tool_budget_exhausted" in str(item.get("content") or "") for item in runtime.session_manager.messages)


def test_single_agent_turn_two_consecutive_tool_failures_closeout_to_agent(tmp_path: Path) -> None:
    class FailingLoopModel(NativeToolCallSequenceModelRuntimeStub):
        def __init__(self) -> None:
            super().__init__(
                [
                    {
                        "content": "我先读取不存在的文件确认状态。",
                        "tool_calls": [
                            {"id": "call-read-1", "name": "read_file", "args": {"path": "does-not-exist-1.txt"}},
                        ],
                    },
                    {
                        "content": "我再确认一次读取状态。",
                        "tool_calls": [
                            {"id": "call-read-2", "name": "read_file", "args": {"path": "does-not-exist-2.txt"}},
                        ],
                    },
                ]
            )
            self.closeout_messages: list[dict[str, object]] = []
            self.closeout_accounting: dict[str, object] = {}

        async def invoke_messages(self, messages, **_kwargs):
            if self.calls >= 2:
                self.calls += 1
                self.seen_tools.append(list(_kwargs.get("tools") or []))
                self.seen_messages.append(list(messages or []))
                self.seen_accounting_contexts.append(dict(_kwargs.get("accounting_context") or {}))
                self.seen_tool_call_options.append(_kwargs.get("tool_call_options"))
                self.closeout_messages = [dict(item) for item in list(messages or []) if isinstance(item, dict)]
                self.closeout_accounting = dict(_kwargs.get("accounting_context") or {})
                return SimpleNamespace(
                    content=json.dumps(
                        _action_request(action_type="respond", final_answer="这两个文件都不存在，先停止继续读文件。"),
                        ensure_ascii=False,
                    )
                )
            self.closeout_messages = [dict(item) for item in list(messages or []) if isinstance(item, dict)]
            self.closeout_accounting = dict(_kwargs.get("accounting_context") or {})
            return await super().invoke_messages(messages, **_kwargs)

    model = FailingLoopModel()
    tool_base_dir = _project_backend_dir()
    runtime = build_harness_runtime(
        base_dir=_runtime_test_root(tmp_path),
        model_runtime=model,
        tool_runtime=_tool_runtime_for_names(tool_base_dir, {"read_file"}),
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(HarnessRuntimeRequest(session_id="session-single-turn-consecutive-failure", message="连续检查两个文件。")):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    observations = [dict(event.get("tool_observation") or {}) for event in events if event.get("type") == "tool_observation"]
    control_signal = next(event for event in events if event.get("type") == "turn_runtime_control_signal_observed")
    done = next(event for event in events if event.get("type") == "done")
    assistant_messages = [dict(item) for item in runtime.session_manager.messages if str(dict(item).get("role") or "") == "assistant"]

    assert model.calls == 3
    assert len(observations) == 2
    assert all(item["status"] == "error" for item in observations)
    control_payload = dict(dict(control_signal.get("event") or {}).get("payload") or {})
    assert dict(control_payload.get("runtime_control_signal") or {}).get("signal_kind") == "consecutive_tool_failures"
    assert done["terminal_reason"] == "single_turn_consecutive_tool_failures"
    assert done["answer_source"] == "harness.single_agent_turn.agent_closeout"
    assert done["content"] == "这两个文件都不存在，先停止继续读文件。"
    assert assistant_messages[-1]["content"] == "这两个文件都不存在，先停止继续读文件。"
    assert model.closeout_accounting["source"] == "harness.single_agent_turn.agent_closeout"
    assert model.closeout_accounting["prompt_manifest"]["invocation_kind"] == "single_agent_turn_agent_authored_closeout"
