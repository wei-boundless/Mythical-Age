from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from pdf_analysis.catalog import PdfAnalysisCatalog
from understanding.memory_intent import MemoryIntent


@dataclass(slots=True)
class TaskUnderstanding:
    intent: str = "general_query"
    source_kind: str = "knowledge_base"
    task_kind: str = "knowledge_lookup"
    target_object: str | None = None
    modality: str = "general"
    route_hint: str = "rag"
    preferred_skill: str | None = None
    candidate_tools: list[str] = field(default_factory=list)
    parameters: dict[str, Any] = field(default_factory=dict)
    execution_posture: str = "direct_rag"
    direct_route_reason: str = ""
    should_skip_rag: bool = False
    confidence: float = 0.0
    reasons: list[str] = field(default_factory=list)


def analyze_task_understanding(
    message: str,
    memory_intent: MemoryIntent | None = None,
) -> TaskUnderstanding:
    normalized = (message or "").strip()
    lowered = normalized.lower()

    if memory_intent is not None and memory_intent.should_skip_rag:
        return TaskUnderstanding(
            intent=memory_intent.intent,
            source_kind="memory",
            task_kind="memory_lookup",
            modality="memory",
            route_hint="memory",
            execution_posture="direct_memory",
            direct_route_reason="memory_intent",
            should_skip_rag=True,
            confidence=1.0,
            reasons=["memory_intent"],
        )

    return (
        _detect_mixed_capability_task(normalized, lowered)
        or _detect_realtime_task(normalized, lowered)
        or _detect_web_task(normalized, lowered)
        or _detect_pdf_task(normalized, lowered)
        or _detect_faq_task(normalized, lowered)
        or _detect_structured_data_task(normalized, lowered)
        or _detect_knowledge_task(normalized, lowered)
        or _build_bounded_lookup_task(
            message=normalized,
            lowered=lowered,
            source_kind="knowledge_base",
            task_kind="knowledge_lookup",
            modality="general",
            confidence=0.35,
            reasons=["fallback_bounded_lookup"],
        )
    )


def _detect_mixed_capability_task(message: str, lowered: str) -> TaskUnderstanding | None:
    explicit_pdf_references = PdfAnalysisCatalog.extract_explicit_pdf_references(message)
    explicit_dataset_reference = _extract_explicit_dataset_reference(message)
    has_document_signal = bool(explicit_pdf_references) or (
        ("pdf" in lowered or "报告" in lowered or "文档" in lowered)
        and bool(re.search(r"第\s*[零一二三四五六七八九十百千两\d]+\s*页", message))
    )
    has_dataset_signal = bool(explicit_dataset_reference)
    has_realtime_signal = _contains_any(
        lowered,
        (
            "weather",
            "forecast",
            "天气",
            "气温",
            "黄金",
            "金价",
            "现货黄金",
        ),
    )
    signal_count = sum(1 for signal in (has_document_signal, has_dataset_signal, has_realtime_signal) if signal)
    if signal_count < 2:
        return None
    return _build_bounded_lookup_task(
        message=message,
        lowered=lowered,
        source_kind="mixed_sources",
        task_kind="multi_capability_request",
        modality="multi",
        confidence=0.72,
        reasons=["mixed_capability_signals"],
    )


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def _detect_realtime_task(message: str, lowered: str) -> TaskUnderstanding | None:
    weather_markers = (
        "weather",
        "forecast",
        "temperature",
        "rain",
        "wind",
        "天气",
        "气温",
        "温度",
        "降雨",
        "下雨",
        "风速",
        "风向",
        "预报",
    )
    if _contains_any(lowered, weather_markers):
        return TaskUnderstanding(
            intent="weather_query",
            source_kind="external_web",
            task_kind="realtime_lookup",
            modality="realtime",
            route_hint="tool",
            preferred_skill="get-weather",
            candidate_tools=["get_weather"],
            parameters={"query": message},
            execution_posture="direct_tool",
            direct_route_reason="weather_markers",
            should_skip_rag=True,
            confidence=0.98,
            reasons=["weather_markers"],
        )

    gold_markers = (
        "gold price",
        "spot gold",
        "xau",
        "xauusd",
        "黄金",
        "金价",
        "现货黄金",
        "黄金价格",
    )
    if _contains_any(lowered, gold_markers):
        return TaskUnderstanding(
            intent="gold_price_query",
            source_kind="external_web",
            task_kind="realtime_lookup",
            modality="realtime",
            route_hint="tool",
            preferred_skill="gold-price",
            candidate_tools=["get_gold_price"],
            parameters={"query": message},
            execution_posture="direct_tool",
            direct_route_reason="gold_markers",
            should_skip_rag=True,
            confidence=0.97,
            reasons=["gold_markers"],
        )
    return None


