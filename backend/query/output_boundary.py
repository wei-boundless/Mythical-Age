from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import re

from query.output_classifier import build_output_decision, classify_output_candidate
from query.output_models import OutputCandidate


INTERNAL_PROTOCOL_MARKERS = (
    "</think>",
    "<tool_call",
    "</tool_call>",
    "**工具调用:**",
    "**工具输出:**",
    "此工具调用为系统自动补全示例",
    "\\end{invoke",
)

_TOOL_CALL_XML_RE = re.compile(r"<tool_call[^>]*>.*?(?:</tool_call>)?", re.IGNORECASE | re.DOTALL)
_THINK_CLOSE_RE = re.compile(r"</think>", re.IGNORECASE)
_NO_NEWLINE_MARKER_RE = re.compile(r"\\ No newline at end of file", re.IGNORECASE)
_TOOL_CALL_BLOCK_RE = re.compile(
    r"\*\*工具调用:\*\*.*?(?=(?:\n\s*---\s*\n)|(?:\*\*结论)|(?:\n\s*结论：)|(?:\n\s*岩，)|\Z)",
    re.DOTALL,
)
_TOOL_OUTPUT_BLOCK_RE = re.compile(
    r"\*\*工具输出:\*\*.*?(?=(?:\n\s*---\s*\n)|(?:\*\*结论)|(?:\n\s*结论：)|(?:\n\s*岩，)|\Z)",
    re.DOTALL,
)
_FENCED_JSON_RE = re.compile(r"```json\s*.*?```", re.IGNORECASE | re.DOTALL)
_TOOL_ARG_JSON_OBJECT_RE = re.compile(
    r"\{[\s\S]{0,240}?(?:\"(?:query|top_k|page|path|mode|section)\"\s*:)[\s\S]{0,240}?\}",
    re.IGNORECASE,
)
_TOOL_AUTOFILL_NOTE_RE = re.compile(
    r"注[:：]\s*此工具调用为系统自动补全示例[^\n]*",
    re.IGNORECASE,
)
_PROTO_ARG_LINE_RE = re.compile(
    r"^(?:query|top_k|page|path|mode|section)\s*:\s*.+$",
    re.IGNORECASE | re.MULTILINE,
)
_INVOKE_TAIL_RE = re.compile(r"\\end\{invoke[^\n]*", re.IGNORECASE)
_FENCE_LINE_RE = re.compile(r"^```(?:json)?\s*$", re.IGNORECASE)
_SEARCH_PROTOCOL_BLOCK_RE = re.compile(
    r"(?:现在)?(?:我)?(?:再)?(?:检索|搜索|看|查看)[^\n]{0,120}?(?:search_knowledge|searchKnowledge|web_search|retrieve)[^\n{]*\{[\s\S]{0,240}?\}",
    re.IGNORECASE,
)
_INLINE_PSEUDO_TOOL_CALL_RE = re.compile(
    r"(?:[A-Za-z_][A-Za-z0-9_]*\([^()\n]{0,400}\)\s*){1,8}",
    re.DOTALL,
)
_INTERNAL_STATUS_LINE_RE = re.compile(
    r"^(?:我将使用.+工具.+|我来检索.+|我来查看.+|知识库检索失败.*|搜索(?:_knowledge)? 工具调用失败.*|"
    r"knowledge 目录存在，但为空或无文件。|\[搜索结果 失败\])$",
    re.IGNORECASE,
)
_PROCEDURAL_LINE_RE = re.compile(
    r"^(?:岩[，,\s]*)?(?:我(?:来|将|会|先|需要先|先来|准备|打算)|让我(?:先)?|接下来(?:我)?(?:先)?|稍等(?:我)?)"
    r"(?:检索|搜索|查看|检查|使用|调用|尝试|读取|分析|确认|核实|改写|整理|查询|执行).+"
    r"|^(?:知识库检索(?:未返回结果|失败)。?(?:让我|我将).+)$",
    re.IGNORECASE,
)
_SUBTASK_STATUS_PROMISE_RE = re.compile(
    r"^(?:\d+[.)、]\s*)?[^:：\n]{1,40}[:：]\s*(?:正在(?:查询|检索|搜索|处理)|稍后(?:给你|给您)?(?:结果|回复)?|待(?:查询|确认|处理)|稍等).*$",
    re.IGNORECASE,
)
_EXCESS_SEPARATOR_RE = re.compile(r"(?:\n\s*---\s*\n){2,}", re.DOTALL)
_BLANK_LINE_RE = re.compile(r"\n{3,}")
_TRAILING_PROCEDURAL_TAIL_RE = re.compile(
    r"(?:\n\s*---\s*\n)(?:(?:让我|我来|我先|我将|我会|接下来(?:我)?)[^\n]{0,80})\s*$",
    re.IGNORECASE,
)
_TRAILING_SEPARATOR_RE = re.compile(r"(?:\n\s*---\s*)+\Z", re.DOTALL)


