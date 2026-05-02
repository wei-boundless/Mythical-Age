from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from pdf_analysis.catalog import PdfAnalysisCatalog
from understanding.memory_intent import MemoryIntent


DATASET_PATH_PATTERN = re.compile(
    r"([^\s,，;；:：\"'“”‘’]+?\.(?:xlsx|csv|xls|json|parquet))",
    flags=re.IGNORECASE,
)
WORKSPACE_FILE_PATH_PATTERN = re.compile(
    r"([^\s,，;；:：\"'“”‘’]+?\.(?:md|txt|py|toml|ya?ml|ini|cfg|ts|tsx|js|jsx|css|html|sql|log|sh|ps1))",
    flags=re.IGNORECASE,
)
URL_PATTERN = re.compile(r"https?://[^\s]+", flags=re.IGNORECASE)

PAGE_REFERENCE_PATTERN = re.compile(
    r"(?:第\s*\d+\s*页|第\s*[零一二三四五六七八九十百千两\d]+\s*页|page\s*\d+)",
    flags=re.IGNORECASE,
)
SECTION_REFERENCE_PATTERN = re.compile(
    r"(?:第\s*[零一二三四五六七八九十百千两\d]+\s*(?:部分|章|节)|这一部分|那一部分|这一章|那一章|这一节|那一节)",
    flags=re.IGNORECASE,
)
LOCAL_SOURCE_ANCHOR_PATTERN = re.compile(
    r"(?P<qualifier>本地|本机|当前|项目(?:内)?|我的|我们(?:的)?|咱们(?:的)?|你(?:这边|这里|的)?|系统(?:内)?|库内)"
    r"(?:\s*的|\s*)"
    r"(?P<container>知识库|资料库|数据库|文档库|本地库|资料|文档)",
    flags=re.IGNORECASE,
)
SOURCE_LOCATIVE_ANCHOR_PATTERN = re.compile(
    r"(?P<container>知识库|资料库|数据库|文档库|本地库|资料|文档)"
    r"(?:里|中|内|里面|当中)",
    flags=re.IGNORECASE,
)


@dataclass(slots=True)
class TaskSignals:
    explicit_dataset_path: str = ""
    explicit_pdf_path: str = ""
    explicit_workspace_path: str = ""
    bound_dataset_path: str = ""
    bound_pdf_path: str = ""
    bound_pdf_mode: str = ""
    bound_pdf_section: str = ""
    bound_pdf_pages: list[int] = field(default_factory=list)
    binding_source: str = ""
    explicit_urls: list[str] = field(default_factory=list)
    anchor_kinds: list[str] = field(default_factory=list)
    page_reference: bool = False
    section_reference: bool = False
    document_reference: bool = False
    document_read_intent: bool = False
    local_knowledge_scope: bool = False
    knowledge_source_anchor: str = ""
    knowledge_source_anchor_kind: str = ""
    workspace_read_request: bool = False
    workspace_search_request: bool = False
    business_dataset_request: bool = False
    faq_shape: bool = False
    external_requirement: bool = False
    official_source_requirement: bool = False
    freshness_requirement: bool = False
    weather_domain: bool = False
    gold_price_domain: bool = False
    mixed_direct_capabilities: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "explicit_dataset_path": self.explicit_dataset_path,
            "explicit_pdf_path": self.explicit_pdf_path,
            "explicit_workspace_path": self.explicit_workspace_path,
            "bound_dataset_path": self.bound_dataset_path,
            "bound_pdf_path": self.bound_pdf_path,
            "bound_pdf_mode": self.bound_pdf_mode,
            "bound_pdf_section": self.bound_pdf_section,
            "bound_pdf_pages": list(self.bound_pdf_pages),
            "binding_source": self.binding_source,
            "explicit_urls": list(self.explicit_urls),
            "anchor_kinds": list(self.anchor_kinds),
            "page_reference": self.page_reference,
            "section_reference": self.section_reference,
            "document_reference": self.document_reference,
            "document_read_intent": self.document_read_intent,
            "local_knowledge_scope": self.local_knowledge_scope,
            "knowledge_source_anchor": self.knowledge_source_anchor,
            "knowledge_source_anchor_kind": self.knowledge_source_anchor_kind,
            "workspace_read_request": self.workspace_read_request,
            "workspace_search_request": self.workspace_search_request,
            "business_dataset_request": self.business_dataset_request,
            "faq_shape": self.faq_shape,
            "external_requirement": self.external_requirement,
            "official_source_requirement": self.official_source_requirement,
            "freshness_requirement": self.freshness_requirement,
            "weather_domain": self.weather_domain,
            "gold_price_domain": self.gold_price_domain,
            "mixed_direct_capabilities": self.mixed_direct_capabilities,
        }


