from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

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
            should_skip_rag=True,
            confidence=1.0,
            reasons=["memory_intent"],
        )

    return (
        _detect_realtime_task(normalized, lowered)
        or _detect_web_task(normalized, lowered)
        or _detect_pdf_task(normalized, lowered)
        or _detect_faq_task(normalized, lowered)
        or _detect_structured_data_task(normalized, lowered)
        or _detect_knowledge_task(normalized, lowered)
        or TaskUnderstanding(
            source_kind="knowledge_base",
            task_kind="knowledge_lookup",
            preferred_skill="rag-skill",
            candidate_tools=["search_knowledge"],
            reasons=["fallback_knowledge_lookup"],
            confidence=0.35,
        )
    )


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def _structured_semantic_hints(
    *,
    analysis_type: str,
    target_object: str | None,
    state_kind: str | None = None,
    group_hint: str | None = None,
    metric_hint: str | None = None,
    query_mode_hint: str | None = None,
) -> dict[str, Any]:
    hints: dict[str, Any] = {"analysis_type_hint": analysis_type}
    if target_object is not None:
        hints["target_object"] = target_object
    if state_kind is not None:
        hints["state_kind"] = state_kind
    if group_hint is not None:
        hints["group_hint"] = group_hint
    if metric_hint is not None:
        hints["metric_hint"] = metric_hint
    if query_mode_hint is not None:
        hints["query_mode_hint"] = query_mode_hint
    return hints


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
            target_object="weather",
            modality="realtime",
            route_hint="tool",
            preferred_skill="get-weather",
            candidate_tools=["get_weather"],
            parameters={"query": message},
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
            target_object="gold_price",
            modality="realtime",
            route_hint="tool",
            preferred_skill="gold-price",
            candidate_tools=["get_gold_price"],
            parameters={"query": message},
            should_skip_rag=True,
            confidence=0.97,
            reasons=["gold_markers"],
        )
    return None


def _detect_web_task(message: str, lowered: str) -> TaskUnderstanding | None:
    web_markers = (
        "联网",
        "搜索",
        "查官网",
        "官网",
        "最新",
        "新闻",
        "实时",
        "最新消息",
        "look it up",
        "search",
        "official docs",
        "news",
    )
    if not _contains_any(lowered, web_markers):
        return None
    return TaskUnderstanding(
        intent="web_search_query",
        source_kind="external_web",
        task_kind="web_lookup",
        target_object="external_information",
        modality="web",
        route_hint="tool",
        preferred_skill="web-search",
        candidate_tools=["web_search"],
        parameters={"query": message},
        should_skip_rag=True,
        confidence=0.92,
        reasons=["web_markers"],
    )


def _detect_pdf_task(message: str, lowered: str) -> TaskUnderstanding | None:
    pdf_markers = ("pdf", "白皮书", "报告", "文档")
    page_markers = (
        bool(re.search(r"第\s*\d+\s*页", message)),
        bool(re.search(r"第\s*[零一二三四五六七八九十百千两\d]+\s*页", message)),
        bool(re.search(r"page\s*\d+", lowered)),
    )
    deep_read_markers = ("详细解读", "通读", "精读", "逐页", "完整总结", "deep read")

    if not _contains_any(lowered, pdf_markers) and not any(page_markers):
        return None

    if any(page_markers):
        task_kind = "document_page_read"
        mode = "page_read"
    elif _contains_any(lowered, deep_read_markers):
        task_kind = "document_deep_read"
        mode = "deep_read"
    else:
        task_kind = "document_browse"
        mode = "browse"

    reasons = ["pdf_markers"] if _contains_any(lowered, pdf_markers) else []
    if any(page_markers):
        reasons.append("page_markers")
    if task_kind == "document_deep_read":
        reasons.append("deep_read_markers")

    return TaskUnderstanding(
        intent=f"pdf_{task_kind}",
        source_kind="document",
        task_kind=task_kind,
        target_object="pdf_document",
        modality="pdf",
        route_hint="tool",
        preferred_skill="pdf-analysis",
        candidate_tools=["pdf_analysis"],
        parameters={"query": message, "mode": mode},
        should_skip_rag=True,
        confidence=0.93 if mode == "page_read" else 0.88,
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
        target_object="faq",
        modality="general",
        route_hint="rag",
        preferred_skill="rag-skill",
        candidate_tools=["search_knowledge"],
        parameters={"query": message},
        should_skip_rag=False,
        confidence=0.9,
        reasons=["faq_explanation_markers"],
    )


