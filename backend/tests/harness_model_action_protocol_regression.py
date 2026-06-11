from __future__ import annotations

from tests.support.harness_runtime_facade_support import *
from harness.loop.model_action_protocol import ModelActionRequest
from harness.loop.single_agent_turn import _action_request_from_native_tool_calls
from harness.loop.task_lifecycle import contract_from_action_request


def test_native_request_task_run_normalizes_string_completion_criteria_without_character_splitting() -> None:
    action = _action_request_from_native_tool_calls(
        [
            {
                "id": "call:task",
                "name": "request_task_run",
                "args": {
                    "user_visible_goal": "审查项目。",
                    "task_run_goal": "逐模块审查项目。",
                    "completion_criteria": "后端核心模块审查完成；前端核心模块审查完成；生成书面报告。",
                    "required_artifacts": {"artifact_kind": "markdown_document", "user_visible_name": "审查报告"},
                },
            }
        ],
        turn_id="turn:test:native-task",
        packet_ref="packet:test",
    )

    assert action is not None
    assert action.public_progress_note == ""
    assert action.public_action_state.get("next_action") == ""
    seed = action.task_contract_seed
    assert seed["completion_criteria"] == ["后端核心模块审查完成", "前端核心模块审查完成", "生成书面报告。"]
    assert seed["required_artifacts"] == [{"artifact_kind": "markdown_document", "user_visible_name": "审查报告"}]
    assert action.completion_contract["completion_criteria"] == seed["completion_criteria"]


def test_json_request_task_run_normalizes_numbered_completion_criteria_without_character_splitting() -> None:
    contract, errors = contract_from_action_request(
        ModelActionRequest(
            request_id="model-action:json-task-string-criteria",
            turn_id="turn:json-task-string-criteria",
            action_type="request_task_run",
            task_contract_seed={
                "user_visible_goal": "审查交互投影。",
                "task_run_goal": "验证 todo 投影和工具活动展示。",
                "completion_criteria": "1. todo 投影显示有效任务 2. 工具活动不展示低层噪声",
            },
        ),
        packet_ref="rtpacket:json-task-string-criteria",
    )

    assert errors == []
    assert contract is not None
    assert contract.completion_criteria == ("todo 投影显示有效任务", "工具活动不展示低层噪声")