@dataclass(slots=True)
class TaskUnderstanding:
    intent: str = "general_query"
    source_kind: str = "knowledge_base"
    task_kind: str = "knowledge_lookup"
    target_object: str | None = None
    modality: str = "general"
    route_hint: str = "rag"
    preferred_skill: str | None = None
    capability_requests: list[str] = field(default_factory=list)
    candidate_tools: list[str] = field(default_factory=list)
    parameters: dict[str, Any] = field(default_factory=dict)
    execution_posture: str = "direct_rag"
    direct_route_reason: str = ""
    should_skip_rag: bool = False
    confidence: float = 0.0
    reasons: list[str] = field(default_factory=list)
    structural_signals: dict[str, Any] = field(default_factory=dict)


def analyze_task_understanding(
    message: str,
    memory_intent: MemoryIntent | None = None,
    *,
    active_bindings: dict[str, Any] | None = None,
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
            capability_requests=[],
        )

    signals = _collect_task_signals(
        normalized,
        lowered,
        active_bindings=active_bindings,
    )

    direct_realtime = _build_direct_weather_task(normalized, signals) or _build_direct_gold_task(normalized, signals)
    if direct_realtime is not None:
        return direct_realtime

    if signals.mixed_direct_capabilities:
        return _build_bounded_lookup_task(
            message=normalized,
            source_kind="mixed_sources",
            task_kind="multi_capability_request",
            modality="multi",
            confidence=0.78,
            reasons=["mixed_direct_capabilities"],
            signals=signals,
        )

    direct = (
        _build_direct_dataset_task(normalized, signals)
        or _build_direct_pdf_task(normalized, signals)
        or _build_direct_workspace_read_task(normalized, signals)
        or _build_direct_workspace_search_task(normalized, signals)
        or _build_direct_web_task(normalized, signals)
        or _build_direct_faq_task(normalized, signals)
        or _build_direct_knowledge_task(normalized, signals)
    )
    if direct is not None:
        return direct

    return _build_bounded_lookup_task(
        message=normalized,
        source_kind="knowledge_base",
        task_kind="knowledge_lookup",
        modality="general",
        confidence=0.42,
        reasons=["fallback_bounded_lookup"],
        signals=signals,
    )