def _detect_web_task(message: str, lowered: str) -> TaskUnderstanding | None:
    explicit_web_markers = (
        "联网",
        "查官网",
        "官网",
        "look it up",
        "official docs",
        "news",
        "web search",
        "上网",
        "网上查",
    )
    has_explicit_web_marker = _contains_any(lowered, explicit_web_markers)
    if not has_explicit_web_marker:
        return None
    return TaskUnderstanding(
        intent="web_search_query",
        source_kind="external_web",
        task_kind="web_lookup",
        modality="web",
        route_hint="tool",
        preferred_skill="web-search",
        candidate_tools=["web_search"],
        parameters={"query": message},
        execution_posture="direct_tool",
        direct_route_reason="explicit_web_request",
        should_skip_rag=True,
        confidence=0.92,
        reasons=["explicit_web_markers"],
    )


def _detect_pdf_task(message: str, lowered: str) -> TaskUnderstanding | None:
    explicit_pdf_markers = ("pdf", "白皮书")
    contextual_doc_markers = ("报告", "文档")
    page_markers = (
        bool(re.search(r"第\s*\d+\s*页", message)),
        bool(re.search(r"第\s*[零一二三四五六七八九十百千两\d]+\s*页", message)),
        bool(re.search(r"page\s*\d+", lowered)),
    )
    section_markers = (
        bool(re.search(r"第\s*[零一二三四五六七八九十百千两\d]+\s*(?:部分|章|节)", message)),
        any(marker in message for marker in ("这一部分", "那一部分", "这一章", "那一章", "这一节", "那一节")),
    )
    document_action_markers = (
        "分析",
        "解读",
        "总结",
        "详细解读",
        "通读",
        "逐页",
        "完整总结",
        "总览",
        "看一下",
        "看看",
        "讲得什么",
        "讲什么",
    )
    explicit_references = PdfAnalysisCatalog.extract_explicit_pdf_references(message)
    has_explicit_pdf_marker = _contains_any(lowered, explicit_pdf_markers) or bool(explicit_references)
    has_contextual_document_signal = _contains_any(lowered, contextual_doc_markers) and (
        any(page_markers) or _contains_any(lowered, document_action_markers)
    )

    if not has_explicit_pdf_marker and not any(page_markers) and not has_contextual_document_signal:
        return None

    if any(page_markers):
        task_kind = "document_page"
        mode = "page"
    elif any(section_markers):
        task_kind = "document_section"
        mode = "section"
    else:
        task_kind = "document_read"
        mode = "document"

    reasons = ["pdf_markers"] if has_explicit_pdf_marker or has_contextual_document_signal else []
    if any(page_markers):
        reasons.append("page_markers")
    if any(section_markers):
        reasons.append("section_markers")
    if mode == "document" and _contains_any(lowered, ("详细解读", "通读", "逐页", "完整总结")):
        reasons.append("document_read_markers")
    parameters = {"query": message, "mode": mode}
    if explicit_references:
        parameters["path"] = explicit_references[0]
        reasons.append("explicit_pdf_reference")

    return TaskUnderstanding(
        intent=f"pdf_{task_kind}",
        source_kind="document",
        task_kind=task_kind,
        modality="pdf",
        route_hint="tool",
        preferred_skill="pdf-analysis",
        candidate_tools=["pdf_analysis"],
        parameters=parameters,
        execution_posture="direct_tool",
        direct_route_reason="explicit_pdf_reference" if explicit_references else "pdf_markers",
        should_skip_rag=True,
        confidence=0.93 if mode in {"page", "section"} else 0.88,
        reasons=reasons,
    )


