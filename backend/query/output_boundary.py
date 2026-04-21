from __future__ import annotations

from dataclasses import dataclass, field
import re


INTERNAL_PROTOCOL_MARKERS = (
    "</think>",
    "<tool_call",
    "</tool_call>",
    "**工具调用:**",
    "**工具输出:**",
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
    r"^(?:我(?:来|将|会|先|需要先|先来|准备|打算)|让我|接下来(?:我)?)(?:检索|搜索|查看|检查|使用|调用|尝试|读取|分析|确认|改写|整理).+"
    r"|^(?:知识库检索(?:未返回结果|失败)。?(?:让我|我将).+)$",
    re.IGNORECASE,
)
_EXCESS_SEPARATOR_RE = re.compile(r"(?:\n\s*---\s*\n){2,}", re.DOTALL)
_BLANK_LINE_RE = re.compile(r"\n{3,}")


def contains_internal_protocol(text: str) -> bool:
    normalized = str(text or "")
    lowered = normalized.lower()
    return any(marker.lower() in lowered for marker in INTERNAL_PROTOCOL_MARKERS)


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
    if contains_internal_protocol(normalized):
        cleaned = _FENCED_JSON_RE.sub("", cleaned)
    cleaned = _INLINE_PSEUDO_TOOL_CALL_RE.sub("", cleaned)

    kept_lines: list[str] = []
    for raw_line in cleaned.splitlines():
        line = raw_line.strip()
        if not line:
            kept_lines.append("")
            continue
        if drop_internal_status and _INTERNAL_STATUS_LINE_RE.match(line):
            continue
        kept_lines.append(line)

    trimmed_lines = _trim_procedural_edges(kept_lines) if trim_procedural else kept_lines
    collapsed = "\n".join(trimmed_lines)
    collapsed = _EXCESS_SEPARATOR_RE.sub("\n\n", collapsed)
    collapsed = _BLANK_LINE_RE.sub("\n\n", collapsed)
    return collapsed.strip()


def _trim_procedural_edges(lines: list[str]) -> list[str]:
    content_indexes = [
        index
        for index, line in enumerate(lines)
        if line.strip() and not _PROCEDURAL_LINE_RE.match(line.strip())
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
    segments: list[AssistantOutputSegment]
    tool_calls: list[dict[str, str]]
    raw_debug_text: str
    leak_flags: list[str]


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
        self._current.tool_calls.append(
            {
                "tool": str(tool_name or "tool"),
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

    def build_response(self) -> AssistantOutputResponse:
        segments = list(self._segments)
        visible_parts = [segment.visible_text.strip() for segment in segments if segment.visible_text.strip()]
        all_tool_calls: list[dict[str, str]] = []
        raw_parts: list[str] = []
        leak_flags: list[str] = []
        for segment in segments:
            raw_parts.append(segment.raw_text)
            all_tool_calls.extend(list(segment.tool_calls))
            for flag in segment.debug_flags:
                if flag not in leak_flags:
                    leak_flags.append(flag)
        return AssistantOutputResponse(
            visible_text="\n\n".join(visible_parts).strip(),
            segments=segments,
            tool_calls=all_tool_calls,
            raw_debug_text="\n\n".join(part for part in raw_parts if part.strip()).strip(),
            leak_flags=leak_flags,
        )

    def _add_flag(self, flag: str) -> None:
        if flag not in self._current.debug_flags:
            self._current.debug_flags.append(flag)