def _collect_task_signals(
    message: str,
    lowered: str,
    *,
    active_bindings: dict[str, Any] | None,
) -> TaskSignals:
    explicit_dataset_path = _extract_explicit_dataset_reference(message)
    explicit_pdf_references = PdfAnalysisCatalog.extract_explicit_pdf_references(message)
    explicit_pdf_path = explicit_pdf_references[0] if explicit_pdf_references else ""
    explicit_workspace_path = _extract_explicit_workspace_file_reference(
        message,
        explicit_dataset_path=explicit_dataset_path,
        explicit_pdf_path=explicit_pdf_path,
    )
    explicit_urls = URL_PATTERN.findall(message)

    page_reference = bool(PAGE_REFERENCE_PATTERN.search(message))
    section_reference = bool(SECTION_REFERENCE_PATTERN.search(message))
    document_reference = _contains_any(lowered, ("pdf", "白皮书", "报告", "report"))
    document_read_intent = page_reference or section_reference or _contains_any(
        lowered,
        ("解读", "总结", "通读", "逐页", "总览", "讲得什么", "讲什么", "看一下", "看看"),
    )

    knowledge_source_anchor, knowledge_source_anchor_kind = _extract_knowledge_source_anchor(message)
    local_knowledge_scope = bool(knowledge_source_anchor)
    workspace_read_request = explicit_workspace_path != "" and _looks_like_workspace_read_request(lowered)
    workspace_search_request = _looks_like_workspace_search_request(lowered)
    business_dataset_request = _looks_like_business_dataset_request(lowered)
    faq_shape = _looks_like_faq_problem(lowered)
    external_requirement = bool(explicit_urls) or _contains_any(
        lowered,
        ("联网", "官网", "官方文档", "official docs", "web search", "上网", "网上查", "look it up", "news"),
    )
    official_source_requirement = bool(explicit_urls) or _contains_any(
        lowered,
        ("官网", "官方文档", "official docs", "official"),
    )
    freshness_requirement = _contains_any(
        lowered,
        ("今年", "现在", "目前", "还在", "最新", "最新状态", "实时", "today", "latest", "current", "currently", "recent"),
    )
    weather_domain = _contains_any(
        lowered,
        ("weather", "forecast", "temperature", "天气", "气温", "温度", "降雨", "下雨", "风速", "风向", "预报"),
    )
    gold_price_domain = _contains_any(
        lowered,
        ("gold price", "spot gold", "xau", "xauusd", "黄金", "金价", "现货黄金", "黄金价格"),
    )
    binding_view = _normalize_active_bindings(active_bindings)

    anchor_kinds: list[str] = []
    if explicit_dataset_path:
        anchor_kinds.append("dataset_path")
    if explicit_pdf_path:
        anchor_kinds.append("pdf_path")
    if explicit_workspace_path:
        anchor_kinds.append("workspace_path")
    elif document_reference:
        anchor_kinds.append("document_reference")
    if page_reference:
        anchor_kinds.append("page_reference")
    if section_reference:
        anchor_kinds.append("section_reference")
    if explicit_urls:
        anchor_kinds.append("url")
    if binding_view["bound_dataset_path"]:
        anchor_kinds.append("bound_dataset")
    if binding_view["bound_pdf_path"]:
        anchor_kinds.append("bound_pdf")
    if external_requirement:
        anchor_kinds.append("external_requirement")
    if official_source_requirement:
        anchor_kinds.append("official_source_requirement")
    if freshness_requirement:
        anchor_kinds.append("freshness_requirement")
    if local_knowledge_scope:
        anchor_kinds.append("knowledge_scope")
    if faq_shape:
        anchor_kinds.append("faq_shape")
    if weather_domain:
        anchor_kinds.append("weather_domain")
    if gold_price_domain:
        anchor_kinds.append("gold_price_domain")

    signals = TaskSignals(
        explicit_dataset_path=explicit_dataset_path,
        explicit_pdf_path=explicit_pdf_path,
        explicit_workspace_path=explicit_workspace_path,
        bound_dataset_path=binding_view["bound_dataset_path"],
        bound_pdf_path=binding_view["bound_pdf_path"],
        bound_pdf_mode=binding_view["bound_pdf_mode"],
        bound_pdf_section=binding_view["bound_pdf_section"],
        bound_pdf_pages=list(binding_view["bound_pdf_pages"]),
        binding_source=binding_view["binding_source"],
        explicit_urls=explicit_urls,
        anchor_kinds=anchor_kinds,
        page_reference=page_reference,
        section_reference=section_reference,
        document_reference=document_reference or bool(explicit_pdf_path),
        document_read_intent=document_read_intent,
        local_knowledge_scope=local_knowledge_scope,
        knowledge_source_anchor=knowledge_source_anchor,
        knowledge_source_anchor_kind=knowledge_source_anchor_kind,
        workspace_read_request=workspace_read_request,
        workspace_search_request=workspace_search_request,
        business_dataset_request=business_dataset_request,
        faq_shape=faq_shape,
        external_requirement=external_requirement,
        official_source_requirement=official_source_requirement,
        freshness_requirement=freshness_requirement,
        weather_domain=weather_domain,
        gold_price_domain=gold_price_domain,
    )
    signals.mixed_direct_capabilities = _has_mixed_direct_capabilities(signals)
    return signals


