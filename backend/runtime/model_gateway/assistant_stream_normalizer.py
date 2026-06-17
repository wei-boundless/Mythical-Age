from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any

from runtime.model_gateway.assistant_stream_frame import (
    ASSISTANT_STREAM_FRAME_SCHEMA_VERSION,
    ASSISTANT_TEXT_DELTA_EVENT,
    AssistantStreamFrame,
    assistant_message_ref,
    content_sha256,
    utf8_byte_length,
)
from runtime.output_boundary import contains_inline_pseudo_tool_call, contains_internal_protocol


_SOFT_PUNCTUATION = {",", ";", ":", "，", "、", "；", "："}
_HARD_PUNCTUATION = {".", "!", "?", "。", "！", "？", "…"}
_ATOMIC_RUN = re.compile(r"^(?:https?://\S+|[A-Za-z]:[\\/]\S+|\.{0,2}[\\/]\S+|[\w.-]+/[\w./-]*[\w-])")
_WORD_RUN = re.compile(r"^\S+\s*")


@dataclass(frozen=True, slots=True)
class AssistantStreamDiagnostics:
    frame_count: int
    coalesce_latency_ms: float
    safety_gate_blocked_total: int
    final_checksum_mismatch_total: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "assistant_stream_frame_count": int(self.frame_count),
            "assistant_stream_coalesce_latency_ms": float(self.coalesce_latency_ms),
            "assistant_stream_safety_gate_blocked_total": int(self.safety_gate_blocked_total),
            "assistant_stream_final_checksum_mismatch_total": int(self.final_checksum_mismatch_total),
        }


@dataclass(frozen=True, slots=True)
class AssistantStreamPolicy:
    max_flush_interval_ms: int = 80
    max_pending_utf8_bytes: int = 256
    max_pending_line_count: int = 1
    min_event_interval_ms: int = 0
    event_budget_per_second: int = 0
    chunk_strategy: str = "semantic"

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "AssistantStreamPolicy":
        policy = dict(value or {})
        return cls(
            max_flush_interval_ms=_bounded_int(policy.get("max_flush_interval_ms"), default=80, minimum=0, maximum=1000),
            max_pending_utf8_bytes=_bounded_int(policy.get("max_pending_utf8_bytes"), default=256, minimum=1, maximum=4096),
            max_pending_line_count=_bounded_int(policy.get("max_pending_line_count"), default=1, minimum=1, maximum=20),
            min_event_interval_ms=_bounded_int(policy.get("min_event_interval_ms"), default=0, minimum=0, maximum=1000),
            event_budget_per_second=_bounded_int(policy.get("event_budget_per_second"), default=0, minimum=0, maximum=240),
            chunk_strategy=_choice(policy.get("chunk_strategy"), default="semantic", choices={"semantic", "typing"}),
        )


