from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import re

from runtime.output_boundary.classifier import build_output_decision, classify_output_candidate
from runtime.output_boundary.output_models import (
    CanonicalState,
    FinalizationPolicy,
    OutputChannel,
    OutputCandidate,
    PersistPolicy,
)


INTERNAL_PROTOCOL_MARKERS = (
    "<think",
    "</think>",
    "<tool_call",
    "</tool_call>",
    "<｜｜DSML｜｜tool_calls>",
    "<｜｜DSML｜｜invoke",
    "<｜｜DSML｜｜parameter",
    "DSML",
    "</｜｜DSML｜｜tool_calls>",
    "</｜｜DSML｜｜parameter",
    "tool_calls",
    "invoke name=",
    'name="read_file"',
    'name="completion_criteria"',
    'name="task_run_goal"',
    'name="user_visible_goal"',
    'name="search_text"',
    'name="search_files"',
    'name="spawn_subagent"',
    'name="send_subagent_message"',
    'name="wait_subagent"',
    'name="list_subagents"',
    'name="close_subagent"',
    "**工具调用:**",
    "**工具输出:**",
    "此工具调用为系统自动补全示例",
    "\\end{invoke",
    "_CANONICAL_RESULT::",
)

_ACTIVE_WORK_CONTROL_ACTIONS = {
    "continue_active_work",
    "pause_active_work",
    "stop_active_work",
    "append_instruction_to_active_work",
    "answer_about_active_work",
    "answer_then_continue_active_work",
}
_ACTIVE_WORK_CONTROL_KEYS = {
    "action",
    "intent",
    "resolved_action",
    "active_work_control",
    "relation_to_current_work",
    "relation",
    "response",
    "appended_instruction",
    "continuation_strategy",
    "turn_response_policy",
    "user_turn_kind",
    "answer_obligation",
}
_ACTIVE_WORK_CONTROL_ACTION_RE = re.compile(
    r'"(?:action|intent|resolved_action)"\s*:\s*"(?:'
    + "|".join(re.escape(action) for action in sorted(_ACTIVE_WORK_CONTROL_ACTIONS))
    + r')"',
    re.IGNORECASE,
)
_ACTIVE_WORK_CONTROL_KEY_RE = re.compile(
    r'"(?:active_work_control|relation_to_current_work|continuation_strategy|turn_response_policy|answer_obligation|appended_instruction|user_turn_kind)"\s*:',
    re.IGNORECASE,
)
_MODEL_ACTION_PROTOCOL_RE = re.compile(
    r'"authority"\s*:\s*"harness\.loop\.model_action_request"|'
    r'"action_type"\s*:\s*"(?:respond|ask_user|tool_call|request_task_run|active_work_control|block)"',
    re.IGNORECASE,
)
_RUNTIME_PROTOCOL_DISCLOSURE_MARKERS = (
    "json_action_required",
    "single_agent_turn_json_action_required",
    "single_agent_turn_model_protocol_error",
    "single_agent_turn_invalid_json_action",
    "single_agent_turn_invalid_native_action",
    "tool_loop_protocol_repair",
    "protocol_repair",
    "model_action_protocol_repair_required",
    "harness.loop.single_agent_turn.protocol_repair",
    "harness.loop.model_action_request",
    "assistant_session_message_allowed",
    "runtime_commit_gate",
    "model-response-protocol:",
)
_RUNTIME_PROTOCOL_DISCLOSURE_RE = re.compile(
    r"(?:上一轮|上轮|本轮|当前轮|模型输出|输出|回复)[^\n。！？]{0,50}"
    r"(?:格式协议|运行协议|动作协议|输出协议|JSON\s*action|json_action|action\s+schema)[^\n。！？]{0,90}"
    r"(?:拦截|拒绝|阻止|修复|违规|违反|未执行|约束|刚性约束)"
    r"|(?:格式协议|运行协议|动作协议|输出协议)[^\n。！？]{0,70}"
    r"(?:系统|会话框架|runtime|运行边界|提交门)[^\n。！？]{0,50}"
    r"(?:拦截|拒绝|阻止|修复|未执行|约束|刚性约束)"
    r"|(?:系统|会话框架|runtime|运行边界|提交门)[^\n。！？]{0,60}"
    r"(?:拦截|拒绝|阻止|修复|未执行|约束|刚性约束)[^\n。！？]{0,60}"
    r"(?:格式协议|运行协议|动作协议|输出协议|JSON\s*action|json_action|action\s+schema)"
    r"|(?:previous|last)\s+(?:model\s+)?(?:response|output|message)[^\n.?!]{0,80}"
    r"(?:protocol|json\s*action|action\s+schema)[^\n.?!]{0,80}"
    r"(?:blocked|rejected|intercepted|repair|repaired|violated)",
    re.IGNORECASE,
)

