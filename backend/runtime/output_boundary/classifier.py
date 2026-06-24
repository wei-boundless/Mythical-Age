from __future__ import annotations

import re

from runtime.output_boundary.output_models import OutputCandidate, OutputDecision


_PROCEDURAL_PREFIX_RE = re.compile(
    r"^(?:岩[，,\s]*)?(?:我(?:(?:来|将|会|准备|打算)(?:先)?|先(?:来)?|需要先)|让我(?:先)?|接下来(?:我)?(?:先)?)"
    r"(?:检索|搜索|查看|检查|使用|调用|尝试|读取|分析|确认|核实|整理|改写|查询|执行|创建|新建|写入|保存|落盘|启动|运行|验证).+",
    re.IGNORECASE,
)
_PROCEDURAL_PROMISE_RE = re.compile(
    r"^(?:岩[，,\s]*)?(?:我(?:(?:来|将|会|准备|打算)(?:先)?|先(?:来)?|需要先)|让我(?:先)?|接下来(?:我)?(?:先)?|稍等(?:我)?)(?:去)?"
    r"(?:检索|搜索|查看|检查|读取|确认|核实|查询|执行|创建|新建|写入|保存|落盘|启动|运行|验证)(?:一下|一遍|下)?(?:最新状态|最新情况)?[\s。.!！…]*$"
    r"|^(?:岩[，,\s]*)?(?:我(?:(?:来|将|会|准备|打算)(?:先)?|先(?:来)?|需要先)|让我(?:先)?|接下来(?:我)?(?:先)?|稍等(?:我)?)"
    r".{0,80}(?:检索|搜索|查看|检查|读取|确认|核实|查询|执行|创建|新建|写入|保存|落盘|启动|运行|验证)(?:一下|一遍|下)?(?:最新状态|最新情况)?.*$",
    re.IGNORECASE,
)
_TOOL_CLAIM_WITHOUT_RECEIPT_RE = re.compile(
    r"^(?:岩[，,\s]*)?(?:我(?:已经|刚刚|刚才)?(?:查到|查询了|检索了|搜索了|确认了|核实了|创建了|新建了|写入了|保存了|落盘了|启动了|运行了|验证了)|我这边(?:已经)?(?:查到|确认到|核实到)).+",
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
    r"(?:^|\n)\s*(?:\*\*结论[:：]?\*\*|结论[:：])\s*(.+)",
    re.IGNORECASE | re.DOTALL,
)
_MARKDOWN_BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")
_NOISY_WHITESPACE_RE = re.compile(r"\s+")
_STRUCTURED_DATA_HINT_RE = re.compile(r"(?:数据源[:：]|查询模式[:：]|前\s*\d+\s*项[:：])")
_WEATHER_HINT_RE = re.compile(r"(?:当前天气|温度[:：]|湿度[:：]|风速[:：])")
_FINANCE_HINT_RE = re.compile(r"(?:黄金|金价|price)")
_PROMISE_LINE_PREFIX_RE = re.compile(
    r"^(?:岩[，,\s]*)?(?:我(?:(?:现在|立即|马上|这就){1,2}|(?:来|将|会|准备|打算)(?:先)?|先(?:来)?|需要先)|让我(?:先)?|接下来(?:我)?(?:先)?|稍等(?:我)?|现在(?:我)?|立即(?:我)?|马上(?:我)?)",
    re.IGNORECASE,
)
_ANSWER_INTRO_RE = re.compile(
    r"(?:结论[:：]|答案[:：]|总结[:：]|可以概括为|主要有|分别是|核心是|先用业务语言给出结论)",
    re.IGNORECASE,
)
_ACK_PREFIX_RE = re.compile(
    r"^(?:收到|好的|好|可以|明白|了解|行)[，,。.!！\s]*(?:这次|现在|接下来)?[，,。.!！\s]*",
    re.IGNORECASE,
)


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
    action_tokens = (
        "查询",
        "检索",
        "搜索",
        "查看",
        "检查",
        "读取",
        "确认",
        "核实",
        "执行",
        "创建",
        "新建",
        "写入",
        "保存",
        "落盘",
        "启动",
        "运行",
        "验证",
    )
    if len(lines) == 1 and re.fullmatch(r"(?:开始|开干|开始执行|开始处理)[。.!！…]*", lines[0]):
        return True
    for line in lines:
        line = _ACK_PREFIX_RE.sub("", line).strip()
        if not line:
            continue
        if _PROCEDURAL_PROMISE_RE.match(line):
            continue
        if _SUBTASK_STATUS_PROMISE_RE.match(line):
            continue
        if _ANSWER_INTRO_RE.search(line):
            return False
        if not _PROMISE_LINE_PREFIX_RE.match(line):
            return False
        compact = re.sub(r"\s+", "", line)
        compact = re.sub(r"^岩[，,]*", "", compact)
        if len(compact) > 120:
            return False
        if not any(token in compact for token in action_tokens):
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
            "我已经创建了",
            "我刚刚创建了",
            "我刚才创建了",
            "我已经新建了",
            "我已经写入了",
            "我刚刚写入了",
            "我已经保存了",
            "我已经落盘了",
            "我已经启动了",
            "我已经运行了",
            "我已经验证了",
            "写了",
            "已写入",
            "已保存",
            "已落盘",
            "已创建",
            "已启动",
        )
    )


