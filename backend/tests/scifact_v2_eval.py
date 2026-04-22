from __future__ import annotations

import argparse
import hashlib
import json
import random
import statistics
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd


BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from config import get_settings
from document_conversion.models import SourceFileRecord
from document_conversion.structured_text import build_markdown_conversion_result
from embedding_compat import build_embedding_model
from normalized_ingestion import NormalizedDocumentBuilder, build_indexable_units
from normalized_ingestion.models import IndexableUnit
from RAG.query_rewriter import QueryRewriter
from RAG.reranker import build_reranker
from retrieval_core import LlamaIndexRetrievalBackend, RetrievalRequest


@dataclass(slots=True)
class EvalConfig:
    split: str
    max_queries: int
    candidate_top_k: int
    metric_top_k: int
    seed: int
    use_rewrite: bool
    use_rerank: bool
    rebuild: bool
    allow_degraded: bool


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate SciFact on the current v2 retrieval chain.")
    parser.add_argument("--scifact-root", default=str(PROJECT_ROOT / "scifact" / "_beir_extract" / "scifact"))
    parser.add_argument("--index-root", default=str(PROJECT_ROOT / "output" / "benchmark_runtime" / "scifact_v2"))
    parser.add_argument("--split", default="test", choices=["train", "test"])
    parser.add_argument("--max-queries", type=int, default=300)
    parser.add_argument("--candidate-top-k", type=int, default=10)
    parser.add_argument("--metric-top-k", type=int, default=10)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--disable-rewrite", action="store_true")
    parser.add_argument("--disable-rerank", action="store_true")
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--allow-degraded", action="store_true")
    parser.add_argument("--output", default="")
    return parser


def _artifact_path(path: str | None) -> Path:
    if path:
        return Path(path)
    stamp = date.today().strftime("%Y%m%d")
    return BACKEND_DIR / "tests" / "_artifacts" / f"scifact_v2_eval_{stamp}.json"