def _build_direct_dataset_task(message: str, signals: TaskSignals) -> TaskUnderstanding | None:
    followup_dataset_request = (
        bool(signals.bound_dataset_path)
        and not signals.explicit_pdf_path
        and not signals.explicit_workspace_path
        and _looks_like_dataset_followup_request(message.lower())
    )
    bundle_followup_request = _looks_like_bundle_followup_request(message.lower())
    if not signals.explicit_dataset_path and not signals.business_dataset_request and not followup_dataset_request:
        if not (bundle_followup_request and signals.bound_dataset_path):
            return None
    parameters: dict[str, Any] = {
        "query": message,
    }
    if signals.explicit_dataset_path:
        reasons = ["explicit_dataset_anchor"]
    elif followup_dataset_request:
        reasons = ["bound_dataset_followup"]
    elif bundle_followup_request:
        reasons = ["bundle_subtask_followup"]
    else:
        reasons = ["business_dataset_intent"]
    if signals.explicit_dataset_path:
        parameters["path"] = signals.explicit_dataset_path
    elif signals.bound_dataset_path:
        parameters["path"] = signals.bound_dataset_path
    return TaskUnderstanding(
        intent="structured_dataset_query",
        source_kind="dataset",
        task_kind="dataset_query",
        modality="table",
        route_hint="tool",
        preferred_skill="structured-data-analysis",
        capability_requests=["dataset_analysis"],
        parameters=parameters,
        execution_posture="direct_tool",
        direct_route_reason=reasons[0],
        should_skip_rag=True,
        confidence=0.96 if signals.explicit_dataset_path else 0.91 if (followup_dataset_request or bundle_followup_request) else 0.86,
        reasons=reasons,
        structural_signals=signals.to_dict(),
    )


def _build_direct_pdf_task(message: str, signals: TaskSignals) -> TaskUnderstanding | None:
    followup_pdf_request = (
        bool(signals.bound_pdf_path)
        and not signals.explicit_dataset_path
        and not signals.explicit_workspace_path
        and _looks_like_pdf_followup_request(message.lower())
    )
    has_document_anchor = bool(signals.explicit_pdf_path) or followup_pdf_request or (
        (signals.document_reference or signals.page_reference or signals.section_reference)
        and (signals.page_reference or signals.section_reference or signals.document_read_intent)
    )
    if not has_document_anchor or signals.external_requirement:
        return None
    if signals.page_reference:
        task_kind = "document_page"
        mode = "page"
    elif signals.section_reference:
        task_kind = "document_section"
        mode = "section"
    else:
        task_kind = "document_read"
        mode = "document"
    parameters: dict[str, Any] = {"query": message, "mode": mode}
    reasons = ["document_scope_anchor"]
    if signals.explicit_pdf_path:
        parameters["path"] = signals.explicit_pdf_path
        reasons.append("explicit_pdf_anchor")
    elif signals.bound_pdf_path:
        parameters["path"] = signals.bound_pdf_path
        reasons.append("bound_pdf_followup")
        if mode == "document" and signals.bound_pdf_mode:
            parameters["mode"] = signals.bound_pdf_mode
    return TaskUnderstanding(
        intent=f"pdf_{task_kind}",
        source_kind="document",
        task_kind=task_kind,
        modality="pdf",
        route_hint="tool",
        preferred_skill="pdf-analysis",
        capability_requests=["document_analysis"],
        parameters=parameters,
        execution_posture="direct_tool",
        direct_route_reason=(
            "explicit_pdf_anchor"
            if signals.explicit_pdf_path
            else "bound_pdf_followup"
            if followup_pdf_request
            else "document_scope_anchor"
        ),
        should_skip_rag=True,
        confidence=0.94 if signals.explicit_pdf_path else 0.91 if followup_pdf_request else 0.87,
        reasons=reasons,
        structural_signals=signals.to_dict(),
    )


