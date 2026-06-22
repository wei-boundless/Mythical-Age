from __future__ import annotations

from tests.support.harness_runtime_facade_support import *
from harness.runtime.control_events import RuntimeSignalScope


def _turn_runtime_gateway_signals(
    runtime,
    turn_run_id: str,
    event_type: str,
    *,
    signal_type: str = "control.signal.requested",
) -> list[dict[str, object]]:
    host = runtime.single_agent_runtime_host
    signals: list[dict[str, object]] = []
    for event in host.event_log.list_events(turn_run_id):
        if event.event_type != event_type:
            continue
        signal = dict(dict(event.payload or {}).get("signal") or {})
        if signal.get("signal_type") != signal_type:
            continue
        signal["_event_id"] = str(event.event_id or "")
        signals.append(signal)
    return signals


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


def test_native_tool_call_parser_does_not_generate_second_identity_when_call_id_missing() -> None:
    from harness.loop.single_agent_turn import _action_requests_from_native_tool_calls_with_diagnostics

    parsed = _action_requests_from_native_tool_calls_with_diagnostics(
        [{"name": "search_text", "args": {"query": "requestAnimationFrame"}}],
        turn_id="turn:native-missing-id",
        packet_ref="packet:native-missing-id",
        iteration=1,
        allowed_action_types=("respond", "tool_call"),
    )

    assert not parsed.actions
    assert parsed.errors[0]["code"] == "native_action_request_missing"
    assert parsed.errors[0]["native_tool_call"]["id"] == ""


def test_native_respond_parser_requires_provider_normalized_call_id() -> None:
    from harness.loop.single_agent_turn import _action_requests_from_native_tool_calls_with_diagnostics

    parsed = _action_requests_from_native_tool_calls_with_diagnostics(
        [{"name": "respond", "args": {"final_answer": "完成。"}}],
        turn_id="turn:native-respond-missing-id",
        packet_ref="packet:native-respond-missing-id",
        iteration=1,
        allowed_action_types=("respond", "tool_call"),
    )

    assert not parsed.actions
    assert parsed.errors[0]["code"] == "native_tool_call_id_missing"
    assert parsed.errors[0]["native_tool_call"]["id"] == ""


def test_tool_followup_prefix_lock_marks_changed_old_message_volatile() -> None:
    from harness.loop.single_agent_turn import _single_agent_turn_followup_segment_plan
    from harness.runtime.prompt_segment_plan import stable_text_hash

    base_segment_plan = {
        "segments": [
            {
                "model_message_index": 0,
                "model_message_role": "system",
                "kind": "turn_stable",
                "source_ref": "stable:test",
                "cache_scope": "session",
                "cache_role": "session_stable",
                "prefix_tier": "session",
                "content_hash": stable_text_hash("old stable content"),
            }
        ]
    }

    segment_plan = _single_agent_turn_followup_segment_plan(
        base_segment_plan=base_segment_plan,
        model_messages=[{"role": "system", "content": "changed stable content"}],
        packet_id="packet:prefix-lock",
        tool_iteration=1,
    )
    segment = dict(list(segment_plan["segments"])[0])
    metadata = dict(segment.get("metadata") or {})

    assert segment_plan["prefix_lock"]["status"] == "violated"
    assert segment["kind"] == "turn_stable"
    assert segment["cache_role"] == "volatile"
    assert segment["prefix_tier"] == "volatile"
    assert metadata["prefix_lock_status"] == "violated"
    assert metadata["prefix_lock_violation"]["reason"] == "content_hash_changed"


def test_tool_followup_prefix_lock_uses_provider_message_hash_with_reasoning_content() -> None:
    from harness.loop.single_agent_turn import _single_agent_turn_followup_segment_plan
    from harness.runtime.prompt_segment_plan import build_prompt_segment_plan

    assistant_message = {
        "role": "assistant",
        "content": "",
        "reasoning_content": "reasoning is part of the provider message prefix",
        "tool_calls": [{"id": "call-read", "name": "read_file", "args": {"path": "README.md"}}],
    }
    base_segment_plan = build_prompt_segment_plan(
        packet_id="packet:prefix-lock-reasoning",
        invocation_kind="single_agent_turn",
        message_specs=[
            {
                "role": "assistant",
                "content": "",
                "kind": "provider_protocol_history",
                "source_ref": "api_transcript:assistant",
                "cache_scope": "task",
                "cache_role": "session_stable",
                "prefix_tier": "task",
                "model_message": assistant_message,
            }
        ],
    ).to_dict()

    segment_plan = _single_agent_turn_followup_segment_plan(
        base_segment_plan=base_segment_plan,
        model_messages=[
            {
                "role": "assistant",
                "content": "",
                "reasoning_content": "reasoning is part of the provider message prefix",
                "tool_calls": [{"id": "call-read", "name": "read_file", "args": {"path": "README.md"}}],
            }
        ],
        packet_id="packet:prefix-lock-reasoning",
        tool_iteration=1,
    )

    assert segment_plan["prefix_lock"]["status"] == "preserved"
    segment = dict(list(segment_plan["segments"])[0])
    assert segment["cache_role"] == "session_stable"
    assert segment["prefix_tier"] == "task"

    missing_reasoning_plan = _single_agent_turn_followup_segment_plan(
        base_segment_plan=base_segment_plan,
        model_messages=[
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "call-read", "name": "read_file", "args": {"path": "README.md"}}],
            }
        ],
        packet_id="packet:prefix-lock-reasoning",
        tool_iteration=1,
    )

    assert missing_reasoning_plan["prefix_lock"]["status"] == "violated"


def test_tool_followup_rebases_old_volatile_tool_transcript_into_task_prefix() -> None:
    from harness.loop.single_agent_turn import _single_agent_turn_followup_segment_plan
    from harness.runtime.prompt_segment_plan import stable_text_hash

    old_call = {
        "role": "assistant",
        "content": "",
        "tool_calls": [{"id": "call-old", "function": {"name": "read_file", "arguments": "{\"path\":\"a.py\"}"}}],
    }
    old_observation = {
        "role": "tool",
        "tool_call_id": "call-old",
        "name": "read_file",
        "content": "old observation",
    }
    current_call = {
        "role": "assistant",
        "content": "",
        "tool_calls": [{"id": "call-new", "function": {"name": "read_file", "arguments": "{\"path\":\"b.py\"}"}}],
    }
    current_observation = {
        "role": "tool",
        "tool_call_id": "call-new",
        "name": "read_file",
        "content": "new observation",
    }
    base_segment_plan = {
        "segments": [
            {
                "model_message_index": 0,
                "model_message_role": "assistant",
                "kind": "single_agent_turn_tool_call",
                "source_ref": "single_agent_turn.tool_call:1",
                "cache_scope": "none",
                "cache_role": "volatile",
                "prefix_tier": "volatile",
                "content_hash": stable_text_hash(""),
            },
            {
                "model_message_index": 1,
                "model_message_role": "tool",
                "kind": "single_agent_turn_tool_observation",
                "source_ref": "single_agent_turn.tool_observation:1",
                "cache_scope": "none",
                "cache_role": "volatile",
                "prefix_tier": "volatile",
                "content_hash": stable_text_hash("old observation"),
            },
        ]
    }

    segment_plan = _single_agent_turn_followup_segment_plan(
        base_segment_plan=base_segment_plan,
        model_messages=[old_call, old_observation, current_call, current_observation],
        packet_id="packet:old-volatile-tool-transcript",
        tool_iteration=2,
    )
    segments = list(segment_plan["segments"])

    assert segment_plan["prefix_lock"]["status"] == "preserved"
    assert segments[0]["cache_role"] == "session_stable"
    assert segments[0]["prefix_tier"] == "task"
    assert segments[1]["cache_role"] == "session_stable"
    assert segments[1]["prefix_tier"] == "task"
    assert segments[2]["cache_role"] == "session_stable"
    assert segments[2]["prefix_tier"] == "task"
    assert segments[3]["cache_role"] == "session_stable"
    assert segments[3]["prefix_tier"] == "task"
    assert "call-old" in segments[0]["source_ref"]
    assert "call-old" in segments[1]["source_ref"]


