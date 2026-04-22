from __future__ import annotations

import re

from query.output_models import OutputCandidate, OutputDecision


_PROCEDURAL_PREFIX_RE = re.compile(
    r"^(?:我(?:来|将|会|先|需要先|准备|打算)|让我|接下来(?:我)?)"
    r"(?:检索|搜索|查看|检查|使用|调用|尝试|读取|分析|确认|整理|改写).+",
    re.IGNORECASE,
)
_SEARCH_CALL_RE = re.compile(
    r"(?:search_knowledge|searchKnowledge|retrieve|web_search)\s*(?:\(|query=)",
    re.IGNORECASE,
)
_CONCLUSION_RE = re.compile(
    r"(?:\*\*结论[:：]?\*\*|结论[:：])\s*(.+)",
    re.IGNORECASE | re.DOTALL,
)
_RAW_PDF_BROWSE_RE = re.compile(
    r"Source:\s*.+?\nMode:\s*PDF browse\b.*?(?:Relevant pages:|\[P\d+\]\s*score=)",
    re.IGNORECASE | re.DOTALL,
)
_RAW_PDF_PAGE_RE = re.compile(
    r"Source:\s*.+?\nMode:\s*PDF page read\b",
    re.IGNORECASE,
)
_PDF_SUMMARY_RE = re.compile(
    r"Summary:\s*(.+?)(?:\n\s*Page snippet:|\Z)",
    re.IGNORECASE | re.DOTALL,
)
_PAGE_IDS_RE = re.compile(r"\[P(\d+)\]")
_MARKDOWN_BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")
_NOISY_WHITESPACE_RE = re.compile(r"\s+")
_STRUCTURED_DATA_HINT_RE = re.compile(r"(?:数据源[:：]|查询模式[:：]|前\s*\d+\s*项[:：])")
_WEATHER_HINT_RE = re.compile(r"(?:当前天气|温度[:：]|湿度[:：]|风速[:：])")
_FINANCE_HINT_RE = re.compile(r"(?:黄金|金价|price)")


def normalize_candidate_text(text: str) -> str:
    normalized = str(text or "").replace("\r\n", "\n").strip()
    normalized = _MARKDOWN_BOLD_RE.sub(r"\1", normalized)
    return normalized.strip()


def looks_like_progress_text(text: str) -> bool:
    normalized = normalize_candidate_text(text)
    if not normalized:
        return False
    lines = [line.strip() for line in normalized.splitlines() if line.strip()]
    if not lines:
        return False
    if any(_SEARCH_CALL_RE.search(line) for line in lines):
        non_search = [_SEARCH_CALL_RE.sub("", line).strip(" .。:：-") for line in lines]
        if not any(item for item in non_search if item and not _PROCEDURAL_PREFIX_RE.match(item)):
            return True
    return all(_PROCEDURAL_PREFIX_RE.match(line) for line in lines)


def extract_explicit_answer(text: str) -> str:
    normalized = normalize_candidate_text(text)
    if not normalized:
        return ""
    match = _CONCLUSION_RE.search(normalized)
    if not match:
        return ""
    answer = match.group(1).strip()
    answer = re.split(r"\n\s*(?:岩，|注[:：]|备注[:：])", answer, maxsplit=1)[0].strip()
    return answer


def extract_tool_visible_summary(text: str, tool_name: str) -> str:
    normalized = normalize_candidate_text(text)
    if not normalized:
        return ""
    if tool_name == "pdf_analysis":
        match = _PDF_SUMMARY_RE.search(normalized)
        if match:
            summary = _collapse_inline_whitespace(match.group(1))
            return summary.strip(" .。")
        if _RAW_PDF_BROWSE_RE.search(normalized):
            pages = _PAGE_IDS_RE.findall(normalized)
            if pages:
                selected = "、".join(f"P{page}" for page in pages[:3])
                return f"已定位到与问题最相关的页面：{selected}。当前工具返回的是原始检索片段，尚未形成可靠摘要。"
            return "已定位到相关 PDF 内容，但当前工具返回的是原始检索片段，尚未形成可靠摘要。"
        if _RAW_PDF_PAGE_RE.search(normalized):
            stripped = _remove_pdf_scaffolding(normalized)
            return _collapse_inline_whitespace(stripped)
    if tool_name == "structured_data_analysis" and _STRUCTURED_DATA_HINT_RE.search(normalized):
        return _collapse_inline_whitespace(normalized)
    if tool_name == "get_weather" and _WEATHER_HINT_RE.search(normalized):
        return _collapse_inline_whitespace(normalized)
    if tool_name == "get_gold_price" and _FINANCE_HINT_RE.search(normalized):
        return _collapse_inline_whitespace(normalized)
    return ""


def looks_like_raw_tool_output(text: str, tool_name: str) -> bool:
    normalized = normalize_candidate_text(text)
    if not normalized:
        return False
    if tool_name == "pdf_analysis":
        return bool(_RAW_PDF_BROWSE_RE.search(normalized))
    if tool_name == "structured_data_analysis":
        return normalized.startswith("{") or normalized.startswith("[")
    return False


