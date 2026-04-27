from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from query.output_boundary import sanitize_visible_assistant_content
from query.runtime_persistence import RuntimePersistenceAssembler
from orchestration import CommitCandidate


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


def test_commit_candidate_stays_denied_after_old_commit_wiring_clear() -> None:
    candidate = CommitCandidate(
        candidate_id="commit:session:1",
        commit_type="session_message",
        producer="query.runtime",
        payload={"messages": [{"role": "assistant", "content": "结论"}]},
    )

    assert candidate.allowed is False
    assert candidate.reason == "pending_commit_gate"


def main() -> None:
    test_output_boundary_strips_pdf_canonical_protocol_block()
    test_persistence_gate_rejects_procedural_partial_even_with_tool_receipt()
    test_commit_candidate_stays_denied_after_old_commit_wiring_clear()
    print("ALL PASSED (runtime persistence regression)")


if __name__ == "__main__":
    main()
