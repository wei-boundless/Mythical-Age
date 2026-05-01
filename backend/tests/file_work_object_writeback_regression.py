from __future__ import annotations

from pathlib import Path

from memory.facade import MemoryFacade
from orchestration.runtime_loop.task_run_loop import _project_file_work_context_from_tool_observation
from query.runtime import QueryRuntime


def test_structured_tool_observation_projects_file_work_context() -> None:
    main_context, task_refs = _project_file_work_context_from_tool_observation(
        {
            "tool_name": "structured_data_analysis",
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


def test_pdf_tool_observation_projects_file_work_context() -> None:
    main_context, task_refs = _project_file_work_context_from_tool_observation(
        {
            "tool_name": "pdf_analysis",
            "tool_args": {
                "query": "第三页具体讲了什么？",
                "path": "knowledge/AI Knowledge/report.pdf",
                "mode": "page",
            },
            "result": "第 3 页主要讨论 AI 治理的风险分层。",
        }
    )

    assert main_context["active_work_item"] == "pdf"
    assert main_context["active_constraints"]["active_pdf"] == "knowledge/AI Knowledge/report.pdf"
    assert main_context["active_constraints"]["active_pdf_pages"] == [3]
    assert main_context["active_object_handle_id"].startswith("source:pdf:")
    assert main_context["active_result_handle_id"].startswith("result:pdf_answer:")
    assert main_context["active_subset_handle_id"].startswith("subset:pdf_pages:")
    assert task_refs[0]["task_kind"] == "pdf"


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


class _SessionManager:
    def __init__(self) -> None:
        self.messages: list[dict[str, object]] = []

    def append_messages(self, _session_id: str, messages: list[dict[str, object]]) -> list[dict[str, object]]:
        self.messages.extend(messages)
        return messages

    def load_session(self, _session_id: str) -> list[dict[str, object]]:
        return list(self.messages)
