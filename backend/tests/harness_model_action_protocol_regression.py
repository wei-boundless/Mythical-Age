from __future__ import annotations

import json
from types import SimpleNamespace

from tests.support.harness_runtime_facade_support import *
from harness.runtime.control_events import RuntimeSignalScope
from harness.loop.model_action_protocol import ModelActionRequest
from harness.loop.task_lifecycle import contract_from_action_request


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


def _agent_contract_feedback_payloads(events: list[dict[str, object]]) -> list[dict[str, object]]:
    payloads: list[dict[str, object]] = []
    for event in events:
        if event.get("type") != "agent_contract_feedback_required":
            continue
        feedback = dict(dict(event.get("event") or {}).get("payload") or {}).get("agent_contract_feedback")
        if isinstance(feedback, dict):
            payloads.append(feedback)
    return payloads


def test_json_request_task_run_normalizes_string_completion_criteria_without_character_splitting() -> None:
    contract, errors = contract_from_action_request(
        ModelActionRequest(
            request_id="model-action:json-task-string-criteria",
            turn_id="turn:json-task-string-criteria",
            action_type="request_task_run",
            task_run_contract_seed=_compact_task_start_intent({
                "user_visible_goal": "审查项目。",
                "task_run_goal": "逐模块审查项目。",
                "working_scope": {
                    "target_objects": ["后端核心模块", "前端核心模块"],
                    "known_constraints": ["输出书面审查报告"],
                },
                "completion_criteria": "后端核心模块审查完成；前端核心模块审查完成；生成书面报告。",
                "required_artifacts": {"artifact_kind": "markdown_document", "user_visible_name": "审查报告"},
            }),
        ),
        packet_ref="packet:test",
    )

    assert errors == []
    assert contract is not None
    assert contract.completion_criteria == ("后端核心模块审查完成", "前端核心模块审查完成", "生成书面报告。")
    assert contract.user_visible_goal == "逐模块审查项目。"
    assert contract.environment_contract["working_scope"]["target_objects"] == ["后端核心模块", "前端核心模块"]
    assert contract.feedback_contract["feedback_identity_binding"] == "active_turn_or_task_run_required"
    assert contract.acceptance_contract["completion_criteria"] == ["后端核心模块审查完成", "前端核心模块审查完成", "生成书面报告。"]


def test_json_request_task_run_normalizes_numbered_completion_criteria_without_character_splitting() -> None:
    contract, errors = contract_from_action_request(
        ModelActionRequest(
            request_id="model-action:json-task-string-criteria",
            turn_id="turn:json-task-string-criteria",
            action_type="request_task_run",
            task_run_contract_seed=_compact_task_start_intent({
                "user_visible_goal": "审查交互投影。",
                "task_run_goal": "验证 todo 投影和工具活动展示。",
                "working_scope": {
                    "target_objects": ["todo 投影", "工具活动展示"],
                    "known_constraints": ["只依据真实投影和工具观察判断"],
                },
                "completion_criteria": "1. todo 投影显示有效任务 2. 工具活动不展示低层噪声",
            }),
        ),
        packet_ref="rtpacket:json-task-string-criteria",
    )

    assert errors == []
    assert contract is not None
    assert contract.completion_criteria == ("todo 投影显示有效任务", "工具活动不展示低层噪声")
    assert contract.plan_contract["plan_status"] == "agent_managed"
    assert contract.acceptance_contract["evidence_refs_required"] is True


def test_request_task_run_accepts_compact_task_start_intent() -> None:
    contract, errors = contract_from_action_request(
        ModelActionRequest(
            request_id="model-action:compact-task-start",
            turn_id="turn:compact-task-start",
            action_type="request_task_run",
            task_run_contract_seed=_compact_task_start_intent({
                "user_visible_goal": "升级任务机制。",
                "task_run_goal": "落实任务机制主链路升级。",
                "success_definition": "Task 具备计划、反馈和验收边界。",
                "working_scope": {"target_objects": ["backend/harness/runtime"]},
                "completion_criteria": ["行为链路可解释", "反馈边界清晰"],
                "mode_payload": {"steps": ["收紧触发", "分层合同", "验证反馈"]},
            }),
        ),
        packet_ref="rtpacket:compact-task-start",
    )

    assert errors == []
    assert contract is not None
    assert contract.task_run_goal == "落实任务机制主链路升级。"
    assert contract.primary_work_mode_instance_id == "work-mode:plan:primary"
    assert contract.plan_contract["major_steps"] == ["收紧触发", "分层合同", "验证反馈"]
    assert contract.environment_contract["working_scope"]["target_objects"] == ["backend/harness/runtime"]
    assert contract.acceptance_contract["completion_criteria"] == ["行为链路可解释", "反馈边界清晰"]


def test_request_task_run_parser_rejects_incomplete_compact_task_start_intent_before_lifecycle() -> None:
    from harness.loop.model_action_protocol import model_action_request_from_payload

    action_request, diagnostics = model_action_request_from_payload(
        {
            "authority": "harness.loop.model_action_request",
            "action_type": "request_task_run",
            "task_run_contract_seed": {
                "working_scope": {"target_objects": ["backend"]},
            },
        },
        turn_id="turn:test:incomplete-task-contract",
        allowed_action_types=("request_task_run", "respond", "ask_user", "block"),
    )

    assert action_request is None
    errors = set(diagnostics["validation_errors"])
    assert "compact_task_start_intent.primary_mode_unsupported:" in errors
    assert "compact_task_start_intent.minimum_viable_next_step_required" in errors
    assert "compact_task_start_intent.acceptance_mode_required" in errors


def test_single_agent_action_schema_keeps_turn_first_task_upgrade_boundary() -> None:
    from harness.runtime.compiler import model_action_request_schema

    schema = model_action_request_schema("turn:test:large-review")
    turn_attention = dict(schema.get("turn_attention") or {})
    selection_rules = [str(item) for item in list(turn_attention.get("selection") or [])]
    intent_contract = dict(schema.get("request_task_run_intent_contract") or {})
    minimal_action = dict(intent_contract.get("minimal_action") or {})
    minimal_seed = dict(minimal_action.get("task_run_contract_seed") or {})

    assert "request_task_run" in list(schema.get("allowed_action_types") or [])
    assert any("tool_call" in rule and "tool_calls" in rule for rule in selection_rules)
    assert any("长任务资源" in rule and "request_task_run" in rule for rule in selection_rules)
    assert intent_contract["contract_shape"] == "compact_task_start_intent"
    assert minimal_seed["contract_shape"] == "compact_task_start_intent"
    assert "todo" not in set(intent_contract.get("primary_mode") or {})
    assert "payload" not in minimal_action


def test_single_agent_model_feedback_identity_is_unique_per_tool_iteration() -> None:
    from harness.loop.single_agent_turn import _model_public_feedback_identity

    first = _model_public_feedback_identity(
        packet_ref="rtpacket:turn:test:single_agent_turn:1",
        tool_iteration=0,
        tool_actions=[
            ModelActionRequest(
                request_id="model-action:turn:test:tool:1",
                turn_id="turn:test",
                action_type="tool_call",
                tool_call={"tool_name": "search_files", "args": {"query": "prompts"}},
            )
        ],
    )
    second = _model_public_feedback_identity(
        packet_ref="rtpacket:turn:test:single_agent_turn:1",
        tool_iteration=1,
        tool_actions=[
            ModelActionRequest(
                request_id="model-action:turn:test:tool:2",
                turn_id="turn:test",
                action_type="tool_call",
                tool_call={"tool_name": "list_dir", "args": {"path": "backend/prompt_library"}},
            )
        ],
    )

    assert first != second
    assert first == "model-action-feedback:model-action:turn:test:tool:1"
    assert second == "model-action-feedback:model-action:turn:test:tool:2"


