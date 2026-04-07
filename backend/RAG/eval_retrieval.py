from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from llama_index.core import Document, Settings as LlamaSettings, VectorStoreIndex
from llama_index.core.node_parser import SentenceSplitter

from config import get_settings
from embedding_compat import build_embedding_model
from RAG.hybrid import (
    BM25Index,
    build_searchable_text,
    merge_scores,
    normalize_dense_score,
    normalize_keyword_score,
    reciprocal_rank_fusion,
    required_bm25_term_matches,
)
from RAG.query_rewriter import QueryRewriter
from RAG.reranker import build_reranker


def _read_parquet_rows(path: Path) -> list[dict[str, Any]]:
    try:
        import pyarrow.parquet as pq  # type: ignore

        table = pq.read_table(path)
        return table.to_pylist()
    except Exception:
        try:
            import pandas as pd  # type: ignore

            frame = pd.read_parquet(path)
            return frame.to_dict(orient="records")
        except Exception as exc:  # pragma: no cover - depends on local env
            raise RuntimeError(
                "Failed to read parquet. Install pyarrow or pandas."
            ) from exc


def _first_parquet(data_dir: Path) -> Path:
    matches = sorted(data_dir.glob("*.parquet"))
    if not matches:
        raise FileNotFoundError(f"No parquet files found under {data_dir}")
    return matches[0]


