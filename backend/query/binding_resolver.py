from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from query.binding_models import StructuredDatasetBinding
from structured_data import StructuredDataCatalog


class StructuredBindingResolver:
    def __init__(self, *, base_dir: Path) -> None:
        self.base_dir = base_dir

    def resolve(
        self,
        *,
        message: str,
        understanding: Any,
        history: list[dict[str, Any]],
    ) -> StructuredDatasetBinding | None:
        if not self._looks_structured(understanding):
            return None

        tool_input = dict(getattr(understanding, "tool_input", {}) or {})

        path_candidate = str(tool_input.get("path", "") or "").strip()
        if path_candidate:
            resolved = self._resolve_explicit_candidate(path_candidate)
            if resolved is not None:
                return StructuredDatasetBinding(
                    dataset_path=StructuredDataCatalog.relative_path(self.base_dir, resolved),
                    target_object=str(getattr(understanding, "target_object", "") or ""),
                    source="prebound_tool_input",
                    confidence=float(getattr(understanding, "confidence", 0.0) or 0.0),
                    explicit_switch=self._looks_explicit_switch(message),
                )

        explicit_match = self._extract_explicit_dataset_path(message)
        if explicit_match:
            resolved = self._resolve_explicit_candidate(explicit_match)
            if resolved is not None:
                return StructuredDatasetBinding(
                    dataset_path=StructuredDataCatalog.relative_path(self.base_dir, resolved),
                    target_object=str(getattr(understanding, "target_object", "") or ""),
                    source="explicit_path",
                    confidence=float(getattr(understanding, "confidence", 0.0) or 0.0),
                    explicit_switch=True,
                )

        target_object = str(getattr(understanding, "target_object", "") or "").strip()
        if target_object:
            try:
                resolved = StructuredDataCatalog.resolve_dataset_path(self.base_dir, "", message)
            except ValueError:
                resolved = None
            if resolved is not None:
                return StructuredDatasetBinding(
                    dataset_path=StructuredDataCatalog.relative_path(self.base_dir, resolved),
                    target_object=target_object,
                    source="semantic_default",
                    confidence=float(getattr(understanding, "confidence", 0.0) or 0.0),
                    explicit_switch=self._looks_explicit_switch(message),
                )

        resolved = StructuredDataCatalog.resolve_dataset_path_from_history(self.base_dir, history)
        if resolved is None:
            return None
        return StructuredDatasetBinding(
            dataset_path=StructuredDataCatalog.relative_path(self.base_dir, resolved),
            target_object=target_object,
            source="history_fallback",
            confidence=0.55,
            explicit_switch=False,
        )

    def _looks_structured(self, understanding: Any) -> bool:
        tool_name = str(getattr(understanding, "tool_name", "") or "").strip()
        source_kind = str(getattr(understanding, "source_kind", "") or "").strip()
        return tool_name == "structured_data_analysis" or source_kind == "dataset"

    def _extract_explicit_dataset_path(self, message: str) -> str:
        normalized = (message or "").strip()
        if not normalized:
            return ""
        match = re.search(
            r"([^\s,，;；:：\"'“”‘’]+?\.(?:xlsx|csv|xls|json|parquet))",
            normalized,
            flags=re.IGNORECASE,
        )
        return match.group(1).strip() if match is not None else ""

    def _resolve_explicit_candidate(self, candidate: str) -> Path | None:
        normalized = (candidate or "").strip()
        if not normalized:
            return None
        datasets = StructuredDataCatalog.list_dataset_paths(self.base_dir)
        matched = StructuredDataCatalog._match_filename(self.base_dir, datasets, normalized)
        if matched is not None:
            return matched
        try:
            return StructuredDataCatalog.resolve_dataset_path(self.base_dir, normalized, normalized)
        except ValueError:
            return None

    def _looks_explicit_switch(self, message: str) -> bool:
        lowered = (message or "").lower()
        if any(ext in lowered for ext in (".xlsx", ".csv", ".xls", ".json", ".parquet")):
            return True
        return any(marker in message for marker in ("切到", "换成", "回到", "再切回"))