def test_single_agent_tool_batch_timeout_overrides_inner_cancel_observation(monkeypatch) -> None:
    import asyncio

    import harness.loop.single_agent_turn as single_agent_turn
    from harness.loop.admission import AdmissionDecision
    from harness.loop.model_action_protocol import ModelActionRequest
    from harness.runtime import ToolBatchGroup
    from runtime.tool_runtime import ToolObservation

    async def _cancel_swallowing_tool(*_args, **_kwargs):
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            return ToolObservation(
                observation_id="toolobs:inner-cancel",
                invocation_id="toolinv:inner-cancel",
                caller_kind="agent_turn",
                caller_ref="turnrun:test",
                tool_name="terminal",
                operation_id="op.shell",
                status="error",
                text="inner swallowed cancellation",
            )

    monkeypatch.setattr(single_agent_turn, "_invoke_turn_tool_for_batch_row", _cancel_swallowing_tool)
    monkeypatch.setattr(single_agent_turn, "_tool_batch_group_timeout_seconds", lambda _runtime_assembly: 0.01)

    action_request = ModelActionRequest(
        request_id="model-action:timeout",
        turn_id="turn:timeout",
        action_type="tool_call",
        tool_call={"tool_name": "terminal", "name": "terminal", "id": "call-timeout", "args": {"command": "sleep"}},
    )
    admission = AdmissionDecision(
        admission_id="admission:timeout",
        action_request_ref=action_request.request_id,
        decision="allow",
    )

    observations = asyncio.run(
        single_agent_turn._execute_tool_batch_group(
            ToolBatchGroup(group_index=0, execution_class="exclusive", item_indexes=(0,), parallel=False),
            invocation_rows=[
                {
                    "action_request": action_request,
                    "admission": admission,
                    "action_permit": {"decision": "allow"},
                }
            ],
            runtime_host=SimpleNamespace(tool_authorization_index=SimpleNamespace(definitions_by_name={})),
            runtime_assembly={},
            turn_run=None,
            session_id="session-timeout",
            turn_id="turn:timeout",
            packet_ref="rtpacket:timeout",
            tool_plan=SimpleNamespace(plan_id="rttoolplan:timeout"),
        )
    )

    assert observations[0].status == "error"
    assert "tool_batch_group_timeout_after_0.01s" in observations[0].text
    assert observations[0].diagnostics["exception_type"] == "TimeoutError"
    assert "inner swallowed cancellation" not in observations[0].text


def test_request_task_run_requires_scope_but_defaults_runtime_execution_settings() -> None:
    contract, errors = contract_from_action_request(
        ModelActionRequest(
            request_id="model-action:legacy-task",
            turn_id="turn:legacy-task",
            action_type="request_task_run",
            task_run_contract_seed=_compact_task_start_intent({
                "user_visible_goal": "旧任务。",
                "task_run_goal": "旧任务。",
                "completion_criteria": ["完成"],
            }),
        ),
        packet_ref="rtpacket:legacy-task",
    )

    assert errors == []
    assert contract is not None
    assert "capability_intent_required_for_request_task_run" not in errors
    assert "skill_intent_required_for_request_task_run" not in errors
    assert "observation_contract.evidence_policy_required" not in errors


def test_request_task_run_accepts_minimal_contract_without_execution_settings() -> None:
    contract, errors = contract_from_action_request(
        ModelActionRequest(
            request_id="model-action:minimal-task",
            turn_id="turn:minimal-task",
            action_type="request_task_run",
            task_run_contract_seed=_compact_task_start_intent({
                "user_visible_goal": "修复任务启动问题。",
                "task_run_goal": "定位并修复 request_task_run 合同和提示问题。",
                "working_scope": {"target_objects": ["backend/harness/loop", "backend/harness/runtime"]},
                "completion_criteria": ["最小任务合同可启动", "相关回归测试通过"],
            }),
        ),
        packet_ref="rtpacket:minimal-task",
    )

    assert errors == []
    assert contract is not None
    assert contract.working_scope["target_objects"] == ["backend/harness/loop", "backend/harness/runtime"]
    payload = contract.to_dict()
    assert "capability_intent" not in payload
    assert "skill_intent" not in payload
    assert "observation_contract" not in payload


def test_native_request_task_run_accepts_canonical_control_signal() -> None:
    from types import SimpleNamespace

    from harness.loop.single_agent_turn import _single_agent_action_request_from_response

    parsed = _single_agent_action_request_from_response(
        SimpleNamespace(
            content="",
            tool_calls=[
                {
                    "id": "call:task-gap",
                    "name": "request_task_run",
                    "args": {
                        "primary_mode": "plan",
                        "task_shape": "standard",
                        "minimum_viable_next_step": "修复运行监控和日志分离。",
                        "working_scope": {"target_objects": ["runtime monitor"]},
                        "acceptance": {
                            "mode": "checkpoint",
                            "criteria": ["监控只读 canonical projection"],
                            "final_answer_requirements": [],
                        },
                        "mode_payload": {
                            "summary": "修复运行监控和日志分离。",
                            "steps": ["确认运行监控投影", "修复日志分离"],
                            "success_definition": "运行监控只读取 canonical projection。",
                            "notes": [],
                        },
                        "todo_tool_contract": {"todo_is_tool": True, "cursor_updates": []},
                        "public_progress_note": "我会进入持续任务来修复运行监控链路。",
                    },
                }
            ],
        ),
        request_id="model-response:test:native-task-gap",
        turn_id="turn:test:native-task-gap",
        packet_ref="packet:test:native-task-gap",
        iteration=1,
        allowed_action_types=("respond", "ask_user", "block", "request_task_run", "tool_call"),
        phase="tool_loop",
        allow_model_tool_calls=True,
    )

    assert parsed.error is None
    assert parsed.action_request is not None
    assert parsed.action_request.action_type == "request_task_run"
    assert parsed.action_request.public_progress_note == "我会进入持续任务来修复运行监控链路。"
    assert parsed.action_request.task_run_contract_seed["mode_payload"]["summary"] == "修复运行监控和日志分离。"
    assert "capability_intent" not in parsed.action_request.task_run_contract_seed
    assert "skill_intent" not in parsed.action_request.task_run_contract_seed
    assert "observation_contract" not in parsed.action_request.task_run_contract_seed
    assert parsed.action_request.diagnostics["origin_kind"] == "single_agent_turn_native_control_action"
    assert parsed.control_action is parsed.action_request


def test_native_request_task_run_rejects_execution_setting_fields() -> None:
    from types import SimpleNamespace

    from harness.loop.single_agent_turn import _single_agent_action_request_from_response

    parsed = _single_agent_action_request_from_response(
        SimpleNamespace(
            content="",
            tool_calls=[
                {
                    "id": "call:task-gap",
                    "name": "request_task_run",
                    "args": {
                        "primary_mode": "plan",
                        "task_shape": "standard",
                        "minimum_viable_next_step": "修复运行监控和日志分离。",
                        "working_scope": {"target_objects": ["runtime monitor"]},
                        "acceptance": {
                            "mode": "checkpoint",
                            "criteria": ["监控只读 canonical projection"],
                            "final_answer_requirements": [],
                        },
                        "mode_payload": {
                            "summary": "修复运行监控和日志分离。",
                            "steps": ["确认运行监控投影"],
                            "success_definition": "运行监控只读 canonical projection。",
                            "notes": [],
                        },
                        "todo_tool_contract": {"todo_is_tool": True, "cursor_updates": []},
                        "capability_intent": "file_work",
                    },
                }
            ],
        ),
        request_id="model-response:test:native-task-gap",
        turn_id="turn:test:native-task-gap",
        packet_ref="packet:test:native-task-gap",
        iteration=1,
        allowed_action_types=("respond", "ask_user", "block", "request_task_run", "tool_call"),
        phase="tool_loop",
        allow_model_tool_calls=True,
    )

    assert parsed.action_request is None
    assert parsed.error is not None
    assert parsed.error["code"] == "single_agent_turn_invalid_native_action"
    diagnostics = parsed.error["diagnostics"]
    native_errors = diagnostics["native_action_errors"]
    validation_errors = set(native_errors[0]["validation_errors"])
    assert "native_control_action_arg_not_allowed:capability_intent" in validation_errors
    assert "provider 参数 schema" in native_errors[0]["action_issue"]["repair_instruction"]


def test_legacy_native_task_run_request_alias_is_rejected_not_canonicalized() -> None:
    from types import SimpleNamespace

    from harness.loop.single_agent_turn import _single_agent_action_request_from_response

    parsed = _single_agent_action_request_from_response(
        SimpleNamespace(
            content="",
            tool_calls=[
                {
                    "id": "call:legacy-task-action",
                    "name": "task_run_request",
                    "args": {
                        "user_visible_goal": "修复运行监控。",
                        "task_run_goal": "修复运行监控和日志分离。",
                    },
                }
            ],
        ),
        request_id="model-response:test:legacy-native-task-action",
        turn_id="turn:test:legacy-native-task-action",
        packet_ref="packet:test:legacy-native-task-action",
        iteration=1,
        allowed_action_types=("respond", "ask_user", "block", "request_task_run", "tool_call"),
        phase="tool_loop",
        allow_model_tool_calls=True,
    )

    assert parsed.action_request is None
    assert parsed.error is not None
    native_errors = parsed.error["diagnostics"]["native_action_errors"]
    assert native_errors[0]["code"] == "action_object_required_for_control_action"
    assert native_errors[0]["action_issue"]["code"] == "action_object_required_for_control_action"
    assert native_errors[0]["action_issue"]["requested_action_type"] == "request_task_run"
    assert native_errors[0]["action_issue"]["requested_tool_name"] == "task_run_request"
    assert native_errors[0]["repair_contract"]["required_signal"] == "model_action_request"
    assert native_errors[0]["repair_contract"]["action_type"] == "request_task_run"