def test_tool_followup_segment_plan_preserves_physical_message_order() -> None:
    from harness.loop.single_agent_turn import _single_agent_turn_followup_segment_plan
    from harness.runtime.prompt_segment_plan import stable_text_hash

    stable_message = {"role": "system", "content": "stable contract"}
    volatile_runtime = {"role": "system", "content": "volatile runtime"}
    current_user = {"role": "user", "content": "current user request"}
    old_call = {
        "role": "assistant",
        "content": "",
        "tool_calls": [{"id": "call-old", "function": {"name": "read_file", "arguments": "{\"path\":\"a.py\"}"}}],
    }
    old_observation = {
        "role": "tool",
        "tool_call_id": "call-old",
        "name": "read_file",
        "content": "old observation",
    }
    current_call = {
        "role": "assistant",
        "content": "",
        "tool_calls": [{"id": "call-new", "function": {"name": "read_file", "arguments": "{\"path\":\"b.py\"}"}}],
    }
    current_observation = {
        "role": "tool",
        "tool_call_id": "call-new",
        "name": "read_file",
        "content": "new observation",
    }
    base_segment_plan = {
        "segments": [
            {
                "model_message_index": 0,
                "model_message_role": "system",
                "kind": "turn_stable",
                "source_ref": "stable:test",
                "cache_scope": "session",
                "cache_role": "session_stable",
                "prefix_tier": "session",
                "content_hash": stable_text_hash("stable contract"),
            },
            {
                "model_message_index": 1,
                "model_message_role": "system",
                "kind": "volatile_runtime_state",
                "source_ref": "volatile:test",
                "cache_scope": "none",
                "cache_role": "volatile",
                "prefix_tier": "volatile",
                "content_hash": stable_text_hash("volatile runtime"),
            },
            {
                "model_message_index": 2,
                "model_message_role": "user",
                "kind": "volatile_user",
                "source_ref": "current_request:test",
                "cache_scope": "none",
                "cache_role": "volatile",
                "prefix_tier": "volatile",
                "content_hash": stable_text_hash("current user request"),
            },
        ]
    }

    model_messages = [
        stable_message,
        volatile_runtime,
        current_user,
        old_call,
        old_observation,
        current_call,
        current_observation,
    ]
    segment_plan = _single_agent_turn_followup_segment_plan(
        base_segment_plan=base_segment_plan,
        model_messages=model_messages,
        packet_id="packet:append-only-followup",
        tool_iteration=2,
    )
    segments = list(segment_plan["segments"])

    assert segment_plan["prefix_lock"]["status"] == "preserved"
    assert [int(segment["model_message_index"]) for segment in segments] == list(range(len(model_messages)))
    assert [str(segment["model_message_role"]) for segment in segments] == [
        str(message.get("role") or "user") for message in model_messages
    ]
    assert [str(segment["content_hash"]) for segment in segments] == [
        stable_text_hash(str(message.get("content") or "")) for message in model_messages
    ]
    assert [segment["kind"] for segment in segments] == [
        "turn_stable",
        "volatile_runtime_state",
        "volatile_user",
        "single_agent_turn_tool_call",
        "single_agent_turn_tool_observation",
        "single_agent_turn_tool_call",
        "single_agent_turn_tool_observation",
    ]
    assert segments[1]["cache_role"] == "volatile"
    assert segments[1]["prefix_tier"] == "volatile"
    assert segments[2]["cache_role"] == "volatile"
    assert segments[2]["prefix_tier"] == "volatile"
    assert segments[3]["cache_role"] == "session_stable"
    assert segments[4]["cache_role"] == "session_stable"
    assert segments[5]["cache_role"] == "session_stable"
    assert segments[6]["cache_role"] == "session_stable"


def test_tool_followup_keeps_replaceable_dynamic_tail_out_of_accumulated_context() -> None:
    from harness.loop.single_agent_turn import (
        _append_tool_transcript_to_accumulated_context,
        _single_agent_turn_followup_segment_plan,
    )
    from harness.runtime.prompt_segment_plan import stable_text_hash

    base_segment_plan = {
        "segments": [
            {
                "model_message_index": 0,
                "model_message_role": "system",
                "kind": "global_static",
                "source_ref": "stable:test",
                "cache_scope": "global",
                "cache_role": "cacheable_prefix",
                "prefix_tier": "provider_global",
                "content_hash": stable_text_hash("stable"),
            },
            {
                "model_message_index": 1,
                "model_message_role": "system",
                "kind": "runtime_control_signal_tail",
                "source_ref": "dynamic:test",
                "cache_scope": "none",
                "cache_role": "volatile",
                "prefix_tier": "volatile",
                "content_hash": stable_text_hash("dynamic tail"),
            },
        ]
    }
    base_messages = [
        {"role": "system", "content": "stable"},
        {"role": "system", "content": "dynamic tail"},
    ]
    new_tool_messages = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "call-after-tail", "function": {"name": "read_file", "arguments": "{}"}}],
        },
        {"role": "tool", "tool_call_id": "call-after-tail", "name": "read_file", "content": "observation"},
    ]
    model_messages = _append_tool_transcript_to_accumulated_context(
        base_messages,
        new_tool_messages,
        segment_plan=base_segment_plan,
    )

    assert [message["content"] for message in model_messages] == ["stable", "", "observation", "dynamic tail"]

    segment_plan = _single_agent_turn_followup_segment_plan(
        base_segment_plan=base_segment_plan,
        model_messages=model_messages,
        packet_id="packet:historical-dynamic-snapshot",
        tool_iteration=1,
    )
    segments = [dict(item) for item in list(segment_plan["segments"])]

    assert [segment["kind"] for segment in segments] == [
        "global_static",
        "single_agent_turn_tool_call",
        "single_agent_turn_tool_observation",
        "runtime_control_signal_tail",
    ]
    assert segments[0]["cache_role"] == "cacheable_prefix"
    assert segments[1]["cache_role"] == "session_stable"
    assert segments[2]["cache_role"] == "session_stable"
    assert segments[3]["cache_role"] == "volatile"
    assert segments[3]["prefix_tier"] == "volatile"


def test_tool_followup_keeps_existing_incremental_frame_before_new_tool_transcript_with_stale_plan() -> None:
    from harness.loop.single_agent_turn import (
        _append_tool_transcript_to_accumulated_context,
        _single_agent_turn_followup_segment_plan,
    )
    from harness.runtime.prompt_segment_plan import stable_text_hash

    old_frame = {
        "role": "system",
        "source_ref": "single_agent_turn_incremental_context_frame",
        "content": "你正在继续同一个工具执行回合。\n{\"frame_type\": \"incremental_context_frame\"}",
    }
    stale_segment_plan = {
        "segments": [
            {
                "model_message_index": 0,
                "model_message_role": "system",
                "kind": "global_static",
                "source_ref": "stable:test",
                "cache_scope": "global",
                "cache_role": "cacheable_prefix",
                "prefix_tier": "provider_global",
                "content_hash": stable_text_hash("stable"),
            },
            {
                "model_message_index": 1,
                "model_message_role": "assistant",
                "kind": "single_agent_turn_tool_call",
                "source_ref": "tool:test:old-call",
                "cache_scope": "task",
                "cache_role": "session_stable",
                "prefix_tier": "task",
                "content_hash": stable_text_hash(""),
            },
            {
                "model_message_index": 2,
                "model_message_role": "tool",
                "kind": "single_agent_turn_tool_observation",
                "source_ref": "tool:test:old",
                "cache_scope": "task",
                "cache_role": "session_stable",
                "prefix_tier": "task",
                "content_hash": stable_text_hash("old observation"),
            },
            {
                "model_message_index": 3,
                "model_message_role": "system",
                "kind": "dynamic_projection",
                "source_ref": "dynamic:test:stale-index",
                "cache_scope": "none",
                "cache_role": "volatile",
                "prefix_tier": "volatile",
                "content_hash": stable_text_hash("old dynamic tail"),
            },
        ]
    }
    base_messages = [
        {"role": "system", "content": "stable"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "call-old", "function": {"name": "read_file", "arguments": "{}"}}],
        },
        {"role": "tool", "tool_call_id": "call-old", "name": "read_file", "content": "old observation"},
        old_frame,
    ]
    new_tool_messages = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "call-new", "function": {"name": "read_file", "arguments": "{}"}}],
        },
        {"role": "tool", "tool_call_id": "call-new", "name": "read_file", "content": "new observation"},
    ]

    model_messages = _append_tool_transcript_to_accumulated_context(
        base_messages,
        new_tool_messages,
        segment_plan=stale_segment_plan,
    )

    assert [message.get("source_ref") or message.get("content") for message in model_messages] == [
        "stable",
        "",
        "old observation",
        "single_agent_turn_incremental_context_frame",
        "",
        "new observation",
    ]

    segment_plan = _single_agent_turn_followup_segment_plan(
        base_segment_plan=stale_segment_plan,
        model_messages=model_messages,
        packet_id="packet:stale-plan-incremental-frame",
        tool_iteration=2,
    )
    segments = [dict(item) for item in list(segment_plan["segments"])]

    assert [segment["kind"] for segment in segments] == [
        "global_static",
        "single_agent_turn_tool_call",
        "single_agent_turn_tool_observation",
        "incremental_context_frame",
        "single_agent_turn_tool_call",
        "single_agent_turn_tool_observation",
    ]
    assert segments[3]["cache_role"] == "session_stable"
    assert segments[3]["prefix_tier"] == "task"


