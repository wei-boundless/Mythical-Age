from __future__ import annotations

from types import SimpleNamespace

from harness.loop.presentation import final_answer_event
from harness.loop.task_executor import _commit_task_run_final_message
from memory_system.continuity import MemoryMessageAdapter
from orchestration.commit_gate import build_assistant_session_message_commit_decision
from runtime.output_boundary import canonical_output_decision_for_final_text


def test_final_text_boundary_sanitizes_protocol_without_marking_stable_answer() -> None:
    decision = canonical_output_decision_for_final_text(
        '<tool_call name="read_file">{"path":"x"}</tool_call>\n结论：任务完成。',
        answer_channel="conversation",
        answer_source="test.final_text",
    )

    assert decision.canonical_state == "unstable_answer"
    assert decision.persist_policy == "persist_debug_only"
    assert "internal_protocol_final_text" in decision.leak_flags


def test_final_text_boundary_blocks_pure_protocol_fragment() -> None:
    decision = canonical_output_decision_for_final_text(
        '<｜｜DSML｜｜tool_calls><｜｜DSML｜｜invoke name="search_text"></｜｜DSML｜｜tool_calls>',
        answer_channel="conversation",
        answer_source="test.final_text",
    )

    assert decision.canonical_state == "missing_answer"
    assert decision.persist_policy == "do_not_persist"
    assert "internal_protocol_final_text" in decision.leak_flags


def test_final_text_boundary_blocks_active_work_control_json() -> None:
    decision = canonical_output_decision_for_final_text(
        '{"action":"continue_active_work","relation_to_current_work":"current_work","response":"用户要求继续推进当前代码审查任务，恢复执行逐模块深入审查并生成完整全新报告。"}',
        answer_channel="conversation",
        answer_source="test.final_text",
    )

    assert decision.canonical_state == "missing_answer"
    assert decision.persist_policy == "do_not_persist"
    assert "internal_protocol_final_text" in decision.leak_flags


def test_final_text_boundary_blocks_runtime_protocol_disclosure() -> None:
    decision = canonical_output_decision_for_final_text(
        (
            "没有真的断开。上一轮输出因为格式协议问题被系统拦截了——这是会话框架的刚性约束，不是服务崩溃或代码报错。\n\n"
            "你当前打开的 `mario.html` 已经有一些落地改动。"
        ),
        answer_channel="conversation",
        answer_source="test.final_text",
    )

    assert decision.canonical_state == "missing_answer"
    assert decision.persist_policy == "do_not_persist"
    assert "runtime_protocol_disclosure_final_text" in decision.leak_flags
    assert "internal_protocol_final_text" in decision.leak_flags


def test_commit_gate_blocks_answer_with_leak_flags_even_if_marked_stable() -> None:
    decision = build_assistant_session_message_commit_decision(
        session_id="session:test",
        task_run_id="",
        task_id="",
        turn_id="turn:session:test:1",
        content="用户可见文本。",
        answer_channel="conversation",
        answer_source="test",
        answer_canonical_state="stable_answer",
        answer_persist_policy="persist_canonical",
        answer_leak_flags=["runtime_protocol_disclosure_final_text"],
    )

    assert decision.commit_allowed is False
    assert decision.reason == "answer_leak_not_committable"
    assert decision.commit_candidate.payload["answer_leak_flags"] == ["runtime_protocol_disclosure_final_text"]
    assert decision.diagnostics["answer_leak_blocked"] is True


def test_task_control_text_is_debug_only_not_canonical_memory() -> None:
    decision = canonical_output_decision_for_final_text(
        "我会按这个目标推进：修复文件管理。",
        answer_channel="task_control",
        answer_source="test.task_control",
    )

    assert decision.answer_channel == "task_control"
    assert decision.canonical_state == "progress_only"
    assert decision.persist_policy == "persist_debug_only"


def test_final_text_boundary_sanitizes_fragmented_ascii_dsml_parameters() -> None:
    decision = canonical_output_decision_for_final_text(
        (
            "理解了。我已经读完所有源文件，现在需要进入持续处理流程。\n"
            'name="completion_criteria" string="true">1. 创建独立目录 2. 复制素材</ | | DSML | | parameter> '
            'name="task_run_goal" string="true">将游戏提取为独立静态页面</ | | DSML | | parameter> '
            'name="user_visible_goal" string="true">创建独立 HTML 页面</ | | DSML | | parameter>'
        ),
        answer_channel="conversation",
        answer_source="test.final_text",
    )

    assert "internal_protocol_final_text" in decision.leak_flags