def test_legacy_control_alias_text_inside_command_transport_is_not_interpreted_as_control_action() -> None:
    from types import SimpleNamespace

    from harness.loop.single_agent_turn import _single_agent_action_request_from_response

    parsed = _single_agent_action_request_from_response(
        SimpleNamespace(
            content="",
            tool_calls=[
                {
                    "id": "call:legacy-command-action",
                    "name": "bash",
                    "args": {"command": "echo task_run_request"},
                }
            ],
        ),
        request_id="model-response:test:legacy-command-action",
        turn_id="turn:test:legacy-command-action",
        packet_ref="packet:test:legacy-command-action",
        iteration=1,
        allowed_action_types=("respond", "ask_user", "block", "request_task_run", "tool_call"),
        phase="tool_loop",
        allow_model_tool_calls=True,
    )

    assert parsed.error is None
    assert parsed.action_request is not None
    assert parsed.action_request.action_type == "tool_call"
    assert parsed.action_request.tool_call["tool_name"] == "bash"
    assert parsed.action_request.tool_call["args"] == {"command": "echo task_run_request"}
    assert parsed.control_action is None


def test_single_agent_native_provider_tools_exclude_model_actions() -> None:
    from harness.loop.single_agent_turn import _native_tools_for_packet

    bindings = _native_tools_for_packet(
        ("respond", "ask_user", "block", "request_task_run", "tool_call"),
        available_tools=(
            {"tool_name": "read_file", "description": "Read a file", "input_schema": {"type": "object"}},
            {"tool_name": "request_task_run", "description": "Start a task"},
            {"tool_name": "task_run_request", "description": "Legacy task action alias"},
            {"tool_name": "ask_user", "description": "Ask the user"},
            {"tool_name": "block", "description": "Block"},
            {"tool_name": "respond", "description": "Respond"},
        ),
    )

    names = [item["name"] for item in bindings]
    assert "read_file" in names
    assert "task_run_request" not in names
    assert names.count("request_task_run") == 1
    by_name = {item["name"]: item for item in bindings}
    assert by_name["read_file"].get("metadata", {}).get("tool_plane") != "model_control_action"
    assert by_name["request_task_run"]["metadata"]["tool_plane"] == "model_control_action"


def test_single_agent_parser_accepts_surrounding_text_json_action_when_unambiguous() -> None:
    from harness.loop.single_agent_turn import _single_agent_action_request_from_response

    parsed = _single_agent_action_request_from_response(
        SimpleNamespace(
            content=(
                "我先说明一下修复方向。\n"
                + json.dumps(
                    {
                        "authority": "harness.loop.model_action_request",
                        "action_type": "respond",
                        "final_answer": "已经完成。",
                    },
                    ensure_ascii=False,
                )
            ),
            tool_calls=[],
        ),
        request_id="model-response:test:surrounding-text-json",
        turn_id="turn:test:surrounding-text-json",
        packet_ref="packet:test:surrounding-text-json",
        iteration=1,
        allowed_action_types=("respond", "ask_user", "block"),
        phase="protocol_recovery",
        require_json_action=True,
        public_feedback_expected=True,
    )

    assert parsed.error is None
    assert parsed.action_request is not None
    assert parsed.action_request.action_type == "respond"
    assert parsed.action_request.final_answer == "已经完成。"
    assert parsed.action_request.diagnostics["origin_kind"] == "single_agent_turn_json_action"
    assert parsed.action_request.diagnostics["parse_transport"]["embedded_action_object"] is True
    assert parsed.assistant_final_text == ""


def test_single_agent_parser_executes_surrounding_text_request_task_run_action() -> None:
    from harness.loop.single_agent_turn import _single_agent_action_request_from_response

    action = {
        "authority": "harness.loop.model_action_request",
        "action_type": "request_task_run",
        "public_progress_note": "我已判断需要进入持续任务。",
        "task_run_contract_seed": _compact_task_start_intent({
            "user_visible_goal": "修复 agent 输出吞没问题。",
            "task_run_goal": "修复控制契约恢复链路。",
            "working_scope": {"target_objects": ["backend/harness/loop/single_agent_turn.py"]},
            "completion_criteria": ["恢复提示保留被拒绝 action", "TaskRun 可在重提后启动"],
        }),
    }
    parsed = _single_agent_action_request_from_response(
        SimpleNamespace(content="我已经掌握链路，现在发起持续任务。\n" + json.dumps(action, ensure_ascii=False)),
        request_id="model-response:test:surrounding-task-json",
        turn_id="turn:test:surrounding-task-json",
        packet_ref="packet:test:surrounding-task-json",
        iteration=1,
        allowed_action_types=("respond", "ask_user", "block", "request_task_run", "tool_call"),
        phase="tool_loop",
        require_json_action=True,
    )

    assert parsed.error is None
    assert parsed.action_request is not None
    assert parsed.action_request.action_type == "request_task_run"
    assert parsed.action_request.task_run_contract_seed["mode_payload"]["summary"] == "修复控制契约恢复链路。"
    assert parsed.action_request.diagnostics["parse_transport"]["embedded_action_object"] is True
    assert parsed.control_action is parsed.action_request


def test_single_agent_parser_rejects_nested_respond_payload_final_answer() -> None:
    from types import SimpleNamespace

    from harness.loop.single_agent_turn import _single_agent_action_request_from_response

    parsed = _single_agent_action_request_from_response(
        SimpleNamespace(
            content=json.dumps(
                {
                    "authority": "harness.loop.model_action_request",
                    "action_type": "respond",
                    "payload": {"final_answer": "OCR 已提取题目，答案是 C。"},
                },
                ensure_ascii=False,
            ),
            tool_calls=[],
        ),
        request_id="model-response:test:nested-respond",
        turn_id="turn:test:nested-respond",
        packet_ref="packet:test:nested-respond",
        iteration=1,
        allowed_action_types=("respond", "ask_user", "block"),
        phase="tool_loop",
        require_json_action=True,
        public_feedback_expected=True,
    )

    assert parsed.action_request is None
    assert parsed.error is not None
    assert parsed.error["code"] == "single_agent_turn_invalid_json_action"
    validation_errors = parsed.error["diagnostics"]["model_action_diagnostics"]["validation_errors"]
    assert "final_answer_required_for_respond" in validation_errors


def test_single_agent_parser_rejects_nested_content_and_question_envelopes() -> None:
    from types import SimpleNamespace

    from harness.loop.single_agent_turn import _single_agent_action_request_from_response

    respond = _single_agent_action_request_from_response(
        SimpleNamespace(
            content=json.dumps(
                {
                    "authority": "harness.loop.model_action_request",
                    "action_type": "respond",
                    "payload": {"content": "这是可直接发布的回答。"},
                },
                ensure_ascii=False,
            ),
            tool_calls=[],
        ),
        request_id="model-response:test:nested-content",
        turn_id="turn:test:nested-content",
        packet_ref="packet:test:nested-content",
        iteration=1,
        allowed_action_types=("respond", "ask_user", "block"),
        phase="tool_loop",
        require_json_action=True,
        public_feedback_expected=True,
    )
    ask = _single_agent_action_request_from_response(
        SimpleNamespace(
            content=json.dumps(
                {
                    "authority": "harness.loop.model_action_request",
                    "action_type": "ask_user",
                    "action": {"question": "请补充第 8 题的完整选项。"},
                },
                ensure_ascii=False,
            ),
            tool_calls=[],
        ),
        request_id="model-response:test:nested-question",
        turn_id="turn:test:nested-question",
        packet_ref="packet:test:nested-question",
        iteration=1,
        allowed_action_types=("respond", "ask_user", "block"),
        phase="tool_loop",
        require_json_action=True,
        public_feedback_expected=True,
    )

    assert respond.action_request is None
    assert respond.error is not None
    assert respond.error["code"] == "single_agent_turn_invalid_json_action"
    respond_errors = respond.error["diagnostics"]["model_action_diagnostics"]["validation_errors"]
    assert "final_answer_required_for_respond" in respond_errors

    assert ask.action_request is None
    assert ask.error is not None
    assert ask.error["code"] == "single_agent_turn_invalid_json_action"
    ask_errors = ask.error["diagnostics"]["model_action_diagnostics"]["validation_errors"]
    assert "user_question_required_for_ask_user" in ask_errors


def test_single_agent_parser_accepts_plain_assistant_text_when_no_action_is_present() -> None:
    from types import SimpleNamespace

    from harness.loop.single_agent_turn import _single_agent_action_request_from_response

    parsed = _single_agent_action_request_from_response(
        SimpleNamespace(
            content=(
                "现在我看到了题目，这是一道无线通信中平衰落信道容量计算的经典题。\n\n"
                "结论：容量按给定信噪比代入香农公式计算。"
            ),
            tool_calls=[],
        ),
        request_id="model-response:test:plain-assistant-final",
        turn_id="turn:test:plain-assistant-final",
        packet_ref="packet:test:plain-assistant-final",
        iteration=1,
        allowed_action_types=("respond", "ask_user", "block", "request_task_run", "tool_call"),
        phase="tool_loop",
        require_json_action=False,
        public_feedback_expected=True,
    )

    assert parsed.error is None
    assert parsed.action_request is None
    assert parsed.tool_actions == ()
    assert parsed.assistant_final_text.startswith("现在我看到了题目")


