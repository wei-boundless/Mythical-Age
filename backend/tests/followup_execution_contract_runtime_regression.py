from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from execution.model_response import ModelResponseRuntimeExecutor
from orchestration.runtime_directive import RuntimeDirective
from orchestration.runtime_loop.task_run_loop import TaskRunLoop
from understanding.memory_intent import MemoryIntent
from understanding.task_understanding import analyze_task_understanding


def test_delegation_payload_inherits_active_subset_contract() -> None:
    runtime = TaskRunLoop.__new__(TaskRunLoop)
    runtime.state_index = SimpleNamespace(
        get_task_run=lambda _task_run_id: SimpleNamespace(session_id="session-contract")
    )
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
        "task_spec": {
            "inputs": {
                "followup_execution_contract": {
                    "authority": "task_system.followup_execution_contract",
                    "constraint_policy": "result_subset_only_do_not_expand_to_full_object",
                    "followup_scope": "active_subset",
                    "followup_target_kind": "active_subset",
                    "followup_target_refs": [
                        "subset:selection:employees:top5",
                        "result:structured:employees:top5",
                    ],
                    "active_subset_handle_id": "subset:selection:employees:top5",
                    "active_result_handle_id": "result:structured:employees:top5",
                    "source_kind": "dataset",
                    "source_path": "Data/employees.xlsx",
                    "subset_filter_column": "name",
                    "subset_labels": ["Alice", "Bob", "Chen", "Diaz", "Eve"],
                }
            }
        }
    }

    request = TaskRunLoop._build_delegation_request(
        runtime,
        task_run_id="task-run-contract",
        action_request=action_request,
        parent_agent_run_ref="agentrun:main",
        source_agent_id="agent:main",
        user_message="只基于刚才这前五名员工，按部门做一个归类总结，不要回到全表重算。",
        task_operation=task_operation,
    )

    assert request.input_payload["path"] == "Data/employees.xlsx"
    assert request.input_payload["active_dataset"] == "Data/employees.xlsx"
    assert request.input_payload["followup_scope"] == "active_subset"
    assert request.input_payload["followup_constraint_policy"] == "result_subset_only_do_not_expand_to_full_object"
    assert request.input_payload["followup_target_refs"] == [
        "subset:selection:employees:top5",
        "result:structured:employees:top5",
    ]
    assert request.input_payload["active_subset_handle_id"] == "subset:selection:employees:top5"
    assert request.input_payload["active_result_handle_id"] == "result:structured:employees:top5"
    assert request.input_payload["subset_filter_column"] == "name"
    assert request.input_payload["subset_labels"] == ["Alice", "Bob", "Chen", "Diaz", "Eve"]
    assert request.input_payload["semantic_hints"]["subset_filter_column"] == "name"
    assert request.input_payload["semantic_hints"]["subset_allowed_values"] == ["Alice", "Bob", "Chen", "Diaz", "Eve"]


