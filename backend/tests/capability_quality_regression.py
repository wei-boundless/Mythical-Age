from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evidence import MCPRequest
from evidence.output_policy import RAGEvidenceOutputPolicy
from evidence.pdf_worker import PDFWorker
from evidence.retrieval_worker import RetrievalWorker
from evidence.structured_data_worker import StructuredDataWorker
from runtime.model_gateway.model_runtime import ModelRuntimeError
from response_system import build_rag_evidence_pack


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
    assert retrieval_result.diagnostics["retrieval"]["result_count"] == 3

    degraded_result = RetrievalWorker(
        retrieval_service=SimpleNamespace(
            retrieve_execution=lambda query, top_k=3: SimpleNamespace(
                results=(),
                status="error",
                diagnostics={
                    "result_count": 0,
                    "retrieval_failure": {"failure_stage": "backend", "error_type": "RuntimeError"},
                },
                degraded_reason_typed="retrieval_execution_failed",
            )
        )
    ).run(SimpleNamespace(query="失败的检索"))
    assert degraded_result.status == "degraded"
    assert degraded_result.diagnostics["degraded_reason_typed"] == "retrieval_execution_failed"

    pdf = PDFWorker(root_dir=ROOT)
    pdf_result = _run(
        pdf.run(
            MCPRequest(
                request_id="pdf:summary",
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

    pdf_action_result = _run(
        pdf.run(
            MCPRequest(
                request_id="pdf:actions",
                query="把这份 PDF 的结论压成三条行动建议，每条都要带行动动词。",
                bindings={"active_pdf": "knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf"},
                constraints={"mode": "document"},
            )
        )
    )
    assert pdf_action_result.status == "ok"
    assert pdf_action_result.canonical_result is not None
    pdf_action_answer = pdf_action_result.canonical_result.answer
    assert "三条行动建议" in pdf_action_answer
    assert "建立" in pdf_action_answer
    assert "推进" in pdf_action_answer
    assert "统一" in pdf_action_answer

    finance_pdf_result = _run(
        pdf.run(
            MCPRequest(
                request_id="pdf:finance",
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
                request_id="sheet:row-count",
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
                request_id="sheet:salary-top5",
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
                request_id="sheet:inventory-shortage",
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

    warehouse_gap_result = _run(
        structured.run(
            MCPRequest(
                request_id="sheet:inventory-warehouse-gap",
                query="继续沿着 inventory.xlsx，只按缺口总量汇总仓库，并给我缺口最高的前三个仓库。",
                bindings={"active_dataset": "knowledge/E-commerce Data/inventory.xlsx"},
            )
        )
    )
    assert warehouse_gap_result.canonical_result is not None
    warehouse_gap_answer = warehouse_gap_result.canonical_result.answer
    assert "查询模式：分组聚合排名" in warehouse_gap_answer
    assert "排名维度：仓库" in warehouse_gap_answer
    assert "缺口" in warehouse_gap_answer

    no_gap_result = _run(
        structured.run(
            MCPRequest(
                request_id="sheet:inventory-no-gap-warehouse",
                query="哪些仓库完全没有缺口？如果没有就直接说没有。",
                bindings={"active_dataset": "knowledge/E-commerce Data/inventory.xlsx"},
            )
        )
    )
    assert no_gap_result.canonical_result is not None
    no_gap_answer = no_gap_result.canonical_result.answer
    assert "数据源：inventory.xlsx" in no_gap_answer
    assert "没有完全没有缺口的仓库" in no_gap_answer

    verbose_no_gap_result = _run(
        structured.run(
            MCPRequest(
                request_id="sheet:inventory-no-gap-warehouse-verbose",
                query=(
                    "读取 knowledge/E-commerce Data/inventory.xlsx 全部数据。\n\n"
                    "任务：找出哪些仓库完全没有库存缺口。\n\n"
                    "缺口定义：stock_on_hand < reorder_level 即为有缺口。完全没有缺口的仓库，"
                    "是指该仓库下所有 SKU 的 stock_on_hand 都 >= reorder_level。\n\n"
                    "请按以下步骤：\n"
                    "1. 读取全部 200 行数据\n"
                    "2. 按 warehouse 分组\n"
                    "3. 对每个仓库，检查是否存在任何一行 stock_on_hand < reorder_level\n"
                    "4. 列出所有完全没有缺口的仓库名称\n"
                    "5. 如果没有这样的仓库，直接说\"没有\"\n"
                ),
                bindings={"active_dataset": "knowledge/E-commerce Data/inventory.xlsx"},
            )
        )
    )
    assert verbose_no_gap_result.canonical_result is not None
    verbose_no_gap_answer = verbose_no_gap_result.canonical_result.answer
    assert "没有完全没有缺口的仓库" in verbose_no_gap_answer
    assert "总行数" not in verbose_no_gap_answer

    sales_result = _run(
        structured.run(
            MCPRequest(
                request_id="sheet:sales-top5",
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

    finalization = _run(
        RAGEvidenceOutputPolicy(
            model_runtime=SimpleNamespace(
                invoke_messages=_raise_model_runtime_error,
            )
        ).rewrite_rag_answer_with_model(
            evidence_pack=build_rag_evidence_pack(
                user_query="总结一下",
                retrieval_results=[
                    {
                        "source": "knowledge/a.md",
                        "text": "这是用于验证最终答案整合失败路径的检索证据内容，长度足够，应该进入最终整理阶段。",
                    }
                ],
                max_items=1,
            )
        )
    )
    assert finalization.status == "error"
    assert finalization.degraded_reason_typed == "rag_finalizer_model_error"

    print("ALL PASSED (capability quality)")


def _run(awaitable):
    return asyncio.run(awaitable)


async def _raise_model_runtime_error(_messages):
    raise ModelRuntimeError(
        code="provider_error",
        provider="test",
        model="test-model",
        detail="boom",
        retryable=False,
        user_message="boom",
    )


if __name__ == "__main__":
    main()
