from __future__ import annotations

import argparse
import dataclasses
import json
import math
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from normalized_ingestion.models import IndexableUnit
from retrieval_core.llamaindex_backend import LlamaIndexRetrievalBackend
from retrieval_core.retrievers import RetrievalRequest


@dataclass(slots=True)
class BenchmarkConfig:
    scifact_root: Path
    split: str = "test"
    max_queries: int = 50
    candidate_top_k: int = 100
    metric_top_k: int = 10
    seed: int = 42
    rebuild: bool = False
    use_rerank: bool = True
    output_path: Path | None = None
    rerank_top_n: int | None = None
    rerank_candidate_pool: int | None = None


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def _read_qrels(path: Path) -> dict[str, set[str]]:
    qrels: dict[str, set[str]] = {}
    with path.open("r", encoding="utf-8") as handle:
        header = handle.readline()
        _ = header
        for line in handle:
            parts = line.strip().split("\t")
            if len(parts) < 3:
                continue
            qid, doc_id, score = parts[:3]
            try:
                relevance = float(score)
            except ValueError:
                relevance = 0.0
            if relevance <= 0:
                continue
            qrels.setdefault(str(qid), set()).add(str(doc_id))
    return qrels


def _load_scifact(config: BenchmarkConfig) -> tuple[dict[str, dict[str, Any]], dict[str, str], dict[str, set[str]]]:
    corpus_rows = _read_jsonl(config.scifact_root / "corpus.jsonl")
    query_rows = _read_jsonl(config.scifact_root / "queries.jsonl")
    qrels = _read_qrels(config.scifact_root / "qrels" / f"{config.split}.tsv")
    corpus = {str(row.get("_id", "")).strip(): row for row in corpus_rows if str(row.get("_id", "")).strip()}
    queries = {str(row.get("_id", "")).strip(): str(row.get("text", "")).strip() for row in query_rows}
    return corpus, queries, qrels


def _sample_query_ids(qrels: dict[str, set[str]], queries: dict[str, str], *, max_queries: int, seed: int) -> list[str]:
    ids = sorted(qid for qid in qrels if qid in queries and queries[qid])
    if max_queries <= 0 or max_queries >= len(ids):
        return ids
    rng = random.Random(seed)
    sampled = rng.sample(ids, max_queries)
    return sorted(sampled, key=lambda value: int(value) if value.isdigit() else value)


def _build_units(corpus: dict[str, dict[str, Any]]) -> list[IndexableUnit]:
    units: list[IndexableUnit] = []
    for doc_id in sorted(corpus, key=lambda value: int(value) if value.isdigit() else value):
        row = corpus[doc_id]
        title = str(row.get("title", "") or "").strip()
        text = str(row.get("text", "") or "").strip()
        merged = f"{title}\n{text}".strip()
        if not merged:
            continue
        units.append(
            IndexableUnit(
                unit_id=f"scifact::{doc_id}",
                unit_type="document",
                collection="benchmark",
                doc_id=doc_id,
                source_path=f"scifact/{doc_id}.json",
                text=merged,
                modality="text",
                node_kind="document",
                block_id=doc_id,
                block_type="document",
                metadata={
                    "title": title,
                    "source_type": "jsonl",
                    "source_path": f"scifact/{doc_id}.json",
                    "parser_backend": "scifact_jsonl",
                    "unit_view": "benchmark_document",
                },
            )
        )
    return units


def _extract_doc_ids(rows: list[dict[str, Any]]) -> list[str]:
    doc_ids: list[str] = []
    for row in rows:
        metadata = dict(row.get("metadata", {}) or {})
        doc_id = str(metadata.get("doc_id") or row.get("doc_id") or "").strip()
        if not doc_id:
            source = str(row.get("source", "") or "")
            stem = Path(source).stem
            doc_id = stem if stem.isdigit() else ""
        if doc_id:
            doc_ids.append(doc_id)
    return doc_ids


def _dcg(relevance: list[int]) -> float:
    total = 0.0
    for index, rel in enumerate(relevance, start=1):
        if rel <= 0:
            continue
        total += (2**rel - 1) / math.log2(index + 1)
    return total


def _metrics(per_query: list[dict[str, Any]], *, metric_top_k: int) -> dict[str, float | int]:
    if not per_query:
        return {
            "queries_evaluated": 0,
            "accuracy_at_1": 0.0,
            "hit_at_3": 0.0,
            "hit_at_5": 0.0,
            "hit_at_10": 0.0,
            "recall_at_10": 0.0,
            "mrr_at_10": 0.0,
            "ndcg_at_10": 0.0,
        }
    count = len(per_query)

    def hit_at(k: int) -> float:
        return sum(1 for item in per_query if item[f"hit_at_{k}"]) / count

    return {
        "queries_evaluated": count,
        "accuracy_at_1": hit_at(1),
        "hit_at_3": hit_at(min(3, metric_top_k)),
        "hit_at_5": hit_at(min(5, metric_top_k)),
        "hit_at_10": hit_at(metric_top_k),
        "recall_at_10": sum(float(item["recall_at_k"]) for item in per_query) / count,
        "mrr_at_10": sum(float(item["mrr_at_k"]) for item in per_query) / count,
        "ndcg_at_10": sum(float(item["ndcg_at_k"]) for item in per_query) / count,
    }