def contains_internal_protocol(text: str) -> bool:
    normalized = str(text or "")
    lowered = normalized.lower()
    return (
        any(marker.lower() in lowered for marker in INTERNAL_PROTOCOL_MARKERS)
        or bool(_TOOL_AUTOFILL_NOTE_RE.search(normalized))
        or bool(_SEARCH_PROTOCOL_BLOCK_RE.search(normalized))
        or bool(_TOOL_ARG_JSON_OBJECT_RE.search(normalized))
        or bool(_PROTO_ARG_LINE_RE.search(normalized))
        or bool(_INVOKE_TAIL_RE.search(normalized))
    )


def sanitize_visible_assistant_content(text: str) -> str:
    return _sanitize_visible_assistant_content(
        text,
        drop_internal_status=True,
        trim_procedural=True,
    )


def salvage_visible_assistant_content(text: str) -> str:
    return _sanitize_visible_assistant_content(
        text,
        drop_internal_status=False,
        trim_procedural=False,
    )


def _sanitize_visible_assistant_content(
    text: str,
    *,
    drop_internal_status: bool,
    trim_procedural: bool,
) -> str:
    normalized = str(text or "").replace("\r\n", "\n")
    if not normalized.strip():
        return ""

    cleaned = normalized
    cleaned = _TOOL_CALL_XML_RE.sub("", cleaned)
    cleaned = _THINK_CLOSE_RE.sub("", cleaned)
    cleaned = _NO_NEWLINE_MARKER_RE.sub("", cleaned)
    cleaned = _TOOL_CALL_BLOCK_RE.sub("", cleaned)
    cleaned = _TOOL_OUTPUT_BLOCK_RE.sub("", cleaned)
    cleaned = _TOOL_AUTOFILL_NOTE_RE.sub("", cleaned)
    cleaned = _TOOL_ARG_JSON_OBJECT_RE.sub("", cleaned)
    cleaned = _PROTO_ARG_LINE_RE.sub("", cleaned)
    cleaned = _INVOKE_TAIL_RE.sub("", cleaned)
    if contains_internal_protocol(normalized):
        cleaned = _FENCED_JSON_RE.sub("", cleaned)
    cleaned = _SEARCH_PROTOCOL_BLOCK_RE.sub("", cleaned)
    cleaned = _INLINE_PSEUDO_TOOL_CALL_RE.sub("", cleaned)

    kept_lines: list[str] = []
    for raw_line in cleaned.splitlines():
        line = raw_line.strip()
        if not line:
            kept_lines.append("")
            continue
        if _FENCE_LINE_RE.match(line):
            continue
        if drop_internal_status and (
            _INTERNAL_STATUS_LINE_RE.match(line)
            or _SUBTASK_STATUS_PROMISE_RE.match(line)
            or "search_knowledge" in line.lower()
            or "searchknowledge" in line.lower()
            or "web_search" in line.lower()
        ):
            continue
        kept_lines.append(line)

    trimmed_lines = _trim_procedural_edges(kept_lines) if trim_procedural else kept_lines
    collapsed = "\n".join(trimmed_lines)
    collapsed = _EXCESS_SEPARATOR_RE.sub("\n\n", collapsed)
    collapsed = _BLANK_LINE_RE.sub("\n\n", collapsed)
    collapsed = _TRAILING_PROCEDURAL_TAIL_RE.sub("", collapsed)
    collapsed = _TRAILING_SEPARATOR_RE.sub("", collapsed)
    return collapsed.strip()


