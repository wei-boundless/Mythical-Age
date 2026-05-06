from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evidence import MCPRequest
from evidence.pdf_worker import PDFWorker
from evidence.retrieval_worker import RetrievalWorker
from evidence.structured_data_worker import StructuredDataWorker


def main() -> None:
    retrieval_worker = RetrievalWorker(
        retrieval_service=SimpleNamespace(
            retrieve=lambda query, top_k=3: [
                {
                    "text": "三一集团有限公司是三一重工第一大股东。",
                    "source": "knowledge/financial/shareholders.md",
                    "score": 0.98,
                    "metadata": {"title": "三一重工股东结构"},
                },
                {
                    "text": "香港中央结算有限公司位列前三大股东之一。",
                    "source": "knowledge/financial/shareholders.md",
                    "score": 0.95,
                    "metadata": {"title": "三一重工股东结构"},
                },
                {
                    "text": "梁稳根也位列前三大股东。",
                    "source": "knowledge/financial/shareholders.md",
                    "score": 0.93,
                    "metadata": {"title": "三一重工股东结构"},
                },
            ]
        )
    )
    retrieval_result = retrieval_worker.run(
        SimpleNamespace(query="从本地知识库里查一下三一重工前三大股东")
    )
    assert retrieval_result.status == "ok"
    assert retrieval_result.mcp_name == "retrieval"
    assert retrieval_result.evidence_envelope is not None
    evidence_text = " ".join(item.text for item in retrieval_result.evidence_envelope.evidence_items)
    assert "三一集团有限公司" in evidence_text
    assert "香港中央结算有限公司" in evidence_text
    assert "梁稳根" in evidence_text
    assert "航天动力" not in evidence_text

    pdf = PDFWorker(root_dir=ROOT)
    pdf_result = _run(
        pdf.run(
            MCPRequest(
                query="这份白皮书主要讲什么",
                bindings={"active_pdf": "knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf"},
                constraints={"mode": "document"},
            )
        )
    )
    assert pdf_result.status == "ok"
    assert pdf_result.canonical_result is not None
    assert "AI治理" in pdf_result.canonical_result.answer
    assert pdf_result.canonical_result.result_handle_ids

    finance_pdf_result = _run(
        pdf.run(
            MCPRequest(
                query="总结这份PDF的核心内容和关键结论，重点关注营业收入、净利润和现金流",
                bindings={"active_pdf": "knowledge/Financial Report Data/三一重工 2025 Q3.pdf"},
                constraints={"mode": "document", "max_chunks": 4},
            )
        )
    )
    assert finance_pdf_result.status == "ok"
    assert finance_pdf_result.canonical_result is not None
    finance_answer = finance_pdf_result.canonical_result.answer
    assert "营业收入：65,741,014，57,890,665" in finance_answer
    assert "经营活动现金流量净额：14,547,126，12,375,235" in finance_answer

    structured = StructuredDataWorker(root_dir=ROOT)
    row_count_result = _run(
        structured.run(
            MCPRequest(
                query="员工表一共有多少行？",
                bindings={"active_dataset": "knowledge/E-commerce Data/employees.xlsx"},
            )
        )
    )
    assert row_count_result.canonical_result is not None
    assert "总行数：200" in row_count_result.canonical_result.answer
    assert "前 10 行预览" not in row_count_result.canonical_result.answer

    salary_result = _run(
        structured.run(
            MCPRequest(
                query="薪水最高的前五名员工是谁？",
                bindings={"active_dataset": "knowledge/E-commerce Data/employees.xlsx"},
                constraints={"semantic_hints": {"limit": 5}},
            )
        )
    )
    assert salary_result.canonical_result is not None
    salary_answer = salary_result.canonical_result.answer
    assert "查询模式：记录排序" in salary_answer
    assert "E-0074" in salary_answer
    assert "罗凯" in salary_answer
    assert "34900" in salary_answer

    shortage_result = _run(
        structured.run(
            MCPRequest(
                query="从我的数据库中查询哪些商品库存不足",
                bindings={"active_dataset": "knowledge/E-commerce Data/inventory.xlsx"},
            )
        )
    )
    assert shortage_result.canonical_result is not None
    shortage_answer = shortage_result.canonical_result.answer
    assert "数据源：inventory.xlsx" in shortage_answer
    assert "缺货商品数：33" in shortage_answer
    assert "SKU-0069" in shortage_answer

    sales_result = _run(
        structured.run(
            MCPRequest(
                query="分析 sales_orders.xlsx 销售前五的有哪些",
                bindings={"active_dataset": "knowledge/E-commerce Data/sales_orders.xlsx"},
            )
        )
    )
    assert sales_result.canonical_result is not None
    sales_answer = sales_result.canonical_result.answer
    assert "数据源：sales_orders.xlsx" in sales_answer
    assert "前 5 条记录" in sales_answer
    assert "总金额" in sales_answer

    print("ALL PASSED (capability quality)")


def _run(awaitable):
    return asyncio.run(awaitable)


if __name__ == "__main__":
    main()
