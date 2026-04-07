from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

from llama_index.core import Document, Settings as LlamaSettings, VectorStoreIndex
from llama_index.core.node_parser import SentenceSplitter


BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from config import get_settings
from embedding_compat import build_embedding_model
from RAG.hybrid import BM25Index, build_searchable_text
from RAG.eval_retrieval import _dense_payload, _hybrid_fuse, _load_dataset
from RAG.query_rewriter import QueryRewriter
from RAG.reranker import HeuristicReranker, build_reranker


@dataclass(slots=True)
class QueryRecord:
    qid: str
    query: str
    rewritten_query: str
    dense_payload: list[dict[str, Any]]
    hybrid_payload: list[dict[str, Any]]
    dense_seconds: float
    hybrid_seconds: float


@dataclass(slots=True)
class ConfigResult:
    name: str
    candidate_source: str
    reranker: str
    metrics: dict[str, Any]
    latency: dict[str, Any]
    backend_counts: dict[str, int]
    sample_improvements: list[dict[str, Any]]
    sample_regressions: list[dict[str, Any]]


class NoopReranker:
    def rerank_dict_results(
        self,
        *,
        query: str,
        results: list[dict[str, Any]],
        text_key: str = "text",
        metadata_key: str = "metadata",
    ) -> list[dict[str, Any]]:
        return [dict(item) for item in results]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Deep RAG retrieval benchmark with rerank comparisons.")
    parser.add_argument("--dataset-dir", default="EcomRetrieval", help="Benchmark corpus directory")
    parser.add_argument("--qrels-dir", default="EcomRetrieval-qrels", help="Benchmark qrels directory")
    parser.add_argument("--target-docs", type=int, default=5000, help="Focused subset size including all gold docs")
    parser.add_argument("--max-queries", type=int, default=300, help="Deterministic query sample size")
    parser.add_argument("--candidate-top-k", type=int, default=20, help="Candidate depth before rerank")
    parser.add_argument("--metric-top-k", type=int, default=10, help="Depth for recall / mrr / ndcg metrics")
    parser.add_argument("--stability-probe-queries", type=int, default=30, help="Repeated remote-rerank probe size")
    parser.add_argument("--seed", type=int, default=42, help="Deterministic seed")
    parser.add_argument("--output", default="", help="Optional artifact output path")
    return parser


def _artifact_path(path: str | None) -> Path:
    if path:
        return Path(path)
    stamp = date.today().strftime("%Y%m%d")
    return BACKEND_DIR / "tests" / "_artifacts" / f"rag_retrieval_deep_experiment_{stamp}.json"


