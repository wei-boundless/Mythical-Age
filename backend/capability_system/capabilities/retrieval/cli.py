from __future__ import annotations

import argparse
import json
from pathlib import Path

from memory_system.governance_service import DurableMemoryGovernanceService
from memory_system.layout import durable_memory_layout_from_backend_dir
from memory_system.storage.memory_manager import MemoryManager
from core.project_layout import ProjectLayout
from capability_system.capabilities.document_processing.adapters.local_parser import LocalDocumentParser
from capability_system.capabilities.document_processing.kernel import DocumentProcessingKernel
from capability_system.capabilities.retrieval.service import RetrievalService
from knowledge_system.conversion.models import SourceFileRecord

from .registry import RAGIndexRegistry


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
        help="OCR language hint used by image OCR when available",
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

    base_dir = Path(__file__).resolve().parents[3]
    layout = ProjectLayout.from_backend_dir(base_dir)
    durable_layout = durable_memory_layout_from_backend_dir(base_dir)
    local_parser = LocalDocumentParser(repo_root=base_dir.parent, ocr_language=args.ocr_language)
    document_kernel = DocumentProcessingKernel(repo_root=base_dir.parent)
    registry = RAGIndexRegistry(base_dir, ocr_language=args.ocr_language)
    retrieval_service = RetrievalService(base_dir)

    if args.command == "status":
        print(
            json.dumps(
                {
                    "configured": True,
                    "document_kernel_version": document_kernel.version,
                    "parser_available": local_parser.parser_available(),
                    "capabilities": local_parser.capabilities(),
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
            payload = {args.collection: retrieval_service.rebuild_collection(args.collection.strip())}
        else:
            payload = retrieval_service.rebuild_all_collections()
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
        normalized_path = args.path.strip().replace("\\", "/").strip("/")
        if normalized_path.lower().startswith("knowledge/"):
            file_path = (layout.knowledge_storage_dir / normalized_path.split("/", 1)[1]).resolve()
        else:
            file_path = (base_dir / normalized_path).resolve()
        if not file_path.exists():
            parser.error("the provided --path does not exist")
        if normalized_path.lower().startswith("knowledge/"):
            record = SourceFileRecord.from_path(file_path, collection="knowledge", root_dir=layout.knowledge_storage_dir)
        else:
            record = SourceFileRecord.from_path(file_path, collection="diagnostic", root_dir=base_dir)
        bundle = document_kernel.parse(record)
        conversion = bundle.rag_projection.conversion_result
        print(
            json.dumps(
                {
                    "document_kernel_version": document_kernel.version,
                    "document_bundle_id": bundle.bundle_id,
                    "detected_format": bundle.detected_format.to_metadata(),
                    "parser_backend": conversion.parser_backend,
                    "parser_route": list(conversion.parser_route),
                    "quality_flags": list(conversion.quality_flags),
                    "diagnostics": [diagnostic.to_dict() for diagnostic in bundle.diagnostics],
                    "blocks": [
                        {
                            "block_id": block.block_id,
                            "block_type": block.block_type,
                            "modality": block.modality,
                            "page": block.page,
                            "section": block.section_label,
                            "metadata": block.metadata,
                            "text": block.text,
                        }
                        for block in conversion.blocks
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.command in {"durable-memory-maintain", "memory-maintain"}:
        manager = MemoryManager(durable_layout.root_dir)
        governance_service = DurableMemoryGovernanceService(base_dir, memory_manager=manager)
        governance_service.mark_namespaces_dirty({"global_common": 1}, reason="retrieval_cli_manual_maintain")
        governance_payload = governance_service.run_governance_tick(
            namespace_ids=["global_common"],
            force=True,
            min_interval_seconds=0,
            reason="retrieval_cli_manual_maintain",
            source="capability_system.retrieval.cli",
        )
        index_payload = manager.ensure_index_consistent()
        rag_payload = retrieval_service.rebuild_collection("durable_memory")
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
        manager = MemoryManager(durable_layout.root_dir)
        governance_service = DurableMemoryGovernanceService(base_dir, memory_manager=manager)
        governance_service.mark_namespaces_dirty({"global_common": 1}, reason="retrieval_cli_manual_consolidate")
        report = governance_service.run_governance_tick(
            namespace_ids=["global_common"],
            force=True,
            min_interval_seconds=0,
            reason="retrieval_cli_manual_consolidate",
            source="capability_system.retrieval.cli",
        )
        rag_payload = retrieval_service.rebuild_collection("durable_memory")
        print(
            json.dumps(
                {
                    "status": "ok",
                    "durable_memory_consolidation": report,
                    "durable_memory_collection": rag_payload,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if not args.query.strip():
        parser.error("--query is required when command is `query`")

    result = retrieval_service.retrieve_execution(args.query, top_k=args.top_k)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())