def test_tool_followup_incremental_context_frame_marks_current_tool_round(tmp_path: Path) -> None:
    model = NativeToolCallSequenceModelRuntimeStub(
        [
            {
                "content": "先读取 requirements.txt。",
                "tool_calls": [
                    {
                        "id": "call-read-requirements",
                        "name": "read_file",
                        "args": {"path": "requirements.txt", "line_count": 20},
                    }
                ],
            },
            {
                "content": json.dumps(
                    _action_request(action_type="respond", final_answer="已经读取 requirements.txt。"),
                    ensure_ascii=False,
                ),
            },
        ]
    )
    runtime = build_harness_runtime(
        base_dir=_runtime_test_root(tmp_path),
        model_runtime=model,
        tool_runtime=_tool_runtime_for_names(_project_backend_dir(), {"read_file"}),
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(HarnessRuntimeRequest(session_id="session-tool-followup-incremental-frame", message="看看依赖文件。")):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    followup_messages = [dict(item) for item in list(model.seen_messages[-1] or []) if isinstance(item, dict)]
    incremental_frame_message = next(
        item
        for item in followup_messages
        if str(item.get("content") or "").startswith("你正在继续同一个工具执行回合。")
    )
    action_contract_message = next(
        item
        for item in followup_messages
        if "你是正在根据刚才工具观察决定下一步的 coding agent。" in str(item.get("content") or "")
    )
    incremental_frame_payload = json.loads(str(incremental_frame_message.get("content") or "").rsplit("\n", 1)[-1])
    followup_context = dict(model.seen_accounting_contexts[-1])
    followup_segment_plan = dict(followup_context.get("segment_plan") or {})
    followup_kinds = [str(item.get("kind") or "") for item in list(followup_segment_plan.get("segments") or [])]
    followup_segments = [dict(item) for item in list(followup_segment_plan.get("segments") or []) if isinstance(item, dict)]

    assert next(event for event in events if event.get("type") == "done")["terminal_reason"] == "respond"
    assert followup_messages[-2] == incremental_frame_message
    assert followup_messages[-1] == action_contract_message
    assert "incremental_context_frame" in followup_kinds
    assert [int(segment["model_message_index"]) for segment in followup_segments] == list(range(len(followup_messages)))
    assert [str(segment["model_message_role"]) for segment in followup_segments] == [
        str(message.get("role") or "user") for message in followup_messages
    ]
    assert dict(followup_segment_plan.get("prefix_lock") or {})["status"] == "preserved"
    assert "cache_aligned_order" not in followup_segment_plan
    assert followup_kinds[-2:] == ["incremental_context_frame", "single_agent_turn_followup_message"]
    assert incremental_frame_payload["frame_type"] == "incremental_context_frame"
    assert incremental_frame_payload["base_prefix"]["prefix_lock_status"] == "preserved"
    assert incremental_frame_payload["current_tool_round"]["status"] == "present"
    assert [event["event_kind"] for event in incremental_frame_payload["current_tool_round"]["events"]] == [
        "tool_call",
        "tool_observation",
    ]
    assert incremental_frame_payload["tool_context_delta"]["status"] == "present"
    assert incremental_frame_payload["tool_context_delta"]["ledger_entry_count"] == 1
    assert len(incremental_frame_payload["tool_context_delta"]["new_entries"]) == 1
    assert incremental_frame_payload["unchanged_refs"] == []


def test_tool_followup_preserves_previous_transcript_prefix_between_rounds(tmp_path: Path) -> None:
    model = NativeToolCallSequenceModelRuntimeStub(
        [
            {
                "content": "先读依赖文件。",
                "tool_calls": [
                    {
                        "id": "call-read-requirements",
                        "name": "read_file",
                        "args": {"path": "app.py", "line_count": 5},
                    }
                ],
            },
            {
                "content": "再读项目说明。",
                "tool_calls": [
                    {
                        "id": "call-read-readme",
                        "name": "read_file",
                        "args": {"path": "config.py", "line_count": 5},
                    }
                ],
            },
            {
                "content": json.dumps(
                    _action_request(action_type="respond", final_answer="已经读取两个文件。"),
                    ensure_ascii=False,
                ),
            },
        ]
    )
    runtime = build_harness_runtime(
        base_dir=_runtime_test_root(tmp_path),
        model_runtime=model,
        tool_runtime=_tool_runtime_for_names(_project_backend_dir(), {"read_file"}),
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(HarnessRuntimeRequest(session_id="session-tool-followup-physical-prefix", message="检查项目入口。")):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    assert next(event for event in events if event.get("type") == "done")["terminal_reason"] == "respond"
    assert len(model.seen_messages) >= 3

    first_followup = [dict(item) for item in list(model.seen_messages[1] or []) if isinstance(item, dict)]
    second_followup = [dict(item) for item in list(model.seen_messages[2] or []) if isinstance(item, dict)]
    first_segment_plan = dict(model.seen_accounting_contexts[1].get("segment_plan") or {})
    second_segment_plan = dict(model.seen_accounting_contexts[2].get("segment_plan") or {})
    first_incremental_indexes = [
        index
        for index, message in enumerate(first_followup)
        if str(message.get("content") or "").startswith("你正在继续同一个工具执行回合。")
    ]
    second_incremental_indexes = [
        index
        for index, message in enumerate(second_followup)
        if str(message.get("content") or "").startswith("你正在继续同一个工具执行回合。")
    ]
    second_latest_incremental_index = second_incremental_indexes[-1]
    second_latest_incremental_payload = json.loads(
        str(second_followup[second_latest_incremental_index].get("content") or "").rsplit("\n", 1)[-1]
    )

    assert "你是正在根据刚才工具观察决定下一步的 coding agent。" in str(first_followup[-1].get("content") or "")
    assert _stable_segment_signature(first_segment_plan) == _stable_segment_signature(second_segment_plan)[
        : len(_stable_segment_signature(first_segment_plan))
    ]
    assert second_incremental_indexes[: len(first_incremental_indexes)] == first_incremental_indexes
    assert second_latest_incremental_index > first_incremental_indexes[-1]
    assert str(second_followup[second_latest_incremental_index - 2].get("role") or "") == "assistant"
    assert second_followup[second_latest_incremental_index - 2].get("tool_calls")
    assert str(second_followup[second_latest_incremental_index - 1].get("role") or "") == "tool"
    assert second_latest_incremental_payload["tool_context_delta"]["ledger_entry_count"] == 2
    assert len(second_latest_incremental_payload["tool_context_delta"]["new_entries"]) == 1
    assert second_latest_incremental_payload["unchanged_refs"]
    assert "你是正在根据刚才工具观察决定下一步的 coding agent。" in str(second_followup[-1].get("content") or "")


def _stable_segment_signature(segment_plan: dict[str, object]) -> list[tuple[str, str]]:
    segments = [dict(item) for item in list(segment_plan.get("segments") or []) if isinstance(item, dict)]
    return [
        (str(segment.get("kind") or ""), str(segment.get("content_hash") or ""))
        for segment in segments
        if str(segment.get("cache_role") or "") in {"cacheable_prefix", "session_stable"}
        and str(segment.get("prefix_tier") or "") not in {"volatile", "none"}
    ]


def test_single_agent_turn_projection_separates_assistant_text_from_control_actions(tmp_path: Path) -> None:
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
    stable_boundary_message = next(
        message
        for message in model.last_messages
        if str(message.get("content") or "").startswith("Single agent turn stable boundary\n")
    )
    stable_payload = _packet_payload_after_title(
        str(stable_boundary_message.get("content") or ""),
        "Single agent turn stable boundary",
    )
    effective_capabilities = dict(stable_payload.get("control_capabilities") or {})
    model_input = "\n".join(str(message.get("content") or "") for message in model.last_messages)
    output_contract = dict(stable_payload.get("output_contract") or {})
    action_protocol = dict(output_contract.get("action_protocol") or {})
    ordinary_tool_contract = dict(action_protocol.get("ordinary_tool_calls") or {})
    native_tool_contract = dict(action_protocol.get("native_tool_calls") or {})
    transport_table = dict(action_protocol.get("transport_decision_table") or {})
    feedback_contract = dict(action_protocol.get("public_feedback_contract") or {})
    native_feedback_contract = dict(action_protocol.get("native_tool_feedback_contract") or {})

    assert dict(assembly.get("control_capabilities") or {}).get("may_call_tools") is True
    assert set(start.get("allowed_action_types") or []) == {
        "respond",
        "ask_user",
        "block",
        "request_task_run",
        "active_work_control",
        "tool_call",
    }
    assert effective_capabilities.get("may_call_tools") is True
    assert effective_capabilities.get("may_use_subagents") is False
    assert effective_capabilities.get("supports_json_action_protocol") is True
    assert effective_capabilities.get("requires_json_action_protocol") is False
    assert output_contract.get("format") == "assistant_message_or_action"
    assert dict(action_protocol.get("assistant_messages") or {}).get("transport") == "assistant_message"
    assert dict(action_protocol.get("assistant_messages") or {}).get("terminal_when_no_action") is True
    assert ordinary_tool_contract.get("multi_tool_calls_allowed") is True
    assert ordinary_tool_contract.get("runtime_execution_policy") == "tool_batch_plan_scheduled_by_safety_and_resource_locks"
    assert "parallel_allowed" not in ordinary_tool_contract
    assert native_tool_contract.get("enabled") is True
    assert native_tool_contract.get("provider_multi_tool_calls_allowed") is True
    assert native_tool_contract.get("runtime_execution_policy") == "tool_batch_plan_scheduled_by_safety_and_resource_locks"
    assert dict(action_protocol.get("control_actions") or {}).get("native_tool_transport_enabled") is False
    assert dict(transport_table.get("control_actions") or {}).get("transport") == "json_action"
    assert dict(transport_table.get("control_actions") or {}).get("native_tool_transport_enabled") is False
    assert dict(transport_table.get("ordinary_tool_calls") or {}).get("transport") == "provider_native_tool_call_or_json_tool_call"
    assert dict(transport_table.get("ordinary_tool_calls") or {}).get("native_tool_transport_enabled") is True
    assert dict(transport_table.get("assistant_body") or {}).get("disabled_reason_when_json_required") == "explicit_control_phase_requires_structured_control_decision"
    assert feedback_contract.get("feedback_must_be_model_authored") is True
    assert feedback_contract.get("system_must_not_synthesize_user_semantic_text") is True
    assert "public_progress_note" in list(feedback_contract.get("json_action_feedback_fields") or [])
    assert native_feedback_contract.get("assistant_content_preamble_is_public_feedback") is True
    assert native_feedback_contract.get("projection_target") == "assistant_public_feedback"
    assert native_feedback_contract.get("missing_preamble_policy") == "record_contract_gap_without_synthesizing_body"
    assert "runtime_prompt.system_call_boundary" in model_input
    assert "runtime_prompt.control_action_json" in model_input
    assert "runtime_prompt.native_tool_preamble" in model_input
    assert "single_action_per_turn" not in json.dumps(output_contract, ensure_ascii=False)
    assert getattr(model.seen_tool_call_options[0], "parallel_tool_calls", None) is True

def test_single_agent_turn_read_only_tool_executes_through_control_plane_and_followup_answers(tmp_path: Path) -> None:
    from harness.runtime.projection.projector import project_public_projection_event
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
    done = next(event for event in events if event.get("type") == "done")
    assistant_finals = [dict(event) for event in events if event.get("type") == "assistant_text_final"]
    public_feedback_events = [
        dict(event)
        for event in events
        if event.get("type") == "assistant_public_feedback"
        and event.get("presentation_source") == "model_action.assistant_content_preamble"
    ]
    followup_messages = [dict(item) for item in list(model.seen_messages[-1] or []) if isinstance(item, dict)]
    assistant_tool_message = next(item for item in followup_messages if item.get("role") == "assistant" and item.get("tool_calls"))
    tool_message = next(item for item in followup_messages if item.get("role") == "tool")
    followup_context = dict(model.seen_accounting_contexts[-1])
    followup_segment_plan = dict(followup_context.get("segment_plan") or {})
    followup_prompt_manifest = dict(followup_context.get("prompt_manifest") or {})
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
    assert done["terminal_reason"] == "respond"
    assert done["answer_source"] == "harness.single_agent_turn.respond"
    assert "已经读取 requirements.txt。" in str(done.get("content") or "")
    assert assistant_finals and assistant_finals[-1]["content"] == "已经读取 requirements.txt。"
    assert len(public_feedback_events) == 1
    assert public_feedback_events[0]["public_progress_note"] == "我先读取 requirements.txt，再回答依赖状态。"
    from runtime.output_stream.public_contract import ASSISTANT_PUBLIC_FEEDBACK_EVENT

    projected_feedback = project_public_projection_event(
        ASSISTANT_PUBLIC_FEEDBACK_EVENT,
        public_feedback_events[0],
        session_id="session-single-turn-read-tool",
        sequence=1,
    )["public_projection_frame"]
    assert projected_feedback["source_event_type"] == ASSISTANT_PUBLIC_FEEDBACK_EVENT
    assert projected_feedback["op"] == "body_append"
    assert projected_feedback["slot"] == "body"
    assert projected_feedback["source_authority"] == "model"
    assert projected_feedback["text"] == "我先读取 requirements.txt，再回答依赖状态。"
    assert tool_observations and tool_observations[0]["status"] == "ok"
    assert tool_observations[0]["caller_kind"] == "agent_turn"
    assert tool_observations[0]["tool_name"] == "read_file"
    assert dict(tool_observations[0].get("diagnostics") or {}).get("stage") == "tool_runtime_executor_dispatch"
    assert str(tool_observations[0].get("caller_ref") or "").startswith("turnrun:")
    assert "task_run_id" not in dict(tool_observations[0].get("result_envelope") or {})
    assert dict(list(assistant_tool_message["tool_calls"])[0]).get("id") == "call-read-requirements"
    assert tool_message["tool_call_id"] == "call-read-requirements"
    assert followup_context["source"] == "harness.single_agent_turn.tool_followup"
    assert followup_prompt_manifest["tool_followup_action_guidance"] is True
    assert followup_prompt_manifest["assistant_body_transport"] == "plain_response_allowed"
    assert followup_prompt_manifest["control_action_transport"] == "json_action"
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
    assert evidence_payload["visible_exact_in_packet"] is False
    assert "read_evidence_injections" not in evidence_payload
    assert evidence_payload["read_evidence_refs"][0]["path"] == "requirements.txt"
    assert evidence_payload["projection_policy"]["rehydration"] == "read_again_or_artifact_lookup_when_exact_text_is_needed"


def test_single_agent_turn_accepts_plain_text_tool_followup_as_agent_closeout(tmp_path: Path) -> None:
    model = NativeToolCallSequenceModelRuntimeStub(
        [
            {
                "content": "我先读取 requirements.txt，再判断依赖状态。",
                "tool_calls": [
                    {
                        "id": "call-read-requirements",
                        "name": "read_file",
                        "args": {"path": "requirements.txt", "line_count": 80},
                    }
                ],
            },
            {
                "content": (
                    "现在所有线索都串起来了。\n\n"
                    "结论：requirements.txt 已经成功读取，依赖清单存在且可以作为后续分析依据。"
                    "当前没有发现读取失败、权限失败或路径错误。下一步如果要继续排查，"
                    "我会基于这份依赖文件检查具体版本约束和运行链路。"
                ),
                "additional_kwargs": {"reasoning_content": "The tool result is enough for a user-facing closeout."},
            },
        ]
    )
    runtime = build_harness_runtime(
        base_dir=_runtime_test_root(tmp_path),
        model_runtime=model,
        tool_runtime=_tool_runtime_for_names(_project_backend_dir(), {"read_file"}),
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(session_id="session-single-turn-plain-tool-followup", message="看看依赖文件。")
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    done = next(event for event in events if event.get("type") == "done")
    assistant_finals = [dict(event) for event in events if event.get("type") == "assistant_text_final"]
    control_signals = [
        dict(dict(event.get("event") or {}).get("payload") or {}).get("runtime_control_signal")
        for event in events
        if event.get("type") == "turn_runtime_control_signal_observed"
    ]
    followup_prompt_text = "\n".join(
        str(message.get("content") or "")
        for message in list(model.seen_messages[-1] or [])
        if isinstance(message, dict)
    )
    assistant_messages = [
        dict(item)
        for item in runtime.session_manager.messages
        if str(dict(item).get("role") or "") == "assistant"
    ]

    assert model.calls == 2
    assert done["terminal_reason"] == "assistant_message"
    assert done["answer_source"] == "harness.single_agent_turn"
    assert "依赖清单存在" in str(done.get("content") or "")
    assert assistant_finals and "依赖清单存在" in str(assistant_finals[-1].get("content") or "")
    assert assistant_messages and "依赖清单存在" in str(assistant_messages[-1].get("content") or "")
    assert not any(dict(signal or {}).get("signal_kind") == "model_protocol_violation" for signal in control_signals)
    assert "直接写用户可见的最终回复" in followup_prompt_text
    assert "不要为了最终回答把自然语言正文塞进 JSON" in followup_prompt_text


def test_single_agent_turn_tool_observation_advances_turn_run_cursor_before_followup(tmp_path: Path) -> None:
    model = NativeToolCallSequenceModelRuntimeStub(
        [
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call-read-requirements",
                        "name": "read_file",
                        "args": {"path": "requirements.txt", "line_count": 20},
                    }
                ],
            },
            {"content": "不应该等到这里才更新工具观察游标。"},
        ]
    )
    runtime = build_harness_runtime(
        base_dir=_runtime_test_root(tmp_path),
        model_runtime=model,
        tool_runtime=_tool_runtime_for_names(_project_backend_dir(), {"read_file"}),
    )
    cursor_updates: list[int] = []
    original_upsert_turn_run = runtime.single_agent_runtime_host.state_index.upsert_turn_run

    def _spy_upsert_turn_run(turn_run):
        cursor_updates.append(int(getattr(turn_run, "latest_event_offset", -1) or -1))
        return original_upsert_turn_run(turn_run)

    runtime.single_agent_runtime_host.state_index.upsert_turn_run = _spy_upsert_turn_run

    async def _collect_until_observation() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(session_id="session-single-turn-observation-cursor", message="看看依赖文件。")
        ):
            events.append(event)
            if event.get("type") == "turn_tool_observation_recorded":
                break
        return events

    events = asyncio.run(_collect_until_observation())
    observation_event = dict(next(event for event in events if event.get("type") == "turn_tool_observation_recorded").get("event") or {})
    turn_run_id = str(observation_event.get("run_id") or "")
    turn_run = runtime.single_agent_runtime_host.state_index.get_turn_run(turn_run_id)

    assert turn_run is not None
    assert observation_event["offset"] in cursor_updates
    assert turn_run.latest_event_offset >= observation_event["offset"]


