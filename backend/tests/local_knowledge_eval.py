from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from RAG.reranker import NoopReranker
from retrieval.service import RetrievalService


def _build_queries() -> list[dict[str, object]]:
    return [
        {"id": "ai_agent_trend", "query": "AI Agent 智能体技术发展趋势有哪些？", "accepted": ["2026年AI Agent智能体技术发展报告.pdf"]},
        {"id": "ai_marketing_fmcg", "query": "快消行业 AI 营销增长有哪些关键抓手？", "accepted": ["2026年快消行业AI营销增长白皮书.pdf"]},
        {"id": "ai_glasses", "query": "AI 眼镜的关键技术和产业生态怎么看？", "accepted": ["AI眼镜关键技术与产业生态研究报告（2025年）.pdf"]},
        {"id": "ai_governance_filing", "query": "生成式人工智能服务合规备案有哪些关键要求？", "accepted": ["生成式人工智能服务合规备案指南（2026年）.pdf"]},
        {"id": "ai_security_governance", "query": "人工智能安全治理的重点方向有哪些？", "accepted": ["人工智能安全治理研究报告（2025年）.pdf"]},
        {"id": "edu_ai", "query": "职业教育里人工智能应用的发展现状和方向是什么？", "accepted": ["清华大学：职业教育人工智能应用发展报告（2024-2025）.pdf"]},
        {"id": "openai_report", "query": "为什么说 OpenAI 是大模型王者并引领 AGI 之路？", "accepted": ["OpenAI深度报告：大模型王者，引领AGI之路.pdf"]},
        {"id": "five_phase", "query": "第五范式怎么看人工智能驱动的科技创新？", "accepted": ["2025年第五范式-人工智能驱动的科技创新报告.pdf"]},
        {"id": "chongqing_cases", "query": "重庆市有哪些典型的人工智能应用场景案例？", "accepted": ["2025年度重庆市人工智能应用场景典型案例集（压缩版）.pdf"]},
        {"id": "inventory_restock", "query": "哪些仓库的库存已经低于补货线？", "accepted": ["inventory.xlsx"]},
        {"id": "employees_salary", "query": "薪资最高的员工有哪些？", "accepted": ["employees.xlsx"]},
        {"id": "customers_city", "query": "企业客户主要分布在哪些城市？", "accepted": ["customers.xlsx"]},
        {"id": "sales_order_status", "query": "哪些订单处于退款中或已取消？", "accepted": ["sales_orders.xlsx"]},
        {"id": "faq_delivery", "query": "订单显示已发货后，一般多久能收到包裹？", "accepted": ["faq.json"]},
        {"id": "cors_basic", "query": "什么是 CORS？", "accepted": ["cors.md"]},
        {"id": "csrf_basic", "query": "什么是 CSRF 攻击？", "accepted": ["CSRF.txt"]},
        {"id": "xss_defense", "query": "XSS 攻击有哪些常见类型和防护方法？", "accepted": ["XSS.md"]},
        {"id": "aerospace_power_q3", "query": "航天动力 2025 年第三季度的营业收入和净利润怎么样？", "accepted": ["航天动力 2025 Q3.pdf", "航天动力_2025_Q3.txt"]},
        {"id": "sany_q3", "query": "三一重工 2025 年第三季度业绩怎么样？", "accepted": ["三一重工 2025 Q3.pdf", "三一重工_2025_Q3.txt"]},
        {"id": "saic_q3", "query": "上汽集团 2025 年第三季度财务表现如何？", "accepted": ["上汽集团 2025 Q3.pdf"]},
    ]


def _reciprocal_rank(sources: list[str], accepted: list[str]) -> float:
    for index, source in enumerate(sources, start=1):
        if any(token in source for token in accepted):
            return 1.0 / index
    return 0.0


def _hit_at(sources: list[str], accepted: list[str], top_k: int) -> int:
    window = sources[:top_k]
    return int(any(any(token in source for token in accepted) for source in window))


def _match_rank(sources: list[str], accepted: list[str]) -> int | None:
    for index, source in enumerate(sources, start=1):
        if any(token in source for token in accepted):
            return index
    return None


def _build_baseline_service(base_dir: Path) -> RetrievalService:
    service = RetrievalService(base_dir)
    settings = SimpleNamespace(rerank_enabled=False, rerank_top_n=8, rerank_candidate_pool=20)
    service._settings = settings
    _ = service.router
    service.router._settings = settings
    service.router._reranker = NoopReranker()
    return service


def _build_rerank_service(base_dir: Path) -> RetrievalService:
    return RetrievalService(base_dir)


def _run_eval(*, base_dir: Path, top_k: int) -> dict[str, object]:
    queries = _build_queries()
    baseline_service = _build_baseline_service(base_dir)
    rerank_service = _build_rerank_service(base_dir)
    results: list[dict[str, object]] = []

    for item in queries:
        accepted = list(item["accepted"])
        query = str(item["query"])
        row: dict[str, object] = {
            "id": item["id"],
            "query": query,
            "accepted": accepted,
        }
        for label, service in (("baseline", baseline_service), ("rerank", rerank_service)):
            started = time.perf_counter()
            payload = service.retrieve(query, top_k=top_k)
            elapsed = time.perf_counter() - started
            sources = [str(hit.get("source", "")) for hit in payload]
            row[label] = {
                "seconds": round(elapsed, 4),
                "top_sources": sources,
                "match_rank": _match_rank(sources, accepted),
                "hit_at_1": _hit_at(sources, accepted, 1),
                "hit_at_3": _hit_at(sources, accepted, 3),
                "hit_at_5": _hit_at(sources, accepted, 5),
                "mrr_at_5": _reciprocal_rank(sources, accepted),
            }
        results.append(row)

    summary: dict[str, dict[str, object]] = {}
    for label in ("baseline", "rerank"):
        summary[label] = {
            "queries": len(results),
            "hit_at_1": round(sum(float(result[label]["hit_at_1"]) for result in results) / len(results), 4),
            "hit_at_3": round(sum(float(result[label]["hit_at_3"]) for result in results) / len(results), 4),
            "hit_at_5": round(sum(float(result[label]["hit_at_5"]) for result in results) / len(results), 4),
            "mrr_at_5": round(sum(float(result[label]["mrr_at_5"]) for result in results) / len(results), 4),
            "mean_seconds": round(sum(float(result[label]["seconds"]) for result in results) / len(results), 4),
        }

    return {
        "artifact_schema_version": "local_knowledge_eval_v1",
        "collection": "knowledge",
        "comparison": "baseline_vs_configured_rerank",
        "summary": summary,
        "results": results,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate baseline vs configured rerank on the local knowledge collection.")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--output", default="")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    payload = _run_eval(base_dir=BACKEND_DIR, top_k=max(int(args.top_k or 1), 1))
    output_path = Path(args.output) if str(args.output).strip() else BACKEND_DIR.parent / "output" / "local_knowledge_eval_latest.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    print(f"artifact={output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