def classify_output_candidate(
    *,
    text: str,
    route: str,
    source: str,
    tool_name: str = "",
    allow_unlabeled_answer: bool = True,
) -> OutputCandidate | None:
    normalized = normalize_candidate_text(text)
    if not normalized:
        return None
    explicit_answer = extract_explicit_answer(normalized)
    if explicit_answer:
        return OutputCandidate(
            channel="answer_candidate",
            text=explicit_answer,
            source=source,
            route=route,
            tool_name=tool_name,
            priority_hint=100,
        )
    tool_summary = extract_tool_visible_summary(normalized, tool_name)
    if tool_summary:
        return OutputCandidate(
            channel="tool_visible_summary",
            text=tool_summary,
            source=source,
            route=route,
            tool_name=tool_name,
            priority_hint=80,
        )
    if looks_like_progress_text(normalized):
        return OutputCandidate(
            channel="progress_text",
            text=normalized,
            source=source,
            route=route,
            tool_name=tool_name,
            priority_hint=0,
        )
    if looks_like_raw_tool_output(normalized, tool_name):
        return OutputCandidate(
            channel="tool_raw_output",
            text=normalized,
            source=source,
            route=route,
            tool_name=tool_name,
            priority_hint=10,
        )
    if not allow_unlabeled_answer:
        return None
    return OutputCandidate(
        channel="answer_candidate",
        text=normalized,
        source=source,
        route=route,
        tool_name=tool_name,
        priority_hint=50,
    )


def build_output_decision(
    *,
    candidates: list[OutputCandidate],
    route: str,
    user_message: str,
    tool_name: str = "",
    retrieval_results: list[dict[str, object]] | None = None,
    leak_flags: list[str] | None = None,
) -> OutputDecision:
    leak_flags = list(leak_flags or [])
    ranked = sorted(
        candidates,
        key=lambda item: (item.priority_hint, len(item.text.strip())),
        reverse=True,
    )
    preferred = next(
        (
            item
            for item in ranked
            if item.channel in {"answer_candidate", "tool_visible_summary"}
            and item.text.strip()
        ),
        None,
    )
    if preferred is not None:
        rejected = [item for item in ranked if item is not preferred]
        return OutputDecision(
            canonical_answer=preferred.text.strip(),
            selected_channel=preferred.channel,
            selected_source=preferred.source,
            rejected_candidates=rejected,
            leak_flags=leak_flags,
        )
    fallback = build_route_fallback(
        route=route,
        user_message=user_message,
        tool_name=tool_name,
        retrieval_results=retrieval_results,
        rejected_candidates=ranked,
    )
    return OutputDecision(
        canonical_answer=fallback[0],
        selected_channel="fallback_answer",
        selected_source="fallback_policy",
        rejected_candidates=ranked,
        leak_flags=leak_flags,
        fallback_reason=fallback[1],
    )


def build_route_fallback(
    *,
    route: str,
    user_message: str,
    tool_name: str,
    retrieval_results: list[dict[str, object]] | None,
    rejected_candidates: list[OutputCandidate],
) -> tuple[str, str]:
    has_retrieval = bool(list(retrieval_results or []))
    if route == "rag":
        if not has_retrieval:
            return ("当前本地知识库没有检到足够相关材料，无法可靠回答这个问题。", "rag_no_retrieval")
        return ("已检索到相关资料，但当前模型尚未产出可直接展示的结论。", "rag_missing_answer")
    if route == "memory":
        return ("当前没有足够的会话记忆可直接回答这个问题。", "memory_missing_answer")
    if tool_name == "pdf_analysis":
        browse_candidate = next(
            (item for item in rejected_candidates if item.channel == "tool_raw_output"),
            None,
        )
        if browse_candidate is not None:
            pages = _PAGE_IDS_RE.findall(browse_candidate.text)
            if pages:
                selected = "、".join(f"P{page}" for page in pages[:3])
                return (
                    f"已定位到与当前问题最相关的 PDF 页面：{selected}，但工具尚未形成可直接展示的摘要。",
                    "pdf_raw_browse_fallback",
                )
        return ("已读取这份 PDF，但当前工具尚未形成可直接展示的摘要。", "pdf_missing_summary")
    if tool_name:
        return (f"工具 `{tool_name}` 已执行，但当前结果尚未形成可直接展示的答案。", "tool_missing_summary")
    if user_message.strip():
        return ("当前尚未形成可直接展示的结论，请继续细化问题或提供更多上下文。", "generic_missing_answer")
    return ("当前没有可展示的答案。", "empty_answer")


def _collapse_inline_whitespace(text: str) -> str:
    return _NOISY_WHITESPACE_RE.sub(" ", text).strip()


def _remove_pdf_scaffolding(text: str) -> str:
    cleaned = re.sub(r"Source:\s*.+?(?:\n|$)", "", text, flags=re.IGNORECASE)
    cleaned = re.sub(r"Mode:\s*PDF page read(?:\n|$)", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"Target page:\s*P\d+(?:\n|$)", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"Heading candidate:\s*.+?(?:\n|$)", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"Keywords:\s*.+?(?:\n|$)", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"Page snippet:\s*.+", "", cleaned, flags=re.IGNORECASE | re.DOTALL)
    return cleaned.strip()
