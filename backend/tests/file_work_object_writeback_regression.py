from __future__ import annotations

import json
from pathlib import Path

from memory_system import MemoryFacade
from runtime.execution_engine import project_file_work_context_from_tool_observation
from query.runtime import QueryRuntime


def test_structured_mcp_observation_projects_file_work_context() -> None:
    main_context, task_refs = project_file_work_context_from_tool_observation(
        {
            "tool_name": "mcp_structured_data",
            "tool_args": {
                "query": "找出薪资前五的人。",
                "path": "knowledge/E-commerce Data/employees.xlsx",
            },
            "result": (
                "| 排名 | 姓名 | 部门 | 薪资 |\n"
                "|---|---|---|---|\n"
                "| 1 | 罗凯 | 运营 | 34900 |\n"
                "| 2 | 唐琳 | 技术 | 34800 |\n"
            ),
        }
    )

    assert main_context["active_work_item"] == "structured_data"
    assert main_context["active_constraints"]["active_dataset"] == "knowledge/E-commerce Data/employees.xlsx"
    assert main_context["active_object_handle_id"].startswith("source:dataset:")
    assert main_context["active_result_handle_id"].startswith("result:structured_answer:")
    assert main_context["active_subset_handle_id"] == ""
    assert task_refs[0]["task_kind"] == "structured_data"
    assert "dataset=knowledge/E-commerce Data/employees.xlsx" in task_refs[0]["key_points"]
    assert not any(str(item).startswith("subset=") for item in task_refs[0]["key_points"])


def test_delegated_structured_observation_uses_canonical_subset_hints() -> None:
    main_context, _ = project_file_work_context_from_tool_observation(
        {
            "tool_name": "delegate_to_agent",
            "tool_args": {
                "delegation_kind": "table_analysis",
                "instruction": "找出薪资前五名员工。",
                "current_user_message": "找出薪资前五名员工。",
                "input_payload": {"path": "Data/employees.xlsx", "query": "找出薪资前五名员工。"},
            },
            "result": json.dumps(
                {
                    "status": "completed",
                    "summary": "薪资前五名员工已返回。",
                    "answer_candidate": "薪资前五名员工已返回。",
                    "context_writeback_hints": {
                        "source_kind": "dataset",
                        "source_path": "Data/employees.xlsx",
                        "active_object_handle_id": "source:dataset:employees",
                        "active_result_handle_id": "result:structured:employees:top5",
                        "active_subset_handle_id": "subset:selection:employees:top5",
                        "subset_filter_column": "name",
                        "subset_labels": ["Alice", "Bob", "Chen", "Diaz", "Eve"],
                    },
                },
                ensure_ascii=False,
            ),
        }
    )

    assert main_context["active_object_handle_id"] == "source:dataset:employees"
    assert main_context["active_result_handle_id"] == "result:structured:employees:top5"
    assert main_context["active_subset_handle_id"] == "subset:selection:employees:top5"
    assert main_context["active_constraints"]["subset_filter_column"] == "name"
    assert main_context["active_constraints"]["subset_labels"] == ["Alice", "Bob", "Chen", "Diaz", "Eve"]


def test_auto_delegated_structured_observation_infers_kind_from_writeback_protocol() -> None:
    main_context, task_refs = project_file_work_context_from_tool_observation(
        {
            "tool_name": "delegate_to_agent",
            "tool_args": {
                "instruction": "是否存在完全没有缺口的仓库？如果没有，直接说没有。",
                "current_user_message": "再补一句：是否存在完全没有缺口的仓库？如果没有，直接说没有。",
                "input_payload": {"query": "是否存在完全没有缺口的仓库？"},
            },
            "result": json.dumps(
                {
                    "type": "agent_delegation_result",
                    "status": "completed",
                    "target_agent_id": "agent:table_analyst",
                    "summary": "数据源：inventory.xlsx\n结论：没有完全没有缺口的仓库。",
                    "answer_candidate": "数据源：inventory.xlsx\n结论：没有完全没有缺口的仓库。",
                    "context_writeback_hints": {
                        "source_kind": "dataset",
                        "source_path": "inventory.xlsx",
                        "active_object_handle_id": "source:dataset:inventory",
                        "active_result_handle_id": "result:structured:inventory:no_gap",
                    },
                },
                ensure_ascii=False,
            ),
        }
    )

    assert main_context["active_work_item"] == "structured_data"
    assert main_context["active_constraints"]["active_dataset"] == "inventory.xlsx"
    assert main_context["active_object_handle_id"] == "source:dataset:inventory"
    assert main_context["active_result_handle_id"] == "result:structured:inventory:no_gap"
    assert task_refs[0]["task_kind"] == "structured_data"
    assert "dataset=inventory.xlsx" in task_refs[0]["key_points"]


