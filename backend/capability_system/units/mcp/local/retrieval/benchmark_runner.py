from __future__ import annotations

import argparse
import dataclasses
import json
import math
import random
import shutil
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

for _parent in Path(__file__).resolve().parents:
    if (_parent / "config.py").exists() and (_parent / "retrieval_core").is_dir():
        backend_path = str(_parent)
        if backend_path not in sys.path:
            sys.path.insert(0, backend_path)
        break

from normalized_ingestion.models import IndexableUnit
from retrieval_core.llamaindex_backend import LlamaIndexRetrievalBackend
from retrieval_core.retrievers import RetrievalRequest


@dataclass(slots=True)
class BenchmarkConfig:
    scifact_root: Path
    runtime_root: Path | None = None
    split: str = "test"
    max_queries: int = 50
    max_docs: int = 0
    candidate_top_k: int = 100
    metric_top_k: int = 10
    seed: int = 42
    rebuild: bool = False
    use_rerank: bool = True
    output_path: Path | None = None
    rerank_top_n: int | None = None
    rerank_candidate_pool: int | None = None
    build_batch_size: int | None = None


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


def _build_units(corpus: dict[str, dict[str, Any]], *, max_docs: int = 0) -> list[IndexableUnit]:
    units: list[IndexableUnit] = []
    doc_ids = sorted(corpus, key=lambda value: int(value) if value.isdigit() else value)
    if max_docs > 0:
        doc_ids = doc_ids[:max_docs]
    for doc_id in doc_ids:
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


def _find_backend_dir() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "config.py").exists() and (parent / "retrieval_core").is_dir():
            return parent
    raise RuntimeError(f"Cannot locate backend directory from {current}")


def _result_metadata(row: dict[str, Any]) -> dict[str, Any]:
    return dict(row.get("metadata", {}) or {})