class AssistantStreamNormalizer:
    def __init__(
        self,
        *,
        stream_ref: str,
        message_ref: str = "",
        turn_run_id: str = "",
        task_run_id: str = "",
        answer_source: str = "",
        answer_channel: str = "conversation",
        max_flush_interval_ms: int = 80,
        max_pending_utf8_bytes: int = 256,
        max_pending_line_count: int = 1,
        min_event_interval_ms: int = 0,
        event_budget_per_second: int = 0,
        chunk_strategy: str = "semantic",
        safety_prefix_utf8_limit: int = 512,
    ) -> None:
        self.stream_ref = str(stream_ref or "")
        self.message_ref = str(message_ref or "") or assistant_message_ref(turn_id=turn_run_id, stream_ref=stream_ref)
        self.turn_run_id = str(turn_run_id or "")
        self.task_run_id = str(task_run_id or "")
        self.answer_source = str(answer_source or "")
        self.answer_channel = str(answer_channel or "conversation")
        self.max_flush_interval_ms = max(0, int(max_flush_interval_ms))
        self.max_pending_utf8_bytes = max(1, int(max_pending_utf8_bytes))
        self.max_pending_line_count = max(1, int(max_pending_line_count))
        self.min_event_interval_ms = max(0, int(min_event_interval_ms))
        self.event_budget_per_second = max(0, int(event_budget_per_second))
        self.chunk_strategy = _choice(chunk_strategy, default="semantic", choices={"semantic", "typing"})
        self.safety_prefix_utf8_limit = max(1, int(safety_prefix_utf8_limit))
        self.latest_sequence = 0
        self.safety_gate_open = False
        self.safety_gate_blocked = False
        self.safety_gate_blocked_total = 0
        self.final_checksum_mismatch_total = 0
        self.observed_content = ""
        self.emitted_content = ""
        self.pending_content = ""
        self._pending_since = time.monotonic()
        self._last_flush = self._pending_since
        self._coalesce_latency_ms_total = 0.0
        self._event_budget_window_started = self._pending_since
        self._event_budget_window_count = 0

    @classmethod
    def from_policy(
        cls,
        *,
        stream_ref: str,
        message_ref: str = "",
        turn_run_id: str = "",
        task_run_id: str = "",
        answer_source: str = "",
        answer_channel: str = "conversation",
        stream_policy: dict[str, Any] | None = None,
        safety_prefix_utf8_limit: int = 512,
    ) -> "AssistantStreamNormalizer":
        policy = AssistantStreamPolicy.from_dict(stream_policy)
        return cls(
            stream_ref=stream_ref,
            message_ref=message_ref,
            turn_run_id=turn_run_id,
            task_run_id=task_run_id,
            answer_source=answer_source,
            answer_channel=answer_channel,
            max_flush_interval_ms=policy.max_flush_interval_ms,
            max_pending_utf8_bytes=policy.max_pending_utf8_bytes,
            max_pending_line_count=policy.max_pending_line_count,
            min_event_interval_ms=policy.min_event_interval_ms,
            event_budget_per_second=policy.event_budget_per_second,
            chunk_strategy=policy.chunk_strategy,
            safety_prefix_utf8_limit=safety_prefix_utf8_limit,
        )

    def observe_delta(self, delta: str) -> list[dict[str, Any]]:
        text = str(delta or "")
        if not text:
            return []
        now = time.monotonic()
        if not self.pending_content:
            self._pending_since = now
        self.observed_content += text
        self.pending_content += text
        if not self._ensure_safety_gate():
            return []
        return [frame.to_event() for frame in self._drain_pending(force=False, now=now)]

    def flush(self) -> list[dict[str, Any]]:
        if not self._ensure_safety_gate():
            return []
        return [frame.to_event() for frame in self._drain_pending(force=True, now=time.monotonic())]

    def next_sequence(self) -> int:
        return self.latest_sequence + 1

    def mark_final_content(self, final_content: str) -> None:
        if self.latest_sequence > 0 and content_sha256(self.emitted_content) != content_sha256(str(final_content or "")):
            self.final_checksum_mismatch_total += 1

    def has_emitted_public_text(self, value: str) -> bool:
        target = _normalized_public_text(value)
        emitted = _normalized_public_text(self.emitted_content)
        return bool(target and emitted and target == emitted)

    def diagnostics(self) -> AssistantStreamDiagnostics:
        latency = self._coalesce_latency_ms_total / self.latest_sequence if self.latest_sequence > 0 else 0.0
        return AssistantStreamDiagnostics(
            frame_count=self.latest_sequence,
            coalesce_latency_ms=latency,
            safety_gate_blocked_total=self.safety_gate_blocked_total,
            final_checksum_mismatch_total=self.final_checksum_mismatch_total,
        )

    def _ensure_safety_gate(self) -> bool:
        if self.safety_gate_blocked:
            return False
        if self.safety_gate_open:
            return True
        text = self.observed_content.lstrip()
        if not text:
            return False
        lowered = text[:160].lower()
        if lowered.startswith(("{", "[", "```json")):
            return self._block_safety_gate()
        if any(marker in lowered for marker in ('"action_type"', '"tool_call"', '"authority"', "model_action_request")):
            return self._block_safety_gate()
        if contains_internal_protocol(text) or contains_inline_pseudo_tool_call(text):
            return self._block_safety_gate()
        if any(ch.isalnum() or "\u4e00" <= ch <= "\u9fff" for ch in text):
            self.safety_gate_open = True
            return True
        if utf8_byte_length(text) >= self.safety_prefix_utf8_limit:
            return self._block_safety_gate()
        return False

    def _block_safety_gate(self) -> bool:
        self.safety_gate_blocked = True
        self.safety_gate_blocked_total += 1
        self.pending_content = ""
        return False

    def _drain_pending(self, *, force: bool, now: float) -> list[AssistantStreamFrame]:
        frames: list[AssistantStreamFrame] = []
        while self.pending_content:
            if not force and not self._can_emit_event(now):
                break
            chunk = self._next_slice(force=force, now=now)
            if not chunk:
                break
            frames.append(self._frame_from_chunk(chunk, now=now))
            self.pending_content = self.pending_content[len(chunk):]
            self._last_flush = now
            self._record_event_budget(now)
            if not force:
                break
        return frames

    def _frame_from_chunk(self, chunk: str, *, now: float) -> AssistantStreamFrame:
        start = utf8_byte_length(self.emitted_content)
        self.emitted_content += chunk
        end = utf8_byte_length(self.emitted_content)
        self.latest_sequence += 1
        self._coalesce_latency_ms_total += max(0.0, (now - self._pending_since) * 1000)
        return AssistantStreamFrame(
            frame_schema_version=ASSISTANT_STREAM_FRAME_SCHEMA_VERSION,
            event_type=ASSISTANT_TEXT_DELTA_EVENT,
            frame_id=f"aframe:{self.stream_ref}:{self.latest_sequence}",
            stream_ref=self.stream_ref,
            message_ref=self.message_ref,
            turn_run_id=self.turn_run_id,
            task_run_id=self.task_run_id,
            sequence=self.latest_sequence,
            content=chunk,
            content_utf8_start=start,
            content_utf8_end=end,
            content_utf8_bytes=utf8_byte_length(chunk),
            accumulated_utf8_bytes=end,
            accumulated_sha256=content_sha256(self.emitted_content),
            answer_channel=self.answer_channel,
            answer_source=self.answer_source,
            markdown_state=_markdown_state(self.emitted_content),
            display_hint=_display_hint(chunk),
        )

    def _next_slice(self, *, force: bool, now: float) -> str:
        pending = self.pending_content
        if not pending:
            return ""
        if force:
            return _take_utf8_budget(pending, self._slice_utf8_budget())
        if self.chunk_strategy == "typing":
            return self._typing_slice(pending, now=now)
        newline_limited = _line_slice(pending, max_lines=self.max_pending_line_count)
        if newline_limited:
            return newline_limited
        atomic = _atomic_slice(pending)
        if atomic:
            return atomic
        punctuation = _punctuation_slice(pending)
        if punctuation:
            return punctuation
        if _starts_with_cjk(pending) and len([*pending[:8]]) >= 5:
            return _take_codepoints(pending, 5)
        words = _word_phrase(pending)
        if words:
            return words
        if utf8_byte_length(pending) >= self.max_pending_utf8_bytes:
            return _take_utf8_budget(pending, min(self.max_pending_utf8_bytes, 96))
        elapsed_ms = (now - self._last_flush) * 1000
        if elapsed_ms >= self.max_flush_interval_ms:
            return _take_codepoints(pending, min(len([*pending]), 24))
        return ""

    def _typing_slice(self, pending: str, *, now: float) -> str:
        budget = self._slice_utf8_budget()
        if utf8_byte_length(pending) >= budget:
            return _take_utf8_budget(pending, budget)
        elapsed_ms = (now - self._last_flush) * 1000
        if elapsed_ms >= self.max_flush_interval_ms:
            return _take_utf8_budget(pending, budget)
        return ""

    def _slice_utf8_budget(self) -> int:
        if self.chunk_strategy == "typing":
            return max(1, min(self.max_pending_utf8_bytes, 48))
        return max(1, min(self.max_pending_utf8_bytes, 96))

    def _can_emit_event(self, now: float) -> bool:
        if self.latest_sequence > 0 and self.min_event_interval_ms > 0:
            elapsed_ms = (now - self._last_flush) * 1000
            if elapsed_ms < self.min_event_interval_ms:
                return False
        if self.event_budget_per_second <= 0:
            return True
        if now - self._event_budget_window_started >= 1.0:
            self._event_budget_window_started = now
            self._event_budget_window_count = 0
        return self._event_budget_window_count < self.event_budget_per_second

    def _record_event_budget(self, now: float) -> None:
        if self.event_budget_per_second <= 0:
            return
        if now - self._event_budget_window_started >= 1.0:
            self._event_budget_window_started = now
            self._event_budget_window_count = 0
        self._event_budget_window_count += 1