def test_single_agent_parser_rejects_plain_assistant_text_when_action_transport_is_required() -> None:
    from harness.loop.single_agent_turn import _single_agent_action_request_from_response

    parsed = _single_agent_action_request_from_response(
        SimpleNamespace(
            content=(
                "现在所有线索都串起来了。真正根因是工具观察后已经足够形成诊断，"
                "所以我直接给出结论和下一步修复方向。"
            ),
            tool_calls=[],
        ),
        request_id="model-response:test:plain-assistant-final-json-requested",
        turn_id="turn:test:plain-assistant-final-json-requested",
        packet_ref="packet:test:plain-assistant-final-json-requested",
        iteration=2,
        allowed_action_types=("respond", "ask_user", "block", "request_task_run", "tool_call"),
        phase="tool_loop",
        require_json_action=True,
        public_feedback_expected=False,
    )

    assert parsed.error is not None
    assert parsed.error["code"] == "single_agent_turn_direct_visible_text_not_allowed"
    assert "respond.final_answer" in parsed.error["diagnostics"]["action_issue"]["repair_instruction"]
    assert parsed.action_request is None
    assert parsed.tool_actions == ()
    assert parsed.assistant_final_text == ""


def test_request_task_run_misnested_contract_fields_get_specific_runtime_repair_signal() -> None:
    from harness.loop.single_agent_turn import (
        _model_protocol_violation_control_signal,
        _single_agent_action_request_from_response,
    )

    invalid_action = {
        "authority": "harness.loop.model_action_request",
        "action_type": "request_task_run",
        "public_progress_note": "范围已经明确，我会进入持续任务完成审查。",
        "public_action_state": {
            "current_judgment": "这是跨多文件审查，需要持续任务。",
            "next_action": "进入持续任务执行流程。",
        },
        "working_scope": {"target_objects": ["backend/prompt_library"]},
        "task_run_contract_seed": {
            "user_visible_goal": "完整审查 prompts 体系。",
            "task_run_goal": "读取 prompts 体系全部相关文件并输出报告。",
            "working_scope": {"target_objects": ["backend/prompt_library", "backend/harness/runtime/compiler.py"]},
            "completion_criteria": ["读取证据", "输出报告"],
        },
    }

    parsed = _single_agent_action_request_from_response(
        SimpleNamespace(content=json.dumps(invalid_action, ensure_ascii=False)),
        request_id="model-response:test:misnested-task-contract",
        turn_id="turn:test:misnested-task-contract",
        packet_ref="packet:test:misnested-task-contract",
        iteration=1,
        allowed_action_types=("respond", "ask_user", "block", "request_task_run", "tool_call"),
        phase="tool_loop",
    )

    assert parsed.action_request is None
    assert parsed.error is not None
    assert parsed.error["code"] == "single_agent_turn_invalid_json_action"
    action_issue = dict(parsed.error["diagnostics"]["action_issue"])
    assert action_issue["requested_action_type"] == "request_task_run"
    assert "放错层级" in action_issue["repair_instruction"]
    assert "task_run_contract_seed 内" in action_issue["repair_instruction"]
    assert "不要使用 payload" in action_issue["repair_instruction"]

    signal = _model_protocol_violation_control_signal(
        turn_id="turn:test:misnested-task-contract",
        packet_ref="packet:test:misnested-task-contract",
        phase="tool_loop",
        protocol_error=parsed.error,
        allowed_action_types=("respond", "ask_user", "block", "request_task_run", "tool_call"),
        recovery_attempt=1,
        max_recovery_attempts=3,
        response_preview=json.dumps(invalid_action, ensure_ascii=False),
    )

    assert "具体修复" in signal["repair_instruction"]
    assert "放错层级" in signal["repair_instruction"]
    assert signal["structured_signal"]["message"] == signal["repair_instruction"]
    repair_example = dict(signal["structured_signal"]["repair_example"])
    repair_seed = dict(repair_example["task_run_contract_seed"])
    assert repair_example["action_type"] == "request_task_run"
    assert "capability_intent" not in repair_seed
    assert "skill_intent" not in repair_seed
    assert "observation_contract" not in repair_seed


def test_agent_contract_feedback_lifecycle_uses_specific_command_transport_control_repair_instruction() -> None:
    from harness.loop.single_agent_turn import _agent_contract_feedback_required_lifecycle

    feedback = _agent_contract_feedback_required_lifecycle(
        reason="protocol_recovery_exhausted",
        phase="tool_loop",
        turn_id="turn:test:native-control-feedback",
        packet_ref="packet:test:native-control-feedback",
        protocol_error={
            "code": "single_agent_turn_invalid_native_action",
            "reason": "native_control_action_command_transport_not_allowed",
            "diagnostics": {
                "native_action_errors": [
                    {
                        "code": "native_control_action_command_transport_not_allowed",
                        "reason": "native_control_action_command_transport_not_allowed",
                        "action_issue": {
                            "category": "protocol_violation",
                            "code": "control_action_command_transport_not_allowed",
                            "requested_action_type": "ask_user",
                            "requested_tool_name": "bash",
                            "repair_instruction": "命令文本不能伪装成控制动作；请提交 canonical structured action。",
                        },
                    },
                ],
            },
        },
    )

    feedback_text = str(feedback["agent_feedback"])
    specific = dict(feedback["contract_failure"])["specific_feedback"]
    assert "上一条输出没有形成可执行的动作合同" in feedback_text
    assert "命令文本" in feedback_text
    assert "canonical structured action" in feedback_text
    assert specific[0]["code"] == "control_action_command_transport_not_allowed"
    assert specific[0]["situation_feedback"] == "上一条输出不能进入执行或发布。"
    assert specific[0]["repair_instruction"] == "命令文本不能伪装成控制动作；请提交 canonical structured action。"
    assert specific[0]["expected_next_action"] == "不要重复提交 bash；按当前允许动作给出下一步。"


def test_agent_contract_feedback_lifecycle_separates_json_and_empty_respond_failures() -> None:
    from harness.loop.single_agent_turn import _agent_contract_feedback_required_lifecycle

    json_feedback = _agent_contract_feedback_required_lifecycle(
        reason="protocol_recovery_exhausted",
        phase="protocol_recovery",
        turn_id="turn:test:json-feedback",
        packet_ref="packet:test:json-feedback",
        protocol_error={
            "code": "single_agent_turn_json_action_required",
            "reason": "json_action_required",
            "diagnostics": {
                "action_issue": {
                    "category": "protocol_violation",
                    "code": "json_action_required",
                },
            },
        },
    )
    empty_respond_feedback = _agent_contract_feedback_required_lifecycle(
        reason="protocol_recovery_exhausted",
        phase="final_output_commit",
        turn_id="turn:test:empty-respond-feedback",
        packet_ref="packet:test:empty-respond-feedback",
        protocol_error={
            "code": "final_answer_required_for_respond",
            "reason": "final_answer_required_for_respond",
            "diagnostics": {
                "action_issue": {
                    "category": "protocol_violation",
                    "code": "final_answer_required_for_respond",
                    "requested_action_type": "respond",
                },
            },
        },
    )

    json_specific = dict(json_feedback["contract_failure"])["specific_feedback"][0]
    empty_specific = dict(empty_respond_feedback["contract_failure"])["specific_feedback"][0]

    assert "结构化动作" in json_specific["situation_feedback"]
    assert "结构化动作" in json_specific["repair_instruction"]
    assert "respond、ask_user 或 block" in json_specific["expected_next_action"]
    assert "只看到状态或记录" in empty_specific["situation_feedback"]
    assert "final_answer" in empty_specific["repair_instruction"]
    assert "能直接给用户看的 final_answer" in empty_specific["expected_next_action"]
    assert json_specific["situation_feedback"] != empty_specific["situation_feedback"]


def test_agent_contract_feedback_lifecycle_describes_tool_budget_exhaustion() -> None:
    from harness.loop.single_agent_turn import _agent_contract_feedback_required_lifecycle

    feedback = _agent_contract_feedback_required_lifecycle(
        reason="tool_budget_exhausted",
        phase="tool_limit_tool_loop",
        turn_id="turn:test:tool-budget-feedback",
        packet_ref="packet:test:tool-budget-feedback",
        control_signal={
            "signal_kind": "tool_budget_exhausted",
            "used_tool_iterations": 16,
            "max_tool_iterations": 16,
            "attempted_actions_not_executed": [
                {
                    "action_type": "tool_call",
                    "tool_call": {
                        "tool_name": "read_file",
                        "args": {"path": "backend/evidence/orchestrator.py"},
                    },
                }
            ],
        },
        previous_invalid_response="<tool_call read_file>",
    )

    feedback_text = str(feedback["agent_feedback"])
    specific = dict(feedback["contract_failure"])["specific_feedback"]
    tool_budget = next(item for item in specific if item["code"] == "tool_budget_exhausted")

    assert "工具预算" in feedback_text
    assert "16/16" in tool_budget["situation_feedback"]
    assert "read_file(backend/evidence/orchestrator.py)" in tool_budget["situation_feedback"]
    assert "用你自己的判断收口" in tool_budget["repair_instruction"]
    assert "respond.final_answer" in tool_budget["expected_next_action"]