def _evaluate_rows(
    *,
    query_ids: list[str],
    queries: dict[str, str],
    qrels: dict[str, set[str]],
    retrieved: dict[str, list[dict[str, Any]]],
    metric_top_k: int,
) -> tuple[dict[str, float | int], list[dict[str, Any]]]:
    per_query: list[dict[str, Any]] = []
    for qid in query_ids:
        gold = set(qrels.get(qid, set()))
        top_rows = retrieved.get(qid, [])[:metric_top_k]
        top_doc_ids = _extract_doc_ids(top_rows)
        top_set = set(top_doc_ids)
        hits = gold & top_set
        first_hit_rank = 0
        for rank, doc_id in enumerate(top_doc_ids, start=1):
            if doc_id in gold:
                first_hit_rank = rank
                break
        relevance = [1 if doc_id in gold else 0 for doc_id in top_doc_ids]
        ideal_relevance = [1] * min(len(gold), metric_top_k)
        ideal_dcg = _dcg(ideal_relevance)
        row = {
            "qid": qid,
            "query": queries[qid],
            "gold_doc_ids": sorted(gold, key=lambda value: int(value) if value.isdigit() else value),
            "top_doc_ids": top_doc_ids,
            "hit_at_1": bool(top_doc_ids[:1] and top_doc_ids[0] in gold),
            "hit_at_3": bool(gold & set(top_doc_ids[: min(3, metric_top_k)])),
            "hit_at_5": bool(gold & set(top_doc_ids[: min(5, metric_top_k)])),
            "hit_at_10": bool(hits),
            "recall_at_k": len(hits) / max(len(gold), 1),
            "mrr_at_k": (1.0 / first_hit_rank) if first_hit_rank else 0.0,
            "ndcg_at_k": (_dcg(relevance) / ideal_dcg) if ideal_dcg > 0 else 0.0,
        }
        per_query.append(row)
    return _metrics(per_query, metric_top_k=metric_top_k), per_query


def _rank_gold(rows: list[dict[str, Any]], gold_doc_ids: set[str]) -> dict[str, int | None]:
    ranks: dict[str, int | None] = {doc_id: None for doc_id in gold_doc_ids}
    for rank, doc_id in enumerate(_extract_doc_ids(rows), start=1):
        if doc_id in ranks and ranks[doc_id] is None:
            ranks[doc_id] = rank
    return ranks


