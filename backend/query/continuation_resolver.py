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

    def promote_pdf_query(
        self,
        message: str,
        history: list[dict[str, Any]],
        understanding: QueryUnderstanding,
    ) -> QueryUnderstanding:
        if understanding.route == "tool":
            return understanding
        if not self._looks_like_pdf_followup(message):
            return understanding
        resolved = PdfAnalysisCatalog.resolve_pdf_path_from_history(self.base_dir, history)
        if resolved is None:
            return understanding
        mode = self._select_pdf_mode(message)
        return QueryUnderstanding(
            intent="pdf_page_followup_query" if mode == "page_read" else "pdf_followup_query",
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
        if not self._looks_like_structured_followup(message):
            return understanding
        resolved = StructuredDataCatalog.resolve_dataset_path_from_history(self.base_dir, history)
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
            reasons=[*list(getattr(understanding, "reasons", []) or []), "structured_followup_context"],
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

        explicit_doc_reference = "pdf" in normalized or any(
            marker in message for marker in ("报告", "文档", "白皮书")
        )
        followup_markers = (
            "这一页",
            "那一页",
            "上一页",
            "下一页",
            "这页",
            "那页",
            "回到刚才",
            "回到之前",
            "回到上一个",
            "刚才那份",
            "这份报告",
            "这份文档",
            "这一部分",
            "那一部分",
            "这一章",
            "那一章",
            "第一部分",
            "第二部分",
            "第三部分",
            "第一章",
            "第二章",
            "第三章",
            "核心结论",
            "主要结论",
            "结论是什么",
        )
        return explicit_doc_reference and any(marker in message for marker in followup_markers)

    def _select_pdf_mode(self, message: str) -> str:
        normalized = (message or "").strip().lower()
        if re.search(r"第\s*\d+\s*页", message):
            return "page_read"
        if re.search(r"第\s*[零一二三四五六七八九十百千两\d]+\s*页", message):
            return "page_read"
        if re.search(r"page\s*\d+", normalized):
            return "page_read"
        return "browse"

    def _looks_like_structured_followup(self, message: str) -> bool:
        normalized = (message or "").strip().lower()
        if not normalized:
            return False
        explicit_dataset_reference = any(
            marker in message for marker in ("表格", "数据表", "数据集", "这个表", "那张表", "刚才那个表")
        )
        if len(normalized) > 40 and not explicit_dataset_reference:
            return False
        followup_markers = (
            "再",
            "那",
            "呢",
            "按",
            "前五",
            "前十",
            "top",
            "排名",
            "排行",
            "最高",
            "最低",
            "汇总",
            "分布",
            "按地区",
            "按部门",
            "按仓库",
            "按品类",
            "缺货",
            "补货",
        )
        if explicit_dataset_reference:
            return True
        if any(marker in message for marker in followup_markers):
            return True
        return bool(re.search(r"(top\s*\d+|第?\d+名)", normalized))

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