def test_agent_contract_feedback_lifecycle_gives_natural_internal_leak_feedback() -> None:
    from harness.loop.single_agent_turn import _agent_contract_feedback_required_lifecycle

    feedback = _agent_contract_feedback_required_lifecycle(
        reason="session_output_commit_not_committed",
        phase="final_output_commit",
        turn_id="turn:test:commit-feedback",
        packet_ref="packet:test:commit-feedback",
        control_signal={
            "signal_kind": "final_output_not_committable",
            "commit_reason": "canonical_answer_rejected",
            "answer_leak_flags": ["internal_protocol"],
        },
        previous_invalid_response="上一轮因为格式协议被系统拦截。",
    )

    feedback_text = str(feedback["agent_feedback"])
    specific = dict(feedback["contract_failure"])["specific_feedback"][0]

    assert "上一条输出没有形成可执行的动作合同" in feedback_text
    assert "不能复述给用户" in feedback_text
    assert "不能作为用户回复" in specific["situation_feedback"]
    assert "改写成你自己的自然回复" in specific["repair_instruction"]
    assert "只保留用户需要知道的事实" in specific["expected_next_action"]


def test_resume_task_recovery_misnested_handle_fields_get_specific_runtime_repair_signal() -> None:
    from harness.loop.single_agent_turn import (
        _model_protocol_violation_control_signal,
        _single_agent_action_request_from_response,
    )

    invalid_action = {
        "authority": "harness.loop.model_action_request",
        "action_type": "resume_task_recovery",
        "public_progress_note": "我会从原任务断点继续。",
        "public_action_state": {"current_judgment": "已确认需要恢复原任务。"},
        "task_run_id": "taskrun:turn:session-a:1:abc",
        "continuation_id": "cont:session-a:1:0",
    }

    parsed = _single_agent_action_request_from_response(
        SimpleNamespace(content=json.dumps(invalid_action, ensure_ascii=False)),
        request_id="model-response:test:misnested-recovery-resume",
        turn_id="turn:test:misnested-recovery-resume",
        packet_ref="packet:test:misnested-recovery-resume",
        iteration=1,
        allowed_action_types=("respond", "ask_user", "block", "resume_task_recovery"),
        phase="tool_loop",
    )

    assert parsed.action_request is None
    assert parsed.error is not None
    assert parsed.error["code"] == "single_agent_turn_invalid_json_action"
    action_issue = dict(parsed.error["diagnostics"]["action_issue"])
    assert action_issue["requested_action_type"] == "resume_task_recovery"
    assert "恢复句柄字段放错层级" in action_issue["repair_instruction"]
    assert "task_recovery_resume" in action_issue["repair_instruction"]
    assert "不要从旧消息文本猜测" in action_issue["repair_instruction"]

    signal = _model_protocol_violation_control_signal(
        turn_id="turn:test:misnested-recovery-resume",
        packet_ref="packet:test:misnested-recovery-resume",
        phase="tool_loop",
        protocol_error=parsed.error,
        allowed_action_types=("respond", "ask_user", "block", "resume_task_recovery"),
        recovery_attempt=1,
        max_recovery_attempts=3,
        response_preview=json.dumps(invalid_action, ensure_ascii=False),
    )

    assert "具体修复" in signal["repair_instruction"]
    assert "恢复句柄字段放错层级" in signal["repair_instruction"]
    assert signal["structured_signal"]["message"] == signal["repair_instruction"]


def test_single_agent_parser_accepts_markdown_fenced_json_action_when_unambiguous() -> None:
    from types import SimpleNamespace

    from harness.loop.single_agent_turn import _single_agent_action_request_from_response

    action = _action_request(
        action_type="request_task_run",
        task_run_contract_seed=_compact_task_start_intent(
            {
                "user_visible_goal": "修复运行监控。",
                "task_run_goal": "修复运行监控和日志分离。",
                "completion_criteria": ["监控只读 canonical projection"],
            },
            target_objects=["runtime monitor"],
            capability_groups=["file_work"],
        ),
    )
    parsed = _single_agent_action_request_from_response(
        SimpleNamespace(content="```json\n" + json.dumps(action, ensure_ascii=False) + "\n```"),
        request_id="model-response:test:fenced-json-action",
        turn_id="turn:test:fenced-json-action",
        packet_ref="packet:test:fenced-json-action",
        iteration=1,
        allowed_action_types=("respond", "ask_user", "block", "request_task_run", "tool_call"),
        phase="initial",
        require_json_action=True,
    )

    assert parsed.error is None
    assert parsed.action_request is not None
    assert parsed.action_request.action_type == "request_task_run"
    assert parsed.action_request.task_run_contract_seed["mode_payload"]["summary"] == "修复运行监控和日志分离。"
    assert parsed.action_request.diagnostics["parse_transport"]["markdown_fence"] is True


def test_single_agent_parser_accepts_surrounded_markdown_fenced_json_action_when_unambiguous() -> None:
    from types import SimpleNamespace

    from harness.loop.single_agent_turn import _single_agent_action_request_from_response

    action = _action_request(
        action_type="request_task_run",
        task_run_contract_seed=_compact_task_start_intent(
            {
                "user_visible_goal": "修复运行监控。",
                "task_run_goal": "修复运行监控和日志分离。",
                "completion_criteria": ["监控只读 canonical projection"],
            },
            target_objects=["runtime monitor"],
            capability_groups=["file_work"],
        ),
    )
    parsed = _single_agent_action_request_from_response(
        SimpleNamespace(content="我现在发起持续任务。\n```json\n" + json.dumps(action, ensure_ascii=False) + "\n```"),
        request_id="model-response:test:surrounded-fenced-json-action",
        turn_id="turn:test:surrounded-fenced-json-action",
        packet_ref="packet:test:surrounded-fenced-json-action",
        iteration=1,
        allowed_action_types=("respond", "ask_user", "block", "request_task_run", "tool_call"),
        phase="initial",
        require_json_action=True,
    )

    assert parsed.error is None
    assert parsed.action_request is not None
    assert parsed.action_request.action_type == "request_task_run"
    transport = parsed.action_request.diagnostics["parse_transport"]
    assert transport["embedded_action_object"] is True
    assert transport["markdown_fence"] is True


def test_single_agent_turn_consecutive_tool_failures_block_protocol_inside_agent_closeout(tmp_path: Path, monkeypatch) -> None:
    import harness.loop.single_agent_turn as single_agent_turn_module

    monkeypatch.setattr(single_agent_turn_module, "_CONSECUTIVE_TOOL_FAILURE_CLOSEOUT_THRESHOLD", 3)

    class ProtocolRespondLoopModel(NativeToolCallSequenceModelRuntimeStub):
        def __init__(self) -> None:
            super().__init__(
                [
                    {
                        "content": "我先检查文件是否存在，再判断下一步。",
                        "tool_calls": [
                            {"id": f"call-read-{index}", "name": "read_file", "args": {"path": "missing/tool-limit.txt"}},
                        ]
                    }
                    for index in range(1, 5)
                ]
            )
            self.plain_invocations = 0
            self.plain_accounting_contexts: list[dict[str, object]] = []

        async def invoke_messages(self, messages, **kwargs):
            del messages
            self.plain_invocations += 1
            self.plain_accounting_contexts.append(dict(kwargs.get("accounting_context") or {}))
            if self.plain_invocations >= 2:
                return SimpleNamespace(
                    content=json.dumps(
                        _action_request(
                            action_type="respond",
                            final_answer="我已经达到本轮工具边界。下一步应缩小搜索范围，或把这次检查升级为项目级任务继续。",
                        ),
                        ensure_ascii=False,
                    )
                )
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
        tool_runtime=_tool_runtime_for_names(_project_backend_dir(), {"read_file"}),
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(HarnessRuntimeRequest(session_id="session-tool-limit-protocol-respond", message="反复检查文件。")):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    done = next(event for event in events if event.get("type") == "done")
    assistant_messages = [dict(item) for item in runtime.session_manager.messages if str(dict(item).get("role") or "") == "assistant"]

    assert model.calls >= 3
    assert model.plain_invocations == 2
    assert all(dict(item).get("segment_plan") for item in model.plain_accounting_contexts)
    assert all(dict(dict(item).get("prompt_manifest") or {}).get("segment_plan_ref") for item in model.plain_accounting_contexts)
    assert done["answer_source"] == "harness.single_agent_turn.agent_closeout"
    assert done["answer_channel"] == "conversation"
    assert done["completion_state"] == "tool_failure_closeout"
    assert done["agent_closeout_attempt"] == 2
    assert "升级为项目级任务" in str(done.get("content") or "")
    assert assistant_messages
    assert assistant_messages[-1]["answer_source"] == "harness.single_agent_turn.agent_closeout"
    assert "DSML" not in str(assistant_messages[-1].get("content") or "")


