from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import re
from typing import Any, Literal

from context_system.budget.presets import match_context_budget_preset_for_available_context_tokens
from memory_system.storage.models import Message
from memory_system.storage.session_memory import SessionMemoryManager
from memory_system.storage.session_memory_view import has_material_session_memory_content
from runtime.prompt_accounting import CanonicalPromptSerializer, CompressionBudgetPlanner
from token_accounting import count_text_tokens

from .hooks import CompactBoundaryReceipt, CompactHookDecision, PreCompactHookRequest
from .invariants import validate_compacted_messages
from .low_authority_text import compress_low_authority_text, is_low_authority_natural_text_message
from .microcompact import decide_microcompact_cache_policy
from .semantic_worker import (
    SemanticCompactionWorkerResult,
    evaluate_semantic_compaction_summary_quality,
    failed_sample_from_summary_quality,
    normalize_semantic_compaction_worker_result,
    semantic_compaction_worker_exception,
    semantic_compactor_registration_from_worker,
)


RECOVERY_PACKAGE_SECTIONS: tuple[tuple[str, str], ...] = (
    ("current_goal", "当前目标"),
    ("active_constraints", "当前约束"),
    ("verified_facts", "已验证事实"),
    ("decisions", "已确认决策"),
    ("artifacts", "产物与引用"),
    ("invalidated_items", "已失效或被否定内容"),
    ("open_questions", "未解决问题"),
    ("next_actions", "下一步恢复动作"),
    ("recovery_notes", "恢复提示"),
)


@dataclass(slots=True)
class CompactResult:
    did_compact: bool
    messages: list[Message]
    summary_message: Message | None = None
    pressure_level: Literal["normal", "warning", "microcompact", "full_compact"] = "normal"
    strategy: str = "none"
    estimated_tokens_before: int = 0
    estimated_tokens_after: int = 0
    original_message_count: int = 0
    compacted_message_count: int = 0
    did_microcompact: bool = False
    did_full_compact: bool = False
    replaced_message_count: int = 0
    preserved_recent_count: int = 0
    diagnostics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SemanticCompactionRequest:
    request_id: str
    pressure_level: Literal["microcompact", "full_compact"]
    summary_target_tokens: int
    messages: tuple[Message, ...]
    recent_messages: tuple[Message, ...]
    dropped_message_count: int
    instructions: str
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "pressure_level": self.pressure_level,
            "summary_target_tokens": self.summary_target_tokens,
            "messages": [self._message_to_dict(message) for message in self.messages],
            "recent_messages": [self._message_to_dict(message) for message in self.recent_messages],
            "dropped_message_count": self.dropped_message_count,
            "instructions": self.instructions,
            "diagnostics": dict(self.diagnostics),
            "authority": "context_system.semantic_compaction_request",
        }

    def _message_to_dict(self, message: Message) -> dict[str, Any]:
        return {
            "role": message.role,
            "content": message.content,
            "meta": dict(message.meta or {}),
        }


def _summary_from_semantic_worker_result(result: SemanticCompactionWorkerResult | None) -> str:
    if result is None or not result.ok:
        return ""
    if result.structured_summary:
        rendered = _render_recovery_package(result.structured_summary, fallback=result.summary_content)
        if rendered:
            return rendered
    return str(result.summary_content or "").strip()


def _render_recovery_package(package: dict[str, Any], *, fallback: str = "") -> str:
    normalized = {str(key): value for key, value in dict(package or {}).items()}
    lines: list[str] = []
    overview = _compact_recovery_text(
        normalized.get("summary")
        or normalized.get("overview")
        or normalized.get("brief")
        or fallback,
        limit=900,
    )
    if overview:
        lines.extend(["## 恢复概览", overview, ""])
    for key, title in RECOVERY_PACKAGE_SECTIONS:
        items = _recovery_items(normalized.get(key))
        if not items:
            continue
        lines.append(f"## {title}")
        lines.extend(f"- {item}" for item in items)
        lines.append("")
    return "\n".join(lines).strip()


def _recovery_items(value: Any) -> list[str]:
    if value in (None, "", [], {}):
        return []
    if isinstance(value, str):
        return [
            item
            for item in (_compact_recovery_text(line.strip(" -\t"), limit=500) for line in value.splitlines())
            if item
        ]
    if isinstance(value, (list, tuple)):
        result: list[str] = []
        for item in value:
            result.extend(_recovery_items(item))
        return _dedupe_recovery_items(result)
    if isinstance(value, dict):
        text = _recovery_item_from_dict(value)
        return [text] if text else []
    return [_compact_recovery_text(value, limit=500)] if _compact_recovery_text(value, limit=500) else []


def _recovery_item_from_dict(value: dict[str, Any]) -> str:
    preferred = (
        value.get("content")
        or value.get("text")
        or value.get("summary")
        or value.get("canonical")
        or value.get("path")
        or value.get("ref")
        or value.get("title")
    )
    if preferred:
        suffixes: list[str] = []
        for key in ("status", "source", "reason"):
            suffix = _compact_recovery_text(value.get(key), limit=120)
            if suffix:
                suffixes.append(f"{key}={suffix}")
        base = _compact_recovery_text(preferred, limit=420)
        return f"{base} ({'; '.join(suffixes)})" if suffixes else base
    pairs = [
        f"{key}={_compact_recovery_text(item, limit=120)}"
        for key, item in sorted(value.items())
        if item not in (None, "", [], {})
    ]
    return _compact_recovery_text("；".join(pairs), limit=500)


