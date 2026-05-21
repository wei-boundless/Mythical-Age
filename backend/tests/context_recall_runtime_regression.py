from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from runtime.model_gateway.model_response import ModelResponseRuntimeExecutor
from orchestration.runtime_directive import RuntimeDirective
from runtime.unit_runtime.loop import TaskRunLoop
from understanding.memory_intent import MemoryIntent
from understanding.task_understanding import analyze_task_understanding


def _runtime() -> TaskRunLoop:
    runtime = TaskRunLoop.__new__(TaskRunLoop)
    runtime.state_index = SimpleNamespace(
        get_task_run=lambda _task_run_id: SimpleNamespace(session_id="session-context-recall")
    )
    return runtime


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
    runtime = _runtime()
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

    request = TaskRunLoop._build_delegation_request(
        runtime,
        task_run_id="task-run-context-recall",
        action_request=action_request,
        parent_agent_run_ref="agentrun:main",
        source_agent_id="agent:main",
        user_message="只基于刚才这前五名员工，按部门做一个归类总结，不要回到全表重算。",
        task_operation=task_operation,
    )

    assert request.input_payload["path"] == "Data/employees.xlsx"
    assert request.input_payload["active_dataset"] == "Data/employees.xlsx"
    assert request.input_payload["query"] == "按部门总结。"
    assert "followup_execution_contract" not in request.input_payload


def test_recipe_mcp_request_derives_path_from_context_recall_candidate() -> None:
    runtime = _runtime()
    _, operation_id, bindings, constraints, _ = TaskRunLoop._recipe_mcp_request_parts(
        runtime,
        user_message="只基于刚才这前五名员工按部门总结。",
        current_turn_context=_candidate_context(),
        query_understanding={"source_kind": "dataset", "parameters": {"query": "按部门总结。"}},
        selected_recipe_payload={"source_kind": "dataset"},
        task_spec_payload={"recipe_id": "runtime.recipe.structured_data_analysis", "inputs": {}},
    )

    assert operation_id == "op.mcp_structured_data"
    assert bindings == {"active_dataset": "Data/employees.xlsx"}
    assert constraints == {"path": "Data/employees.xlsx"}


def test_model_executor_auto_delegates_when_delegate_operation_required() -> None:
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

    assert [event["type"] for event in events] == ["tool_call_requested"]
    assert events[0]["tool_name"] == "delegate_to_agent"
    assert dict(events[0]["tool_call"])["args"]["input_payload"]["query"] == "再回到 PDF，第二部分的约束能不能只用两句话说清楚？"


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


def test_memory_intent_no_longer_short_circuits_deictic_pdf_without_explicit_input() -> None:
    understanding = analyze_task_understanding(
        "如果我要把这份报告讲给业务负责人听，第四页最值得摘出来的两到三句是什么？",
        MemoryIntent(intent="session_state", memory_read_mode="session_state", should_skip_rag=True),
    )

    assert understanding.route_hint == "pdf"
    assert understanding.modality == "pdf"
    assert understanding.task_kind == "document_page"
    assert understanding.parameters["mode"] == "page"
    assert "path" not in understanding.parameters
    assert "bound_pdf_followup" not in understanding.reasons