def test_single_agent_turn_consecutive_tool_failure_noncompliant_closeout_records_contract_feedback_lifecycle(tmp_path: Path, monkeypatch) -> None:
    import harness.loop.single_agent_turn as single_agent_turn_module

    monkeypatch.setattr(single_agent_turn_module, "_CONSECUTIVE_TOOL_FAILURE_CLOSEOUT_THRESHOLD", 3)

    class NoncompliantCloseoutLoopModel(NativeToolCallSequenceModelRuntimeStub):
        def __init__(self) -> None:
            super().__init__(
                [
                    {
                        "content": "我继续检查文件状态。",
                        "tool_calls": [
                            {"id": f"call-read-{index}", "name": "read_file", "args": {"path": "missing/noncompliant-closeout.txt"}},
                        ],
                    }
                    for index in range(1, 5)
                ]
            )
            self.closeout_invocations = 0

        async def invoke_messages(self, messages, **_kwargs):
            self.closeout_invocations += 1
            self.seen_messages.append(list(messages or []))
            self.seen_accounting_contexts.append(dict(_kwargs.get("accounting_context") or {}))
            return SimpleNamespace(content=json.dumps({"authority": "bad"}, ensure_ascii=False))

    model = NoncompliantCloseoutLoopModel()
    runtime = build_harness_runtime(
        base_dir=_runtime_test_root(tmp_path),
        model_runtime=model,
        tool_runtime=_tool_runtime_for_names(_project_backend_dir(), {"read_file"}),
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(HarnessRuntimeRequest(session_id="session-tool-limit-noncompliant-closeout", message="反复检查文件。")):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    terminal = next(event for event in events if event.get("type") == "agent_turn_terminal")
    terminal_payload = dict(dict(terminal.get("event") or {}).get("payload") or {})
    control_signals = [
        dict(dict(event.get("event") or {}).get("payload") or {}).get("runtime_control_signal")
        for event in events
        if event.get("type") == "turn_runtime_control_signal_observed"
    ]
    feedback_payloads = _agent_contract_feedback_payloads(events)
    assistant_messages = [dict(item) for item in runtime.session_manager.messages if str(dict(item).get("role") or "") == "assistant"]

    assert model.calls >= 3
    assert model.closeout_invocations == 2
    assert any(dict(signal or {}).get("signal_kind") == "consecutive_tool_failures" for signal in control_signals)
    assert not any(dict(signal or {}).get("signal_kind") == "model_protocol_violation" for signal in control_signals)
    assert not any(event.get("type") == "error" for event in events)
    assert terminal_payload["terminal_reason"] == "agent_contract_feedback_required"
    assert terminal_payload["status"] == "failed"
    assert feedback_payloads
    feedback = feedback_payloads[-1]
    assert feedback["signal_kind"] == "agent_contract_feedback_required"
    assert "上一条输出没有形成可执行的动作合同" in str(feedback["agent_feedback"])
    assert "不能复述给用户" in str(feedback["agent_feedback"])
    specific = dict(feedback["contract_failure"])["specific_feedback"]
    assert any(
        item.get("code") == "consecutive_tool_failures"
        and "连续工具失败" in str(item.get("situation_feedback") or "")
        and "read_file" in str(item.get("situation_feedback") or "")
        for item in specific
    )
    closeout_prompt_text = "\n".join(
        str(message.get("content") or "")
        for batch in model.seen_messages
        for message in batch
        if isinstance(message, dict)
    )
    assert "current_stop_context" in closeout_prompt_text
    assert "tool_failure_closeout" in closeout_prompt_text
    assert "不要逐字泄露内部字段" in closeout_prompt_text
    assert "runtime_control_signal" not in closeout_prompt_text
    assert dict(feedback["observed_facts"])["failed_tool_observation_count"] >= 3
    assert not assistant_messages


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
    assert parsed.error["code"] == "single_agent_turn_unexecuted_tool_intent"
    assert parsed.error["reason"] == "tool_action_intent_not_executed"
    assert parsed.error["diagnostics"]["action_issue"]["category"] == "action_not_executed"
    assert parsed.error["diagnostics"]["action_issue"]["code"] == "tool_action_intent_not_in_current_connection"

def test_malformed_agent_action_request_recovers_through_agent_closeout_with_protocol_reason() -> None:
    class MalformedThenCloseoutRuntime:
        def __init__(self) -> None:
            self.invocations = 0

        async def invoke_messages(self, _messages, **_kwargs):
            self.invocations += 1
            if self.invocations >= 4:
                return SimpleNamespace(
                    content=json.dumps(
                        _action_request(
                            action_type="respond",
                            final_answer="我没有继续执行工具；这一步需要重新确认输入后再推进。",
                        ),
                        ensure_ascii=False,
                    )
                )
            return SimpleNamespace(content=json.dumps({"authority": "bad"}))

    model = MalformedThenCloseoutRuntime()
    runtime = build_harness_runtime(model_runtime=model)

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(HarnessRuntimeRequest(session_id="session-malformed", message="继续。")):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    assistant_messages = [dict(item) for item in runtime.session_manager.messages if str(dict(item).get("role") or "") == "assistant"]
    control_signals = [
        dict(dict(event.get("event") or {}).get("payload") or {}).get("runtime_control_signal")
        for event in events
        if event.get("type") == "turn_runtime_control_signal_observed"
    ]
    done = next(event for event in events if event.get("type") == "done")

    done_text = "\n".join(str(event.get("content") or "") for event in events if event.get("type") == "done")
    assert "重新确认输入" in done_text
    assert any(dict(signal or {}).get("signal_kind") == "model_protocol_violation" for signal in control_signals)
    assert done["terminal_reason"] == "single_agent_turn_invalid_json_action"
    assert done["answer_source"] == "harness.single_agent_turn.agent_closeout"
    assert done["answer_channel"] == "conversation"
    assert done["completion_state"] == "protocol_recovery_exhausted"
    assert assistant_messages
    assert assistant_messages[-1]["answer_source"] == "harness.single_agent_turn.agent_closeout"
    assert "重新确认输入" in str(assistant_messages[-1].get("content") or "")
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

def test_invalid_json_action_text_recovers_through_control_signal_without_leaking_protocol() -> None:
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
    control_signal_events = [event for event in events if event.get("type") == "turn_runtime_control_signal_observed"]
    control_signals = [
        dict(dict(event.get("event") or {}).get("payload") or {}).get("runtime_control_signal")
        for event in control_signal_events
    ]
    protocol_signal = next(
        dict(signal or {})
        for signal in control_signals
        if dict(signal or {}).get("signal_kind") == "model_protocol_violation"
    )
    protocol_event = next(
        event
        for event in control_signal_events
        if dict(dict(dict(event.get("event") or {}).get("payload") or {}).get("runtime_control_signal") or {}).get("runtime_control_signal_ref")
        == protocol_signal.get("runtime_control_signal_ref")
    )
    protocol_signal_ref = str(protocol_signal.get("runtime_control_signal_ref") or "")
    protocol_turn_run_id = str(dict(dict(protocol_event.get("event") or {}).get("refs") or {}).get("turn_run_ref") or "")
    gateway_requested = _turn_runtime_gateway_signals(runtime, protocol_turn_run_id, "runtime_control_signal_published")
    gateway_observed = _turn_runtime_gateway_signals(runtime, protocol_turn_run_id, "runtime_control_signal_observed")

    assert "bounded_observation" not in event_types
    assert any(dict(signal or {}).get("signal_kind") == "model_protocol_violation" for signal in control_signals)
    assert any(str(item.get("signal_id") or "") == protocol_signal_ref for item in gateway_requested)
    assert any(str(item.get("signal_id") or "") == protocol_signal_ref for item in gateway_observed)
    gateway_signal = next(item for item in gateway_requested if str(item.get("signal_id") or "") == protocol_signal_ref)
    assert dict(gateway_signal.get("payload") or {}).get("adapter") == "single_agent_turn_runtime_control_boundary"
    assert dict(gateway_signal.get("payload") or {}).get("signal_kind") == "model_protocol_violation"
    assert runtime.single_agent_runtime_host.runtime_gateway.drain(
        protocol_turn_run_id,
        scope=RuntimeSignalScope(turn_run_id=protocol_turn_run_id),
        signal_types={"control.signal.requested"},
    ).pending_signals == ()
    assert admissions
    assert any(event.get("type") == "done" and "协议修复后完成" in str(event.get("content") or "") for event in events)
    assert not any(event.get("type") == "done" and "harness.loop.model_action_request" in str(event.get("content") or "") for event in events)


def test_protocol_control_signal_respond_with_runtime_protocol_disclosure_is_not_committed() -> None:
    leaked_answer = (
        "没有真的断开。上一轮输出因为格式协议问题被系统拦截了——这是会话框架的刚性约束，不是服务崩溃或代码报错。\n\n"
        "你当前打开的 `mario.html` 已经有一些落地改动。"
    )

    class InvalidActionThenLeakyRepairRuntime:
        def __init__(self) -> None:
            self.invocation_count = 0

        async def invoke_messages(self, _messages, **_kwargs):
            self.invocation_count += 1
            if self.invocation_count == 1:
                return SimpleNamespace(content=json.dumps({"authority": "bad"}, ensure_ascii=False))
            return SimpleNamespace(
                content=json.dumps(
                    _action_request(action_type="respond", final_answer=leaked_answer),
                    ensure_ascii=False,
                )
            )

    session_id = "session-turn-protocol-repair-leak"
    runtime = build_harness_runtime(model_runtime=InvalidActionThenLeakyRepairRuntime())

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(HarnessRuntimeRequest(session_id=session_id, message="为什么你又断开了")):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    admissions = _admission_payloads(events)
    control_signals = [
        dict(dict(event.get("event") or {}).get("payload") or {}).get("runtime_control_signal")
        for event in events
        if event.get("type") == "turn_runtime_control_signal_observed"
    ]
    checked_events = [event for event in events if event.get("type") == "session_output_commit_checked"]
    skipped_events = [event for event in events if event.get("type") == "session_output_commit_skipped"]
    feedback_payloads = _agent_contract_feedback_payloads(events)
    messages = runtime.session_manager.load_session(session_id)
    terminal = next(event for event in events if event.get("type") == "agent_turn_terminal")
    terminal_payload = dict(dict(terminal.get("event") or {}).get("payload") or {})
    done_text = "\n".join(str(event.get("content") or "") for event in events if event.get("type") == "done")

    assert admissions
    assert any(
        dict(signal or {}).get("signal_kind") == "model_protocol_violation"
        and dict(dict(signal or {}).get("protocol_error") or {}).get("code") == "single_agent_turn_invalid_json_action"
        for signal in control_signals
    )
    assert any(dict(signal or {}).get("signal_kind") == "final_output_not_committable" for signal in control_signals)
    assert checked_events
    assert skipped_events
    assert terminal_payload["terminal_reason"] == "agent_contract_feedback_required"
    assert terminal_payload["status"] == "failed"
    assert not any(event.get("type") == "done" for event in events)
    assert feedback_payloads
    assert "内部字段或动作说明" in str(feedback_payloads[-1]["agent_feedback"])
    assert "改写成你自己的自然回复" in str(feedback_payloads[-1]["agent_feedback"])
    assert "格式协议问题被系统拦截" not in done_text
    assert not any(leaked_answer in str(message.get("content") or "") for message in messages)


def test_single_agent_turn_native_control_actions_recover_to_json_action() -> None:
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
        recovery_action=_action_request(
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
    control_signals = [
        dict(dict(event.get("event") or {}).get("payload") or {}).get("runtime_control_signal")
        for event in events
        if event.get("type") == "turn_runtime_control_signal_observed"
    ]

    assert len(admissions) == 1
    assert dict(admissions[0].get("admission") or {}).get("decision") == "allow"
    admitted_action = dict(admissions[0].get("model_action_request") or {})
    assert admitted_action.get("action_type") == "ask_user"
    assert any(
        dict(signal or {}).get("signal_kind") == "model_protocol_violation"
        and dict(dict(signal or {}).get("protocol_error") or {}).get("code") == "single_agent_turn_invalid_native_action"
        for signal in control_signals
    )
    assert not any(dict(payload.get("model_action_request") or {}).get("action_type") == "block" for payload in admissions)
    assert any(event.get("type") == "done" and "请补充目标平台" in str(event.get("content") or "") for event in events)

def test_single_agent_turn_native_control_actions_do_not_execute_original_when_recovery_fails() -> None:
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
    control_signals = [
        dict(dict(event.get("event") or {}).get("payload") or {}).get("runtime_control_signal")
        for event in events
        if event.get("type") == "turn_runtime_control_signal_observed"
    ]
    feedback_payloads = _agent_contract_feedback_payloads(events)
    terminal = next(event for event in events if event.get("type") == "agent_turn_terminal")
    terminal_payload = dict(dict(terminal.get("event") or {}).get("payload") or {})

    assert not _admission_payloads(events)
    assert not any(event.get("type") == "done" and "当前环境缺少必要授权" in str(event.get("content") or "") for event in events)
    assert any(dict(signal or {}).get("signal_kind") == "model_protocol_violation" for signal in control_signals)
    assert terminal_payload["terminal_reason"] == "agent_contract_feedback_required"
    assert terminal_payload["status"] == "failed"
    assert not any(event.get("type") == "done" for event in events)
    assert feedback_payloads
    feedback_text = str(feedback_payloads[-1]["agent_feedback"])
    assert "没有提交本阶段要求的结构化动作" in feedback_text
    assert "重新选择 respond、ask_user 或 block" in feedback_text
    assistant_messages = [dict(item) for item in runtime.session_manager.messages if str(dict(item).get("role") or "") == "assistant"]
    assert not assistant_messages

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

def test_task_model_action_request_accepts_final_answer_without_separate_progress_note() -> None:
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
        public_feedback_expected=True,
    )

    assert action is not None
    assert diagnostics["status"] == "accepted"
    assert diagnostics["contract_gaps"] == []
    assert action.final_answer == "已完成。"


def test_public_feedback_expected_records_tool_call_feedback_gap_without_rejecting_action() -> None:
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
        public_feedback_expected=True,
    )

    assert action is not None
    assert diagnostics["status"] == "accepted"
    assert diagnostics["contract_gaps"] == [
        "public_feedback_omitted_for_tool_call",
        "public_progress_note_missing_for_tool_call",
        "public_action_state_missing_for_tool_call",
    ]
    assert action.diagnostics["contract_gaps"] == diagnostics["contract_gaps"]