def _compact_recovery_text(value: Any, *, limit: int) -> str:
    text = " ".join(str(value or "").replace("\r\n", "\n").replace("\r", "\n").split())
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _dedupe_recovery_items(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = _compact_recovery_text(value, limit=500)
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


class ContextCompactor:
    """Applies token-aware runtime compaction using session memory as working state."""

    def __init__(
        self,
        session_memory_manager: SessionMemoryManager,
        max_messages: int = 18,
        keep_recent_messages: int = 8,
        effective_history_token_budget: int = 6_000,
        compaction_threshold_tokens: dict[str, Any] | None = None,
        warning_ratio: float = 0.65,
        microcompact_ratio: float = 0.82,
        full_compact_ratio: float = 0.94,
        bulky_message_token_threshold: int = 220,
        low_authority_text_token_threshold: int = 260,
        low_authority_text_target_chars: int = 520,
        full_compact_recent_messages: int = 6,
        prompt_serializer: CanonicalPromptSerializer | None = None,
        compression_budget_planner: CompressionBudgetPlanner | None = None,
        semantic_compactor: Any | None = None,
        microcompact_cache_state_provider: Any | None = None,
        pre_compact_hook: Any | None = None,
        post_compact_hook: Any | None = None,
    ) -> None:
        if keep_recent_messages >= max_messages:
            raise ValueError("keep_recent_messages must be smaller than max_messages")
        if full_compact_recent_messages <= 0:
            raise ValueError("full_compact_recent_messages must be positive")
        self.session_memory_manager = session_memory_manager
        self.max_messages = max_messages
        self.keep_recent_messages = keep_recent_messages
        self.full_compact_recent_messages = min(full_compact_recent_messages, keep_recent_messages)
        self.effective_history_token_budget = effective_history_token_budget
        configured_thresholds = self._configured_thresholds(
            compaction_threshold_tokens,
            effective_history_token_budget=effective_history_token_budget,
        )
        if configured_thresholds is not None:
            self.warning_tokens = configured_thresholds["warning"]
            self.microcompact_tokens = configured_thresholds["ready"]
            self.full_compact_tokens = configured_thresholds["replacement"]
        else:
            self.warning_tokens = max(1, int(effective_history_token_budget * warning_ratio))
            self.microcompact_tokens = max(self.warning_tokens + 1, int(effective_history_token_budget * microcompact_ratio))
            self.full_compact_tokens = max(self.microcompact_tokens + 1, int(effective_history_token_budget * full_compact_ratio))
        self.bulky_message_token_threshold = bulky_message_token_threshold
        self.low_authority_text_token_threshold = max(1, int(low_authority_text_token_threshold or 1))
        self.low_authority_text_target_chars = max(120, int(low_authority_text_target_chars or 120))
        self.prompt_serializer = prompt_serializer or CanonicalPromptSerializer()
        self.compression_budget_planner = compression_budget_planner or CompressionBudgetPlanner()
        self.semantic_compactor = semantic_compactor
        self.semantic_compactor_registration = (
            semantic_compactor_registration_from_worker(semantic_compactor)
            if semantic_compactor is not None
            else None
        )
        self.microcompact_cache_state_provider = microcompact_cache_state_provider
        self.pre_compact_hook = pre_compact_hook
        self.post_compact_hook = post_compact_hook

    def count_tokens(self, text: str) -> int:
        return self._count_tokens(text)

    def message_tokens(self, message: Message) -> int:
        return self._message_tokens(message)

    def conversation_tokens(self, messages: list[Message]) -> int:
        return self._conversation_tokens(messages)

    def _configured_thresholds(
        self,
        compaction_threshold_tokens: dict[str, Any] | None,
        *,
        effective_history_token_budget: int,
    ) -> dict[str, int] | None:
        raw_thresholds = dict(compaction_threshold_tokens or {})
        if not raw_thresholds:
            preset = match_context_budget_preset_for_available_context_tokens(effective_history_token_budget)
            if preset is not None:
                raw_thresholds = preset.compaction_threshold_tokens()
        if not raw_thresholds:
            return None

        budget = max(1, int(effective_history_token_budget or 1))
        replacement = self._positive_threshold(raw_thresholds.get("replacement"), budget)
        replacement = min(replacement, budget)
        ready = self._positive_threshold(raw_thresholds.get("ready"), int(replacement * 0.85))
        warning = self._positive_threshold(raw_thresholds.get("warning"), int(replacement * 0.75))
        ready = min(max(1, ready), replacement)
        warning = min(max(1, warning), ready)
        return {
            "warning": warning,
            "ready": ready,
            "replacement": replacement,
        }

    def _positive_threshold(self, value: Any, fallback: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = 0
        return max(1, parsed if parsed > 0 else int(fallback or 1))

    def pressure_level(
        self,
        tokens: int,
        message_count: int,
    ) -> Literal["normal", "warning", "microcompact", "full_compact"]:
        return self._pressure_level(tokens, message_count)

    def _count_tokens(self, text: str) -> int:
        return count_text_tokens(text)

    def _message_tokens(self, message: Message) -> int:
        return self._count_tokens(message.content)

    def _conversation_tokens(self, messages: list[Message]) -> int:
        return sum(self._message_tokens(message) for message in messages)

    def _pressure_level(self, tokens: int, message_count: int) -> Literal["normal", "warning", "microcompact", "full_compact"]:
        if tokens >= self.full_compact_tokens:
            return "full_compact"
        if tokens >= self.microcompact_tokens:
            return "microcompact"
        if tokens >= self.warning_tokens:
            return "warning"
        return "normal"

    def _looks_like_bulk_output(self, message: Message) -> bool:
        if message.role != "assistant":
            return False
        content = message.content.strip()
        lowered = content.lower()
        if self._message_tokens(message) < self.bulky_message_token_threshold:
            return False
        if "[rag retrieved context]" in lowered:
            return True
        markers = (
            "数据源：",
            "总行数：",
            "总商品数：",
            "列名：",
            "前 10 项",
            "结果（前 10 项）",
            "Extracted chunks:",
            "Rows:",
            "Sheet:",
            "Source:",
            "Modalities:",
            "tool call",
            "tool calls",
            "工具调用",
        )
        if any(marker.lower() in lowered for marker in markers):
            return True
        if content.count("|") >= 10:
            return True
        if content.count("{") + content.count("[") >= 8:
            return True
        if len(re.findall(r"https?://", lowered)) >= 2:
            return True
        return False

    def _microcompact_stub(self, message: Message) -> Message:
        content = message.content.strip()
        lowered = content.lower()
        label = "assistant output"
        if "[rag retrieved context]" in lowered:
            label = "retrieval context"
        elif any(
            token in lowered
            for token in ("数据源：", "总商品数：", "总行数：", "前 10 项", "结果（前 10 项）", "工具调用")
        ):
            label = "structured analysis output"
        elif "source:" in lowered or "http" in lowered:
            label = "source-heavy output"
        preview = re.sub(r"\s+", " ", content)[:160].strip()
        return Message(
            role=message.role,
            content=(
                f"[Earlier {label} was microcompacted to reduce context pressure. "
                f"Use session memory for the working state. Preview: {preview}]"
            ),
            meta={**message.meta, "kind": "microcompact_stub"},
        )

    def _low_authority_text_stub(self, message: Message) -> Message | None:
        compression = compress_low_authority_text(
            message.content,
            target_chars=self.low_authority_text_target_chars,
        )
        if not compression.applied:
            return None
        digest = hashlib.sha256(str(message.content or "").encode("utf-8", errors="ignore")).hexdigest()[:16]
        return Message(
            role=message.role,
            content=(
                "[Earlier low-authority assistant prose was compressed to reduce context pressure. "
                "This checkpoint is not source evidence and must not replace current user intent. "
                f"Preview: {compression.content}]"
            ),
            meta={
                **message.meta,
                "kind": "low_authority_text_compressed",
                "original_content_hash": digest,
                "compression": compression.to_dict(),
            },
        )

    def _apply_microcompact(self, messages: list[Message]) -> tuple[list[Message], int, int]:
        if len(messages) <= self.keep_recent_messages:
            return list(messages), 0, 0

        boundary = len(messages) - self.keep_recent_messages
        compacted: list[Message] = []
        bulky_replaced = 0
        low_authority_replaced = 0
        for index, message in enumerate(messages):
            if index < boundary and self._looks_like_bulk_output(message):
                compacted.append(self._microcompact_stub(message))
                bulky_replaced += 1
            elif index < boundary and is_low_authority_natural_text_message(
                message,
                token_count=self._message_tokens(message),
                threshold_tokens=self.low_authority_text_token_threshold,
            ):
                stub = self._low_authority_text_stub(message)
                if stub is not None:
                    compacted.append(stub)
                    low_authority_replaced += 1
                else:
                    compacted.append(message)
            else:
                compacted.append(message)
        return compacted, bulky_replaced, low_authority_replaced

    def build_semantic_compaction_request(
        self,
        messages: list[Message],
        *,
        pressure_level: Literal["microcompact", "full_compact"],
        request_id: str = "context_compaction:preview",
        session_id: str = "",
        turn_id: str = "",
        task_run_id: str = "",
        task_environment_id: str = "",
        trigger: str = "",
        reason: str = "",
        reserved_output_tokens: int = 0,
    ) -> SemanticCompactionRequest:
        diagnostics = self._prompt_accounting_diagnostics(
            list(messages),
            request_id=request_id,
            session_id="",
            task_run_id="",
            reserved_output_tokens=reserved_output_tokens,
        )
        diagnostics = {
            **diagnostics,
            "session_id": str(session_id or ""),
            "turn_id": str(turn_id or ""),
            "task_run_id": str(task_run_id or ""),
            "task_environment_id": str(task_environment_id or ""),
            "trigger": str(trigger or ""),
            "reason": str(reason or ""),
        }
        decision = dict(diagnostics.get("compression_budget_decision") or {})
        recent = tuple(self._select_recent_core_messages(list(messages), self.full_compact_recent_messages))
        protected_recent_ids = {id(message) for message in recent}
        semantic_messages = tuple(
            message
            for message in list(messages)
            if id(message) not in protected_recent_ids and not self._is_compaction_noise(message)
        )
        return SemanticCompactionRequest(
            request_id=request_id,
            pressure_level=pressure_level,
            summary_target_tokens=int(decision.get("summary_target_tokens") or 0),
            messages=semantic_messages,
            recent_messages=recent,
            dropped_message_count=max(0, len(messages) - len(semantic_messages) - len(recent)),
            instructions=self._semantic_compaction_instructions(),
            diagnostics=diagnostics,
        )

    def _build_full_compact_messages(
        self,
        messages: list[Message],
        *,
        max_chars_per_section: int,
        recent_count: int,
        summary_content: str | None = None,
        summary_target_tokens: int = 0,
        compaction_source: str = "deterministic_session_memory",
        preserve_from_index: int | None = None,
    ) -> tuple[list[Message], Message]:
        recent = self._select_full_compact_preserved_messages(
            messages,
            recent_count=recent_count,
            preserve_from_index=preserve_from_index,
        )
        session_summary = (
            summary_content.strip()
            if summary_content is not None
            else self.session_memory_manager.compact_view(max_chars_per_section=max_chars_per_section).strip()
        )
        session_summary = self._trim_summary_to_token_target(session_summary, summary_target_tokens)
        if not has_material_session_memory_content(session_summary):
            raise ValueError("compaction_summary_unavailable")
        summary_message = Message(
            role="system",
            content=(
                "Conversation history was compacted into a checkpoint because runtime context pressure became high. "
                "Use this handoff summary as the recovery point, then rely on the recent real messages that follow it. "
                "Do not infer that omitted raw tool output is still available in this prompt.\n\n"
                f"{session_summary}"
            ),
            meta={
                "kind": "compact_summary",
                "compaction_source": compaction_source,
                "summary_target_tokens": summary_target_tokens,
            },
        )
        return [summary_message, *recent], summary_message

    def _select_full_compact_preserved_messages(
        self,
        messages: list[Message],
        *,
        recent_count: int,
        preserve_from_index: int | None = None,
    ) -> list[Message]:
        if preserve_from_index is None:
            return self._select_recent_core_messages(messages, recent_count)
        preserve_start = max(0, min(int(preserve_from_index or 0), len(messages)))
        recent_core = self._select_recent_core_messages(messages, recent_count)
        recent_ids = {id(message) for message in recent_core}
        preserved: list[Message] = []
        for index, message in enumerate(messages):
            if index >= preserve_start or id(message) in recent_ids:
                preserved.append(message)
        return preserved

    def apply_strategy(
        self,
        messages: list[Message],
        *,
        pressure_level: Literal["normal", "warning", "microcompact", "full_compact"],
        summary_content: str | None = None,
        summary_source_content: str | None = None,
        request_id: str = "context_compaction:preview",
        session_id: str = "",
        turn_id: str = "",
        task_run_id: str = "",
        task_environment_id: str = "",
        trigger: Literal["auto", "manual", "context_overflow", "preview"] = "preview",
        reason: str = "",
        reserved_output_tokens: int = 0,
        semantic_summary_content: str | None = None,
        microcompact_cache_state: dict[str, Any] | None = None,
        force_full_compact: bool = False,
    ) -> CompactResult:
        working = list(messages)
        tokens_before = self._conversation_tokens(working)
        prompt_diagnostics = self._prompt_accounting_diagnostics(
            working,
            request_id=request_id,
            session_id=session_id,
            task_run_id=task_run_id,
            reserved_output_tokens=reserved_output_tokens,
        )
        budget_decision = dict(prompt_diagnostics.get("compression_budget_decision") or {})
        planned_strategy = str(budget_decision.get("strategy") or budget_decision.get("decision") or "none")

        if pressure_level in {"normal", "warning"}:
            return CompactResult(
                did_compact=False,
                messages=working,
                pressure_level=pressure_level,
                strategy="warning_only" if pressure_level == "warning" else "none",
                estimated_tokens_before=tokens_before,
                estimated_tokens_after=tokens_before,
                original_message_count=len(messages),
                compacted_message_count=len(working),
                preserved_recent_count=min(len(working), self.keep_recent_messages),
                diagnostics=prompt_diagnostics,
            )

        pre_hook_request = PreCompactHookRequest(
            request_id=request_id,
            session_id=session_id,
            turn_id=turn_id,
            task_run_id=task_run_id,
            task_environment_id=task_environment_id,
            trigger=trigger,
            reason=reason,
            token_before=tokens_before,
            planned_strategy=planned_strategy,
            pressure_level=pressure_level,
            diagnostics={"compression_budget_decision": budget_decision},
        )
        pre_hook_decision = self._run_pre_compact_hook(pre_hook_request)
        if not pre_hook_decision.allowed:
            return self._blocked_result(
                working,
                pressure_level=pressure_level,
                strategy="blocked_by_pre_compact_hook",
                tokens_before=tokens_before,
                request_id=request_id,
                session_id=session_id,
                turn_id=turn_id,
                task_run_id=task_run_id,
                task_environment_id=task_environment_id,
                trigger=trigger,
                reason=reason,
                planned_strategy=planned_strategy,
                block_reason=pre_hook_decision.reason or "pre_compact_hook_blocked",
                prompt_diagnostics={
                    **prompt_diagnostics,
                    "pre_compact_hook": pre_hook_decision.to_dict(),
                },
            )

        resolved_microcompact_cache_state = self._resolve_microcompact_cache_state(
            explicit_state=microcompact_cache_state,
            request_id=request_id,
            session_id=session_id,
            turn_id=turn_id,
            task_run_id=task_run_id,
            task_environment_id=task_environment_id,
            trigger=trigger,
            pressure_level=pressure_level,
        )
        microcompact_cache_decision = decide_microcompact_cache_policy(resolved_microcompact_cache_state)
        if microcompact_cache_decision.local_rewrite_allowed:
            micro_messages, bulky_replaced, low_authority_replaced = self._apply_microcompact(working)
        else:
            micro_messages, bulky_replaced, low_authority_replaced = list(working), 0, 0
        replaced = bulky_replaced + low_authority_replaced
        tokens_after_micro = self._conversation_tokens(micro_messages)
        post_micro_level = self._pressure_level(tokens_after_micro, len(micro_messages))
        if not force_full_compact and (
            pressure_level == "microcompact" or post_micro_level in {"normal", "warning", "microcompact"}
        ):
            strategy = "microcompact" if microcompact_cache_decision.local_rewrite_allowed else "microcompact_skipped_cache_warm"
            result = CompactResult(
                did_compact=replaced > 0,
                messages=micro_messages,
                pressure_level="microcompact",
                strategy=strategy,
                estimated_tokens_before=tokens_before,
                estimated_tokens_after=tokens_after_micro,
                original_message_count=len(messages),
                compacted_message_count=len(micro_messages),
                did_microcompact=replaced > 0,
                did_full_compact=False,
                replaced_message_count=replaced,
                preserved_recent_count=min(len(micro_messages), self.keep_recent_messages),
                diagnostics={
                    **prompt_diagnostics,
                    "estimated_tokens_after_microcompact": tokens_after_micro,
                    "bulky_message_replaced_count": bulky_replaced,
                    "low_authority_text_compressed_count": low_authority_replaced,
                    "microcompact_cache_decision": microcompact_cache_decision.to_dict(),
                    "semantic_compactor_required": False,
                },
            )
            return self._finalize_compact_result(
                result,
                before_messages=working,
                request_id=request_id,
                session_id=session_id,
                turn_id=turn_id,
                task_run_id=task_run_id,
                task_environment_id=task_environment_id,
                trigger=trigger,
                reason=reason,
                planned_strategy=planned_strategy,
                summary_source="",
                pre_hook_decision=pre_hook_decision,
            )

        summary_message: Message | None = None
        compacted = micro_messages
        tokens_after = tokens_after_micro
        recent_count = self.full_compact_recent_messages
        max_chars_per_section = 420
        summary_target_tokens = int(budget_decision.get("summary_target_tokens") or 0)
        session_compaction_validation = self.session_memory_manager.validate_compaction_state(working)
        session_summary_content = ""
        session_preserve_from_index: int | None = None
        if session_compaction_validation.get("ok"):
            session_summary_content = self.session_memory_manager.compact_view(
                max_chars_per_section=max_chars_per_section,
            ).strip()
            session_preserve_from_index = int(session_compaction_validation.get("covered_message_count") or 0)
        semantic_request = self.build_semantic_compaction_request(
            working,
            pressure_level="full_compact",
            request_id=request_id,
            session_id=session_id,
            turn_id=turn_id,
            task_run_id=task_run_id,
            task_environment_id=task_environment_id,
            trigger=trigger,
            reason=reason,
            reserved_output_tokens=reserved_output_tokens,
        )
        semantic_compactor_needed = (
            semantic_summary_content is None
            and not has_material_session_memory_content(summary_content or "")
            and not has_material_session_memory_content(summary_source_content or "")
            and not session_summary_content
        )
        semantic_worker_result = (
            self._run_registered_semantic_compactor(semantic_request)
            if semantic_compactor_needed and self.semantic_compactor is not None
            else None
        )
        semantic_worker_summary = _summary_from_semantic_worker_result(semantic_worker_result)
        resolved_summary_content = (
            semantic_summary_content
            or summary_content
            or session_summary_content
            or semantic_worker_summary
        )
        preserve_from_index = session_preserve_from_index if session_summary_content and resolved_summary_content == session_summary_content else None
        compaction_source = (
            "semantic_compactor"
            if semantic_summary_content
            else "explicit_summary"
            if summary_content
            else "validated_session_memory"
            if session_summary_content and resolved_summary_content == session_summary_content
            else str(semantic_worker_result.source)
            if semantic_worker_result and semantic_worker_result.ok
            else "explicit_summary_source"
            if summary_source_content
            else "unavailable"
        )
        full_compact_diagnostics = {
            **prompt_diagnostics,
            "estimated_tokens_after_microcompact": tokens_after_micro,
            "bulky_message_replaced_count": bulky_replaced,
            "low_authority_text_compressed_count": low_authority_replaced,
            "microcompact_cache_decision": microcompact_cache_decision.to_dict(),
            "summary_source_tokens": self._count_tokens(summary_source_content or ""),
            "session_compaction_state": dict(session_compaction_validation or {}),
            "semantic_compactor_required": semantic_compactor_needed,
            "semantic_compactor_registered": self.semantic_compactor_registration is not None,
            "semantic_compactor_binding": (
                self.semantic_compactor_registration.to_dict()
                if self.semantic_compactor_registration is not None
                else {}
            ),
            "semantic_compactor_result": semantic_worker_result.to_dict() if semantic_worker_result is not None else {},
            "semantic_compaction_request": semantic_request.to_dict(),
            "semantic_structured_summary_present": bool(
                semantic_worker_result
                and semantic_worker_result.ok
                and semantic_worker_result.structured_summary
            ),
            "compaction_source": compaction_source,
        }
        while True:
            if resolved_summary_content is None and summary_source_content is not None:
                resolved_summary_content = self.session_memory_manager.compact_view(
                    content=summary_source_content,
                    max_chars_per_section=max_chars_per_section,
                ).strip()
            try:
                compacted, summary_message = self._build_full_compact_messages(
                    micro_messages,
                    max_chars_per_section=max_chars_per_section,
                    recent_count=recent_count,
                    summary_content=resolved_summary_content if resolved_summary_content is not None else "",
                    summary_target_tokens=summary_target_tokens,
                    compaction_source=compaction_source,
                    preserve_from_index=preserve_from_index,
                )
            except ValueError as exc:
                if str(exc) != "compaction_summary_unavailable":
                    raise
                return self._blocked_result(
                    working,
                    pressure_level=pressure_level,
                    strategy="blocked_by_empty_compaction_summary",
                    tokens_before=tokens_before,
                    request_id=request_id,
                    session_id=session_id,
                    turn_id=turn_id,
                    task_run_id=task_run_id,
                    task_environment_id=task_environment_id,
                    trigger=trigger,
                    reason=reason,
                    planned_strategy=planned_strategy,
                    block_reason="compaction_summary_unavailable",
                    prompt_diagnostics={
                        **full_compact_diagnostics,
                        **self._summary_quality_diagnostics(
                            request_id=request_id,
                            session_id=session_id,
                            summary_source=compaction_source,
                            before_messages=working,
                            after_messages=working,
                            summary_content=resolved_summary_content or "",
                            semantic_worker_result=semantic_worker_result,
                        ),
                        "pre_compact_hook": pre_hook_decision.to_dict(),
                    },
                )
            tokens_after = self._conversation_tokens(compacted)
            if tokens_after <= self.effective_history_token_budget:
                break
            if recent_count > 3:
                recent_count -= 1
                continue
            if max_chars_per_section > 240:
                max_chars_per_section = 240
                if resolved_summary_content is None and summary_source_content is None and summary_content is None:
                    resolved_summary_content = self.session_memory_manager.compact_view(
                        max_chars_per_section=max_chars_per_section,
                    ).strip()
                continue
            break

        if tokens_after >= tokens_before and summary_message is not None:
            fallback_summary = resolved_summary_content
            if fallback_summary is None:
                if summary_source_content is not None:
                    fallback_summary = self.session_memory_manager.compact_view(
                        content=summary_source_content,
                        max_chars_per_section=160,
                    ).strip()
                else:
                    fallback_summary = self.session_memory_manager.compact_view(max_chars_per_section=160).strip()
            try:
                compacted, summary_message = self._build_full_compact_messages(
                    micro_messages,
                    max_chars_per_section=160,
                    recent_count=min(2, len(micro_messages)),
                    summary_content=fallback_summary if fallback_summary is not None else "",
                    summary_target_tokens=min(summary_target_tokens, 160) if summary_target_tokens else 160,
                    compaction_source=compaction_source,
                    preserve_from_index=preserve_from_index,
                )
            except ValueError as exc:
                if str(exc) != "compaction_summary_unavailable":
                    raise
                return self._blocked_result(
                    working,
                    pressure_level=pressure_level,
                    strategy="blocked_by_empty_compaction_summary",
                    tokens_before=tokens_before,
                    request_id=request_id,
                    session_id=session_id,
                    turn_id=turn_id,
                    task_run_id=task_run_id,
                    task_environment_id=task_environment_id,
                    trigger=trigger,
                    reason=reason,
                    planned_strategy=planned_strategy,
                    block_reason="compaction_summary_unavailable",
                    prompt_diagnostics={
                        **full_compact_diagnostics,
                        **self._summary_quality_diagnostics(
                            request_id=request_id,
                            session_id=session_id,
                            summary_source=compaction_source,
                            before_messages=working,
                            after_messages=working,
                            summary_content=fallback_summary or "",
                            semantic_worker_result=semantic_worker_result,
                        ),
                        "pre_compact_hook": pre_hook_decision.to_dict(),
                    },
                )
            tokens_after = self._conversation_tokens(compacted)

        full_compact_diagnostics = {
            **full_compact_diagnostics,
            **self._summary_quality_diagnostics(
                request_id=request_id,
                session_id=session_id,
                summary_source=compaction_source,
                before_messages=working,
                after_messages=compacted,
                summary_content=str(getattr(summary_message, "content", "") or resolved_summary_content or ""),
                semantic_worker_result=semantic_worker_result,
            ),
        }
        result = CompactResult(
            did_compact=True,
            messages=compacted,
            summary_message=summary_message,
            pressure_level="full_compact",
            strategy="full_compact",
            estimated_tokens_before=tokens_before,
            estimated_tokens_after=tokens_after,
            original_message_count=len(messages),
            compacted_message_count=len(compacted),
            did_microcompact=replaced > 0,
            did_full_compact=True,
            replaced_message_count=replaced,
            preserved_recent_count=max(0, len(compacted) - 1),
            diagnostics=full_compact_diagnostics,
        )
        return self._finalize_compact_result(
            result,
            before_messages=working,
            request_id=request_id,
            session_id=session_id,
            turn_id=turn_id,
            task_run_id=task_run_id,
            task_environment_id=task_environment_id,
            trigger=trigger,
            reason=reason,
            planned_strategy=planned_strategy,
            summary_source=compaction_source,
            pre_hook_decision=pre_hook_decision,
        )

    def _select_recent_core_messages(self, messages: list[Message], recent_count: int) -> list[Message]:
        if recent_count <= 0:
            return []
        tail = list(messages)
        recent: list[Message] = []
        for message in reversed(tail):
            if len(recent) >= recent_count:
                break
            if not self._looks_like_bulk_output(message):
                recent.append(message)
        if len(recent) < recent_count:
            for message in reversed(tail):
                if len(recent) >= recent_count:
                    break
                if message in recent:
                    continue
                recent.append(message)
        recent.reverse()
        return recent

    def _is_compaction_noise(self, message: Message) -> bool:
        meta = dict(message.meta or {})
        if str(meta.get("kind") or "") in {"compact_summary", "microcompact_stub", "low_authority_text_compressed"}:
            return True
        content = str(message.content or "").strip()
        lowered = content.lower()
        return any(
            marker in lowered
            for marker in (
                "runtime context package",
                "runtime execution facts",
                "operationgate",
                "resourcepolicy",
                "当前 agent 工作契约",
            )
        )

    def _semantic_compaction_instructions(self) -> str:
        return "\n".join(
            [
                "你是一名上下文压缩员。",
                "你只负责把已有运行历史整理成后续主 agent 可以继续工作的恢复点，不回答用户，也不继续执行原任务。",
                "你不能引入新事实，不能搜索，不能修改文件，不能调用工具，不能写入记忆。",
                "你需要保留用户目标、当前约束、用户纠错、已验证事实、决策、产物引用、已失效事项、未解决问题和下一步恢复提示。",
                "你需要丢弃重复寒暄、旧工具原文、大段 JSON/表格/日志原文、过期状态和已被后续消息否定的信息。",
                "你必须输出 JSON 对象，并包含 structured_summary。",
                "structured_summary 必须只包含从输入中能找到证据的信息，字段包括 current_goal、active_constraints、verified_facts、decisions、artifacts、invalidated_items、open_questions、next_actions、recovery_notes。",
                "没有证据的字段使用空数组或空字符串；不要用模板说明占位。",
                "可以附带 summary_content 作为简短中文概览，但系统会优先使用 structured_summary 渲染 checkpoint。",
                "如果输入不足以可靠压缩，输出空 structured_summary 和空 summary_content，并在 diagnostics.reason 中说明原因。",
                "不要暴露内部运行 id，不要输出 JSON 以外的解释文本，不要把旧工具原文整段复制进摘要。",
            ]
        )

    def _run_registered_semantic_compactor(self, request: SemanticCompactionRequest) -> SemanticCompactionWorkerResult:
        if self.semantic_compactor is None:
            return SemanticCompactionWorkerResult(ok=False, diagnostics={"reason": "semantic_compactor_not_configured"})
        try:
            if hasattr(self.semantic_compactor, "compact"):
                raw_result = self.semantic_compactor.compact(request)
            else:
                raw_result = self.semantic_compactor(request)
        except Exception as exc:
            return semantic_compaction_worker_exception(exc)
        return normalize_semantic_compaction_worker_result(raw_result)

    def _summary_quality_diagnostics(
        self,
        *,
        request_id: str,
        session_id: str,
        summary_source: str,
        before_messages: list[Message],
        after_messages: list[Message],
        summary_content: str,
        semantic_worker_result: SemanticCompactionWorkerResult | None,
    ) -> dict[str, Any]:
        quality = evaluate_semantic_compaction_summary_quality(
            request_id=request_id,
            session_id=session_id,
            summary_source=summary_source,
            before_messages=before_messages,
            after_messages=after_messages,
            summary_content=summary_content,
            structured_summary=(
                dict(semantic_worker_result.structured_summary or {})
                if semantic_worker_result is not None and semantic_worker_result.structured_summary
                else {}
            ),
        )
        failed_sample = failed_sample_from_summary_quality(
            quality,
            request_id=request_id,
            session_id=session_id,
            summary_source=summary_source,
        )
        return {
            "summary_quality": quality.to_dict(),
            "summary_quality_failed_sample_ledger": [failed_sample.to_dict()] if failed_sample is not None else [],
        }

    def _resolve_microcompact_cache_state(
        self,
        *,
        explicit_state: dict[str, Any] | None,
        request_id: str,
        session_id: str,
        turn_id: str,
        task_run_id: str,
        task_environment_id: str,
        trigger: str,
        pressure_level: str,
    ) -> dict[str, Any]:
        if explicit_state is not None:
            return dict(explicit_state or {})
        provider = self.microcompact_cache_state_provider
        if provider is None:
            return {}
        payload = {
            "request_id": request_id,
            "session_id": session_id,
            "turn_id": turn_id,
            "task_run_id": task_run_id,
            "task_environment_id": task_environment_id,
            "trigger": trigger,
            "pressure_level": pressure_level,
        }
        try:
            value = provider(payload)
        except TypeError:
            value = provider()
        return dict(value or {}) if isinstance(value, dict) else {}

    def _trim_summary_to_token_target(self, summary: str, target_tokens: int) -> str:
        normalized = str(summary or "").strip()
        if not normalized or target_tokens <= 0:
            return normalized
        if self._count_tokens(normalized) <= target_tokens:
            return normalized
        lines = [line.strip() for line in normalized.splitlines() if line.strip()]
        kept: list[str] = []
        for line in lines:
            candidate = "\n".join([*kept, line]).strip()
            if kept and self._count_tokens(candidate) > target_tokens:
                break
            kept.append(line)
        trimmed = "\n".join(kept).strip()
        if trimmed:
            return trimmed
        char_limit = max(200, target_tokens * 4)
        return normalized[:char_limit].rstrip()

    def _run_pre_compact_hook(self, request: PreCompactHookRequest) -> CompactHookDecision:
        if self.pre_compact_hook is None:
            return CompactHookDecision(allowed=True, reason="no_pre_compact_hook")
        return self._normalize_hook_decision(self.pre_compact_hook(request))

    def _run_post_compact_hook(self, receipt: CompactBoundaryReceipt) -> CompactHookDecision:
        if self.post_compact_hook is None:
            return CompactHookDecision(allowed=True, reason="no_post_compact_hook")
        return self._normalize_hook_decision(self.post_compact_hook(receipt))

    def _normalize_hook_decision(self, value: Any) -> CompactHookDecision:
        if isinstance(value, CompactHookDecision):
            return value
        if hasattr(value, "to_dict"):
            value = value.to_dict()
        if isinstance(value, dict):
            return CompactHookDecision(
                allowed=bool(value.get("allowed", True)),
                reason=str(value.get("reason") or ""),
                diagnostics=dict(value.get("diagnostics") or {}),
            )
        return CompactHookDecision(allowed=True, reason="hook_returned_no_decision")

    def _finalize_compact_result(
        self,
        result: CompactResult,
        *,
        before_messages: list[Message],
        request_id: str,
        session_id: str,
        turn_id: str,
        task_run_id: str,
        task_environment_id: str,
        trigger: Literal["auto", "manual", "context_overflow", "preview"],
        reason: str,
        planned_strategy: str,
        summary_source: str,
        pre_hook_decision: CompactHookDecision,
    ) -> CompactResult:
        invariant_report = validate_compacted_messages(before_messages, result.messages)
        if not invariant_report.ok:
            return self._blocked_result(
                before_messages,
                pressure_level=result.pressure_level,
                strategy="blocked_by_compaction_invariants",
                tokens_before=result.estimated_tokens_before,
                request_id=request_id,
                session_id=session_id,
                turn_id=turn_id,
                task_run_id=task_run_id,
                task_environment_id=task_environment_id,
                trigger=trigger,
                reason=reason,
                planned_strategy=planned_strategy,
                block_reason=";".join(invariant_report.reasons) or "compaction_invariant_failed",
                prompt_diagnostics={
                    **dict(result.diagnostics or {}),
                    "pre_compact_hook": pre_hook_decision.to_dict(),
                    "compaction_invariants": invariant_report.to_dict(),
                },
            )
        receipt = self._build_boundary_receipt(
            result,
            request_id=request_id,
            session_id=session_id,
            turn_id=turn_id,
            task_run_id=task_run_id,
            task_environment_id=task_environment_id,
            trigger=trigger,
            reason=reason,
            planned_strategy=planned_strategy,
            summary_source=summary_source,
            invariant_status="ok",
            blocked=False,
            block_reason="",
            extra_diagnostics={"pre_compact_hook": pre_hook_decision.to_dict(), "compaction_invariants": invariant_report.to_dict()},
        )
        post_hook_decision = self._run_post_compact_hook(receipt)
        result.diagnostics = {
            **dict(result.diagnostics or {}),
            "pre_compact_hook": pre_hook_decision.to_dict(),
            "post_compact_hook": post_hook_decision.to_dict(),
            "compaction_invariants": invariant_report.to_dict(),
            "compact_boundary_receipt": receipt.to_dict(),
        }
        return result

    def _blocked_result(
        self,
        messages: list[Message],
        *,
        pressure_level: Literal["normal", "warning", "microcompact", "full_compact"],
        strategy: str,
        tokens_before: int,
        request_id: str,
        session_id: str,
        turn_id: str,
        task_run_id: str,
        task_environment_id: str,
        trigger: Literal["auto", "manual", "context_overflow", "preview"],
        reason: str,
        planned_strategy: str,
        block_reason: str,
        prompt_diagnostics: dict[str, Any],
    ) -> CompactResult:
        result = CompactResult(
            did_compact=False,
            messages=list(messages),
            pressure_level=pressure_level,
            strategy=strategy,
            estimated_tokens_before=tokens_before,
            estimated_tokens_after=tokens_before,
            original_message_count=len(messages),
            compacted_message_count=len(messages),
            preserved_recent_count=min(len(messages), self.keep_recent_messages),
            diagnostics=dict(prompt_diagnostics or {}),
        )
        receipt = self._build_boundary_receipt(
            result,
            request_id=request_id,
            session_id=session_id,
            turn_id=turn_id,
            task_run_id=task_run_id,
            task_environment_id=task_environment_id,
            trigger=trigger,
            reason=reason,
            planned_strategy=planned_strategy,
            summary_source="",
            invariant_status=str(dict(prompt_diagnostics.get("compaction_invariants") or {}).get("ok") or "blocked"),
            blocked=True,
            block_reason=block_reason,
            extra_diagnostics={},
        )
        result.diagnostics = {
            **result.diagnostics,
            "compact_boundary_receipt": receipt.to_dict(),
        }
        return result

    def _build_boundary_receipt(
        self,
        result: CompactResult,
        *,
        request_id: str,
        session_id: str,
        turn_id: str,
        task_run_id: str,
        task_environment_id: str,
        trigger: Literal["auto", "manual", "context_overflow", "preview"],
        reason: str,
        planned_strategy: str,
        summary_source: str,
        invariant_status: str,
        blocked: bool,
        block_reason: str,
        extra_diagnostics: dict[str, Any],
    ) -> CompactBoundaryReceipt:
        budget_decision = dict(dict(result.diagnostics or {}).get("compression_budget_decision") or {})
        seed = json.dumps(
            {
                "request_id": request_id,
                "strategy": result.strategy,
                "before": result.estimated_tokens_before,
                "after": result.estimated_tokens_after,
                "blocked": blocked,
                "block_reason": block_reason,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        receipt_id = f"compact-receipt:{request_id}:{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:12]}"
        return CompactBoundaryReceipt(
            receipt_id=receipt_id,
            request_id=request_id,
            session_id=session_id,
            turn_id=turn_id,
            task_run_id=task_run_id,
            task_environment_id=task_environment_id,
            trigger=trigger,
            reason=reason,
            token_before=int(result.estimated_tokens_before or 0),
            token_after=int(result.estimated_tokens_after or 0),
            planned_strategy=planned_strategy,
            applied_strategy=result.strategy,
            pressure_level=result.pressure_level,
            preserved_segments=tuple(str(item) for item in list(budget_decision.get("preserved_segments") or [])),
            dropped_segments=tuple(str(item) for item in list(budget_decision.get("dropped_segments") or [])),
            summarized_segments=tuple(str(item) for item in list(budget_decision.get("summarized_segments") or [])),
            replaced_message_count=int(result.replaced_message_count or 0),
            preserved_recent_count=int(result.preserved_recent_count or 0),
            summary_source=summary_source,
            invariant_status=invariant_status,
            blocked=blocked,
            block_reason=block_reason,
            diagnostics=dict(extra_diagnostics or {}),
        )

    def maybe_compact(self, messages: list[Message]) -> CompactResult:
        working = list(messages)
        tokens_before = self._conversation_tokens(working)
        level = self._pressure_level(tokens_before, len(working))
        return self.apply_strategy(working, pressure_level=level)

    def _prompt_accounting_diagnostics(
        self,
        messages: list[Message],
        *,
        request_id: str,
        session_id: str,
        task_run_id: str,
        reserved_output_tokens: int,
    ) -> dict[str, Any]:
        segment_map = self.prompt_serializer.build_segment_map(
            request_id=request_id,
            messages=[self._message_payload(message) for message in messages],
            session_id=session_id,
            task_run_id=task_run_id,
            metadata={"source": "context_compaction"},
        )
        decision = self.compression_budget_planner.plan(
            segment_map.segments,
            context_window_tokens=self.effective_history_token_budget + max(0, int(reserved_output_tokens or 0)),
            reserved_output_tokens=max(0, int(reserved_output_tokens or 0)),
        )
        return {
            "prompt_segment_map": {
                "request_id": segment_map.request_id,
                "canonical_hash": segment_map.canonical_hash,
                "predicted_prompt_tokens": segment_map.predicted_prompt_tokens,
                "segment_count": len(segment_map.segments),
            },
            "segment_token_map": [
                {
                    "segment_id": segment.segment_id,
                    "kind": segment.kind,
                    "role": segment.role,
                    "ordinal": segment.ordinal,
                    "predicted_tokens": segment.predicted_tokens,
                    "cache_role": segment.cache_role,
                    "compression_role": segment.compression_role,
                    "content_hash": segment.content_hash,
                }
                for segment in segment_map.segments
            ],
            "compression_budget_decision": decision.to_dict(),
        }

    def _message_payload(self, message: Message) -> dict[str, Any]:
        return {
            "role": message.role,
            "content": message.content,
            "source": str(dict(message.meta or {}).get("source") or "session_history"),
        }