def _detect_structured_data_task(message: str, lowered: str) -> TaskUnderstanding | None:
    explicit_dataset_markers = (
        ".xlsx",
        ".csv",
        ".json",
        "excel",
        "spreadsheet",
        "sheet",
        "数据表",
        "表格",
        "工作表",
        "列名",
        "schema",
        "数据库",
    )
    inventory_markers = (
        "inventory",
        "stock",
        "reorder",
        "warehouse",
        "sku",
        "库存",
        "缺货",
        "补货",
        "安全库存",
        "仓库",
        "货物",
        "商品",
    )
    employee_markers = (
        "employee",
        "employees",
        "staff",
        "salary",
        "wage",
        "pay",
        "base_salary",
        "department",
        "title",
        "hire",
        "员工",
        "薪水",
        "工资",
        "薪资",
        "底薪",
        "部门",
        "职位",
    )
    sales_markers = (
        "sales",
        "sale",
        "orders",
        "revenue",
        "amount",
        "region",
        "quantity",
        "gmv",
        "销售",
        "销售额",
        "销量",
        "金额",
        "地区",
        "区域",
        "成交",
    )
    customer_markers = (
        "customer",
        "customers",
        "segment",
        "signup",
        "email",
        "province",
        "客户",
        "用户",
        "分群",
        "注册",
        "邮箱",
        "省份",
    )

    schema_markers = ("schema", "columns", "row count", "列名", "字段", "结构", "表头", "总行数")
    row_count_markers = ("总数", "总行数", "多少条", "几条", "多少人", "多少商品", "row count")
    shortage_markers = ("缺货", "库存不足", "补货", "安全库存", "reorder")
    non_shortage_markers = (
        "不缺货",
        "不缺",
        "没有缺货",
        "无缺货",
        "不短缺",
        "不紧张",
    )
    shortage_location_markers = (
        "不够",
        "不足",
        "缺少",
        "不太够",
        "紧张",
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
    correction_markers = ("不是", "不要", "而是", "别", "别再", "我不是要")

    has_explicit_dataset_source = _contains_any(lowered, explicit_dataset_markers)

    target_object: str | None = None
    if _contains_any(lowered, inventory_markers):
        target_object = "inventory"
    elif _contains_any(lowered, employee_markers):
        target_object = "employee"
    elif _contains_any(lowered, sales_markers):
        target_object = "sales"
    elif _contains_any(lowered, customer_markers):
        target_object = "customer"

    if _contains_any(lowered, explanation_markers) and not has_explicit_dataset_source:
        return None

    task_kind: str | None = None
    analysis_type = "auto"
    reasons: list[str] = []

    correction_override = _contains_any(lowered, correction_markers)
    inventory_abundance_query = target_object == "inventory" and _contains_any(lowered, abundance_markers)
    inventory_non_shortage_query = (
        target_object == "inventory"
        and _contains_any(lowered, non_shortage_markers)
        and any(marker in lowered for marker in ("哪些地方", "哪个地方", "哪里", "地方", "哪些仓库", "哪个仓库", "仓库"))
    )
    inventory_location_shortage_query = (
        target_object == "inventory"
        and (_contains_any(lowered, shortage_markers) or _contains_any(lowered, shortage_location_markers))
        and any(marker in lowered for marker in ("哪些地方", "哪个地方", "哪里", "地方", "哪些仓库", "哪个仓库", "仓库"))
    )

    if _contains_any(lowered, schema_markers):
        task_kind = "dataset_schema_inspect"
        analysis_type = "schema_preview"
        reasons.append("schema_markers")
    elif _contains_any(lowered, row_count_markers):
        task_kind = "dataset_row_count"
        analysis_type = "row_count"
        reasons.append("row_count_markers")
    elif inventory_non_shortage_query:
        task_kind = "dataset_top_n"
        analysis_type = "top_n"
        reasons.append("inventory_non_shortage_markers")
    elif inventory_location_shortage_query and not (correction_override and inventory_abundance_query):
        task_kind = "dataset_top_n"
        analysis_type = "top_n"
        reasons.append("inventory_location_shortage_markers")
    elif target_object == "inventory" and _contains_any(lowered, shortage_markers + shortage_location_markers) and not (correction_override and inventory_abundance_query):
        task_kind = "dataset_filter"
        analysis_type = "inventory_shortage"
        reasons.append("inventory_shortage_markers")
    elif inventory_abundance_query:
        task_kind = "dataset_top_n"
        analysis_type = "top_n"
        reasons.append("inventory_abundance_markers")
    elif _contains_any(lowered, ranking_markers):
        task_kind = "dataset_top_n"
        analysis_type = "top_n"
        reasons.append("ranking_markers")
    elif _contains_any(lowered, extreme_markers):
        task_kind = "dataset_extreme_record"
        analysis_type = "extreme_record"
        reasons.append("extreme_markers")
    elif _contains_any(lowered, grouping_markers):
        task_kind = "dataset_group_summary"
        analysis_type = "grouped_summary"
        reasons.append("grouping_markers")
    elif target_object == "inventory" and "库存" in lowered:
        task_kind = "dataset_summary"
        analysis_type = "inventory_summary"
        reasons.append("inventory_summary_markers")

    strong_query_shape = has_explicit_dataset_source or target_object is not None or _contains_any(lowered, query_markers)
    if task_kind is None and strong_query_shape and target_object is not None:
        task_kind = "dataset_inspect"
        analysis_type = "auto"
        reasons.append("dataset_domain_fallback")

    if task_kind is None:
        return None

    semantic_hints: dict[str, Any] = {}
    if target_object == "inventory":
        if inventory_abundance_query:
            semantic_hints = _structured_semantic_hints(
                analysis_type=analysis_type,
                target_object=target_object,
                state_kind="abundance",
                group_hint="warehouse",
                metric_hint="stock_on_hand",
                query_mode_hint="grouped",
            )
        elif inventory_non_shortage_query:
            semantic_hints = _structured_semantic_hints(
                analysis_type=analysis_type,
                target_object=target_object,
                state_kind="non_shortage",
                group_hint="warehouse",
                metric_hint="shortage_qty",
                query_mode_hint="grouped",
            )
        elif inventory_location_shortage_query:
            semantic_hints = _structured_semantic_hints(
                analysis_type=analysis_type,
                target_object=target_object,
                state_kind="shortage",
                group_hint="warehouse",
                metric_hint="shortage_qty",
                query_mode_hint="grouped",
            )
        elif analysis_type == "inventory_shortage":
            semantic_hints = _structured_semantic_hints(
                analysis_type=analysis_type,
                target_object=target_object,
                state_kind="shortage",
                metric_hint="shortage_qty",
            )
    elif analysis_type == "grouped_summary":
        semantic_hints = _structured_semantic_hints(
            analysis_type=analysis_type,
            target_object=target_object,
            query_mode_hint="grouped",
        )
    elif analysis_type == "extreme_record":
        semantic_hints = _structured_semantic_hints(
            analysis_type=analysis_type,
            target_object=target_object,
            query_mode_hint="record",
        )
    elif analysis_type == "top_n":
        semantic_hints = _structured_semantic_hints(
            analysis_type=analysis_type,
            target_object=target_object,
        )

    return TaskUnderstanding(
        intent=f"structured_{task_kind}",
        source_kind="dataset",
        task_kind=task_kind,
        target_object=target_object,
        modality="table",
        route_hint="tool",
        preferred_skill="structured-data-analysis",
        candidate_tools=["structured_data_analysis"],
        parameters={
            "query": message,
            "analysis_type": analysis_type,
            "semantic_hints": semantic_hints,
        },
        should_skip_rag=True,
        confidence=0.94 if target_object is not None else 0.82,
        reasons=reasons + (["explicit_dataset_source"] if has_explicit_dataset_source else []),
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
    return TaskUnderstanding(
        intent="knowledge_lookup_query",
        source_kind="knowledge_base",
        task_kind="knowledge_lookup",
        target_object="local_knowledge",
        modality="general",
        route_hint="rag",
        preferred_skill="rag-skill",
        candidate_tools=["search_knowledge"],
        parameters={"query": message},
        should_skip_rag=False,
        confidence=0.78,
        reasons=["knowledge_markers"],
    )