def _build_direct_workspace_read_task(message: str, signals: TaskSignals) -> TaskUnderstanding | None:
    if not signals.explicit_workspace_path or not signals.workspace_read_request:
        return None
    lowered_path = signals.explicit_workspace_path.lower()
    modality = "code" if lowered_path.endswith((".py", ".ts", ".tsx", ".js", ".jsx", ".sh", ".ps1", ".sql")) else "text"
    return TaskUnderstanding(
        intent="workspace_file_read_query",
        source_kind="workspace",
        task_kind="workspace_file_read",
        modality=modality,
        route_hint="tool",
        preferred_skill=None,
        capability_requests=["workspace_read"],
        candidate_tools=["read_file"],
        parameters={"path": signals.explicit_workspace_path},
        execution_posture="direct_tool",
        direct_route_reason="explicit_workspace_file_anchor",
        should_skip_rag=True,
        confidence=0.95,
        reasons=["explicit_workspace_file_anchor"],
        structural_signals=signals.to_dict(),
    )


def _build_direct_workspace_search_task(message: str, signals: TaskSignals) -> TaskUnderstanding | None:
    if not signals.workspace_search_request or signals.external_requirement:
        return None
    return TaskUnderstanding(
        intent="workspace_file_search_query",
        source_kind="workspace",
        task_kind="workspace_file_search",
        modality="workspace",
        route_hint="tool",
        preferred_skill=None,
        capability_requests=["workspace_search"],
        candidate_tools=["search_files"],
        parameters={"query": message},
        execution_posture="direct_tool",
        direct_route_reason="workspace_search_request",
        should_skip_rag=True,
        confidence=0.9,
        reasons=["workspace_search_request"],
        structural_signals=signals.to_dict(),
    )


def _build_direct_weather_task(message: str, signals: TaskSignals) -> TaskUnderstanding | None:
    if not signals.weather_domain or signals.explicit_dataset_path or signals.explicit_pdf_path:
        return None
    return TaskUnderstanding(
        intent="weather_query",
        source_kind="external_web",
        task_kind="realtime_lookup",
        modality="realtime",
        route_hint="tool",
        preferred_skill=None,
        capability_requests=["weather"],
        candidate_tools=["get_weather"],
        parameters={"query": message},
        execution_posture="direct_tool",
        direct_route_reason="dedicated_weather_capability",
        should_skip_rag=True,
        confidence=0.98,
        reasons=["dedicated_weather_capability"],
        structural_signals=signals.to_dict(),
    )


def _build_direct_gold_task(message: str, signals: TaskSignals) -> TaskUnderstanding | None:
    if not signals.gold_price_domain or signals.explicit_dataset_path or signals.explicit_pdf_path:
        return None
    return TaskUnderstanding(
        intent="gold_price_query",
        source_kind="external_web",
        task_kind="realtime_lookup",
        modality="realtime",
        route_hint="tool",
        preferred_skill=None,
        capability_requests=["gold_price"],
        candidate_tools=["get_gold_price"],
        parameters={"query": message},
        execution_posture="direct_tool",
        direct_route_reason="dedicated_gold_price_capability",
        should_skip_rag=True,
        confidence=0.97,
        reasons=["dedicated_gold_price_capability"],
        structural_signals=signals.to_dict(),
    )


def _build_direct_web_task(message: str, signals: TaskSignals) -> TaskUnderstanding | None:
    if not signals.external_requirement:
        return None
    return TaskUnderstanding(
        intent="web_search_query",
        source_kind="external_web",
        task_kind="web_lookup",
        modality="web",
        route_hint="tool",
        preferred_skill="web-search",
        capability_requests=["latest_information"],
        parameters={"query": message},
        execution_posture="direct_tool",
        direct_route_reason="explicit_external_constraint",
        should_skip_rag=True,
        confidence=0.93,
        reasons=["explicit_external_constraint"],
        structural_signals=signals.to_dict(),
    )


