from __future__ import annotations

import re
from typing import Any

from .models import IntentFrame
from .profile_registry import IntentDomainProfile, default_intent_profiles, marker_hits, profile_by_domain


_DATASET_PATH_RE = re.compile(r"([^\s,，;；:：\"'“”‘’]+?\.(?:xlsx|csv|xls|json|parquet))", re.I)
_PDF_PATH_RE = re.compile(r"([^\s,，;；:：\"'“”‘’]+?\.pdf)", re.I)


def collect_intent_frame(
    message: str,
    *,
    memory_intent: Any | None = None,
    memory_runtime_view: dict[str, Any] | None = None,
) -> IntentFrame:
    text = str(message or "").strip()
    lowered = text.lower()
    evidence = _collect_evidence(text, lowered, memory_intent=memory_intent, memory_runtime_view=memory_runtime_view)
    actions: list[str] = []
    if evidence["memory_recall"]:
        actions.append("recall_memory")
    if evidence["retrieve_knowledge"]:
        actions.append("retrieve_knowledge")
    if evidence["explicit_target"]:
        actions.append("switch_target")
    if evidence["continuation_language"]:
        actions.append("continue")
    if evidence["scope_refinement"]:
        actions.append("refine_scope")
    if evidence["delegation_work"]:
        actions.append("delegate_work")
    if not actions:
        actions.append("start_new")
    if len(actions) > 1 and "compound" not in actions:
        actions.append("compound")

    domain_hints = _domain_hints(evidence)
    strategy_candidates = _execution_strategy_candidates(evidence)
    task_complexity = "long_running" if evidence["long_task"] else "short"
    return IntentFrame(
        user_message=text,
        action_hypotheses=tuple(_dedupe(actions)),
        target_domain_hints=tuple(domain_hints),
        task_complexity=task_complexity,
        execution_strategy_candidates=tuple(strategy_candidates),
        evidence=evidence,
        diagnostics={
            "collector": "intent.signal_collector",
            "state_candidate_count": evidence["state_candidate_count"],
            "restore_candidate_count": evidence["restore_candidate_count"],
            "task_summary_candidate_count": evidence["task_summary_candidate_count"],
            "context_candidate_count": evidence["context_candidate_count"],
        },
    )