_DSML_TOKEN_RE = r"(?:[｜|]\s*){2}\s*DSML\s*(?:[｜|]\s*){2}"
_TOOL_CALL_XML_RE = re.compile(r"<tool_call\b[^>]*>[\s\S]*?(?:</tool_call>|\Z)", re.IGNORECASE)
_DSML_TOOL_CALL_BLOCK_RE = re.compile(rf"<\s*{_DSML_TOKEN_RE}\s*tool_calls\b[^>]*>[\s\S]*?(?:</\s*{_DSML_TOKEN_RE}\s*tool_calls\s*>|\Z)", re.IGNORECASE)
_DSML_INVOKE_BLOCK_RE = re.compile(rf"<\s*{_DSML_TOKEN_RE}\s*invoke\b[^>]*>[\s\S]*?(?:</\s*{_DSML_TOKEN_RE}\s*invoke\s*>|\Z)", re.IGNORECASE)
_DSML_PARAMETER_BLOCK_RE = re.compile(rf"<\s*{_DSML_TOKEN_RE}\s*parameter\b[^>]*>[\s\S]*?(?:</\s*{_DSML_TOKEN_RE}\s*parameter\s*>|\Z)", re.IGNORECASE)
_DSML_PARAMETER_FRAGMENT_RE = re.compile(
    rf"(?:<\s*{_DSML_TOKEN_RE}\s*parameter\b\s*)?name\s*=\s*[\"'][A-Za-z_][\w-]*[\"']\s+string\s*=\s*[\"'](?:true|false)[\"']\s*>.*?(?:</\s*{_DSML_TOKEN_RE}\s*parameter\s*>|\Z)",
    re.IGNORECASE | re.DOTALL,
)
_DSML_TAG_FRAGMENT_RE = re.compile(rf"</?\s*{_DSML_TOKEN_RE}\s*[^>]*>?", re.IGNORECASE)
_HALF_DSML_TOOL_LINE_RE = re.compile(
    rf"^\s*(?:name\s*=\s*[\"'][A-Za-z_][\w-]*[\"']\s*>?|<\s*{_DSML_TOKEN_RE}\s*/?parameter\b.*|</?\s*{_DSML_TOKEN_RE}\s*[^>]*>?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_THINK_BLOCK_RE = re.compile(r"<think\b[^>]*>[\s\S]*?(?:</think>|\Z)", re.IGNORECASE)
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
_CANONICAL_RESULT_BLOCK_RE = re.compile(
    r"[A-Z_]+_CANONICAL_RESULT::[\s\S]*",
    re.IGNORECASE,
)
_PSEUDO_TOOL_CALL_NAMES = (
    "agent_todo",
    "bash",
    "close_subagent",
    "cmd",
    "edit_file",
    "execute_command",
    "fetch_url",
    "git_branch_create",
    "git_branch_list",
    "git_commit",
    "git_diff",
    "git_log",
    "git_restore",
    "git_show",
    "git_stage",
    "git_status",
    "git_unstage",
    "glob_paths",
    "image_generate",
    "list_dir",
    "list_subagents",
    "memory_search",
    "path_exists",
    "python_code_outline",
    "python_parse_check",
    "python_symbol_search",
    "read_file",
    "read_persisted_tool_result",
    "read_structured_file",
    "search_files",
    "search_text",
    "send_subagent_message",
    "shell",
    "spawn_subagent",
    "stat_path",
    "terminal",
    "wait_subagent",
    "web_search",
    "write_file",
)
_PSEUDO_TOOL_CALL_NAME_RE = "|".join(re.escape(name) for name in _PSEUDO_TOOL_CALL_NAMES)
_INLINE_PSEUDO_TOOL_CALL_RE = re.compile(
    rf"^\s*(?:(?:{_PSEUDO_TOOL_CALL_NAME_RE})\s*\([^()\n]{{0,800}}\)\s*(?:[,;]\s*)?){{1,8}}\s*$",
    re.IGNORECASE | re.MULTILINE,
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
        or contains_runtime_protocol_disclosure(normalized)
        or bool(_MODEL_ACTION_PROTOCOL_RE.search(normalized))
        or _looks_like_active_work_control_protocol(normalized)
        or bool(_TOOL_AUTOFILL_NOTE_RE.search(normalized))
        or bool(_SEARCH_PROTOCOL_BLOCK_RE.search(normalized))
        or bool(_TOOL_ARG_JSON_OBJECT_RE.search(normalized))
        or bool(_DSML_PARAMETER_FRAGMENT_RE.search(normalized))
        or bool(_DSML_TAG_FRAGMENT_RE.search(normalized))
        or bool(_PROTO_ARG_LINE_RE.search(normalized))
        or bool(_INVOKE_TAIL_RE.search(normalized))
    )


def contains_runtime_protocol_disclosure(text: str) -> bool:
    normalized = str(text or "")
    lowered = normalized.lower()
    return any(marker.lower() in lowered for marker in _RUNTIME_PROTOCOL_DISCLOSURE_MARKERS) or bool(
        _RUNTIME_PROTOCOL_DISCLOSURE_RE.search(normalized)
    )


def _looks_like_active_work_control_protocol(text: str) -> bool:
    normalized = str(text or "").strip()
    if not normalized:
        return False
    lowered = normalized.lower()
    if "active_work_control" not in lowered and not any(action in lowered for action in _ACTIVE_WORK_CONTROL_ACTIONS):
        return False
    parsed = _parse_json_like(normalized)
    if _payload_contains_active_work_control(parsed):
        return True
    return bool(_ACTIVE_WORK_CONTROL_ACTION_RE.search(normalized) and _ACTIVE_WORK_CONTROL_KEY_RE.search(normalized))


def _parse_json_like(text: str) -> object | None:
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = _FENCE_LINE_RE.sub("", candidate.replace("\r\n", "\n")).strip()
    if not ((candidate.startswith("{") and candidate.endswith("}")) or (candidate.startswith("[") and candidate.endswith("]"))):
        return None
    try:
        return json.loads(candidate)
    except Exception:
        return None


def _payload_contains_active_work_control(value: object | None) -> bool:
    if isinstance(value, list):
        return any(_payload_contains_active_work_control(item) for item in value)
    if not isinstance(value, dict):
        return False
    payload = {str(key): item for key, item in value.items()}
    action_type = str(payload.get("action_type") or "").strip().lower()
    if action_type == "active_work_control":
        return True
    if _payload_contains_active_work_control(payload.get("active_work_control")):
        return True
    action = str(payload.get("resolved_action") or payload.get("action") or payload.get("intent") or "").strip().lower()
    if action not in _ACTIVE_WORK_CONTROL_ACTIONS:
        return False
    return any(key in payload for key in _ACTIVE_WORK_CONTROL_KEYS)


def contains_inline_pseudo_tool_call(text: str) -> bool:
    normalized = str(text or "")
    if not normalized.strip():
        return False
    return bool(_INLINE_PSEUDO_TOOL_CALL_RE.search(normalized))


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
    cleaned = _DSML_TOOL_CALL_BLOCK_RE.sub("", cleaned)
    cleaned = _DSML_INVOKE_BLOCK_RE.sub("", cleaned)
    cleaned = _DSML_PARAMETER_BLOCK_RE.sub("", cleaned)
    cleaned = _DSML_PARAMETER_FRAGMENT_RE.sub("", cleaned)
    cleaned = _DSML_TAG_FRAGMENT_RE.sub("", cleaned)
    cleaned = _HALF_DSML_TOOL_LINE_RE.sub("", cleaned)
    cleaned = _THINK_BLOCK_RE.sub("", cleaned)
    cleaned = _THINK_CLOSE_RE.sub("", cleaned)
    cleaned = _NO_NEWLINE_MARKER_RE.sub("", cleaned)
    cleaned = _TOOL_CALL_BLOCK_RE.sub("", cleaned)
    cleaned = _TOOL_OUTPUT_BLOCK_RE.sub("", cleaned)
    cleaned = _TOOL_AUTOFILL_NOTE_RE.sub("", cleaned)
    cleaned = _TOOL_ARG_JSON_OBJECT_RE.sub("", cleaned)
    cleaned = _PROTO_ARG_LINE_RE.sub("", cleaned)
    cleaned = _INVOKE_TAIL_RE.sub("", cleaned)
    cleaned = _FENCED_JSON_RE.sub("", cleaned)
    cleaned = _SEARCH_PROTOCOL_BLOCK_RE.sub("", cleaned)
    cleaned = _CANONICAL_RESULT_BLOCK_RE.sub("", cleaned)
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
    canonical_state: CanonicalState
    persist_policy: PersistPolicy
    finalization_policy: FinalizationPolicy
    segments: list[AssistantOutputSegment]
    tool_calls: list[dict[str, str]]
    tool_receipts: list[dict[str, object]]
    raw_debug_text: str
    leak_flags: list[str]
    fallback_reason: str = ""


@dataclass(slots=True, frozen=True)
class CanonicalFinalTextDecision:
    content: str
    answer_channel: str
    answer_source: str
    selected_channel: OutputChannel
    selected_source: str
    canonical_state: CanonicalState
    persist_policy: PersistPolicy
    finalization_policy: FinalizationPolicy
    fallback_reason: str = ""
    leak_flags: list[str] = field(default_factory=list)

    def to_payload(self) -> dict[str, object]:
        return {
            "content": self.content,
            "answer_channel": self.answer_channel,
            "answer_source": self.answer_source,
            "answer_canonical_state": self.canonical_state,
            "answer_persist_policy": self.persist_policy,
            "answer_finalization_policy": self.finalization_policy,
            "answer_fallback_reason": self.fallback_reason,
            "answer_selected_channel": self.selected_channel,
            "answer_selected_source": self.selected_source,
            "answer_leak_flags": list(self.leak_flags),
        }


_DEBUG_ONLY_FINAL_TEXT_CHANNELS = {
    "active_work_control",
    "opening_judgment",
    "task_control",
    "orchestration_fail_closed",
    "runtime_control",
}


def _meaningful_visible_final_text(text: str) -> bool:
    normalized = str(text or "").strip()
    if not normalized:
        return False
    if normalized in {">", "<", "...", "…", "---", "----"}:
        return False
    if contains_internal_protocol(normalized) or contains_inline_pseudo_tool_call(normalized):
        return False
    return any(ch.isalnum() or "\u4e00" <= ch <= "\u9fff" for ch in normalized)


def _canonical_visible_final_text(
    text: str,
    *,
    route: str,
    source: str,
    execution_posture: str,
    user_message: str,
    tool_name: str,
    retrieval_results: list[dict[str, object]] | None,
    has_tool_receipt: bool,
) -> str:
    visible_text = str(text or "").strip()
    if not visible_text:
        return ""
    candidates: list[OutputCandidate] = []
    candidate = classify_output_candidate(
        text=visible_text,
        route=route,
        source=source,
        tool_name=tool_name,
        has_tool_receipt=has_tool_receipt,
    )
    if candidate is not None:
        candidates.append(candidate)
    decision = build_output_decision(
        candidates=candidates,
        route=route,
        execution_posture=execution_posture,
        user_message=user_message,
        tool_name=tool_name,
        retrieval_results=retrieval_results,
        leak_flags=[],
        has_tool_receipt=has_tool_receipt,
    )
    canonical_content = sanitize_visible_assistant_content(decision.canonical_answer).strip()
    return canonical_content or visible_text


def canonical_output_decision_for_final_text(
    content: str,
    *,
    answer_source: str,
    answer_channel: str = "final_answer",
    route: str = "",
    execution_posture: str = "",
    user_message: str = "",
    tool_name: str = "",
    retrieval_results: list[dict[str, object]] | None = None,
    has_tool_receipt: bool = False,
    terminal_reason: str = "",
    completion_state: str = "",
) -> CanonicalFinalTextDecision:
    raw_text = str(content or "")
    visible_text = sanitize_visible_assistant_content(raw_text)
    leak_flags: list[str] = []
    if contains_runtime_protocol_disclosure(raw_text):
        leak_flags.append("runtime_protocol_disclosure_final_text")
    if contains_internal_protocol(raw_text):
        leak_flags.append("internal_protocol_final_text")
    if contains_inline_pseudo_tool_call(raw_text):
        leak_flags.append("inline_pseudo_tool_call_final_text")
    hard_leak_flags = [
        flag
        for flag in leak_flags
        if flag != "inline_pseudo_tool_call_final_text"
    ]

    normalized_channel = str(answer_channel or "").strip() or "final_answer"
    normalized_source = str(answer_source or "").strip() or "runtime.output_boundary.final_text"
    if not visible_text.strip():
        return CanonicalFinalTextDecision(
            content="",
            answer_channel=normalized_channel,
            answer_source=normalized_source,
            selected_channel="missing_answer",
            selected_source="runtime.output_boundary.empty_final_text",
            canonical_state="missing_answer",
            persist_policy="do_not_persist",
            finalization_policy="none",
            fallback_reason=str(terminal_reason or completion_state or "empty_final_text").strip(),
            leak_flags=leak_flags,
        )
    if hard_leak_flags and not _meaningful_visible_final_text(visible_text):
        return CanonicalFinalTextDecision(
            content="",
            answer_channel=normalized_channel,
            answer_source=normalized_source,
            selected_channel="missing_answer",
            selected_source="runtime.output_boundary.protocol_fail_closed",
            canonical_state="missing_answer",
            persist_policy="do_not_persist",
            finalization_policy="none",
            fallback_reason=str(terminal_reason or completion_state or "internal_protocol_final_text").strip(),
            leak_flags=hard_leak_flags,
        )
    if normalized_channel in _DEBUG_ONLY_FINAL_TEXT_CHANNELS:
        return CanonicalFinalTextDecision(
            content=(visible_text or salvage_visible_assistant_content(raw_text)).strip(),
            answer_channel=normalized_channel,
            answer_source=normalized_source,
            selected_channel="progress_text",
            selected_source=normalized_source,
            canonical_state="progress_only",
            persist_policy="persist_debug_only",
            finalization_policy="none",
            fallback_reason=str(terminal_reason or completion_state or f"{normalized_channel}_message").strip(),
            leak_flags=leak_flags,
        )
    if hard_leak_flags:
        return CanonicalFinalTextDecision(
            content="",
            answer_channel=normalized_channel,
            answer_source=normalized_source,
            selected_channel="missing_answer",
            selected_source="runtime.output_boundary.protocol_sanitized",
            canonical_state="missing_answer",
            persist_policy="do_not_persist",
            finalization_policy="none",
            fallback_reason=str(terminal_reason or completion_state or "internal_protocol_final_text").strip(),
            leak_flags=hard_leak_flags,
        )

    candidate = classify_output_candidate(
        text=visible_text,
        route=route,
        source=normalized_source,
        tool_name=tool_name,
        has_tool_receipt=has_tool_receipt,
    )
    output_decision = build_output_decision(
        candidates=[candidate] if candidate is not None else [],
        route=route,
        execution_posture=execution_posture,
        user_message=user_message,
        tool_name=tool_name,
        retrieval_results=retrieval_results,
        leak_flags=[],
        has_tool_receipt=has_tool_receipt,
    )
    canonical_content = sanitize_visible_assistant_content(output_decision.canonical_answer).strip()
    if not canonical_content:
        return CanonicalFinalTextDecision(
            content="",
            answer_channel=normalized_channel,
            answer_source=normalized_source,
            selected_channel="missing_answer",
            selected_source="runtime.output_boundary.empty_final_text",
            canonical_state="missing_answer",
            persist_policy="do_not_persist",
            finalization_policy="none",
            fallback_reason=str(terminal_reason or completion_state or "empty_final_text").strip(),
            leak_flags=[],
        )
    return CanonicalFinalTextDecision(
        content=canonical_content,
        answer_channel=normalized_channel,
        answer_source=normalized_source,
        selected_channel=output_decision.selected_channel,
        selected_source=output_decision.selected_source,
        canonical_state=output_decision.canonical_state,
        persist_policy=output_decision.persist_policy,
        finalization_policy=output_decision.finalization_policy,
        fallback_reason=str(output_decision.fallback_reason or terminal_reason or completion_state or "").strip(),
        leak_flags=[],
    )


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
        if contains_inline_pseudo_tool_call(chunk):
            self._add_flag("inline_pseudo_tool_call_stream")
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
        if contains_inline_pseudo_tool_call(text):
            self._add_flag("inline_pseudo_tool_call_ai_update")
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
            canonical_state=decision.canonical_state,
            persist_policy=decision.persist_policy,
            finalization_policy=decision.finalization_policy,
            segments=segments,
            tool_calls=all_tool_calls,
            tool_receipts=tool_receipts,
            raw_debug_text="\n\n".join(part for part in raw_parts if part.strip()).strip(),
            leak_flags=decision.leak_flags,
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


