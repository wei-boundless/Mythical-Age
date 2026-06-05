from __future__ import annotations

from pathlib import Path

from memory_system import MemoryFacade
from memory_system.runtime_context_provider import RuntimeMemoryContextProvider
from harness.entrypoint import HarnessRuntimeFacade


def test_assistant_commit_uses_context_state_writeback_for_file_work_objects(tmp_path: Path) -> None:
    runtime = HarnessRuntimeFacade.__new__(HarnessRuntimeFacade)
    runtime.session_manager = _SessionManager()
    runtime.memory_facade = MemoryFacade(tmp_path)
    runtime.runtime_memory_context_provider = RuntimeMemoryContextProvider(
        bundle_service_getter=lambda: runtime.memory_facade.bundle_service,
        session_record_loader=lambda _session_id: {},
        recent_messages_loader=lambda _session_id: [],
    )

    result = HarnessRuntimeFacade._apply_assistant_message_commit(
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
        force=True,
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


