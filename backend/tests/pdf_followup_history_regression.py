from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from query.continuation_resolver import QueryContinuationResolver
from query.planner import QueryPlanner
from understanding.query_understanding import QueryUnderstanding


def main() -> None:
    planner = QueryPlanner(
        base_dir=ROOT,
        skill_registry=None,
        tool_runtime=SimpleNamespace(registry=None),
    )

    history = [
        {"role": "user", "content": "请帮我详细解读 AI治理报告.pdf"},
        {"role": "assistant", "content": "已分析文件：knowledge/reports/AI治理报告.pdf"},
    ]

    original = QueryUnderstanding(
        intent="knowledge_lookup_query",
        route="rag",
        modality="general",
        should_skip_rag=False,
    )
    continuation_resolver = QueryContinuationResolver(base_dir=ROOT)
    with patch(
        "query.continuation_resolver.PdfAnalysisCatalog.resolve_pdf_path_from_history",
        return_value=ROOT / "knowledge" / "reports" / "AI治理报告.pdf",
    ), patch(
        "query.continuation_resolver.PdfAnalysisCatalog.relative_path",
        side_effect=lambda root_dir, path: str(path.relative_to(root_dir)).replace("\\", "/"),
    ):
        promoted = continuation_resolver.promote_pdf_query("第三页讲了什么？", history, original)

    assert promoted.route == "tool"
    assert promoted.intent == "pdf_page_followup_query"
    assert promoted.modality == "pdf"
    assert promoted.tool_name == "pdf_analysis"
    assert promoted.tool_input["mode"] == "page_read"
    assert promoted.tool_input["path"].endswith("AI治理报告.pdf")
    assert promoted.should_skip_rag is True

    with patch(
        "query.tool_input_resolver.PdfAnalysisCatalog.resolve_pdf_path_from_history",
        return_value=ROOT / "knowledge" / "reports" / "AI治理报告.pdf",
    ), patch(
        "query.tool_input_resolver.PdfAnalysisCatalog.relative_path",
        side_effect=lambda root_dir, path: str(path.relative_to(root_dir)).replace("\\", "/"),
    ):
        plan = planner.build_plan(
            session_id="pdf-followup-regression",
            message="第三页讲了什么？",
            history=history,
        )
    execution = plan.iter_executions()[0]
    assert execution.tool_input["path"].endswith("AI治理报告.pdf")

    print("ALL PASSED (pdf follow-up history regression)")


if __name__ == "__main__":
    main()