def _build_qrel_scores(rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    grouped: dict[str, dict[str, int]] = {}
    for row in rows:
        qid = str(row.get("qid", "")).strip()
        pid = str(row.get("pid", "")).strip()
        score = int(row.get("score", 0) or 0)
        if not qid or not pid or score <= 0:
            continue
        grouped.setdefault(qid, {})[pid] = score
    return grouped


def _focused_corpus(
    corpus_rows: list[dict[str, Any]],
    qrel_scores: dict[str, dict[str, int]],
    *,
    target_docs: int,
    seed: int,
) -> list[dict[str, Any]]:
    rows_by_id = {
        str(row.get("id", "")).strip(): row
        for row in corpus_rows
        if str(row.get("id", "")).strip() and str(row.get("text", "")).strip()
    }
    gold_doc_ids = sorted({pid for mapping in qrel_scores.values() for pid in mapping})
    gold_rows = [rows_by_id[doc_id] for doc_id in gold_doc_ids if doc_id in rows_by_id]
    if len(gold_rows) > target_docs:
        raise RuntimeError("target_docs is smaller than the number of gold documents required by qrels")

    negatives = [
        row
        for doc_id, row in rows_by_id.items()
        if doc_id not in set(gold_doc_ids)
    ]
    remaining = max(target_docs - len(gold_rows), 0)
    rng = random.Random(seed)
    negative_rows = rng.sample(negatives, remaining)
    selected = gold_rows + negative_rows
    selected.sort(key=lambda row: str(row.get("id", "")))
    return selected


def _sample_queries(
    queries_rows: list[dict[str, Any]],
    qrel_scores: dict[str, dict[str, int]],
    *,
    max_queries: int,
    seed: int,
) -> list[dict[str, Any]]:
    filtered = [
        row
        for row in queries_rows
        if str(row.get("id", "")).strip() in qrel_scores and str(row.get("text", "")).strip()
    ]
    if max_queries <= 0 or max_queries >= len(filtered):
        return filtered
    rng = random.Random(seed)
    sampled = rng.sample(filtered, max_queries)
    sampled.sort(key=lambda row: str(row.get("id", "")))
    return sampled


def _build_documents(corpus_rows: list[dict[str, Any]]) -> list[Document]:
    documents: list[Document] = []
    for row in corpus_rows:
        doc_id = str(row.get("id", "")).strip()
        text = str(row.get("text", "")).strip()
        if not doc_id or not text:
            continue
        documents.append(
            Document(
                text=text,
                metadata={
                    "doc_id": doc_id,
                    "source": f"corpus:{doc_id}",
                    "collection": "benchmark",
                    "modality": "text",
                },
            )
        )
    return documents


def _prepare_query_records(
    index: VectorStoreIndex,
    docs: list[Document],
    queries: list[dict[str, Any]],
    *,
    candidate_top_k: int,
) -> list[QueryRecord]:
    rewriter = QueryRewriter()
    retriever = index.as_retriever(similarity_top_k=max(candidate_top_k, 8))
    bm25_index = BM25Index.from_texts(
        [
            build_searchable_text(
                doc.text,
                source=str(doc.metadata.get("source", "")),
                metadata=dict(doc.metadata),
            )
            for doc in docs
        ]
    )

    records: list[QueryRecord] = []
    for row in queries:
        qid = str(row.get("id", "")).strip()
        query = str(row.get("text", "")).strip()
        rewritten = rewriter.rewrite(query).rewritten_query

        dense_started = time.perf_counter()
        dense_payload = _dense_payload(retriever.retrieve(rewritten))[:candidate_top_k]
        dense_seconds = time.perf_counter() - dense_started

        hybrid_started = time.perf_counter()
        hybrid_payload = _hybrid_fuse(
            query=query,
            dense_payload=dense_payload,
            docs=docs,
            top_k=candidate_top_k,
            bm25_index=bm25_index,
        )
        hybrid_seconds = time.perf_counter() - hybrid_started

        records.append(
            QueryRecord(
                qid=qid,
                query=query,
                rewritten_query=rewritten,
                dense_payload=dense_payload,
                hybrid_payload=hybrid_payload,
                dense_seconds=round(dense_seconds, 6),
                hybrid_seconds=round(hybrid_seconds, 6),
            )
        )
    return records


def _doc_ids(results: list[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    for item in results:
        metadata = dict(item.get("metadata") or {})
        ids.append(str(metadata.get("doc_id", "")).strip())
    return ids


def _recall_at_k(doc_ids: list[str], gold_scores: dict[str, int], k: int) -> float:
    if not gold_scores:
        return 0.0
    retrieved = sum(1 for doc_id in doc_ids[:k] if doc_id in gold_scores)
    return retrieved / max(len(gold_scores), 1)


def _precision_at_k(doc_ids: list[str], gold_scores: dict[str, int], k: int) -> float:
    if k <= 0:
        return 0.0
    retrieved = sum(1 for doc_id in doc_ids[:k] if doc_id in gold_scores)
    return retrieved / k


def _mrr_at_k(doc_ids: list[str], gold_scores: dict[str, int], k: int) -> float:
    for rank, doc_id in enumerate(doc_ids[:k], start=1):
        if doc_id in gold_scores:
            return 1.0 / rank
    return 0.0


def _average_precision_at_k(doc_ids: list[str], gold_scores: dict[str, int], k: int) -> float:
    if not gold_scores:
        return 0.0
    hits = 0
    precision_sum = 0.0
    for rank, doc_id in enumerate(doc_ids[:k], start=1):
        if doc_id not in gold_scores:
            continue
        hits += 1
        precision_sum += hits / rank
    return precision_sum / max(len(gold_scores), 1)


def _ndcg_at_k(doc_ids: list[str], gold_scores: dict[str, int], k: int) -> float:
    dcg = 0.0
    for rank, doc_id in enumerate(doc_ids[:k], start=1):
        rel = float(gold_scores.get(doc_id, 0))
        if rel <= 0:
            continue
        dcg += (2**rel - 1) / math.log2(rank + 1)

    ideal_rels = sorted((float(score) for score in gold_scores.values() if score > 0), reverse=True)[:k]
    idcg = 0.0
    for rank, rel in enumerate(ideal_rels, start=1):
        idcg += (2**rel - 1) / math.log2(rank + 1)
    return dcg / idcg if idcg > 0 else 0.0


def _metrics_for_rankings(
    rankings: dict[str, list[dict[str, Any]]],
    qrel_scores: dict[str, dict[str, int]],
    *,
    metric_top_k: int,
) -> dict[str, Any]:
    hit1 = 0
    hit3 = 0
    hit5 = 0
    hit10 = 0
    recall5: list[float] = []
    recall10: list[float] = []
    precision5: list[float] = []
    precision10: list[float] = []
    mrr10: list[float] = []
    ap10: list[float] = []
    ndcg10: list[float] = []

    for qid, results in rankings.items():
        gold = qrel_scores.get(qid, {})
        doc_ids = _doc_ids(results)
        if any(doc_id in gold for doc_id in doc_ids[:1]):
            hit1 += 1
        if any(doc_id in gold for doc_id in doc_ids[:3]):
            hit3 += 1
        if any(doc_id in gold for doc_id in doc_ids[:5]):
            hit5 += 1
        if any(doc_id in gold for doc_id in doc_ids[: min(metric_top_k, 10)]):
            hit10 += 1
        recall5.append(_recall_at_k(doc_ids, gold, 5))
        recall10.append(_recall_at_k(doc_ids, gold, metric_top_k))
        precision5.append(_precision_at_k(doc_ids, gold, 5))
        precision10.append(_precision_at_k(doc_ids, gold, metric_top_k))
        mrr10.append(_mrr_at_k(doc_ids, gold, metric_top_k))
        ap10.append(_average_precision_at_k(doc_ids, gold, metric_top_k))
        ndcg10.append(_ndcg_at_k(doc_ids, gold, metric_top_k))

    total = max(len(rankings), 1)
    return {
        "queries_evaluated": len(rankings),
        "accuracy_at_1": round(hit1 / total, 4),
        "hit_at_3": round(hit3 / total, 4),
        "hit_at_5": round(hit5 / total, 4),
        "hit_at_10": round(hit10 / total, 4),
        "recall_at_5": round(statistics.mean(recall5), 4) if recall5 else 0.0,
        "recall_at_10": round(statistics.mean(recall10), 4) if recall10 else 0.0,
        "precision_at_5": round(statistics.mean(precision5), 4) if precision5 else 0.0,
        "precision_at_10": round(statistics.mean(precision10), 4) if precision10 else 0.0,
        "mrr_at_10": round(statistics.mean(mrr10), 4) if mrr10 else 0.0,
        "map_at_10": round(statistics.mean(ap10), 4) if ap10 else 0.0,
        "ndcg_at_10": round(statistics.mean(ndcg10), 4) if ndcg10 else 0.0,
    }


def _evaluate_config(
    *,
    name: str,
    candidate_source: str,
    reranker_name: str,
    reranker,
    records: list[QueryRecord],
    qrel_scores: dict[str, dict[str, int]],
    metric_top_k: int,
) -> tuple[ConfigResult, dict[str, list[dict[str, Any]]]]:
    rankings: dict[str, list[dict[str, Any]]] = {}
    rerank_seconds: list[float] = []
    retrieval_seconds: list[float] = []
    backend_counts: Counter[str] = Counter()

    for record in records:
        base_results = record.dense_payload if candidate_source == "dense" else record.hybrid_payload
        retrieval_time = record.dense_seconds if candidate_source == "dense" else record.dense_seconds + record.hybrid_seconds

        started = time.perf_counter()
        ranked = reranker.rerank_dict_results(query=record.query, results=base_results)
        rerank_time = time.perf_counter() - started
        rerank_seconds.append(rerank_time)
        retrieval_seconds.append(retrieval_time)
        rankings[record.qid] = ranked[:metric_top_k]

        for item in ranked[: min(len(ranked), 3)]:
            backend = str(item.get("rerank_backend", "none") or "none")
            backend_counts[backend] += 1

    metrics = _metrics_for_rankings(rankings, qrel_scores, metric_top_k=metric_top_k)
    result = ConfigResult(
        name=name,
        candidate_source=candidate_source,
        reranker=reranker_name,
        metrics=metrics,
        latency={
            "mean_retrieval_seconds": round(statistics.mean(retrieval_seconds), 4) if retrieval_seconds else 0.0,
            "mean_rerank_seconds": round(statistics.mean(rerank_seconds), 4) if rerank_seconds else 0.0,
            "mean_total_seconds": round(
                statistics.mean([a + b for a, b in zip(retrieval_seconds, rerank_seconds, strict=False)]),
                4,
            ) if retrieval_seconds else 0.0,
        },
        backend_counts=dict(backend_counts),
        sample_improvements=[],
        sample_regressions=[],
    )
    return result, rankings


def _compare_rankings(
    *,
    base_name: str,
    target_name: str,
    base_rankings: dict[str, list[dict[str, Any]]],
    target_rankings: dict[str, list[dict[str, Any]]],
    qrel_scores: dict[str, dict[str, int]],
    query_texts: dict[str, str],
) -> dict[str, Any]:
    improved = 0
    regressed = 0
    unchanged = 0
    sample_improvements: list[dict[str, Any]] = []
    sample_regressions: list[dict[str, Any]] = []

    def first_relevant_rank(results: list[dict[str, Any]], gold: dict[str, int]) -> int | None:
        for rank, doc_id in enumerate(_doc_ids(results), start=1):
            if doc_id in gold:
                return rank
        return None

    for qid, gold in qrel_scores.items():
        if qid not in base_rankings or qid not in target_rankings:
            continue
        base_rank = first_relevant_rank(base_rankings[qid], gold)
        target_rank = first_relevant_rank(target_rankings[qid], gold)

        if base_rank is None and target_rank is None:
            unchanged += 1
            continue
        if base_rank is None and target_rank is not None:
            improved += 1
            if len(sample_improvements) < 8:
                sample_improvements.append(
                    {
                        "qid": qid,
                        "query": query_texts.get(qid, ""),
                        "base_rank": None,
                        "target_rank": target_rank,
                        "gold_doc_ids": sorted(gold)[:3],
                        "base_top5": _doc_ids(base_rankings[qid])[:5],
                        "target_top5": _doc_ids(target_rankings[qid])[:5],
                    }
                )
            continue
        if base_rank is not None and target_rank is None:
            regressed += 1
            if len(sample_regressions) < 8:
                sample_regressions.append(
                    {
                        "qid": qid,
                        "query": query_texts.get(qid, ""),
                        "base_rank": base_rank,
                        "target_rank": None,
                        "gold_doc_ids": sorted(gold)[:3],
                        "base_top5": _doc_ids(base_rankings[qid])[:5],
                        "target_top5": _doc_ids(target_rankings[qid])[:5],
                    }
                )
            continue
        if target_rank < base_rank:
            improved += 1
            if len(sample_improvements) < 8:
                sample_improvements.append(
                    {
                        "qid": qid,
                        "query": query_texts.get(qid, ""),
                        "base_rank": base_rank,
                        "target_rank": target_rank,
                        "gold_doc_ids": sorted(gold)[:3],
                        "base_top5": _doc_ids(base_rankings[qid])[:5],
                        "target_top5": _doc_ids(target_rankings[qid])[:5],
                    }
                )
        elif target_rank > base_rank:
            regressed += 1
            if len(sample_regressions) < 8:
                sample_regressions.append(
                    {
                        "qid": qid,
                        "query": query_texts.get(qid, ""),
                        "base_rank": base_rank,
                        "target_rank": target_rank,
                        "gold_doc_ids": sorted(gold)[:3],
                        "base_top5": _doc_ids(base_rankings[qid])[:5],
                        "target_top5": _doc_ids(target_rankings[qid])[:5],
                    }
                )
        else:
            unchanged += 1

    return {
        "base": base_name,
        "target": target_name,
        "improved_queries": improved,
        "regressed_queries": regressed,
        "unchanged_queries": unchanged,
        "sample_improvements": sample_improvements,
        "sample_regressions": sample_regressions,
    }


def _stability_probe(
    reranker,
    records: list[QueryRecord],
    original_rankings: dict[str, list[dict[str, Any]]],
    *,
    limit: int,
) -> dict[str, Any]:
    if limit <= 0:
        return {
            "queries_probed": 0,
            "top1_consistency": 1.0,
            "top5_exact_consistency": 1.0,
        }

    sampled = records[: min(limit, len(records))]
    top1_matches = 0
    top5_matches = 0
    probed = 0
    for record in sampled:
        reranked = reranker.rerank_dict_results(query=record.query, results=record.hybrid_payload)
        current_top1 = _doc_ids(reranked)[:1]
        current_top5 = _doc_ids(reranked)[:5]
        original_top1 = _doc_ids(original_rankings.get(record.qid, []))[:1]
        original_top5 = _doc_ids(original_rankings.get(record.qid, []))[:5]
        top1_matches += int(current_top1 == original_top1)
        top5_matches += int(current_top5 == original_top5)
        probed += 1

    total = max(probed, 1)
    return {
        "queries_probed": probed,
        "top1_consistency": round(top1_matches / total, 4),
        "top5_exact_consistency": round(top5_matches / total, 4),
    }


def main() -> None:
    args = _build_parser().parse_args()

    dataset_dir = Path(args.dataset_dir).resolve()
    qrels_dir = Path(args.qrels_dir).resolve()

    corpus_rows, queries_rows, qrels_rows = _load_dataset(dataset_dir, qrels_dir)
    qrel_scores = _build_qrel_scores(qrels_rows)
    subset_rows = _focused_corpus(
        corpus_rows,
        qrel_scores,
        target_docs=args.target_docs,
        seed=args.seed,
    )
    subset_doc_ids = {str(row.get("id", "")).strip() for row in subset_rows}
    filtered_qrels = {
        qid: {pid: score for pid, score in mapping.items() if pid in subset_doc_ids}
        for qid, mapping in qrel_scores.items()
    }
    filtered_qrels = {qid: mapping for qid, mapping in filtered_qrels.items() if mapping}
    sampled_queries = _sample_queries(
        queries_rows,
        filtered_qrels,
        max_queries=args.max_queries,
        seed=args.seed,
    )

    settings = get_settings()
    LlamaSettings.embed_model = build_embedding_model(settings)
    documents = _build_documents(subset_rows)
    splitter = SentenceSplitter(
        chunk_size=settings.rag_chunk_size,
        chunk_overlap=settings.rag_chunk_overlap,
    )
    nodes = splitter.get_nodes_from_documents(documents)
    index = VectorStoreIndex(nodes)

    records = _prepare_query_records(
        index,
        documents,
        sampled_queries,
        candidate_top_k=args.candidate_top_k,
    )
    query_texts = {record.qid: record.query for record in records}
    filtered_qrels = {qid: filtered_qrels[qid] for qid in query_texts}

    remote_reranker = build_reranker(settings)
    heuristic_reranker = HeuristicReranker()
    noop_reranker = NoopReranker()

    configs = [
        ("dense_no_rerank", "dense", "none", noop_reranker),
        ("hybrid_no_rerank", "hybrid", "none", noop_reranker),
        ("hybrid_heuristic_rerank", "hybrid", "heuristic", heuristic_reranker),
        ("hybrid_remote_rerank", "hybrid", type(remote_reranker).__name__, remote_reranker),
    ]

    config_results: list[ConfigResult] = []
    rankings_by_name: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for name, candidate_source, reranker_name, reranker in configs:
        result, rankings = _evaluate_config(
            name=name,
            candidate_source=candidate_source,
            reranker_name=reranker_name,
            reranker=reranker,
            records=records,
            qrel_scores=filtered_qrels,
            metric_top_k=args.metric_top_k,
        )
        config_results.append(result)
        rankings_by_name[name] = rankings

    comparisons = [
        _compare_rankings(
            base_name="hybrid_no_rerank",
            target_name="hybrid_heuristic_rerank",
            base_rankings=rankings_by_name["hybrid_no_rerank"],
            target_rankings=rankings_by_name["hybrid_heuristic_rerank"],
            qrel_scores=filtered_qrels,
            query_texts=query_texts,
        ),
        _compare_rankings(
            base_name="hybrid_no_rerank",
            target_name="hybrid_remote_rerank",
            base_rankings=rankings_by_name["hybrid_no_rerank"],
            target_rankings=rankings_by_name["hybrid_remote_rerank"],
            qrel_scores=filtered_qrels,
            query_texts=query_texts,
        ),
        _compare_rankings(
            base_name="hybrid_heuristic_rerank",
            target_name="hybrid_remote_rerank",
            base_rankings=rankings_by_name["hybrid_heuristic_rerank"],
            target_rankings=rankings_by_name["hybrid_remote_rerank"],
            qrel_scores=filtered_qrels,
            query_texts=query_texts,
        ),
    ]

    stability = _stability_probe(
        remote_reranker,
        records,
        rankings_by_name["hybrid_remote_rerank"],
        limit=args.stability_probe_queries,
    )

    result_by_name = {item.name: item for item in config_results}
    for comparison in comparisons:
        target_name = str(comparison["target"])
        result_by_name[target_name].sample_improvements = comparison["sample_improvements"]
        result_by_name[target_name].sample_regressions = comparison["sample_regressions"]

    payload = {
        "ok": True,
        "artifact_date": date.today().isoformat(),
        "dataset_dir": str(dataset_dir),
        "qrels_dir": str(qrels_dir),
        "subset": {
            "target_docs": args.target_docs,
            "docs_indexed": len(documents),
            "nodes_indexed": len(nodes),
            "queries_evaluated": len(records),
            "candidate_top_k": args.candidate_top_k,
            "metric_top_k": args.metric_top_k,
            "seed": args.seed,
        },
        "runtime": {
            "embedding_provider": settings.embedding_provider,
            "embedding_model": settings.embedding_model,
            "vector_store_backend": settings.vector_store_backend,
            "rerank_provider": settings.rerank_provider,
            "rerank_model": settings.rerank_model,
            "rerank_top_n": settings.rerank_top_n,
            "remote_reranker_type": type(remote_reranker).__name__,
        },
        "configs": [asdict(item) for item in config_results],
        "comparisons": comparisons,
        "stability_probe": stability,
    }

    artifact = _artifact_path(args.output or None)
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"artifact={artifact}")


if __name__ == "__main__":
    main()