def _load_scifact(root: Path, split: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    corpus = pd.read_json(root / "corpus.jsonl", lines=True)
    queries = pd.read_json(root / "queries.jsonl", lines=True)
    qrels = pd.read_csv(root / "qrels" / f"{split}.tsv", sep="\t")
    return corpus, queries, qrels


def _stable_digest(*parts: str) -> str:
    digest = hashlib.sha1()
    for part in parts:
        digest.update(part.encode("utf-8", errors="ignore"))
    return digest.hexdigest()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _git_output(*args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except Exception:
        return ""
    return completed.stdout.strip()


def _git_commit() -> str:
    return _git_output("rev-parse", "HEAD") or "unknown"


def _git_dirty_entries() -> list[dict[str, str]]:
    try:
        completed = subprocess.run(
            ["git", "status", "--porcelain=v1", "-z"],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
        )
    except Exception:
        return []
    entries: list[dict[str, str]] = []
    for entry in completed.stdout.split(b"\x00"):
        if not entry:
            continue
        line = entry.decode("utf-8", errors="replace")
        if not line.strip():
            continue
        status = line[:2] if len(line) >= 2 else "??"
        item = line[3:].strip() if len(line) >= 4 else line.strip()
        if not item:
            continue
        entries.append(
            {
                "status": status,
                "path": item.replace("\\", "/"),
            }
        )
    return entries


def _file_sha1(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    digest = hashlib.sha1()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_stat(path: Path) -> dict[str, object]:
    if not path.exists():
        return {"path": str(path), "exists": False}
    stat = path.stat()
    return {
        "path": str(path),
        "exists": True,
        "size_bytes": int(stat.st_size),
        "modified_ns": int(stat.st_mtime_ns),
    }


def _chain_version(
    runtime_descriptor: dict[str, object],
    *,
    use_rewrite: bool,
    use_rerank: bool,
) -> str:
    base = str(runtime_descriptor.get("chain_version", "") or "").strip()
    if not base:
        dense_backend = str(runtime_descriptor.get("dense_backend", "unknown") or "unknown")
        lexical_backend = str(runtime_descriptor.get("lexical_backend", "unknown") or "unknown")
        fusion_backend = str(runtime_descriptor.get("fusion_backend", "unknown") or "unknown")
        base = f"scifact_v2__dense_{dense_backend}__lexical_{lexical_backend}__fusion_{fusion_backend}"
    rerank_mode = "rerank_on" if use_rerank else "rerank_off"
    rewrite_mode = "rewrite_on" if use_rewrite else "rewrite_off"
    return f"{base}__{rewrite_mode}__{rerank_mode}"


def _code_lineage() -> dict[str, object]:
    commit = _git_commit()
    dirty_entries = _git_dirty_entries()
    active_dirty_files = [
        entry["path"]
        for entry in dirty_entries
        if "D" not in str(entry.get("status", "") or "")
    ]
    deleted_dirty_files = [
        entry["path"]
        for entry in dirty_entries
        if "D" in str(entry.get("status", "") or "")
    ]
    tracked_files = [
        BACKEND_DIR / "tests" / "scifact_v2_eval.py",
        BACKEND_DIR / "retrieval_core" / "llamaindex_backend.py",
        BACKEND_DIR / "retrieval" / "service.py",
    ]
    file_digests = {str(path.relative_to(PROJECT_ROOT)).replace("\\", "/"): _file_sha1(path) for path in tracked_files}
    code_signature = _stable_digest(*(file_digests[key] for key in sorted(file_digests)))
    return {
        "code_commit": commit,
        "code_commit_short": commit[:12] if commit != "unknown" else "unknown",
        "working_tree_dirty": bool(dirty_entries),
        "dirty_files": active_dirty_files,
        "deleted_dirty_files": deleted_dirty_files,
        "dirty_entries": dirty_entries,
        "tracked_file_digests": file_digests,
        "retrieval_code_signature": code_signature,
    }


def _index_lineage(backend: LlamaIndexRetrievalBackend, *, index_root: Path, build_payload: dict[str, object]) -> dict[str, object]:
    meta_path = backend.layout.metadata_path("benchmark")
    units_path = backend.layout.units_path("benchmark")
    lexical_path = backend.layout.lexical_dir("benchmark") / "index.json"
    meta_digest = _file_sha1(meta_path)
    build_signature = _stable_digest(
        str(index_root),
        meta_digest,
        str(build_payload.get("status", "")),
        str(build_payload.get("dense_documents", "")),
        str(build_payload.get("lexical_documents", "")),
        str(build_payload.get("vector_backend", "")),
    )
    return {
        "index_root": str(index_root),
        "meta": {**_file_stat(meta_path), "sha1": meta_digest},
        "units": _file_stat(units_path),
        "lexical": _file_stat(lexical_path),
        "build_signature": build_signature,
    }


def _build_units(corpus: pd.DataFrame) -> list[IndexableUnit]:
    units: list[IndexableUnit] = []
    builder = NormalizedDocumentBuilder()
    corpus_source = PROJECT_ROOT / "scifact" / "_beir_extract" / "scifact" / "corpus.jsonl"
    for row in corpus.to_dict(orient="records"):
        doc_id = str(row.get("_id", "")).strip()
        title = str(row.get("title", "") or "").strip()
        text = str(row.get("text", "") or "").strip()
        if not doc_id or not (title or text):
            continue
        version_digest = _stable_digest(doc_id, title, text)
        markdown = "\n\n".join(part for part in (f"# {title}" if title else "", text) if part).strip()
        record = SourceFileRecord(
            collection="benchmark",
            absolute_path=corpus_source,
            source_path=f"scifact/{doc_id}.jsonl",
            source_type="scifact_jsonl",
            version_digest=version_digest,
            size_bytes=0,
            modified_ns=0,
        )
        conversion = build_markdown_conversion_result(
            record,
            markdown,
            parser_backend="scifact_jsonl",
            title=title,
            language="en",
            page_count=1,
            metadata={"title": title, "benchmark_source": str(corpus_source)},
            doc_id=doc_id,
        )
        document, blocks, object_refs = builder.build(conversion)
        units.extend(build_indexable_units(document, blocks, object_refs))
    return units


def _group_qrels(qrels: pd.DataFrame) -> dict[str, dict[str, int]]:
    grouped: dict[str, dict[str, int]] = {}
    for row in qrels.to_dict(orient="records"):
        qid = str(row.get("query-id", "")).strip()
        pid = str(row.get("corpus-id", "")).strip()
        score = int(row.get("score", 0) or 0)
        if not qid or not pid or score <= 0:
            continue
        grouped.setdefault(qid, {})[pid] = score
    return grouped


def _sample_queries(queries: pd.DataFrame, qrels: dict[str, dict[str, int]], *, max_queries: int, seed: int) -> list[dict[str, str]]:
    rows = [
        {"id": str(row.get("_id", "")).strip(), "text": str(row.get("text", "") or "").strip()}
        for row in queries.to_dict(orient="records")
        if str(row.get("_id", "")).strip() in qrels and str(row.get("text", "") or "").strip()
    ]
    rows.sort(key=lambda item: item["id"])
    if max_queries <= 0 or max_queries >= len(rows):
        return rows
    rng = random.Random(seed)
    sampled = rng.sample(rows, max_queries)
    sampled.sort(key=lambda item: item["id"])
    return sampled


def _payload_from_hits(hits: list[object]) -> list[dict[str, object]]:
    payload: list[dict[str, object]] = []
    for hit in hits:
        payload.append(
            {
                "text": str(getattr(hit, "text", "") or ""),
                "score": float(getattr(hit, "score", 0.0) or 0.0),
                "score_breakdown": dict(getattr(hit, "score_breakdown", {}) or {}),
                "result_granularity": str((dict(getattr(hit, "metadata", {}) or {})).get("result_granularity", "") or "block"),
                "metadata": {
                    **dict(getattr(hit, "metadata", {}) or {}),
                    "doc_id": str(getattr(hit, "doc_id", "") or ""),
                    "retrieval_modes": list(getattr(hit, "retrieval_modes", ()) or ()),
                },
            }
        )
    return payload


def _doc_ids(results: list[dict[str, object]]) -> list[str]:
    return [str((item.get("metadata") or {}).get("doc_id", "")).strip() for item in results]


def _mrr_at_k(doc_ids: list[str], gold_scores: dict[str, int], k: int) -> float:
    for rank, doc_id in enumerate(doc_ids[:k], start=1):
        if doc_id in gold_scores:
            return 1.0 / rank
    return 0.0


def _ndcg_at_k(doc_ids: list[str], gold_scores: dict[str, int], k: int) -> float:
    import math

    dcg = 0.0
    for rank, doc_id in enumerate(doc_ids[:k], start=1):
        rel = float(gold_scores.get(doc_id, 0))
        if rel <= 0:
            continue
        dcg += (2**rel - 1) / math.log2(rank + 1)
    ideal = sorted((float(score) for score in gold_scores.values() if score > 0), reverse=True)[:k]
    idcg = 0.0
    for rank, rel in enumerate(ideal, start=1):
        idcg += (2**rel - 1) / math.log2(rank + 1)
    return dcg / idcg if idcg > 0 else 0.0


def _evaluate_rankings(rankings: dict[str, list[dict[str, object]]], qrels: dict[str, dict[str, int]], *, metric_top_k: int) -> dict[str, float | int]:
    hit1 = 0
    hit3 = 0
    hit5 = 0
    hit10 = 0
    recall10: list[float] = []
    mrr10: list[float] = []
    ndcg10: list[float] = []
    for qid, results in rankings.items():
        gold = qrels[qid]
        doc_ids = _doc_ids(results)
        if any(doc_id in gold for doc_id in doc_ids[:1]):
            hit1 += 1
        if any(doc_id in gold for doc_id in doc_ids[:3]):
            hit3 += 1
        if any(doc_id in gold for doc_id in doc_ids[:5]):
            hit5 += 1
        if any(doc_id in gold for doc_id in doc_ids[: min(metric_top_k, 10)]):
            hit10 += 1
        recall10.append(sum(1 for doc_id in doc_ids[:metric_top_k] if doc_id in gold) / max(len(gold), 1))
        mrr10.append(_mrr_at_k(doc_ids, gold, metric_top_k))
        ndcg10.append(_ndcg_at_k(doc_ids, gold, metric_top_k))
    total = max(len(rankings), 1)
    return {
        "queries_evaluated": len(rankings),
        "accuracy_at_1": round(hit1 / total, 4),
        "hit_at_3": round(hit3 / total, 4),
        "hit_at_5": round(hit5 / total, 4),
        "hit_at_10": round(hit10 / total, 4),
        "recall_at_10": round(statistics.mean(recall10), 4) if recall10 else 0.0,
        "mrr_at_10": round(statistics.mean(mrr10), 4) if mrr10 else 0.0,
        "ndcg_at_10": round(statistics.mean(ndcg10), 4) if ndcg10 else 0.0,
    }


def _granularity_counts(rankings: dict[str, list[dict[str, object]]]) -> dict[str, int]:
    counts: dict[str, int] = {"document": 0, "page": 0, "block": 0, "object": 0}
    for results in rankings.values():
        for item in results:
            granularity = str(item.get("result_granularity", "") or (item.get("metadata") or {}).get("result_granularity", "") or "block")
            counts[granularity] = counts.get(granularity, 0) + 1
    return counts


def run_eval(config: EvalConfig, *, scifact_root: Path, index_root: Path) -> dict[str, object]:
    started_at_utc = _utc_now_iso()
    corpus, queries, qrels_frame = _load_scifact(scifact_root, config.split)
    qrels = _group_qrels(qrels_frame)
    sampled_queries = _sample_queries(queries, qrels, max_queries=config.max_queries, seed=config.seed)
    settings = get_settings()
    embed_model = build_embedding_model(settings)
    backend = LlamaIndexRetrievalBackend(index_root)
    if config.rebuild or not backend.layout.metadata_path("benchmark").exists():
        build_started = time.perf_counter()
        build_payload = backend.build_collection(
            "benchmark",
            _build_units(corpus),
            embed_model=embed_model,
        )
        build_seconds = time.perf_counter() - build_started
    else:
        meta_path = backend.layout.metadata_path("benchmark")
        build_payload = json.loads(meta_path.read_text(encoding="utf-8"))
        build_seconds = 0.0

    dense_health = backend.dense_health("benchmark", embed_model=embed_model)
    benchmark_mode = "hybrid_ready" if dense_health.get("available") and dense_health.get("query_ok") else "sparse_fallback_only"
    if benchmark_mode != "hybrid_ready" and not config.allow_degraded:
        raise RuntimeError(
            f"Benchmark dense path is not healthy: {json.dumps(dense_health, ensure_ascii=False)}. "
            "Use --allow-degraded only for diagnostics."
        )
    runtime_descriptor = backend.runtime_descriptor()
    chain_version = _chain_version(
        runtime_descriptor,
        use_rewrite=config.use_rewrite,
        use_rerank=config.use_rerank,
    )
    code_lineage = _code_lineage()
    index_lineage = _index_lineage(backend, index_root=index_root, build_payload=build_payload)
    build_id = "scifact-eval-" + _stable_digest(
        started_at_utc,
        chain_version,
        str(code_lineage.get("code_commit", "")),
        str(index_lineage.get("build_signature", "")),
        json.dumps(asdict(config), ensure_ascii=False, sort_keys=True),
    )[:12]

    rewriter = QueryRewriter()
    reranker = build_reranker(settings)
    base_rankings: dict[str, list[dict[str, object]]] = {}
    final_rankings: dict[str, list[dict[str, object]]] = {}
    retrieval_latencies: list[float] = []
    rerank_latencies: list[float] = []
    rewrite_changes = 0
    sample_failures: list[dict[str, object]] = []

    for item in sampled_queries:
        qid = item["id"]
        query = item["text"]
        rewritten = rewriter.rewrite(query).rewritten_query if config.use_rewrite else query
        if rewritten != query:
            rewrite_changes += 1
        started = time.perf_counter()
        hits = backend.retrieve(
            RetrievalRequest(
                query=rewritten,
                top_k=config.candidate_top_k,
                collections=("benchmark",),
                query_mode="semantic_lookup",
            ),
            embed_model=embed_model,
        )
        retrieval_latencies.append(time.perf_counter() - started)
        payload = _payload_from_hits(hits)
        base_rankings[qid] = payload[: config.metric_top_k]
        if config.use_rerank:
            rerank_started = time.perf_counter()
            ranked = reranker.rerank_dict_results(query=query, results=payload)
            rerank_latencies.append(time.perf_counter() - rerank_started)
        else:
            ranked = [dict(result) for result in payload]
        final_rankings[qid] = ranked[: config.metric_top_k]
        if not any(doc_id in qrels[qid] for doc_id in _doc_ids(final_rankings[qid])[: config.metric_top_k]) and len(sample_failures) < 10:
            sample_failures.append(
                {
                    "qid": qid,
                    "query": query,
                    "rewritten_query": rewritten,
                    "gold_doc_ids": sorted(qrels[qid])[:5],
                    "top_doc_ids": _doc_ids(final_rankings[qid])[: config.metric_top_k],
                }
            )

    return {
        "artifact_schema_version": "scifact_eval_v2",
        "artifact_created_at_utc": started_at_utc,
        "build_id": build_id,
        "chain_version": chain_version,
        "strategy_name": str(runtime_descriptor.get("strategy_name", "") or "baseline_dense_lexical"),
        "config": asdict(config),
        "scifact_root": str(scifact_root),
        "index_root": str(index_root),
        "runtime_descriptor": runtime_descriptor,
        "code_lineage": code_lineage,
        "index_lineage": index_lineage,
        "build_seconds": round(build_seconds, 3),
        "index_payload": build_payload,
        "dense_health": dense_health,
        "benchmark_mode": benchmark_mode,
        "rewrite_changed_queries": rewrite_changes,
        "base_retrieval": _evaluate_rankings(base_rankings, qrels, metric_top_k=config.metric_top_k),
        "current_chain": _evaluate_rankings(final_rankings, qrels, metric_top_k=config.metric_top_k),
        "base_result_granularity": _granularity_counts(base_rankings),
        "current_result_granularity": _granularity_counts(final_rankings),
        "latency": {
            "mean_retrieval_seconds": round(statistics.mean(retrieval_latencies), 4) if retrieval_latencies else 0.0,
            "mean_rerank_seconds": round(statistics.mean(rerank_latencies), 4) if rerank_latencies else 0.0,
        },
        "sample_failures": sample_failures,
    }


def main() -> int:
    args = _build_parser().parse_args()
    config = EvalConfig(
        split=str(args.split),
        max_queries=int(args.max_queries),
        candidate_top_k=int(args.candidate_top_k),
        metric_top_k=int(args.metric_top_k),
        seed=int(args.seed),
        use_rewrite=not bool(args.disable_rewrite),
        use_rerank=not bool(args.disable_rerank),
        rebuild=bool(args.rebuild),
        allow_degraded=bool(args.allow_degraded),
    )
    payload = run_eval(config, scifact_root=Path(args.scifact_root).resolve(), index_root=Path(args.index_root).resolve())
    artifact = _artifact_path(args.output or None)
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"artifact={artifact}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