def _load_dataset(dataset_dir: Path, qrels_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    corpus_path = _first_parquet(dataset_dir / "data")
    queries_path = next(
        path
        for path in sorted((dataset_dir / "data").glob("*.parquet"))
        if "queries" in path.name
    )
    qrels_path = _first_parquet(qrels_dir / "data")
    return (
        _read_parquet_rows(corpus_path),
        _read_parquet_rows(queries_path),
        _read_parquet_rows(qrels_path),
    )


def _build_documents(corpus_rows: list[dict[str, Any]], *, max_docs: int | None = None) -> list[Document]:
    docs: list[Document] = []
    for row in corpus_rows[: max_docs or None]:
        doc_id = str(row.get("id", "")).strip()
        text = str(row.get("text", "")).strip()
        if not doc_id or not text:
            continue
        docs.append(
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
    return docs


def _group_qrels(qrels_rows: list[dict[str, Any]]) -> dict[str, set[str]]:
    grouped: dict[str, set[str]] = {}
    for row in qrels_rows:
        qid = str(row.get("qid", "")).strip()
        pid = str(row.get("pid", "")).strip()
        score = int(row.get("score", 0) or 0)
        if not qid or not pid or score <= 0:
            continue
        grouped.setdefault(qid, set()).add(pid)
    return grouped


def _filter_queries(
    queries_rows: list[dict[str, Any]],
    qrels: dict[str, set[str]],
    *,
    max_queries: int | None = None,
) -> list[dict[str, Any]]:
    filtered = [
        row
        for row in queries_rows
        if str(row.get("id", "")).strip() in qrels and str(row.get("text", "")).strip()
    ]
    return filtered[: max_queries or None]


def _evaluate(
    index: VectorStoreIndex,
    docs: list[Document],
    queries: list[dict[str, Any]],
    qrels: dict[str, set[str]],
    *,
    top_k: int,
    use_rewrite: bool,
    use_rerank: bool,
    use_hybrid: bool,
) -> dict[str, Any]:
    rewriter = QueryRewriter()
    reranker = build_reranker(get_settings())
    retriever = index.as_retriever(similarity_top_k=max(top_k, 8))
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

    total = len(queries)
    hit1 = 0
    hit3 = 0
    hit5 = 0
    misses: list[dict[str, Any]] = []

    for row in queries:
        qid = str(row["id"])
        query = str(row["text"])
        rewritten = rewriter.rewrite(query).rewritten_query if use_rewrite else query
        payload = _dense_payload(retriever.retrieve(rewritten))
        if use_hybrid:
            payload = _hybrid_fuse(
                query=query,
                dense_payload=payload,
                docs=docs,
                top_k=max(top_k, 8),
                bm25_index=bm25_index,
            )
        if use_rerank:
            payload = reranker.rerank_dict_results(query=query, results=payload)
        retrieved_ids = [str((item.get("metadata") or {}).get("doc_id", "")) for item in payload]
        gold = qrels.get(qid, set())

        if any(doc_id in gold for doc_id in retrieved_ids[:1]):
            hit1 += 1
        if any(doc_id in gold for doc_id in retrieved_ids[:3]):
            hit3 += 1
        if any(doc_id in gold for doc_id in retrieved_ids[:5]):
            hit5 += 1
        if not any(doc_id in gold for doc_id in retrieved_ids[:top_k]):
            misses.append(
                {
                    "qid": qid,
                    "query": query,
                    "rewritten_query": rewritten,
                    "gold_doc_ids": sorted(gold)[:5],
                    "retrieved_doc_ids": retrieved_ids[:top_k],
                }
            )

    denominator = max(total, 1)
    return {
        "queries_evaluated": total,
        "hit_at_1": round(hit1 / denominator, 4),
        "hit_at_3": round(hit3 / denominator, 4),
        "hit_at_5": round(hit5 / denominator, 4),
        "sample_misses": misses[:10],
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate retrieval with corpus/queries/qrels parquet files.")
    parser.add_argument("--dataset-dir", required=True, help="Path to dataset directory like EcomRetrieval")
    parser.add_argument("--qrels-dir", required=True, help="Path to qrels directory like EcomRetrieval-qrels")
    parser.add_argument("--max-docs", type=int, default=5000, help="Optional corpus cap for faster local testing")
    parser.add_argument("--max-queries", type=int, default=100, help="Optional query cap for faster local testing")
    parser.add_argument("--top-k", type=int, default=5, help="Top K retrieval depth")
    parser.add_argument("--disable-rewrite", action="store_true", help="Disable query rewrite before retrieval")
    parser.add_argument("--disable-rerank", action="store_true", help="Disable heuristic rerank after retrieval")
    parser.add_argument("--disable-hybrid", action="store_true", help="Disable keyword+dense hybrid fusion")
    return parser


def _dense_payload(results: list[Any]) -> list[dict[str, Any]]:
    payload = []
    for item in results:
        node = getattr(item, "node", item)
        metadata = getattr(node, "metadata", {}) or {}
        payload.append(
            {
                "text": getattr(node, "text", "") or getattr(node, "get_content", lambda: "")(),
                "source": metadata.get("source", ""),
                "metadata": metadata,
                "score": float(getattr(item, "score", 0.0) or 0.0),
            }
        )
    return payload


def _hybrid_fuse(
    *,
    query: str,
    dense_payload: list[dict[str, Any]],
    docs: list[Document],
    top_k: int,
    bm25_index: BM25Index | None = None,
) -> list[dict[str, Any]]:
    fused: dict[str, dict[str, Any]] = {}
    for rank, item in enumerate(dense_payload, start=1):
        metadata = dict(item.get("metadata") or {})
        key = str(metadata.get("doc_id", "")) or f"dense::{rank}"
        fused[key] = {
            **item,
            "score": merge_scores(
                reciprocal_rank_fusion(rank),
                normalize_dense_score(float(item.get("score", 0.0) or 0.0)),
            ),
            "hybrid_reasons": ["dense"],
        }

    active_bm25 = bm25_index or BM25Index.from_texts(
        [
            build_searchable_text(
                doc.text,
                source=str(doc.metadata.get("source", "")),
                metadata=dict(doc.metadata),
            )
            for doc in docs
        ]
    )

    lexical_rows: list[dict[str, Any]] = []
    min_term_matches = required_bm25_term_matches(query)
    for match in active_bm25.search(query, top_k=top_k * 2):
        if match.matched_term_count < min_term_matches:
            continue
        doc = docs[match.index]
        metadata = dict(doc.metadata)
        lexical_rows.append(
            {
                "text": doc.text,
                "source": metadata.get("source", ""),
                "metadata": metadata,
                "keyword_score": float(match.score),
                "hybrid_reasons": [
                    "bm25",
                    f"matched_terms:{len(match.matched_terms)}",
                    *[f"term:{term}" for term in match.matched_terms[:3]],
                    "keyword",
                ],
            }
        )
        if len(lexical_rows) >= top_k:
            break

    best_keyword_score = max(float(row["keyword_score"]) for row in lexical_rows) if lexical_rows else 0.0
    for rank, item in enumerate(lexical_rows[:top_k], start=1):
        metadata = dict(item.get("metadata") or {})
        key = str(metadata.get("doc_id", "")) or f"keyword::{rank}"
        lexical_score = merge_scores(
            reciprocal_rank_fusion(rank),
            normalize_keyword_score(
                float(item["keyword_score"]),
                ceiling=best_keyword_score,
            ),
        )
        if key in fused:
            fused[key]["score"] = float(fused[key]["score"]) + lexical_score
            fused[key]["hybrid_reasons"] = list(dict.fromkeys(list(fused[key].get("hybrid_reasons", [])) + list(item["hybrid_reasons"])))
        else:
            fused[key] = {
                "text": item["text"],
                "source": item["source"],
                "metadata": metadata,
                "score": lexical_score,
                "hybrid_reasons": item["hybrid_reasons"],
            }
    return sorted(fused.values(), key=lambda row: float(row.get("score", 0.0)), reverse=True)[:top_k]


def main() -> int:
    args = _build_parser().parse_args()

    dataset_dir = Path(args.dataset_dir).resolve()
    qrels_dir = Path(args.qrels_dir).resolve()
    corpus_rows, queries_rows, qrels_rows = _load_dataset(dataset_dir, qrels_dir)

    docs = _build_documents(corpus_rows, max_docs=args.max_docs)
    kept_doc_ids = {doc.metadata["doc_id"] for doc in docs}
    qrels = {
        qid: {pid for pid in pids if pid in kept_doc_ids}
        for qid, pids in _group_qrels(qrels_rows).items()
    }
    qrels = {qid: pids for qid, pids in qrels.items() if pids}
    queries = _filter_queries(
        queries_rows,
        qrels,
        max_queries=args.max_queries,
    )

    settings = get_settings()
    LlamaSettings.embed_model = build_embedding_model(settings)
    splitter = SentenceSplitter(
        chunk_size=settings.rag_chunk_size,
        chunk_overlap=settings.rag_chunk_overlap,
    )
    nodes = splitter.get_nodes_from_documents(docs)
    index = VectorStoreIndex(nodes)

    metrics = _evaluate(
        index,
        docs,
        queries,
        qrels,
        top_k=args.top_k,
        use_rewrite=not args.disable_rewrite,
        use_rerank=not args.disable_rerank,
        use_hybrid=not args.disable_hybrid,
    )

    payload = {
        "dataset_dir": str(dataset_dir),
        "qrels_dir": str(qrels_dir),
        "documents_indexed": len(docs),
        "nodes_indexed": len(nodes),
        "rewrite_enabled": not args.disable_rewrite,
        "hybrid_enabled": not args.disable_hybrid,
        "rerank_enabled": not args.disable_rerank,
        "chunk_size": settings.rag_chunk_size,
        "chunk_overlap": settings.rag_chunk_overlap,
        "embedding_dimensions": settings.embedding_dimensions,
        "metrics": metrics,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
