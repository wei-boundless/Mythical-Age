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
    assert getattr(model.seen_tool_call_options[0], "parallel_tool_calls", None) is False

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
    assert runtime.single_agent_runtime_host.list_session_traces("session-single-turn-read-tool")["task_run_count"] == 0

    async def _collect_second_turn() -> None:
        async for _event in runtime.astream(HarnessRuntimeRequest(session_id="session-single-turn-read-tool", message="继续说明。")):
            pass

    asyncio.run(_collect_second_turn())
    second_turn_messages = [dict(item) for item in list(model.seen_messages[-1] or []) if isinstance(item, dict)]
    replayed_tool_call = next(item for item in second_turn_messages if item.get("role") == "assistant" and item.get("tool_calls"))
    replayed_tool_result = next(item for item in second_turn_messages if item.get("role") == "tool")

    assert dict(list(replayed_tool_call["tool_calls"])[0]).get("id") == "call-read-requirements"
    assert replayed_tool_result["tool_call_id"] == "call-read-requirements"

def test_single_agent_turn_stream_policy_emits_assistant_text_frame_before_done(tmp_path: Path) -> None:
    model = StreamingMessageModelRuntimeStub(chunks=["第一段", "，第二段。"])
    runtime = build_harness_runtime(
        base_dir=_runtime_test_root(tmp_path),
        model_runtime=model,
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-single-turn-stream",
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
    deltas = [str(event.get("content") or "") for event in events if event.get("type") == "assistant_text_delta"]
    final = next(event for event in events if event.get("type") == "assistant_text_final")
    done = next(event for event in events if event.get("type") == "done")

    event_types = [event.get("type") for event in events]
    assert event_types.index("assistant_text_delta") < event_types.index("assistant_text_final") < event_types.index("done")

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
                "tool_calls": [
                    {
                        "id": "call-read-requirements",
                        "name": "read_file",
                        "args": {"path": "requirements.txt", "line_count": 20},
                    }
                ]
            },
            {"content": "已经基于恢复包和工具结果继续。"},
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
                runtime_contract={"task_environment_id": "env.coding.vibe_workspace"},
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
    assert not any(
        event.get("type") == "done" and dict(event).get("terminal_reason") == "tool_denied"
        for event in events
    )

def test_single_agent_turn_publishes_environment_artifact_write_before_reporting_success(tmp_path: Path) -> None:
    session_id = "session-single-turn-artifact-publish"
    artifact_path = _session_artifact_path(session_id, "coding/vibe-workspace", "single_turn_artifact.html")
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
    runtime_root = _runtime_test_root(tmp_path)
    runtime = build_harness_runtime(
        base_dir=runtime_root,
        model_runtime=model,
        tool_runtime=_tool_runtime_for_names(runtime_root, {"write_file", "path_exists"}),
    )

    async def _collect(message: str) -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id=session_id,
                message=message,
                runtime_contract={"task_environment_id": "env.coding.vibe_workspace"},
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

def test_vibe_coding_artifact_write_creates_environment_dirs_and_publishes(tmp_path: Path) -> None:
    session_id = "session-vibe-coding-artifact-publish"
    artifact_path = _session_artifact_path(session_id, "coding/vibe-workspace", "vibe_index.html")
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
    runtime_root = _runtime_test_root(tmp_path)
    runtime = build_harness_runtime(
        base_dir=runtime_root,
        model_runtime=model,
        tool_runtime=_tool_runtime_for_names(runtime_root, {"write_file", "path_exists"}),
    )

    async def _collect(message: str) -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id=session_id,
                message=message,
                runtime_contract={"task_environment_id": "env.coding.vibe_workspace"},
            )
        ):
            events.append(event)
        return events

    write_events = asyncio.run(_collect("写一个 vibe coding artifact。"))
    storage_root = runtime_root / f"mythical-agent/sessions/{session_id}/environments/coding/vibe-workspace"
    artifact_root = storage_root / "artifacts"
    published_file = runtime_root / artifact_path
    write_observation = next(dict(event.get("tool_observation") or {}) for event in write_events if event.get("type") == "tool_observation")
    artifact_refs = [dict(item) for item in list(write_observation.get("artifact_refs") or [])]

    assert storage_root.exists()
    assert artifact_root.exists()
    assert write_observation["status"] == "ok"
    assert published_file.exists()
    assert artifact_refs and artifact_refs[0]["published"] is True
    assert artifact_refs[0]["absolute_path"] == str(published_file.resolve())

    exists_events = asyncio.run(_collect("确认 vibe coding artifact 是否存在。"))
    exists_observation = next(dict(event.get("tool_observation") or {}) for event in exists_events if event.get("type") == "tool_observation")

    assert model.calls == 4
    assert exists_observation["status"] == "ok"
    assert exists_observation["text"] == "true"

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
                runtime_contract={"task_environment_id": "env.coding.vibe_workspace"},
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
                runtime_contract={"task_environment_id": "env.coding.vibe_workspace"},
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    observation = next(dict(event.get("tool_observation") or {}) for event in events if event.get("type") == "tool_observation")
    artifact_refs = [dict(item) for item in list(observation.get("artifact_refs") or [])]

    assert observation["status"] == "ok"
    assert project_file.exists()
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
                runtime_contract={"task_environment_id": "env.coding.vibe_workspace"},
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
                runtime_contract={"task_environment_id": "env.coding.vibe_workspace"},
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    observation = next(dict(event.get("tool_observation") or {}) for event in events if event.get("type") == "tool_observation")
    artifact_refs = [dict(item) for item in list(observation.get("artifact_refs") or [])]

    assert observation["status"] == "ok"
    assert project_file.exists()
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
    assert not any("本轮工具观察次数已达到上限" in str(item.get("content") or "") for item in runtime.session_manager.messages)
