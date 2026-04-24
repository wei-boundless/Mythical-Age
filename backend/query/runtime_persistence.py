from __future__ import annotations

from typing import Any

from query.output_boundary import sanitize_visible_assistant_content
from query.output_classifier import looks_like_procedural_promise_text, looks_like_tool_claim_without_receipt


class RuntimePersistenceAssembler:
    def __init__(self, *, hidden_skill_notice: str) -> None:
        self.hidden_skill_notice = hidden_skill_notice

    def is_internal_skill_read_tool_call(self, tool_call: dict[str, Any]) -> bool:
        tool_name = str(tool_call.get("tool", "") or "").strip().lower()
        raw = f"{tool_call.get('input', '')}\n{tool_call.get('output', '')}".lower()
        return tool_name == "read_file" and "skills/" in raw and "/skill.md" in raw

    def looks_like_skill_document(self, content: str) -> bool:
        normalized = content.strip()
        if not normalized:
            return False
        lowered = normalized.lower()
        has_skill_frontmatter = (
            (normalized.startswith("---") or lowered.startswith("name:"))
            and "metadata:" in lowered
            and "description:" in lowered
        )
        has_skill_sections = "display_name:" in lowered and (
            "## execution steps" in lowered
            or "## output format" in lowered
            or "目标" in normalized
            or "执行步骤" in normalized
            or "输出格式" in normalized
            or "故障排查" in normalized
            or "查询策略" in normalized
        )
        return has_skill_frontmatter or has_skill_sections

    def sanitize_tool_call(self, tool_call: dict[str, Any]) -> dict[str, Any] | None:
        if self.is_internal_skill_read_tool_call(tool_call):
            return None

        sanitized = {
            "tool": tool_call.get("tool", "tool"),
            "input": str(tool_call.get("input", "") or ""),
            "output": str(tool_call.get("output", "") or ""),
        }
        input_is_skill = self.looks_like_skill_document(sanitized["input"])
        output_is_skill = self.looks_like_skill_document(sanitized["output"])

        if (input_is_skill and not sanitized["output"].strip()) or (input_is_skill and output_is_skill):
            return None

        if input_is_skill:
            sanitized["input"] = self.hidden_skill_notice
        if output_is_skill:
            sanitized["output"] = self.hidden_skill_notice
        return sanitized

    def finalize_segments(
        self,
        segments: list[dict[str, Any]],
        current_segment: dict[str, Any],
        *,
        fallback_content: str = "",
    ) -> list[dict[str, Any]]:
        finalized = list(segments)
        candidate = {
            "content": current_segment.get("content", ""),
            "tool_calls": list(current_segment.get("tool_calls", [])),
        }
        if not str(candidate["content"]).strip() and fallback_content:
            candidate["content"] = fallback_content
        if str(candidate["content"]).strip() or candidate["tool_calls"]:
            finalized.append(candidate)
        return finalized

    def build_assistant_messages(
        self,
        segments: list[dict[str, Any]],
        *,
        canonical_content: str | None = None,
        answer_metadata: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        if canonical_content is not None:
            filtered_tool_calls = [
                sanitized
                for segment in segments
                for tool_call in (segment.get("tool_calls") or [])
                for sanitized in [self.sanitize_tool_call(tool_call)]
                if sanitized is not None
            ]
            content = sanitize_visible_assistant_content(canonical_content)
            content = self.apply_assistant_persistence_gate(content, filtered_tool_calls)
            if self.looks_like_skill_document(content) and not filtered_tool_calls:
                return []
            if not content.strip() and not filtered_tool_calls:
                return []
            return [
                {
                    "role": "assistant",
                    "content": content,
                    "tool_calls": filtered_tool_calls or None,
                    **dict(answer_metadata or {}),
                }
            ]

        persisted: list[dict[str, Any]] = []
        for segment in segments:
            filtered_tool_calls = [
                sanitized
                for tool_call in (segment.get("tool_calls") or [])
                for sanitized in [self.sanitize_tool_call(tool_call)]
                if sanitized is not None
            ]
            content = sanitize_visible_assistant_content(str(segment.get("content", "") or ""))
            content = self.apply_assistant_persistence_gate(content, filtered_tool_calls)
            if self.looks_like_skill_document(content) and not filtered_tool_calls:
                continue
            if not content.strip() and not filtered_tool_calls:
                continue
            persisted.append(
                {
                    "role": "assistant",
                    "content": content,
                    "tool_calls": filtered_tool_calls or None,
                    **dict(answer_metadata or {}),
                }
            )
        return persisted

    def assistant_metadata_from_done_event(self, event: dict[str, Any]) -> dict[str, Any]:
        answer_channel = str(event.get("answer_channel", "") or "").strip()
        answer_source = str(event.get("answer_source", "") or "").strip()
        fallback_reason = str(event.get("answer_fallback_reason", "") or "").strip()
        canonical_state = str(event.get("answer_canonical_state", "") or "").strip()
        persist_policy = str(event.get("answer_persist_policy", "") or "").strip()
        finalization_policy = str(event.get("answer_finalization_policy", "") or "").strip()

        if not canonical_state:
            if fallback_reason in {"no_receipt_query_promise", "no_receipt_tool_claim"}:
                canonical_state = "progress_only"
            elif answer_channel == "answer_candidate" or answer_source in {"memory_write_ack"}:
                canonical_state = "stable_answer"
            elif answer_channel == "fallback_answer":
                canonical_state = "missing_answer"

        if not persist_policy:
            if canonical_state in {"stable_answer", "tool_summary"}:
                persist_policy = "persist_canonical"
            elif canonical_state == "progress_only":
                persist_policy = "persist_debug_only"
            else:
                persist_policy = "do_not_persist"

        if not finalization_policy:
            if fallback_reason in {"rag_missing_answer", "pdf_missing_summary", "pdf_canonical_missing_summary"}:
                finalization_policy = "route_required"
            else:
                finalization_policy = "none"

        metadata: dict[str, Any] = {}
        if answer_channel:
            metadata["answer_channel"] = answer_channel
        if answer_source:
            metadata["answer_source"] = answer_source
        if canonical_state:
            metadata["answer_canonical_state"] = canonical_state
        if persist_policy:
            metadata["answer_persist_policy"] = persist_policy
        if finalization_policy:
            metadata["answer_finalization_policy"] = finalization_policy
        if fallback_reason:
            metadata["answer_fallback_reason"] = fallback_reason
        return metadata

    def apply_assistant_persistence_gate(
        self,
        content: str,
        tool_calls: list[dict[str, Any]],
    ) -> str:
        normalized = sanitize_visible_assistant_content(str(content or "")).strip()
        if not normalized:
            return ""
        if self.has_completed_tool_receipt(tool_calls):
            return normalized
        if looks_like_procedural_promise_text(normalized) or looks_like_tool_claim_without_receipt(normalized):
            return "当前还没有形成真实查询结果。"
        return normalized

    def has_completed_tool_receipt(self, tool_calls: list[dict[str, Any]]) -> bool:
        return any(str(tool_call.get("output", "") or "").strip() for tool_call in list(tool_calls or []))
