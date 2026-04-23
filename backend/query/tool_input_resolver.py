from __future__ import annotations

from pathlib import Path
from typing import Any

from pdf_analysis import PdfAnalysisCatalog
from structured_data import StructuredDataCatalog


class ToolInputResolver:
    def __init__(self, *, base_dir: Path) -> None:
        self.base_dir = base_dir

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
        if understanding.tool_name == "pdf_analysis" and not str(tool_input.get("path", "") or "").strip():
            explicit_refs = PdfAnalysisCatalog.extract_explicit_pdf_references(message)
            if explicit_refs:
                resolved = self._resolve_explicit_pdf_reference(explicit_refs[0])
                if resolved is not None:
                    tool_input["path"] = PdfAnalysisCatalog.relative_path(self.base_dir, resolved)
        if understanding.tool_name == "structured_data_analysis":
            explicit_path = str(tool_input.get("path", "") or "").strip()
            if explicit_path:
                resolved = self._resolve_explicit_dataset_reference(explicit_path)
                if resolved is not None:
                    tool_input["path"] = StructuredDataCatalog.relative_path(self.base_dir, resolved)
            binding_path = str(getattr(structured_binding, "dataset_path", "") or "").strip()
            if binding_path:
                tool_input["path"] = binding_path
        return tool_input

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
