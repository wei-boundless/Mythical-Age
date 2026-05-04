from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from capability_system.units.tools.pdf_analysis_tool import PdfAnalysisTool
from capability_system.units.tools.search_knowledge_tool import SearchKnowledgeBaseTool
from capability_system.units.tools.structured_data_analysis_tool import StructuredDataAnalysisTool


def main() -> None:
    rag = SearchKnowledgeBaseTool(root_dir=ROOT)
    shareholder_result = rag.invoke({"query": "从本地知识库里查一下三一重工前三大股东", "top_k": 3})
    assert "三一集团有限公司" in shareholder_result
    assert "香港中央结算" in shareholder_result
    assert "梁稳根" in shareholder_result
    assert "航天动力" not in shareholder_result

    pdf = PdfAnalysisTool(root_dir=ROOT)
    pdf_result = pdf.invoke(
        {
            "query": "这份白皮书主要讲什么",
            "path": "knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf",
            "mode": "document",
        }
    )
    assert "PDF_CANONICAL_RESULT::" in pdf_result
    assert "AI治理" in pdf_result
    assert "pages" in pdf_result

    finance_pdf_result = pdf.invoke(
        {
            "query": "总结这份PDF的核心内容和关键结论，重点关注营业收入、净利润和现金流",
            "path": "knowledge/Financial Report Data/三一重工 2025 Q3.pdf",
            "mode": "document",
            "max_chunks": 4,
        }
    )
    assert "PDF_CANONICAL_RESULT::" in finance_pdf_result
    assert '"status":"ok"' in finance_pdf_result
    assert "营业收入：65,741,014，57,890,665" in finance_pdf_result
    assert "经营活动现金流量净额：14,547,126，12,375,235" in finance_pdf_result

    structured = StructuredDataAnalysisTool(root_dir=ROOT)
    row_count_result = structured.invoke(
        {
            "query": "员工表一共有多少行？",
            "path": "knowledge/E-commerce Data/employees.xlsx",
        }
    )
    assert "总行数：200" in row_count_result
    assert "前 10 行预览" not in row_count_result

    salary_result = structured.invoke(
        {
            "query": "薪水最高的前五名员工是谁？",
            "path": "knowledge/E-commerce Data/employees.xlsx",
            "limit": 5,
        }
    )
    assert "查询模式：记录排序" in salary_result
    assert "E-0074" in salary_result
    assert "罗凯" in salary_result
    assert "34900" in salary_result

    shortage_result = structured.invoke({"query": "从我的数据库中查询哪些商品库存不足"})
    assert "数据源：inventory.xlsx" in shortage_result
    assert "缺货商品数：33" in shortage_result
    assert "SKU-0069" in shortage_result

    sales_result = structured.invoke({"query": "分析 sales_orders.xlsx 销售前五的有哪些"})
    assert "数据源：sales_orders.xlsx" in sales_result
    assert "前 5 条记录" in sales_result
    assert "总金额" in sales_result

    print("ALL PASSED (capability quality)")


if __name__ == "__main__":
    main()
