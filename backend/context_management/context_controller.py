from __future__ import annotations

import re
from typing import Any

from structured_memory.flow_snapshots import FlowSnapshot
from structured_memory.models import Message
from structured_memory.session_memory import SessionMemoryManager
from structured_memory.text_utils import normalize_storage_text

from .context_compactor import ContextCompactor
from .context_models import ContextBudget, ContextControllerResult, ContextPackage, PressureLevel

_HOT_TRUTH_TOOL_CALL_RE = re.compile(r"<tool_call[^>]*>.*?(?:</tool_call>)?", re.IGNORECASE | re.DOTALL)
_HOT_TRUTH_THINK_RE = re.compile(r"</think>", re.IGNORECASE)
_HOT_TRUTH_TOOL_BLOCK_RE = re.compile(
    r"\*\*工具(?:调用|输出):\*\*.*?(?=(?:\n\s*---\s*\n)|(?:\*\*结论)|(?:\n\s*结论：)|(?:\n\s*岩，)|\Z)",
    re.DOTALL,
)
_HOT_TRUTH_FENCED_JSON_RE = re.compile(r"```json\s*.*?```", re.IGNORECASE | re.DOTALL)


class ContextController:
    """Builds a context package and delegates compaction execution through a stable interface."""

    def __init__(
        self,
        session_memory_manager: SessionMemoryManager,
        *,
        reserved_output_tokens: int = 1200,
        static_context: list[str] | None = None,
        **compactor_kwargs: Any,
    ) -> None:
        self.session_memory_manager = session_memory_manager
        self.compactor = ContextCompactor(session_memory_manager, **compactor_kwargs)
        self.reserved_output_tokens = max(0, reserved_output_tokens)
        self.static_context = list(static_context or [])

    def compact_history(
        self,
        messages: list[Message],
        *,
        rebuild_reason: str = "history_compaction",
        exact_durable_matches: list[dict[str, Any]] | None = None,
        relevant_durable_matches: list[dict[str, Any]] | None = None,
        retrieval_evidence: list[str] | None = None,
    ) -> ContextControllerResult:
        package = self.build_context_package(
            messages,
            rebuild_reason=rebuild_reason,
            exact_durable_matches=exact_durable_matches,
            relevant_durable_matches=relevant_durable_matches,
            retrieval_evidence=retrieval_evidence,
        )
        preview_content = self._preview_content(messages)
        compact_result = self.compactor.apply_strategy(
            messages,
            pressure_level=package.pressure_level,
            summary_source_content=preview_content,
        )
        package.compaction_strategy = compact_result.strategy
        package.token_accounting["estimated_tokens_after"] = compact_result.estimated_tokens_after
        package.token_accounting["compacted_message_count"] = compact_result.compacted_message_count
        package.token_accounting["replaced_message_count"] = compact_result.replaced_message_count
        if compact_result.did_full_compact:
            package.dropped_sections = self._dedupe(
                [*package.dropped_sections, "warm_snapshots"]
            )
            package.compaction_decisions = self._dedupe(
                [
                    *package.compaction_decisions,
                    "full compact used compaction_view.md as the restore-oriented working-memory view",
                ]
            )
        return ContextControllerResult(
            messages=compact_result.messages,
            package=package,
            compact_result=compact_result,
        )

    def build_context_package(
        self,
        messages: list[Message],
        *,
        rebuild_reason: str,
        pending_user_message: str | None = None,
        exact_durable_matches: list[dict[str, Any]] | None = None,
        relevant_durable_matches: list[dict[str, Any]] | None = None,
        retrieval_evidence: list[str] | None = None,
        static_context: list[str] | None = None,
    ) -> ContextPackage:
        preview_messages = list(messages)
        if pending_user_message:
            preview_messages.append(Message(role="user", content=pending_user_message))

        preview_views = self.session_memory_manager.preview_views(preview_messages)
        compaction_view = preview_views["compaction"]
        model_sections = self.session_memory_manager.parse_sections(compaction_view)
        debug_view = preview_views["debug"]
        debug_source_sections = self.session_memory_manager.parse_sections(debug_view)

        tokens_before = self.compactor.conversation_tokens(messages)
        pressure_level = self.compactor.pressure_level(tokens_before, len(messages))
        budget = self._build_budget()
        model_visible_sections = self._select_sections(
            model_sections,
            preview_messages,
            pressure_level=pressure_level,
            exact_durable_matches=exact_durable_matches,
            relevant_durable_matches=relevant_durable_matches,
            retrieval_evidence=retrieval_evidence,
            static_context=static_context,
            include_debug_trace=False,
        )
        debug_sections = self._select_sections(
            debug_source_sections,
            preview_messages,
            pressure_level=pressure_level,
            exact_durable_matches=exact_durable_matches,
            relevant_durable_matches=relevant_durable_matches,
            retrieval_evidence=retrieval_evidence,
            static_context=static_context,
            include_debug_trace=True,
        )
        selected_sections = [name for name, items in model_visible_sections.items() if items]
        debug_selected_sections = [name for name, items in debug_sections.items() if items]
        dropped_sections = self._dropped_sections_for_pressure(
            pressure_level,
            context_sections=model_visible_sections,
            has_warm=bool(model_visible_sections.get("warm_snapshots")),
            has_retrieval=bool(retrieval_evidence),
            has_durable=bool(exact_durable_matches or relevant_durable_matches),
        )
        compaction_decisions = self._decisions_for_pressure(pressure_level)
        token_accounting = self._token_accounting(
            tokens_before=tokens_before,
            compaction_view=compaction_view,
            sections=model_visible_sections,
            budget=budget,
        )

        return ContextPackage(
            pressure_level=pressure_level,
            budget=budget,
            sections=model_visible_sections,
            model_visible_sections=model_visible_sections,
            debug_sections=debug_sections,
            selected_sections=selected_sections,
            debug_selected_sections=debug_selected_sections,
            dropped_sections=dropped_sections,
            dropped_items=[],
            rebuild_reason=rebuild_reason,
            compaction_strategy="warning_only" if pressure_level == "warning" else pressure_level if pressure_level != "normal" else "none",
            compaction_decisions=compaction_decisions,
            token_accounting=token_accounting,
        )

    def _preview_content(self, messages: list[Message]) -> str:
        if messages:
            return self.session_memory_manager.update_from_messages(messages, persist=False)
        return self.session_memory_manager.load()

    def _build_budget(self) -> ContextBudget:
        available_context = self.compactor.effective_history_token_budget
        total = available_context + self.reserved_output_tokens
        static_budget = min(600, max(120, int(available_context * 0.08)))
        active_process_budget = min(1800, max(260, int(available_context * 0.24)))
        hot_truth_budget = min(2200, max(320, int(available_context * 0.3)))
        warm_budget = min(1100, max(180, int(available_context * 0.12)))
        durable_budget = min(1000, max(180, int(available_context * 0.1)))
        retrieval_budget = max(
            0,
            available_context
            - static_budget
            - active_process_budget
            - hot_truth_budget
            - warm_budget
            - durable_budget,
        )
        return ContextBudget(
            total=total,
            reserved_output=self.reserved_output_tokens,
            available_context=available_context,
            static=static_budget,
            active_process=active_process_budget,
            hot_truth=hot_truth_budget,
            warm_snapshots=warm_budget,
            durable=durable_budget,
            retrieval=retrieval_budget,
        )

    def _select_sections(
        self,
        parsed_sections: dict[str, list[str]],
        messages: list[Message],
        *,
        pressure_level: PressureLevel,
        exact_durable_matches: list[dict[str, Any]] | None,
        relevant_durable_matches: list[dict[str, Any]] | None,
        retrieval_evidence: list[str] | None,
        static_context: list[str] | None,
        include_debug_trace: bool,
    ) -> dict[str, list[str]]:
        active_process_headers = (
            [
                "# Active Goal",
                "# Flow State",
                "# Context Slots",
                "# Current Task State",
            ]
            if include_debug_trace
            else [
                "# Active Goal",
                "# Context Slots",
            ]
        )
        active_process_context = self._section_blocks(parsed_sections, active_process_headers)
        hot_truth_window = self._recent_truth_window(messages)
        persisted_snapshots = self.session_memory_manager.load_flow_snapshots()
        warm_snapshots = self._warm_snapshot_items(
            persisted_snapshots,
            fallback_blocks=self._section_blocks(parsed_sections, ["# Warm Context"]),
        )
        exact_durable_context = self._exact_durable_items(exact_durable_matches)
        relevant_durable_context = self._relevant_durable_items(
            relevant_durable_matches,
            exact_durable_matches=exact_durable_matches,
        )
        static_items = list(static_context or self.static_context)
        retrieval_items = self._retrieval_items(retrieval_evidence)
        debug_session_trace = self._debug_trace_blocks(parsed_sections) if include_debug_trace else []

        if pressure_level == "warning":
            warm_snapshots = self._limit_items_by_tokens(warm_snapshots, budget_tokens=max(80, self._budget_slice(0.5)))
            exact_durable_context = self._limit_items_by_tokens(
                exact_durable_context,
                budget_tokens=max(80, self._budget_slice(0.35)),
            )
            relevant_durable_context = self._limit_items_by_tokens(
                relevant_durable_context,
                budget_tokens=max(60, self._budget_slice(0.2)),
            )
        elif pressure_level == "microcompact":
            warm_snapshots = self._limit_items_by_tokens(warm_snapshots, budget_tokens=max(60, self._budget_slice(0.3)))
            exact_durable_context = self._limit_items_by_tokens(
                exact_durable_context,
                budget_tokens=max(60, self._budget_slice(0.16)),
            )
            relevant_durable_context = []
        elif pressure_level == "full_compact":
            warm_snapshots = []
            exact_durable_context = self._limit_items_by_tokens(
                exact_durable_context,
                budget_tokens=max(60, self._budget_slice(0.12)),
            )
            relevant_durable_context = []
            retrieval_items = self._limit_items_by_tokens(retrieval_items, budget_tokens=max(60, self._budget_slice(0.35)))

        return {
            "static_context": static_items,
            "active_process_context": active_process_context,
            "hot_truth_window": hot_truth_window,
            "retrieval_evidence": retrieval_items,
            "warm_snapshots": warm_snapshots,
            "exact_durable_context": exact_durable_context,
            "relevant_durable_context": relevant_durable_context,
            "debug_session_trace": debug_session_trace,
        }

    def _budget_slice(self, ratio: float) -> int:
        return max(1, int(self.compactor.effective_history_token_budget * ratio))

    def _section_blocks(
        self,
        parsed_sections: dict[str, list[str]],
        headers: list[str],
    ) -> list[str]:
        blocks: list[str] = []
        for header in headers:
            body = [
                line
                for line in parsed_sections.get(header, [])
                if line.strip() and not line.strip().startswith("_")
            ]
            if not body:
                continue
            blocks.append("\n".join([header, *body]).strip())
        return blocks

    def _recent_truth_window(self, messages: list[Message], *, limit: int = 4) -> list[str]:
        window = messages[-limit:]
        items: list[str] = []
        for message in window:
            content = self._sanitize_hot_truth_content(message.content, role=message.role)
            shortened = self._shorten(content, 180)
            if not shortened:
                continue
            items.append(f"{message.role}: {shortened}")
        return items

    def _sanitize_hot_truth_content(self, content: str, *, role: str) -> str:
        normalized = normalize_storage_text(str(content or ""))
        if not normalized:
            return ""
        if role != "assistant":
            return normalized
        cleaned = _HOT_TRUTH_TOOL_CALL_RE.sub("", normalized)
        cleaned = _HOT_TRUTH_THINK_RE.sub("", cleaned)
        cleaned = _HOT_TRUTH_TOOL_BLOCK_RE.sub("", cleaned)
        cleaned = _HOT_TRUTH_FENCED_JSON_RE.sub("", cleaned)
        lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
        return "\n".join(lines).strip()

    def _debug_trace_blocks(self, parsed_sections: dict[str, list[str]]) -> list[str]:
        debug_headers = [
            "# Key User Requests",
            "# Files and Functions",
            "# Conventions and Constraints",
            "# Errors and Corrections",
            "# Decisions and Learnings",
            "# Key Results",
            "# Risk Watch",
            "# Next Step",
            "# Worklog",
        ]
        return self._section_blocks(parsed_sections, debug_headers)

    def _warm_snapshot_items(
        self,
        snapshots: list[FlowSnapshot],
        *,
        fallback_blocks: list[str],
    ) -> list[str]:
        if not snapshots:
            return fallback_blocks
        items: list[str] = []
        for snapshot in snapshots[:3]:
            slot_parts = [f"{key}={value}" for key, value in snapshot.key_slots.items() if value]
            binding_part = ""
            if snapshot.binding_identity:
                binding_label = snapshot.binding_kind or "binding"
                binding_part = f" | binding={binding_label}:{snapshot.binding_identity}"
            owner_part = f" | owner={snapshot.binding_owner_task_id}" if snapshot.binding_owner_task_id else ""
            result_part = f" | recent result: {snapshot.recent_results[0]}" if snapshot.recent_results else ""
            hint_part = f" | resume hint: {snapshot.resume_hints[0]}" if snapshot.resume_hints else ""
            items.append(
                f"{snapshot.goal} | flow={snapshot.flow_type}"
                + binding_part
                + owner_part
                + (f" | restore candidates: {', '.join(slot_parts)}" if slot_parts else "")
                + result_part
                + hint_part
            )
        return self._dedupe(items)

    def _exact_durable_items(
        self,
        exact_durable_matches: list[dict[str, Any]] | None,
    ) -> list[str]:
        items: list[str] = []
        for match in exact_durable_matches or []:
            title = normalize_storage_text(str(match.get("title", "") or ""))
            if title:
                items.append(f"Exact durable memory: {title}")
        return self._dedupe(items)

    def _relevant_durable_items(
        self,
        relevant_durable_matches: list[dict[str, Any]] | None,
        *,
        exact_durable_matches: list[dict[str, Any]] | None,
    ) -> list[str]:
        items: list[str] = []
        exact_filenames = {
            normalize_storage_text(str(match.get("filename", "") or ""))
            for match in (exact_durable_matches or [])
            if normalize_storage_text(str(match.get("filename", "") or ""))
        }
        for note in relevant_durable_matches or []:
            filename = normalize_storage_text(str(note.get("filename", "") or ""))
            if filename and filename in exact_filenames:
                continue
            title = normalize_storage_text(str(note.get("title", "") or ""))
            if title:
                items.append(f"Relevant durable memory: {title}")
        return self._dedupe(items)

    def _retrieval_items(self, retrieval_evidence: list[str] | None) -> list[str]:
        return self._dedupe(
            [self._shorten(item, 180) for item in list(retrieval_evidence or []) if self._shorten(item, 180)]
        )

    def _limit_items_by_tokens(self, items: list[str], *, budget_tokens: int) -> list[str]:
        kept: list[str] = []
        used = 0
        for item in items:
            item_tokens = self.compactor.count_tokens(item)
            if kept and used + item_tokens > budget_tokens:
                break
            kept.append(item)
            used += item_tokens
        return kept

    def _dropped_sections_for_pressure(
        self,
        pressure_level: PressureLevel,
        *,
        context_sections: dict[str, list[str]],
        has_warm: bool,
        has_retrieval: bool,
        has_durable: bool,
    ) -> list[str]:
        dropped: list[str] = []
        if pressure_level == "warning":
            if has_warm and not context_sections.get("warm_snapshots"):
                dropped.append("warm_snapshots")
            if has_durable and not context_sections.get("relevant_durable_context"):
                dropped.append("relevant_durable_context")
        elif pressure_level == "microcompact":
            if has_durable:
                dropped.append("relevant_durable_context")
                if not context_sections.get("exact_durable_context"):
                    dropped.append("exact_durable_context")
            if has_warm and not context_sections.get("warm_snapshots"):
                dropped.append("warm_snapshots")
        elif pressure_level == "full_compact":
            if has_warm:
                dropped.append("warm_snapshots")
            if has_durable:
                if not context_sections.get("exact_durable_context"):
                    dropped.append("exact_durable_context")
                dropped.append("relevant_durable_context")
            if has_retrieval and not context_sections.get("retrieval_evidence"):
                dropped.append("retrieval_evidence")
        return self._dedupe(dropped)

    def _decisions_for_pressure(self, pressure_level: PressureLevel) -> list[str]:
        if pressure_level == "warning":
            return [
                "warning pressure: keep active-process context intact and trim warm layers first if pressure grows",
            ]
        if pressure_level == "microcompact":
            return [
                "microcompact pressure: preserve active-process context and replace bulky old outputs with placeholders",
            ]
        if pressure_level == "full_compact":
            return [
                "full compact pressure: preserve active-process context, keep a short hot-truth window, and restore through compaction_view.md",
            ]
        return ["normal pressure: include selected layers within budget"]

    def _token_accounting(
        self,
        *,
        tokens_before: int,
        compaction_view: str,
        sections: dict[str, list[str]],
        budget: ContextBudget,
    ) -> dict[str, int]:
        section_tokens = {
            name: sum(self.compactor.count_tokens(item) for item in items)
            for name, items in sections.items()
        }
        return {
            "estimated_tokens_before": tokens_before,
            "available_context": budget.available_context,
            "reserved_output": budget.reserved_output,
            "compaction_view_tokens": self.compactor.count_tokens(compaction_view),
            "static_tokens": section_tokens.get("static_context", 0),
            "active_process_tokens": section_tokens.get("active_process_context", 0),
            "hot_truth_tokens": section_tokens.get("hot_truth_window", 0),
            "retrieval_tokens": section_tokens.get("retrieval_evidence", 0),
            "warm_snapshot_tokens": section_tokens.get("warm_snapshots", 0),
            "exact_durable_tokens": section_tokens.get("exact_durable_context", 0),
            "relevant_durable_tokens": section_tokens.get("relevant_durable_context", 0),
            "durable_tokens": section_tokens.get("exact_durable_context", 0)
            + section_tokens.get("relevant_durable_context", 0),
        }

    def _shorten(self, text: str, limit: int) -> str:
        compact = re.sub(r"\s+", " ", normalize_storage_text(text)).strip()
        return compact[:limit] + ("..." if len(compact) > limit else "")

    def _dedupe(self, items: list[str]) -> list[str]:
        deduped: list[str] = []
        for item in items:
            cleaned = normalize_storage_text(item).strip()
            if cleaned and cleaned not in deduped:
                deduped.append(cleaned)
        return deduped