def test_delegated_observation_does_not_infer_file_work_kind_from_agent_name() -> None:
    main_context, task_refs = project_file_work_context_from_tool_observation(
        {
            "tool_name": "delegate_to_agent",
            "tool_args": {
                "instruction": "检查这个结果。",
                "current_user_message": "检查这个结果。",
                "input_payload": {"query": "检查这个结果。"},
            },
            "result": json.dumps(
                {
                    "type": "agent_delegation_result",
                    "status": "completed",
                    "target_agent_id": "agent:table_analyst",
                    "summary": "这个结果看起来像表格分析，但没有写回协议。",
                    "answer_candidate": "这个结果看起来像表格分析，但没有写回协议。",
                },
                ensure_ascii=False,
            ),
        }
    )

    assert main_context == {}
    assert task_refs == []


def test_pdf_mcp_observation_projects_file_work_context() -> None:
    main_context, task_refs = project_file_work_context_from_tool_observation(
        {
            "tool_name": "mcp_pdf",
            "tool_args": {
                "query": "第三页具体讲了什么？",
                "path": "knowledge/AI Knowledge/report.pdf",
                "mode": "page",
            },
            "result": "第 3 页主要讨论 AI 治理的风险分层。",
        }
    )

    assert main_context["active_work_item"] == "pdf"
    assert main_context["followup_mode"] == "binding_ref"
    assert main_context["active_constraints"]["active_pdf"] == "knowledge/AI Knowledge/report.pdf"
    assert main_context["active_constraints"]["active_pdf_pages"] == [3]
    assert main_context["active_object_handle_id"].startswith("source:pdf:")
    assert main_context["active_result_handle_id"].startswith("result:pdf_answer:")
    assert main_context["active_subset_handle_id"].startswith("subset:pdf_pages:")
    assert task_refs[0]["task_kind"] == "pdf"


def test_structured_projection_does_not_infer_subset_from_answer_text() -> None:
    main_context, task_refs = project_file_work_context_from_tool_observation(
        {
            "tool_name": "delegate_to_agent",
            "tool_args": {
                "delegation_kind": "table_analysis",
                "instruction": "找出薪资前五名员工。",
                "current_user_message": "找出薪资前五名员工。",
                "input_payload": {"path": "Data/employees.xlsx", "query": "找出薪资前五名员工。"},
            },
            "result": json.dumps(
                {
                    "status": "completed",
                    "summary": (
                        "数据源：employees.xlsx\n"
                        "筛选条件：无\n"
                        "查询模式：记录排序\n"
                        "排序字段：薪水\n\n"
                        "前 5 条记录：\n"
                        "员工编号 姓名 部门 职位 城市 薪水\n"
                        "E-0074 罗凯 运营 运营专员 北京 34900\n"
                        "E-0148 唐琳 技术 后端工程师 杭州 34800"
                    ),
                    "context_writeback_hints": {
                        "source_kind": "dataset",
                        "source_path": "Data/employees.xlsx",
                        "active_object_handle_id": "source:dataset:employees",
                        "active_result_handle_id": "result:structured:employees:top5",
                    },
                },
                ensure_ascii=False,
            ),
        }
    )

    assert main_context["active_constraints"]["active_dataset"] == "Data/employees.xlsx"
    assert main_context["active_subset_handle_id"] == ""
    assert "subset_labels" not in main_context["active_constraints"]
    assert not any(str(item).startswith("subset=") for item in task_refs[0]["key_points"])


def test_assistant_commit_uses_context_state_writeback_for_file_work_objects(tmp_path: Path) -> None:
    runtime = QueryRuntime.__new__(QueryRuntime)
    runtime.session_manager = _SessionManager()
    runtime.memory_facade = MemoryFacade(tmp_path)

    result = QueryRuntime._apply_assistant_message_commit(
        runtime,
        "session-1",
        {
            "role": "assistant",
            "content": "薪资前五已经整理完。",
            "answer_channel": "answer_candidate",
            "answer_source": "test",
            "answer_canonical_state": "stable_answer",
            "answer_persist_policy": "persist_canonical",
            "main_context": {
                "active_goal": "找出薪资前五的人。",
                "active_work_item": "structured_data",
                "active_binding_identity": "knowledge/e-commerce data/employees.xlsx",
                "active_object_handle_id": "source:dataset:employees",
                "active_result_handle_id": "result:structured:employees:top5",
                "active_subset_handle_id": "subset:selection:employees:top5",
                "followup_mode": "task_ref",
                "followup_binding_key": "active_dataset",
                "followup_binding_identity": "knowledge/e-commerce data/employees.xlsx",
                "active_constraints": {
                    "active_dataset": "knowledge/E-commerce Data/employees.xlsx",
                    "source_kind": "dataset",
                    "subset_filter_column": "name",
                    "subset_labels": ["Alice", "Bob", "Chen", "Diaz", "Eve"],
                },
            },
            "task_summary_refs": [
                {
                    "task_id": "result:structured:employees:top5",
                    "query": "找出薪资前五的人。",
                    "summary": "薪资前五已经整理完。",
                    "task_kind": "structured_data",
                    "key_points": ["dataset=knowledge/E-commerce Data/employees.xlsx"],
                }
            ],
        },
    )

    state = runtime.memory_facade.session_memory.manager("session-1").load_state()
    assert result["file_work_context_writeback"] is True
    assert state.context_slots.active_dataset == "knowledge/E-commerce Data/employees.xlsx"
    assert state.context_slots.active_object_handle_id == "source:dataset:employees"
    assert state.context_slots.active_result_handle_id == "result:structured:employees:top5"
    assert state.context_slots.active_subset_handle_id == "subset:selection:employees:top5"
    assert state.context_slots.active_subset_filter_column == "name"
    assert state.context_slots.active_subset_labels == ["Alice", "Bob", "Chen", "Diaz", "Eve"]