def test_single_agent_turn_absorbs_queued_user_steer_before_executing_model_action(tmp_path: Path) -> None:
    class MidModelSteerRuntime:
        def __init__(self) -> None:
            self.runtime = None
            self.calls = 0
            self.seen_messages: list[list[dict[str, object]]] = []

        async def invoke_messages_with_tools(self, messages, tools, **kwargs):
            del tools
            return await self.invoke_messages(messages, **kwargs)

        async def invoke_messages(self, messages, **_kwargs):
            self.calls += 1
            self.seen_messages.append([dict(item) for item in list(messages or []) if isinstance(item, dict)])
            if self.calls == 1:
                self.runtime.single_agent_runtime_host.queued_user_inputs.enqueue(
                    session_id="session-single-turn-live-steer",
                    content="补充：先处理设置页面里的字体选项。",
                    client_message_id="user:live-steer",
                    input_policy="auto",
                )
                return SimpleNamespace(
                    content=json.dumps(
                        _tool_action_request(
                            tool_name="read_file",
                            args={"path": "requirements.txt", "line_count": 20},
                            public_progress_note="准备读取依赖文件。",
                        ),
                        ensure_ascii=False,
                    )
                )
            return SimpleNamespace(
                content=json.dumps(
                    _action_request(
                        action_type="respond",
                        final_answer="已按补充要求转向设置页面的字体选项。",
                    ),
                    ensure_ascii=False,
                )
            )

    model = MidModelSteerRuntime()
    tool_base_dir = _project_backend_dir()
    runtime = build_harness_runtime(
        base_dir=_runtime_test_root(tmp_path),
        model_runtime=model,
        tool_runtime=_tool_runtime_for_names(tool_base_dir, {"read_file"}),
    )
    model.runtime = runtime

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-single-turn-live-steer",
                message="先检查依赖文件。",
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    event_types = [str(event.get("type") or "") for event in events]
    second_model_input = "\n\n".join(str(item.get("content") or "") for item in model.seen_messages[-1])
    queued = runtime.single_agent_runtime_host.queued_user_inputs.list_session("session-single-turn-live-steer")
    stored_messages = runtime.session_manager.load_session("session-single-turn-live-steer")

    assert model.calls == 2
    assert "active_turn_steer_included" in event_types
    assert "tool_batch_planned" not in event_types
    assert "补充：先处理设置页面里的字体选项。" in second_model_input
    assert "不是新的独立任务，也不是下一轮聊天" in second_model_input
    assert queued[0].status == "dispatched"
    assert queued[0].expected_active_turn_id.startswith("turn:session-single-turn-live-steer:")
    assert any(
        message.get("role") == "user"
        and message.get("id") == "user:live-steer"
        and message.get("active_turn_steer") is True
        for message in stored_messages
    )

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


