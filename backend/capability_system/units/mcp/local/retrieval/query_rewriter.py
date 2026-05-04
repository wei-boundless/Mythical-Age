from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(slots=True)
class QueryRewriteResult:
    original_query: str
    rewritten_query: str
    query_type: str = "general"
    keywords: list[str] = field(default_factory=list)
    applied_rules: list[str] = field(default_factory=list)


class QueryRewriter:
    """Lightweight retrieval-oriented query rewriter."""

    _RULES: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
        (
            "table_terms",
            (
                "\u8868\u683c",
                "excel",
                "xlsx",
                "csv",
                "\u5de5\u4f5c\u8868",
                "\u8868\u5355",
                "sheet",
                "inventory",
                "stock",
                "\u5e93\u5b58",
            ),
            (
                "table",
                "excel",
                "xlsx",
                "csv",
                "sheet",
                "inventory",
                "stock",
                "\u8868\u683c",
                "\u5e93\u5b58",
            ),
        ),
        (
            "image_terms",
            (
                "\u56fe\u7247",
                "\u56fe\u50cf",
                "\u622a\u56fe",
                "\u7167\u7247",
                "photo",
                "image",
                "picture",
                "screenshot",
                "ocr",
            ),
            (
                "image",
                "picture",
                "screenshot",
                "ocr",
                "\u56fe\u7247",
                "\u622a\u56fe",
            ),
        ),
        (
            "document_terms",
            (
                "pdf",
                "\u6587\u6863",
                "\u62a5\u544a",
                "report",
                "document",
                "page",
                "\u9875",
                "ppt",
                "docx",
                "slide",
                "\u5b63\u62a5",
                "\u5e74\u62a5",
            ),
            (
                "pdf",
                "document",
                "report",
                "page",
                "docx",
                "pptx",
                "slide",
                "\u6587\u6863",
                "\u62a5\u544a",
            ),
        ),
        (
            "shareholder_terms",
            (
                "\u80a1\u4e1c",
                "\u6301\u80a1",
                "\u5341\u5927\u80a1\u4e1c",
                "\u524d\u4e09\u5927\u80a1\u4e1c",
                "shareholder",
                "holder",
            ),
            (
                "shareholder",
                "top shareholders",
                "equity holder",
                "\u80a1\u4e1c",
                "\u6301\u80a1",
            ),
        ),
        (
            "order_terms",
            (
                "\u8ba2\u5355",
                "\u9500\u552e\u8ba2\u5355",
                "order",
                "orders",
                "purchase",
                "\u8d2d\u4e70\u8bb0\u5f55",
            ),
            (
                "order",
                "orders",
                "sales order",
                "purchase record",
                "\u8ba2\u5355",
            ),
        ),
        (
            "memory_terms",
            (
                "\u8bb0\u4f4f",
                "\u504f\u597d",
                "\u5de5\u4f5c\u6d41",
                "session",
                "memory",
                "preference",
                "workflow",
                "project",
            ),
            (
                "memory",
                "session",
                "preference",
                "workflow",
                "project",
                "\u8bb0\u5fc6",
                "\u504f\u597d",
            ),
        ),
        (
            "security_terms",
            (
                "xss",
                "csrf",
                "cors",
                "\u5b89\u5168",
                "\u6f0f\u6d1e",
                "security",
            ),
            (
                "security",
                "xss",
                "csrf",
                "cors",
                "\u6f0f\u6d1e",
                "\u5b89\u5168",
            ),
        ),
    )

    _QUERY_TYPE_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
        (
            "memory",
            (
                "记得",
                "记住",
                "偏好",
                "习惯",
                "workflow",
                "memory",
                "session",
                "project",
                "preference",
            ),
        ),
        (
            "table",
            (
                "表格",
                "excel",
                "xlsx",
                "csv",
                "sheet",
                "库存",
                "订单",
                "销售额",
                "销量",
                "top",
                "前五",
                "前十",
                "排名",
                "排行",
                "group by",
                "汇总",
            ),
        ),
        (
            "pdf_page",
            (
                "第",
                "页",
                "page",
                "pdf",
                "白皮书",
                "报告",
                "文档",
            ),
        ),
        (
            "document",
            (
                "pdf",
                "白皮书",
                "报告",
                "文档",
                "report",
                "document",
                "slide",
                "ppt",
                "docx",
            ),
        ),
    )

    def rewrite(self, query: str) -> QueryRewriteResult:
        normalized = self._normalize(query)
        lowered = normalized.lower()
        query_type = self._detect_query_type(normalized)
        keywords: list[str] = []
        applied_rules: list[str] = []

        for rule_name, triggers, expansions in self._RULES:
            if any(trigger.lower() in lowered for trigger in triggers):
                applied_rules.append(rule_name)
                for token in expansions:
                    if token not in keywords:
                        keywords.append(token)

        if self._looks_short_or_underspecified(normalized) and self._should_apply_generic_expansion(query_type, normalized):
            applied_rules.append("underspecified_query")
            for token in (
                "definition",
                "summary",
                "key points",
                "\u76f8\u5173\u8d44\u6599",
                "\u5173\u952e\u4fe1\u606f",
            ):
                if token not in keywords:
                    keywords.append(token)

        rewritten = self._compose_rewritten_query(normalized, keywords, query_type)

        return QueryRewriteResult(
            original_query=query,
            rewritten_query=rewritten,
            query_type=query_type,
            keywords=keywords,
            applied_rules=applied_rules,
        )

    def _normalize(self, query: str) -> str:
        query = query.replace("\r\n", "\n").replace("\r", "\n").strip()
        query = re.sub(r"\s+", " ", query)
        return query

    def _looks_short_or_underspecified(self, query: str) -> bool:
        if len(query) <= 8:
            return True
        tokens = [token for token in re.split(r"\s+", query) if token]
        return len(tokens) <= 2 and len(query) <= 20

    def _detect_query_type(self, query: str) -> str:
        lowered = query.lower()
        if self._looks_like_pdf_page_query(query):
            return "pdf_page"
        for query_type, markers in self._QUERY_TYPE_MARKERS:
            if any(marker.lower() in lowered for marker in markers):
                return query_type
        return "general"

    def _looks_like_pdf_page_query(self, query: str) -> bool:
        lowered = query.lower()
        if re.search(r"第\s*\d+\s*页", query):
            return True
        if re.search(r"第\s*[零一二三四五六七八九十百两]+\s*页", query):
            return True
        if re.search(r"page\s*\d+", lowered):
            return True
        return False

    def _should_apply_generic_expansion(self, query_type: str, query: str) -> bool:
        if query_type in {"memory", "table", "pdf_page"}:
            return False
        if re.search(r"[\u4e00-\u9fff]{4,}", query):
            return False
        return True

    def _compose_rewritten_query(self, normalized: str, keywords: list[str], query_type: str) -> str:
        if not keywords:
            return normalized
        if query_type in {"memory", "table", "pdf_page"}:
            return normalized
        return f"{normalized}\nRetrieval hints: {' | '.join(keywords)}"
