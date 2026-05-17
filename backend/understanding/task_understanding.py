from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from capability_system.units.mcp.local.pdf.analysis.catalog import PdfAnalysisCatalog
from understanding.capability_candidate_matcher import build_capability_candidates, build_capability_resolution
from understanding.capability_resolution_view import capability_resolution_view
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
    workspace_write_request: bool = False
    workspace_search_request: bool = False
    business_dataset_request: bool = False
    faq_shape: bool = False
    external_requirement: bool = False
    official_source_requirement: bool = False
    freshness_requirement: bool = False
    weather_domain: bool = False
    gold_price_domain: bool = False
    skill_authoring_request: bool = False
    mixed_direct_capabilities: bool = False
    followup_target_kind: str = ""
    followup_ordinals: list[int] = field(default_factory=list)
    followup_scope: str = ""

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
            "workspace_write_request": self.workspace_write_request,
            "workspace_search_request": self.workspace_search_request,
            "business_dataset_request": self.business_dataset_request,
            "faq_shape": self.faq_shape,
            "external_requirement": self.external_requirement,
            "official_source_requirement": self.official_source_requirement,
            "freshness_requirement": self.freshness_requirement,
            "weather_domain": self.weather_domain,
            "gold_price_domain": self.gold_price_domain,
            "skill_authoring_request": self.skill_authoring_request,
            "mixed_direct_capabilities": self.mixed_direct_capabilities,
            "followup_target_kind": self.followup_target_kind,
            "followup_ordinals": list(self.followup_ordinals),
            "followup_scope": self.followup_scope,
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
    candidate_capabilities: list[dict[str, Any]] = field(default_factory=list)
    capability_resolution: dict[str, Any] = field(default_factory=dict)