def test_pdf_delegation_payload_prefers_current_turn_tool_input_over_stale_instruction() -> None:
    runtime = TaskRunLoop.__new__(TaskRunLoop)
    runtime.state_index = SimpleNamespace(
        get_task_run=lambda _task_run_id: SimpleNamespace(session_id="session-pdf-contract")
    )
    action_request = SimpleNamespace(
        operation_id="op.delegate_to_agent",
        payload={
            "tool_call": {
                "id": "call-pdf-stale",
                "args": {
                    "instruction": "之前第三页和第四页是过渡页，现在从第三页继续看第二部分。",
                    "input_payload": {},
                },
            }
        },
    )
    task_operation = {
        "selected_recipe": {
            "metadata": {
                "delegation_kind": "pdf_reading",
                "delegate_target_agent_id": "agent:pdf_reader",
            }
        },
        "task_spec": {
            "inputs": {
                "followup_execution_contract": {
                    "authority": "task_system.followup_execution_contract",
                    "constraint_policy": "active_object_followup",
                    "followup_scope": "active_object",
                    "followup_target_kind": "active_pdf",
                    "followup_target_refs": ["result:pdf_answer:p3"],
                    "source_kind": "pdf",
                    "source_path": "knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf",
                    "tool_input": {
                        "query": "回到刚才 PDF。第二部分真正强调的约束重点是什么？",
                        "mode": "section",
                        "path": "knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf",
                    },
                }
            }
        },
    }

    request = TaskRunLoop._build_delegation_request(
        runtime,
        task_run_id="task-run-pdf-contract",
        action_request=action_request,
        parent_agent_run_ref="agentrun:main",
        source_agent_id="agent:main",
        user_message="回到刚才 PDF。第二部分真正强调的约束重点是什么？",
        task_operation=task_operation,
    )

    assert request.target_agent_id == "agent:pdf_reader"
    assert request.delegation_kind == "pdf_reading"
    assert request.input_payload["query"] == "回到刚才 PDF。第二部分真正强调的约束重点是什么？"
    assert request.input_payload["mode"] == "section"
    assert request.input_payload["path"] == "knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf"
    assert "第三页" in request.instruction


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


def test_memory_intent_does_not_short_circuit_bound_pdf_page_understanding() -> None:
    understanding = analyze_task_understanding(
        "如果我要把这份报告讲给业务负责人听，第四页最值得摘出来的两到三句是什么？",
        MemoryIntent(intent="session_state", memory_read_mode="session_state", should_skip_rag=True),
        active_bindings={
            "committed_pdf": "knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf",
            "committed_pdf_owner_task_id": "result:pdf_answer:p3",
        },
    )

    assert understanding.route_hint == "pdf"
    assert understanding.modality == "pdf"
    assert understanding.task_kind == "document_page"
    assert understanding.parameters["mode"] == "page"
    assert understanding.parameters["path"] == "knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf"
    assert "bound_pdf_followup" in understanding.reasons


def test_recipe_mcp_constraints_inherit_active_subset_contract() -> None:
    runtime = TaskRunLoop.__new__(TaskRunLoop)
    _, operation_id, bindings, constraints, _ = TaskRunLoop._recipe_mcp_request_parts(
        runtime,
        user_message="只基于刚才这前五名员工按部门总结。",
        current_turn_context={},
        query_understanding={"source_kind": "dataset", "parameters": {"query": "按部门总结。"}},
        selected_recipe_payload={"source_kind": "dataset"},
        task_spec_payload={
            "inputs": {
                "followup_execution_contract": {
                    "authority": "task_system.followup_execution_contract",
                    "constraint_policy": "result_subset_only_do_not_expand_to_full_object",
                    "followup_scope": "active_subset",
                    "followup_target_kind": "active_subset",
                    "followup_target_refs": ["subset:selection:employees:top5"],
                    "source_kind": "dataset",
                    "source_path": "Data/employees.xlsx",
                    "subset_filter_column": "name",
                    "subset_labels": ["Alice", "Bob", "Chen", "Diaz", "Eve"],
                }
            }
        },
    )

    assert operation_id == "op.mcp_structured_data"
    assert bindings == {"active_dataset": "Data/employees.xlsx"}
    assert constraints["path"] == "Data/employees.xlsx"
    assert constraints["followup_constraint_policy"] == "result_subset_only_do_not_expand_to_full_object"
    assert constraints["followup_scope"] == "active_subset"
    assert constraints["followup_target_refs"] == ["subset:selection:employees:top5"]
    assert constraints["subset_filter_column"] == "name"
    assert constraints["subset_labels"] == ["Alice", "Bob", "Chen", "Diaz", "Eve"]
    assert constraints["semantic_hints"]["subset_filter_column"] == "name"
    assert constraints["semantic_hints"]["subset_allowed_values"] == ["Alice", "Bob", "Chen", "Diaz", "Eve"]
