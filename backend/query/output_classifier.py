from __future__ import annotations

import re

from pdf_agent import PDFCanonicalResult
from query.output_models import OutputCandidate, OutputDecision


_PROCEDURAL_PREFIX_RE = re.compile(
    r"^(?:岩[，,\s]*)?(?:我(?:(?:来|将|会|准备|打算)(?:先)?|先(?:来)?|需要先)|让我(?:先)?|接下来(?:我)?(?:先)?)"
    r"(?:检索|搜索|查看|检查|使用|调用|尝试|读取|分析|确认|核实|整理|改写|查询|执行).+",
    re.IGNORECASE,
)
_PROCEDURAL_PROMISE_RE = re.compile(
    r"^(?:岩[，,\s]*)?(?:我(?:(?:来|将|会|准备|打算)(?:先)?|先(?:来)?|需要先)|让我(?:先)?|接下来(?:我)?(?:先)?|稍等(?:我)?)(?:去)?"
    r"(?:检索|搜索|查看|检查|读取|确认|核实|查询|执行)(?:一下|一遍|下)?(?:最新状态|最新情况)?[\s。.!！…]*$"
    r"|^(?:岩[，,\s]*)?(?:我(?:(?:来|将|会|准备|打算)(?:先)?|先(?:来)?|需要先)|让我(?:先)?|接下来(?:我)?(?:先)?|稍等(?:我)?)"
    r".{0,24}(?:检索|搜索|查看|检查|读取|确认|核实|查询|执行)(?:一下|一遍|下)?(?:最新状态|最新情况)?.*$",
    re.IGNORECASE,
)
_TOOL_CLAIM_WITHOUT_RECEIPT_RE = re.compile(
    r"^(?:岩[，,\s]*)?(?:我(?:已经|刚刚|刚才)?(?:查到|查询了|检索了|搜索了|确认了|核实了)|我这边(?:已经)?(?:查到|确认到|核实到)).+",
    re.IGNORECASE,
)
_SUBTASK_STATUS_PROMISE_RE = re.compile(
    r"^(?:\d+[.)、]\s*)?[^:：\n]{1,40}[:：]\s*(?:正在(?:查询|检索|搜索|处理)|稍后(?:给你|给您)?(?:结果|回复)?|待(?:查询|确认|处理)|稍等).*$",
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
    if looks_like_procedural_promise_text(text):
        return True
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


def looks_like_procedural_promise_text(text: str) -> bool:
    normalized = normalize_candidate_text(text)
    if not normalized:
        return False
    lines = [line.strip() for line in normalized.splitlines() if line.strip()]
    if not lines:
        return False
    action_tokens = ("查询", "检索", "搜索", "查看", "检查", "读取", "确认", "核实", "执行")
    promise_tokens = ("我", "现在", "立即", "马上", "这就", "稍等", "接下来", "让我")
    for line in lines:
        if _PROCEDURAL_PROMISE_RE.match(line):
            continue
        if _SUBTASK_STATUS_PROMISE_RE.match(line):
            continue
        compact = re.sub(r"\s+", "", line)
        compact = re.sub(r"^岩[，,]*", "", compact)
        if not any(token in compact for token in action_tokens):
            return False
        if not any(token in compact for token in promise_tokens):
            return False
    return True


def looks_like_tool_claim_without_receipt(text: str) -> bool:
    normalized = normalize_candidate_text(text)
    if not normalized:
        return False
    first_line = next((line.strip() for line in normalized.splitlines() if line.strip()), "")
    if not first_line:
        return False
    compact = re.sub(r"\s+", "", first_line)
    compact = re.sub(r"^岩[，,]*", "", compact)
    if bool(_TOOL_CLAIM_WITHOUT_RECEIPT_RE.match(first_line)):
        return True
    return any(
        compact.startswith(prefix)
        for prefix in (
            "我已经查到",
            "我刚刚查到",
            "我刚才查到",
            "我已经查询了",
            "我刚刚查询了",
            "我已经检索了",
            "我刚刚检索了",
            "我已经确认了",
            "我刚刚确认了",
            "我已经核实了",
            "我刚刚核实了",
        )
    )


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
        canonical_result = PDFCanonicalResult.from_tool_output(normalized)
        if canonical_result is not None:
            if canonical_result.ok and canonical_result.summary.strip():
                return canonical_result.summary.strip()
            return ""
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
        if PDFCanonicalResult.from_tool_output(normalized) is not None:
            return False
        return False
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
    has_tool_receipt: bool = True,
) -> OutputCandidate | None:
    normalized = normalize_candidate_text(text)
    if not normalized:
        return None
    if looks_like_procedural_promise_text(normalized):
        return OutputCandidate(
            channel="progress_text" if has_tool_receipt else "procedural_promise",
            text=normalized,
            source=source,
            route=route,
            tool_name=tool_name,
            priority_hint=0,
        )
    if not has_tool_receipt and looks_like_tool_claim_without_receipt(normalized):
        return OutputCandidate(
            channel="tool_claim_without_receipt",
            text=normalized,
            source=source,
            route=route,
            tool_name=tool_name,
            priority_hint=0,
        )
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
        metadata: dict[str, object] = {}
        if tool_name == "pdf_analysis":
            canonical_result = PDFCanonicalResult.from_tool_output(normalized)
            if canonical_result is not None:
                metadata["pdf_pages"] = list(canonical_result.pages)
                metadata["pdf_mode"] = canonical_result.effective_mode
        return OutputCandidate(
            channel="tool_visible_summary",
            text=tool_summary,
            source=source,
            route=route,
            tool_name=tool_name,
            priority_hint=80,
            metadata=metadata,
        )
    if tool_name == "pdf_analysis":
        canonical_result = PDFCanonicalResult.from_tool_output(normalized)
        if canonical_result is not None:
            return OutputCandidate(
                channel="tool_raw_output",
                text=normalized,
                source=source,
                route=route,
                tool_name=tool_name,
                priority_hint=10,
                metadata={
                    "pdf_pages": list(canonical_result.pages),
                    "pdf_mode": canonical_result.effective_mode,
                    "pdf_status": canonical_result.status,
                    "pdf_degraded_reason": canonical_result.degraded_reason,
                },
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
    execution_posture: str,
    user_message: str,
    tool_name: str = "",
    retrieval_results: list[dict[str, object]] | None = None,
    leak_flags: list[str] | None = None,
    has_tool_receipt: bool = False,
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
        execution_posture=execution_posture,
        user_message=user_message,
        tool_name=tool_name,
        retrieval_results=retrieval_results,
        rejected_candidates=ranked,
        has_tool_receipt=has_tool_receipt,
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
    execution_posture: str,
    user_message: str,
    tool_name: str,
    retrieval_results: list[dict[str, object]] | None,
    rejected_candidates: list[OutputCandidate],
    has_tool_receipt: bool,
) -> tuple[str, str]:
    has_retrieval = bool(list(retrieval_results or []))
    has_no_receipt_promise = any(
        item.channel in {"procedural_promise", "tool_claim_without_receipt"}
        for item in rejected_candidates
    )
    if has_no_receipt_promise and not has_tool_receipt:
        if execution_posture == "bounded_agent" or route == "agent":
            return ("当前还没有形成真实查询结果。", "no_receipt_query_promise")
        return ("当前没有可验证的执行结果。", "no_receipt_tool_claim")
    if route == "rag":
        if not has_retrieval:
            return ("当前本地知识库没有检到足够相关材料，无法可靠回答这个问题。", "rag_no_retrieval")
        return ("已检索到相关资料，但当前模型尚未产出可直接展示的结论。", "rag_missing_answer")
    if route == "memory":
        return ("当前没有足够的会话记忆可直接回答这个问题。", "memory_missing_answer")
    if tool_name == "pdf_analysis":
        canonical_candidates = [
            item
            for item in rejected_candidates
            if item.tool_name == "pdf_analysis" and item.metadata.get("pdf_pages")
        ]
        if canonical_candidates:
            pages = canonical_candidates[0].metadata.get("pdf_pages") or []
            selected = "、".join(f"P{page}" for page in list(pages)[:3])
            if selected:
                return (
                    f"已读取与当前问题最相关的 PDF 页面：{selected}，但当前还没有形成稳定摘要。",
                    "pdf_canonical_missing_summary",
                )
        return ("已读取这份 PDF，但当前工具尚未形成可直接展示的摘要。", "pdf_missing_summary")
    if tool_name:
        return (f"工具 `{tool_name}` 已执行，但当前结果尚未形成可直接展示的答案。", "tool_missing_summary")
    if user_message.strip():
        return ("当前尚未形成可直接展示的结论，请继续细化问题或提供更多上下文。", "generic_missing_answer")
    return ("当前没有可展示的答案。", "empty_answer")


def _collapse_inline_whitespace(text: str) -> str:
    return _NOISY_WHITESPACE_RE.sub(" ", text).strip()