def _build_direct_faq_task(message: str, signals: TaskSignals) -> TaskUnderstanding | None:
    if not signals.faq_shape or signals.external_requirement or signals.explicit_dataset_path or signals.explicit_pdf_path:
        return None
    return TaskUnderstanding(
        intent="faq_explanation_query",
        source_kind="knowledge_base",
        task_kind="faq_explanation",
        modality="general",
        route_hint="rag",
        preferred_skill="rag-skill",
        capability_requests=["faq"],
        parameters={"query": message},
        execution_posture="direct_rag",
        direct_route_reason="faq_problem_shape",
        should_skip_rag=False,
        confidence=0.9,
        reasons=["faq_problem_shape"],
        structural_signals=signals.to_dict(),
    )


def _build_direct_knowledge_task(message: str, signals: TaskSignals) -> TaskUnderstanding | None:
    if not signals.local_knowledge_scope or signals.freshness_requirement:
        return None
    return TaskUnderstanding(
        intent="knowledge_lookup_query",
        source_kind="knowledge_base",
        task_kind="knowledge_lookup",
        modality="general",
        route_hint="rag",
        preferred_skill="rag-skill",
        capability_requests=["knowledge_lookup"],
        parameters={"query": message},
        execution_posture="direct_rag",
        direct_route_reason="explicit_knowledge_scope",
        should_skip_rag=False,
        confidence=0.8,
        reasons=["explicit_knowledge_scope"],
        structural_signals=signals.to_dict(),
    )


def _build_bounded_lookup_task(
    *,
    message: str,
    source_kind: str,
    task_kind: str,
    modality: str,
    confidence: float,
    reasons: list[str],
    signals: TaskSignals,
) -> TaskUnderstanding:
    capability_requests = _build_capability_requests(
        signals,
        include_default_knowledge=True,
    )
    direct_route_reason = "unresolved_lookup"
    if "latest_information" in capability_requests:
        direct_route_reason = "freshness_aware_lookup"
    return TaskUnderstanding(
        intent="general_query",
        source_kind=source_kind,
        task_kind=task_kind,
        modality=modality,
        route_hint="agent",
        preferred_skill=None,
        capability_requests=capability_requests,
        parameters={"query": message},
        execution_posture="bounded_agent",
        direct_route_reason=direct_route_reason,
        should_skip_rag=False,
        confidence=confidence,
        reasons=reasons,
        structural_signals=signals.to_dict(),
    )


def _extract_explicit_dataset_reference(message: str) -> str:
    normalized = (message or "").strip()
    if not normalized:
        return ""
    match = DATASET_PATH_PATTERN.search(normalized)
    return match.group(1).strip() if match is not None else ""


def _extract_explicit_workspace_file_reference(
    message: str,
    *,
    explicit_dataset_path: str,
    explicit_pdf_path: str,
) -> str:
    normalized = (message or "").strip()
    if not normalized or explicit_dataset_path or explicit_pdf_path:
        return ""
    match = WORKSPACE_FILE_PATH_PATTERN.search(normalized)
    if match is None:
        return ""
    return match.group(1).strip()


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def _extract_knowledge_source_anchor(message: str) -> tuple[str, str]:
    normalized = (message or "").strip()
    if not normalized:
        return "", ""

    match = LOCAL_SOURCE_ANCHOR_PATTERN.search(normalized)
    if match is not None:
        return match.group(0).strip(), "qualified_local_source"

    match = SOURCE_LOCATIVE_ANCHOR_PATTERN.search(normalized)
    if match is not None:
        return match.group(0).strip(), "locative_source"

    # In this product, an unqualified "知识库" names the local RAG corpus, not a
    # task domain. Keep this as a source anchor, but do not extend it to business
    # nouns such as "库存/缺货".
    if "知识库" in normalized:
        return "知识库", "named_knowledge_base"

    return "", ""