def _trim_procedural_edges(lines: list[str]) -> list[str]:
    content_indexes = [
        index
        for index, line in enumerate(lines)
        if line.strip()
        and not _PROCEDURAL_LINE_RE.match(line.strip())
        and not _SUBTASK_STATUS_PROMISE_RE.match(line.strip())
    ]
    if not content_indexes:
        return lines
    start = content_indexes[0]
    end = content_indexes[-1]
    return lines[start : end + 1]


def _visible_delta(previous: str, current: str) -> str:
    if not current:
        return ""
    if not previous:
        return current
    if current.startswith(previous):
        return current[len(previous):]
    return ""


@dataclass(slots=True)
class AssistantOutputSegment:
    raw_text: str = ""
    stream_visible_text: str = ""
    ai_update_raw_text: str = ""
    ai_update_visible_text: str = ""
    visible_text: str = ""
    tool_calls: list[dict[str, str]] = field(default_factory=list)
    debug_flags: list[str] = field(default_factory=list)


@dataclass(slots=True)
class AssistantOutputResponse:
    visible_text: str
    canonical_answer: str
    selected_channel: str
    selected_source: str
    segments: list[AssistantOutputSegment]
    tool_calls: list[dict[str, str]]
    tool_receipts: list[dict[str, object]]
    raw_debug_text: str
    leak_flags: list[str]
    fallback_reason: str = ""


