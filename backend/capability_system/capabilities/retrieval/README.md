# Retrieval MCP

This package contains the local retrieval MCP unit and the local parsing helpers
still needed by the current document conversion pipeline.

The active chat/retrieval path is:

1. `RetrievalService` builds a route plan.
2. `RetrievalBootstrapper` discovers and converts source documents.
3. `knowledge_system.ingestion` cleans blocks and builds hierarchical index units.
4. `LlamaIndexRetrievalBackend` stores dense vectors in Qdrant and lexical BM25
   data under the external indexes root resolved by `ProjectLayout.indexes_dir`.
5. Retrieval fuses dense and lexical candidates, coalesces related hits, reranks
   candidates, and emits evidence for the runtime.

## Supported inputs

- PDF: local extraction with `pdfplumber` / `pypdf`, or MinerU API when configured
- Images: OCR with RapidOCR when available
- Markdown / text
- JSON
- CSV
- DOCX
- PPTX
- XLSX with `openpyxl` when available

Binary `.doc/.ppt/.xls` files are recognized, but the parser will only produce a fallback note telling you to convert them first.

## Structure

- `collections.py`
  Defines `knowledge`, `durable_memory`, `session_memory`, and optional benchmark
  collections.
- `router.py`
  Rewrites and routes queries to collection/filter/policy plans.
- `reranker.py`
  Provides no-op, heuristic, local cross-encoder, and remote API rerankers.
- `parser_adapter.py`
  Local multimodal parser kept as a fallback for document conversion.
- `registry.py`
  Collection wrapper around the active retrieval backend. New runtime code
  should prefer `capability_system.capabilities.retrieval.RetrievalService`.
- `cli.py`
  Maintenance helper for collection status, rebuilds, and test queries.

## Directories

- Knowledge source directory: `ProjectLayout.knowledge_storage_dir`
- Index root: `ProjectLayout.indexes_dir`
- Document conversion cache: `ProjectLayout.document_cache_dir`

By default these RAG data roots live outside the project at `../langchain-agent-data`.
Use `APP_EXTERNAL_DATA_ROOT`, `APP_KNOWLEDGE_ROOT`, `APP_INDEXES_ROOT`, or
`APP_DOCUMENT_CACHE_ROOT` to override them.

## Minimal usage

```python
from pathlib import Path

from capability_system.capabilities.retrieval import RetrievalService

service = RetrievalService(Path("backend").resolve())
result = service.retrieve_execution("What does the table say?", top_k=5)
```

## CLI

```bash
cd backend
python -m capability_system.capabilities.retrieval.cli status
python -m capability_system.capabilities.retrieval.cli clean --path knowledge/example.pdf
python -m capability_system.capabilities.retrieval.cli rebuild --ocr-language eng
python -m capability_system.capabilities.retrieval.cli query --query "What is described in the image?" --top-k 5
```

## Notes

- MinerU API is optional. When `MINERU_API_ENABLED=true`, PDF parsing will try the remote MinerU service first and fall back to local extraction if the API is unavailable or returns unusable content.
- OCR is optional. If RapidOCR is not installed, image parsing still keeps image metadata but will not extract text.
- PDF extraction is optional. If `pypdf` is not installed, PDFs will be skipped.
- Embedding settings still come from the current backend config.
- The `clean` command lets you preview cleaned chunks before rebuilding the index.
