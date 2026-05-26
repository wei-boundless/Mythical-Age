from __future__ import annotations

import sys
import asyncio
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from runtime.execution_engine import (
    ModelToolCallAccumulator,
    build_answer_readiness_judge_message,
    translate_executor_event,
)


class _Event:
    def __init__(self, event_type: str, payload: dict, refs: dict | None = None) -> None:
        self.event_type = event_type
        self.payload = payload
        self.refs = dict(refs or {})
        self.event_id = f"event:{event_type}"


class _EventLog:
    def __init__(self) -> None:
        self.events: list[_Event] = []

    def append(self, task_run_id: str, event_type: str, payload: dict | None = None, refs: dict | None = None) -> _Event:
        _ = task_run_id
        event = _Event(event_type, dict(payload or {}), refs)
        self.events.append(event)
        return event


def test_execution_engine_does_not_export_system_answer_finalizers() -> None:
    import runtime.execution_engine as execution_engine

    assert not hasattr(execution_engine, "select_final_answer_from_context")
    assert not hasattr(execution_engine, "finalize_budget_exhausted_followup")
    assert not hasattr(execution_engine, "builtin_tool_lane_answer_from_observation")


def test_execution_engine_readiness_prompt_keeps_answer_decision_with_model() -> None:
    class _Aggregation:
        evidence_items = (
            {
                "tool_name": "read_file",
                "tool_args": {"path": "README.md"},
                "result_preview": "project overview",
                "result_chars": 16,
            },
        )

    content = build_answer_readiness_judge_message(
        user_message="总结 README",
        aggregation=_Aggregation(),
        current_bundle_items=[],
        remaining_model_calls=2,
    )

    assert "如果证据已经足够覆盖用户当前问题，请直接收口回答" in content
    assert "不要输出 JSON" in content
    assert "runtime_loop_control" not in content


def test_execution_engine_model_tool_call_accumulator_collects_stream_context() -> None:
    accumulator = ModelToolCallAccumulator()

    accumulator.ingest_event(
        {
            "type": "tool_call_requested",
            "tool_call": {"id": "call-1", "name": "read_file"},
            "assistant_content": "需要读取文件",
            "assistant_additional_kwargs": {"tool_calls": [{"id": "call-1"}]},
        }
    )
    accumulator.ingest_event({"type": "content_delta", "content": "ignore"})

    assert accumulator.pending_tool_calls == [{"id": "call-1", "name": "read_file"}]
    assert accumulator.assistant_content == "需要读取文件"
    assert accumulator.assistant_additional_kwargs["tool_calls"] == [{"id": "call-1"}]


def test_execution_engine_translates_model_stream_delta() -> None:
    event_log = _EventLog()

    events = asyncio.run(
        translate_executor_event(
            event_log=event_log,
            task_run_id="task-run-1",
            user_message="hello",
            task_id="task",
            task_operation={},
            adopted_resource_policy=None,
            current_step_id="step-1",
            runtime_context_manager=None,
            model_response_executor=None,
            tool_runtime_executor=None,
            event={
                "type": "content_delta",
                "content": "partial",
                "stream_ref": "directive-1",
            },
            definitions_by_name={},
            operation_gate=None,
            permission_mode="default",
            root_dir=".",
        )
    )

    assert [event.event_type for event in events] == ["model_item_received"]
    assert event_log.events[0].payload["delta_preview"] == "partial"
