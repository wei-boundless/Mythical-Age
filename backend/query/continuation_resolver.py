from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pdf_analysis import PdfAnalysisCatalog
from structured_data import StructuredDataCatalog
from understanding.query_understanding import QueryUnderstanding

_PAGE_RE = re.compile(r"(?:第\s*\d+\s*页|第\s*[零一二三四五六七八九十百千两\d]+\s*页|page\s*\d+)", flags=re.IGNORECASE)
_SECTION_RE = re.compile(
    r"(?:第\s*[零一二三四五六七八九十百千两\d]+\s*(?:部分|章|节)|这一部分|那一部分|这一章|那一章|这一节|那一节)",
    flags=re.IGNORECASE,
)
_DATASET_SOURCE_RE = re.compile(
    r"数据源[:：]\s*([^\s,，;；|]+?\.(?:xlsx|csv|xls|json|parquet))",
    flags=re.IGNORECASE,
)


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
        promoted = self.promote_knowledge_followup_query(message, history, promoted)
        return self.promote_session_summary_query(message, history, promoted)

    def apply_authoritative_context(
        self,
        *,
        message: str,
        understanding: QueryUnderstanding,
        authority_context: dict[str, Any] | None,
    ) -> QueryUnderstanding:
        # Restored authority may help later handle/bundle arbitration, but it must
        # not rewrite the current-turn route. Follow-up execution should be
        # recovered through explicit handle resolution, not by injecting
        # active_pdf/active_dataset back into understanding.
        return understanding

    def promote_pdf_query(
        self,
        message: str,
        history: list[dict[str, Any]],
        understanding: QueryUnderstanding,
    ) -> QueryUnderstanding:
        if self._has_mixed_capability_reason(understanding):
            return understanding
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
            execution_posture="direct_tool",
            direct_route_reason="pdf_followup_context",
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
        if self._has_mixed_capability_reason(understanding):
            return understanding
        if understanding.route == "tool":
            return understanding
        explicit_path = self._extract_explicit_dataset_reference(message)
        if not self._has_strong_structured_operation(message):
            return understanding
        path_reference = explicit_path or self._extract_recent_dataset_reference(history)
        if not path_reference:
            return understanding
        if explicit_path:
            try:
                resolved = StructuredDataCatalog.resolve_dataset_path(self.base_dir, explicit_path, message)
            except ValueError:
                resolved = None
            if resolved is None:
                return understanding
            path_reference = StructuredDataCatalog.relative_path(self.base_dir, resolved)
        return QueryUnderstanding(
            intent="structured_followup_query",
            source_kind="dataset",
            task_kind="structured_data",
            modality="table",
            route="tool",
            execution_posture="direct_tool",
            direct_route_reason=(
                "structured_explicit_context"
                if explicit_path
                else "structured_recent_history_context"
            ),
            tool_name="structured_data_analysis",
            tool_input={
                "query": message,
                "analysis_type": "auto",
                "path": path_reference,
            },
            should_skip_rag=True,
            confidence=max(float(getattr(understanding, "confidence", 0.0) or 0.0), 0.88),
            reasons=[
                *list(getattr(understanding, "reasons", []) or []),
                "structured_explicit_context" if explicit_path else "structured_recent_history_context",
            ],
        )

    def promote_knowledge_followup_query(
        self,
        message: str,
        history: list[dict[str, Any]],
        understanding: QueryUnderstanding,
    ) -> QueryUnderstanding:
        if not history:
            return understanding
        if not self._looks_like_knowledge_followup(message):
            return understanding
        if self._has_mixed_capability_reason(understanding):
            return understanding
        if understanding.route in {"tool", "memory"}:
            return understanding
        if str(getattr(understanding, "direct_route_reason", "") or "") not in {"", "unresolved_lookup"}:
            return understanding
        prior = self._recent_rag_exchange(history)
        if prior is None:
            return understanding
        prior_user, prior_assistant = prior
        expanded_query = self._build_knowledge_followup_query(
            message=message,
            prior_user=prior_user,
            prior_assistant=prior_assistant,
        )
        return QueryUnderstanding(
            intent="knowledge_followup_query",
            source_kind="knowledge_base",
            task_kind="knowledge_lookup",
            modality="general",
            route="rag",
            execution_posture="direct_rag",
            direct_route_reason="knowledge_followup_context",
            capability_requests=["knowledge_lookup"],
            tool_input={"query": expanded_query},
            should_skip_rag=False,
            confidence=max(float(getattr(understanding, "confidence", 0.0) or 0.0), 0.84),
            reasons=[*list(getattr(understanding, "reasons", []) or []), "knowledge_followup_context"],
            structural_signals=dict(getattr(understanding, "structural_signals", {}) or {}),
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
            if self._should_preserve_orchestration_understanding(understanding):
                return understanding
            return understanding
        return QueryUnderstanding(
            intent="session_summary_query",
            source_kind="memory",
            task_kind="session_summary",
            modality="memory",
            route="memory",
            execution_posture="direct_memory",
            direct_route_reason="session_summary_context",
            should_skip_rag=True,
            confidence=max(float(getattr(understanding, "confidence", 0.0) or 0.0), 0.9),
            reasons=[*list(getattr(understanding, "reasons", []) or []), "session_summary_context"],
        )

    def _should_preserve_orchestration_understanding(
        self,
        understanding: QueryUnderstanding,
    ) -> bool:
        task_kind = str(getattr(understanding, "task_kind", "") or "").strip()
        if task_kind == "multi_capability_request":
            return True
        reasons = set(str(reason or "").strip() for reason in list(getattr(understanding, "reasons", []) or []))
        return bool(reasons & {"mixed_capability_signals", "mixed_direct_capabilities"})

    def _extract_explicit_pdf_reference(self, message: str) -> str:
        normalized = (message or "").strip()
        if not normalized:
            return ""
        matches = PdfAnalysisCatalog.extract_explicit_pdf_references(normalized)
        return matches[0] if matches else ""

    def _has_mixed_capability_reason(self, understanding: QueryUnderstanding) -> bool:
        reasons = {
            str(reason or "").strip()
            for reason in list(getattr(understanding, "reasons", []) or [])
            if str(reason or "").strip()
        }
        return bool(reasons & {"mixed_capability_signals", "mixed_direct_capabilities"})

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

    def _looks_like_knowledge_followup(self, message: str) -> bool:
        normalized = (message or "").strip()
        if not normalized:
            return False
        lowered = normalized.lower()
        if self._extract_explicit_pdf_reference(normalized) or self._extract_explicit_dataset_reference(normalized):
            return False
        if any(marker in lowered for marker in ("http://", "https://", "天气", "金价", "黄金", "股票")):
            return False
        return any(
            marker in normalized
            for marker in (
                "具体",
                "一篇",
                "哪篇",
                "这篇",
                "那篇",
                "展开",
                "说说",
                "讲讲",
                "详细",
                "继续",
                "刚才",
                "刚刚",
            )
        )

    def _recent_rag_exchange(self, history: list[dict[str, Any]]) -> tuple[str, str] | None:
        last_assistant_index = -1
        last_assistant: dict[str, Any] | None = None
        for index in range(len(history) - 1, -1, -1):
            message = history[index]
            if str(message.get("role") or "") != "assistant":
                continue
            if self._is_rag_assistant_message(message):
                last_assistant_index = index
                last_assistant = message
                break
        if last_assistant is None:
            return None
        prior_user = ""
        for index in range(last_assistant_index - 1, -1, -1):
            message = history[index]
            if str(message.get("role") or "") == "user":
                prior_user = str(message.get("content") or "").strip()
                break
        assistant_content = str(last_assistant.get("content") or "").strip()
        if not prior_user or not assistant_content:
            return None
        return prior_user, assistant_content

    def _is_rag_assistant_message(self, message: dict[str, Any]) -> bool:
        source = str(message.get("answer_source") or "").strip()
        route = str(message.get("route") or message.get("app.route") or "").strip()
        content = str(message.get("content") or "")
        if source in {"rag_answer_finalization", "retrieval_worker", "rag"} or route == "rag":
            return True
        return "本地" in content and any(marker in content for marker in ("报告", "资料", "知识库", "数据库"))

    def _build_knowledge_followup_query(self, *, message: str, prior_user: str, prior_assistant: str) -> str:
        compact_prior = " ".join(prior_assistant.split())[:900]
        compact_user = " ".join(prior_user.split())[:260]
        return f"{compact_user}\n上一轮检索结果：{compact_prior}\n追问：{message.strip()}"

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

    def _extract_recent_dataset_reference(self, history: list[dict[str, Any]]) -> str:
        if not history:
            return ""
        recent_messages = list(history[-8:])
        for item in reversed(recent_messages):
            content = str(item.get("content", "") or "").strip()
            if not content:
                continue
            explicit_reference = self._extract_explicit_dataset_reference(content)
            if explicit_reference:
                return explicit_reference
            source_match = _DATASET_SOURCE_RE.search(content)
            if source_match is not None:
                return str(source_match.group(1) or "").strip()
        return ""

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
                "摘要",
                "运营摘要",
                "简报",
                "概括",
                "归纳",
                "梳理",
                "汇总摘要",
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
        has_explicit_execution_anchor = bool(
            PdfAnalysisCatalog.extract_explicit_pdf_references(message)
            or _PAGE_RE.search(message)
            or _SECTION_RE.search(message)
            or self._extract_explicit_dataset_reference(message)
        )
        if has_explicit_execution_anchor:
            return False
        summary_markers = (
            "总结",
            "摘要",
            "运营摘要",
            "回顾",
            "归纳",
            "梳理",
            "整理",
            "概括",
            "简报",
            "汇总摘要",
        )
        organization_markers = (
            "分成",
            "拆成",
            "分开",
            "分段",
            "按",
            "组织",
            "三段",
            "四段",
            "四块",
            "几块",
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
        source_markers = (
            "pdf",
            "报告",
            "数据",
            "数据表",
            "表格",
            "库存",
            "员工",
            "黄金",
            "天气",
            "实时",
            "知识库",
            "记忆",
        )
        has_summary_intent = any(marker in message for marker in summary_markers)
        has_organization_intent = any(marker in message for marker in organization_markers) and (
            has_summary_intent or any(marker in message for marker in ("汇报", "简报", "结论"))
        )
        multi_source_hits = sum(1 for marker in source_markers if marker in normalized or marker in message)
        has_session_scope = any(marker in message for marker in scope_markers)
        return (has_summary_intent or has_organization_intent) and (has_session_scope or multi_source_hits >= 2)