class _NativeToolStreamChunk:
    def __init__(self, content: str = "", tool_calls: list[dict[str, object]] | None = None) -> None:
        self.content = content
        self.tool_calls = [dict(item) for item in list(tool_calls or [])]

    def __add__(self, other: object) -> "_NativeToolStreamChunk":
        return _NativeToolStreamChunk(
            self.content + str(getattr(other, "content", "") or ""),
            [*self.tool_calls, *[dict(item) for item in list(getattr(other, "tool_calls", []) or [])]],
        )


class _StreamingNativeToolSequenceModel:
    def __init__(self, responses: list[list[_NativeToolStreamChunk]]) -> None:
        self.responses = [list(item) for item in responses]
        self.calls = 0
        self.seen_tools: list[object] = []

    async def astream_messages_with_tools(self, _messages, tools, **_kwargs):
        self.calls += 1
        self.seen_tools.append(list(tools or []))
        chunks = self.responses[min(self.calls - 1, max(0, len(self.responses) - 1))] if self.responses else []
        for chunk in chunks:
            yield chunk

    async def invoke_messages_with_tools(self, _messages, tools, **_kwargs):
        self.calls += 1
        self.seen_tools.append(list(tools or []))
        chunks = self.responses[min(self.calls - 1, max(0, len(self.responses) - 1))] if self.responses else []
        current = _NativeToolStreamChunk()
        for chunk in chunks:
            current = current + chunk
        return SimpleNamespace(content=current.content, tool_calls=current.tool_calls)