def extract_explicit_answer(text: str) -> str:
    # Candidate recovery helper only. Normal final-text commits must preserve the
    # authored answer body instead of cropping around these labels.
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
    if tool_name in {"mcp_structured_data", "structured_data"} and _STRUCTURED_DATA_HINT_RE.search(normalized):
        return _collapse_inline_whitespace(normalized)
    if tool_name == "web_search":
        if normalized.startswith("{") or normalized.startswith("["):
            return ""
        if '"results"' in normalized or '"request_id"' in normalized or '"response_time"' in normalized:
            return ""
    if tool_name == "web_search" and (_WEATHER_HINT_RE.search(normalized) or _FINANCE_HINT_RE.search(normalized)):
        return _collapse_inline_whitespace(normalized)
    return ""


def looks_like_raw_tool_output(text: str, tool_name: str) -> bool:
    normalized = normalize_candidate_text(text)
    if not normalized:
        return False
    if tool_name == "web_search":
        return normalized.startswith("{") or normalized.startswith("[")
    if tool_name in {"mcp_structured_data", "structured_data"}:
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
        return OutputCandidate(
            channel="tool_visible_summary",
            text=tool_summary,
            source=source,
            route=route,
            tool_name=tool_name,
            priority_hint=80,
            metadata=metadata,
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
        canonical_state = "stable_answer"
        if preferred.channel == "tool_visible_summary":
            canonical_state = "tool_summary"
        return OutputDecision(
            canonical_answer=preferred.text.strip(),
            selected_channel=preferred.channel,
            selected_source=preferred.source,
            canonical_state=canonical_state,
            persist_policy="persist_canonical",
            finalization_policy="none",
            rejected_candidates=rejected,
            leak_flags=leak_flags,
        )
    fallback_reason, finalization_policy = missing_answer_reason(
        route=route,
        execution_posture=execution_posture,
        tool_name=tool_name,
        retrieval_results=retrieval_results,
        rejected_candidates=ranked,
        has_tool_receipt=has_tool_receipt,
        leak_flags=leak_flags,
    )
    return OutputDecision(
        canonical_answer="",
        selected_channel="missing_answer",
        selected_source="runtime.output_boundary.missing_answer",
        canonical_state="missing_answer",
        persist_policy="do_not_persist",
        finalization_policy=finalization_policy,
        rejected_candidates=ranked,
        leak_flags=leak_flags,
        fallback_reason=fallback_reason,
    )


def missing_answer_reason(
    *,
    route: str,
    execution_posture: str,
    tool_name: str,
    retrieval_results: list[dict[str, object]] | None,
    rejected_candidates: list[OutputCandidate],
    has_tool_receipt: bool,
    leak_flags: list[str] | None = None,
) -> tuple[str, str]:
    has_retrieval = bool(list(retrieval_results or []))
    normalized_leak_flags = {str(flag or "").strip() for flag in list(leak_flags or [])}
    has_no_receipt_promise = any(
        item.channel in {"procedural_promise", "tool_claim_without_receipt"}
        for item in rejected_candidates
    )
    has_receiptless_procedural = any(
        item.channel == "procedural_promise"
        for item in rejected_candidates
    )
    has_explicit_tool_claim = any(
        any(
            marker in str(item.text or "").lower()
            for marker in ("search_knowledge", "searchknowledge", "web_search", "retrieve", "tool")
        )
        or any(marker in str(item.text or "") for marker in ("工具", "调用"))
        for item in rejected_candidates
    ) or any("inline_pseudo_tool_call" in flag for flag in normalized_leak_flags)
    if not has_tool_receipt and has_explicit_tool_claim and not rejected_candidates:
        return "no_receipt_tool_claim", "none"
    if has_no_receipt_promise and not has_tool_receipt:
        if has_explicit_tool_claim:
            return "no_receipt_tool_claim", "none"
        if route == "rag" and has_retrieval and has_receiptless_procedural:
            return "no_receipt_query_promise", "route_required"
        if execution_posture == "bounded_agent" or route == "agent":
            return "no_receipt_query_promise", "none"
        return "no_receipt_tool_claim", "none"
    if route == "rag":
        if has_retrieval:
            return "rag_missing_answer", "route_required"
        return "rag_no_retrieval", "none"
    if route == "memory":
        return "memory_missing_answer", "none"
    if route == "pdf" or tool_name in {"mcp_pdf", "pdf"}:
        return _pdf_missing_answer_reason(rejected_candidates), "route_required"
    if tool_name:
        return "tool_missing_summary", "none"
    return "empty_answer", "none"


def _collapse_inline_whitespace(text: str) -> str:
    return _NOISY_WHITESPACE_RE.sub(" ", text).strip()


def _pdf_missing_answer_reason(rejected_candidates: list[OutputCandidate]) -> str:
    canonical_candidates = [
        item
        for item in rejected_candidates
        if item.route == "pdf" or item.tool_name in {"mcp_pdf", "pdf"}
    ]
    if not canonical_candidates:
        return "pdf_missing_summary"
    metadata = dict(canonical_candidates[0].metadata or {})
    degraded_reason = str(metadata.get("pdf_degraded_reason", "") or "").strip()
    return degraded_reason or "pdf_missing_summary"