def test_final_answer_event_does_not_promote_procedural_promise() -> None:
    event = final_answer_event(
        content="我会先检查文件。",
        answer_source="test.presentation",
    )

    assert event["answer_canonical_state"] == "progress_only"
    assert event["answer_persist_policy"] == "persist_debug_only"
    assert event["answer_fallback_reason"] == "no_receipt_tool_claim"


def test_memory_adapter_keeps_only_canonical_assistant_answers() -> None:
    adapter = MemoryMessageAdapter()

    messages = adapter.to_messages(
        [
            {
                "role": "assistant",
                "content": "稳定结论。",
                "answer_canonical_state": "stable_answer",
                "answer_persist_policy": "persist_canonical",
            },
            {
                "role": "assistant",
                "content": "我会继续处理。",
                "answer_canonical_state": "progress_only",
                "answer_persist_policy": "persist_debug_only",
            },
            {
                "role": "assistant",
                "content": "",
                "answer_canonical_state": "missing_answer",
                "answer_persist_policy": "do_not_persist",
            },
        ],
        session_id="session:test",
    )

    assert messages[0].meta["answer_canonical_state"] == "stable_answer"


def test_task_executor_final_commit_uses_canonical_output_boundary() -> None:
    committed: list[dict[str, object]] = []
    event_log = SimpleNamespace(
        append=lambda *_args, **_kwargs: SimpleNamespace(offset=1, created_at=1.0, to_dict=lambda: {})
    )
    services = SimpleNamespace(
        assistant_message_committer=lambda payload: committed.append(dict(payload)),
        runtime_host=SimpleNamespace(event_log=event_log),
    )
    task_run = SimpleNamespace(
        session_id="session:test",
        task_run_id="taskrun:test",
        task_id="task:test",
        diagnostics={"turn_id": "turn:session:test:1"},
    )

    _commit_task_run_final_message(
        services,
        task_run=task_run,
        final_answer="结论：任务完成。",
    )

    assert committed[0]["content"] == "任务完成。"
    assert committed[0]["answer_canonical_state"] == "stable_answer"
    assert committed[0]["answer_persist_policy"] == "persist_canonical"
    assert committed[0]["answer_selected_channel"] == "answer_candidate"


def test_task_executor_final_commit_carries_turn_id() -> None:
    committed: list[dict[str, object]] = []
    event_log = SimpleNamespace(
        append=lambda *_args, **_kwargs: SimpleNamespace(offset=1, created_at=1.0, to_dict=lambda: {})
    )
    services = SimpleNamespace(
        assistant_message_committer=lambda payload: committed.append(dict(payload)),
        runtime_host=SimpleNamespace(event_log=event_log),
    )
    task_run = SimpleNamespace(
        session_id="session:test",
        task_run_id="taskrun:test",
        task_id="task:test",
        diagnostics={"turn_id": "turn:session:test:9"},
    )

    _commit_task_run_final_message(
        services,
        task_run=task_run,
        final_answer="结论：任务完成。",
    )

    assert committed[0]["turn_id"] == "turn:session:test:9"


def test_replacement_stop_closeout_does_not_commit_session_message() -> None:
    committed: list[dict[str, object]] = []
    event_log = SimpleNamespace(
        append=lambda *_args, **_kwargs: SimpleNamespace(offset=1, created_at=1.0, to_dict=lambda: {})
    )
    services = SimpleNamespace(
        assistant_message_committer=lambda payload: committed.append(dict(payload)),
        runtime_host=SimpleNamespace(event_log=event_log),
    )
    task_run = SimpleNamespace(
        session_id="session:test",
        task_run_id="taskrun:test",
        task_id="task:test",
        diagnostics={
            "turn_id": "turn:session:test:old",
            "runtime_control": {"reason": "replaced_by_new_task_request"},
        },
    )

    _commit_task_run_final_message(
        services,
        task_run=task_run,
        final_answer="尚未读取文件。",
        completion_state="aborted",
        terminal_reason="user_aborted",
        answer_source="harness.loop.task_executor.agent_controlled_runtime_boundary",
        execution_posture="task_run_agent_controlled_runtime_boundary",
    )

    assert committed == []