def _markdown_state(text: str) -> dict[str, Any]:
    fences = str(text or "").count("```")
    line_start = not text or text.endswith("\n")
    block_kind = "code" if fences % 2 == 1 else "paragraph"
    if line_start:
        block_kind = "line"
    return {
        "block_kind": block_kind,
        "inside_code_fence": fences % 2 == 1,
        "line_start": line_start,
    }


def _display_hint(chunk: str) -> dict[str, Any]:
    text = str(chunk or "")
    atomic = bool(_ATOMIC_RUN.match(text))
    last = [*text][-1] if text else ""
    pause = "hard" if last in _HARD_PUNCTUATION else "soft" if last in _SOFT_PUNCTUATION else "none"
    if text.endswith("\n"):
        pause = "line"
    return {
        "chunk_kind": "atomic" if atomic else "phrase",
        "pause": pause,
        "atomic": atomic,
    }


def _normalized_public_text(value: str) -> str:
    return " ".join(str(value or "").split()).strip()


def _line_slice(text: str, *, max_lines: int) -> str:
    line_limit = max(1, int(max_lines))
    newline_count = 0
    for index, char in enumerate(str(text or "")):
        if char != "\n":
            continue
        newline_count += 1
        if newline_count >= line_limit:
            return text[: index + 1]
    return ""