def analyze_task_understanding(
    message: str,
    memory_intent: MemoryIntent | None = None,
    *,
    active_bindings: dict[str, Any] | None = None,
) -> TaskUnderstanding:
    normalized = (message or "").strip()
    lowered = normalized.lower()

    if memory_intent is not None and memory_intent.should_skip_rag:
        understanding = TaskUnderstanding(
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
        understanding.capability_resolution = {
            "route": "memory",
            "execution_posture": "direct_memory",
            "diagnostics": {"selection_source": "memory_direct", "candidate_count": 0},
        }
        return understanding

    signals = _collect_task_signals(
        normalized,
        lowered,
        active_bindings=active_bindings,
    )

    if signals.mixed_direct_capabilities:
        understanding = _build_bounded_lookup_task(
            message=normalized,
            source_kind="mixed_sources",
            task_kind="multi_capability_request",
            modality="multi",
            confidence=0.78,
            reasons=["mixed_direct_capabilities"],
            signals=signals,
        )
        _attach_capability_matching(understanding, message=normalized)
        return understanding

    understanding = _build_fallback_task_from_signals(
        message=normalized,
        signals=signals,
    )
    _attach_capability_matching(understanding, message=normalized)
    return understanding


def _build_fallback_task_from_signals(
    *,
    message: str,
    signals: TaskSignals,
) -> TaskUnderstanding:
    workspace_write_task = _build_bounded_workspace_write_task(
        message=message,
        signals=signals,
    )
    if workspace_write_task is not None:
        return workspace_write_task
    workspace_read_task = _build_bounded_workspace_read_task(
        message=message,
        signals=signals,
    )
    if workspace_read_task is not None:
        return workspace_read_task
    workspace_search_task = _build_bounded_workspace_search_task(
        message=message,
        signals=signals,
    )
    if workspace_search_task is not None:
        return workspace_search_task
    bundle_followup_task = _build_bundle_ordinal_followup_task(
        message=message,
        signals=signals,
    )
    if bundle_followup_task is not None:
        return bundle_followup_task
    dataset_task = _build_bounded_dataset_task(
        message=message,
        signals=signals,
    )
    if dataset_task is not None:
        return dataset_task
    pdf_task = _build_bounded_pdf_task(
        message=message,
        signals=signals,
    )
    if pdf_task is not None:
        return pdf_task
    web_task = _build_bounded_web_task(
        message=message,
        signals=signals,
    )
    if web_task is not None:
        return web_task
    if signals.skill_authoring_request:
        return _build_bounded_skill_authoring_task(
            message=message,
            signals=signals,
        )
    if (
        signals.faq_shape
        and not signals.external_requirement
        and not signals.explicit_dataset_path
        and not signals.explicit_pdf_path
    ):
        return _build_bounded_lookup_task(
            message=message,
            source_kind="knowledge_base",
            task_kind="faq_explanation",
            modality="general",
            confidence=0.9,
            reasons=["faq_problem_shape"],
            direct_route_reason="faq_problem_shape",
            signals=signals,
        )
    if signals.local_knowledge_scope and not signals.freshness_requirement:
        return _build_bounded_lookup_task(
            message=message,
            source_kind="knowledge_base",
            task_kind="knowledge_lookup",
            modality="general",
            confidence=0.8,
            reasons=["explicit_knowledge_scope"],
            direct_route_reason="explicit_knowledge_scope",
            signals=signals,
        )
    return _build_general_conversation_task(
        message=message,
        signals=signals,
        confidence=0.42,
        reasons=["fallback_general_conversation"],
    )


def _build_general_conversation_task(
    *,
    message: str,
    signals: TaskSignals,
    task_kind: str = "general_conversation",
    modality: str = "general",
    confidence: float,
    reasons: list[str],
) -> TaskUnderstanding:
    return TaskUnderstanding(
        intent="general_query",
        source_kind="conversation",
        task_kind=task_kind,
        modality=modality,
        route_hint="agent",
        preferred_skill=None,
        capability_requests=[],
        parameters={"query": message},
        execution_posture="bounded_agent",
        direct_route_reason="conversation_fallback",
        should_skip_rag=True,
        confidence=confidence,
        reasons=reasons,
        structural_signals=signals.to_dict(),
    )


def _build_bundle_ordinal_followup_task(
    *,
    message: str,
    signals: TaskSignals,
) -> TaskUnderstanding | None:
    if signals.followup_target_kind != "bundle_ordinals":
        return None
    understanding = _build_bounded_lookup_task(
        message=message,
        source_kind="bundle_result",
        task_kind="bundle_followup",
        modality="bundle",
        confidence=0.93,
        reasons=["bundle_ordinal_followup"],
        direct_route_reason="bundle_ordinal_followup",
        route_hint="bundle_followup",
        signals=signals,
    )
    understanding.parameters = {
        "query": message,
        "followup_ordinals": list(signals.followup_ordinals),
        "followup_scope": signals.followup_scope or "bundle_result",
    }
    understanding.capability_requests = []
    return understanding


def _build_bounded_workspace_read_task(
    *,
    message: str,
    signals: TaskSignals,
) -> TaskUnderstanding | None:
    if not signals.explicit_workspace_path or not signals.workspace_read_request:
        return None
    lowered_path = signals.explicit_workspace_path.lower()
    modality = "code" if lowered_path.endswith((".py", ".ts", ".tsx", ".js", ".jsx", ".sh", ".ps1", ".sql")) else "text"
    understanding = _build_bounded_lookup_task(
        message=message,
        source_kind="workspace",
        task_kind="workspace_file_read",
        modality=modality,
        confidence=0.95,
        reasons=["explicit_workspace_file_anchor"],
        direct_route_reason="explicit_workspace_file_anchor",
        route_hint="workspace_read",
        signals=signals,
    )
    understanding.capability_requests = ["workspace_read"]
    understanding.parameters = {"path": signals.explicit_workspace_path}
    understanding.candidate_tools = ["read_file"]
    return understanding


def _build_bounded_workspace_write_task(
    *,
    message: str,
    signals: TaskSignals,
) -> TaskUnderstanding | None:
    if not signals.explicit_workspace_path or not signals.workspace_write_request:
        return None
    lowered_path = signals.explicit_workspace_path.lower()
    modality = "code" if lowered_path.endswith((".py", ".ts", ".tsx", ".js", ".jsx", ".sh", ".ps1", ".sql")) else "text"
    understanding = _build_bounded_lookup_task(
        message=message,
        source_kind="workspace",
        task_kind="workspace_file_write",
        modality=modality,
        confidence=0.95,
        reasons=["explicit_workspace_write_anchor"],
        direct_route_reason="explicit_workspace_write_anchor",
        route_hint="workspace_write",
        signals=signals,
    )
    understanding.capability_requests = ["workspace_write"]
    understanding.parameters = {"path": signals.explicit_workspace_path}
    understanding.candidate_tools = ["write_file"]
    return understanding


def _build_bounded_workspace_search_task(
    *,
    message: str,
    signals: TaskSignals,
) -> TaskUnderstanding | None:
    if not signals.workspace_search_request or signals.external_requirement:
        return None
    understanding = _build_bounded_lookup_task(
        message=message,
        source_kind="workspace",
        task_kind="workspace_file_search",
        modality="workspace",
        confidence=0.9,
        reasons=["workspace_search_request"],
        direct_route_reason="workspace_search_request",
        route_hint="workspace_path_search",
        signals=signals,
    )
    understanding.capability_requests = ["workspace_path_search"]
    understanding.parameters = {"query": message}
    understanding.candidate_tools = ["search_files"]
    return understanding


def _build_bounded_web_task(
    *,
    message: str,
    signals: TaskSignals,
) -> TaskUnderstanding | None:
    if not (
        signals.external_requirement
        or signals.official_source_requirement
        or signals.freshness_requirement
        or signals.weather_domain
        or signals.gold_price_domain
    ):
        return None
    capability_requests: list[str] = []
    reasons: list[str] = []
    source_kind = "external_web"
    task_kind = "web_lookup"
    modality = "web"
    confidence = 0.93
    if signals.weather_domain:
        capability_requests.append("weather")
        reasons.append("weather_realtime_task")
        task_kind = "realtime_lookup"
        modality = "realtime"
        confidence = 0.96
    if signals.gold_price_domain:
        capability_requests.append("gold_price")
        reasons.append("gold_price_realtime_task")
        task_kind = "realtime_lookup"
        modality = "realtime"
        confidence = 0.95
    if signals.external_requirement or signals.official_source_requirement:
        reasons.append("explicit_external_constraint")
    capability_requests.append("latest_information")
    if signals.freshness_requirement and not reasons:
        reasons.append("freshness_aware_lookup")
        task_kind = "current_information_lookup"
        modality = "realtime"
        confidence = 0.84
    if not reasons:
        reasons.append("explicit_external_constraint")
    understanding = _build_bounded_lookup_task(
        message=message,
        source_kind=source_kind,
        task_kind=task_kind,
        modality=modality,
        confidence=confidence,
        reasons=reasons,
        direct_route_reason=reasons[0],
        route_hint="realtime_network",
        signals=signals,
    )
    understanding.capability_requests = _dedupe(capability_requests)
    understanding.parameters = {"query": message}
    understanding.candidate_tools = ["web_search"]
    return understanding


def _build_bounded_dataset_task(
    *,
    message: str,
    signals: TaskSignals,
) -> TaskUnderstanding | None:
    if signals.weather_domain or signals.gold_price_domain:
        return None
    if signals.followup_target_kind == "bundle_ordinals":
        return None
    followup_dataset_request = (
        bool(signals.bound_dataset_path)
        and not signals.explicit_pdf_path
        and not signals.explicit_workspace_path
        and signals.followup_target_kind in {"active_dataset", "active_subset"}
    )
    bundle_followup_request = _looks_like_bundle_followup_request(message.lower())
    if not signals.explicit_dataset_path and not signals.business_dataset_request and not followup_dataset_request:
        if not (bundle_followup_request and signals.bound_dataset_path):
            return None
    parameters: dict[str, Any] = {"query": message}
    reasons = ["business_dataset_intent"]
    if signals.explicit_dataset_path:
        reasons = ["explicit_dataset_anchor"]
        parameters["path"] = signals.explicit_dataset_path
    elif followup_dataset_request:
        reasons = ["active_subset_followup" if signals.followup_target_kind == "active_subset" else "bound_dataset_followup"]
        parameters["path"] = signals.bound_dataset_path
        if signals.followup_target_kind == "active_subset" and signals.followup_scope:
            parameters["followup_scope"] = signals.followup_scope
    elif bundle_followup_request and signals.bound_dataset_path:
        reasons = ["bundle_subtask_followup"]
        parameters["path"] = signals.bound_dataset_path
    elif signals.bound_dataset_path:
        parameters["path"] = signals.bound_dataset_path

    understanding = _build_bounded_lookup_task(
        message=message,
        source_kind="dataset",
        task_kind="dataset_query",
        modality="table",
        confidence=0.96 if signals.explicit_dataset_path else 0.91 if (followup_dataset_request or bundle_followup_request) else 0.86,
        reasons=reasons,
        direct_route_reason=reasons[0],
        signals=signals,
    )
    understanding.parameters = parameters
    understanding.capability_requests = ["dataset_analysis"]
    return understanding


def _build_bounded_pdf_task(
    *,
    message: str,
    signals: TaskSignals,
) -> TaskUnderstanding | None:
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
    direct_route_reason = (
        "explicit_pdf_anchor"
        if signals.explicit_pdf_path
        else "bound_pdf_followup"
        if followup_pdf_request
        else "document_scope_anchor"
    )
    understanding = _build_bounded_lookup_task(
        message=message,
        source_kind="document",
        task_kind=task_kind,
        modality="pdf",
        confidence=0.94 if signals.explicit_pdf_path else 0.91 if followup_pdf_request else 0.87,
        reasons=reasons,
        direct_route_reason=direct_route_reason,
        signals=signals,
    )
    understanding.parameters = parameters
    understanding.capability_requests = ["document_analysis"]
    return understanding


def _build_bounded_skill_authoring_task(
    *,
    message: str,
    signals: TaskSignals,
) -> TaskUnderstanding:
    lowered = message.lower()
    task_kind = "capability_authoring"
    reasons = ["skill_authoring_intent"]
    if _contains_any(lowered, ("创建", "新建", "新增", "生成", "create ", "new skill", "add skill")):
        task_kind = "skill_create"
        reasons.append("skill_create_request")
    elif _contains_any(lowered, ("更新", "修改", "改写", "调整", "优化", "补齐", "update ", "modify ", "rewrite ")):
        task_kind = "skill_update"
        reasons.append("skill_update_request")
    elif _contains_any(lowered, ("检查", "审查", "review", "validate", "是否适合")):
        task_kind = "skill_update"
        reasons.append("skill_review_request")
    elif _contains_any(lowered, ("prompt", "提示词", "调用契约", "触发条件", "prompt contract")):
        task_kind = "prompt_contract_design"
        reasons.append("prompt_contract_request")

    modality = "markdown" if _contains_any(lowered, ("skill.md", "markdown", ".md")) else "workflow"
    understanding = _build_bounded_lookup_task(
        message=message,
        source_kind="capability_system",
        task_kind=task_kind,
        modality=modality,
        confidence=0.93,
        reasons=_dedupe(reasons),
        direct_route_reason="skill_authoring_intent",
        signals=signals,
    )
    capability_requests = ["skill-authoring", "capability-design"]
    if task_kind == "prompt_contract_design" or _contains_any(lowered, ("prompt", "提示词", "调用契约", "触发条件")):
        capability_requests.append("prompt-contract")
    if _contains_any(lowered, ("检查", "审查", "review", "validate", "校验")):
        capability_requests.append("validation")
    understanding.capability_requests = _dedupe(capability_requests)
    return understanding


def _attach_capability_matching(understanding: TaskUnderstanding, *, message: str) -> None:
    candidates = build_capability_candidates(
        message=message,
        route_hint=understanding.route_hint,
        execution_posture=understanding.execution_posture,
        preferred_skill=str(understanding.preferred_skill or ""),
        candidate_tools=list(understanding.candidate_tools),
        capability_requests=list(understanding.capability_requests),
        task_kind=understanding.task_kind,
        source_kind=understanding.source_kind,
        modality=understanding.modality,
    )
    understanding.candidate_capabilities = [item.to_dict() for item in candidates]
    understanding.capability_resolution = build_capability_resolution(
        route_hint=understanding.route_hint,
        execution_posture=understanding.execution_posture,
        preferred_skill=str(understanding.preferred_skill or ""),
        candidate_tools=list(understanding.candidate_tools),
        capability_requests=list(understanding.capability_requests),
        candidates=candidates,
    ).to_dict()
    _apply_capability_resolution_state(understanding)


def _apply_capability_resolution_state(understanding: TaskUnderstanding) -> None:
    resolution = capability_resolution_view(
        {
            "route_hint": understanding.route_hint,
            "execution_posture": understanding.execution_posture,
            "preferred_skill": understanding.preferred_skill,
            "candidate_tools": list(understanding.candidate_tools),
            "capability_resolution": dict(understanding.capability_resolution or {}),
        }
    )
    if resolution.route:
        understanding.route_hint = resolution.route
    if resolution.execution_posture:
        understanding.execution_posture = resolution.execution_posture
    if resolution.execution_posture in {"direct_mcp", "builtin_tool_lane", "direct_memory"}:
        understanding.should_skip_rag = True
    if resolution.preferred_skill:
        understanding.preferred_skill = resolution.preferred_skill
    if resolution.tool_name and resolution.tool_name not in understanding.candidate_tools:
        understanding.candidate_tools = [resolution.tool_name, *list(understanding.candidate_tools)]


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
    workspace_read_request = (
        explicit_workspace_path != ""
        and _looks_like_workspace_read_request(lowered)
        and not _looks_like_workspace_write_request(lowered)
    )
    workspace_write_request = explicit_workspace_path != "" and _looks_like_workspace_write_request(lowered)
    workspace_search_request = _looks_like_workspace_search_request(lowered)
    business_dataset_request = _looks_like_business_dataset_request(lowered)
    faq_shape = _looks_like_faq_problem(lowered)
    official_source_requirement = bool(explicit_urls) or _contains_any(
        lowered,
        ("官网", "官方", "官方文档", "权威来源", "一手来源", "official docs", "official"),
    )
    official_external_context = official_source_requirement and _contains_any(
        lowered,
        ("公告", "发布", "更新", "来源", "时间", "最近", "近期", "最新", "recent", "release", "update"),
    )
    external_requirement = bool(explicit_urls) or official_external_context or _contains_any(
        lowered,
        ("联网", "官网", "官方文档", "web search", "上网", "网上查", "look it up", "news"),
    )
    freshness_requirement = _contains_any(
        lowered,
        ("今年", "现在", "目前", "还在", "最新", "最新状态", "实时", "最近", "近期", "today", "latest", "current", "currently", "recent"),
    )
    weather_domain = _contains_any(
        lowered,
        ("weather", "forecast", "temperature", "天气", "气温", "温度", "降雨", "下雨", "风速", "风向", "预报"),
    )
    gold_price_domain = _contains_any(
        lowered,
        ("gold price", "spot gold", "xau", "xauusd", "黄金", "金价", "现货黄金", "黄金价格"),
    )
    skill_authoring_request = _looks_like_skill_authoring_request(message, lowered)
    binding_view = _normalize_active_bindings(active_bindings)
    followup_resolution = _resolve_followup_target(lowered, binding_view)
    if (
        followup_resolution["target_kind"] != "bundle_ordinals"
        and (explicit_dataset_path or explicit_pdf_path or explicit_workspace_path or weather_domain or gold_price_domain or external_requirement)
    ):
        followup_resolution = {"target_kind": "", "ordinals": [], "scope": ""}

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
    if skill_authoring_request:
        anchor_kinds.append("skill_authoring")
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
        workspace_write_request=workspace_write_request,
        workspace_search_request=workspace_search_request,
        business_dataset_request=business_dataset_request,
        faq_shape=faq_shape,
        external_requirement=external_requirement,
        official_source_requirement=official_source_requirement,
        freshness_requirement=freshness_requirement,
        weather_domain=weather_domain,
        gold_price_domain=gold_price_domain,
        skill_authoring_request=skill_authoring_request,
        followup_target_kind=followup_resolution["target_kind"],
        followup_ordinals=list(followup_resolution["ordinals"]),
        followup_scope=followup_resolution["scope"],
    )
    signals.mixed_direct_capabilities = _has_mixed_direct_capabilities(signals)
    return signals


