from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from query.tool_output_adapter import build_tool_result_envelope
from tools.definitions import get_tool_definition_map


def main() -> None:
    definitions = get_tool_definition_map()
    assert definitions["read_file"].output_contract.display_mode == "verbatim_text"
    assert definitions["structured_data_analysis"].output_contract.display_mode == "canonical_structured"
    assert definitions["pdf_analysis"].output_contract.display_mode == "finalize_then_display"

    read_file = build_tool_result_envelope(
        "plain source text",
        tool_name="read_file",
    )
    assert read_file.allow_unlabeled_answer is True
    assert read_file.display_text == "plain source text"

    table_dump = build_tool_result_envelope(
        "warehouse,shortage\nA,12",
        tool_name="structured_data_analysis",
    )
    assert table_dump.allow_unlabeled_answer is False
    assert table_dump.display_text.startswith("warehouse")

    structured_summary = build_tool_result_envelope(
        {"summary": "按仓库汇总后，A 仓缺货最多。"},
        tool_name="structured_data_analysis",
    )
    assert structured_summary.allow_unlabeled_answer is True
    assert structured_summary.display_text == "按仓库汇总后，A 仓缺货最多。"

    print("ALL PASSED (tool output contract)")


if __name__ == "__main__":
    main()
