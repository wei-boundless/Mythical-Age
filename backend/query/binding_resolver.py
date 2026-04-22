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
                    target_object=StructuredDataCatalog.target_object_for_path(resolved),
                    source="prebound_tool_input",
                    confidence=float(getattr(understanding, "confidence", 0.0) or 0.0),
                    binding_identity=StructuredDataCatalog.relative_path(self.base_dir, resolved).replace("\\", "/").lower(),
                    explicit_switch=self._looks_explicit_switch(message),
                )
            return None

        explicit_match = self._extract_explicit_dataset_path(message)
        if explicit_match:
            resolved = self._resolve_explicit_candidate(explicit_match)
            if resolved is not None:
                return StructuredDatasetBinding(
                    dataset_path=StructuredDataCatalog.relative_path(self.base_dir, resolved),
                    target_object=StructuredDataCatalog.target_object_for_path(resolved),
                    source="explicit_path",
                    confidence=float(getattr(understanding, "confidence", 0.0) or 0.0),
                    binding_identity=StructuredDataCatalog.relative_path(self.base_dir, resolved).replace("\\", "/").lower(),
                    explicit_switch=True,
                )
            return None

        if self._looks_like_generic_followup(message):
            return None

        try:
            resolved = StructuredDataCatalog.resolve_dataset_path(self.base_dir, "", message)
        except ValueError:
            resolved = None
        if resolved is not None:
            return StructuredDatasetBinding(
                dataset_path=StructuredDataCatalog.relative_path(self.base_dir, resolved),
                target_object=StructuredDataCatalog.target_object_for_path(resolved),
                source="catalog_default",
                confidence=float(getattr(understanding, "confidence", 0.0) or 0.0),
                binding_identity=StructuredDataCatalog.relative_path(self.base_dir, resolved).replace("\\", "/").lower(),
                explicit_switch=self._looks_explicit_switch(message),
            )
        return None

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
            resolved = StructuredDataCatalog.resolve_dataset_path(self.base_dir, normalized, normalized)
        except ValueError:
            return None
        if not resolved.exists() or not resolved.is_file():
            return None
        return resolved

    def _looks_explicit_switch(self, message: str) -> bool:
        lowered = (message or "").lower()
        if any(ext in lowered for ext in (".xlsx", ".csv", ".xls", ".json", ".parquet")):
            return True
        return any(marker in message for marker in ("切到", "换成", "回到", "再切回"))

    def _looks_like_generic_followup(self, message: str) -> bool:
        normalized = (message or "").strip().lower()
        if not normalized:
            return False
        starter_markers = ("再", "继续", "然后", "接着", "那", "回到刚才", "刚才那个")
        continuation_markers = ("展开一下", "展开", "看一下", "看下", "列一下", "整理一下")
        grouping_markers = ("按仓库", "按地区", "按部门", "按品类")
        domain_markers = (
            "缺货",
            "库存",
            "商品",
            "员工",
            "薪水",
            "工资",
            "订单",
            "客户",
            "销售",
            "总数",
            "多少",
            "均值",
            "平均",
            "统计",
            "汇总",
            "筛选",
            "排序",
            "top",
            "前",
        )
        generic_reference_markers = (
            "这个表",
            "这张表",
            "那个表",
            "那张表",
            "这份表格",
            "这个数据表",
            "刚才那个表",
            "刚才的数据表",
            "刚才",
            "前面那个表",
        )
        if any(marker in message for marker in generic_reference_markers):
            return True
        if normalized.startswith(starter_markers):
            return True
        return (
            any(marker in message for marker in grouping_markers)
            and any(marker in message for marker in continuation_markers)
            and not any(marker in message for marker in domain_markers)
        )