def _build_bounded_lookup_task(
    *,
    message: str,
    source_kind: str,
    task_kind: str,
    modality: str,
    confidence: float,
    reasons: list[str],
    direct_route_reason: str = "",
    route_hint: str = "agent",
    signals: TaskSignals,
) -> TaskUnderstanding:
    capability_requests = _build_capability_requests(
        signals,
        include_default_knowledge=True,
    )
    effective_direct_route_reason = direct_route_reason or "unresolved_lookup"
    if not direct_route_reason and "latest_information" in capability_requests:
        effective_direct_route_reason = "freshness_aware_lookup"
    return TaskUnderstanding(
        intent="general_query",
        source_kind=source_kind,
        task_kind=task_kind,
        modality=modality,
        route_hint=route_hint,
        preferred_skill=None,
        capability_requests=capability_requests,
        parameters={"query": message},
        execution_posture="bounded_agent",
        direct_route_reason=effective_direct_route_reason,
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


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


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


def _looks_like_workspace_write_request(lowered: str) -> bool:
    return _contains_any(
        lowered,
        (
            "write_file",
            "写入",
            "写到",
            "写进",
            "生成",
            "产出",
            "创建",
            "保存到",
            "输出到",
            "write ",
            "create ",
            "save to",
            "output to",
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


def _looks_like_skill_authoring_request(message: str, lowered: str) -> bool:
    normalized = (message or "").strip()
    if not normalized:
        return False
    has_skill_object = _contains_any(
        lowered,
        (
            "skill",
            "skill.md",
            "skills",
            "能力系统",
            "能力注册",
            "能力编写",
            "能力创建",
            "prompt view",
            "prompt contract",
        ),
    )
    has_authoring_intent = _contains_any(
        lowered,
        (
            "创建",
            "新建",
            "新增",
            "生成",
            "编写",
            "写一个",
            "做一个",
            "更新",
            "修改",
            "改写",
            "调整",
            "优化",
            "补齐",
            "检查",
            "审查",
            "校验",
            "设计",
            "注册",
            "触发",
            "使用条件",
            "提示词",
            "create ",
            "add ",
            "new ",
            "update ",
            "modify ",
            "rewrite ",
            "review ",
            "validate ",
        ),
    )
    return has_skill_object and has_authoring_intent


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
    if signals.explicit_workspace_path and signals.workspace_write_request:
        requests.append("workspace_write")
    if signals.workspace_search_request:
        requests.append("workspace_search")
    if signals.weather_domain:
        requests.extend(["weather", "latest_information"])
    if signals.gold_price_domain:
        requests.extend(["gold_price", "latest_information"])
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
            for item in ("dataset_analysis", "document_analysis", "workspace_read", "workspace_write", "latest_information")
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
        "完全没有缺口",
        "没有缺口",
        "缺口",
        "是否存在",
        "如果没有",
        "只基于刚才",
        "刚才这",
        "前五名",
        "这些员工",
        "这些人",
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


def _resolve_followup_target(lowered: str, binding_view: dict[str, Any]) -> dict[str, Any]:
    ordinals = _extract_followup_ordinals(lowered)
    if ordinals:
        return {"target_kind": "bundle_ordinals", "ordinals": ordinals, "scope": "bundle_result"}
    if _looks_like_active_subset_followup(lowered):
        if str(binding_view.get("bound_dataset_path") or "").strip():
            return {"target_kind": "active_subset", "ordinals": [], "scope": "active_subset"}
        if str(binding_view.get("bound_pdf_path") or "").strip():
            return {"target_kind": "active_subset", "ordinals": [], "scope": "active_subset"}
    if str(binding_view.get("bound_dataset_path") or "").strip() and _looks_like_dataset_followup_request(lowered):
        return {"target_kind": "active_dataset", "ordinals": [], "scope": "active_object"}
    if str(binding_view.get("bound_pdf_path") or "").strip() and _looks_like_pdf_followup_request(lowered):
        return {"target_kind": "active_pdf", "ordinals": [], "scope": "active_object"}
    return {"target_kind": "", "ordinals": [], "scope": ""}


def _looks_like_active_subset_followup(lowered: str) -> bool:
    markers = (
        "只基于刚才",
        "基于刚才",
        "刚才这",
        "刚才的",
        "这前五",
        "这几条",
        "这些人",
        "这些员工",
        "上面这",
        "上面的",
        "不要回到全表",
        "不要全表",
        "不要重算",
    )
    return _contains_any(lowered, markers)


def _extract_followup_ordinals(lowered: str) -> list[int]:
    mapping = {
        "第一个": 1,
        "第一项": 1,
        "第1个": 1,
        "第1项": 1,
        "第二个": 2,
        "第二项": 2,
        "第2个": 2,
        "第2项": 2,
        "第三个": 3,
        "第三项": 3,
        "第3个": 3,
        "第3项": 3,
    }
    ordinals: list[int] = []
    if "子任务" not in lowered and not any(marker in lowered for marker in mapping):
        return []
    for marker, ordinal in mapping.items():
        if marker in lowered and ordinal not in ordinals:
            ordinals.append(ordinal)
    excluded: set[int] = set()
    if "不要再提第二个" in lowered or "不要提第二个" in lowered or "不提第二个" in lowered:
        excluded.add(2)
    if "不要再提第2个" in lowered or "不要提第2个" in lowered or "不提第2个" in lowered:
        excluded.add(2)
    if excluded:
        ordinals = [ordinal for ordinal in ordinals if ordinal not in excluded]
    return ordinals