def _count_values(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        metadata = _result_metadata(row)
        value = metadata.get(key)
        if isinstance(value, list | tuple):
            values = [str(item) for item in value if str(item)]
        else:
            values = [str(value)] if value not in (None, "") else []
        for item in values:
            counts[item] = counts.get(item, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _retrieval_diagnostics_for_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    candidate_graph_hits = [
        row
        for row in rows
        if _result_metadata(row).get("retrieval_stage") == "candidate_graph"
        or _result_metadata(row).get("candidate_graph_node_key")
    ]
    return {
        "result_count": len(rows),
        "retrieval_mode_counts": _count_values(rows, "retrieval_modes"),
        "unit_type_counts": _count_values(rows, "unit_type"),
        "modality_counts": _count_values(rows, "modality"),
        "candidate_graph": {
            "result_count": len(candidate_graph_hits),
            "bucket_kind_counts": _count_values(candidate_graph_hits, "candidate_graph_bucket_kind"),
            "merged_result_count": sum(
                1
                for row in candidate_graph_hits
                if int(_result_metadata(row).get("candidate_graph_hit_count") or 0) > 1
            ),
        },
    }


def _aggregate_retrieval_diagnostics(retrieved: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    all_rows: list[dict[str, Any]] = []
    for rows in retrieved.values():
        all_rows.extend(rows)
    diagnostics = _retrieval_diagnostics_for_rows(all_rows)
    diagnostics["queries_with_results"] = sum(1 for rows in retrieved.values() if rows)
    return diagnostics


def _index_payload_ready(payload: dict[str, Any]) -> bool:
    status = str(payload.get("status", "") or "").strip().lower()
    if status != "ready":
        return False
    dense_documents = int(payload.get("dense_documents") or 0)
    dense_indexed = int(payload.get("dense_documents_indexed") or dense_documents or 0)
    if dense_documents > 0 and dense_indexed < dense_documents:
        return False
    dense_status = str(payload.get("dense_status", status) or status).strip().lower()
    if dense_status not in {"", "ready"}:
        return False
    return True


def _load_existing_index_payload(backend: LlamaIndexRetrievalBackend, collection: str) -> dict[str, Any]:
    metadata_path = backend.layout.metadata_path(collection)
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except Exception:
        return {"collection": collection, "status": "unknown"}
    if not _index_payload_ready(payload):
        raise RuntimeError(
            f"Benchmark index '{collection}' is not ready: "
            f"status={payload.get('status')!r}, "
            f"dense_documents_indexed={payload.get('dense_documents_indexed')!r}, "
            f"dense_documents={payload.get('dense_documents')!r}. "
            f"index_dir={backend.layout.collection_dir(collection)}. "
            "Run with --rebuild to build in a staging directory and publish only after success."
        )
    return payload


def _publish_benchmark_collection(staging_backend: LlamaIndexRetrievalBackend, final_backend: LlamaIndexRetrievalBackend) -> None:
    staging_collection_dir = staging_backend.layout.collection_dir("benchmark")
    final_collection_dir = final_backend.layout.collection_dir("benchmark")
    if not staging_collection_dir.exists():
        raise RuntimeError(f"Benchmark staging collection missing: {staging_collection_dir}")
    final_collection_dir.parent.mkdir(parents=True, exist_ok=True)
    backup_dir = final_collection_dir.with_name(f"{final_collection_dir.name}.backup-{uuid.uuid4().hex[:8]}")
    if final_collection_dir.exists():
        final_collection_dir.rename(backup_dir)
    try:
        shutil.move(str(staging_collection_dir), str(final_collection_dir))
        if backup_dir.exists():
            shutil.rmtree(backup_dir)
    except Exception:
        if final_collection_dir.exists():
            shutil.rmtree(final_collection_dir)
        if backup_dir.exists():
            backup_dir.rename(final_collection_dir)
        raise


def _rewrite_published_metadata(backend: LlamaIndexRetrievalBackend, collection: str) -> None:
    metadata_path = backend.layout.metadata_path(collection)
    if not metadata_path.exists():
        return
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    backend._write_metadata(collection, payload)


def _build_benchmark_index_atomically(
    *,
    runtime_root: Path,
    corpus: dict[str, dict[str, Any]],
    build_batch_size: int | None = None,
    max_docs: int = 0,
) -> tuple[LlamaIndexRetrievalBackend, dict[str, Any], float]:
    from config import get_settings
    from embedding_compat import build_embedding_model
    from retrieval_core.embedding_cache import CachedEmbeddingModel

    staging_parent = runtime_root.parent / ".benchmark_staging"
    staging_root = staging_parent / f"{runtime_root.name}-{uuid.uuid4().hex[:10]}"
    staging_parent.mkdir(parents=True, exist_ok=True)
    settings = get_settings()
    if build_batch_size is not None:
        settings = dataclasses.replace(settings, qdrant_build_batch_size=max(int(build_batch_size), 1))
    staging_backend = LlamaIndexRetrievalBackend(staging_root)
    staging_backend.settings = settings
    embed_model = CachedEmbeddingModel(
        build_embedding_model(settings),
        cache_path=runtime_root / "storage" / "embedding_cache" / "benchmark.sqlite3",
        namespace=f"benchmark:{settings.embedding_provider}:{settings.embedding_model}:{settings.embedding_dimensions or ''}",
    )
    started = time.perf_counter()
    index_payload = staging_backend.build_collection(
        "benchmark",
        _build_units(corpus, max_docs=max_docs),
        embed_model=embed_model,
        verify_dense_query=False,
    )
    build_seconds = time.perf_counter() - started
    if not _index_payload_ready(index_payload):
        raise RuntimeError(
            f"Benchmark rebuild did not produce a ready index: "
            f"status={index_payload.get('status')!r}, "
            f"dense_documents_indexed={index_payload.get('dense_documents_indexed')!r}, "
            f"dense_documents={index_payload.get('dense_documents')!r}."
        )
    final_backend = LlamaIndexRetrievalBackend(runtime_root)
    _publish_benchmark_collection(staging_backend, final_backend)
    _rewrite_published_metadata(final_backend, "benchmark")
    try:
        shutil.rmtree(staging_root)
    except FileNotFoundError:
        pass
    return final_backend, _load_existing_index_payload(final_backend, "benchmark"), build_seconds


def run_benchmark(config: BenchmarkConfig, *, backend_dir: Path) -> dict[str, Any]:
    corpus, queries, qrels = _load_scifact(config)
    query_ids = _sample_query_ids(qrels, queries, max_queries=config.max_queries, seed=config.seed)
    runtime_root = Path(config.runtime_root).resolve() if config.runtime_root is not None else backend_dir
    backend = LlamaIndexRetrievalBackend(runtime_root)

    build_seconds = 0.0
    index_payload: dict[str, Any]
    if config.rebuild or not backend.layout.metadata_path("benchmark").exists():
        backend, index_payload, build_seconds = _build_benchmark_index_atomically(
            runtime_root=runtime_root,
            corpus=corpus,
            build_batch_size=config.build_batch_size,
            max_docs=config.max_docs,
        )
    else:
        index_payload = _load_existing_index_payload(backend, "benchmark")

    base_retrieved: dict[str, list[dict[str, Any]]] = {}
    reranked_retrieved: dict[str, list[dict[str, Any]]] = {}
    retrieval_seconds: list[float] = []
    rerank_seconds: list[float] = []

    reranker = None
    rerank_settings: dict[str, Any] = {"enabled": False}
    if config.use_rerank:
        from config import get_settings
        from capability_system.units.mcp.local.retrieval.reranker import build_reranker

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
        query_index = len(base_retrieved) + 1
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
        retrieval_elapsed = time.perf_counter() - started
        retrieval_seconds.append(retrieval_elapsed)
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
            print(
                f"[benchmark-query] {query_index}/{len(query_ids)} qid={qid} "
                f"retrieval={retrieval_elapsed:.4f}s rerank=0.0000s rerank_top_n=0",
                flush=True,
            )
            continue
        rerank_started = time.perf_counter()
        reranked_retrieved[qid] = reranker.rerank_dict_results(query=query, results=rows)
        rerank_elapsed = time.perf_counter() - rerank_started
        rerank_seconds.append(rerank_elapsed)
        print(
            f"[benchmark-query] {query_index}/{len(query_ids)} qid={qid} "
            f"retrieval={retrieval_elapsed:.4f}s rerank={rerank_elapsed:.4f}s "
            f"rerank_top_n={rerank_settings.get('top_n', 0)}",
            flush=True,
        )

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
            "retrieval_diagnostics": _retrieval_diagnostics_for_rows(
                reranked_retrieved.get(str(row["qid"]), [])[: config.metric_top_k]
            ),
        }
        for row in current_rows
        if not row["hit_at_10"]
    ][:20]
    query_diagnostics = {
        qid: _retrieval_diagnostics_for_rows(reranked_retrieved.get(qid, [])[: config.metric_top_k])
        for qid in query_ids
    }
    payload = {
        "config": {
            "split": config.split,
            "max_queries": config.max_queries,
            "max_docs": config.max_docs,
            "candidate_top_k": config.candidate_top_k,
            "metric_top_k": config.metric_top_k,
            "seed": config.seed,
            "use_rerank": config.use_rerank,
            "rebuild": config.rebuild,
            "rerank_top_n": config.rerank_top_n,
            "rerank_candidate_pool": config.rerank_candidate_pool,
            "build_batch_size": config.build_batch_size,
            "runtime_root": str(runtime_root),
        },
        "rerank_settings": rerank_settings,
        "scifact_root": str(config.scifact_root),
        "index_root": str(backend.layout.root),
        "build_seconds": round(build_seconds, 4),
        "index_payload": index_payload,
        "base_retrieval": base_metrics,
        "current_chain": current_metrics,
        "retrieval_diagnostics": {
            "base": _aggregate_retrieval_diagnostics(base_retrieved),
            "current": _aggregate_retrieval_diagnostics(reranked_retrieved),
        },
        "latency": {
            "mean_retrieval_seconds": round(sum(retrieval_seconds) / max(len(retrieval_seconds), 1), 4),
            "mean_rerank_seconds": round(sum(rerank_seconds) / max(len(rerank_seconds), 1), 4),
        },
        "sample_failures": sample_failures,
        "query_diagnostics": query_diagnostics,
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
    parser.add_argument("--max-docs", type=int, default=0, help="Limit indexed docs for rebuild smoke tests only. 0 indexes full corpus.")
    parser.add_argument("--candidate-top-k", type=int, default=100)
    parser.add_argument("--metric-top-k", type=int, default=10)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--no-rerank", action="store_true")
    parser.add_argument("--rerank-top-n", type=int, default=None)
    parser.add_argument("--rerank-candidate-pool", type=int, default=None)
    parser.add_argument("--build-batch-size", type=int, default=None)
    parser.add_argument(
        "--runtime-root",
        default="",
        help="Isolated project/runtime root for benchmark indexes. Defaults to output/benchmark_runtime/scifact_v2.",
    )
    parser.add_argument("--output", default="")
    return parser


def main() -> int:
    backend_dir = _find_backend_dir()
    args = _build_parser().parse_args()
    scifact_root = Path(args.scifact_root).resolve() if args.scifact_root else (
        backend_dir.parent / "scifact" / "_beir_extract" / "scifact"
    ).resolve()
    if args.output:
        output_arg = Path(args.output)
        output = output_arg.resolve() if output_arg.is_absolute() else (backend_dir / output_arg).resolve()
    else:
        output = (backend_dir / "tests" / "_artifacts" / "scifact_v2_current.json").resolve()
    if args.runtime_root:
        runtime_root_arg = Path(args.runtime_root)
        runtime_root = runtime_root_arg.resolve() if runtime_root_arg.is_absolute() else (backend_dir.parent / runtime_root_arg).resolve()
    else:
        runtime_root = (backend_dir.parent / "output" / "benchmark_runtime" / "scifact_v2").resolve()
    payload = run_benchmark(
        BenchmarkConfig(
            scifact_root=scifact_root,
            runtime_root=runtime_root,
            split=args.split,
            max_queries=args.max_queries,
            max_docs=args.max_docs,
            candidate_top_k=args.candidate_top_k,
            metric_top_k=args.metric_top_k,
            seed=args.seed,
            rebuild=bool(args.rebuild),
            use_rerank=not bool(args.no_rerank),
            output_path=output,
            rerank_top_n=args.rerank_top_n,
            rerank_candidate_pool=args.rerank_candidate_pool,
            build_batch_size=args.build_batch_size,
        ),
        backend_dir=backend_dir,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