def _atomic_slice(text: str) -> str:
    match = _ATOMIC_RUN.match(str(text or ""))
    if not match:
        return ""
    value = match.group(0)
    if len(value) < len(text):
        return value
    return ""


def _punctuation_slice(text: str) -> str:
    for index, char in enumerate(str(text or "")[:80]):
        if char in _SOFT_PUNCTUATION or char in _HARD_PUNCTUATION:
            return text[: index + 1]
    return ""


def _starts_with_cjk(text: str) -> bool:
    return bool(re.match(r"^[\u3400-\u9FFF\uF900-\uFAFF]", str(text or "")))


def _word_phrase(text: str) -> str:
    pending = str(text or "")
    index = 0
    words = 0
    while index < len(pending) and words < 4 and index < 56:
        match = _WORD_RUN.match(pending[index:])
        if not match:
            break
        index += len(match.group(0))
        words += 1
        if any(char in _SOFT_PUNCTUATION or char in _HARD_PUNCTUATION for char in match.group(0)):
            break
    if words >= 4:
        return pending[:index]
    return ""


def _take_codepoints(text: str, limit: int) -> str:
    return "".join([*str(text or "")][: max(1, int(limit))])


def _take_utf8_budget(text: str, budget: int) -> str:
    collected = ""
    for char in str(text or ""):
        candidate = f"{collected}{char}"
        if collected and utf8_byte_length(candidate) > budget:
            break
        collected = candidate
    return collected or _take_codepoints(text, 1)


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = int(default)
    return min(max(parsed, int(minimum)), int(maximum))


def _choice(value: Any, *, default: str, choices: set[str]) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in choices else default
