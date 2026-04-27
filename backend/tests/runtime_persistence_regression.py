from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from query.output_boundary import sanitize_visible_assistant_content
from query.runtime_persistence import RuntimePersistenceAssembler
from orchestration.output_commit import OutputCommitGate


def test_output_boundary_strips_pdf_canonical_protocol_block() -> None:
    assert (
        sanitize_visible_assistant_content(
            'PDF_CANONICAL_RESULT::{"status":"degraded","summary":"","pages":[3]}'
        )
        == ""
    )


def test_persistence_gate_rejects_procedural_partial_even_with_tool_receipt() -> None:
    assembler = RuntimePersistenceAssembler(hidden_skill_notice="[hidden]")

    gated = assembler.apply_assistant_persistence_gate(
        "我先读取文档，同时查看当前目录结构，以便确认 Python 脚本的执行环境。",
        [{"tool": "read_file", "input": '{"path":"docs"}', "output": "Read failed: path is a directory."}],
    )

    assert gated == "当前还没有形成真实查询结果。"


def test_output_commit_gate_projects_persist_candidates_without_takeover() -> None:
    gate = OutputCommitGate()

    plan = gate.build_plan(
        done_event={
            "answer_channel": "answer_candidate",
            "answer_source": "segment.visible_text",
            "answer_persist_policy": "persist_canonical",
            "main_context": {"active_goal": "整理报告"},
            "task_summary_refs": [{"task_id": "task:1"}],
        },
        assistant_messages=[{"role": "assistant", "content": "结论"}],
        segment_count=1,
        title_seed="整理报告",
    )

    assert plan.diagnostics["phase"] == "8L"
    assert plan.diagnostics["state"] == "commit_candidates_projected"
    assert plan.diagnostics["takeover_allowed"] is False
    assert plan.diagnostics["assistant_message_count"] == 1
    assert {item["candidate_type"] for item in plan.diagnostics["candidates"]} == {
        "state_memory_projection",
        "session_transcript",
        "post_turn_refresh",
    }
    assert plan.projection["task_summary_refs"] == [{"task_id": "task:1"}]


def main() -> None:
    test_output_boundary_strips_pdf_canonical_protocol_block()
    test_persistence_gate_rejects_procedural_partial_even_with_tool_receipt()
    test_output_commit_gate_projects_persist_candidates_without_takeover()
    print("ALL PASSED (runtime persistence regression)")


if __name__ == "__main__":
    main()