def test_single_agent_turn_tool_limit_blocks_protocol_inside_agent_closeout(tmp_path: Path) -> None:
    class ProtocolRespondLoopModel(NativeToolCallSequenceModelRuntimeStub):
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
            self.plain_invocations = 0

        async def invoke_messages(self, messages, **_kwargs):
            del messages
            self.plain_invocations += 1
            return SimpleNamespace(
                content=json.dumps(
                    _action_request(
                        action_type="respond",
                        final_answer='<｜｜DSML｜｜tool_calls><｜｜DSML｜｜invoke name="search_text"></｜｜DSML｜｜tool_calls>',
                    ),
                    ensure_ascii=False,
                )
            )

    model = ProtocolRespondLoopModel()
    runtime = build_harness_runtime(
        base_dir=_runtime_test_root(tmp_path),
        model_runtime=model,
        tool_runtime=_tool_runtime_for_names(_project_backend_dir(), {"path_exists"}),
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(HarnessRuntimeRequest(session_id="session-tool-limit-protocol-respond", message="反复检查文件。")):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    done = next(event for event in events if event.get("type") == "done")
    assistant_messages = [dict(item) for item in runtime.session_manager.messages if str(dict(item).get("role") or "") == "assistant"]

    assert model.calls == 9
    assert model.plain_invocations == 2
    assert done["answer_source"] == "harness.single_agent_turn.tool_limit_closeout"
    assert done["answer_channel"] == "runtime_control"
    assert done["answer_canonical_state"] == "progress_only"
    assert done["answer_persist_policy"] == "persist_debug_only"
    assert done["completion_state"] == "tool_limit_closeout_unsafe_content"
    assert str(done.get("content") or "") == ""
    assert assistant_messages
    assert "DSML" not in str(assistant_messages[-1].get("content") or "")
    assert "search_text" not in str(assistant_messages[-1].get("content") or "")
    assert "工具协议" not in str(assistant_messages[-1].get("content") or "")


def test_single_agent_parser_rejects_native_tool_call_when_json_action_required() -> None:
    from types import SimpleNamespace

    from harness.loop.single_agent_turn import _single_agent_action_request_from_response

    parsed = _single_agent_action_request_from_response(
        SimpleNamespace(
            content="",
            tool_calls=[
                {"id": "call-read", "name": "read_file", "args": {"path": "README.md"}},
            ],
        ),
        request_id="model-response:test:json-required-native-tool",
        turn_id="turn:test:json-required-native-tool",
        packet_ref="packet:test:json-required-native-tool",
        iteration=1,
        allowed_action_types=("respond", "ask_user", "block"),
        phase="tool_limit_closeout",
        require_json_action=True,
    )

    assert parsed.action_request is None
    assert parsed.error is not None
    assert parsed.error["code"] == "single_agent_turn_model_protocol_error"
    assert "native_tool_calls_not_allowed" in parsed.error["reason"]

def test_malformed_agent_action_request_fails_closed() -> None:
    runtime = build_harness_runtime(model_runtime=_MalformedModelRuntime())

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(HarnessRuntimeRequest(session_id="session-malformed", message="继续。")):
            events.append(event)
        return events

    events = asyncio.run(_collect())

    done_text = "\n".join(str(event.get("content") or "") for event in events if event.get("type") == "done")
    assert "已经停住" in done_text
    assert "模型" not in done_text
    assert "JSON" not in done_text
    assert "系统动作" not in done_text
    assert "协议" not in done_text
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

def test_model_action_request_accepts_public_progress_note() -> None:
    from harness.loop.model_action_protocol import model_action_request_from_payload

    action, diagnostics = model_action_request_from_payload(
        {
            "authority": "harness.loop.model_action_request",
            "request_id": "model-action:test:progress",
            "turn_id": "turn:test:1",
            "action_type": "respond",
            "public_progress_note": "正在整理当前回复。",
            "public_action_state": {
                "current_judgment": "当前信息足以直接回复。",
                "next_action": "整理回复。",
            },
            "final_answer": "这是当前回复。",
        },
        turn_id="turn:test:1",
    )

    assert diagnostics["status"] == "accepted"
    assert action is not None
    assert action.public_progress_note == "正在整理当前回复。"
    assert action.public_action_state["next_action"] == "整理回复。"

def test_task_model_action_request_requires_public_progress_note_for_public_response() -> None:
    from harness.loop.model_action_protocol import model_action_request_from_payload

    action, diagnostics = model_action_request_from_payload(
        {
            "authority": "harness.loop.model_action_request",
            "request_id": "model-action:test:missing-progress",
            "turn_id": "taskrun:test:progress-required",
            "action_type": "respond",
            "public_action_state": {"completion_status": "ready_to_finish"},
            "final_answer": "已完成。",
        },
        turn_id="taskrun:test:progress-required",
        require_public_progress_note=True,
    )

    assert action is None
    assert diagnostics["status"] == "invalid"
    assert "public_progress_note_required" in diagnostics["validation_errors"]

def test_task_model_action_request_does_not_require_public_text_for_tool_call() -> None:
    from harness.loop.model_action_protocol import model_action_request_from_payload

    action, diagnostics = model_action_request_from_payload(
        {
            "authority": "harness.loop.model_action_request",
            "request_id": "model-action:test:missing-report",
            "turn_id": "taskrun:test:progress-report-required",
            "action_type": "tool_call",
            "tool_call": {"tool_name": "read_file", "args": {"path": "README.md"}},
        },
        turn_id="taskrun:test:progress-report-required",
        require_public_progress_note=True,
        require_public_action_state=True,
    )

    assert action is not None
    assert diagnostics["status"] == "accepted"
    assert diagnostics["contract_gaps"] == [
        "public_progress_note_missing_for_tool_call",
        "public_action_state_missing_for_tool_call",
    ]
    assert action.public_progress_note == ""
    assert action.public_action_state == {}
    assert action.diagnostics["contract_gaps"] == diagnostics["contract_gaps"]

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
            "tool_calls": [{"tool_name": "read_file", "args": {"path": "README.md"}}],
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


def test_active_work_control_request_accepts_intent_alias() -> None:
    from harness.loop.model_action_protocol import model_action_request_from_payload

    action, diagnostics = model_action_request_from_payload(
        {
            "authority": "harness.loop.model_action_request",
            "request_id": "model-action:test:active-work-intent",
            "turn_id": "turn:test:active-work-intent",
            "action_type": "active_work_control",
            "public_progress_note": "我会继续当前工作。",
            "active_work_control": {
                "intent": "continue_active_work",
                "relation_to_current_work": "current_work",
                "response": "好，我接着处理。",
            },
        },
        turn_id="turn:test:active-work-intent",
        allowed_action_types=("respond", "active_work_control"),
    )

    assert diagnostics["status"] == "accepted"
    assert action is not None
    assert action.action_type == "active_work_control"
    assert action.active_work_control["intent"] == "continue_active_work"


def test_single_agent_parser_normalizes_bare_active_work_control_payload() -> None:
    from types import SimpleNamespace

    from harness.loop.single_agent_turn import _single_agent_action_request_from_response

    parsed = _single_agent_action_request_from_response(
        SimpleNamespace(
            content='{"action":"continue_active_work","relation_to_current_work":"current_work","response":"用户要求继续推进当前代码审查任务。"}'
        ),
        request_id="model-response:test:active-work-json",
        turn_id="turn:test:active-work-json",
        packet_ref="packet:test:active-work-json",
        iteration=1,
        allowed_action_types=("respond", "active_work_control"),
        phase="final",
        require_json_action=True,
    )

    assert parsed.error is None
    assert parsed.action_request is not None
    assert parsed.action_request.action_type == "active_work_control"
    assert parsed.action_request.active_work_control["action"] == "continue_active_work"
    assert parsed.action_request.active_work_control["relation_to_current_work"] == "current_work"
    assert parsed.action_request.diagnostics["origin_kind"] == "single_agent_turn_json_active_work_control_payload"


def test_single_agent_parser_normalizes_minimal_bare_active_work_control_payload() -> None:
    from types import SimpleNamespace

    from harness.loop.single_agent_turn import _single_agent_action_request_from_response

    parsed = _single_agent_action_request_from_response(
        SimpleNamespace(content='{"action":"continue_active_work"}'),
        request_id="model-response:test:minimal-active-work-json",
        turn_id="turn:test:minimal-active-work-json",
        packet_ref="packet:test:minimal-active-work-json",
        iteration=1,
        allowed_action_types=("respond", "active_work_control"),
        phase="final",
        require_json_action=False,
    )

    assert parsed.error is None
    assert parsed.action_request is not None
    assert parsed.action_request.action_type == "active_work_control"
    assert parsed.action_request.active_work_control["action"] == "continue_active_work"
    assert parsed.action_request.diagnostics["origin_kind"] == "single_agent_turn_json_active_work_control_payload"


def test_single_agent_parser_rejects_bare_active_work_control_when_not_allowed() -> None:
    from types import SimpleNamespace

    from harness.loop.single_agent_turn import _single_agent_action_request_from_response

    parsed = _single_agent_action_request_from_response(
        SimpleNamespace(
            content='{"action":"continue_active_work","relation_to_current_work":"current_work","response":"用户要求继续推进当前代码审查任务。"}'
        ),
        request_id="model-response:test:active-work-json-denied",
        turn_id="turn:test:active-work-json-denied",
        packet_ref="packet:test:active-work-json-denied",
        iteration=1,
        allowed_action_types=("respond",),
        phase="final",
        require_json_action=True,
    )

    assert parsed.action_request is None
    assert parsed.error is not None
    assert parsed.error["code"] == "single_agent_turn_invalid_json_action"
    assert "action_type_not_allowed_for_context:active_work_control" in parsed.error["reason"]


def test_active_work_turn_decision_preserves_control_only_reply_contract() -> None:
    from harness.loop.active_work import active_work_turn_decision_from_payload

    decision = active_work_turn_decision_from_payload(
        {
            "authority": "harness.loop.active_work_turn_decision",
            "action": "append_instruction_to_active_work",
            "relation_to_current_work": "current_work",
            "turn_response_policy": "active_work_only",
            "answer_obligation": "none",
            "user_turn_kind": "command",
            "appended_instruction": "contract update",
        }
    )

    assert decision.accepted is True
    assert decision.action == "append_instruction_to_active_work"
    assert decision.turn_response_policy == "active_work_only"
    assert decision.answer_obligation == "none"
    assert decision.appended_instruction == "contract update"


def test_active_work_turn_decision_maps_no_user_reply_to_no_answer_obligation() -> None:
    from harness.loop.active_work import active_work_turn_decision_from_payload

    decision = active_work_turn_decision_from_payload(
        {
            "authority": "harness.loop.active_work_turn_decision",
            "action": "continue_active_work",
            "relation_to_current_work": "current_work",
            "turn_response_policy": "no_user_reply",
            "user_turn_kind": "command",
        }
    )

    assert decision.accepted is True
    assert decision.action == "continue_active_work"
    assert decision.turn_response_policy == "no_user_reply"
    assert decision.answer_obligation == "none"


def test_active_work_control_followup_contract_keeps_steer_actions_running() -> None:
    from harness.loop.single_agent_turn import _active_work_control_requires_followup

    assert (
        _active_work_control_requires_followup(
            {
                "action": "continue_active_work",
                "turn_response_policy": "active_work_only",
                "answer_obligation": "none",
                "user_turn_kind": "command",
            },
            status="completed",
        )
        is True
    )
    assert (
        _active_work_control_requires_followup(
            {
                "action": "append_instruction_to_active_work",
                "turn_response_policy": "no_user_reply",
                "answer_obligation": "none",
                "user_turn_kind": "command",
            },
            status="completed",
        )
        is True
    )
    assert (
        _active_work_control_requires_followup(
            {
                "action": "continue_active_work",
                "turn_response_policy": "answer_then_active_work",
                "answer_obligation": "direct_answer_required",
                "user_turn_kind": "mixed",
            },
            status="completed",
        )
        is True
    )
    assert (
        _active_work_control_requires_followup(
            {
                "action": "continue_active_work",
                "turn_response_policy": "active_work_only",
                "answer_obligation": "none",
                "user_turn_kind": "command",
            },
            status="blocked",
        )
        is True
    )


def test_model_action_request_rejects_removed_registered_engagement_action() -> None:
    from harness.loop.model_action_protocol import model_action_request_from_payload

    action, diagnostics = model_action_request_from_payload(
        {
            "authority": "harness.loop.model_action_request",
            "request_id": "model-action:test:removed-engagement",
            "turn_id": "turn:test:removed-engagement",
            "action_type": "request_registered_engagement",
            "engagement_request": {"plan_id": "plan:test"},
        },
        turn_id="turn:test:removed-engagement",
        allowed_action_types=("respond", "request_task_run", "block"),
    )

    assert action is None
    assert diagnostics["status"] == "invalid"
    assert "action_type_unsupported:request_registered_engagement" in diagnostics["validation_errors"]


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
