from __future__ import annotations

from pathlib import Path

from context_management.projection import projection_from_bound_answer
from memory_system import MemoryFacade
from orchestration.runtime_loop.task_run_loop import _project_file_work_context_from_tool_observation
from query.runtime import QueryRuntime


def test_structured_mcp_observation_projects_file_work_context() -> None:
    main_context, task_refs = _project_file_work_context_from_tool_observation(
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
    assert main_context["active_subset_handle_id"].startswith("subset:structured_selection:")
    assert task_refs[0]["task_kind"] == "structured_data"
    assert "dataset=knowledge/E-commerce Data/employees.xlsx" in task_refs[0]["key_points"]


def test_pdf_mcp_observation_projects_file_work_context() -> None:
    main_context, task_refs = _project_file_work_context_from_tool_observation(
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


def test_bound_answer_projection_prefers_dataset_template_over_prior_pdf_binding() -> None:
    projection = projection_from_bound_answer(
        content="没有。每个仓库至少存在一条库存低于补货线的记录。",
        current_turn_context={
            "intent": "general_query",
            "selected_template_id": "template.data.structured_analysis",
            "explicit_inputs": {
                "bound_dataset_path": "inventory.xlsx",
                "bound_pdf_path": "knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf",
                "tool_input": {
                    "query": "是否存在完全没有缺口的仓库？",
                    "path": "inventory.xlsx",
                },
            },
            "resolved_bindings": [
                {
                    "binding_kind": "source_file",
                    "identity": "knowledge/ai knowledge/2025年ai治理报告：回归现实主义.pdf",
                    "file_kind": "pdf",
                    "metadata": {"path": "knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf"},
                },
                {
                    "binding_kind": "source_file",
                    "identity": "inventory.xlsx",
                    "file_kind": "dataset",
                    "metadata": {"path": "inventory.xlsx"},
                },
            ],
        },
    )

    assert projection.main_context["active_work_item"] == "structured_data"
    assert projection.main_context["followup_binding_key"] == "active_dataset"
    assert projection.main_context["active_constraints"]["active_dataset"] == "inventory.xlsx"
    assert projection.main_context["active_result_handle_id"].startswith("result:structured_answer:")
    assert projection.task_summary_refs[0]["task_kind"] == "structured_data"


def test_bound_answer_projection_prefers_pdf_template_over_dataset_binding() -> None:
    pdf_path = "knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf"
    projection = projection_from_bound_answer(
        content="第三页承担目录和结构导航作用。",
        current_turn_context={
            "intent": "general_query",
            "selected_template_id": "template.pdf.document_analysis",
            "explicit_inputs": {
                "bound_dataset_path": "inventory.xlsx",
                "bound_pdf_path": pdf_path,
                "tool_input": {
                    "query": "第三页承担什么作用？",
                    "path": pdf_path,
                    "mode": "page",
                },
            },
            "resolved_bindings": [
                {
                    "binding_kind": "source_file",
                    "identity": "inventory.xlsx",
                    "file_kind": "dataset",
                    "metadata": {"path": "inventory.xlsx"},
                },
                {
                    "binding_kind": "source_file",
                    "identity": pdf_path.lower(),
                    "file_kind": "pdf",
                    "metadata": {"path": pdf_path},
                },
            ],
        },
    )

    assert projection.main_context["active_work_item"] == "pdf"
    assert projection.main_context["followup_binding_key"] == "active_pdf"
    assert projection.main_context["active_constraints"]["active_pdf"] == pdf_path
    assert projection.main_context["active_result_handle_id"].startswith("result:pdf_answer:")
    assert projection.task_summary_refs[0]["task_kind"] == "pdf"


def test_bound_answer_projection_ignores_non_file_task_with_stale_binding() -> None:
    projection = projection_from_bound_answer(
        content="现货黄金约 4737 美元/盎司，时间口径为 2026-05-11 21:03 UTC。",
        current_turn_context={
            "intent": "realtime_network",
            "selected_template_id": "template.search.information_search",
            "explicit_inputs": {
                "bound_dataset_path": "inventory.xlsx",
                "tool_input": {
                    "query": "顺便查一下黄金价格，直接给结论和时间口径。",
                },
            },
            "resolved_bindings": [
                {
                    "binding_kind": "source_file",
                    "identity": "inventory.xlsx",
                    "file_kind": "dataset",
                    "metadata": {"path": "inventory.xlsx"},
                },
            ],
        },
    )

    assert projection.main_context == {}
    assert projection.task_summary_refs == []
    assert projection.result_handle_ids == []


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


def test_history_refresh_preserves_bound_pdf_followup_slots(tmp_path: Path) -> None:
    facade = MemoryFacade(tmp_path)
    session_id = "session-pdf-history-refresh"
    pdf_path = "knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf"

    facade.refresh_session_memory_from_context_state(
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

    facade.refresh_session_memory(
        session_id,
        [
            {"role": "user", "content": f"现在打开 {pdf_path}，给我一个全文总览。"},
            {"role": "assistant", "content": "已定位与当前问题最相关的页面。"},
            {"role": "user", "content": "第四页如果要给业务负责人看，应该重点看哪几句？"},
            {"role": "assistant", "content": "第四页重点看三句。"},
            {"role": "user", "content": "把这份 PDF 的核心结论压成三条行动建议。"},
        ],
    )

    state = facade.session_memory.manager(session_id).load_state()
    assert state.context_slots.active_pdf == pdf_path
    assert state.context_slots.active_pdf_mode == "page"
    assert state.context_slots.active_pdf_pages == [4]
    assert state.context_slots.active_binding_kind == "active_pdf"
    assert state.context_slots.active_binding_owner_task_id == "result:pdf_answer:turn7"
    assert state.context_slots.active_result_handle_id == "result:pdf_answer:turn7"


class _SessionManager:
    def __init__(self) -> None:
        self.messages: list[dict[str, object]] = []

    def append_messages(self, _session_id: str, messages: list[dict[str, object]]) -> list[dict[str, object]]:
        self.messages.extend(messages)
        return messages

    def load_session(self, _session_id: str) -> list[dict[str, object]]:
        return list(self.messages)