def test_internal_tool_call_can_keep_public_response_empty() -> None:
    from harness.loop.model_action_protocol import model_action_request_from_payload

    action, diagnostics = model_action_request_from_payload(
        {
            "authority": "harness.loop.model_action_request",
            "request_id": "model-action:test:internal-tool",
            "turn_id": "taskrun:test:internal-tool",
            "action_type": "tool_call",
            "tool_call": {"tool_name": "read_file", "args": {"path": "README.md"}},
        },
        turn_id="taskrun:test:internal-tool",
        require_public_progress_note=True,
        require_public_action_state=True,
        public_feedback_expected=False,
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
    assert action.tool_call["id"].startswith("toolcall:model-action:test:internal-tool:")


def test_tool_call_id_is_generated_during_action_normalization() -> None:
    from harness.loop.model_action_protocol import model_action_request_from_payload

    action, diagnostics = model_action_request_from_payload(
        {
            "authority": "harness.loop.model_action_request",
            "request_id": "model-action:test:generated-tool-id",
            "turn_id": "turn:test:generated-tool-id",
            "action_type": "tool_call",
            "tool_call": {"tool_name": "read_file", "args": {"path": "README.md"}},
        },
        turn_id="turn:test:generated-tool-id",
    )

    assert diagnostics["status"] == "accepted"
    assert action is not None
    assert action.tool_call["id"].startswith("toolcall:model-action:test:generated-tool-id:")
    assert action.tool_call["id"] != action.request_id


def test_single_agent_parser_allows_native_tool_call_without_model_preamble_as_diagnostic_gap() -> None:
    from types import SimpleNamespace

    from harness.loop.single_agent_turn import _single_agent_action_request_from_response

    parsed = _single_agent_action_request_from_response(
        SimpleNamespace(
            content="",
            tool_calls=[
                {"id": "call-read", "name": "read_file", "args": {"path": "README.md"}},
            ],
        ),
        request_id="model-response:test:native-tool-public-response",
        turn_id="turn:test:native-tool-public-response",
        packet_ref="packet:test:native-tool-public-response",
        iteration=1,
        allowed_action_types=("respond", "ask_user", "block", "tool_call"),
        phase="tool_loop",
        allow_model_tool_calls=True,
        public_feedback_expected=True,
    )

    assert parsed.error is None
    assert parsed.tool_actions
    action = parsed.tool_actions[0]
    assert action.action_type == "tool_call"
    assert action.tool_call["args"] == {"path": "README.md"}
    assert dict(action.diagnostics or {}).get("public_feedback_recommended") is True
    assert dict(action.diagnostics or {}).get("public_feedback_recommendation_source") == "tool_observation_feedback"
    assert "public_feedback_omitted_for_native_tool_call" in dict(action.diagnostics or {}).get("contract_gaps", [])


def test_single_agent_continues_corrected_tool_call_after_failed_tool_without_preamble(tmp_path: Path) -> None:
    model = NativeToolCallSequenceModelRuntimeStub(
        [
            {
                "content": "我先读取目标文件，确认当前结构。",
                "tool_calls": [
                    {
                        "id": "call-bad-read",
                        "name": "read_file",
                        "args": {"path": "backend/memory_system/runtime_supply.py", "limit": 120},
                    },
                ],
            },
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call-corrected-read",
                        "name": "read_file",
                        "args": {
                            "path": "backend/memory_system/runtime_supply.py",
                            "start_line": 1,
                            "line_count": 120,
                        },
                    },
                ],
            },
            {
                "content": json.dumps(
                    _action_request(action_type="respond", final_answer="已用正确窗口参数继续读取 runtime_supply.py。"),
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
        async for event in runtime.astream(HarnessRuntimeRequest(session_id="session-corrected-read-after-failure", message="继续审查记忆系统。")):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    observations = [dict(event.get("tool_observation") or {}) for event in events if event.get("type") == "tool_observation"]
    public_feedback_events = [
        dict(event)
        for event in events
        if event.get("type") == "assistant_public_feedback"
        and str(event.get("presentation_source") or "").startswith("model_action.")
    ]
    admissions = _admission_payloads(events)
    control_signals = [
        dict(dict(event.get("event") or {}).get("payload") or {}).get("runtime_control_signal")
        for event in events
        if event.get("type") == "turn_runtime_control_signal_observed"
    ]
    done = next(event for event in events if event.get("type") == "done")
    tool_admissions = [
        dict(item.get("model_action_request") or {})
        for item in admissions
        if dict(item.get("model_action_request") or {}).get("action_type") == "tool_call"
    ]

    assert [dict(item.get("tool_call") or {}).get("id") for item in tool_admissions] == [
        "call-bad-read",
        "call-corrected-read",
    ]
    assert len(observations) == 2
    assert observations[0]["status"] == "error"
    assert observations[1]["status"] == "ok"
    assert [item["public_progress_note"] for item in public_feedback_events] == ["我先读取目标文件，确认当前结构。"]
    assert "public_feedback_omitted_for_native_tool_call" in dict(
        tool_admissions[1].get("diagnostics") or {}
    ).get("contract_gaps", [])
    assert not any(dict(signal or {}).get("signal_kind") == "model_protocol_violation" for signal in control_signals)
    assert done["terminal_reason"] == "respond"
    assert "正确窗口参数" in str(done.get("content") or "")


def test_single_agent_parser_uses_native_tool_preamble_as_model_response() -> None:
    from types import SimpleNamespace

    from harness.loop.single_agent_turn import _single_agent_action_request_from_response

    parsed = _single_agent_action_request_from_response(
        SimpleNamespace(
            content="我先读取 README 来确认项目状态，再回答你的问题。",
            tool_calls=[
                {"id": "call-read", "name": "read_file", "args": {"path": "README.md"}},
            ],
        ),
        request_id="model-response:test:native-tool-preamble",
        turn_id="turn:test:native-tool-preamble",
        packet_ref="packet:test:native-tool-preamble",
        iteration=1,
        allowed_action_types=("respond", "ask_user", "block", "tool_call"),
        phase="tool_loop",
        allow_model_tool_calls=True,
        public_feedback_expected=True,
    )

    assert parsed.error is None
    assert parsed.tool_actions
    action = parsed.tool_actions[0]
    assert action.public_progress_note == "我先读取 README 来确认项目状态，再回答你的问题。"
    assert action.public_action_state["current_judgment"] == action.public_progress_note
    assert action.tool_call["args"] == {"path": "README.md"}

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
    assert payload["tool_calls"][0]["id"].startswith("toolcall:model-action:test:task-tool:")
    assert payload["tool_calls"][0]["id"] != payload["request_id"]
    assert "task_contract_seed" not in payload
    assert "completion_contract" not in payload
    assert "permission_request" not in payload
    assert "engagement_request" not in payload
    assert "active_work_control" not in payload
    assert "selected_skill_ids" not in payload


def test_active_work_control_request_rejects_intent_alias_and_requires_action() -> None:
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

    assert action is None
    assert diagnostics["status"] == "invalid"
    assert "active_work_action_required" in diagnostics["validation_errors"]


def test_active_work_control_request_rejects_action_alias() -> None:
    from harness.loop.model_action_protocol import model_action_request_from_payload

    action, diagnostics = model_action_request_from_payload(
        {
            "authority": "harness.loop.model_action_request",
            "request_id": "model-action:test:active-work-action-alias",
            "turn_id": "turn:test:active-work-action-alias",
            "action_type": "active_work_control",
            "public_progress_note": "我会继续当前工作。",
            "active_work_control": {
                "action": "continue",
                "relation_to_current_work": "current_work",
                "response": "好，我接着处理。",
            },
        },
        turn_id="turn:test:active-work-action-alias",
        allowed_action_types=("respond", "active_work_control"),
    )

    assert action is None
    assert diagnostics["status"] == "invalid"
    assert "active_work_action_not_allowed" in diagnostics["validation_errors"]


def test_active_work_control_request_accepts_canonical_action_field() -> None:
    from harness.loop.model_action_protocol import model_action_request_from_payload

    action, diagnostics = model_action_request_from_payload(
        {
            "authority": "harness.loop.model_action_request",
            "request_id": "model-action:test:active-work-action",
            "turn_id": "turn:test:active-work-action",
            "action_type": "active_work_control",
            "public_progress_note": "我会继续当前工作。",
            "active_work_control": {
                "action": "continue_active_work",
                "relation_to_current_work": "current_work",
                "response": "好，我接着处理。",
            },
        },
        turn_id="turn:test:active-work-action",
        allowed_action_types=("respond", "active_work_control"),
    )

    assert diagnostics["status"] == "accepted"
    assert action is not None
    assert action.action_type == "active_work_control"
    assert action.active_work_control["action"] == "continue_active_work"


def test_single_agent_parser_rejects_bare_active_work_control_payload() -> None:
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

    assert parsed.action_request is None
    assert parsed.error is not None
    assert parsed.error["code"] == "single_agent_turn_invalid_json_action"
    validation_errors = parsed.error["diagnostics"]["model_action_diagnostics"]["validation_errors"]
    assert "action_type_unsupported:" in validation_errors


def test_single_agent_parser_rejects_minimal_bare_active_work_control_payload() -> None:
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
        require_json_action=True,
    )

    assert parsed.action_request is None
    assert parsed.error is not None
    assert parsed.error["code"] == "single_agent_turn_invalid_json_action"
    validation_errors = parsed.error["diagnostics"]["model_action_diagnostics"]["validation_errors"]
    assert "action_type_unsupported:" in validation_errors


def test_single_agent_parser_requires_action_type_before_checking_active_work_allowed_actions() -> None:
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
    validation_errors = parsed.error["diagnostics"]["model_action_diagnostics"]["validation_errors"]
    assert "action_type_unsupported:" in validation_errors


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


def test_active_work_turn_decision_rejects_field_and_action_aliases() -> None:
    from harness.loop.active_work import active_work_turn_decision_from_payload

    field_alias_decision = active_work_turn_decision_from_payload(
        {
            "authority": "harness.loop.active_work_turn_decision",
            "intent": "continue_active_work",
            "relation_to_current_work": "current_work",
        }
    )
    action_alias_decision = active_work_turn_decision_from_payload(
        {
            "authority": "harness.loop.active_work_turn_decision",
            "action": "continue",
            "relation_to_current_work": "current_work",
        }
    )
    relation_alias_decision = active_work_turn_decision_from_payload(
        {
            "authority": "harness.loop.active_work_turn_decision",
            "action": "continue_active_work",
            "relation": "current_work",
        }
    )
    relation_value_alias_decision = active_work_turn_decision_from_payload(
        {
            "authority": "harness.loop.active_work_turn_decision",
            "action": "continue_active_work",
            "relation_to_current_work": "current",
        }
    )

    assert field_alias_decision.accepted is False
    assert field_alias_decision.denied_reason == "active_work_control_action_not_allowed"
    assert action_alias_decision.accepted is False
    assert action_alias_decision.denied_reason == "active_work_control_action_not_allowed"
    assert relation_alias_decision.accepted is False
    assert relation_alias_decision.denied_reason == "active_work_relation_ambiguous"
    assert relation_value_alias_decision.accepted is False
    assert relation_value_alias_decision.denied_reason == "active_work_relation_ambiguous"


def test_active_work_turn_decision_ignores_removed_payload_aliases() -> None:
    from harness.loop.active_work import active_work_turn_decision_from_payload

    decision = active_work_turn_decision_from_payload(
        {
            "authority": "harness.loop.active_work_turn_decision",
            "action": "continue_active_work",
            "relation_to_current_work": "current_work",
            "final_answer": "旧字段不应成为控制回应。",
            "routing_evidence": "旧字段不应成为证据。",
            "turn_kind": "question",
            "response_obligation": "none",
            "resume_strategy": "same_run_resume",
        }
    )

    assert decision.accepted is True
    assert decision.response == ""
    assert decision.evidence == ""
    assert decision.user_turn_kind == "ambiguous"
    assert decision.answer_obligation == "acknowledgement_only"
    assert decision.continuation_strategy == ""


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
