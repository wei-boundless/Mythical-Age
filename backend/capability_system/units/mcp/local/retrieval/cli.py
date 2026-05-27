from __future__ import annotations

import argparse
import json
from pathlib import Path

from memory_system.layout import durable_memory_layout_from_backend_dir
from memory_system.storage.consolidation import DurableMemoryConsolidator
from memory_system.storage.memory_manager import MemoryManager
from project_layout import ProjectLayout

from .parser_adapter import MultimodalParserAdapter
from .registry import RAGIndexRegistry
from .router import RAGQueryRouter


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="RAG multimodal CLI")
    parser.add_argument(
        "command",
        choices=[
            "status",
            "rebuild",
            "query",
            "clean",
            "durable-memory-maintain",
            "memory-maintain",
            "durable-memory-consolidate",
        ],
        help="Command to run",
    )
    parser.add_argument(
        "--ocr-language",
        default="eng",
        help="OCR language passed to pytesseract when image OCR is available",
    )
    parser.add_argument(
        "--query",
        default="",
        help="Query text for the `query` command",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Top K results for the `query` command",
    )
    parser.add_argument(
        "--path",
        default="",
        help="Relative path inside backend for the `clean` command",
    )
    parser.add_argument(
        "--collection",
        default="",
        help="Optional collection name for the `rebuild` command. Defaults to rebuilding all collections.",
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    base_dir = Path(__file__).resolve().parents[1]
    layout = ProjectLayout.from_backend_dir(base_dir)
    durable_layout = durable_memory_layout_from_backend_dir(base_dir)
    adapter = MultimodalParserAdapter(repo_root=base_dir.parent, ocr_language=args.ocr_language)
    registry = RAGIndexRegistry(base_dir, ocr_language=args.ocr_language)
    router = RAGQueryRouter(base_dir, ocr_language=args.ocr_language)

    if args.command == "status":
        print(
            json.dumps(
                {
                    "configured": True,
                    "parser_available": adapter.parser_available(),
                    "capabilities": adapter.capabilities(),
                    "knowledge_dir": str(layout.knowledge_storage_dir),
                    "collections": registry.list_collections(),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.command == "rebuild":
        if args.collection.strip():
            payload = {args.collection: registry.rebuild(args.collection.strip())}
        else:
            payload = registry.rebuild_all()
        print(
            json.dumps(
                {
                    "status": "ok",
                    "collections": payload,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.command == "clean":
        if not args.path.strip():
            parser.error("--path is required when command is `clean`")
        file_path = (base_dir / args.path).resolve()
        if not file_path.exists():
            parser.error("the provided --path does not exist")
        chunks = adapter.parse_file(file_path)
        print(
            json.dumps(
                [
                    {
                        "source": chunk.source,
                        "modality": chunk.modality,
                        "page": chunk.page,
                        "section": chunk.section,
                        "metadata": chunk.metadata,
                        "text": chunk.text,
                    }
                    for chunk in chunks
                ],
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.command in {"durable-memory-maintain", "memory-maintain"}:
        manager = MemoryManager(durable_layout.root_dir)
        governance_payload = manager.govern_note_store()
        index_payload = manager.ensure_index_consistent()
        rag_payload = registry.rebuild("durable_memory")
        print(
            json.dumps(
                {
                    "status": "ok",
                    "durable_memory_store": {
                        "governance": governance_payload,
                        "index": index_payload,
                    },
                    "durable_memory_collection": rag_payload,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.command == "durable-memory-consolidate":
        consolidator = DurableMemoryConsolidator(durable_layout.root_dir)
        report = consolidator.run()
        rag_payload = registry.rebuild("durable_memory")
        print(
            json.dumps(
                {
                    "status": "ok",
                    "durable_memory_consolidation": report.to_dict(),
                    "durable_memory_collection": rag_payload,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if not args.query.strip():
        parser.error("--query is required when command is `query`")

    hits = router.retrieve(args.query, top_k=args.top_k)
    print(json.dumps(hits, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())



