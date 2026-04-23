from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from query import AnswerAssembler, MainContextState


def test_answer_assembler_prefers_summary_and_dedupes() -> None:
    assembler = AnswerAssembler()
    main_context = MainContextState(
        active_goal="compound",
        active_work_item="compound_query",
        active_constraints={"dedupe": True},
    )
    results = [
        {
            "index": 1,
            "task_id": "t1",
            "query": "第一个任务",
            "summary": {"response": "同一条结论。", "response_style": ""},
            "content": "raw-1",
        },
        {
            "index": 2,
            "task_id": "t2",
            "query": "第二个任务",
            "summary": {"response": "同一条结论。", "response_style": ""},
            "content": "raw-2",
        },
    ]

    plan = assembler.build_plan(results=results, main_context=main_context)
    rendered = assembler.render(plan)

    assert len(plan.segments) == 1
    assert plan.dedupe_targets == ["t2"]
    assert "raw-1" not in rendered
    assert "同一条结论。" in rendered


def test_answer_assembler_compresses_one_sentence_segments() -> None:
    assembler = AnswerAssembler()
    main_context = MainContextState(active_goal="compound", active_work_item="compound_query")
    results = [
        {
            "index": 3,
            "task_id": "t3",
            "query": "补一句北京天气",
            "summary": {
                "response": "北京晴朗。当前温度 15.6°C，西南风 8.5 km/h。",
                "response_style": "one_sentence",
            },
            "content": "raw-weather",
        }
    ]

    plan = assembler.build_plan(results=results, main_context=main_context)
    rendered = assembler.render(plan)

    assert "北京晴朗。" in rendered
    assert "西南风" not in rendered


def test_answer_assembler_can_filter_to_followup_target_tasks() -> None:
    assembler = AnswerAssembler()
    main_context = MainContextState(
        active_goal="followup",
        active_work_item="followup_task_subset_assembly",
        followup_target_task_ids=["t1", "t3"],
        active_constraints={"response_style": "one_sentence"},
    )
    results = [
        {
            "index": 1,
            "task_id": "t1",
            "query": "第一个任务",
            "summary": {"response": "第一条。还有补充。", "response_style": ""},
            "content": "raw-1",
        },
        {
            "index": 2,
            "task_id": "t2",
            "query": "第二个任务",
            "summary": {"response": "第二条。还有补充。", "response_style": ""},
            "content": "raw-2",
        },
        {
            "index": 3,
            "task_id": "t3",
            "query": "第三个任务",
            "summary": {"response": "第三条。还有补充。", "response_style": ""},
            "content": "raw-3",
        },
    ]

    plan = assembler.build_plan(results=results, main_context=main_context)
    rendered = assembler.render(plan)

    assert [segment.task_id for segment in plan.segments] == ["t1", "t3"]
    assert "第二个任务" not in rendered
    assert "第一条。" in rendered
    assert "第三条。" in rendered


def test_answer_assembler_never_falls_back_to_raw_content() -> None:
    assembler = AnswerAssembler()
    main_context = MainContextState(active_goal="followup", active_work_item="followup_task_result_assembly")
    results = [
        {
            "index": 1,
            "task_id": "t1",
            "query": "库存任务",
            "summary": None,
            "content": "warehouse,shortage\nEast,12\nNorth,9",
            "result_ref": {"result_id": "t1-result", "storage_path": "output/task_results/t1.json"},
        }
    ]

    plan = assembler.build_plan(results=results, main_context=main_context)
    rendered = assembler.render(plan)

    assert len(plan.segments) == 1
    assert plan.segments[0].answer_source == "result_ref_placeholder"
    assert plan.segments[0].answer_ref == "t1-result"
    assert "warehouse,shortage" not in rendered
    assert "结果已保存，但当前尚未形成可直接展示的摘要" in rendered


def test_answer_assembler_records_summary_source_ref() -> None:
    assembler = AnswerAssembler()
    main_context = MainContextState(active_goal="compound", active_work_item="compound_query")
    results = [
        {
            "index": 1,
            "task_id": "t1",
            "query": "第一个任务",
            "summary": {"response": "结论一。", "response_style": ""},
            "result_ref": {"result_id": "t1-result", "storage_path": "output/task_results/t1.json"},
        }
    ]

    plan = assembler.build_plan(results=results, main_context=main_context)

    assert plan.segments[0].answer_source == "canonical_summary"
    assert plan.segments[0].answer_ref == ""
    assert plan.source_refs == []


def test_answer_assembler_renders_single_followup_segment_without_numbered_wrapper() -> None:
    assembler = AnswerAssembler()
    main_context = MainContextState(
        active_goal="followup",
        active_work_item="followup_task_result_assembly",
        followup_target_task_ids=["t1"],
    )
    results = [
        {
            "index": 1,
            "task_id": "t1",
            "query": "把这份 PDF 的核心结论压成三条行动建议。",
            "summary": {"response": "先立规则，再建审计，最后做责任归口。", "response_style": ""},
        }
    ]

    plan = assembler.build_plan(results=results, main_context=main_context)
    rendered = assembler.render(plan)

    assert rendered == "先立规则，再建审计，最后做责任归口。"
    assert "1. 把这份 PDF 的核心结论压成三条行动建议。" not in rendered


def main() -> None:
    test_answer_assembler_prefers_summary_and_dedupes()
    test_answer_assembler_compresses_one_sentence_segments()
    test_answer_assembler_can_filter_to_followup_target_tasks()
    test_answer_assembler_never_falls_back_to_raw_content()
    test_answer_assembler_records_summary_source_ref()
    test_answer_assembler_renders_single_followup_segment_without_numbered_wrapper()
    print("ALL PASSED (answer assembler regression)")


if __name__ == "__main__":
    main()