def run_benchmark(config: BenchmarkConfig, *, backend_dir: Path) -> dict[str, Any]:
    corpus, queries, qrels = _load_scifact(config)
    query_ids = _sample_query_ids(qrels, queries, max_queries=config.max_queries, seed=config.seed)
    backend = LlamaIndexRetrievalBackend(backend_dir)

    build_seconds = 0.0
    index_payload: dict[str, Any]
    if config.rebuild or not backend.layout.metadata_path("benchmark").exists():
        started = time.perf_counter()
        index_payload = backend.build_collection("benchmark", _build_units(corpus))
        build_seconds = time.perf_counter() - started
    else:
        try:
            index_payload = json.loads(backend.layout.metadata_path("benchmark").read_text(encoding="utf-8"))
        except Exception:
            index_payload = {"collection": "benchmark", "status": "unknown"}

    base_retrieved: dict[str, list[dict[str, Any]]] = {}
    reranked_retrieved: dict[str, list[dict[str, Any]]] = {}
    retrieval_seconds: list[float] = []
    rerank_seconds: list[float] = []

    reranker = None
    rerank_settings: dict[str, Any] = {"enabled": False}
    if config.use_rerank:
        from config import get_settings
        from RAG.reranker import build_reranker

        settings = get_settings()
        overrides: dict[str, Any] = {}
        if config.rerank_top_n is not None:
            overrides["rerank_top_n"] = max(int(config.rerank_top_n), 1)
        if config.rerank_candidate_pool is not None:
            overrides["rerank_candidate_pool"] = max(int(config.rerank_candidate_pool), 1)
        if overrides:
            settings = dataclasses.replace(settings, **overrides)
        rerank_settings = {
            "enabled": bool(settings.rerank_enabled),
            "provider": settings.rerank_provider,
            "model": settings.rerank_model,
            "top_n": settings.rerank_top_n,
            "candidate_pool": settings.rerank_candidate_pool,
            "batch_size": settings.rerank_batch_size,
            "max_length": settings.rerank_max_length,
            "device": settings.rerank_device,
        }
        reranker = build_reranker(settings)

    for qid in query_ids:
        query = queries[qid]
        started = time.perf_counter()
        hits = backend.retrieve(
            RetrievalRequest(
                query=query,
                top_k=config.candidate_top_k,
                query_mode="semantic_lookup",
                collections=("benchmark",),
            )
        )
        retrieval_seconds.append(time.perf_counter() - started)
        rows = [
            {
                "text": hit.text,
                "source": hit.source,
                "score": float(hit.score or 0.0),
                "retrieval_score": float(hit.score or 0.0),
                "metadata": {
                    **dict(hit.metadata),
                    "doc_id": hit.doc_id,
                    "block_id": hit.block_id,
                    "retrieval_modes": list(hit.retrieval_modes),
                },
            }
            for hit in hits
        ]
        base_retrieved[qid] = rows
        if reranker is None:
            reranked_retrieved[qid] = rows
            rerank_seconds.append(0.0)
            continue
        rerank_started = time.perf_counter()
        reranked_retrieved[qid] = reranker.rerank_dict_results(query=query, results=rows)
        rerank_seconds.append(time.perf_counter() - rerank_started)

    base_metrics, base_rows = _evaluate_rows(
        query_ids=query_ids,
        queries=queries,
        qrels=qrels,
        retrieved=base_retrieved,
        metric_top_k=config.metric_top_k,
    )
    current_metrics, current_rows = _evaluate_rows(
        query_ids=query_ids,
        queries=queries,
        qrels=qrels,
        retrieved=reranked_retrieved,
        metric_top_k=config.metric_top_k,
    )
    sample_failures = [
        {
            "qid": row["qid"],
            "query": row["query"],
            "gold_doc_ids": row["gold_doc_ids"],
            "top_doc_ids": row["top_doc_ids"][: config.metric_top_k],
        }
        for row in current_rows
        if not row["hit_at_10"]
    ][:20]
    payload = {
        "config": {
            "split": config.split,
            "max_queries": config.max_queries,
            "candidate_top_k": config.candidate_top_k,
            "metric_top_k": config.metric_top_k,
            "seed": config.seed,
            "use_rerank": config.use_rerank,
            "rebuild": config.rebuild,
            "rerank_top_n": config.rerank_top_n,
            "rerank_candidate_pool": config.rerank_candidate_pool,
        },
        "rerank_settings": rerank_settings,
        "scifact_root": str(config.scifact_root),
        "build_seconds": round(build_seconds, 4),
        "index_payload": index_payload,
        "base_retrieval": base_metrics,
        "current_chain": current_metrics,
        "latency": {
            "mean_retrieval_seconds": round(sum(retrieval_seconds) / max(len(retrieval_seconds), 1), 4),
            "mean_rerank_seconds": round(sum(rerank_seconds) / max(len(rerank_seconds), 1), 4),
        },
        "sample_failures": sample_failures,
        "gold_ranks": {
            qid: {
                "query": queries[qid],
                "gold_doc_ids": sorted(qrels.get(qid, set()), key=lambda value: int(value) if value.isdigit() else value),
                "base_rank": _rank_gold(base_retrieved.get(qid, []), qrels.get(qid, set())),
                "current_rank": _rank_gold(reranked_retrieved.get(qid, []), qrels.get(qid, set())),
            }
            for qid in query_ids
        },
    }
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run local SciFact retrieval benchmark against the RAG benchmark collection.")
    parser.add_argument("--scifact-root", default="", help="Path to BEIR SciFact root. Defaults to ../scifact/_beir_extract/scifact.")
    parser.add_argument("--split", default="test", choices=("test", "train"))
    parser.add_argument("--max-queries", type=int, default=50)
    parser.add_argument("--candidate-top-k", type=int, default=100)
    parser.add_argument("--metric-top-k", type=int, default=10)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--no-rerank", action="store_true")
    parser.add_argument("--rerank-top-n", type=int, default=None)
    parser.add_argument("--rerank-candidate-pool", type=int, default=None)
    parser.add_argument("--output", default="")
    return parser


def main() -> int:
    backend_dir = Path(__file__).resolve().parents[1]
    args = _build_parser().parse_args()
    scifact_root = Path(args.scifact_root).resolve() if args.scifact_root else (
        backend_dir.parent / "scifact" / "_beir_extract" / "scifact"
    ).resolve()
    if args.output:
        output_arg = Path(args.output)
        output = output_arg.resolve() if output_arg.is_absolute() else (backend_dir / output_arg).resolve()
    else:
        output = (backend_dir / "tests" / "_artifacts" / "scifact_v2_current.json").resolve()
    payload = run_benchmark(
        BenchmarkConfig(
            scifact_root=scifact_root,
            split=args.split,
            max_queries=args.max_queries,
            candidate_top_k=args.candidate_top_k,
            metric_top_k=args.metric_top_k,
            seed=args.seed,
            rebuild=bool(args.rebuild),
            use_rerank=not bool(args.no_rerank),
            output_path=output,
            rerank_top_n=args.rerank_top_n,
            rerank_candidate_pool=args.rerank_candidate_pool,
        ),
        backend_dir=backend_dir,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