def _detect_faq_task(message: str, lowered: str) -> TaskUnderstanding | None:
    explanation_markers = (
        "为什么",
        "为啥",
        "怎么会",
        "怎么回事",
        "为什么会",
        "找不到",
        "看不到",
        "无法",
        "不能",
        "失败",
        "收不到",
        "没收到",
        "没有显示",
        "why",
        "can't",
        "cannot",
        "failed",
    )
    faq_domain_markers = (
        "订单",
        "帐户",
        "账户",
        "登录",
        "付款",
        "支付",
        "退款",
        "验证码",
        "发票",
        "配送",
        "order",
        "account",
        "login",
        "payment",
        "refund",
    )
    if not (_contains_any(lowered, explanation_markers) and _contains_any(lowered, faq_domain_markers)):
        return None
    return TaskUnderstanding(
        intent="faq_explanation_query",
        source_kind="knowledge_base",
        task_kind="faq_explanation",
        modality="general",
        route_hint="rag",
        preferred_skill="rag-skill",
        candidate_tools=["search_knowledge"],
        parameters={"query": message},
        execution_posture="direct_rag",
        direct_route_reason="faq_explanation_markers",
        should_skip_rag=False,
        confidence=0.9,
        reasons=["faq_explanation_markers"],
    )


def _detect_structured_data_task(message: str, lowered: str) -> TaskUnderstanding | None:
    explicit_dataset_path = _extract_explicit_dataset_reference(message)
    explicit_dataset_markers = (
        "excel",
        "csv",
        "json",
        "parquet",
        "spreadsheet",
        "workbook",
        "工作簿",
    )
    weak_dataset_reference_markers = (
        "这个表",
        "这张表",
        "那个表",
        "那张表",
        "刚才那个表",
        "刚才的数据表",
        "这份表格",
        "这个数据表",
    )

    schema_markers = ("schema", "columns", "row count", "列名", "字段", "结构", "表头", "总行数")
    row_count_markers = ("总数", "总行数", "多少条", "几条", "多少人", "多少商品", "row count")
    shortage_markers = ("缺货", "库存不足", "补货", "安全库存", "reorder")
    shortage_location_markers = (
        "不够",
        "不足",
        "缺少",
        "不太够",
        "紧张",
    )
    non_shortage_markers = (
        "不缺货",
        "不缺",
        "没有缺货",
        "无缺货",
        "不短缺",
        "不紧张",
    )
    abundance_markers = (
        "充足",
        "最充足",
        "最足",
        "最丰富",
        "库存最高",
        "货物最充足",
        "most stock",
        "highest stock",
        "stockiest",
    )
    ranking_markers = ("top 5", "top5", "top 10", "top10", "前三", "前五", "前十", "排名", "排行")
    extreme_markers = ("最高", "最大", "最低", "最小", "谁", "哪个")
    grouping_markers = ("group", "sum", "mean", "avg", "按地区", "按仓库", "按部门", "按品类", "汇总", "分布", "平均")
    query_markers = ("查询", "查找", "找出", "有哪些", "筛选", "统计", "分析")
    explanation_markers = ("为什么", "怎么回事", "找不到", "无法", "不能", "失败")
    structured_operation_markers = (
        *schema_markers,
        *row_count_markers,
        *shortage_markers,
        *shortage_location_markers,
        *non_shortage_markers,
        *abundance_markers,
        *ranking_markers,
        *extreme_markers,
        *grouping_markers,
        *query_markers,
    )

    has_explicit_dataset_source = bool(explicit_dataset_path) or _contains_any(lowered, explicit_dataset_markers)
    has_weak_dataset_reference = _contains_any(lowered, weak_dataset_reference_markers)
    has_generic_dataset_followup = _looks_generic_dataset_followup(message, lowered)
    has_structured_operation = _contains_any(lowered, structured_operation_markers)
    if _contains_any(lowered, explanation_markers) and not has_explicit_dataset_source:
        return None
    if (has_weak_dataset_reference or has_generic_dataset_followup) and not has_explicit_dataset_source:
        return None
    if not has_explicit_dataset_source:
        return None
    if not has_explicit_dataset_source and not has_structured_operation:
        return None

    reasons: list[str] = []
    if explicit_dataset_path:
        reasons.append("explicit_dataset_reference")
    elif has_explicit_dataset_source:
        reasons.append("explicit_dataset_source")
    if has_structured_operation:
        reasons.append("structured_operation_markers")

    parameters: dict[str, Any] = {"query": message}
    if explicit_dataset_path:
        parameters["path"] = explicit_dataset_path

    return TaskUnderstanding(
        intent="structured_dataset_query",
        source_kind="dataset",
        task_kind="dataset_query",
        modality="table",
        route_hint="tool",
        preferred_skill="structured-data-analysis",
        candidate_tools=["structured_data_analysis"],
        parameters=parameters,
        execution_posture="direct_tool",
        direct_route_reason="explicit_dataset_reference" if explicit_dataset_path else "explicit_dataset_source",
        should_skip_rag=True,
        confidence=0.9 if explicit_dataset_path else 0.76,
        reasons=reasons,
    )


