from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from runtime.model_gateway.model_response import ModelResponseRuntimeExecutor
from orchestration.runtime_directive import RuntimeDirective
from request_intent.request_signals import build_request_signals
from runtime.context_management.system_retrieval import build_system_retrieval_request_parts
from runtime.execution_engine.delegation_context import build_delegation_request


def _candidate_context() -> dict:
    return {
        "authority": "context.current_turn",
        "context_recall_candidates": [
            {
                "candidate_id": "continuation:state:active_dataset:data-employees-xlsx",
                "recall_source": "continuation_candidate",
                "source_kind": "dataset",
                "file_kind": "dataset",
                "target_kind": "result_subset",
                "identity": "data/employees.xlsx",
                "compatible": True,
                "selected_by_context_recall": True,
                "recall_payload": {
                    "path": "Data/employees.xlsx",
                    "active_dataset": "Data/employees.xlsx",
                    "source_kind": "dataset",
                    "active_result_handle_id": "result:structured:employees:top5",
                    "active_subset_handle_id": "subset:selection:employees:top5",
                    "active_constraints": {
                        "active_dataset": "Data/employees.xlsx",
                        "source_kind": "dataset",
                        "subset_filter_column": "name",
                        "subset_labels": ["Alice", "Bob", "Chen", "Diaz", "Eve"],
                    },
                },
            }
        ],
    }


def test_delegation_payload_uses_context_recall_candidate_without_old_contract() -> None:
    action_request = SimpleNamespace(
        operation_id="op.delegate_to_agent",
        payload={
            "tool_call": {
                "id": "call-1",
                "args": {
                    "target_agent_id": "agent:table_analyst",
                    "delegation_kind": "table_analysis",
                    "instruction": "只基于刚才这前五名员工按部门总结。",
                    "input_payload": {"query": "按部门总结。"},
                },
            }
        },
    )
    task_operation = {
        "current_turn_context": _candidate_context(),
        "task_spec": {
            "recipe_id": "runtime.recipe.structured_data_analysis",
            "inputs": {},
        },
    }

    request = build_delegation_request(
        task_run_id="task-run-context-recall",
        action_request=action_request,
        parent_agent_run_ref="agentrun:main",
        source_agent_id="agent:main",
        user_message="只基于刚才这前五名员工，按部门做一个归类总结，不要回到全表重算。",
        task_operation=task_operation,
        session_id="session-context-recall",
    )

    assert request.input_payload["path"] == "Data/employees.xlsx"
    assert request.input_payload["active_dataset"] == "Data/employees.xlsx"
    assert request.input_payload["query"] == "按部门总结。"
    assert "followup_execution_contract" not in request.input_payload


def test_system_retrieval_request_derives_path_from_context_recall_candidate() -> None:
    _, operation_id, bindings, constraints, _ = build_system_retrieval_request_parts(
        user_message="只基于刚才这前五名员工按部门总结。",
        current_turn_context=_candidate_context(),
        query_understanding=build_request_signals("只基于刚才这前五名员工按部门总结。").to_dict(),
        selected_recipe_payload={"source_kind": "dataset"},
        task_spec_payload={"recipe_id": "runtime.recipe.structured_data_analysis", "inputs": {}},
    )

    assert operation_id == "op.mcp_structured_data"
    assert bindings == {"active_dataset": "Data/employees.xlsx"}
    assert constraints == {"path": "Data/employees.xlsx"}


def test_model_executor_does_not_fabricate_delegate_tool_call_when_model_answers() -> None:
    class _Runtime:
        async def invoke_messages(self, _messages):
            return SimpleNamespace(content="第二部分的约束是旧摘要里的两句话。")

    directive = RuntimeDirective(
        directive_id="runtime-directive:test:model",
        task_id="task:auto-delegate",
        plan_ref="plan:test",
        stage_ref="stage:test",
        executor_type="model",
        adopted_resource_policy_ref="respol:test",
        operation_refs=("op.model_response", "op.delegate_to_agent"),
    )
    executor = ModelResponseRuntimeExecutor(model_runtime=_Runtime())

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in executor.stream(
            user_message="再回到 PDF，第二部分的约束能不能只用两句话说清楚？",
            model_messages=[],
            directive=directive,
            tool_instances=[],
        ):
            events.append(event)
        return events

    events = __import__("asyncio").run(_collect())

    assert all(event["type"] != "tool_call_requested" for event in events)
    assert events[-1]["type"] == "done"
    assert "第二部分的约束是旧摘要里的两句话。" in str(events[-1]["content"])


def test_model_executor_forwards_explicit_delegate_tool_call_without_target_inference() -> None:
    class _Runtime:
        async def invoke_messages(self, _messages):
            return SimpleNamespace(content="unused")

        async def invoke_messages_with_tools(self, _messages, _tools, **_kwargs):
            return SimpleNamespace(
                content="",
                tool_calls=[
                    {
                        "id": "call-delegate-1",
                        "name": "delegate_to_agent",
                        "args": {
                            "target_agent_id": "agent:pdf_reader",
                            "delegation_kind": "pdf_reading",
                            "instruction": "阅读第二部分并压缩成两句话。",
                            "input_payload": {
                                "query": "第二部分的约束能不能只用两句话说清楚？",
                                "path": "knowledge/report.pdf",
                            },
                        },
                    }
                ],
            )

    directive = RuntimeDirective(
        directive_id="runtime-directive:test:explicit-delegate",
        task_id="task:explicit-delegate",
        plan_ref="plan:test",
        stage_ref="stage:test",
        executor_type="model",
        adopted_resource_policy_ref="respol:test",
        operation_refs=("op.model_response", "op.delegate_to_agent"),
    )
    executor = ModelResponseRuntimeExecutor(model_runtime=_Runtime())

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in executor.stream(
            user_message="再回到 PDF，第二部分的约束能不能只用两句话说清楚？",
            model_messages=[],
            directive=directive,
            tool_instances=[SimpleNamespace(name="delegate_to_agent")],
        ):
            events.append(event)
        return events

    events = __import__("asyncio").run(_collect())

    assert [event["type"] for event in events] == ["tool_call_requested"]
    tool_call = dict(events[0]["tool_call"])
    args = dict(tool_call["args"])
    assert events[0]["tool_name"] == "delegate_to_agent"
    assert args["target_agent_id"] == "agent:pdf_reader"
    assert args["delegation_kind"] == "pdf_reading"
    assert args["input_payload"]["path"] == "knowledge/report.pdf"


def test_model_executor_does_not_auto_delegate_for_direct_web_search_lane() -> None:
    class _Runtime:
        async def invoke_messages(self, _messages):
            return SimpleNamespace(content="需要联网查询后回答。")

    directive = RuntimeDirective(
        directive_id="runtime-directive:test:web",
        task_id="task:web-search",
        plan_ref="plan:test",
        stage_ref="stage:test",
        executor_type="model",
        adopted_resource_policy_ref="respol:test",
        operation_refs=("op.model_response", "op.web_search"),
    )
    executor = ModelResponseRuntimeExecutor(model_runtime=_Runtime())

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in executor.stream(
            user_message="北京今天天气怎么样，直接给温度范围和时间口径。",
            model_messages=[],
            directive=directive,
            tool_instances=[],
        ):
            events.append(event)
        return events

    events = __import__("asyncio").run(_collect())

    assert all(event["type"] != "tool_call_requested" for event in events)
    assert events[-1]["type"] == "done"
