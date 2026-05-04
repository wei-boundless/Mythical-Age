# RAG Multimodal Prototype

`backend/RAG` is an independent multimodal parsing and retrieval prototype for the current agent.

It does not depend on `RAG-Anything` anymore. The idea is simpler:

1. parse common multimodal files locally
2. normalize them into unified chunks
3. reuse the current embedding + vector retrieval style

## Supported inputs

- PDF: local extraction with `pdfplumber` / `pypdf`, or MinerU API when configured
- Images: OCR with `Pillow + pytesseract` when available
- Markdown / text
- JSON
- CSV
- DOCX
- PPTX
- XLSX with `openpyxl` when available

Legacy `.doc/.ppt/.xls` files are recognized, but the parser will only produce a fallback note telling you to convert them first.

## Structure

- `backend/knowledge`
  This is the default knowledge source directory scanned by the multimodal indexer.
- `parser_adapter.py`
  Local multimodal parser that converts files into unified chunks.
- `cleaner.py`
  Lightweight cleaning logic for OCR noise, duplicate lines, empty table columns, and repeated headers/footers.
- `indexer.py`
  Standalone vector index persisted under `backend/storage/rag_index`.
- `models.py`
  Shared data models.
- `cli.py`
  CLI for checking capabilities, rebuilding the index, and running test queries.

## Flow

1. Put knowledge files into `backend/knowledge`
2. `MultimodalParserAdapter` parses them into `ParsedChunk`
3. Parsed content is cleaned before indexing
4. `RAGMultimodalIndexer` builds embeddings and stores the index
5. Retrieval returns `text`, `source`, `modality`, `page`, `score`, and metadata

## Directories

- Knowledge source directory: `backend/knowledge`
- Vector store directory: `backend/storage/rag_index`

## Minimal usage

```python
from pathlib import Path

from RAG import rag_multimodal_indexer

base_dir = Path("backend").resolve()
rag_multimodal_indexer.configure(base_dir, ocr_language="eng")
rag_multimodal_indexer.rebuild_index()
hits = rag_multimodal_indexer.retrieve_as_dicts("What does the table say?", top_k=5)
```

## CLI

```bash
cd backend
python -m RAG.cli status
python -m RAG.cli clean --path knowledge/example.pdf
python -m RAG.cli rebuild --ocr-language eng
python -m RAG.cli query --query "What is described in the image?" --top-k 5
```

## Notes

- MinerU API is optional. When `MINERU_API_ENABLED=true`, PDF parsing will try the remote MinerU service first and fall back to local extraction if the API is unavailable or returns unusable content.
- OCR is optional. If `pytesseract` is not installed, image parsing still keeps image metadata but will not extract text.
- On Windows, you can set `TESSERACT_CMD` to the full path of `tesseract.exe` if it is not on PATH.
- PDF extraction is optional. If `pypdf` is not installed, PDFs will be skipped.
- Embedding settings still come from the current backend config.
- The `clean` command lets you preview cleaned chunks before rebuilding the index.