def test_single_agent_turn_streamed_native_tool_preamble_has_single_body_source(tmp_path: Path) -> None:
    preamble = "我先读取 requirements.txt，再回答依赖状态。"
    model = _StreamingNativeToolSequenceModel(
        [
            [
                _NativeToolStreamChunk(preamble),
                _NativeToolStreamChunk(
                    "",
                    [
                        {
                            "id": "call-read-requirements",
                            "name": "read_file",
                            "args": {"path": "requirements.txt"},
                        }
                    ],
                ),
            ],
            [
                _NativeToolStreamChunk(
                    json.dumps(
                        _action_request(action_type="respond", final_answer="已经读取 requirements.txt。"),
                        ensure_ascii=False,
                    )
                )
            ],
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
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-streamed-native-preamble",
                message="看看依赖文件。",
                model_selection={
                    "stream_policy": {
                        "enabled": True,
                        "emit_assistant_text_delta": True,
                        "max_flush_interval_ms": 0,
                    }
                },
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    streamed_preamble = "".join(
        str(event.get("content") or "")
        for event in events
        if event.get("type") == "assistant_text_delta"
    )
    duplicate_feedback_events = [
        dict(event)
        for event in events
        if event.get("type") == "assistant_public_feedback"
        and event.get("public_progress_note") == preamble
    ]

    assert preamble in streamed_preamble
    assert duplicate_feedback_events == []


def test_single_agent_turn_tool_followup_action_json_is_not_body_streamed(tmp_path: Path) -> None:
    action = json.dumps(
        {
            **_action_request(action_type="respond", final_answer="已经读取 requirements.txt。"),
            "task_contract_seed": {
                "user_visible_goal": "不应作为正文直播。",
                "task_run_goal": "不应作为正文直播。",
                "completion_criteria": ["不泄露内部合同。"],
                "working_scope": {"target_objects": ["requirements.txt"]},
                "capability_intent": {"needed_capability_groups": ["file_work"]},
                "skill_intent": {"selected_skill_ids": [], "candidate_skill_ids": []},
                "observation_contract": {"evidence_policy": "observation_required"},
            },
        },
        ensure_ascii=False,
    )
    model = _StreamingNativeToolSequenceModel(
        [
            [
                _NativeToolStreamChunk(
                    "",
                    [
                        {
                            "id": "call-read-requirements",
                            "name": "read_file",
                            "args": {"path": "requirements.txt"},
                        }
                    ],
                )
            ],
            [_NativeToolStreamChunk(action[:80]), _NativeToolStreamChunk(action[80:])],
        ]
    )
    runtime = build_harness_runtime(
        base_dir=_runtime_test_root(tmp_path),
        model_runtime=model,
        tool_runtime=_tool_runtime_for_names(_project_backend_dir(), {"read_file"}),
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-tool-followup-action-json-hidden",
                message="看看依赖文件。",
                model_selection={
                    "stream_policy": {
                        "enabled": True,
                        "emit_assistant_text_delta": True,
                        "max_flush_interval_ms": 0,
                    }
                },
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    streamed_text = "".join(
        str(event.get("content") or "")
        for event in events
        if event.get("type") == "assistant_text_delta"
    )
    done = dict(next(event for event in events if event.get("type") == "done"))

    assert "task_contract_seed" not in streamed_text
    assert "observation_contract" not in streamed_text
    assert done["content"] == "已经读取 requirements.txt。"


def test_single_agent_turn_tool_followup_plain_text_streams_before_commit(tmp_path: Path) -> None:
    model = _StreamingNativeToolSequenceModel(
        [
            [
                _NativeToolStreamChunk(
                    "",
                    [
                        {
                            "id": "call-read-requirements",
                            "name": "read_file",
                            "args": {"path": "requirements.txt"},
                        }
                    ],
                )
            ],
            [
                _NativeToolStreamChunk("现在根据工具结果给出结论："),
                _NativeToolStreamChunk("依赖清单存在，可以继续分析。"),
            ],
        ]
    )
    runtime = build_harness_runtime(
        base_dir=_runtime_test_root(tmp_path),
        model_runtime=model,
        tool_runtime=_tool_runtime_for_names(_project_backend_dir(), {"read_file"}),
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-tool-followup-plain-text-streamed",
                message="看看依赖文件。",
                model_selection={
                    "stream_policy": {
                        "enabled": True,
                        "emit_assistant_text_delta": True,
                        "max_flush_interval_ms": 0,
                    }
                },
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    streamed_text = "".join(
        str(event.get("content") or "")
        for event in events
        if event.get("type") == "assistant_text_delta"
    )
    done = dict(next(event for event in events if event.get("type") == "done"))

    assert "依赖清单存在" in streamed_text
    assert "tool_call" not in streamed_text
    assert "依赖清单存在" in str(done.get("content") or "")


def test_single_agent_turn_recovers_partial_provider_stream_from_visible_prefix(tmp_path: Path) -> None:
    from runtime.model_gateway.model_runtime import ModelRuntimeError

    class InterruptedStreamingModel:
        def __init__(self) -> None:
            self.invoke_messages_seen: list[list[dict[str, object]]] = []
            self.invoke_model_specs_seen: list[dict[str, object]] = []

        async def astream_messages(self, _messages, **_kwargs):
            yield SimpleNamespace(content="你的任务")
            raise ModelRuntimeError(
                code="provider_unavailable",
                provider="test",
                model="stream",
                detail="provider stream disconnected",
                retryable=True,
                user_message="provider stream disconnected",
            )

        async def invoke_messages(self, messages, **_kwargs):
            self.invoke_messages_seen.append([dict(item) for item in list(messages or []) if isinstance(item, dict)])
            self.invoke_model_specs_seen.append(dict(_kwargs.get("model_spec") or {}))
            return SimpleNamespace(content="你的任务已经继续完成。")

    model = InterruptedStreamingModel()
    runtime = build_harness_runtime(
        base_dir=_runtime_test_root(tmp_path),
        model_runtime=model,
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-partial-stream-recovery",
                message="继续输出。",
                model_selection={
                    "stream_policy": {
                        "enabled": True,
                        "emit_assistant_text_delta": True,
                        "upstream_reconnect_enabled": True,
                        "partial_stream_recovery": "continue_from_visible_prefix",
                        "chunk_strategy": "typing",
                        "max_flush_interval_ms": 0,
                        "max_pending_utf8_bytes": 24,
                    }
                },
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    streamed_text = "".join(
        str(event.get("content") or "")
        for event in events
        if event.get("type") == "assistant_text_delta"
    )
    recovery_events = [dict(event) for event in events if event.get("type") == "stream_recovery"]
    done = dict(next(event for event in events if event.get("type") == "done"))
    recovery_prompt = "\n".join(
        str(message.get("content") or "")
        for message in model.invoke_messages_seen[-1]
    )

    assert streamed_text == "你的任务已经继续完成。"
    assert [event.get("status") for event in recovery_events] == ["started", "completed"]
    assert done["content"] == "你的任务已经继续完成。"
    assert "你的任务" in recovery_prompt
    assert "不要重复已经公开的文字" in recovery_prompt
    assert model.invoke_messages_seen[-1][-1]["role"] == "assistant"
    assert model.invoke_messages_seen[-1][-1]["content"] == "你的任务"
    assert model.invoke_messages_seen[-1][-1]["prefix"] is True
    assert model.invoke_model_specs_seen[-1]["completion_profile"] == {
        "mode": "chat_prefix",
        "provider_mode": "deepseek_chat_prefix",
        "source": "partial_stream_recovery",
    }


def test_single_agent_turn_falls_back_to_plain_continuation_when_prefix_recovery_fails(tmp_path: Path) -> None:
    from runtime.model_gateway.model_runtime import ModelRuntimeError

    class PrefixFailingStreamingModel:
        def __init__(self) -> None:
            self.invoke_messages_seen: list[list[dict[str, object]]] = []
            self.invoke_model_specs_seen: list[dict[str, object]] = []

        async def astream_messages(self, _messages, **_kwargs):
            yield SimpleNamespace(content="你的任务")
            raise ModelRuntimeError(
                code="provider_unavailable",
                provider="test",
                model="stream",
                detail="provider stream disconnected",
                retryable=True,
                user_message="provider stream disconnected",
            )

        async def invoke_messages(self, messages, **_kwargs):
            model_spec = dict(_kwargs.get("model_spec") or {})
            self.invoke_messages_seen.append([dict(item) for item in list(messages or []) if isinstance(item, dict)])
            self.invoke_model_specs_seen.append(model_spec)
            completion_profile = dict(model_spec.get("completion_profile") or {})
            if completion_profile.get("mode") == "chat_prefix":
                return {
                    "type": "error",
                    "code": "single_agent_turn_model_failed",
                    "reason": "prefix recovery failed",
                }
            return SimpleNamespace(content="你的任务已经继续完成。")

    model = PrefixFailingStreamingModel()
    runtime = build_harness_runtime(
        base_dir=_runtime_test_root(tmp_path),
        model_runtime=model,
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-partial-stream-recovery-plain-fallback",
                message="继续输出。",
                model_selection={
                    "stream_policy": {
                        "enabled": True,
                        "emit_assistant_text_delta": True,
                        "upstream_reconnect_enabled": True,
                        "partial_stream_recovery": "continue_from_visible_prefix",
                        "chunk_strategy": "typing",
                        "max_flush_interval_ms": 0,
                        "max_pending_utf8_bytes": 24,
                    }
                },
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    streamed_text = "".join(
        str(event.get("content") or "")
        for event in events
        if event.get("type") == "assistant_text_delta"
    )
    recovery_events = [dict(event) for event in events if event.get("type") == "stream_recovery"]
    done = dict(next(event for event in events if event.get("type") == "done"))

    assert streamed_text == "你的任务已经继续完成。"
    assert recovery_events[-1]["reason"] == "continued_from_visible_prefix"
    assert recovery_events[-1]["fallback_mode"] == "plain_continuation"
    assert done["content"] == "你的任务已经继续完成。"
    assert len(model.invoke_messages_seen) >= 3
    assert dict(model.invoke_model_specs_seen[0]["completion_profile"])["mode"] == "chat_prefix"
    assert dict(model.invoke_model_specs_seen[1]["completion_profile"])["mode"] == "chat_prefix"
    assert "completion_profile" not in model.invoke_model_specs_seen[-1]
    assert model.invoke_messages_seen[-1][-1]["role"] == "user"
    assert "不要重复已经公开的文字" in model.invoke_messages_seen[-1][-1]["content"]


def test_single_agent_turn_fails_when_partial_stream_recovery_call_fails(tmp_path: Path) -> None:
    from runtime.model_gateway.model_runtime import ModelRuntimeError

    class RecoveryFailingStreamingModel:
        async def astream_messages(self, _messages, **_kwargs):
            yield SimpleNamespace(content="已经公开的正文")
            raise ModelRuntimeError(
                code="provider_unavailable",
                provider="test",
                model="stream",
                detail="provider stream disconnected",
                retryable=True,
                user_message="provider stream disconnected",
            )

        async def invoke_messages(self, _messages, **_kwargs):
            return {
                "type": "error",
                "code": "single_agent_turn_model_failed",
                "reason": "recovery provider unavailable",
            }

    runtime = build_harness_runtime(
        base_dir=_runtime_test_root(tmp_path),
        model_runtime=RecoveryFailingStreamingModel(),
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-partial-stream-recovery-fallback",
                message="继续输出。",
                model_selection={
                    "stream_policy": {
                        "enabled": True,
                        "emit_assistant_text_delta": True,
                        "upstream_reconnect_enabled": True,
                        "partial_stream_recovery": "continue_from_visible_prefix",
                        "partial_stream_recovery_attempts": 2,
                        "chunk_strategy": "typing",
                        "max_flush_interval_ms": 0,
                        "max_pending_utf8_bytes": 24,
                    }
                },
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    streamed_text = "".join(
        str(event.get("content") or "")
        for event in events
        if event.get("type") == "assistant_text_delta"
    )
    recovery_events = [dict(event) for event in events if event.get("type") == "stream_recovery"]
    error_events = [dict(event) for event in events if event.get("type") == "error"]
    done_events = [dict(event) for event in events if event.get("type") == "done"]

    assert streamed_text == "已经公开的正文"
    assert [event.get("status") for event in recovery_events] == ["started", "failed"]
    assert recovery_events[-1]["reason"] == "partial_stream_recovery_failed"
    assert recovery_events[-1]["recovery_call_status"] == "failed"
    assert error_events[-1]["code"] == "partial_stream_recovery_failed"
    assert error_events[-1]["content"] == "运行中断"
    assert all(event.get("content") != "已经公开的正文" for event in done_events)


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


def test_single_agent_turn_tool_iteration_budget_defaults_and_clamps_to_100(monkeypatch) -> None:
    import harness.loop.single_agent_turn as single_agent_turn_module

    monkeypatch.delenv("AGENT_SINGLE_TURN_TOOL_ITERATIONS", raising=False)
    assert single_agent_turn_module._configured_single_turn_tool_iterations() == 100

    monkeypatch.setenv("AGENT_SINGLE_TURN_TOOL_ITERATIONS", "250")
    assert single_agent_turn_module._configured_single_turn_tool_iterations() == 100

    monkeypatch.setenv("AGENT_SINGLE_TURN_TOOL_ITERATIONS", "0")
    assert single_agent_turn_module._configured_single_turn_tool_iterations() == 1


def test_single_agent_turn_tool_loop_hands_budget_closeout_to_agent_without_ninth_tool_call(tmp_path: Path, monkeypatch) -> None:
    import harness.loop.single_agent_turn as single_agent_turn_module

    monkeypatch.setattr(single_agent_turn_module, "_MAX_SINGLE_TURN_TOOL_ITERATIONS", 8)

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
                    _action_request(action_type="respond", final_answer="agent closeout final"),
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
    control_signal_event = next(event for event in events if event.get("type") == "turn_runtime_control_signal_observed")
    control_signal_payload = dict(dict(control_signal_event.get("event") or {}).get("payload") or {})
    control_signal = dict(control_signal_payload.get("runtime_control_signal") or {})
    signal_ref = str(control_signal.get("runtime_control_signal_ref") or "")
    control_refs = dict(dict(control_signal_event.get("event") or {}).get("refs") or {})
    turn_run_id = str(control_refs.get("turn_run_ref") or "")
    gateway_requested = _turn_runtime_gateway_signals(runtime, turn_run_id, "runtime_control_signal_published")
    gateway_observed = _turn_runtime_gateway_signals(runtime, turn_run_id, "runtime_control_signal_observed")
    stored_turn = runtime.single_agent_runtime_host.state_index.get_turn_run(turn_run_id)
    stored_diagnostics = dict(getattr(stored_turn, "diagnostics", {}) or {})

    assert model.calls == len(observations) + 1
    assert len(observations) == 8
    assert done["terminal_reason"] == "single_turn_tool_iteration_limit"
    assert done["answer_source"] == "harness.single_agent_turn.agent_closeout"
    assert done["completion_state"] == "tool_limit_agent_closeout"
    assert done["content"] == "agent closeout final"
    assert signal_ref
    assert dict(control_signal_event["event"]["refs"])["runtime_control_signal_ref"] == signal_ref
    assert [str(item.get("signal_id") or "") for item in gateway_requested] == [signal_ref]
    assert [str(item.get("signal_id") or "") for item in gateway_observed] == [signal_ref]
    assert dict(gateway_requested[0].get("payload") or {}).get("adapter") == "single_agent_turn_runtime_control_boundary"
    assert dict(gateway_requested[0].get("payload") or {}).get("signal_kind") == "tool_budget_exhausted"
    assert control_refs["runtime_gateway_observed_event_ref"] == gateway_observed[0]["_event_id"]
    assert "latest_runtime_control_signal" not in stored_diagnostics
    assert stored_diagnostics["latest_runtime_control_signal_ref"] == signal_ref
    assert stored_diagnostics["latest_runtime_control_signal_kind"] == "tool_budget_exhausted"
    assert runtime.single_agent_runtime_host.runtime_gateway.drain(
        turn_run_id,
        scope=RuntimeSignalScope(turn_run_id=turn_run_id),
        signal_types={"control.signal.requested"},
    ).pending_signals == ()
    assert model.closeout_accounting["source"] == "harness.single_agent_turn.agent_closeout"
    assert model.closeout_accounting["prompt_manifest"]["invocation_kind"] == "single_agent_turn_agent_authored_closeout"
    assert model.closeout_accounting["prompt_manifest"]["closeout_reason"] == "tool_budget_exhausted"
    assert model.closeout_accounting["prompt_manifest"]["closeout_phase"] == "tool_limit_tool_loop"
    assert model.closeout_messages[-1]["role"] == "system"
    closeout_content = str(model.closeout_messages[-1].get("content") or "")
    assert '"closeout_lifecycle"' in closeout_content
    assert '"lifecycle": "agent_authored_closeout"' in closeout_content
    assert '"cause": "tool_budget_exhausted"' in closeout_content
    assert '"phase": "tool_limit_tool_loop"' in closeout_content
    assert '"tool_channel": "closed"' in closeout_content
    assert '"allowed_actions": ["respond", "ask_user", "block"]' in closeout_content
    assert '"facts"' in closeout_content
    assert "runtime_control_signal" not in closeout_content
    assert signal_ref not in closeout_content
    assert '"max_tool_iterations": 8' in closeout_content
    assert '"tool_call_allowed": false' in closeout_content
    assert "你收到的是本轮收口生命周期 observation" in closeout_content
    assert "你必须只输出一个 JSON action 对象" in closeout_content
    assert "action_type 只能是 respond、ask_user 或 block" in closeout_content
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
    control_refs = dict(dict(control_signal.get("event") or {}).get("refs") or {})
    signal_payload = dict(dict(dict(control_signal.get("event") or {}).get("payload") or {}).get("runtime_control_signal") or {})
    signal_ref = str(signal_payload.get("runtime_control_signal_ref") or "")
    turn_run_id = str(control_refs.get("turn_run_ref") or "")
    gateway_requested = _turn_runtime_gateway_signals(runtime, turn_run_id, "runtime_control_signal_published")
    gateway_observed = _turn_runtime_gateway_signals(runtime, turn_run_id, "runtime_control_signal_observed")

    assert model.calls >= 3
    assert len(observations) >= 2
    assert all(item["status"] == "error" for item in observations[:2])
    control_payload = dict(dict(control_signal.get("event") or {}).get("payload") or {})
    assert dict(control_payload.get("runtime_control_signal") or {}).get("signal_kind") == "consecutive_tool_failures"
    assert [str(item.get("signal_id") or "") for item in gateway_requested] == [signal_ref]
    assert [str(item.get("signal_id") or "") for item in gateway_observed] == [signal_ref]
    assert dict(gateway_requested[0].get("payload") or {}).get("signal_kind") == "consecutive_tool_failures"
    assert runtime.single_agent_runtime_host.runtime_gateway.drain(
        turn_run_id,
        scope=RuntimeSignalScope(turn_run_id=turn_run_id),
        signal_types={"control.signal.requested"},
    ).pending_signals == ()
    assert done["terminal_reason"] == "single_turn_consecutive_tool_failures"
    assert done["answer_source"] == "harness.single_agent_turn.agent_closeout"
    assert done["content"] == "这两个文件都不存在，先停止继续读文件。"
    assert assistant_messages[-1]["content"] == "这两个文件都不存在，先停止继续读文件。"
    assert model.closeout_accounting["source"] == "harness.single_agent_turn.agent_closeout"
    assert model.closeout_accounting["prompt_manifest"]["invocation_kind"] == "single_agent_turn_agent_authored_closeout"


def test_single_agent_turn_agent_authored_closeout_does_not_stream_before_contract_validation(tmp_path: Path) -> None:
    class StreamingCloseoutFailureModel:
        def __init__(self) -> None:
            self.tool_calls = 0
            self.closeout_accounting: dict[str, object] = {}

        async def astream_messages_with_tools(self, _messages, tools, **_kwargs):
            self.tool_calls += 1
            del tools
            yield _NativeToolStreamChunk(
                "我先确认文件状态。",
                [
                    {
                        "id": f"call-read-{self.tool_calls}",
                        "name": "read_file",
                        "args": {"path": f"does-not-exist-{self.tool_calls}.txt"},
                    }
                ],
            )

        async def invoke_messages_with_tools(self, messages, tools, **kwargs):
            current = _NativeToolStreamChunk()
            async for chunk in self.astream_messages_with_tools(messages, tools, **kwargs):
                current = current + chunk
            return SimpleNamespace(content=current.content, tool_calls=current.tool_calls)

        async def astream_messages(self, _messages, **_kwargs):
            self.closeout_accounting = dict(_kwargs.get("accounting_context") or {})
            payload = json.dumps(
                _action_request(action_type="respond", final_answer="这两个文件都不存在，先停止继续读文件。"),
                ensure_ascii=False,
            )
            yield SimpleNamespace(content=payload[:80])
            yield SimpleNamespace(content=payload[80:])

        async def invoke_messages(self, messages, **kwargs):
            text = ""
            async for chunk in self.astream_messages(messages, **kwargs):
                text += str(getattr(chunk, "content", "") or "")
            return SimpleNamespace(content=text)

    model = StreamingCloseoutFailureModel()
    tool_base_dir = _project_backend_dir()
    runtime = build_harness_runtime(
        base_dir=_runtime_test_root(tmp_path),
        model_runtime=model,
        tool_runtime=_tool_runtime_for_names(tool_base_dir, {"read_file"}),
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-single-turn-streaming-closeout",
                message="连续检查两个文件。",
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
    streamed_text = "".join(str(event.get("content") or "") for event in events if event.get("type") == "assistant_text_delta")
    final_text = "".join(str(event.get("content") or "") for event in events if event.get("type") == "assistant_text_final")
    done = next(event for event in events if event.get("type") == "done")

    assert "这两个文件都不存在" not in streamed_text
    assert "先停止继续读文件" not in streamed_text
    assert "这两个文件都不存在，先停止继续读文件。" in final_text
    assert done["answer_source"] == "harness.single_agent_turn.agent_closeout"
    assert done["content"] == "这两个文件都不存在，先停止继续读文件。"
    assert model.closeout_accounting["source"] == "harness.single_agent_turn.agent_closeout"
    assert model.closeout_accounting["prompt_manifest"]["invocation_kind"] == "single_agent_turn_agent_authored_closeout"


def test_single_agent_turn_agent_closeout_rejects_plain_text_without_streaming_it(tmp_path: Path, monkeypatch) -> None:
    import harness.loop.single_agent_turn as single_agent_turn_module

    monkeypatch.setattr(single_agent_turn_module, "_MAX_SINGLE_TURN_TOOL_ITERATIONS", 1)

    class PlainTextCloseoutModel:
        def __init__(self) -> None:
            self.tool_calls = 0
            self.closeout_calls = 0

        async def astream_messages_with_tools(self, _messages, tools, **_kwargs):
            self.tool_calls += 1
            del tools
            yield _NativeToolStreamChunk(
                "我先确认文件状态。",
                [
                    {
                        "id": f"call-exists-{self.tool_calls}",
                        "name": "path_exists",
                        "args": {"path": "requirements.txt"},
                    }
                ],
            )

        async def invoke_messages_with_tools(self, messages, tools, **kwargs):
            current = _NativeToolStreamChunk()
            async for chunk in self.astream_messages_with_tools(messages, tools, **kwargs):
                current = current + chunk
            return SimpleNamespace(content=current.content, tool_calls=current.tool_calls)

        async def astream_messages(self, _messages, **_kwargs):
            self.closeout_calls += 1
            yield SimpleNamespace(content="这是一段没有结构化 action 的收口正文。")

        async def invoke_messages(self, messages, **kwargs):
            text = ""
            async for chunk in self.astream_messages(messages, **kwargs):
                text += str(getattr(chunk, "content", "") or "")
            return SimpleNamespace(content=text)

    model = PlainTextCloseoutModel()
    tool_base_dir = _project_backend_dir()
    runtime = build_harness_runtime(
        base_dir=_runtime_test_root(tmp_path),
        model_runtime=model,
        tool_runtime=_tool_runtime_for_names(tool_base_dir, {"path_exists"}),
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-single-turn-plain-closeout",
                message="反复检查文件。",
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
    streamed_text = "".join(str(event.get("content") or "") for event in events if event.get("type") == "assistant_text_delta")
    final_text = "".join(str(event.get("content") or "") for event in events if event.get("type") == "assistant_text_final")
    done = next(event for event in events if event.get("type") == "done")
    assistant_messages = [dict(item) for item in runtime.session_manager.messages if str(dict(item).get("role") or "") == "assistant"]

    assert model.closeout_calls == 2
    assert "没有结构化 action" not in streamed_text
    assert "没有结构化 action" not in final_text
    assert done["terminal_reason"] == "agent_contract_feedback_required"
    assert done["completion_state"] == "agent_contract_feedback_required"
    assert str(done.get("content") or "") == ""
    assert not assistant_messages