def _detect_knowledge_task(message: str, lowered: str) -> TaskUnderstanding | None:
    knowledge_markers = (
        "知识库",
        "本地资料",
        "查资料",
        "文档里",
        "资料里",
        "讲讲",
        "介绍",
        "总结",
        "股东",
        "报告",
        "白皮书",
        "数据库里有不少",
    )
    if not _contains_any(lowered, knowledge_markers):
        return None
    if _has_freshness_signal(lowered):
        return _build_bounded_lookup_task(
            message=message,
            lowered=lowered,
            source_kind="knowledge_base",
            task_kind="knowledge_lookup",
            modality="general",
            confidence=0.68,
            reasons=["knowledge_markers", "freshness_signal"],
        )
    return TaskUnderstanding(
        intent="knowledge_lookup_query",
        source_kind="knowledge_base",
        task_kind="knowledge_lookup",
        modality="general",
        route_hint="rag",
        preferred_skill="rag-skill",
        candidate_tools=["search_knowledge"],
        parameters={"query": message},
        execution_posture="direct_rag",
        direct_route_reason="explicit_knowledge_scope",
        should_skip_rag=False,
        confidence=0.78,
        reasons=["knowledge_markers"],
    )


def _extract_explicit_dataset_reference(message: str) -> str:
    normalized = (message or "").strip()
    if not normalized:
        return ""
    match = re.search(
        r"([^\s,，;；:：\"'“”‘’]+?\.(?:xlsx|csv|xls|json|parquet))",
        normalized,
        flags=re.IGNORECASE,
    )
    return match.group(1).strip() if match is not None else ""


def _build_bounded_lookup_task(
    *,
    message: str,
    lowered: str,
    source_kind: str,
    task_kind: str,
    modality: str,
    confidence: float,
    reasons: list[str],
) -> TaskUnderstanding:
    candidate_tools = ["search_knowledge"]
    direct_route_reason = "unresolved_lookup"
    if _has_freshness_signal(lowered):
        candidate_tools.append("web_search")
        direct_route_reason = "freshness_aware_lookup"
    return TaskUnderstanding(
        intent="general_query",
        source_kind=source_kind,
        task_kind=task_kind,
        modality=modality,
        route_hint="agent",
        preferred_skill=None,
        candidate_tools=candidate_tools,
        parameters={"query": message},
        execution_posture="bounded_agent",
        direct_route_reason=direct_route_reason,
        should_skip_rag=False,
        confidence=confidence,
        reasons=reasons,
    )


def _has_freshness_signal(lowered: str) -> bool:
    freshness_markers = (
        "今年",
        "现在",
        "目前",
        "还在",
        "最新",
        "最新状态",
        "实时",
        "today",
        "latest",
        "current",
        "currently",
        "recent",
    )
    return _contains_any(lowered, freshness_markers)


def _looks_generic_dataset_followup(message: str, lowered: str) -> bool:
    starter_markers = ("再", "继续", "然后", "接着", "那就", "再来", "回到刚才", "刚才那个")
    generic_reference_markers = (
        "这个表",
        "这张表",
        "那个表",
        "那张表",
        "刚才那个表",
        "刚才的数据表",
        "这份表格",
        "这个数据表",
    )
    continuation_actions = (
        "展开一下",
        "展开",
        "看一下",
        "看下",
        "列一下",
        "整理一下",
        "再按",
    )
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
    if any(marker in message for marker in generic_reference_markers):
        return True
    if not any(lowered.startswith(marker) for marker in starter_markers):
        return (
            any(marker in message for marker in grouping_markers)
            and any(marker in message for marker in continuation_actions)
            and not any(marker in message for marker in domain_markers)
        )
    return any(marker in message for marker in continuation_actions)
