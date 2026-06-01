from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from capability_system.capabilities.document_processing.pdf.analysis.catalog import PdfAnalysisCatalog
from capability_system.capabilities.retrieval.collections import build_default_collections
from capability_system.capabilities.structured_data.catalog import StructuredDataCatalog
from capability_system.tools.tool_units.read_file_tool import ReadFileTool
from capability_system.tools.tool_units.search_files_tool import SearchFilesTool
from capability_system.tools.tool_units.write_file_tool import WriteFileTool
from project_layout import ProjectLayout


def test_rag_layout_defaults_to_external_data_root_and_keeps_memory_in_storage(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    backend_dir = project / "backend"
    backend_dir.mkdir(parents=True)
    monkeypatch.delenv("APP_EXTERNAL_DATA_ROOT", raising=False)
    monkeypatch.delenv("APP_KNOWLEDGE_ROOT", raising=False)
    monkeypatch.delenv("APP_INDEXES_ROOT", raising=False)
    monkeypatch.delenv("APP_DOCUMENT_CACHE_ROOT", raising=False)

    layout = ProjectLayout.from_backend_dir(backend_dir)

    assert layout.external_data_root == tmp_path / "project-data"
    assert layout.knowledge_storage_dir == tmp_path / "project-data" / "knowledge"
    assert layout.indexes_dir == tmp_path / "project-data" / "indexes"
    assert layout.document_cache_dir == tmp_path / "project-data" / "document_cache"
    assert layout.durable_memory_dir == project / "storage" / "durable_memory"
    assert layout.session_memory_dir == project / "storage" / "session_memory"
    assert layout.task_durable_memory_dir == project / "storage" / "task_durable_memory"


def test_rag_layout_env_overrides_are_centralized(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    backend_dir = project / "backend"
    backend_dir.mkdir(parents=True)
    external_root = tmp_path / "rag-data"
    monkeypatch.setenv("APP_EXTERNAL_DATA_ROOT", str(external_root))
    monkeypatch.setenv("APP_KNOWLEDGE_ROOT", str(tmp_path / "knowledge-root"))

    layout = ProjectLayout.from_backend_dir(backend_dir)

    assert layout.external_data_root == external_root
    assert layout.knowledge_storage_dir == tmp_path / "knowledge-root"
    assert layout.indexes_dir == external_root / "indexes"


def test_ensure_storage_dirs_migrates_rag_assets_but_not_memory(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    backend_dir = project / "backend"
    legacy_knowledge = project / "storage" / "knowledge"
    legacy_indexes = project / "storage" / "indexes"
    memory_dir = project / "storage" / "durable_memory"
    backend_dir.mkdir(parents=True)
    legacy_knowledge.mkdir(parents=True)
    legacy_indexes.mkdir(parents=True)
    memory_dir.mkdir(parents=True)
    (legacy_knowledge / "note.md").write_text("knowledge", encoding="utf-8")
    (legacy_indexes / "meta.json").write_text("{}", encoding="utf-8")
    (memory_dir / "memory.md").write_text("memory", encoding="utf-8")
    monkeypatch.setenv("APP_EXTERNAL_DATA_ROOT", str(tmp_path / "external-data"))

    layout = ProjectLayout.from_backend_dir(backend_dir)
    layout.ensure_storage_dirs()

    assert (layout.knowledge_storage_dir / "note.md").read_text(encoding="utf-8") == "knowledge"
    assert (layout.indexes_dir / "meta.json").read_text(encoding="utf-8") == "{}"
    assert not legacy_knowledge.exists()
    assert not legacy_indexes.exists()
    assert (memory_dir / "memory.md").read_text(encoding="utf-8") == "memory"


def test_retrieval_collections_use_external_rag_indexes_and_project_memory_sources(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    backend_dir = project / "backend"
    backend_dir.mkdir(parents=True)
    external_root = tmp_path / "rag-data"
    monkeypatch.setenv("APP_EXTERNAL_DATA_ROOT", str(external_root))

    collections = build_default_collections(backend_dir)

    assert collections["knowledge"].source_dirs == (external_root / "knowledge",)
    assert collections["knowledge"].storage_dir == external_root / "indexes" / "knowledge"
    assert collections["durable_memory"].storage_dir == external_root / "indexes" / "durable_memory"
    assert project / "storage" / "durable_memory" in collections["durable_memory"].source_dirs[0].parents
    assert collections["session_memory"].source_dirs == (project / "storage" / "session_memory",)


def test_knowledge_logical_paths_resolve_to_external_physical_root(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    backend_dir = project / "backend"
    backend_dir.mkdir(parents=True)
    external_root = tmp_path / "rag-data"
    monkeypatch.setenv("APP_EXTERNAL_DATA_ROOT", str(external_root))
    knowledge_dir = external_root / "knowledge"
    knowledge_dir.mkdir(parents=True)
    (knowledge_dir / "note.md").write_text("external knowledge", encoding="utf-8")

    reader = ReadFileTool(root_dir=backend_dir)
    writer = WriteFileTool(root_dir=backend_dir)
    search = SearchFilesTool(root_dir=backend_dir)

    assert reader.invoke({"path": "knowledge/note.md"}) == "external knowledge"
    assert writer.invoke({"path": "knowledge/new.md", "content": "new external"}) == "Write succeeded: knowledge/new.md"
    assert (knowledge_dir / "new.md").read_text(encoding="utf-8") == "new external"
    assert "knowledge/note.md" in search.invoke({"query": "note", "roots": ["knowledge"], "max_results": 10})


def test_pdf_and_structured_catalogs_keep_knowledge_logical_paths(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    backend_dir = project / "backend"
    backend_dir.mkdir(parents=True)
    external_root = tmp_path / "rag-data"
    monkeypatch.setenv("APP_EXTERNAL_DATA_ROOT", str(external_root))
    (external_root / "knowledge" / "AI Knowledge").mkdir(parents=True)
    (external_root / "knowledge" / "E-commerce Data").mkdir(parents=True)
    pdf_path = external_root / "knowledge" / "AI Knowledge" / "report.pdf"
    xlsx_path = external_root / "knowledge" / "E-commerce Data" / "employees.xlsx"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    xlsx_path.write_bytes(b"placeholder")

    assert PdfAnalysisCatalog.relative_path(backend_dir, pdf_path) == "knowledge/AI Knowledge/report.pdf"
    assert PdfAnalysisCatalog.resolve_pdf_path(backend_dir, "knowledge/AI Knowledge/report.pdf", "") == pdf_path
    assert StructuredDataCatalog.relative_path(backend_dir, xlsx_path) == "knowledge/E-commerce Data/employees.xlsx"
    assert StructuredDataCatalog.resolve_dataset_path(backend_dir, "knowledge/E-commerce Data/employees.xlsx", "") == xlsx_path
