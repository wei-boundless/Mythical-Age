from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pdf_analysis import PdfAnalysisCatalog
from structured_data import StructuredDataCatalog
from understanding.query_understanding import QueryUnderstanding


class QueryContinuationResolver:
    def __init__(self, *, base_dir: Path) -> None:
        self.base_dir = base_dir

    def resolve(
        self,
        *,
        message: str,
        history: list[dict[str, Any]],
        understanding: QueryUnderstanding,
    ) -> QueryUnderstanding:
        promoted = self.promote_pdf_query(message, history, understanding)
        promoted = self.promote_structured_query(message, history, promoted)
        return self.promote_session_summary_query(message, history, promoted)

    def apply_authoritative_context(
        self,
        *,
        message: str,
        understanding: QueryUnderstanding,
        authority_context: dict[str, Any] | None,
    ) -> QueryUnderstanding:
        if not authority_context:
            return understanding
        promoted = self._apply_pdf_authority(message, understanding, authority_context)
        return self._apply_structured_authority(message, promoted, authority_context)

    def promote_pdf_query(
        self,
        message: str,
        history: list[dict[str, Any]],
        understanding: QueryUnderstanding,
    ) -> QueryUnderstanding:
        existing_tool_name = str(getattr(understanding, "tool_name", "") or "").strip()
        existing_tool_input = dict(getattr(understanding, "tool_input", {}) or {})
        existing_path = str(existing_tool_input.get("path", "") or "").strip()
        if understanding.route == "tool" and (existing_tool_name != "pdf_analysis" or existing_path):
            return understanding
        explicit_reference = self._extract_explicit_pdf_reference(message)
        if not explicit_reference:
            return understanding
        try:
            resolved = PdfAnalysisCatalog.resolve_pdf_path(self.base_dir, explicit_reference, message)
        except ValueError:
            resolved = None
        if resolved is None:
            return understanding
        mode = self._select_pdf_mode(message)
        task_kind = (
            "document_page"
            if mode == "page"
            else "document_section"
            if mode == "section"
            else "document_read"
        )
        return QueryUnderstanding(
            intent=(
                "pdf_page_followup_query"
                if mode == "page"
                else "pdf_section_followup_query"
                if mode == "section"
                else "pdf_followup_query"
            ),
            source_kind="document",
            task_kind=task_kind,
            modality="pdf",
            route="tool",
            tool_name="pdf_analysis",
            tool_input={
                "query": message,
                "mode": mode,
                "path": PdfAnalysisCatalog.relative_path(self.base_dir, resolved),
            },
            should_skip_rag=True,
            confidence=max(float(getattr(understanding, "confidence", 0.0) or 0.0), 0.9),
            reasons=[*list(getattr(understanding, "reasons", []) or []), "pdf_followup_context"],
        )

    def promote_structured_query(
        self,
        message: str,
        history: list[dict[str, Any]],
        understanding: QueryUnderstanding,
    ) -> QueryUnderstanding:
        if understanding.route == "tool":
            return understanding
        explicit_path = self._extract_explicit_dataset_reference(message)
        if not explicit_path:
            return understanding
        if not self._has_strong_structured_operation(message):
            return understanding
        try:
            resolved = StructuredDataCatalog.resolve_dataset_path(self.base_dir, explicit_path, message)
        except ValueError:
            resolved = None
        if resolved is None:
            return understanding
        return QueryUnderstanding(
            intent="structured_followup_query",
            modality="table",
            route="tool",
            tool_name="structured_data_analysis",
            tool_input={
                "query": message,
                "analysis_type": "auto",
                "path": StructuredDataCatalog.relative_path(self.base_dir, resolved),
            },
            should_skip_rag=True,
            confidence=max(float(getattr(understanding, "confidence", 0.0) or 0.0), 0.88),
            reasons=[*list(getattr(understanding, "reasons", []) or []), "structured_explicit_context"],
        )

    def promote_session_summary_query(
        self,
        message: str,
        history: list[dict[str, Any]],
        understanding: QueryUnderstanding,
    ) -> QueryUnderstanding:
        if not history:
            return understanding
        if not self._looks_like_session_summary(message):
            return understanding
        return QueryUnderstanding(
            intent="session_summary_query",
            source_kind="memory",
            task_kind="session_summary",
            modality="memory",
            route="memory",
            should_skip_rag=True,
            confidence=max(float(getattr(understanding, "confidence", 0.0) or 0.0), 0.9),
            reasons=[*list(getattr(understanding, "reasons", []) or []), "session_summary_context"],
        )

    def _extract_explicit_pdf_reference(self, message: str) -> str:
        normalized = (message or "").strip()
        if not normalized:
            return ""
        matches = PdfAnalysisCatalog.extract_explicit_pdf_references(normalized)
        return matches[0] if matches else ""

    def _looks_like_pdf_followup(self, message: str) -> bool:
        normalized = (message or "").strip().lower()
        if not normalized:
            return False
        if re.search(r"第\s*\d+\s*页", message):
            return True
        if re.search(r"第\s*[零一二三四五六七八九十百千两\d]+\s*页", message):
            return True
        if re.search(r"page\s*\d+", normalized):
            return True
        if re.search(r"第\s*[零一二三四五六七八九十百千两\d]+\s*(?:部分|章|节)", message):
            return True

        explicit_doc_reference = ".pdf" in normalized or "pdf" in normalized
        followup_markers = (
            "这一页",
            "那一页",
            "上一页",
            "下一页",
            "这页",
            "那页",
            "回到刚才",
            "刚才那份",
            "这一部分",
            "那一部分",
            "这一章",
            "那一章",
            "核心结论",
            "主要结论",
            "结论是什么",
        )
        return explicit_doc_reference and any(marker in message for marker in followup_markers)

    def _select_pdf_mode(self, message: str) -> str:
        normalized = (message or "").strip().lower()
        if re.search(r"第\s*\d+\s*页", message):
            return "page"
        if re.search(r"第\s*[零一二三四五六七八九十百千两\d]+\s*页", message):
            return "page"
        if re.search(r"page\s*\d+", normalized):
            return "page"
        if re.search(r"第\s*[零一二三四五六七八九十百千两\d]+\s*(?:部分|章|节)", message):
            return "section"
        if any(marker in message for marker in ("这一部分", "那一部分", "这一章", "那一章", "这一节", "那一节")):
            return "section"
        return "document"

    def _looks_like_structured_followup(self, message: str) -> bool:
        normalized = (message or "").strip().lower()
        if not normalized:
            return False
        if self._looks_like_summary_or_rewrite_request(message):
            return False
        if not self._has_explicit_dataset_reference(message):
            return False
        return self._has_strong_structured_operation(message)

    def _has_explicit_dataset_reference(self, message: str) -> bool:
        return bool(self._extract_explicit_dataset_reference(message))

    def _extract_explicit_dataset_reference(self, message: str) -> str:
        normalized = (message or "").strip()
        if not normalized:
            return ""
        match = re.search(
            r"([^\s,，;；:：\"'“”‘’]+?\.(?:xlsx|csv|xls|json|parquet))",
            normalized,
            flags=re.IGNORECASE,
        )
        return match.group(1).strip() if match is not None else ""

    def _has_strong_structured_operation(self, message: str) -> bool:
        normalized = (message or "").strip().lower()
        if not normalized:
            return False
        operation_markers = (
            "汇总",
            "统计",
            "分组",
            "分布",
            "筛选",
            "过滤",
            "排序",
            "均值",
            "平均",
            "总和",
            "总计",
            "占比",
            "缺货",
            "补货",
            "展开",
        )
        if any(marker in message for marker in operation_markers):
            return True
        return bool(re.search(r"按[^\s,，。；;]{1,12}(?:汇总|统计|分组|展开|分析|排序|筛选|查看|列出|看)?", message))

    def _looks_like_summary_or_rewrite_request(self, message: str) -> bool:
        return any(
            marker in message
            for marker in (
                "总结",
                "概括",
                "归纳",
                "梳理",
                "整理成",
                "压成",
                "改写",
                "改成",
                "润色",
                "适合管理层",
                "汇报版本",
            )
        )

    def _looks_like_session_summary(self, message: str) -> bool:
        normalized = (message or "").strip().lower()
        if not normalized:
            return False
        summary_markers = (
            "总结",
            "回顾",
            "归纳",
            "梳理",
            "整理",
            "概括",
            "分成",
            "拆成",
        )
        scope_markers = (
            "这几个任务",
            "这些任务",
            "这几个问题",
            "这些问题",
            "刚才",
            "前面",
            "刚刚",
            "本轮",
            "这轮",
            "今天这几个",
            "今天做的",
            "刚做的",
            "刚问的",
        )
        return any(marker in message for marker in summary_markers) and any(
            marker in message for marker in scope_markers
        )

    def _apply_pdf_authority(
        self,
        message: str,
        understanding: QueryUnderstanding,
        authority_context: dict[str, Any],
    ) -> QueryUnderstanding:
        authority_pdf = str(authority_context.get("active_pdf", "") or "").strip()
        if not authority_pdf:
            return understanding
        if understanding.route in {"memory", "compound"}:
            return understanding
        existing_tool_name = str(getattr(understanding, "tool_name", "") or "").strip()
        existing_tool_input = dict(getattr(understanding, "tool_input", {}) or {})
        existing_path = str(existing_tool_input.get("path", "") or "").strip()
        if existing_path:
            return understanding
        if existing_tool_name and existing_tool_name != "pdf_analysis":
            return understanding
        if not self._can_apply_pdf_authority(message, understanding):
            return understanding
        mode = self._select_pdf_mode(message)
        return QueryUnderstanding(
            intent=(
                "pdf_page_followup_query"
                if mode == "page"
                else "pdf_section_followup_query"
                if mode == "section"
                else "pdf_followup_query"
            ),
            source_kind="document",
            task_kind=(
                "document_page"
                if mode == "page"
                else "document_section"
                if mode == "section"
                else "document_read"
            ),
            modality="pdf",
            route="tool",
            tool_name="pdf_analysis",
            tool_input={
                **existing_tool_input,
                "query": message,
                "mode": mode,
                "path": authority_pdf,
            },
            should_skip_rag=True,
            confidence=max(float(getattr(understanding, "confidence", 0.0) or 0.0), 0.82),
            reasons=[*list(getattr(understanding, "reasons", []) or []), "compound_authoritative_pdf_context"],
        )

    def _apply_structured_authority(
        self,
        message: str,
        understanding: QueryUnderstanding,
        authority_context: dict[str, Any],
    ) -> QueryUnderstanding:
        authority_dataset = str(authority_context.get("active_dataset", "") or "").strip()
        if not authority_dataset:
            return understanding
        if understanding.route in {"memory", "compound"}:
            return understanding
        existing_tool_name = str(getattr(understanding, "tool_name", "") or "").strip()
        existing_tool_input = dict(getattr(understanding, "tool_input", {}) or {})
        existing_path = str(existing_tool_input.get("path", "") or "").strip()
        if existing_path:
            return understanding
        if existing_tool_name and existing_tool_name != "structured_data_analysis":
            return understanding
        if not self._can_apply_structured_authority(message, understanding):
            return understanding
        return QueryUnderstanding(
            intent="structured_followup_query",
            source_kind="dataset",
            task_kind="structured_data",
            modality="table",
            route="tool",
            tool_name="structured_data_analysis",
            tool_input={
                **existing_tool_input,
                "query": message,
                "analysis_type": "auto",
                "path": authority_dataset,
            },
            should_skip_rag=True,
            confidence=max(float(getattr(understanding, "confidence", 0.0) or 0.0), 0.8),
            reasons=[*list(getattr(understanding, "reasons", []) or []), "compound_authoritative_dataset_context"],
        )

    def _can_apply_pdf_authority(
        self,
        message: str,
        understanding: QueryUnderstanding,
    ) -> bool:
        tool_name = str(getattr(understanding, "tool_name", "") or "").strip()
        if tool_name == "pdf_analysis":
            return True
        if self._looks_like_pdf_followup(message):
            return True
        return any(
            marker in message
            for marker in (
                "全文",
                "总览",
                "结论",
                "行动建议",
                "约束",
                "重点",
                "解读",
                "分析",
                "说明",
                "提炼",
            )
        )

    def _can_apply_structured_authority(
        self,
        message: str,
        understanding: QueryUnderstanding,
    ) -> bool:
        tool_name = str(getattr(understanding, "tool_name", "") or "").strip()
        if tool_name == "structured_data_analysis":
            return True
        return self._has_strong_structured_operation(message)