def test_memory_maintenance_without_model_does_not_rewrite_pdf_work_object_slots(tmp_path: Path) -> None:
    facade = MemoryFacade(tmp_path)
    session_id = "session-pdf-history-refresh"
    pdf_path = "knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf"

    facade.session_memory.update_runtime_state_from_context_state(
        session_id,
        {
            "active_goal": "第四页如果要给业务负责人看，应该重点看哪几句？",
            "active_work_item": "pdf",
            "active_binding_identity": pdf_path.lower(),
            "active_object_handle_id": "source:pdf:ai-governance",
            "active_result_handle_id": "result:pdf_answer:turn7",
            "active_subset_handle_id": "subset:pdf_pages:p4",
            "followup_mode": "task_ref",
            "followup_binding_key": "active_pdf",
            "followup_target_task_id": "result:pdf_answer:turn7",
            "active_constraints": {
                "active_pdf": pdf_path,
                "active_pdf_mode": "page",
                "active_pdf_pages": [4],
                "source_kind": "pdf",
            },
        },
        task_summaries=[
            {
                "task_id": "result:pdf_answer:turn7",
                "query": "第四页如果要给业务负责人看，应该重点看哪几句？",
                "summary": "第四页重点看三句。",
                "task_kind": "pdf",
                "key_points": [
                    f"pdf={pdf_path}",
                    "pdf_mode=page",
                    "pdf_pages=4",
                ],
            }
        ],
    )

    receipt = facade.run_memory_maintenance_after_commit(
        session_id=session_id,
        durable_lane_enabled=False,
        messages=[
            {"role": "user", "content": f"现在打开 {pdf_path}，给我一个全文总览。"},
            {"role": "assistant", "content": "已定位与当前问题最相关的页面。"},
            {"role": "user", "content": "第四页如果要给业务负责人看，应该重点看哪几句？"},
            {"role": "assistant", "content": "第四页重点看三句。"},
            {"role": "user", "content": "把这份 PDF 的核心结论压成三条行动建议。"},
        ],
    )

    state = facade.session_memory.manager(session_id).load_state()
    assert receipt.status == "failed"
    assert state.context_slots.active_pdf == pdf_path
    assert state.context_slots.active_pdf_mode == "page"
    assert state.context_slots.active_pdf_pages == [4]
    assert state.context_slots.active_binding_kind == "active_pdf"
    assert state.context_slots.active_binding_owner_task_id == "result:pdf_answer:turn7"
    assert state.context_slots.active_result_handle_id == "result:pdf_answer:turn7"


def test_session_memory_prefers_structured_answer_over_short_summary(tmp_path: Path) -> None:
    facade = MemoryFacade(tmp_path)
    session_id = "session-answer-preferred"

    facade.session_memory.update_runtime_state_from_context_state(
        session_id,
        {
            "active_goal": "请给出完整结论。",
            "active_work_item": "structured_data",
            "active_constraints": {"source_kind": "dataset"},
        },
        task_summaries=[
            {
                "task_id": "result:structured:turn1",
                "query": "请给出完整结论。",
                "answer": "这是完整答案，包含三点结论与行动建议。",
                "summary": "这是完整答案",
                "task_kind": "structured_data",
                "key_points": ["dataset=inventory.xlsx"],
            }
        ],
    )

    state = facade.session_memory.manager(session_id).load_state()
    assert state.current_result_refs[0] == "这是完整答案，包含三点结论与行动建议。"
    assert state.key_results[0] == "这是完整答案，包含三点结论与行动建议。"

class _SessionManager:
    def __init__(self) -> None:
        self.messages: list[dict[str, object]] = []

    def append_messages(self, _session_id: str, messages: list[dict[str, object]]) -> list[dict[str, object]]:
        self.messages.extend(messages)
        return messages

    def load_session(self, _session_id: str) -> list[dict[str, object]]:
        return list(self.messages)