def _collect_evidence(
    text: str,
    lowered: str,
    *,
    memory_intent: Any | None,
    memory_runtime_view: dict[str, Any] | None,
) -> dict[str, Any]:
    memory_view = dict(memory_runtime_view or {})
    state_snapshot = dict(memory_view.get("state_snapshot") or {})
    context_slots = dict(state_snapshot.get("context_slots") or {})
    restore_candidates = [item for item in list(memory_view.get("restore_candidates") or []) if isinstance(item, dict)]
    context_candidates = [item for item in list(memory_view.get("context_candidates") or []) if isinstance(item, dict)]
    task_summary_candidates = [
        item
        for key in ("task_summary_refs", "recent_task_summary_refs")
        for item in list(state_snapshot.get(key) or [])
        if isinstance(item, dict)
    ]
    has_state_candidate = any(
        str(context_slots.get(key) or "").strip()
        for key in ("active_pdf", "committed_pdf", "active_dataset", "committed_dataset")
    )
    profiles = profile_by_domain()
    explicit_dataset = _DATASET_PATH_RE.search(text) is not None
    # "这份 PDF/报告" is a deictic continuation, not an explicit new target.
    explicit_pdf = _PDF_PATH_RE.search(text) is not None or _contains_any(lowered, ("打开 .pdf",))
    page_or_section = _looks_like_document_page_or_section(text)
    dataset_profile = profiles.get("dataset") or _empty_profile("dataset")
    pdf_profile = profiles.get("pdf") or _empty_profile("pdf")
    knowledge_profile = profiles.get("knowledge") or _empty_profile("knowledge")
    memory_profile = profiles.get("memory") or _empty_profile("memory")
    graph_profile = profiles.get("workflow_graph") or _empty_profile("workflow_graph")
    long_task_profile = profiles.get("long_task") or _empty_profile("long_task")
    official_source_requirement = bool(_contains_any(lowered, ("官网", "官方", "官方文档", "权威来源", "一手来源", "official docs", "official")))
    official_external_context = official_source_requirement and _contains_any(
        lowered,
        ("公告", "发布", "更新", "来源", "时间", "最近", "近期", "最新", "recent", "release", "update"),
    )
    external_requirement = official_external_context or _contains_any(
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
    dataset_language = (
        marker_hits(lowered, tuple(getattr(dataset_profile, "markers", ()) or ())) > 0
        or explicit_dataset
    )
    pdf_language = (
        marker_hits(lowered, tuple(getattr(pdf_profile, "markers", ()) or ())) > 0
        or explicit_pdf
        or page_or_section
    )
    scope_refinement = marker_hits(
        lowered,
        (
            *tuple(getattr(dataset_profile, "scope_refinement_markers", ()) or ()),
            *tuple(getattr(pdf_profile, "scope_refinement_markers", ()) or ()),
            "只基于",
            "这几条",
        ),
    ) > 0
    continuation_source_available = (
        has_state_candidate
        or bool(restore_candidates)
        or bool(task_summary_candidates)
        or _context_candidates_reference_work_object(context_candidates)
    )
    dataset_analysis_followup = (
        continuation_source_available
        and dataset_language
        and _looks_like_dataset_analysis_followup(lowered)
    )
    continuation_language = (
        continuation_source_available
        and not (weather_domain or gold_price_domain or external_requirement)
        and (
        scope_refinement
        or dataset_analysis_followup
        or _contains_any(lowered, ("继续", "再", "刚才", "这些", "这个", "这份", "回到", "展开一下", "按"))
        or page_or_section
        )
    )
    retrieve_knowledge = marker_hits(lowered, tuple(getattr(knowledge_profile, "markers", ()) or ())) > 0
    memory_recall = bool(getattr(memory_intent, "should_skip_rag", False)) or _contains_any(
        lowered,
        tuple(getattr(memory_profile, "markers", ()) or ()),
    )
    delegation_work = dataset_analysis_followup or _contains_any(
        lowered,
        tuple(
            {
                "分析",
                "汇总",
                "总结",
                "查询",
                "找出",
                "处理",
                "修复",
                "执行",
                "重跑",
                "追踪",
                "检查",
                "生成",
                "写",
                *tuple(getattr(dataset_profile, "delegation_markers", ()) or ()),
                *tuple(getattr(pdf_profile, "delegation_markers", ()) or ()),
                *tuple(getattr(knowledge_profile, "delegation_markers", ()) or ()),
                *tuple(getattr(graph_profile, "delegation_markers", ()) or ()),
                *tuple(getattr(long_task_profile, "delegation_markers", ()) or ()),
            }
        ),
    )
    long_task = marker_hits(lowered, tuple(getattr(long_task_profile, "markers", ()) or ())) > 0
    background = _contains_any(lowered, ("后台", "异步", "不用等", "跑完告诉我"))
    graph_coordination = marker_hits(lowered, tuple(getattr(graph_profile, "markers", ()) or ())) > 0
    profile_hits = {
        profile.domain_id: marker_hits(lowered, tuple(profile.markers or ()))
        for profile in default_intent_profiles()
    }
    return {
        "explicit_target": explicit_dataset or explicit_pdf,
        "explicit_dataset": explicit_dataset,
        "explicit_pdf": explicit_pdf,
        "dataset_language": dataset_language,
        "pdf_language": pdf_language,
        "page_or_section": page_or_section,
        "scope_refinement": scope_refinement,
        "dataset_analysis_followup": dataset_analysis_followup,
        "continuation_language": continuation_language,
        "retrieve_knowledge": retrieve_knowledge,
        "memory_recall": memory_recall,
        "external_requirement": external_requirement,
        "official_source_requirement": official_source_requirement,
        "freshness_requirement": freshness_requirement,
        "weather_domain": weather_domain,
        "gold_price_domain": gold_price_domain,
        "delegation_work": delegation_work,
        "long_task": long_task,
        "background": background,
        "graph_coordination": graph_coordination,
        "profile_hits": profile_hits,
        "state_candidate_count": 1 if has_state_candidate else 0,
        "restore_candidate_count": len(restore_candidates),
        "task_summary_candidate_count": len(task_summary_candidates),
        "context_candidate_count": len(context_candidates),
    }


def _domain_hints(evidence: dict[str, Any]) -> list[str]:
    hints: list[str] = []
    if evidence.get("weather_domain") or evidence.get("gold_price_domain") or evidence.get("external_requirement"):
        hints.append("realtime")
    if evidence.get("dataset_language") or evidence.get("explicit_dataset"):
        hints.append("dataset")
    if evidence.get("pdf_language") or evidence.get("explicit_pdf"):
        hints.append("pdf")
    if evidence.get("retrieve_knowledge"):
        hints.append("knowledge")
    if evidence.get("memory_recall"):
        hints.append("memory")
    if evidence.get("graph_coordination"):
        hints.append("workflow_graph")
    return _dedupe(hints)


def _execution_strategy_candidates(evidence: dict[str, Any]) -> list[str]:
    if evidence.get("weather_domain") or evidence.get("gold_price_domain") or evidence.get("external_requirement"):
        return ["single_react_loop"]
    if evidence.get("graph_coordination"):
        return ["graph_coordination_run", "professional_task_run"]
    if evidence.get("background"):
        return ["professional_task_run", "single_react_loop"]
    if evidence.get("long_task"):
        return ["professional_task_run", "single_react_loop"]
    if evidence.get("retrieve_knowledge"):
        return ["retrieval_augmented_answer", "single_react_loop"]
    if evidence.get("delegation_work") and (evidence.get("dataset_language") or evidence.get("pdf_language")):
        return ["specialist_handoff", "single_react_loop"]
    return ["single_react_loop"]


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def _looks_like_document_page_or_section(text: str) -> bool:
    normalized = str(text or "")
    if re.search(r"page\s*\d+", normalized, re.I):
        return True
    if re.search(r"第\s*[零一二三四五六七八九十百千两\d]+\s*(?:页|部分)", normalized):
        return True
    if not re.search(r"第\s*[零一二三四五六七八九十百千两\d]+\s*(?:章|节)", normalized):
        return False
    lowered = normalized.lower()
    document_markers = (
        "pdf",
        ".pdf",
        "报告",
        "白皮书",
        "文档",
        "文件",
        "材料",
        "这份",
        "这个pdf",
        "这个 pdf",
        "阅读",
        "抽取",
        "页码",
        "目录",
    )
    creative_writing_markers = (
        "小说",
        "网文",
        "写作",
        "章节",
        "正文",
        "细纲",
        "大纲",
        "卷",
        "章至",
        "第1章",
        "第 1 章",
    )
    return any(marker in lowered for marker in document_markers) and not any(
        marker in lowered for marker in creative_writing_markers
    )


def _context_candidates_reference_work_object(candidates: list[dict[str, Any]]) -> bool:
    for candidate in candidates:
        preview = str(candidate.get("rendered_preview") or "").lower()
        metadata = dict(candidate.get("metadata") or {})
        if any(token in preview for token in (".pdf", ".xlsx", ".csv", "pdf", "数据集", "表格")):
            return True
        if any(str(value or "").strip() for value in metadata.values()):
            joined = " ".join(str(value or "") for value in metadata.values()).lower()
            if any(token in joined for token in (".pdf", ".xlsx", ".csv", "dataset", "pdf")):
                return True
    return False


def _looks_like_dataset_analysis_followup(lowered: str) -> bool:
    if not lowered.strip():
        return False
    analytical_markers = (
        "哪些",
        "哪个",
        "是否",
        "有没有",
        "没有",
        "存在",
        "完全没有",
        "缺口",
        "缺货",
        "仓库",
        "库存",
        "统计",
        "汇总",
        "排名",
        "排行",
        "前五",
        "前十",
        "按仓库",
        "按部门",
        "筛选",
        "找出",
        "列出",
    )
    return _contains_any(lowered, analytical_markers)


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


def _empty_profile(domain_id: str) -> IntentDomainProfile:
    return IntentDomainProfile(domain_id=domain_id, target_domain_hint=domain_id)