def _looks_like_business_dataset_request(lowered: str) -> bool:
    data_anchor = _contains_any(
        lowered,
        (
            "数据库",
            "数据表",
            "表格",
            "excel",
            "xlsx",
            "csv",
            "库存",
            "商品",
            "货物",
            "销售",
            "订单",
            "员工",
            "客户",
            "薪水",
            "工资",
            "薪资",
        ),
    )
    analytic_intent = _contains_any(
        lowered,
        (
            "查询",
            "分析",
            "统计",
            "汇总",
            "排名",
            "排行",
            "前五",
            "前三",
            "前十",
            "top",
            "哪些",
            "哪个",
            "多少",
            "缺货",
            "不足",
            "不缺货",
            "不缺",
            "不够",
            "充足",
            "最高",
            "最低",
        ),
    )
    implicit_inventory_intent = _contains_any(
        lowered,
        (
            "缺货",
            "不缺货",
            "不缺",
            "库存不足",
            "不够",
            "补货",
            "安全库存",
            "货物最充足",
        ),
    )
    implicit_location_inventory = implicit_inventory_intent and _contains_any(
        lowered,
        ("哪些地方", "哪个地方", "地方", "哪里", "仓库", "地区", "区域"),
    )
    return (data_anchor and analytic_intent) or implicit_location_inventory


def _looks_like_workspace_read_request(lowered: str) -> bool:
    return _contains_any(
        lowered,
        (
            "读取",
            "读一下",
            "读这个",
            "打开",
            "看一下",
            "看看",
            "内容",
            "原文",
            "源码",
            "文件",
            "read ",
            "open ",
            "show ",
            "file",
            "source",
        ),
    )


def _looks_like_workspace_search_request(lowered: str) -> bool:
    has_search_intent = _contains_any(
        lowered,
        (
            "搜索",
            "查找",
            "找一下",
            "找到",
            "搜一下",
            "检索",
            "rg",
            "ripgrep",
            "search file",
            "find file",
            "locate file",
        ),
    )
    has_workspace_object = _contains_any(
        lowered,
        (
            "文件",
            "路径",
            "目录",
            "源码",
            "文档",
            "file",
            "path",
            "workspace",
            "repo",
            "repository",
        ),
    )
    return has_search_intent and has_workspace_object


def _looks_like_faq_problem(lowered: str) -> bool:
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
    return _contains_any(lowered, explanation_markers) and _contains_any(lowered, faq_domain_markers)


def _has_mixed_direct_capabilities(signals: TaskSignals) -> bool:
    families: list[str] = []
    if signals.explicit_dataset_path:
        families.append("dataset")
    if signals.explicit_pdf_path or (
        signals.document_reference and (signals.page_reference or signals.section_reference)
    ):
        families.append("document")
    if signals.external_requirement:
        families.append("external")
    if signals.weather_domain:
        families.append("weather")
    if signals.gold_price_domain:
        families.append("finance")
    return len(set(families)) > 1


