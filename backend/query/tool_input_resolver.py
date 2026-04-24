from __future__ import annotations

from pathlib import Path
from typing import Any

from RAG.parser_adapter import MultimodalParserAdapter
from pdf_analysis import PdfAnalysisCatalog
from structured_data import StructuredDataCatalog
from tools.definitions import get_tool_definition_map


class ToolInputResolver:
    def __init__(self, *, base_dir: Path) -> None:
        self.base_dir = base_dir.resolve()

    def resolve(
        self,
        *,
        plan: Any,
        history: list[dict[str, Any]],
    ) -> dict[str, Any]:
        message = plan.message
        understanding = plan.query_understanding
        tool_input = dict(understanding.tool_input or {"query": message})
        structured_binding = getattr(plan, "structured_binding", None)
        definition = get_tool_definition_map().get(str(understanding.tool_name or "").strip())
        resolution_contract = getattr(definition, "resolution_contract", None)
        if resolution_contract is None:
            return tool_input
        path_field = str(getattr(resolution_contract, "path_field", "") or "").strip()
        path_kind = str(getattr(resolution_contract, "path_kind", "") or "").strip()
        if path_field and path_kind:
            self._resolve_contract_path(
                tool_input=tool_input,
                path_field=path_field,
                path_kind=path_kind,
                message=message,
                allow_message_extraction=bool(getattr(resolution_contract, "allow_message_extraction", False)),
            )
        binding_field = str(getattr(resolution_contract, "binding_field", "") or "").strip()
        if binding_field:
            binding_path = str(getattr(structured_binding, binding_field, "") or "").strip()
            if binding_path and path_field:
                tool_input[path_field] = binding_path
        return tool_input

    def _resolve_contract_path(
        self,
        *,
        tool_input: dict[str, Any],
        path_field: str,
        path_kind: str,
        message: str,
        allow_message_extraction: bool,
    ) -> None:
        explicit_path = str(tool_input.get(path_field, "") or "").strip()
        if not explicit_path and allow_message_extraction and path_kind == "pdf":
            explicit_refs = PdfAnalysisCatalog.extract_explicit_pdf_references(message)
            explicit_path = explicit_refs[0] if explicit_refs else ""
        if not explicit_path:
            return
        resolved = self._resolve_explicit_path_reference(path_kind, explicit_path)
        if resolved is None:
            return
        tool_input[path_field] = self._format_resolved_path(path_kind, resolved)

    def _resolve_explicit_path_reference(self, path_kind: str, candidate: str) -> Path | None:
        if path_kind == "pdf":
            return self._resolve_explicit_pdf_reference(candidate)
        if path_kind == "dataset":
            return self._resolve_explicit_dataset_reference(candidate)
        if path_kind == "multimodal":
            return self._resolve_explicit_multimodal_file_reference(candidate)
        if path_kind == "workspace":
            return self._resolve_explicit_workspace_file_reference(candidate)
        return None

    def _format_resolved_path(self, path_kind: str, path: Path) -> str:
        if path_kind == "pdf":
            return PdfAnalysisCatalog.relative_path(self.base_dir, path)
        if path_kind == "dataset":
            return StructuredDataCatalog.relative_path(self.base_dir, path)
        return self._relative_to_base(path)

    def _relative_to_base(self, path: Path) -> str:
        return str(path.resolve().relative_to(self.base_dir)).replace("\\", "/")

    def _resolve_explicit_pdf_reference(self, candidate: str) -> Path | None:
        normalized = str(candidate or "").strip()
        if not normalized:
            return None
        candidates = PdfAnalysisCatalog.list_pdf_paths(self.base_dir)
        matched = PdfAnalysisCatalog._match_filename(self.base_dir, candidates, normalized)
        if matched is not None:
            return matched
        try:
            resolved = PdfAnalysisCatalog.resolve_pdf_path(self.base_dir, normalized, normalized)
        except ValueError:
            return None
        if not resolved.exists() or not resolved.is_file():
            return None
        return resolved

    def _resolve_explicit_dataset_reference(self, candidate: str) -> Path | None:
        normalized = str(candidate or "").strip()
        if not normalized:
            return None
        candidates = StructuredDataCatalog.list_dataset_paths(self.base_dir)
        matched = StructuredDataCatalog._match_filename(self.base_dir, candidates, normalized)
        if matched is not None:
            return matched
        try:
            resolved = StructuredDataCatalog.resolve_dataset_path(self.base_dir, normalized, normalized)
        except ValueError:
            return None
        if not resolved.exists() or not resolved.is_file():
            return None
        return resolved

    def _resolve_explicit_multimodal_file_reference(self, candidate: str) -> Path | None:
        normalized = str(candidate or "").strip()
        if not normalized:
            return None
        adapter = MultimodalParserAdapter(repo_root=self.base_dir.parent)
        direct = (self.base_dir / normalized).resolve()
        if direct.exists() and direct.is_file():
            try:
                direct.relative_to(self.base_dir)
            except ValueError:
                return None
            return direct if adapter.is_supported_file(direct) else None

        target_name = Path(normalized).name.lower()
        for path in self.base_dir.rglob("*"):
            if not path.is_file() or path.name.lower() != target_name:
                continue
            if not adapter.is_supported_file(path):
                continue
            return path.resolve()
        return None

    def _resolve_explicit_workspace_file_reference(self, candidate: str) -> Path | None:
        normalized = str(candidate or "").strip().replace("\\", "/")
        if not normalized:
            return None
        if normalized.lower().startswith("backend/"):
            normalized = normalized.split("/", 1)[1]
        direct = (self.base_dir / normalized).resolve()
        if direct.exists() and direct.is_file():
            try:
                direct.relative_to(self.base_dir)
            except ValueError:
                return None
            return direct

        target_name = Path(normalized).name.lower()
        for path in self.base_dir.rglob("*"):
            if not path.is_file() or path.name.lower() != target_name:
                continue
            return path.resolve()
        return None