class AssistantOutputBoundary:
    def __init__(self) -> None:
        self._segments: list[AssistantOutputSegment] = []
        self._current = AssistantOutputSegment()

    def ingest_stream_text(self, text: str) -> str:
        chunk = str(text or "")
        if not chunk:
            return ""
        self._current.raw_text += chunk
        if contains_internal_protocol(chunk):
            self._add_flag("internal_protocol_stream")
        sanitized = sanitize_visible_assistant_content(self._current.raw_text)
        delta = _visible_delta(self._current.stream_visible_text, sanitized)
        self._current.stream_visible_text = sanitized
        return delta

    def ingest_ai_update(self, content: str, *, has_tool_calls: bool = False) -> None:
        text = str(content or "")
        if not text:
            return
        self._current.ai_update_raw_text = text
        if contains_internal_protocol(text):
            self._add_flag("internal_protocol_ai_update")
        if has_tool_calls:
            return
        sanitized = sanitize_visible_assistant_content(text)
        if sanitized and len(sanitized) >= len(self._current.ai_update_visible_text):
            self._current.ai_update_visible_text = sanitized

    def ingest_tool_call(self, tool_name: str, tool_input: str) -> None:
        self._current.tool_calls.append(
            {
                "tool": str(tool_name or "tool"),
                "input": str(tool_input or ""),
            }
        )

    def ingest_tool_result(self, tool_name: str, tool_output: str) -> None:
        normalized_tool = str(tool_name or "tool")
        for index in range(len(self._current.tool_calls) - 1, -1, -1):
            candidate = self._current.tool_calls[index]
            if str(candidate.get("tool", "") or "") != normalized_tool:
                continue
            if str(candidate.get("output", "") or "").strip():
                continue
            candidate["output"] = str(tool_output or "")
            return
        self._current.tool_calls.append(
            {
                "tool": normalized_tool,
                "output": str(tool_output or ""),
            }
        )

    def finalize_segment(self, *, fallback_content: str = "") -> None:
        fallback_visible = sanitize_visible_assistant_content(fallback_content) if fallback_content else ""
        strict_visible = (
            self._current.stream_visible_text
            or self._current.ai_update_visible_text
            or fallback_visible
        )
        if strict_visible:
            self._current.visible_text = strict_visible
        else:
            self._current.visible_text = (
                salvage_visible_assistant_content(self._current.raw_text)
                or salvage_visible_assistant_content(self._current.ai_update_raw_text)
                or salvage_visible_assistant_content(fallback_content)
            )
        if (
            self._current.raw_text.strip()
            or self._current.visible_text.strip()
            or self._current.tool_calls
            or self._current.debug_flags
        ):
            self._segments.append(self._current)
        self._current = AssistantOutputSegment()

    def build_response(
        self,
        *,
        route: str = "",
        execution_posture: str = "",
        user_message: str = "",
        tool_name: str = "",
        retrieval_results: list[dict[str, object]] | None = None,
    ) -> AssistantOutputResponse:
        segments = list(self._segments)
        visible_parts = [segment.visible_text.strip() for segment in segments if segment.visible_text.strip()]
        all_tool_calls: list[dict[str, str]] = []
        raw_parts: list[str] = []
        leak_flags: list[str] = []
        for segment in segments:
            raw_parts.append(segment.raw_text)
            all_tool_calls.extend(list(segment.tool_calls))
        tool_receipts = self._build_tool_receipts(all_tool_calls)
        has_tool_receipt = bool(tool_receipts)
        candidates: list[OutputCandidate] = []
        for segment in segments:
            if segment.visible_text.strip():
                candidate = classify_output_candidate(
                    text=segment.visible_text,
                    route=route,
                    source="segment.visible_text",
                    tool_name=tool_name,
                    has_tool_receipt=has_tool_receipt,
                )
                if candidate is not None:
                    candidates.append(candidate)
            if (
                segment.ai_update_visible_text.strip()
                and segment.ai_update_visible_text.strip() != segment.visible_text.strip()
            ):
                candidate = classify_output_candidate(
                    text=segment.ai_update_visible_text,
                    route=route,
                    source="segment.ai_update_visible_text",
                    tool_name=tool_name,
                    has_tool_receipt=has_tool_receipt,
                )
                if candidate is not None:
                    candidates.append(candidate)
            for tool_call in segment.tool_calls:
                output = str(tool_call.get("output", "") or "").strip()
                if not output:
                    continue
                candidate = classify_output_candidate(
                    text=output,
                    route=route,
                    source=f"tool.{tool_call.get('tool', tool_name or 'tool')}.output",
                    tool_name=str(tool_call.get("tool", "") or tool_name or ""),
                    allow_unlabeled_answer=False,
                    has_tool_receipt=True,
                )
                if candidate is not None:
                    candidates.append(candidate)
            for flag in segment.debug_flags:
                if flag not in leak_flags:
                    leak_flags.append(flag)
        decision = build_output_decision(
            candidates=candidates,
            route=route,
            execution_posture=execution_posture,
            user_message=user_message,
            tool_name=tool_name,
            retrieval_results=retrieval_results,
            leak_flags=leak_flags,
            has_tool_receipt=has_tool_receipt,
        )
        return AssistantOutputResponse(
            visible_text="\n\n".join(visible_parts).strip(),
            canonical_answer=decision.canonical_answer,
            selected_channel=decision.selected_channel,
            selected_source=decision.selected_source,
            segments=segments,
            tool_calls=all_tool_calls,
            tool_receipts=tool_receipts,
            raw_debug_text="\n\n".join(part for part in raw_parts if part.strip()).strip(),
            leak_flags=leak_flags,
            fallback_reason=decision.fallback_reason,
        )

    def _add_flag(self, flag: str) -> None:
        if flag not in self._current.debug_flags:
            self._current.debug_flags.append(flag)

    def _build_tool_receipts(self, tool_calls: list[dict[str, str]]) -> list[dict[str, object]]:
        receipts: list[dict[str, object]] = []
        for tool_call in tool_calls:
            output = str(tool_call.get("output", "") or "").strip()
            if not output:
                continue
            input_text = str(tool_call.get("input", "") or "")
            receipt = {
                "tool_name": str(tool_call.get("tool", "tool") or "tool"),
                "status": "completed",
                "input_digest": hashlib.sha1(input_text.encode("utf-8")).hexdigest()[:12] if input_text else "",
                "canonical_summary_available": bool(sanitize_visible_assistant_content(output).strip()),
                "evidence_ref": f"tool_output:{str(tool_call.get('tool', 'tool') or 'tool')}",
            }
            receipts.append(receipt)
        return receipts