def _build_capability_requests(
    signals: TaskSignals,
    *,
    include_default_knowledge: bool,
) -> list[str]:
    requests: list[str] = []
    if signals.explicit_dataset_path:
        requests.append("dataset_analysis")
    if signals.explicit_pdf_path or (
        signals.document_reference and (signals.page_reference or signals.section_reference or signals.document_read_intent)
    ):
        requests.append("document_analysis")
    if signals.explicit_workspace_path and signals.workspace_read_request:
        requests.append("workspace_read")
    if signals.workspace_search_request:
        requests.append("workspace_search")
    if signals.weather_domain:
        requests.append("weather")
    if signals.gold_price_domain:
        requests.append("gold_price")
    if signals.external_requirement or signals.official_source_requirement or signals.freshness_requirement:
        requests.append("latest_information")
    if signals.faq_shape:
        requests.append("faq")
    if signals.local_knowledge_scope:
        requests.append("knowledge_lookup")
    if (
        include_default_knowledge
        and "knowledge_lookup" not in requests
        and not any(
            item in requests
            for item in ("dataset_analysis", "document_analysis", "workspace_read", "weather", "gold_price")
        )
    ):
        requests.insert(0, "knowledge_lookup")
    deduped: list[str] = []
    seen: set[str] = set()
    for item in requests:
        normalized = str(item or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def _normalize_active_bindings(active_bindings: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(active_bindings or {})
    active_constraints = dict(payload.get("active_constraints") or {})
    bound_pdf_path = str(
        payload.get("active_pdf")
        or active_constraints.get("active_pdf")
        or payload.get("committed_pdf")
        or active_constraints.get("committed_pdf")
        or ""
    ).strip()
    bound_dataset_path = str(
        payload.get("active_dataset")
        or active_constraints.get("active_dataset")
        or payload.get("committed_dataset")
        or active_constraints.get("committed_dataset")
        or ""
    ).strip()
    raw_pages = (
        payload.get("active_pdf_pages")
        or active_constraints.get("active_pdf_pages")
        or payload.get("pdf_focus_pages")
        or active_constraints.get("pdf_focus_pages")
        or []
    )
    bound_pdf_pages = [int(item) for item in list(raw_pages or []) if str(item).strip().isdigit()]
    binding_source = "active" if (payload.get("active_pdf") or payload.get("active_dataset") or active_constraints.get("active_pdf") or active_constraints.get("active_dataset")) else "committed" if (payload.get("committed_pdf") or payload.get("committed_dataset") or active_constraints.get("committed_pdf") or active_constraints.get("committed_dataset")) else ""
    return {
        "bound_pdf_path": bound_pdf_path,
        "bound_dataset_path": bound_dataset_path,
        "bound_pdf_mode": str(
            payload.get("active_pdf_mode")
            or active_constraints.get("active_pdf_mode")
            or payload.get("pdf_mode")
            or active_constraints.get("pdf_mode")
            or ""
        ).strip(),
        "bound_pdf_section": str(
            payload.get("active_pdf_section")
            or active_constraints.get("active_pdf_section")
            or payload.get("pdf_section")
            or active_constraints.get("pdf_section")
            or ""
        ).strip(),
        "bound_pdf_pages": bound_pdf_pages,
        "binding_source": binding_source,
    }


def _looks_like_dataset_followup_request(lowered: str) -> bool:
    if not lowered.strip():
        return False
    dataset_markers = (
        "汇总",
        "统计",
        "排行",
        "排名",
        "前五",
        "前三",
        "前十",
        "top",
        "按仓库",
        "按地区",
        "按部门",
        "这些人",
        "这些数据",
        "这个表",
        "这张表",
        "上面的表",
        "继续分析",
        "展开一下",
        "再看",
        "再查",
    )
    return _contains_any(lowered, dataset_markers)


def _looks_like_pdf_followup_request(lowered: str) -> bool:
    if not lowered.strip():
        return False
    pdf_markers = (
        "这份 pdf",
        "这个 pdf",
        "这份报告",
        "这个报告",
        "第几页",
        "第三页",
        "第四页",
        "第二部分",
        "这一页",
        "那一页",
        "这一部分",
        "那一部分",
        "核心结论",
        "行动建议",
        "重点看",
        "压成",
        "总结一下",
        "继续",
        "展开一下",
    )
    return _contains_any(lowered, pdf_markers) or bool(PAGE_REFERENCE_PATTERN.search(lowered)) or bool(SECTION_REFERENCE_PATTERN.search(lowered))


def _looks_like_bundle_followup_request(lowered: str) -> bool:
    markers = (
        "子任务",
        "展开第二个",
        "展开第一个",
        "展开第三个",
        "第一个和第三个",
        "压成一句话",
        "只展开",
    )
    return _contains_any(lowered, markers)
