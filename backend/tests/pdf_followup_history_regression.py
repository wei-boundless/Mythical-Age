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
from query.tool_input_resolver import ToolInputResolver
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
    promoted = continuation_resolver.promote_pdf_query("第三页讲了什么？", history, original)

    assert promoted.route == "rag"
    assert promoted.tool_name is None
    assert promoted.tool_input == {}
    assert promoted.should_skip_rag is False

    plan = planner.build_plan(
        session_id="pdf-followup-regression",
        message="第三页讲了什么？",
        history=history,
    )
    execution = plan.iter_executions()[0]
    assert "path" not in execution.tool_input

    resolver = ToolInputResolver(base_dir=ROOT)
    explicit_message = "现在打开 knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf，给我一个全文总览。"
    explicit_plan = SimpleNamespace(
        message=explicit_message,
        query_understanding=QueryUnderstanding(
            route="tool",
            tool_name="pdf_analysis",
            tool_input={"query": explicit_message, "mode": "document"},
        ),
        structured_binding=None,
    )
    with patch(
        "query.tool_input_resolver.PdfAnalysisCatalog.resolve_pdf_path_from_history",
        return_value=ROOT / "knowledge" / "AI Knowledge" / "2026AI应用专题：各大厂新模型持续迭代，重视AI应用板块投资机会.pdf",
    ):
        explicit_tool_input = resolver.resolve(plan=explicit_plan, history=history)
    assert explicit_tool_input["path"] == "knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf"

    non_explicit_plan = SimpleNamespace(
        message="请继续解读第三页。",
        query_understanding=QueryUnderstanding(
            route="tool",
            tool_name="pdf_analysis",
            tool_input={"query": "请继续解读第三页。", "mode": "page"},
        ),
        structured_binding=None,
    )
    with patch(
        "query.tool_input_resolver.PdfAnalysisCatalog.resolve_pdf_path_from_history",
        return_value=ROOT / "knowledge" / "reports" / "AI治理报告.pdf",
    ):
        non_explicit_tool_input = resolver.resolve(plan=non_explicit_plan, history=history)
    assert "path" not in non_explicit_tool_input

    print("ALL PASSED (pdf follow-up history regression)")


if __name__ == "__main__":
    main()
